"""Unified portal pages — Prompts/39 §39.5 ``portal_repository`` / §39.6 rule 3.

Every source query is keyed by the caller's *own* identities (user id, own student + consented wards, their
enrolments, own library members, own staff row) — the same predicates as the modules' self resolvers, so no new
visibility rule is introduced and no scope parameter is honoured. Each source runs in its own SAVEPOINT: a module
whose tables are empty or whose feature is off contributes nothing instead of failing the page.

Sources of My requests: certificate requests (26), service desk (25), grievances (27), hostel leaves / complaints /
room change (20), no-dues (12), revaluation / photocopy (16), transcripts (16), credit transfers (07), library
reservations / ILL (19), mentoring bookings (27), scholarship applications (12), event registrations (25), room
bookings (25), data-subject requests (02).
"""

import functools
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog

from app.core.portals import PortalEntry
from app.enums.portals import normalise_status
from app.schemas.portals import (
    ApprovalItem,
    CalendarItem,
    MyCalendarOut,
    MyPaymentsOut,
    MyRequestsOut,
    PaymentTotals,
    PortalNavEntry,
    TimelineItem,
    UnifiedDocumentItem,
    UnifiedPaymentItem,
    UnifiedRequestItem,
)
from app.services.portals.common import PortalBase, persona_of

log = structlog.get_logger()

Ctx = dict[str, Any]

# (module, type, feature, sql, route template) — params: :i institution, :u user, :e enrolments, :s students, :m members
REQUEST_SOURCES: tuple[tuple[str, str, str | None, str, str], ...] = (
    (
        "documents",
        "certificate",
        "documents.certificate_requests",
        "SELECT id, NULL AS number, coalesce(template_type, 'certificate') || ' — ' || coalesce(purpose, '') AS title, "
        "status, created_at, CASE WHEN person_type = 'student' THEN person_id END AS student_id FROM certificate_requests "
        "WHERE institution_id = :i AND (requester_user_id = :u OR (person_type = 'student' AND person_id = ANY(:s)))",
        "{p}/documents",
    ),
    (
        "facilities",
        "service_request",
        "facilities.service_desk",
        "SELECT id, ticket_number AS number, category || ': ' || left(coalesce(description, ''), 80) AS title, status, "
        "created_at, NULL::uuid AS student_id FROM service_requests WHERE institution_id = :i AND requested_by = :u",
        "{p}/requests",
    ),
    (
        "grievances",
        "grievance",
        "grievances.core",
        "SELECT id, ticket_number AS number, 'Grievance: ' || category AS title, status, created_at, NULL::uuid AS student_id "
        "FROM grievances WHERE institution_id = :i AND (raised_by_user_id = :u OR "
        "(student_program_enrollment_id = ANY(:e) AND NOT is_anonymous))",
        "{p}/grievances",
    ),
    (
        "hostel",
        "hostel_leave",
        "hostel.leave_outpass",
        "SELECT h.id, NULL AS number, 'Out-pass: ' || h.leave_type || ' ' || to_char(h.from_at, 'DD Mon') AS title, "
        "h.status, h.created_at, e.student_id FROM hostel_leaves h JOIN student_program_enrollments e "
        "ON e.id = h.student_program_enrollment_id WHERE h.institution_id = :i AND h.student_program_enrollment_id = ANY(:e)",
        "{p}/hostel",
    ),
    (
        "hostel",
        "hostel_complaint",
        "hostel.complaints",
        "SELECT h.id, NULL AS number, 'Hostel complaint: ' || h.category AS title, h.status, h.created_at, e.student_id "
        "FROM hostel_complaints h JOIN student_program_enrollments e ON e.id = h.student_program_enrollment_id "
        "WHERE h.institution_id = :i AND h.student_program_enrollment_id = ANY(:e)",
        "{p}/hostel",
    ),
    (
        "hostel",
        "room_change",
        "hostel.room_change",
        "SELECT r.id, NULL AS number, 'Room change request' AS title, r.status, r.created_at, e.student_id "
        "FROM room_change_requests r JOIN hostel_allocations a ON a.id = r.allocation_id "
        "JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id "
        "WHERE r.institution_id = :i AND a.student_program_enrollment_id = ANY(:e)",
        "{p}/hostel",
    ),
    (
        "fees",
        "no_dues",
        "fees.no_dues",
        "SELECT n.id, NULL AS number, 'No-dues: ' || coalesce(n.purpose, '') AS title, n.status, n.requested_at AS created_at, "
        "e.student_id FROM no_dues_requests n JOIN student_program_enrollments e ON e.id = n.student_program_enrollment_id "
        "WHERE n.institution_id = :i AND n.student_program_enrollment_id = ANY(:e)",
        "{p}/fees",
    ),
    (
        "results",
        "revaluation",
        "results.revaluation",
        "SELECT r.id, NULL AS number, initcap(r.request_type) || ' request' AS title, r.status, r.created_at, e.student_id "
        "FROM reval_requests r JOIN exam_registration_items it ON it.id = r.exam_registration_item_id "
        "JOIN exam_registrations g ON g.id = it.exam_registration_id "
        "JOIN student_program_enrollments e ON e.id = g.student_program_enrollment_id "
        "WHERE r.institution_id = :i AND g.student_program_enrollment_id = ANY(:e)",
        "{p}/exams/reval",
    ),
    (
        "results",
        "transcript",
        "results.transcripts",
        "SELECT t.id, t.document_number AS number, initcap(t.transcript_type) || ' transcript' AS title, t.status, "
        "t.requested_at AS created_at, e.student_id FROM transcripts t JOIN student_program_enrollments e "
        "ON e.id = t.student_program_enrollment_id WHERE t.institution_id = :i AND t.student_program_enrollment_id = ANY(:e)",
        "{p}/transcripts",
    ),
    (
        "students",
        "credit_transfer",
        "academics.credit_transfer_mooc",
        "SELECT c.id, c.source_course_code AS number, 'Credit transfer: ' || coalesce(c.source_title, c.source) AS title, "
        "c.status, c.created_at, e.student_id FROM credit_transfers c JOIN student_program_enrollments e "
        "ON e.id = c.student_program_enrollment_id WHERE c.institution_id = :i AND c.student_program_enrollment_id = ANY(:e)",
        "{p}/credit-transfers",
    ),
    (
        "library",
        "reservation",
        "library.core",
        "SELECT r.id, NULL AS number, 'Book reservation' AS title, r.status, r.reserved_at AS created_at, "
        "NULL::uuid AS student_id FROM library_reservations r WHERE r.institution_id = :i AND r.member_id = ANY(:m)",
        "{p}/library",
    ),
    (
        "library",
        "ill_request",
        "library.core",
        "SELECT r.id, NULL AS number, 'Inter-library loan: ' || r.title AS title, r.status, r.requested_at AS created_at, "
        "NULL::uuid AS student_id FROM library_ill_requests r WHERE r.institution_id = :i AND r.member_id = ANY(:m)",
        "{p}/library",
    ),
    (
        "mentoring",
        "mentoring_booking",
        "mentoring.core",
        "SELECT b.id, NULL AS number, 'Mentor meeting ' || to_char(s.starts_at, 'DD Mon HH24:MI') AS title, b.status, "
        "b.created_at, e.student_id FROM mentoring_bookings b JOIN mentoring_slots s ON s.id = b.slot_id "
        "LEFT JOIN student_program_enrollments e ON e.id = b.student_program_enrollment_id "
        "WHERE b.institution_id = :i AND (b.student_program_enrollment_id = ANY(:e) OR b.guardian_user_id = :u)",
        "{p}/mentor",
    ),
    (
        "fees",
        "scholarship",
        "fees.scholarships",
        "SELECT a.id, a.external_ref AS number, 'Scholarship: ' || coalesce(sc.name, '') AS title, a.status, a.created_at, "
        "e.student_id FROM scholarship_applications a JOIN student_program_enrollments e "
        "ON e.id = a.student_program_enrollment_id LEFT JOIN scholarships sc ON sc.id = a.scholarship_id "
        "WHERE a.institution_id = :i AND a.student_program_enrollment_id = ANY(:e)",
        "{p}/fees",
    ),
    (
        "events",
        "event_registration",
        "events.core",
        "SELECT r.id, NULL AS number, 'Event: ' || ev.title AS title, "
        "CASE WHEN r.attended THEN 'attended' ELSE 'registered' END AS status, r.registered_at AS created_at, "
        "CASE WHEN r.person_type = 'student' THEN r.person_id END AS student_id FROM event_registrations r "
        "JOIN events ev ON ev.id = r.event_id WHERE r.institution_id = :i AND "
        "((r.person_type = 'student' AND r.person_id = ANY(:s)) OR (r.person_type = 'staff' AND r.person_id = :staff))",
        "{p}/calendar",
    ),
    (
        "facilities",
        "room_booking",
        "facilities.room_booking",
        "SELECT id, NULL AS number, 'Room booking: ' || coalesce(purpose, '') AS title, status, created_at, "
        "NULL::uuid AS student_id FROM room_bookings WHERE institution_id = :i AND requested_by = :u",
        "{p}/requests",
    ),
    (
        "privacy",
        "data_request",
        "privacy.data_subject_requests",
        "SELECT id, NULL AS number, 'Data request: ' || request_type AS title, status, created_at, NULL::uuid AS student_id "
        "FROM data_subject_requests WHERE institution_id = :i AND user_id = :u",
        "{p}/profile",
    ),
)

RAISE_NEW: tuple[PortalEntry, ...] = (
    PortalEntry("certificate", "{p}/documents?new=certificate", "file-plus", "documents.certificate_requests"),
    PortalEntry("grievance", "{p}/grievances?new=1", "alert-circle", "grievances.core"),
    PortalEntry("outpass", "{p}/hostel?new=leave", "log-out", "hostel.leave_outpass"),
    PortalEntry("reval", "{p}/exams/reval?new=1", "rotate-ccw", "results.revaluation"),
    PortalEntry("transcript", "{p}/transcripts?new=1", "scroll", "results.transcripts"),
    PortalEntry("service_request", "{p}/requests?new=service", "wrench", "facilities.service_desk"),
)


class PortalAggregator(PortalBase):
    def prefix(self) -> str:
        from app.enums.portals import PERSONA_HOME

        return PERSONA_HOME.get(persona_of(self.principal) or "student", "/student")

    async def _ids(self) -> Ctx:
        students = await self.subject_student_ids()
        members = await self.rows(
            "SELECT id FROM library_members WHERE institution_id = :i AND user_id = :u", u=self.principal.id
        )
        return {
            "u": self.principal.id,
            "s": students,
            "e": await self.enrollment_ids(students),
            "m": [m["id"] for m in members],
            "staff": await self.own_staff_id() or uuid.UUID(int=0),
        }

    async def _safe(self, label: str, fn: Callable[[], Awaitable[list[dict[str, Any]]]]) -> list[dict[str, Any]]:
        try:
            async with self.db.begin_nested():
                return await fn()
        except Exception as exc:  # noqa: BLE001 - one module never breaks the unified page
            log.warning("portal_source_failed", source=label, error=str(exc)[:200])
            return []

    # ---- My requests ----------------------------------------------------------------------------------------------
    async def my_requests(
        self, status: str | None, module: str | None, date_from: date | None, date_to: date | None
    ) -> MyRequestsOut:
        ids = await self._ids()
        p = self.prefix()
        items: list[UnifiedRequestItem] = []
        for mod, typ, feature, sql, route in REQUEST_SOURCES:
            if module and mod != module:
                continue
            if feature and not self.principal.has_feature(feature):
                continue
            rows = await self._safe(typ, functools.partial(self.rows, sql, **ids))
            for r in rows:
                items.append(
                    UnifiedRequestItem(
                        source_module=mod,
                        type=typ,
                        id=r["id"],
                        number=r.get("number"),
                        title=(r.get("title") or typ.replace("_", " ").title())[:200],
                        status=normalise_status(r.get("status")),
                        raw_status=r.get("status"),
                        created_at=r.get("created_at"),
                        route=route.format(p=p),
                        student_id=r.get("student_id"),
                    )
                )
        if status:
            items = [i for i in items if i.status == status]
        if date_from:
            items = [i for i in items if i.created_at is None or i.created_at.date() >= date_from]
        if date_to:
            items = [i for i in items if i.created_at is None or i.created_at.date() <= date_to]
        items.sort(key=lambda i: i.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        launchers = [
            PortalNavEntry(**{**e.as_dict(), "route": e.route.format(p=p)})
            for e in RAISE_NEW
            if not e.feature or self.principal.has_feature(e.feature)
        ]
        return MyRequestsOut(
            items=items,
            by_status=dict(Counter(i.status for i in items)),
            by_module=dict(Counter(i.source_module for i in items)),
            launchers=launchers,
        )

    # ---- My documents ---------------------------------------------------------------------------------------------
    async def my_documents(self) -> list[UnifiedDocumentItem]:
        ids = await self._ids()
        persona = persona_of(self.principal)
        people: list[tuple[str, uuid.UUID]] = [("student", s) for s in ids["s"]]
        if ids["staff"].int:
            people.append(("staff", ids["staff"]))
        alumni = await self.rows(
            "SELECT id FROM alumni_profiles WHERE institution_id = :i AND student_id = ANY(:s)", s=ids["s"]
        )
        people += [("alumni", a["id"]) for a in alumni]
        if not people:
            return []
        sql = (
            "SELECT id, template_type, document_number, person_type, person_id, issued_at, verification_token "
            "FROM issued_documents WHERE institution_id = :i AND revoked_at IS NULL AND ("
            + " OR ".join(f"(person_type = :t{n} AND person_id = :p{n})" for n in range(len(people)))
            + ")"
        )
        if persona == "evaluator":  # §39.11 step 10: an external examiner sees remuneration slips only
            sql += " AND template_type ILIKE '%remuneration%'"
        params: dict[str, Any] = {}
        for n, (t, pid) in enumerate(people):
            params[f"t{n}"], params[f"p{n}"] = t, pid
        rows = await self._safe("documents", lambda: self.rows(sql + " ORDER BY issued_at DESC LIMIT 500", **params))
        return [
            UnifiedDocumentItem(
                id=r["id"],
                template_type=r["template_type"],
                document_number=r["document_number"],
                title=(r["template_type"] or "document").replace("_", " ").title(),
                person_type=r["person_type"],
                person_id=r["person_id"],
                issued_at=r["issued_at"],
                verification_token=r["verification_token"],
                verify_url=f"/verify/{r['verification_token']}" if r["verification_token"] else None,
                download_route=f"/api/v1/documents/issued/{r['id']}/signed-link",
            )
            for r in rows
        ]

    # ---- My payments ----------------------------------------------------------------------------------------------
    async def my_payments(self, date_from: date | None, date_to: date | None, status: str | None) -> MyPaymentsOut:
        ids = await self._ids()
        f = date_from or (datetime.now(UTC).date() - timedelta(days=730))
        t = date_to or (datetime.now(UTC).date() + timedelta(days=1))
        payer = (
            "(i.payer_type = 'student' AND i.payer_id = ANY(:s)) OR i.student_program_enrollment_id = ANY(:e) "
            "OR (i.payer_type = 'staff' AND i.payer_id = :staff) OR (i.payer_type = 'user' AND i.payer_id = :u)"
        )
        common = {**ids, "f": f, "t": t}
        inv = await self._safe(
            "invoices",
            lambda: self.rows(
                "SELECT i.id, i.invoice_number, i.source_type, i.description, i.total_paise, i.balance_paise, i.status, "
                "i.created_at, i.due_date, i.payer_id, e.student_id FROM fee_invoices i "
                "LEFT JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id "
                f"WHERE i.institution_id = :i AND ({payer}) AND i.created_at::date BETWEEN :f AND :t "
                "AND i.cancelled_at IS NULL ORDER BY i.created_at DESC LIMIT 500",
                **common,
            ),
        )
        pays = await self._safe(
            "payments",
            lambda: self.rows(
                "SELECT p.id, p.receipt_number, i.source_type, p.amount_paise, p.status, p.payment_date, p.receipt_url, "
                "e.student_id FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id "
                "LEFT JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id "
                f"WHERE p.institution_id = :i AND ({payer}) AND p.payment_date BETWEEN :f AND :t "
                "ORDER BY p.payment_date DESC LIMIT 500",
                **common,
            ),
        )
        refs = await self._safe(
            "refunds",
            lambda: self.rows(
                "SELECT r.id, i.invoice_number, i.source_type, r.amount_paise, r.status, r.created_at, e.student_id "
                "FROM fee_refunds r JOIN fee_invoices i ON i.id = r.invoice_id "
                "LEFT JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id "
                f"WHERE r.institution_id = :i AND ({payer}) AND r.created_at::date BETWEEN :f AND :t "
                "ORDER BY r.created_at DESC LIMIT 200",
                **common,
            ),
        )
        invoices = [
            UnifiedPaymentItem(
                kind="invoice",
                id=r["id"],
                number=r["invoice_number"],
                source_type=r["source_type"],
                description=r["description"],
                amount_paise=int(r["total_paise"] or 0),
                balance_paise=int(r["balance_paise"] or 0),
                status=r["status"],
                at=r["created_at"],
                due_date=r["due_date"],
                payable=int(r["balance_paise"] or 0) > 0 and r["status"] not in ("cancelled", "paid"),
                student_id=r["student_id"],
            )
            for r in inv
        ]
        if status:
            invoices = [i for i in invoices if i.status == status]
        payments = [
            UnifiedPaymentItem(
                kind="payment",
                id=r["id"],
                number=r["receipt_number"],
                source_type=r["source_type"],
                amount_paise=int(r["amount_paise"] or 0),
                status=r["status"],
                at=r["payment_date"],
                student_id=r["student_id"],
                receipt_url=r["receipt_url"],
            )
            for r in pays
        ]
        refunds = [
            UnifiedPaymentItem(
                kind="refund",
                id=r["id"],
                number=r["invoice_number"],
                source_type=r["source_type"],
                amount_paise=int(r["amount_paise"] or 0),
                status=r["status"],
                at=r["created_at"],
                student_id=r["student_id"],
            )
            for r in refs
        ]
        totals = PaymentTotals(
            invoiced_paise=sum(i.amount_paise for i in invoices),
            balance_paise=sum(i.balance_paise or 0 for i in invoices),
            paid_paise=sum(p.amount_paise for p in payments if p.status in ("success", "captured", "paid", "settled")),
            refunded_paise=sum(r.amount_paise for r in refunds if r.status in ("processed", "completed", "paid")),
        )
        return MyPaymentsOut(invoices=invoices, payments=payments, refunds=refunds, totals=totals)

    # ---- My approvals (Phase 04 inbox, own steps only) ----------------------------------------------------------
    async def my_approvals(self) -> list[ApprovalItem]:
        rows = await self.rows(
            "SELECT s.id AS step_id, s.instance_id, s.step_order, s.sla_due_at, s.created_at, w.entity_type, w.entity_id, "
            "w.title, d.name AS workflow FROM workflow_steps s JOIN workflow_instances w ON w.id = s.instance_id "
            "JOIN workflow_definitions d ON d.id = w.definition_id WHERE s.institution_id = :i AND s.status = 'pending' "
            "AND w.status IN ('pending', 'in_progress') AND w.current_step = s.step_order "
            "AND (s.approver_user_id = :u OR s.escalated_to = :u) ORDER BY s.sla_due_at NULLS LAST, s.created_at LIMIT 200",
            u=self.principal.id,
        )
        return [
            ApprovalItem(
                step_id=r["step_id"],
                instance_id=r["instance_id"],
                workflow=r["workflow"],
                entity_type=r["entity_type"],
                entity_id=r["entity_id"],
                title=r["title"] or (r["workflow"] or "Approval"),
                step_order=r["step_order"],
                sla_due_at=r["sla_due_at"],
                created_at=r["created_at"],
                route=f"/approvals/{r['instance_id']}",
            )
            for r in rows
        ]

    # ---- My calendar (Phase 25 personal view) --------------------------------------------------------------------
    async def my_calendar(self, date_from: datetime | None, date_to: datetime | None) -> MyCalendarOut:
        from app.services.facilities.calendar_service import CalendarService

        items: list[CalendarItem] = []
        if self.principal.has_feature("calendar.core"):
            try:
                async with self.db.begin_nested():
                    view = await CalendarService(self.db, self.principal, self.request).view(
                        date_from, date_to, None, None, "mine"
                    )
                items = [
                    CalendarItem(
                        id=i.key, title=i.title, start=i.starts_at, end=i.ends_at, kind=i.event_type, route=None
                    )
                    for i in view.items
                ]
            except Exception as exc:  # noqa: BLE001
                log.warning("portal_calendar_failed", error=str(exc)[:200])
        token = await self.rows(
            "SELECT 1 FROM calendar_feed_tokens WHERE institution_id = :i AND user_id = :u LIMIT 1", u=self.principal.id
        )
        return MyCalendarOut(items=items, subscribe_url="/calendar/feed-token" if token else None)

    # ---- My timeline (last 90 days) ------------------------------------------------------------------------------
    async def my_timeline(self, date_from: date | None) -> list[TimelineItem]:
        since = date_from or (datetime.now(UTC).date() - timedelta(days=90))
        ids = await self._ids()
        audit = await self._safe(
            "timeline_audit",
            lambda: self.rows(
                "SELECT created_at AS at, module, action, record_type FROM audit_logs WHERE institution_id = :i "
                "AND created_at >= :f AND (user_id = :u OR (record_type = 'student' AND record_id = ANY(:s))) "
                "AND action NOT IN ('view', 'view_pii', 'login', 'refresh') ORDER BY created_at DESC LIMIT 200",
                f=since,
                **ids,
            ),
        )
        notes = await self.rows(
            "SELECT created_at AS at, category, title, link->>'route' AS route FROM notifications "
            "WHERE user_id = :u AND created_at >= :f ORDER BY created_at DESC LIMIT 200",
            u=self.principal.id,
            f=since,
        )
        out = [
            TimelineItem(
                at=r["at"],
                kind=f"{r['module']}.{r['action']}",
                title=f"{(r['record_type'] or r['module']).replace('_', ' ').title()} {r['action'].replace('_', ' ')}",
                module=r["module"],
            )
            for r in audit
        ] + [
            TimelineItem(
                at=r["at"], kind=f"notification.{r['category'] or 'system'}", title=r["title"], route=r["route"]
            )
            for r in notes
        ]
        out.sort(key=lambda x: x.at, reverse=True)
        return out[:300]
