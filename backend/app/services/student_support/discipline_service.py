"""Discipline — Prompts/27 §27.6 ``discipline_service`` ({discipline.core}).

1. Cases for students (``subject_id`` = enrolment) or staff from reports (manual, hostel discipline events, exam
   malpractice referrals, false SOS, placement violations — ``source``); ``case_number`` from
   ``number_sequences('disc_case')``; inquiry (committee, notice to the subject + guardians), statement through the
   portal, hearing scheduling; decision by the committee (``discipline:decide`` or a member / chair of the case's
   committee) with sanctions. ``suspension`` / ``expulsion`` need the principal: workflow ``discipline.case`` and the
   effects apply on approval; other sanctions apply at once:
   ``warning`` (record) · ``fine`` (Phase 12 linkage invoice ``source_type='discipline_fine'``) · ``suspension``
   (hold ``all`` for the period, attendance policy ``discipline.suspension_attendance`` and an LMS access flag in the
   ``discipline.sanction_applied`` event) · ``community_service`` (hours target, consumed from ``activity_hours``) ·
   ``hostel_eviction`` / ``debar_placement`` (events for Phases 20 / 28) · ``expulsion`` (enrolment ``expelled`` +
   hold ``all``; staff → ``hr.disciplinary_action``). The decision letter is rendered through Phase 26
   ``documents.render('custom', 'disciplinary_case', id)``.
2. Appeal within ``discipline.sanction_scale.appeal_window_days`` → workflow ``discipline.appeal``; the appellate
   authority (``discipline:appeal``) upholds / modifies / revokes with reversal effects (fine cancelled, holds
   released); the case closes. Register export for statutory returns and counts for Phase 32.
"""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, false, func, or_, select, true

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.enums.student_support import DEFAULT_SANCTION_SCALE, SEVERE_SANCTIONS
from app.models.discipline import DisciplinaryCase
from app.models.fees import FeeInvoice
from app.models.hr import Staff
from app.models.platform import WorkflowInstance
from app.models.post_result import Committee
from app.models.students import StudentHold, StudentProgramEnrollment
from app.schemas.discipline import (
    DiscAppealCreate,
    DiscAppealDecision,
    DiscCaseCreate,
    DiscCaseOut,
    DiscDecision,
    DiscHearing,
    DiscInquiry,
    DiscNotice,
    DiscRegisterRow,
    DiscStatement,
)
from app.services.documents.render_service import RenderService, register_resolver
from app.services.student_support.common import (
    SupportBase,
    all_access,
    dept_subquery,
    forbidden,
    module_reader,
    not_found,
    now_utc,
    rule,
    scope_ids,
)


class DisciplineService(SupportBase):
    audit_module = "discipline"
    module = "discipline"

    # ---- visibility -----------------------------------------------------------------------------------------------------
    async def _subject_self(self) -> list[Any]:
        parts: list[Any] = []
        ids = await self.my_enrollment_ids()
        if ids:
            parts.append(and_(DisciplinaryCase.subject_type == "student", DisciplinaryCase.subject_id.in_(ids)))
        staff_id = await self.my_staff_id()
        if staff_id is not None:
            parts.append(and_(DisciplinaryCase.subject_type == "staff", DisciplinaryCase.subject_id == staff_id))
        wards = await self.ward_enrollment_ids()
        if wards:
            parts.append(and_(DisciplinaryCase.subject_type == "student", DisciplinaryCase.subject_id.in_(wards)))
        return parts

    async def _visible(self, scope: str | None = None) -> Any:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return true()
        if scope in (None, "all") and all_access(p, self.module):
            return true()
        parts: list[Any] = []
        if scope in (None, "self", "mine"):
            parts += await self._subject_self()
        if scope in (None, "own", "committee"):
            committees = await self.my_committee_ids()
            if committees:
                parts.append(DisciplinaryCase.committee_id.in_(committees))
            parts.append(DisciplinaryCase.reported_by == self.actor_id)
        units = scope_ids(p, "department") or scope_ids(p, "faculty")
        if scope in (None, "department") and units and module_reader(p, self.module):
            depts = dept_subquery(p)
            parts.append(
                or_(
                    and_(
                        DisciplinaryCase.subject_type == "student",
                        DisciplinaryCase.subject_id.in_(
                            select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id.in_(depts))
                        ),
                    ),
                    and_(
                        DisciplinaryCase.subject_type == "staff",
                        DisciplinaryCase.subject_id.in_(select(Staff.id).where(Staff.department_id.in_(depts))),
                    ),
                )
            )
        if scope in (None, "college") and scope_ids(p, "college") and module_reader(p, self.module):
            cols = scope_ids(p, "college")
            parts.append(
                or_(
                    and_(
                        DisciplinaryCase.subject_type == "student",
                        DisciplinaryCase.subject_id.in_(
                            select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.college_id.in_(cols))
                        ),
                    ),
                    and_(
                        DisciplinaryCase.subject_type == "staff",
                        DisciplinaryCase.subject_id.in_(select(Staff.id).where(Staff.college_id.in_(cols))),
                    ),
                )
            )
        return or_(*parts) if parts else false()

    async def _get(self, cid: uuid.UUID, *, lock: bool = False) -> DisciplinaryCase:
        stmt = select(DisciplinaryCase).where(
            DisciplinaryCase.id == cid, DisciplinaryCase.institution_id == self.inst, await self._visible()
        )
        if lock:
            stmt = stmt.with_for_update()
        c = (await self.db.execute(stmt)).scalar_one_or_none()
        if c is None:
            raise not_found("Case")
        return c

    async def _raw(self, cid: uuid.UUID) -> DisciplinaryCase:
        c = (
            await self.db.execute(select(DisciplinaryCase).where(DisciplinaryCase.id == cid).with_for_update())
        ).scalar_one_or_none()
        if c is None:
            raise not_found("Case")
        return c

    async def _is_subject(self, c: DisciplinaryCase) -> bool:
        if c.subject_type == "student":
            return c.subject_id in await self.my_enrollment_ids()
        return c.subject_id == await self.my_staff_id()

    async def _is_committee(self, c: DisciplinaryCase) -> bool:
        return c.committee_id is not None and c.committee_id in await self.my_committee_ids()

    def _manager(self) -> bool:
        return self.can("discipline", "manage") and not self._auditor()

    def _auditor(self) -> bool:
        from app.services.student_support.common import is_auditor

        return is_auditor(self.principal)

    # ---- output ---------------------------------------------------------------------------------------------------------
    async def _subject_info(self, rows: list[DisciplinaryCase]) -> dict[uuid.UUID, dict[str, Any]]:
        students = await self.enrollment_cards([r.subject_id for r in rows if r.subject_type == "student"])
        staff = await self.staff_cards([r.subject_id for r in rows if r.subject_type == "staff"])
        out: dict[uuid.UUID, dict[str, Any]] = {}
        for k, v in students.items():
            out[k] = {"name": v.get("name"), "department_id": v.get("department_id"), "user_id": v.get("user_id")}
        for k, v in staff.items():
            out[k] = {"name": v.get("name"), "department_id": v.get("department_id"), "user_id": v.get("user_id")}
        return out

    async def outs(self, rows: list[DisciplinaryCase], *, detail: bool = False) -> list[DiscCaseOut]:
        info = await self._subject_info(rows)
        comms = {
            c.id: c.name
            for c in (
                await self.db.execute(
                    select(Committee).where(
                        Committee.id.in_([r.committee_id for r in rows if r.committee_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        out = []
        for r in rows:
            ev = r.evidence or {}
            i = info.get(r.subject_id, {})
            o = DiscCaseOut(
                id=r.id,
                case_number=r.case_number,
                subject_type=r.subject_type,
                subject_id=r.subject_id,
                subject_name=i.get("name"),
                department_id=i.get("department_id"),
                category=r.category,
                description=r.description if detail else (r.description or "")[:200],
                status=r.status,
                committee_id=r.committee_id,
                committee_name=comms.get(r.committee_id) if r.committee_id else None,
                hearing_at=r.hearing_at,
                sanctions=list(r.sanctions or []),
                fee_invoice_id=r.fee_invoice_id,
                appeal_status=r.appeal_status,
                decided_at=r.decided_at,
                source=ev.get("source"),
                created_at=r.created_at,
            )
            if detail:
                o.effects = list(ev.get("effects") or [])
                o.appeal = ev.get("appeal")
                o.decision_text = ev.get("decision_text")
                doc = ev.get("decision_document_id")
                o.decision_document_id = uuid.UUID(doc) if doc else None
                o.evidence = list(ev.get("items") or [])
                o.notices = list(ev.get("notices") or [])
                o.statements = list(ev.get("statements") or [])
                o.hearings = list(ev.get("hearings") or [])
                o.timeline = list(ev.get("timeline") or [])
                wf = ev.get("workflow_instance_id")
                o.workflow_instance_id = uuid.UUID(wf) if wf else None
                o.is_subject = await self._is_subject(r)
                o.can_appeal = o.is_subject and await self._appeal_open(r)
            out.append(o)
        return out

    async def _appeal_open(self, c: DisciplinaryCase) -> bool:
        if c.status != "decided" or c.appeal_status or c.decided_at is None:
            return False
        scale = await self.setting("discipline", "sanction_scale")
        days = int((scale if isinstance(scale, dict) else DEFAULT_SANCTION_SCALE).get("appeal_window_days") or 15)
        return now_utc() <= c.decided_at + timedelta(days=days)

    def _ev(self, c: DisciplinaryCase) -> dict[str, Any]:
        return dict(c.evidence or {})

    def _tl(self, ev: dict[str, Any], action: str, **extra: Any) -> None:
        tl = list(ev.get("timeline") or [])
        tl.append(
            {
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
                "action": action,
                **extra,
            }
        )
        ev["timeline"] = tl

    async def _subject_users(self, c: DisciplinaryCase, *, guardians: bool = True) -> list[uuid.UUID | None]:
        info = (await self._subject_info([c])).get(c.subject_id, {})
        users: list[uuid.UUID | None] = [info.get("user_id")]
        if c.subject_type == "student" and guardians:
            users += await self.guardian_users(c.subject_id)
        return users

    # ---- create ---------------------------------------------------------------------------------------------------------
    async def create(self, body: DiscCaseCreate, *, system: bool = False) -> DiscCaseOut:
        if not system:
            self.require_writer()
            if not (self._manager() or self.can("discipline", "create")):
                raise forbidden("discipline:manage required")
        if body.subject_type == "student":
            await self.enrollment(body.subject_id)
        elif (await self.db.execute(select(Staff.id).where(Staff.id == body.subject_id))).scalar_one_or_none() is None:
            raise not_found("Staff member")
        if body.source and body.source.id:
            dup = (
                await self.db.execute(
                    select(DisciplinaryCase).where(
                        DisciplinaryCase.institution_id == self.inst,
                        DisciplinaryCase.evidence["source"]["id"].astext == str(body.source.id),
                    )
                )
            ).scalar_one_or_none()
            if dup is not None:
                return (await self.outs([dup], detail=True))[0]
        ev: dict[str, Any] = {
            "items": [e.model_dump() for e in body.evidence],
            "source": body.source.model_dump(mode="json") if body.source else {"type": "manual", "id": None},
        }
        self._tl(ev, "reported")
        c = DisciplinaryCase(
            institution_id=self.inst,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            case_number=(await self.sequence("disc_case", "DC")).upper(),
            category=body.category,
            description=body.description,
            evidence=ev,
            reported_by=self.actor_id,
            status="reported",
        )
        self.db.add(c)
        await self.db.flush()
        await self._emit(
            "discipline.case_reported",
            {"case_id": str(c.id), "subject_type": c.subject_type, "source": ev["source"].get("type")},
            "disciplinary_case",
            c.id,
        )
        await self._audit(
            "report", "disciplinary_case", c.id, None, {"subject_type": c.subject_type, "category": c.category}
        )
        return (await self.outs([c], detail=True))[0]

    # ---- inquiry / notice / hearing / statement ------------------------------------------------------------------------
    async def inquiry(self, cid: uuid.UUID, body: DiscInquiry) -> DiscCaseOut:
        self.require_writer()
        c = await self._get(cid, lock=True)
        if not (self._manager() or await self._is_committee(c)):
            raise forbidden("discipline:manage required")
        if c.status not in ("reported", "inquiry"):
            raise rule(f"A {c.status} case cannot move to inquiry", "BAD_STATUS")
        com = (
            await self.db.execute(
                select(Committee).where(Committee.id == body.committee_id, Committee.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if com is None:
            raise not_found("Committee")
        ev = self._ev(c)
        c.committee_id, c.status = com.id, "inquiry"
        if body.hearing_at:
            c.hearing_at = body.hearing_at
        self._tl(ev, "inquiry", committee_id=str(com.id))
        if body.notice_text:
            ev.setdefault("notices", []).append({"at": now_utc().isoformat(), "text": body.notice_text})
        c.evidence = ev
        await self.db.flush()
        await self._emit(
            "discipline.inquiry", {"case_id": str(c.id), "committee_id": str(com.id)}, "disciplinary_case", c.id
        )
        await self._notify(
            "discipline.notice",
            await self.committee_user_ids(com.id),
            {"case_number": c.case_number, "message": "A case was referred to your committee"},
        )
        if body.notice_text:
            await self._notify(
                "discipline.notice",
                await self._subject_users(c),
                {"case_number": c.case_number, "message": body.notice_text},
            )
        return (await self.outs([c], detail=True))[0]

    async def notice(self, cid: uuid.UUID, body: DiscNotice) -> DiscCaseOut:
        self.require_writer()
        c = await self._get(cid, lock=True)
        if not (self._manager() or await self._is_committee(c)):
            raise forbidden("discipline:manage required")
        ev = self._ev(c)
        ev.setdefault("notices", []).append(
            {
                "at": now_utc().isoformat(),
                "text": body.notice_text,
                "respond_by": body.respond_by.isoformat() if body.respond_by else None,
            }
        )
        self._tl(ev, "notice")
        c.evidence = ev
        await self.db.flush()
        await self._notify(
            "discipline.notice",
            await self._subject_users(c),
            {"case_number": c.case_number, "message": body.notice_text},
        )
        return (await self.outs([c], detail=True))[0]

    async def hearing(self, cid: uuid.UUID, body: DiscHearing) -> DiscCaseOut:
        self.require_writer()
        c = await self._get(cid, lock=True)
        if not (self._manager() or await self._is_committee(c)):
            raise forbidden("discipline:manage required")
        if c.status not in ("inquiry", "hearing", "reported"):
            raise rule(f"A {c.status} case cannot schedule a hearing", "BAD_STATUS")
        ev = self._ev(c)
        ev.setdefault("hearings", []).append(
            {
                "at": body.hearing_at.isoformat(),
                "venue": body.venue,
                "attendees": body.attendees,
                "minutes": body.minutes,
                "recorded_at": now_utc().isoformat(),
            }
        )
        self._tl(ev, "hearing", hearing_at=body.hearing_at.isoformat())
        c.evidence, c.hearing_at, c.status = ev, body.hearing_at, "hearing"
        await self.db.flush()
        await self._emit("discipline.hearing", {"case_id": str(c.id)}, "disciplinary_case", c.id)
        await self._notify(
            "discipline.hearing",
            await self._subject_users(c),
            {"case_number": c.case_number, "hearing_at": body.hearing_at.strftime("%d %b %Y %H:%M")},
        )
        return (await self.outs([c], detail=True))[0]

    async def statement(self, cid: uuid.UUID, body: DiscStatement) -> DiscCaseOut:
        c = await self._get(cid, lock=True)
        if not await self._is_subject(c):
            raise not_found("Case")
        if c.status in ("decided", "closed", "appealed"):
            raise rule("Statements are taken before the decision", "BAD_STATUS")
        ev = self._ev(c)
        ev.setdefault("statements", []).append(
            {"at": now_utc().isoformat(), "text": body.text, "attachments": [a.model_dump() for a in body.attachments]}
        )
        self._tl(ev, "statement")
        c.evidence = ev
        await self.db.flush()
        await self._notify(
            "discipline.notice",
            await self.committee_user_ids(c.committee_id),
            {"case_number": c.case_number, "message": "The subject submitted a statement"},
        )
        return (await self.outs([c], detail=True))[0]

    # ---- decision -------------------------------------------------------------------------------------------------------
    async def decide(self, cid: uuid.UUID, body: DiscDecision) -> DiscCaseOut:
        self.require_writer()
        c = await self._get(cid, lock=True)
        if not (self.can("discipline", "decide") and (await self._is_committee(c) or self._manager())):
            raise forbidden("discipline:decide (committee) required")
        if c.status not in ("inquiry", "hearing", "reported"):
            raise rule(f"A {c.status} case cannot be decided", "BAD_STATUS")
        scale = await self.setting("discipline", "sanction_scale")
        max_fine = int((scale if isinstance(scale, dict) else DEFAULT_SANCTION_SCALE).get("max_fine_paise") or 0)
        for s in body.sanctions:
            if s.type == "fine" and (not s.amount_paise or (max_fine and s.amount_paise > max_fine)):
                raise rule("A fine needs an amount within the sanction scale", "BAD_FINE")
            if s.type == "suspension" and not (s.from_on and s.to_on and s.to_on >= s.from_on):
                raise rule("A suspension needs from_on ≤ to_on", "BAD_DATES")
            if c.subject_type == "staff" and s.type in ("hostel_eviction", "debar_placement", "community_service"):
                raise rule(f"{s.type} applies to students only", "BAD_SANCTION")
        ev = self._ev(c)
        ev["decision_text"] = body.decision_text
        c.sanctions = [s.model_dump(mode="json") for s in body.sanctions]
        c.decided_by = self.actor_id
        severe = any(s.type in SEVERE_SANCTIONS for s in body.sanctions)
        if severe:
            com = (
                (await self.db.execute(select(Committee).where(Committee.id == c.committee_id))).scalar_one_or_none()
                if c.committee_id
                else None
            )
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="discipline.case",
                entity_type="disciplinary_case",
                entity_id=c.id,
                started_by=self.actor_id,
                context={
                    "chair_user_id": str(await self.staff_user(com.chair_staff_id))
                    if com and com.chair_staff_id
                    else None,
                    "sanctions": [s.type for s in body.sanctions],
                },
                title=f"Discipline {c.case_number} — principal approval"[:200],
            )
            ev["workflow_instance_id"] = str(wf.id)
            self._tl(ev, "decision_proposed", sanctions=[s.type for s in body.sanctions])
            c.evidence = ev
            await self.db.flush()
            await self._audit("propose", "disciplinary_case", c.id, None, {"sanctions": c.sanctions})
        else:
            self._tl(ev, "decided", sanctions=[s.type for s in body.sanctions])
            c.evidence = ev
            await self.apply_decision(c)
        return (await self.outs([c], detail=True))[0]

    async def apply_decision(self, c: DisciplinaryCase) -> None:
        """Apply the sanctions' effects (decision approved / non-severe) and issue the decision letter."""
        c.status, c.decided_at = "decided", now_utc()
        ev = self._ev(c)
        effects = list(ev.get("effects") or [])
        for s in list(c.sanctions or []):
            effects.append(await self._apply(c, s))
        ev["effects"] = effects
        c.evidence = ev
        await self.db.flush()
        doc = await self._letter(c)
        if doc:
            ev = self._ev(c)
            ev["decision_document_id"] = str(doc)
            c.evidence = ev
            await self.db.flush()
        await self._emit(
            "discipline.decided",
            {"case_id": str(c.id), "sanctions": [s.get("type") for s in c.sanctions or []]},
            "disciplinary_case",
            c.id,
        )
        await self._notify(
            "discipline.decision",
            await self._subject_users(c),
            {"case_number": c.case_number, "decision": ", ".join(str(s.get("type")) for s in c.sanctions or [])},
        )
        await self._audit("decide", "disciplinary_case", c.id, None, {"sanctions": c.sanctions})

    async def _enrolment_of(self, c: DisciplinaryCase) -> StudentProgramEnrollment | None:
        if c.subject_type != "student":
            return None
        return (
            await self.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == c.subject_id))
        ).scalar_one_or_none()

    async def _apply(self, c: DisciplinaryCase, s: dict[str, Any]) -> dict[str, Any]:
        t = s.get("type")
        eff: dict[str, Any] = {"type": t, "applied_at": now_utc().isoformat(), "status": "applied"}
        enrol = await self._enrolment_of(c)
        try:
            if t == "fine" and enrol is not None:
                from app.services.fees.invoice_service import InvoiceService

                inv = await InvoiceService(self.db, self.principal, self.request, self.inst).link(
                    "discipline_fine",
                    c.id,
                    int(s.get("amount_paise") or 0),
                    enrol.id,
                    f"Disciplinary fine {c.case_number}",
                    head_type="fine",
                )
                c.fee_invoice_id = inv.id
                eff["fee_invoice_id"] = str(inv.id)
            elif t in ("suspension", "expulsion") and enrol is not None:
                from app.services.hold_service import HoldService

                hold = await HoldService(self.db, self.principal, self.request, self.inst).place_system(
                    enrol, "all", f"Disciplinary {t} ({c.case_number})", "discipline_case", c.id
                )
                eff["hold_id"] = str(hold.id)
                if t == "expulsion":
                    enrol.status = "expelled"
                    eff["enrolment_status"] = "expelled"
                else:
                    eff["attendance_policy"] = str(
                        await self.setting("discipline", "suspension_attendance") or "absent"
                    )
                    eff["lms_access"] = False
                    eff["from_on"], eff["to_on"] = s.get("from_on"), s.get("to_on")
            elif t == "community_service":
                eff["hours_target"] = float(s.get("hours") or 20)
            elif t == "expulsion" and c.subject_type == "staff":
                await self._emit(
                    "hr.disciplinary_action",
                    {"case_id": str(c.id), "staff_id": str(c.subject_id), "action": "termination"},
                    "staff",
                    c.subject_id,
                )
            if c.subject_type == "staff" and t != "expulsion":
                await self._emit(
                    "hr.disciplinary_action",
                    {"case_id": str(c.id), "staff_id": str(c.subject_id), "action": t},
                    "staff",
                    c.subject_id,
                )
        except APIError as exc:
            eff["status"], eff["error"] = "failed", exc.message if hasattr(exc, "message") else str(exc)
        await self._emit(
            "discipline.sanction_applied",
            {
                "case_id": str(c.id),
                "subject_type": c.subject_type,
                "subject_id": str(c.subject_id),
                **s,
                **{k: v for k, v in eff.items() if k != "type"},
            },
            "disciplinary_case",
            c.id,
        )
        return eff

    async def _letter(self, c: DisciplinaryCase) -> uuid.UUID | None:
        if not await self.feature("documents.templates"):
            return None
        try:
            res = await RenderService(self.db, self.principal, self.request, self.inst).render(
                "custom",
                "disciplinary_case",
                c.id,
                allow_multiple=True,
                variables_override={"title": "Disciplinary decision"},
            )
            return res.issued_document_id
        except APIError:
            return None

    async def _reverse(self, c: DisciplinaryCase, types: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if "fine" in types and c.fee_invoice_id:
            inv = (
                await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == c.fee_invoice_id))
            ).scalar_one_or_none()
            if inv is not None and (inv.paid_paise or 0) == 0:
                inv.status, inv.balance_paise = "cancelled", 0
                out.append({"type": "fine", "reversed": "invoice_cancelled"})
            else:
                out.append({"type": "fine", "reversed": "refund_due"})
        if types & {"suspension", "expulsion"}:
            holds = (
                (
                    await self.db.execute(
                        select(StudentHold).where(
                            StudentHold.source_type == "discipline_case",
                            StudentHold.source_id == c.id,
                            StudentHold.released_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for h in holds:
                h.released_at, h.released_by = now_utc(), self.actor_id
            out.append({"type": "hold", "released": len(holds)})
            if "expulsion" in types:
                enrol = await self._enrolment_of(c)
                if enrol is not None and enrol.status == "expelled":
                    enrol.status = "active"
        for t in types:
            await self._emit(
                "discipline.sanction_reversed",
                {"case_id": str(c.id), "type": t, "subject_id": str(c.subject_id)},
                "disciplinary_case",
                c.id,
            )
        await self.db.flush()
        return out

    # ---- appeal ---------------------------------------------------------------------------------------------------------
    async def appeal(self, cid: uuid.UUID, body: DiscAppealCreate) -> DiscCaseOut:
        c = await self._get(cid, lock=True)
        if not await self._is_subject(c):
            raise not_found("Case")
        if not await self._appeal_open(c):
            raise rule("The appeal window is closed or an appeal exists", "APPEAL_CLOSED")
        ev = self._ev(c)
        ev["appeal"] = {
            "grounds": body.grounds,
            "attachments": [a.model_dump() for a in body.attachments],
            "filed_at": now_utc().isoformat(),
        }
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="discipline.appeal",
                entity_type="disciplinary_case",
                entity_id=c.id,
                started_by=self.actor_id,
                context={"case_number": c.case_number},
                title=f"Appeal — {c.case_number}"[:200],
            )
            ev["appeal"]["workflow_instance_id"] = str(wf.id)
        except APIError:
            pass
        self._tl(ev, "appealed")
        c.evidence, c.appeal_status, c.status = ev, "pending", "appealed"
        await self.db.flush()
        await self._emit("discipline.appealed", {"case_id": str(c.id)}, "disciplinary_case", c.id)
        await self._notify(
            "discipline.appeal",
            await self.role_users("vice_chancellor"),
            {"case_number": c.case_number, "status": "appeal filed"},
        )
        return (await self.outs([c], detail=True))[0]

    async def decide_appeal(self, cid: uuid.UUID, body: DiscAppealDecision) -> DiscCaseOut:
        self.require_writer()
        if not self.can("discipline", "appeal"):
            raise forbidden("discipline:appeal required")
        c = await self._get(cid, lock=True)
        if c.status != "appealed" or c.appeal_status != "pending":
            raise rule("No pending appeal", "NO_APPEAL")
        current = {str(s.get("type")) for s in c.sanctions or []}
        ev = self._ev(c)
        reversals: list[dict[str, Any]] = []
        if body.outcome == "revoke":
            reversals = await self._reverse(c, current)
            c.sanctions = []
        elif body.outcome == "modify":
            new = [s.model_dump(mode="json") for s in (body.sanctions or [])]
            keep = {str(s["type"]) for s in new}
            reversals = await self._reverse(c, current - keep)
            c.sanctions = new
            for s in new:
                if s["type"] not in current:
                    ev.setdefault("effects", []).append(await self._apply(c, s))
        appeal = dict(ev.get("appeal") or {})
        appeal.update(
            {
                "outcome": body.outcome,
                "remarks": body.remarks,
                "decided_at": now_utc().isoformat(),
                "reversals": reversals,
            }
        )
        ev["appeal"] = appeal
        wf = appeal.get("workflow_instance_id")
        if wf:
            await self.close_workflow(uuid.UUID(wf), "approved")
        self._tl(ev, f"appeal_{body.outcome}")
        c.evidence, c.appeal_status, c.status = ev, body.outcome, "closed"
        await self.db.flush()
        await self._emit("discipline.closed", {"case_id": str(c.id), "appeal": body.outcome}, "disciplinary_case", c.id)
        await self._notify(
            "discipline.appeal",
            await self._subject_users(c),
            {"case_number": c.case_number, "status": f"appeal {body.outcome}"},
        )
        return (await self.outs([c], detail=True))[0]

    async def close(self, cid: uuid.UUID) -> DiscCaseOut:
        self.require_writer()
        c = await self._get(cid, lock=True)
        if not self._manager():
            raise forbidden("discipline:manage required")
        if c.status == "appealed":
            raise rule("Decide the appeal first", "APPEAL_PENDING")
        ev = self._ev(c)
        self._tl(ev, "closed")
        c.evidence, c.status = ev, "closed"
        await self.db.flush()
        await self._emit("discipline.closed", {"case_id": str(c.id)}, "disciplinary_case", c.id)
        return (await self.outs([c], detail=True))[0]

    # ---- reads ----------------------------------------------------------------------------------------------------------
    async def list_cases(
        self, status: str | None, subject_type: str | None, scope: str | None = None, limit: int = 500
    ) -> list[DiscCaseOut]:
        stmt = select(DisciplinaryCase).where(DisciplinaryCase.institution_id == self.inst, await self._visible(scope))
        if status:
            stmt = stmt.where(DisciplinaryCase.status == status)
        if subject_type:
            stmt = stmt.where(DisciplinaryCase.subject_type == subject_type)
        rows = (await self.db.execute(stmt.order_by(DisciplinaryCase.created_at.desc()).limit(limit))).scalars().all()
        return await self.outs(list(rows))

    async def get(self, cid: uuid.UUID) -> DiscCaseOut:
        return (await self.outs([await self._get(cid)], detail=True))[0]

    async def mine(self) -> list[DiscCaseOut]:
        parts = await self._subject_self()
        if not parts:
            return []
        rows = (
            (
                await self.db.execute(
                    select(DisciplinaryCase).where(or_(*parts)).order_by(DisciplinaryCase.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows), detail=True)

    async def register(self, date_from: Any, date_to: Any, subject_type: str | None) -> list[DiscRegisterRow]:
        if not self.reader():
            raise forbidden("discipline:view_all required")
        stmt = select(DisciplinaryCase).where(DisciplinaryCase.institution_id == self.inst, await self._visible())
        if date_from:
            stmt = stmt.where(func.date(DisciplinaryCase.created_at) >= date_from)
        if date_to:
            stmt = stmt.where(func.date(DisciplinaryCase.created_at) <= date_to)
        if subject_type:
            stmt = stmt.where(DisciplinaryCase.subject_type == subject_type)
        rows = list((await self.db.execute(stmt.order_by(DisciplinaryCase.created_at))).scalars().all())
        info = await self._subject_info(rows)
        return [
            DiscRegisterRow(
                case_number=r.case_number,
                subject_type=r.subject_type,
                subject=info.get(r.subject_id, {}).get("name"),
                category=r.category,
                reported_on=r.created_at,
                status=r.status,
                sanctions=", ".join(str(s.get("type")) for s in r.sanctions or []) or None,
                decided_on=r.decided_at,
                appeal_status=r.appeal_status,
            )
            for r in rows
        ]

    async def counts(self) -> dict[str, Any]:
        by_status = {
            s: int(n)
            for s, n in (
                await self.db.execute(
                    select(DisciplinaryCase.status, func.count())
                    .where(DisciplinaryCase.institution_id == self.inst)
                    .group_by(DisciplinaryCase.status)
                )
            ).all()
        }
        by_subject = {
            s: int(n)
            for s, n in (
                await self.db.execute(
                    select(DisciplinaryCase.subject_type, func.count())
                    .where(DisciplinaryCase.institution_id == self.inst)
                    .group_by(DisciplinaryCase.subject_type)
                )
            ).all()
        }
        return {"total": sum(by_status.values()), "by_status": by_status, "by_subject": by_subject}

    async def appeal_window(self) -> int:
        """Beat ``discipline.appeal_window`` — close decided cases whose appeal window lapsed."""
        scale = await self.setting("discipline", "sanction_scale")
        days = int((scale if isinstance(scale, dict) else DEFAULT_SANCTION_SCALE).get("appeal_window_days") or 15)
        rows = (
            (
                await self.db.execute(
                    select(DisciplinaryCase).where(
                        DisciplinaryCase.institution_id == self.inst,
                        DisciplinaryCase.status == "decided",
                        DisciplinaryCase.appeal_status.is_(None),
                        DisciplinaryCase.decided_at < now_utc() - timedelta(days=days),
                    )
                )
            )
            .scalars()
            .all()
        )
        for c in rows:
            ev = self._ev(c)
            self._tl(ev, "closed", reason="appeal window lapsed")
            c.evidence, c.status = ev, "closed"
            await self._emit("discipline.closed", {"case_id": str(c.id), "auto": True}, "disciplinary_case", c.id)
        await self.db.flush()
        return len(rows)

    async def from_source(
        self,
        subject_type: str,
        subject_id: uuid.UUID,
        category: str,
        description: str,
        source_type: str,
        source_id: Any,
    ) -> None:
        """Consumers (hostel discipline, malpractice referral, false SOS, placement violation) open a case."""
        from app.schemas.discipline import DiscSource

        await self.create(
            DiscCaseCreate(
                subject_type=subject_type,  # type: ignore[arg-type]
                subject_id=subject_id,
                category=category[:40],
                description=description[:10000] or category,
                source=DiscSource(type=source_type, id=uuid.UUID(str(source_id)) if source_id else None),  # type: ignore[arg-type]
            ),
            system=True,
        )


@register_resolver("disciplinary_case")
async def _case_ctx(svc: RenderService, cid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    c = (await svc.db.execute(select(DisciplinaryCase).where(DisciplinaryCase.id == cid))).scalar_one()
    ev = c.evidence or {}
    sanctions = "; ".join(
        f"{s.get('type')}"
        + (f" ₹{int(s['amount_paise']) / 100:,.0f}" if s.get("amount_paise") else "")
        + (f" {s.get('from_on')} to {s.get('to_on')}" if s.get("from_on") else "")
        for s in c.sanctions or []
    )
    if c.subject_type == "student":
        ctx, ptype, pid = await svc.enrolment_ctx(c.subject_id)
    else:
        ctx, ptype, pid = await svc.staff_ctx(c.subject_id)
    name = (ctx.get("student") or ctx.get("staff") or {}).get("name", "")
    ctx["case"] = {"number": c.case_number, "category": c.category, "sanctions": sanctions}
    ctx["title"] = "Disciplinary decision"
    ctx["body"] = (
        f"Case {c.case_number} ({c.category}) against {name}: {ev.get('decision_text') or ''} "
        f"Sanctions: {sanctions or 'none'}. An appeal may be filed within the appeal window."
    )
    return ctx, ptype, pid


@workflow_engine.summariser("disciplinary_case")
async def _summary(db: Any, cid: uuid.UUID) -> tuple[str | None, str | None]:
    c = (await db.execute(select(DisciplinaryCase).where(DisciplinaryCase.id == cid))).scalar_one_or_none()
    if c is None:
        return None, None
    return f"Discipline {c.case_number} · {c.category}", f"/admin/discipline/{c.id}"


@workflow_engine.on("discipline.case", "approved")
async def _case_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = DisciplineService(db, actor, institution_id=instance.institution_id)
    c = await svc._raw(instance.entity_id)
    if c.status in ("inquiry", "hearing", "reported"):
        ev = svc._ev(c)
        svc._tl(ev, "decision_approved")
        c.evidence = ev
        await svc.apply_decision(c)


@workflow_engine.on("discipline.case", "rejected")
async def _case_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = DisciplineService(db, actor, institution_id=instance.institution_id)
    c = await svc._raw(instance.entity_id)
    ev = svc._ev(c)
    svc._tl(ev, "decision_returned")
    ev.pop("workflow_instance_id", None)
    c.evidence, c.sanctions = ev, None
    await db.flush()


@workflow_engine.on("discipline.appeal", "rejected")
async def _appeal_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = DisciplineService(db, actor, institution_id=instance.institution_id)
    c = await svc._raw(instance.entity_id)
    if c.status == "appealed":
        ev = svc._ev(c)
        appeal = dict(ev.get("appeal") or {})
        appeal.update({"outcome": "uphold", "decided_at": now_utc().isoformat()})
        ev["appeal"] = appeal
        svc._tl(ev, "appeal_uphold")
        c.evidence, c.appeal_status, c.status = ev, "uphold", "closed"
        await db.flush()
