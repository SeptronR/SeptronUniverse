"""Class sessions — Prompts/10 §10.6 ``session_service.py``.

Sessions are the anchor for attendance (Phase 11), lesson-plan delivery (Phase 13) and guest-faculty remuneration
(Phase 06 payroll reads ``conducted`` sessions × ``hourly_rate_paise``).

* **List / today** with ``class_sessions`` visibility (own sessions, taught offerings, confirmed offerings of the
  student / wards; department / faculty / college / all with ``attendance:view_all`` / ``timetable:view_all``).
* **Extra / remedial session**: offering schedulable; the staff member (default: the caller when allocated, else the
  offering's first allocated member) and the room must be free in ``[start, end)`` on that date — overlapping live
  sessions are locked ``FOR UPDATE`` and answer 409 ``CONFLICT``. Emits ``session.created``.
* **Cancel / reschedule** only while ``attendance_status = 'not_taken'`` (else 409 ``RECORD_LOCKED``); reschedule
  marks the old row ``rescheduled`` and creates the new one with the same checks. Students of the offering and the
  faculty member are notified; ``session.cancelled`` / ``session.rescheduled`` emitted.
* **Beat** ``sessions.mark_missed`` (setting ``timetable.mark_missed_sessions``): ``scheduled`` sessions whose end has
  passed (institution-local) without attendance → ``status='conducted'``, ``attendance_status='not_taken'`` — flagged
  for follow-up by Phase 11.
"""

import uuid
from datetime import datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import APIError, ErrorCode
from app.enums.timetable import SCHEDULABLE_OFFERING_STATUSES
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentProgramEnrollment
from app.models.timetable import ClassSession, TimetableEntry
from app.repositories.timetable_scope import session_visibility
from app.schemas.timetable import (
    ClassSessionResponse,
    ExtraSessionCreate,
    SessionCancel,
    SessionReschedule,
    SessionUpdate,
)
from app.services.students.common import snap
from app.services.timetable.common import TT, TimetableBase, rule
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

SESSION_KEYS = ("session_date", "start_time", "end_time", "staff_id", "room_id", "status", "topic", "online_link")


class SessionService(TimetableBase):
    async def list_page(
        self, params: PageParams, scope: str | None, *, section_id: uuid.UUID | None = None, **filters: Any
    ) -> tuple[list[ClassSessionResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.sessions.filtered(scope, **filters)
        if section_id:
            stmt = stmt.where(
                ClassSession.timetable_entry_id.in_(
                    select(TimetableEntry.id).where(TimetableEntry.section_id == section_id)
                )
            )
        if not params.sort:
            stmt = stmt.order_by(ClassSession.session_date, ClassSession.start_time)
        rows, page = await self.sessions.paginate(stmt, params)
        return await self.session_outs(list(rows)), page, session_visibility(self.principal)

    async def today_sessions(self) -> list[ClassSessionResponse]:
        on = await self.today()
        stmt = self.sessions.filtered("self", on=on).order_by(ClassSession.start_time)
        return await self.session_outs(list((await self.db.execute(stmt)).scalars().all()))

    async def get(self, session_id: uuid.UUID) -> ClassSessionResponse:
        return (await self.session_outs([await self.sessions.get_one(session_id)]))[0]

    # ---- writes ------------------------------------------------------------------------------------------------
    async def _assert_write(self, offering: CourseOffering) -> uuid.UUID | None:
        """Returns the caller's staff id when they teach the offering; HOD / registrar otherwise (department)."""
        me = await self.my_staff()
        if me is not None:
            teaches = (
                await self.db.execute(
                    select(func.count()).where(
                        CourseOfferingFaculty.offering_id == offering.id, CourseOfferingFaculty.staff_id == me.id
                    )
                )
            ).scalar_one()
            if teaches:
                return me.id
        if getattr(self.principal, "is_super_admin", False) or self.can(TT, "manage"):
            return None
        depts = await self.department_filter()
        if (self.can(TT, "update") or self.can(TT, "create")) and (depts is None or offering.department_id in depts):
            return None
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may manage sessions of your own offerings only")

    async def _check_free(
        self,
        on: Any,
        start: time,
        end: time,
        *,
        staff_id: uuid.UUID | None,
        room_id: uuid.UUID | None,
        exclude: uuid.UUID | None = None,
    ) -> None:
        if room_id:
            room = await self.rooms.get_one(room_id)
            if not room.is_active:
                raise APIError(422, ErrorCode.VALIDATION, "The room is inactive", {"field": "room_id"})
            clash = await self.sessions.overlapping(on, start, end, room_id=room_id, exclude=exclude)
            if clash:
                raise APIError(
                    409,
                    ErrorCode.CONFLICT,
                    f"Room {room.code} is busy at that time",
                    {"field": "room_id", "kind": "room"},
                )
        if staff_id:
            clash = await self.sessions.overlapping(on, start, end, staff_id=staff_id, exclude=exclude)
            if clash:
                raise APIError(
                    409,
                    ErrorCode.CONFLICT,
                    "The faculty member has another class then",
                    {"field": "staff_id", "kind": "staff"},
                )

    async def _offering(self, offering_id: uuid.UUID) -> CourseOffering:
        off: CourseOffering | None = (await self._rows(CourseOffering, [offering_id])).get(offering_id)
        if off is None or off.deleted_at is not None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course offering not found", {"field": "offering_id"})
        if off.status not in SCHEDULABLE_OFFERING_STATUSES:
            raise rule(
                "Only running offerings can have sessions", "OFFERING_NOT_SCHEDULABLE", offering_status=off.status
            )
        return off

    async def extra(self, body: ExtraSessionCreate) -> ClassSessionResponse:
        off = await self._offering(body.offering_id)
        mine = await self._assert_write(off)
        staff_id = body.staff_id or mine
        if staff_id is None:
            staff_id = (
                await self.db.execute(
                    select(CourseOfferingFaculty.staff_id)
                    .where(CourseOfferingFaculty.offering_id == off.id)
                    .order_by(CourseOfferingFaculty.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
        term = await self.get_term(off.term_id)
        if not (term.start_date <= body.date <= term.end_date):
            raise APIError(422, ErrorCode.VALIDATION, "The date is outside the term", {"field": "date"})
        await self._check_free(body.date, body.start, body.end, staff_id=staff_id, room_id=body.room_id)
        s = ClassSession(
            institution_id=self.inst,
            college_id=off.college_id,
            term_id=off.term_id,
            offering_id=off.id,
            session_date=body.date,
            start_time=body.start,
            end_time=body.end,
            staff_id=staff_id,
            session_type=body.session_type.value,
            topic=body.topic,
            room_id=body.room_id,
            online_link=off.online_class_link,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(s)
                await self.db.flush()
        except IntegrityError as exc:
            raise APIError(
                409, ErrorCode.CONFLICT, "The offering already has a session starting then", {"field": "start"}
            ) from exc
        await self._audit("create", "class_session", s.id, None, snap(s, SESSION_KEYS))
        await self._emit(
            "session.created",
            {"session_id": str(s.id), "offering_id": str(off.id), "date": body.date.isoformat(), "kind": "extra"},
            "class_session",
            s.id,
        )
        await self._notify_students(off.id, "session.created", s, extra={"change": "extra class"})
        return await self.get(s.id)

    async def _locked(self, session_id: uuid.UUID) -> tuple[ClassSession, CourseOffering]:
        s = await self.sessions.get_one(session_id, for_update=True)
        off = (await self._rows(CourseOffering, [s.offering_id]))[s.offering_id]
        await self._assert_write(off)
        return s, off

    @staticmethod
    def _assert_open(s: ClassSession) -> None:
        if s.attendance_status != "not_taken":
            raise APIError(
                409,
                ErrorCode.RECORD_LOCKED,
                f"Attendance is already {s.attendance_status} for this session",
                {"attendance_status": s.attendance_status},
            )

    async def update(self, session_id: uuid.UUID, body: SessionUpdate) -> ClassSessionResponse:
        s, _ = await self._locked(session_id)
        data = body.model_dump(exclude_unset=True)
        old = snap(s, SESSION_KEYS)
        if "status" in data and data["status"] is not None and data["status"] != s.status:
            self._assert_open(s)
            if data["status"] not in ("conducted", "scheduled"):
                raise APIError(
                    422, ErrorCode.VALIDATION, "Use cancel / reschedule for those changes", {"field": "status"}
                )
            s.status = str(data["status"])
        if "room_id" in data and data["room_id"] != s.room_id:
            self._assert_open(s)
            await self._check_free(
                s.session_date, s.start_time, s.end_time, staff_id=None, room_id=data["room_id"], exclude=s.id
            )
            s.room_id = data["room_id"]
        if "topic" in data:
            s.topic = data["topic"]
        if "online_link" in data:
            s.online_link = data["online_link"]
        await self.db.flush()
        await self._audit("update", "class_session", s.id, old, snap(s, SESSION_KEYS))
        return await self.get(s.id)

    async def cancel(self, session_id: uuid.UUID, body: SessionCancel) -> ClassSessionResponse:
        s, off = await self._locked(session_id)
        self._assert_open(s)
        if s.status != "scheduled":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"A {s.status} session cannot be cancelled")
        old = snap(s, SESSION_KEYS)
        s.status = "cancelled"
        await self.db.flush()
        await self._audit("cancel", "class_session", s.id, old, {**snap(s, SESSION_KEYS), "reason": body.reason})
        await self._emit(
            "session.cancelled",
            {
                "session_id": str(s.id),
                "offering_id": str(off.id),
                "date": s.session_date.isoformat(),
                "reason": body.reason,
            },
            "class_session",
            s.id,
        )
        await self._notify_students(off.id, "session.cancelled", s, extra={"reason": body.reason or ""})
        return await self.get(s.id)

    async def reschedule(self, session_id: uuid.UUID, body: SessionReschedule) -> ClassSessionResponse:
        s, off = await self._locked(session_id)
        self._assert_open(s)
        if s.status != "scheduled":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"A {s.status} session cannot be rescheduled")
        room_id = body.room_id or s.room_id
        await self._check_free(body.date, body.start, body.end, staff_id=s.staff_id, room_id=room_id, exclude=s.id)
        old = snap(s, SESSION_KEYS)
        s.status = "rescheduled"
        new = ClassSession(
            institution_id=self.inst,
            college_id=s.college_id,
            term_id=s.term_id,
            offering_id=s.offering_id,
            timetable_entry_id=s.timetable_entry_id,
            session_date=body.date,
            start_time=body.start,
            end_time=body.end,
            staff_id=s.staff_id,
            session_type=s.session_type,
            topic=s.topic,
            room_id=room_id,
            online_link=s.online_link,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(new)
                await self.db.flush()
        except IntegrityError as exc:
            raise APIError(409, ErrorCode.CONFLICT, "The offering already has a session starting then") from exc
        await self._audit(
            "reschedule", "class_session", s.id, old, {"new_session_id": str(new.id), "reason": body.reason}
        )
        await self._emit(
            "session.rescheduled",
            {
                "session_id": str(s.id),
                "new_session_id": str(new.id),
                "offering_id": str(off.id),
                "date": body.date.isoformat(),
            },
            "class_session",
            new.id,
        )
        await self._notify_students(off.id, "session.rescheduled", new, extra={"from_date": s.session_date.isoformat()})
        return await self.get(new.id)

    async def _notify_students(
        self, offering_id: uuid.UUID, event: str, s: ClassSession, extra: dict[str, Any]
    ) -> None:
        users = (
            await self.db.execute(
                select(Student.user_id)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .join(
                    CourseRegistration, CourseRegistration.student_program_enrollment_id == StudentProgramEnrollment.id
                )
                .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
                .where(
                    CourseRegistrationItem.offering_id == offering_id,
                    CourseRegistrationItem.status == "confirmed",
                    Student.user_id.is_not(None),
                )
                .distinct()
            )
        ).scalars()
        oc = await self.offering_courses([offering_id])
        course = oc.get(offering_id, (None, None))[1]
        recipients = [*users, *await self.staff_user_ids([s.staff_id])]
        await self._notify(
            event,
            recipients,
            {
                "course": course.code if course else "class",
                "date": s.session_date.isoformat(),
                "time": f"{s.start_time:%H:%M}",
                **{k: str(v) for k, v in extra.items()},
            },
        )

    # ---- beat ----------------------------------------------------------------------------------------------------
    async def mark_missed(self) -> int:
        if not await self.tt_setting("mark_missed_sessions", True):
            return 0
        from app.core.tenancy import institution_tz

        now = datetime.now(institution_tz(await self.institution()))
        stmt = (
            select(ClassSession)
            .where(
                ClassSession.institution_id == self.inst,
                ClassSession.status == "scheduled",
                ClassSession.attendance_status == "not_taken",
                (ClassSession.session_date < now.date())
                | ((ClassSession.session_date == now.date()) & (ClassSession.end_time < now.time())),
            )
            .with_for_update(skip_locked=True)
        )
        rows = list((await self.db.execute(stmt)).scalars().all())
        for s in rows:
            s.status = "conducted"
        await self.db.flush()
        return len(rows)


__all__ = ["SessionService"]
