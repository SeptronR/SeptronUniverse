"""Substitutions — Prompts/10 §10.6 ``substitution_service.py`` ({timetable.substitutions}).

* **Manual request** by the entry's faculty member or a HOD / registrar (``timetable:substitute``) for a live entry on
  a date that has a session of it (weekday match, not in the past); an optional proposed substitute must be free at
  that time and not on approved leave. Starts the Phase 04 workflow ``timetable.substitution`` (HOD of the offering's
  department) and notifies the HOD. One request per entry × date; a rejected / withdrawn one is reopened.
* **Approval** (HOD of the department, ``timetable:approve`` / ``manage``) from the queue or the generic approvals
  inbox (workflow hook): a substitute is required, must be free at that slot (409 ``CONFLICT`` — overlapping live
  session) and not on approved Phase 06 leave that day (409); the session's ``staff_id`` is swapped for that date,
  both members notified, ``substitution.approved`` emitted. Reject → ``rejected`` + requester notified.
* **Auto from leave**: the ``leave.approved`` consumer creates ``requested`` rows (``source='leave_auto'``, reason
  tagged ``[leave:<id>]``) for every scheduled session of the staff member in the leave range and notifies the HOD;
  ``leave.cancelled`` → those rows ``withdrawn`` (an approved swap is reverted while attendance is not taken).
* **Candidates**: the department's teaching staff with ``free`` / ``on_leave`` flags for the slot (availability-aware
  picker).
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.hr import Staff, StaffLeave
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.platform import WorkflowInstance, WorkflowStep
from app.models.timetable import ClassSession, TimetableEntry, TimetableSubstitution
from app.repositories.substitution_repository import leave_tag
from app.schemas.timetable import SubstituteCandidate, SubstitutionCreate, SubstitutionDecision, SubstitutionResponse
from app.services.timetable.common import TT, TimetableBase, now_utc
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

WF_KEY = "timetable.substitution"
ENTITY = "timetable_substitution"


class _Actor:
    def __init__(self, institution_id: uuid.UUID, user_id: Any):
        self.institution_id, self.id = institution_id, user_id
        self.impersonator_id, self.is_super_admin = None, False
        self.scopes: list[Any] = [("institution", None)]

    def has(self, module: str, action: str) -> bool:
        return True


class SubstitutionService(TimetableBase):
    def _approver(self) -> bool:
        return bool(
            getattr(self.principal, "is_super_admin", False) or self.can(TT, "approve") or self.can(TT, "manage")
        )

    async def _departments(self) -> list[uuid.UUID] | None:
        if not self._approver():
            return []
        return await self.department_filter()

    async def _entry_department(self, entry: TimetableEntry) -> uuid.UUID | None:
        return (
            await self.db.execute(select(CourseOffering.department_id).where(CourseOffering.id == entry.offering_id))
        ).scalar_one_or_none()

    async def _assert_approver(self, entry: TimetableEntry) -> None:
        if not self._approver():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the HOD can decide substitutions")
        depts = await self.department_filter()
        if depts is not None and await self._entry_department(entry) not in depts:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "The class belongs to another department")

    # ---- reads -------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, **filters: Any
    ) -> tuple[list[SubstitutionResponse], PaginationMeta, VisibilityMeta]:
        depts = await self._departments()
        mine = scope in ("mine", "self", "own") or depts == []
        stmt = self.subs.filtered(department_ids=None if mine else depts, mine_only=mine, **filters)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.db.execute(stmt.offset(params.offset).limit(params.page_size))).scalars().all()
        page = PaginationMeta(
            page=params.page,
            page_size=params.page_size,
            total=total,
            total_pages=max(1, -(-total // params.page_size)),
        )
        tabs = [] if depts == [] else (["all"] if depts is None else ["department"])
        vis = VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=False)
        return await self.substitution_outs(rows), page, vis

    async def get(self, sub_id: uuid.UUID) -> SubstitutionResponse:
        return (await self.substitution_outs([await self.subs.get_one(sub_id)]))[0]

    # ---- availability ------------------------------------------------------------------------------------------
    async def _on_leave(self, staff_ids: list[uuid.UUID], on: date) -> set[uuid.UUID]:
        if not staff_ids:
            return set()
        rows = await self.db.execute(
            select(StaffLeave.staff_id).where(
                StaffLeave.staff_id.in_(staff_ids),
                StaffLeave.status == "approved",
                StaffLeave.from_date <= on,
                StaffLeave.to_date >= on,
            )
        )
        return set(rows.scalars().all())

    async def _session_for(self, entry: TimetableEntry, on: date) -> ClassSession:
        session = await self.sessions.of_entry(entry.id, on)
        if session is None:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "There is no session of this class on that date",
                {"field": "on_date", "reason": "no_session"},
            )
        return session

    async def _assert_free(self, staff_id: uuid.UUID, session: ClassSession) -> None:
        clash = await self.sessions.overlapping(
            session.session_date, session.start_time, session.end_time, staff_id=staff_id, exclude=session.id
        )
        if clash:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "The substitute already has a class at that time",
                {"field": "substitute_staff_id", "session_id": str(clash[0].id)},
            )
        if staff_id in await self._on_leave([staff_id], session.session_date):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "The substitute is on approved leave that day",
                {"field": "substitute_staff_id", "reason": "on_leave"},
            )

    async def candidates(self, sub_id: uuid.UUID) -> list[SubstituteCandidate]:
        sub = await self.subs.get_one(sub_id)
        entry = await self.tts.entry(sub.timetable_entry_id)
        session = await self._session_for(entry, sub.on_date)
        dept = await self._entry_department(entry)
        staff = (
            (
                await self.db.execute(
                    select(Staff)
                    .where(
                        Staff.institution_id == self.inst,
                        Staff.deleted_at.is_(None),
                        Staff.staff_category == "teaching",
                        Staff.department_id == dept,
                        Staff.id != entry.staff_id,
                    )
                    .order_by(Staff.first_name)
                )
            )
            .scalars()
            .all()
        )
        ids = [s.id for s in staff]
        busy_rows = await self.db.execute(
            select(ClassSession.staff_id).where(
                ClassSession.staff_id.in_(ids),
                ClassSession.session_date == session.session_date,
                ClassSession.status.in_(("scheduled", "conducted")),
                ClassSession.start_time < session.end_time,
                ClassSession.end_time > session.start_time,
            )
        )
        busy = set(busy_rows.scalars().all())
        leave = await self._on_leave(ids, session.session_date)
        teaches = set(
            (
                await self.db.execute(
                    select(CourseOfferingFaculty.staff_id).where(
                        CourseOfferingFaculty.offering_id == entry.offering_id, CourseOfferingFaculty.staff_id.in_(ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        out = [
            SubstituteCandidate(
                staff_id=s.id,
                name=s.full_name,
                department_id=s.department_id,
                free=s.id not in busy and s.id not in leave,
                on_leave=s.id in leave,
                teaches_offering=s.id in teaches,
            )
            for s in staff
        ]
        return sorted(out, key=lambda c: (not c.free, not c.teaches_offering, c.name))

    # ---- request -----------------------------------------------------------------------------------------------
    async def create(self, body: SubstitutionCreate) -> SubstitutionResponse:
        entry = await self.tts.entry(body.entry_id, for_update=True)
        if not entry.is_active:
            raise APIError(
                422, ErrorCode.VALIDATION, "Only published classes can be substituted", {"field": "entry_id"}
            )
        me = await self.my_staff()
        if not (me is not None and me.id == entry.staff_id):
            await self._assert_approver(entry)
        if body.on_date < await self.today():
            raise APIError(422, ErrorCode.VALIDATION, "The date is in the past", {"field": "on_date"})
        session = await self._session_for(entry, body.on_date)
        if body.substitute_staff_id:
            await self._assert_free(body.substitute_staff_id, session)
        row = await self.subs.find(entry.id, body.on_date)
        if row is not None and row.status in ("requested", "approved"):
            raise APIError(
                409, ErrorCode.CONFLICT, "A substitution already exists for that class and date", {"id": str(row.id)}
            )
        if row is None:
            row = TimetableSubstitution(institution_id=self.inst, timetable_entry_id=entry.id, on_date=body.on_date)
            self.db.add(row)
        row.substitute_staff_id, row.reason = body.substitute_staff_id, body.reason
        row.source, row.status, row.approved_by = "manual", "requested", None
        await self.db.flush()
        await self._requested(row, entry)
        return await self.get(row.id)

    async def _requested(self, row: TimetableSubstitution, entry: TimetableEntry) -> None:
        dept = await self._entry_department(entry)
        oc = await self.offering_courses([entry.offering_id])
        course = oc.get(entry.offering_id, (None, None))[1]
        await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WF_KEY,
            entity_type=ENTITY,
            entity_id=row.id,
            started_by=self.actor_id,
            context={"department_id": str(dept) if dept else None, "on_date": row.on_date.isoformat()},
            title=f"Substitution · {course.code if course else 'class'} · {row.on_date.isoformat()}",
        )
        await self._audit(
            "request",
            ENTITY,
            row.id,
            None,
            {"entry_id": str(entry.id), "on_date": row.on_date.isoformat(), "source": row.source},
        )
        await self._emit(
            "substitution.requested",
            {
                "substitution_id": str(row.id),
                "entry_id": str(entry.id),
                "on_date": row.on_date.isoformat(),
                "source": row.source,
            },
            ENTITY,
            row.id,
        )
        await self._notify(
            "substitution.requested",
            await self.hod_user_ids(dept),
            {"course": course.code if course else "class", "on_date": row.on_date.isoformat(), "source": row.source},
        )

    # ---- decisions ---------------------------------------------------------------------------------------------
    async def _close_instance(self, sub_id: uuid.UUID, status: str) -> None:
        inst = (
            await self.db.execute(
                select(WorkflowInstance)
                .where(
                    WorkflowInstance.entity_type == ENTITY,
                    WorkflowInstance.entity_id == sub_id,
                    WorkflowInstance.status.in_(("pending", "escalated")),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if inst is None:
            return
        for step in (
            await self.db.execute(
                select(WorkflowStep).where(
                    WorkflowStep.instance_id == inst.id, WorkflowStep.status.in_(("pending", "escalated"))
                )
            )
        ).scalars():
            step.status = "skipped"
        inst.status, inst.closed_at = status, now_utc()

    async def approve(
        self, sub_id: uuid.UUID, body: SubstitutionDecision, *, via_workflow: bool = False
    ) -> SubstitutionResponse:
        row = await self.subs.get_one(sub_id, for_update=True)
        entry = await self.tts.entry(row.timetable_entry_id)
        if not via_workflow:
            await self._assert_approver(entry)
        if row.status != "requested":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        substitute = body.substitute_staff_id or row.substitute_staff_id
        if substitute is None:
            raise APIError(422, ErrorCode.VALIDATION, "Choose a substitute", {"field": "substitute_staff_id"})
        session = await self._session_for(entry, row.on_date)
        if session.attendance_status != "not_taken":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Attendance is already taken for that session")
        await self.db.execute(select(ClassSession.id).where(ClassSession.id == session.id).with_for_update())
        await self._assert_free(substitute, session)
        old_staff = session.staff_id
        session.staff_id = substitute
        row.substitute_staff_id, row.status, row.approved_by = substitute, "approved", self.actor_id
        await self.db.flush()
        if not via_workflow:
            await self._close_instance(row.id, "approved")
        await self._audit(
            "approve", ENTITY, row.id, {"status": "requested"}, {"status": "approved", "substitute": str(substitute)}
        )
        await self._emit(
            "substitution.approved",
            {
                "substitution_id": str(row.id),
                "session_id": str(session.id),
                "staff_id": str(old_staff) if old_staff else None,
                "substitute_staff_id": str(substitute),
                "on_date": row.on_date.isoformat(),
            },
            ENTITY,
            row.id,
        )
        oc = await self.offering_courses([entry.offering_id])
        course = oc.get(entry.offering_id, (None, None))[1]
        await self._notify(
            "substitution.approved",
            await self.staff_user_ids([old_staff, substitute]),
            {
                "course": course.code if course else "class",
                "on_date": row.on_date.isoformat(),
                "time": f"{session.start_time:%H:%M}",
            },
        )
        return await self.get(row.id)

    async def reject(
        self, sub_id: uuid.UUID, body: SubstitutionDecision, *, via_workflow: bool = False
    ) -> SubstitutionResponse:
        row = await self.subs.get_one(sub_id, for_update=True)
        entry = await self.tts.entry(row.timetable_entry_id)
        if not via_workflow:
            await self._assert_approver(entry)
        if row.status != "requested":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        row.status, row.approved_by = "rejected", self.actor_id
        await self.db.flush()
        if not via_workflow:
            await self._close_instance(row.id, "rejected")
        await self._audit(
            "reject", ENTITY, row.id, {"status": "requested"}, {"status": "rejected", "comment": body.comment}
        )
        await self._emit("substitution.rejected", {"substitution_id": str(row.id)}, ENTITY, row.id)
        await self._notify(
            "substitution.rejected",
            await self.staff_user_ids([entry.staff_id]),
            {"on_date": row.on_date.isoformat(), "comment": body.comment or ""},
        )
        return await self.get(row.id)

    async def withdraw(
        self, sub_id: uuid.UUID, *, reason: str | None = None, system: bool = False
    ) -> SubstitutionResponse:
        row = await self.subs.get_one(sub_id, for_update=True)
        entry = (
            await self.tts.entry(row.timetable_entry_id)
            if not system
            else (await self._rows(TimetableEntry, [row.timetable_entry_id]))[row.timetable_entry_id]
        )
        if not system:
            me = await self.my_staff()
            if not (me is not None and me.id == entry.staff_id):
                await self._assert_approver(entry)
        if row.status not in ("requested", "approved"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        was = row.status
        if was == "approved":
            session = await self.sessions.of_entry(entry.id, row.on_date)
            if session is not None and session.attendance_status == "not_taken":
                session.staff_id = entry.staff_id
        row.status = "withdrawn"
        await self.db.flush()
        await self._close_instance(row.id, "cancelled")
        await self._audit("withdraw", ENTITY, row.id, {"status": was}, {"status": "withdrawn", "reason": reason})
        return await self.get(row.id)

    # ---- leave hooks (outbox consumers) -------------------------------------------------------------------------
    async def from_leave(self, payload: dict[str, Any]) -> int:
        staff_id = uuid.UUID(str(payload["staff_id"]))
        leave_id = uuid.UUID(str(payload["leave_id"]))
        start, end = date.fromisoformat(payload["from_date"]), date.fromisoformat(payload["to_date"])
        start = max(start, await self.today())
        created = 0
        hods: dict[uuid.UUID | None, list[str]] = {}
        for s in await self.sessions.of_staff_between(staff_id, start, end):
            if s.timetable_entry_id is None or s.status != "scheduled":
                continue
            row = await self.subs.find(s.timetable_entry_id, s.session_date)
            if row is not None and row.status in ("requested", "approved"):
                continue
            if row is None:
                row = TimetableSubstitution(
                    institution_id=self.inst, timetable_entry_id=s.timetable_entry_id, on_date=s.session_date
                )
                self.db.add(row)
            row.substitute_staff_id, row.approved_by = None, None
            row.source, row.status = "leave_auto", "requested"
            row.reason = f"{leave_tag(leave_id)}On approved leave"
            await self.db.flush()
            entry = (await self._rows(TimetableEntry, [s.timetable_entry_id]))[s.timetable_entry_id]
            dept = await self._entry_department(entry)
            await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_KEY,
                entity_type=ENTITY,
                entity_id=row.id,
                started_by=None,
                context={"department_id": str(dept) if dept else None, "leave_id": str(leave_id)},
                title=f"Substitution (leave) · {s.session_date.isoformat()}",
            )
            await self._emit(
                "substitution.requested",
                {
                    "substitution_id": str(row.id),
                    "on_date": s.session_date.isoformat(),
                    "source": "leave_auto",
                    "leave_id": str(leave_id),
                },
                ENTITY,
                row.id,
            )
            hods.setdefault(dept, []).append(s.session_date.isoformat())
            created += 1
        for dept, dates in hods.items():
            await self._notify(
                "substitution.requested",
                await self.hod_user_ids(dept),
                {"course": f"{len(dates)} class(es)", "on_date": ", ".join(sorted(set(dates))), "source": "leave_auto"},
            )
        if created:
            await self._audit("leave_auto", ENTITY, None, None, {"leave_id": str(leave_id), "created": created})
        return created

    async def leave_cancelled(self, payload: dict[str, Any]) -> int:
        leave_id = uuid.UUID(str(payload["leave_id"]))
        n = 0
        for row in await self.subs.of_leave(leave_id):
            if row.status in ("requested", "approved"):
                await self.withdraw(row.id, reason="leave cancelled", system=True)
                n += 1
        return n


def _service(db: Any, instance: WorkflowInstance, actor: Any) -> SubstitutionService:
    return SubstitutionService(
        db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id
    )


@workflow_engine.on(WF_KEY, "approved")
async def _on_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = _service(db, instance, actor)
    row = await svc.subs.get_one(instance.entity_id)
    if row.status == "requested":
        await svc.approve(row.id, SubstitutionDecision(), via_workflow=True)


@workflow_engine.on(WF_KEY, "rejected")
async def _on_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = _service(db, instance, actor)
    row = await svc.subs.get_one(instance.entity_id)
    if row.status == "requested":
        await svc.reject(row.id, SubstitutionDecision(), via_workflow=True)


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (
        await db.execute(select(TimetableSubstitution).where(TimetableSubstitution.id == entity_id))
    ).scalar_one_or_none()
    if row is None:
        return None, None
    return f"Substitution · {row.on_date.isoformat()} ({row.source})", "/admin/timetable/substitutions"


__all__ = ["SubstitutionService"]
