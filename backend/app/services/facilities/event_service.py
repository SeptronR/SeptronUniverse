"""Events — Prompts/25 §25.6 ``event_service`` ({events.core}, {events.certificates}).

1. **Lifecycle** — proposal (organiser = the caller's staff row, department defaults to theirs) → ``submit`` starts the
   ``event.approval`` workflow (HOD of the organiser department → principal); approval with ``budget_paise > 0`` and
   {accounting.budgets} on starts ``event.budget`` (accountant) and its approval emits ``budget.commit_requested``;
   ``schedule`` books the venue through ``BookingService.for_event`` (approved when free, else 409 ``ROOM_CONFLICT`` and
   the event stays ``approved``); ``cancel`` releases the venue and the budget commitment (``budget.commit_released``).
   ``events:manage`` holders may approve / reject directly (the pending workflow is closed).
2. **Registrations** — internal (student / staff) or external (public form when ``registration.audience='public'``),
   capacity with waitlist (``external.waitlisted``), fee through ``InvoiceService.create_invoice``
   (``source_type='event_registration'``; students and staff — external fees are collected at the venue), QR token.
3. **Attendance / certificates** — attendance by QR (organiser) or list; the ``event.certificates`` job numbers a
   certificate for each attended registrant (``certificate_document_id``, ``certificate_no`` sequence) rendered from
   the platform ``event_certificate`` template with a signed verification link until the Phase 26 renderer lands.
4. **Report** — participants, external count, spend (expenses whose ``reference_no`` is the event id + manual spend),
   images, outcomes, ``naac_criterion``; completion emits ``event.completed`` and ``accreditation.evidence_suggested``.

Visibility: self (creator / organiser), department (HOD — organiser department), college, all; anyone with
``events:view`` additionally sees scheduled / completed events whose registration audience covers them.
"""

import secrets
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import false, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.facilities import EVENT_CERTIFICATE_HTML, NAAC_DEFAULTS
from app.models.events import Event, EventRegistration
from app.models.fees import FeeInvoice
from app.models.hr import Staff
from app.models.platform import WorkflowInstance
from app.models.students import Student, StudentProgramEnrollment
from app.models.timetable import Room
from app.schemas.events import (
    EventAction,
    EventAttendanceMark,
    EventCertificateRequest,
    EventCreate,
    EventPublicOut,
    EventRegister,
    EventRegistrationOut,
    EventReport,
    EventReportIn,
    EventResponse,
    EventUpdate,
)
from app.services.facilities.common import FacilitiesBase, forbidden, not_found, rule, scope_ids

LIVE = ("approved", "scheduled")
EKEYS = ("title", "status", "from_on", "to_on", "budget_paise")


class EventService(FacilitiesBase):
    audit_module = "events"
    module = "events"

    # ---- visibility ---------------------------------------------------------------------------------------------------
    async def _visible(self) -> Any:
        p = self.principal
        managed = self.unit_predicate(
            "events",
            self_cols=(Event.created_by,),
            dept_col=Event.organiser_department_id,
            college_col=Event.college_id,
        )
        sid = await self.my_staff_id()
        parts = [managed]
        if sid:
            parts.append(Event.organiser_staff_id == sid)
        if p is not None and self.can("events", "view"):
            parts.append(Event.status.in_(("scheduled", "completed")))
        return or_(*parts) if parts else false()

    async def _audience_ok(self, e: Event, reg: dict[str, Any]) -> bool:
        aud = reg.get("audience") or "institution"
        if aud in ("institution", "public") or self.all_access():
            return True
        if aud == "college":
            colleges = set(scope_ids(self.principal, "college"))
            st, sf = await self.my_student(), await self.my_staff()
            if st:
                colleges.add(st.college_id)
            if sf and sf.college_id:
                colleges.add(sf.college_id)
            return e.college_id is None or e.college_id in colleges
        if aud == "department":
            deps = set(scope_ids(self.principal, "department"))
            sf = await self.my_staff()
            if sf and sf.department_id:
                deps.add(sf.department_id)
            st = await self.my_student()
            if st:
                deps |= set(
                    (
                        await self.db.execute(
                            select(StudentProgramEnrollment.department_id).where(
                                StudentProgramEnrollment.student_id == st.id
                            )
                        )
                    ).scalars()
                )
            return e.organiser_department_id is None or e.organiser_department_id in deps
        return True

    async def row(self, eid: uuid.UUID, *, for_update: bool = False) -> Event:
        stmt = select(Event).where(
            Event.id == eid, Event.institution_id == self.inst, Event.deleted_at.is_(None), await self._visible()
        )
        if for_update:
            stmt = stmt.with_for_update()
        e = (await self.db.execute(stmt)).scalar_one_or_none()
        if e is None:
            raise not_found("Event")
        if e.status in ("scheduled", "completed") and not await self._is_manager(e):
            reg = (await self.meta("event", e.id)).get("registration") or {}
            if not await self._audience_ok(e, reg):
                raise not_found("Event")
        return e

    async def _is_organiser(self, e: Event) -> bool:
        if self.actor_id and e.created_by == self.actor_id:
            return True
        sid = await self.my_staff_id()
        return bool(sid and e.organiser_staff_id == sid)

    async def _is_manager(self, e: Event) -> bool:
        if await self._is_organiser(e) or self.can("events", "manage") or self.can("events", "view_all"):
            return True
        return bool(e.organiser_department_id and e.organiser_department_id in scope_ids(self.principal, "department"))

    async def outs(self, rows: Sequence[Event]) -> list[EventResponse]:
        ids = [e.id for e in rows]
        metas = await self.metas("event", ids)
        counts: dict[uuid.UUID, dict[str, int]] = {}
        for eid, attended, waitlisted, n in (
            await self.db.execute(
                select(
                    EventRegistration.event_id,
                    EventRegistration.attended,
                    EventRegistration.external["waitlisted"].astext,
                    func.count(),
                )
                .where(EventRegistration.event_id.in_(ids or [uuid.uuid4()]))
                .group_by(
                    EventRegistration.event_id,
                    EventRegistration.attended,
                    EventRegistration.external["waitlisted"].astext,
                )
            )
        ).all():
            c = counts.setdefault(eid, {"registered": 0, "attended": 0, "waitlisted": 0})
            if waitlisted == "true":
                c["waitlisted"] += n
            else:
                c["registered"] += n
            if attended:
                c["attended"] += n
        rooms = {
            r.id: r.code
            for r in (
                await self.db.execute(
                    select(Room).where(
                        Room.id.in_([e.venue_room_id for e in rows if e.venue_room_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        wfs = {
            w.id: w
            for w in (
                await self.db.execute(
                    select(WorkflowInstance).where(
                        WorkflowInstance.id.in_(
                            [e.workflow_instance_id for e in rows if e.workflow_instance_id] or [uuid.uuid4()]
                        )
                    )
                )
            ).scalars()
        }
        mine: dict[uuid.UUID, EventRegistration] = {}
        try:
            ptype, pid = await self.me_person()
            for r in (
                await self.db.execute(
                    select(EventRegistration).where(
                        EventRegistration.event_id.in_(ids or [uuid.uuid4()]),
                        EventRegistration.person_type == ptype,
                        EventRegistration.person_id == pid,
                    )
                )
            ).scalars():
                mine[r.event_id] = r
        except APIError:
            pass
        sid = await self.my_staff_id()
        out = []
        for e in rows:
            o = EventResponse.model_validate(e)
            m = metas.get(str(e.id), {})
            o.registration = m.get("registration") or {}
            o.budget = {
                k: m.get(k) for k in ("budget_head_id", "budget_status", "committed_paise") if m.get(k) is not None
            }
            o.counts = counts.get(e.id, {"registered": 0, "attended": 0, "waitlisted": 0})
            o.venue_label = rooms.get(e.venue_room_id) if e.venue_room_id else e.venue_text
            o.venue_booking_id = uuid.UUID(m["venue_booking_id"]) if m.get("venue_booking_id") else None
            wf = wfs.get(e.workflow_instance_id) if e.workflow_instance_id else None
            o.workflow = {"status": wf.status, "current_step": wf.current_step, "instance_id": str(wf.id)} if wf else {}
            if m.get("budget_workflow_id"):
                o.workflow["budget_workflow_id"] = m["budget_workflow_id"]
            o.is_organiser = (self.actor_id is not None and e.created_by == self.actor_id) or (
                sid is not None and e.organiser_staff_id == sid
            )
            mr = mine.get(e.id)
            if mr is not None:
                o.my_registration = {
                    "id": str(mr.id),
                    "attended": mr.attended,
                    "waitlisted": bool((mr.external or {}).get("waitlisted")),
                    "qr_token": (mr.external or {}).get("qr_token"),
                    "certificate": bool(mr.certificate_document_id or (mr.external or {}).get("certificate_id")),
                }
            out.append(o)
        return out

    async def list_events(
        self,
        *,
        status: str | None = None,
        event_type: str | None = None,
        scope: str | None = None,
        q: str | None = None,
    ) -> list[EventResponse]:
        stmt = select(Event).where(Event.institution_id == self.inst, Event.deleted_at.is_(None))
        if scope in ("mine", "self"):
            sid = await self.my_staff_id()
            stmt = stmt.where(or_(Event.created_by == self.actor_id, Event.organiser_staff_id == (sid or uuid.uuid4())))
        elif scope in ("department", "college", "all"):
            stmt = stmt.where(
                self.unit_predicate(
                    "events", dept_col=Event.organiser_department_id, college_col=Event.college_id, scope=scope
                )
            )
        else:
            stmt = stmt.where(await self._visible())
        if status:
            stmt = stmt.where(Event.status == status)
        if event_type:
            stmt = stmt.where(Event.event_type == event_type)
        if q:
            stmt = stmt.where(Event.title.ilike(f"%{q}%"))
        rows = (await self.db.execute(stmt.order_by(Event.from_on.desc()).limit(300))).scalars().all()
        outs = await self.outs(rows)
        visible: list[EventResponse] = []
        for o, e in zip(outs, rows, strict=True):
            restricted = e.status in ("scheduled", "completed") and not o.is_organiser
            if restricted and not await self._is_manager(e) and not await self._audience_ok(e, o.registration):
                continue
            visible.append(o)
        return visible

    async def get(self, eid: uuid.UUID) -> EventResponse:
        return (await self.outs([await self.row(eid)]))[0]

    # ---- proposal ------------------------------------------------------------------------------------------------------
    async def create(self, body: EventCreate) -> EventResponse:
        self.require("events:organise", "events:manage")
        self.require_writer()
        staff = await self.my_staff()
        dept = body.organiser_department_id or (staff.department_id if staff else None)
        other_dept = bool(body.organiser_department_id and staff and staff.department_id != dept)
        if other_dept and not self.all_access() and dept not in scope_ids(self.principal, "department"):
            raise forbidden("You organise events for your own department")
        e = Event(
            institution_id=self.inst,
            college_id=body.college_id or (staff.college_id if staff else None),
            event_type=body.event_type,
            title=body.title,
            description=body.description,
            organiser_department_id=dept,
            organiser_staff_id=staff.id if staff else None,
            from_on=body.from_on,
            to_on=body.to_on,
            venue_room_id=body.venue_room_id,
            venue_text=body.venue_text,
            budget_paise=body.budget_paise or None,
            sponsor=body.sponsor,
            naac_criterion=body.naac_criterion or NAAC_DEFAULTS.get(body.event_type),
            registration_fee_paise=body.registration.fee_paise or None,
            status="proposed",
            created_by=self.actor_id,
        )
        self.db.add(e)
        await self.db.flush()
        meta: dict[str, Any] = {"registration": body.registration.model_dump(mode="json")}
        if body.budget_head_id:
            meta["budget_head_id"] = str(body.budget_head_id)
        if body.club_id:
            meta["club_id"] = str(body.club_id)
        await self.put_meta("event", e.id, meta)
        await self._audit("create", "event", e.id, None, {"title": e.title})
        return await self.get(e.id)

    async def update(self, eid: uuid.UUID, body: EventUpdate) -> EventResponse:
        self.require_writer()
        e = await self.row(eid, for_update=True)
        if not (await self._is_organiser(e) or self.can("events", "manage")):
            raise forbidden("Only the organiser edits the event")
        if e.status in ("completed", "cancelled"):
            raise rule("A closed event cannot be edited", "EVENT_CLOSED")
        data = body.model_dump(exclude_unset=True)
        reg = data.pop("registration", None)
        head = data.pop("budget_head_id", None)
        if e.status == "scheduled" and any(k in data for k in ("from_on", "to_on", "venue_room_id", "budget_paise")):
            raise rule("Dates, venue and budget are fixed once the event is scheduled", "EVENT_SCHEDULED")
        for k, v in data.items():
            setattr(e, k, v)
        if e.to_on < e.from_on:
            raise APIError(422, ErrorCode.VALIDATION, "to_on must not be before from_on")
        m = await self.meta("event", e.id)
        if reg is not None:
            m["registration"] = reg
            e.registration_fee_paise = int(reg.get("fee_paise") or 0) or None
        if head is not None:
            m["budget_head_id"] = str(head)
        await self.put_meta("event", e.id, m)
        await self.db.flush()
        await self._audit("update", "event", e.id, None, {k: str(v) for k, v in data.items()})
        return await self.get(e.id)

    # ---- actions --------------------------------------------------------------------------------------------------------
    async def action(self, eid: uuid.UUID, body: EventAction) -> EventResponse:
        self.require_writer()
        e = await self.row(eid, for_update=True)
        a = body.action
        organiser = await self._is_organiser(e)
        if a == "submit":
            if not organiser and not self.can("events", "manage"):
                raise forbidden("Only the organiser submits the proposal")
            if e.status != "proposed" or e.workflow_instance_id:
                raise rule("The proposal was already submitted", "ALREADY_SUBMITTED")
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="event.approval",
                entity_type="event",
                entity_id=e.id,
                started_by=self.actor_id,
                context={
                    "department_id": str(e.organiser_department_id) if e.organiser_department_id else None,
                    "college_id": str(e.college_id) if e.college_id else None,
                    "budget_paise": e.budget_paise or 0,
                },
                title=f"Event · {e.title}"[:200],
            )
            e.workflow_instance_id = wf.id
            await self._emit("event.proposed", {"event_id": str(e.id)}, "event", e.id)
            await self._notify(
                "event.proposed",
                [],
                {"event": e.title, "event_type": e.event_type, "from_on": e.from_on.isoformat(), "event_id": str(e.id)},
                audience={"roles": ["hod"]},
            )
        elif a in ("approve", "reject"):
            self.require("events:manage", "events:approve")
            if not self.can("events", "manage"):
                raise rule("Decide the proposal in the approvals inbox", "WORKFLOW_REQUIRED")
            if e.status != "proposed":
                raise rule("Only a proposed event is decided", "NOT_PROPOSED")
            await self.close_workflow(e.workflow_instance_id, "approved" if a == "approve" else "rejected")
            if a == "approve":
                await self.approved(e)
            else:
                await self.rejected(e)
        elif a == "schedule":
            if not organiser and not self.can("events", "manage"):
                raise forbidden("Only the organiser schedules the event")
            if e.status != "approved":
                raise rule("Only an approved event is scheduled", "NOT_APPROVED", current=e.status)
            m = await self.meta("event", e.id)
            if m.get("budget_status") == "pending":
                raise rule("The event budget is awaiting approval", "BUDGET_PENDING")
            if e.venue_room_id and await self.feature("facilities.room_booking"):
                from app.services.facilities.booking_service import BookingService

                bk = await BookingService(self.db, self.principal, self.request, self.inst).for_event(
                    e.id, e.venue_room_id, e.from_on, e.to_on, e.title
                )
                m["venue_booking_id"] = str(bk.id)
            e.status = "scheduled"
            await self.put_meta("event", e.id, m)
            await self._emit("event.scheduled", {"event_id": str(e.id)}, "event", e.id)
            if (m.get("registration") or {}).get("open"):
                await self._notify(
                    "event.registration_open",
                    [],
                    {"event": e.title, "from_on": e.from_on.isoformat()},
                    audience={"roles": ["student", "faculty"]},
                )
        elif a == "complete":
            if not organiser and not self.can("events", "manage"):
                raise forbidden("Only the organiser completes the event")
            if e.status != "scheduled":
                raise rule("Only a scheduled event is completed", "NOT_SCHEDULED")
            e.status = "completed"
            counts = (await self.outs([e]))[0].counts
            e.participants_count = e.participants_count or counts.get("attended") or counts.get("registered")
            await self._emit(
                "event.completed", {"event_id": str(e.id), "naac_criterion": e.naac_criterion}, "event", e.id
            )
            if e.naac_criterion:
                await self._emit(
                    "accreditation.evidence_suggested",
                    {"source_type": "event", "source_id": str(e.id), "criterion": e.naac_criterion, "title": e.title},
                    "event",
                    e.id,
                )
            m = await self.meta("event", e.id)
            if m.get("club_id"):
                await self._emit(
                    "clubs.activity_hours_credits", {"event_id": str(e.id), "club_id": m["club_id"]}, "event", e.id
                )
        elif a == "cancel":
            if not organiser and not self.can("events", "manage"):
                raise forbidden("Only the organiser cancels the event")
            if e.status in ("completed", "cancelled"):
                raise rule("The event is already closed", "EVENT_CLOSED")
            await self.close_workflow(e.workflow_instance_id)
            from app.services.facilities.booking_service import BookingService

            await BookingService(self.db, self.principal, self.request, self.inst).release_event(e.id)
            m = await self.meta("event", e.id)
            if m.get("budget_status") == "committed" and m.get("budget_head_id"):
                await self._emit(
                    "budget.commit_released",
                    {
                        "budget_head_id": m["budget_head_id"],
                        "amount_paise": e.budget_paise or 0,
                        "source": f"event:{e.id}",
                    },
                    "event",
                    e.id,
                )
                m["budget_status"] = "released"
                await self.put_meta("event", e.id, m)
            e.status = "cancelled"
            await self._emit("event.cancelled", {"event_id": str(e.id)}, "event", e.id)
        await self.db.flush()
        await self._audit(a, "event", e.id, None, {"status": e.status, "remarks": body.remarks})
        return await self.get(e.id)

    async def approved(self, e: Event) -> None:
        m = await self.meta("event", e.id)
        if (e.budget_paise or 0) > 0 and await self.feature("accounting.budgets") and m.get("budget_status") is None:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="event.budget",
                entity_type="event_budget",
                entity_id=e.id,
                started_by=e.created_by,
                context={"college_id": str(e.college_id) if e.college_id else None, "budget_paise": e.budget_paise},
                title=f"Event budget · {e.title} · ₹{(e.budget_paise or 0) / 100:,.0f}"[:200],
            )
            m["budget_status"], m["budget_workflow_id"] = "pending", str(wf.id)
        e.status = "approved"
        await self.put_meta("event", e.id, m)
        await self.db.flush()
        await self._emit("event.approved", {"event_id": str(e.id)}, "event", e.id)
        await self._notify(
            "event.approved", [e.created_by], {"event": e.title, "status": "approved", "event_id": str(e.id)}
        )

    async def rejected(self, e: Event) -> None:
        e.status = "cancelled"
        await self.db.flush()
        await self._emit("event.rejected", {"event_id": str(e.id)}, "event", e.id)
        await self._notify(
            "event.approved", [e.created_by], {"event": e.title, "status": "rejected", "event_id": str(e.id)}
        )

    async def budget_decided(self, e: Event, approved: bool) -> None:
        m = await self.meta("event", e.id)
        if approved:
            m["budget_status"] = "committed"
            m["committed_paise"] = e.budget_paise or 0
            if m.get("budget_head_id"):
                await self._emit(
                    "budget.commit_requested",
                    {
                        "budget_head_id": m["budget_head_id"],
                        "amount_paise": e.budget_paise or 0,
                        "source": f"event:{e.id}",
                    },
                    "event",
                    e.id,
                )
        else:
            m["budget_status"] = "rejected"
        await self.put_meta("event", e.id, m)
        await self._notify(
            "event.approved",
            [e.created_by],
            {"event": e.title, "status": "budget " + ("approved" if approved else "rejected"), "event_id": str(e.id)},
        )

    # ---- registrations -----------------------------------------------------------------------------------------------
    async def reg_outs(self, rows: Sequence[EventRegistration], e: Event) -> list[EventRegistrationOut]:
        names = await self.person_names([(r.person_type, r.person_id) for r in rows])
        invs = {
            i.id: i.status
            for i in (
                await self.db.execute(
                    select(FeeInvoice).where(
                        FeeInvoice.id.in_([r.fee_invoice_id for r in rows if r.fee_invoice_id] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        out = []
        for r in rows:
            ext = r.external or {}
            out.append(
                EventRegistrationOut(
                    id=r.id,
                    event_id=r.event_id,
                    person_type=r.person_type,
                    person_id=r.person_id,
                    name=names.get(r.person_id) if r.person_id else ext.get("name"),
                    external=(
                        {k: v for k, v in ext.items() if k not in ("qr_token",)}
                        if r.person_type == "external"
                        else None
                    ),
                    fee_invoice_id=r.fee_invoice_id,
                    fee_status=invs.get(r.fee_invoice_id) if r.fee_invoice_id else ext.get("fee_status"),
                    attended=r.attended,
                    waitlisted=bool(ext.get("waitlisted")),
                    qr_token=ext.get("qr_token"),
                    certificate_document_id=r.certificate_document_id,
                    certificate_url=(
                        f"/api/v1/events/{e.id}/registrations/{r.id}/certificate"
                        if (r.certificate_document_id or ext.get("certificate_id"))
                        else None
                    ),
                    registered_at=r.registered_at,
                )
            )
        return out

    async def _capacity_state(self, e: Event, reg: dict[str, Any]) -> bool:
        """True when the next registrant goes to the waitlist."""
        cap = reg.get("capacity")
        if not cap:
            return False
        n = (
            await self.db.execute(
                select(func.count())
                .select_from(EventRegistration)
                .where(
                    EventRegistration.event_id == e.id,
                    or_(
                        EventRegistration.external.is_(None), EventRegistration.external["waitlisted"].astext != "true"
                    ),
                )
            )
        ).scalar_one()
        if n >= int(cap):
            if not reg.get("waitlist", True):
                raise rule("The event is full", "EVENT_FULL")
            return True
        return False

    async def register(self, eid: uuid.UUID, body: EventRegister) -> EventRegistrationOut:
        self.require("events:view", "events:organise", "events:manage")
        self.require_writer()
        e = await self.row(eid, for_update=True)
        reg = (await self.meta("event", e.id)).get("registration") or {}
        if e.status not in LIVE or not reg.get("open"):
            raise rule("Registrations are not open for this event", "REGISTRATION_CLOSED")
        if not await self._audience_ok(e, reg):
            raise forbidden("This event is not open to you")
        if body.person_type == "external":
            if body.external is None:
                raise APIError(422, ErrorCode.VALIDATION, "external details are required")
            return await self._register_external(e, reg, body)
        ptype, pid = await self.me_person()
        dup = (
            await self.db.execute(
                select(EventRegistration).where(
                    EventRegistration.event_id == e.id,
                    EventRegistration.person_type == ptype,
                    EventRegistration.person_id == pid,
                )
            )
        ).scalar_one_or_none()
        if dup is not None:
            return (await self.reg_outs([dup], e))[0]
        waitlisted = await self._capacity_state(e, reg)
        r = EventRegistration(
            institution_id=self.inst,
            event_id=e.id,
            person_type=ptype,
            person_id=pid,
            external={"qr_token": secrets.token_urlsafe(16), "waitlisted": waitlisted},
        )
        self.db.add(r)
        await self.db.flush()
        fee = int(reg.get("fee_paise") or 0)
        if fee > 0 and not waitlisted:
            r.fee_invoice_id = await self._invoice(e, r, ptype, pid, fee)
        await self.db.flush()
        await self._audit(
            "register", "event_registration", r.id, None, {"event_id": str(e.id), "waitlisted": waitlisted}
        )
        await self._emit("event.registered", {"event_id": str(e.id), "registration_id": str(r.id)}, "event", e.id)
        return (await self.reg_outs([r], e))[0]

    async def _register_external(self, e: Event, reg: dict[str, Any], body: EventRegister) -> EventRegistrationOut:
        if reg.get("audience") != "public":
            raise forbidden("This event does not take external registrations")
        assert body.external is not None
        waitlisted = await self._capacity_state(e, reg)
        fee = int(reg.get("fee_paise") or 0)
        r = EventRegistration(
            institution_id=self.inst,
            event_id=e.id,
            person_type="external",
            person_id=None,
            external={
                **body.external.model_dump(),
                "qr_token": secrets.token_urlsafe(16),
                "waitlisted": waitlisted,
                "fee_paise": fee,
                "fee_status": "due" if fee else None,
            },
        )
        self.db.add(r)
        await self.db.flush()
        await self._emit(
            "event.registered", {"event_id": str(e.id), "registration_id": str(r.id), "external": True}, "event", e.id
        )
        return (await self.reg_outs([r], e))[0]

    async def register_public(self, eid: uuid.UUID, body: EventRegister) -> EventRegistrationOut:
        e = (
            await self.db.execute(
                select(Event)
                .where(Event.id == eid, Event.institution_id == self.inst, Event.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if e is None:
            raise not_found("Event")
        reg = (await self.meta("event", e.id)).get("registration") or {}
        if e.status not in LIVE or not reg.get("open"):
            raise rule("Registrations are not open for this event", "REGISTRATION_CLOSED")
        return await self._register_external(e, reg, body.model_copy(update={"person_type": "external"}))

    async def _invoice(self, e: Event, r: EventRegistration, ptype: str, pid: uuid.UUID, fee: int) -> uuid.UUID | None:
        from app.schemas.fees import InvoiceCreate, InvoiceItemIn
        from app.services.fees.invoice_service import InvoiceService

        enrol_id = None
        if ptype == "student":
            enrol = await self.enrollments.open_for(pid)
            enrol_id = enrol.id if enrol else None
        inv = await InvoiceService(self.db, None, self.request, self.inst).create_invoice(
            InvoiceCreate(
                payer_type=ptype,
                payer_id=pid,
                enrollment_id=enrol_id,
                source_type="event_registration",
                source_id=r.id,
                description=f"Event registration — {e.title}"[:255],
                items=[
                    InvoiceItemIn(description=f"Registration: {e.title}"[:200], amount_paise=fee, head_code="OTHER")
                ],
                due_date=e.from_on,
            )
        )
        return inv.id

    async def registrations(self, eid: uuid.UUID) -> list[EventRegistrationOut]:
        e = await self.row(eid)
        if not await self._is_manager(e) and not self.can("events", "certify"):
            raise forbidden("Only the organiser lists the registrations")
        rows = (
            (
                await self.db.execute(
                    select(EventRegistration)
                    .where(EventRegistration.event_id == e.id)
                    .order_by(EventRegistration.registered_at)
                )
            )
            .scalars()
            .all()
        )
        return await self.reg_outs(rows, e)

    async def attendance(self, eid: uuid.UUID, body: EventAttendanceMark) -> list[EventRegistrationOut]:
        self.require_writer()
        e = await self.row(eid, for_update=True)
        if not (await self._is_organiser(e) or self.can("events", "manage")):
            raise forbidden("Only the organiser marks attendance")
        if e.status not in ("scheduled", "completed"):
            raise rule("Attendance is marked for a scheduled event", "NOT_SCHEDULED")
        stmt = select(EventRegistration).where(EventRegistration.event_id == e.id)
        if body.qr:
            stmt = stmt.where(EventRegistration.external["qr_token"].astext == body.qr)
        elif body.registration_ids:
            stmt = stmt.where(EventRegistration.id.in_(body.registration_ids))
        else:
            raise APIError(422, ErrorCode.VALIDATION, "registration_ids or qr is required")
        rows = (await self.db.execute(stmt)).scalars().all()
        if body.qr and not rows:
            raise not_found("Ticket")
        for r in rows:
            if (r.external or {}).get("waitlisted"):
                raise rule("A waitlisted registrant cannot be marked present", "WAITLISTED")
            r.attended = body.attended
            await self._emit("event.attended", {"event_id": str(e.id), "registration_id": str(r.id)}, "event", e.id)
        await self.db.flush()
        await self._audit("attendance", "event", e.id, None, {"count": len(rows), "attended": body.attended})
        return await self.reg_outs(rows, e)

    async def my_events(self) -> list[dict[str, Any]]:
        ptype, pid = await self.me_person()
        rows = (
            await self.db.execute(
                select(EventRegistration, Event)
                .join(Event, Event.id == EventRegistration.event_id)
                .where(EventRegistration.person_type == ptype, EventRegistration.person_id == pid)
                .order_by(Event.from_on.desc())
            )
        ).all()
        out = []
        for r, e in rows:
            ro = (await self.reg_outs([r], e))[0]
            out.append(
                {
                    "event": {
                        "id": str(e.id),
                        "title": e.title,
                        "event_type": e.event_type,
                        "from_on": e.from_on.isoformat(),
                        "to_on": e.to_on.isoformat(),
                        "status": e.status,
                    },
                    "registration": ro.model_dump(mode="json"),
                }
            )
        return out

    # ---- certificates ---------------------------------------------------------------------------------------------------
    async def queue_certificates(self, eid: uuid.UUID, body: EventCertificateRequest) -> Any:
        from app.core.jobs import enqueue

        self.require("events:certify", "events:manage", "events:organise")
        self.require_writer()
        e = await self.row(eid)
        if not (await self._is_organiser(e) or self.can("events", "certify") or self.can("events", "manage")):
            raise forbidden("Only the organiser issues certificates")
        if e.status not in ("scheduled", "completed"):
            raise rule("Certificates are issued for a held event", "NOT_HELD")
        return await enqueue(
            self.db, self.principal, "event.certificates", {"event_id": str(e.id), "only_attended": body.only_attended}
        )

    async def issue_certificates(self, eid: uuid.UUID, only_attended: bool = True) -> int:
        e = (await self.db.execute(select(Event).where(Event.id == eid))).scalar_one()
        stmt = select(EventRegistration).where(
            EventRegistration.event_id == e.id, EventRegistration.external["certificate_id"].astext.is_(None)
        )
        if only_attended:
            stmt = stmt.where(EventRegistration.attended.is_(True))
        rows = (await self.db.execute(stmt)).scalars().all()
        for r in rows:
            cert_id = uuid.uuid4()
            no = await self.sequence("certificate_no", "CERT")
            ext = dict(r.external or {})
            ext["certificate_no"], ext["certificate_id"] = no, str(cert_id)
            r.external = ext
            await self._emit(
                "event.certificate_issued",
                {"event_id": str(e.id), "registration_id": str(r.id), "document_id": str(cert_id)},
                "event",
                e.id,
            )
            if r.person_id:
                uid = await self.person_user_id(r.person_type, r.person_id)
                await self._notify("event.certificate_ready", [uid], {"event": e.title})
        await self.db.flush()
        return len(rows)

    async def certificate_pdf(self, eid: uuid.UUID, rid: uuid.UUID) -> bytes:
        from app.core.security import sign_payload
        from app.utils.pdf import render_pdf

        r = (
            await self.db.execute(
                select(EventRegistration).where(EventRegistration.id == rid, EventRegistration.event_id == eid)
            )
        ).scalar_one_or_none()
        if r is None or not (r.certificate_document_id or (r.external or {}).get("certificate_id")):
            raise not_found("Certificate")
        e = (
            await self.db.execute(select(Event).where(Event.id == eid, Event.institution_id == self.inst))
        ).scalar_one()
        mine = False
        try:
            ptype, pid = await self.me_person()
            mine = r.person_type == ptype and r.person_id == pid
        except APIError:
            pass
        if not mine and not await self._is_manager(e) and not self.can("events", "certify"):
            raise not_found("Certificate")
        name = (
            (await self.person_names([(r.person_type, r.person_id)])).get(r.person_id)
            if r.person_id
            else (r.external or {}).get("name")
        )
        token = sign_payload({"t": "event_cert", "r": str(r.id), "i": str(self.inst)}, 3650 * 86400)
        verify = f"/api/v1/verify/event-certificate?token={token}"
        inst = await self.institution()
        html = EVENT_CERTIFICATE_HTML
        ctx = {
            "name": name or "Participant",
            "event": e.title,
            "event_type": e.event_type.replace("_", " "),
            "from_on": e.from_on.isoformat(),
            "to_on": e.to_on.isoformat(),
            "institution": inst.name,
            "verify_url": verify,
        }
        for k, v in ctx.items():
            html = html.replace("{{ " + k + " }}", str(v))
        lines = [
            "Certificate of Participation",
            "",
            f"This is to certify that {ctx['name']}",
            f"participated in {e.title} ({ctx['event_type']})",
            f"held from {ctx['from_on']} to {ctx['to_on']}.",
            "",
            inst.name,
            f"Certificate no: {(r.external or {}).get('certificate_no', '')}",
            f"Verify: {verify}",
        ]
        return render_pdf(html, lines, title="Certificate")

    # ---- report -----------------------------------------------------------------------------------------------------------
    async def report(self, eid: uuid.UUID) -> EventReport:
        from app.models.accounting import ExpenseRecord

        e = await self.row(eid)
        if not await self._is_manager(e) and not self.can("events", "view_all"):
            raise forbidden("Only the organiser reads the report")
        m = await self.meta("event", e.id)
        c = (await self.outs([e]))[0].counts
        certs = (
            await self.db.execute(
                select(func.count())
                .select_from(EventRegistration)
                .where(
                    EventRegistration.event_id == e.id, EventRegistration.external["certificate_id"].astext.is_not(None)
                )
            )
        ).scalar_one()
        ext = (
            await self.db.execute(
                select(func.count())
                .select_from(EventRegistration)
                .where(EventRegistration.event_id == e.id, EventRegistration.person_type == "external")
            )
        ).scalar_one()
        spend = (
            await self.db.execute(
                select(func.coalesce(func.sum(ExpenseRecord.amount_paise), 0)).where(
                    ExpenseRecord.institution_id == self.inst,
                    ExpenseRecord.reference_no == str(e.id),
                    ExpenseRecord.status.in_(("approved", "paid")),
                )
            )
        ).scalar_one()
        return EventReport(
            event_id=e.id,
            participants=e.participants_count or c.get("attended", 0),
            external=e.external_participants_count if e.external_participants_count is not None else int(ext),
            registered=c.get("registered", 0),
            attended=c.get("attended", 0),
            certificates=int(certs),
            budget_paise=e.budget_paise or 0,
            spend_paise=int(spend) + int(m.get("manual_spend_paise") or 0),
            images=e.images or [],
            report_url=e.report_url,
            outcomes=m.get("outcomes"),
            naac_criterion=e.naac_criterion,
        )

    async def save_report(self, eid: uuid.UUID, body: EventReportIn) -> EventReport:
        self.require_writer()
        e = await self.row(eid, for_update=True)
        if not (await self._is_organiser(e) or self.can("events", "manage")):
            raise forbidden("Only the organiser writes the report")
        if body.participants is not None:
            e.participants_count = body.participants
        if body.external is not None:
            e.external_participants_count = body.external
        if body.images:
            e.images = body.images
        if body.report_url:
            e.report_url = body.report_url
        if body.naac_criterion:
            e.naac_criterion = body.naac_criterion
        m = await self.meta("event", e.id)
        if body.outcomes is not None:
            m["outcomes"] = body.outcomes
        await self.put_meta("event", e.id, m)
        await self.db.flush()
        await self._audit("report", "event", e.id, None, {"participants": e.participants_count})
        return await self.report(e.id)

    # ---- public / reminders -------------------------------------------------------------------------------------------
    async def public_list(self) -> list[EventPublicOut]:
        today = await self.today()
        rows = (
            await self.db.execute(
                select(Event, Room.code)
                .outerjoin(Room, Room.id == Event.venue_room_id)
                .where(
                    Event.institution_id == self.inst,
                    Event.deleted_at.is_(None),
                    Event.status == "scheduled",
                    Event.to_on >= today,
                )
                .order_by(Event.from_on)
                .limit(100)
            )
        ).all()
        metas = await self.metas("event", [e.id for e, _ in rows])
        out = []
        for e, room in rows:
            reg = (metas.get(str(e.id)) or {}).get("registration") or {}
            if reg.get("audience") != "public":
                continue
            out.append(
                EventPublicOut(
                    id=e.id,
                    title=e.title,
                    event_type=e.event_type,
                    from_on=e.from_on,
                    to_on=e.to_on,
                    venue=room or e.venue_text,
                    registration_open=bool(reg.get("open")),
                    fee_paise=int(reg.get("fee_paise") or 0),
                )
            )
        return out

    async def reminders(self) -> int:
        from datetime import timedelta

        tomorrow = (await self.today()) + timedelta(days=1)
        rows = (
            (
                await self.db.execute(
                    select(Event).where(
                        Event.institution_id == self.inst, Event.status == "scheduled", Event.from_on == tomorrow
                    )
                )
            )
            .scalars()
            .all()
        )
        sent = 0
        for e in rows:
            regs = (
                (await self.db.execute(select(EventRegistration).where(EventRegistration.event_id == e.id)))
                .scalars()
                .all()
            )
            users = []
            for r in regs:
                if r.person_id:
                    users.append(await self.person_user_id(r.person_type, r.person_id))
            if users:
                await self._notify(
                    "event.reminder",
                    users,
                    {"event": e.title, "from_on": e.from_on.isoformat(), "venue": e.venue_text or ""},
                )
                sent += 1
        return sent

    async def staff_of(self, sid: uuid.UUID | None) -> Staff | None:
        if sid is None:
            return None
        return (await self.db.execute(select(Staff).where(Staff.id == sid))).scalar_one_or_none()

    async def student_of(self, sid: uuid.UUID) -> Student | None:
        return (await self.db.execute(select(Student).where(Student.id == sid))).scalar_one_or_none()


@workflow_engine.on("event.approval", "approved")
async def _event_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = EventService(db, actor, institution_id=instance.institution_id)
    e = (await db.execute(select(Event).where(Event.id == instance.entity_id).with_for_update())).scalar_one_or_none()
    if e is not None and e.status == "proposed":
        await svc.approved(e)


@workflow_engine.on("event.approval", "rejected")
async def _event_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = EventService(db, actor, institution_id=instance.institution_id)
    e = (await db.execute(select(Event).where(Event.id == instance.entity_id).with_for_update())).scalar_one_or_none()
    if e is not None and e.status == "proposed":
        await svc.rejected(e)


@workflow_engine.on("event.budget", "approved")
async def _budget_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    e = (await db.execute(select(Event).where(Event.id == instance.entity_id))).scalar_one_or_none()
    if e is not None:
        await EventService(db, actor, institution_id=instance.institution_id).budget_decided(e, True)


@workflow_engine.on("event.budget", "rejected")
async def _budget_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    e = (await db.execute(select(Event).where(Event.id == instance.entity_id))).scalar_one_or_none()
    if e is not None:
        await EventService(db, actor, institution_id=instance.institution_id).budget_decided(e, False)
