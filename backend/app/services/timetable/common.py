"""Shared plumbing of the Phase 10 services — repositories, settings, the caller's staff row, write scope of a
timetable (HOD @department, ``college_admin`` @college, registrar @institution) and the response builders that batch
the related rows (courses, slots, rooms, staff, sections) of a page of entries / sessions / substitutions.

Built on the Phase 09 ``RegistrationBase`` (tenant, audit, outbox, notifications, institution-local ``today``,
terms) so every Phase 10 service shares one transaction-aware context.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm, Batch, BatchSection, Program
from app.models.curriculum import Course
from app.models.hr import Staff
from app.models.offerings import CourseOffering
from app.models.timetable import ClassSession, TimeSlot, Timetable, TimetableEntry, TimetableSubstitution
from app.repositories.class_session_repository import ClassSessionRepository
from app.repositories.room_repository import BuildingRepository, RoomRepository
from app.repositories.slot_repository import SlotRepository
from app.repositories.substitution_repository import SubstitutionRepository, leave_of, strip_tag
from app.repositories.timetable_repository import TimetableRepository
from app.schemas.timetable import ClassSessionResponse, EntryOut, SubstitutionResponse
from app.services.academics.context import writable_department_ids
from app.services.registration.common import RegistrationBase, rule

TT = "timetable"


def minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def week_start(d: date) -> date:
    return d - timedelta(days=d.isoweekday() - 1)


def matches_week(pattern: str, d: date) -> bool:
    if pattern == "all":
        return True
    odd = d.isocalendar().week % 2 == 1
    return odd if pattern == "odd" else not odd


class TimetableBase(RegistrationBase):
    audit_module = TT

    def __init__(
        self, db: AsyncSession, principal: Any, request: Request | None = None, institution_id: uuid.UUID | None = None
    ):
        super().__init__(db, principal, request, institution_id)
        self.buildings = BuildingRepository(db, principal, self.inst)
        self.rooms = RoomRepository(db, principal, self.inst)
        self.slots = SlotRepository(db, self.inst)
        self.tts = TimetableRepository(db, principal, self.inst)
        self.sessions = ClassSessionRepository(db, principal, self.inst)
        self.subs = SubstitutionRepository(db, principal, self.inst)

    # ---- context -----------------------------------------------------------------------------------------------
    async def tt_setting(self, key: str, default: Any = None) -> Any:
        value = await self.setting(TT, key)
        return default if value is None else value

    async def my_staff(self) -> Staff | None:
        if self.actor_id is None:
            return None
        return (
            await self.db.execute(
                select(Staff).where(
                    Staff.user_id == self.actor_id, Staff.institution_id == self.inst, Staff.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

    async def default_college(self, college_id: uuid.UUID | None) -> uuid.UUID:
        if college_id:
            return college_id
        colleges: list[uuid.UUID] = [
            sid for st, sid in getattr(self.principal, "scopes", []) if st == "college" and sid
        ]
        if colleges:
            return colleges[0]
        staff = await self.my_staff()
        if staff is not None and staff.college_id:
            college: uuid.UUID = staff.college_id
            return college
        from app.models.platform import College

        first = (
            await self.db.execute(
                select(College.id)
                .where(College.institution_id == self.inst, College.deleted_at.is_(None))
                .order_by(College.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        if first is None:
            raise APIError(422, ErrorCode.VALIDATION, "college_id is required", {"field": "college_id"})
        return first

    async def term_row(self, term_id: uuid.UUID) -> AcademicTerm:
        return await self.get_term(term_id)

    async def scope_department(self, scope_type: str, scope_id: uuid.UUID) -> uuid.UUID | None:
        """Department owning a timetable scope (a section's / batch's programme department)."""
        if scope_type == "department":
            return scope_id
        batch_id = scope_id
        if scope_type == "section":
            sec = (await self.db.execute(select(BatchSection).where(BatchSection.id == scope_id))).scalar_one_or_none()
            if sec is None:
                return None
            batch_id = sec.batch_id
        row = (
            await self.db.execute(
                select(Program.department_id).join(Batch, Batch.program_id == Program.id).where(Batch.id == batch_id)
            )
        ).scalar_one_or_none()
        return row

    def _institution_wide(self) -> bool:
        return bool(
            getattr(self.principal, "is_super_admin", False)
            or self.principal is None
            or any(st == "institution" for st, _ in getattr(self.principal, "scopes", []))
        )

    async def can_edit(self, tt: Timetable) -> bool:
        """Registrar / ``manage`` @institution everywhere; ``college_admin`` (``manage`` @college) its college; HOD
        (``create`` / ``update`` @department) the scopes of its departments."""
        if not (self.can(TT, "manage") or self.can(TT, "create") or self.can(TT, "update")):
            return False
        if self._institution_wide():
            return True
        colleges = [sid for st, sid in getattr(self.principal, "scopes", []) if st == "college" and sid]
        if tt.college_id in colleges:
            return True
        writable = await writable_department_ids(self.db, self.principal)
        if writable is None:
            return True
        dept = await self.scope_department(tt.scope_type, tt.scope_id)
        return dept is not None and dept in writable

    async def assert_edit(self, tt: Timetable) -> None:
        if not await self.can_edit(tt):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may edit timetables of your own department only")

    async def department_filter(self) -> list[uuid.UUID] | None:
        """``None`` = every department (institution scope); otherwise the departments the caller administers
        (department / faculty / college scopes)."""
        if self._institution_wide():
            return None
        writable = await writable_department_ids(self.db, self.principal)
        return None if writable is None else sorted(writable, key=str)

    # ---- loaders -------------------------------------------------------------------------------------------------
    async def _rows(self, model: Any, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, Any]:
        return await self.offerings.rows(model, ids)

    async def offering_courses(self, offering_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[CourseOffering, Any]]:
        offs = await self._rows(CourseOffering, offering_ids)
        courses = await self._rows(Course, [o.course_id for o in offs.values()])
        return {oid: (o, courses.get(o.course_id)) for oid, o in offs.items()}

    async def entry_outs(self, entries: Sequence[TimetableEntry]) -> list[EntryOut]:
        entries = list(entries)
        oc = await self.offering_courses([e.offering_id for e in entries])
        slots = await self.slots.rows([e.time_slot_id for e in entries])
        rooms = await self.rooms.rows([e.room_id for e in entries])
        staff = await self._rows(Staff, [e.staff_id for e in entries])
        sections = await self._rows(BatchSection, [e.section_id for e in entries])
        out = []
        for e in entries:
            off, course = oc.get(e.offering_id, (None, None))
            slot = slots.get(e.time_slot_id)
            end = slot.end_time if slot else None
            if slot is not None and e.slot_span > 1:
                try:
                    end = (await self.slots.span(slot, e.slot_span))[-1].end_time
                except APIError:
                    end = slot.end_time
            out.append(
                EntryOut(
                    id=e.id,
                    timetable_id=e.timetable_id,
                    term_id=e.term_id,
                    offering_id=e.offering_id,
                    course_code=course.code if course else None,
                    course_title=course.title if course else None,
                    section_id=e.section_id,
                    section_name=sections[e.section_id].name if e.section_id in sections else None,
                    day_of_week=e.day_of_week,
                    time_slot_id=e.time_slot_id,
                    slot_name=slot.name if slot else None,
                    start_time=slot.start_time if slot else None,
                    end_time=end,
                    room_id=e.room_id,
                    room_code=rooms[e.room_id].code if e.room_id in rooms else None,
                    staff_id=e.staff_id,
                    staff_name=staff[e.staff_id].full_name if e.staff_id in staff else None,
                    session_type=e.session_type,
                    week_pattern=e.week_pattern,
                    slot_span=e.slot_span,
                    is_active=e.is_active,
                )
            )
        return out

    async def session_outs(self, rows: Sequence[ClassSession]) -> list[ClassSessionResponse]:
        rows = list(rows)
        oc = await self.offering_courses([s.offering_id for s in rows])
        slots = await self.slots.rows([s.time_slot_id for s in rows])
        rooms = await self.rooms.rows([s.room_id for s in rows])
        staff = await self._rows(Staff, [s.staff_id for s in rows])
        entries = await self._rows(TimetableEntry, [s.timetable_entry_id for s in rows])
        sections = await self._rows(BatchSection, [e.section_id for e in entries.values()])
        out = []
        for s in rows:
            _, course = oc.get(s.offering_id, (None, None))
            entry = entries.get(s.timetable_entry_id) if s.timetable_entry_id else None
            out.append(
                ClassSessionResponse(
                    id=s.id,
                    offering_id=s.offering_id,
                    course_code=course.code if course else None,
                    course_title=course.title if course else None,
                    timetable_entry_id=s.timetable_entry_id,
                    session_date=s.session_date,
                    time_slot_id=s.time_slot_id,
                    slot_name=slots[s.time_slot_id].name if s.time_slot_id in slots else None,
                    start_time=s.start_time,
                    end_time=s.end_time,
                    staff_id=s.staff_id,
                    staff_name=staff[s.staff_id].full_name if s.staff_id in staff else None,
                    room_id=s.room_id,
                    room_code=rooms[s.room_id].code if s.room_id in rooms else None,
                    section_name=(sections[entry.section_id].name if entry and entry.section_id in sections else None),
                    session_type=s.session_type,
                    topic=s.topic,
                    online_link=s.online_link,
                    status=s.status,
                    attendance_status=s.attendance_status,
                    substituted=bool(entry is not None and entry.staff_id and s.staff_id != entry.staff_id),
                )
            )
        return out

    async def substitution_outs(self, rows: Sequence[TimetableSubstitution]) -> list[SubstitutionResponse]:
        rows = list(rows)
        entries = await self._rows(TimetableEntry, [r.timetable_entry_id for r in rows])
        oc = await self.offering_courses([e.offering_id for e in entries.values()])
        slots = await self.slots.rows([e.time_slot_id for e in entries.values()])
        sections = await self._rows(BatchSection, [e.section_id for e in entries.values()])
        staff = await self._rows(Staff, [e.staff_id for e in entries.values()] + [r.substitute_staff_id for r in rows])
        out = []
        for r in rows:
            e = entries.get(r.timetable_entry_id)
            _, course = oc.get(e.offering_id, (None, None)) if e else (None, None)
            out.append(
                SubstitutionResponse(
                    id=r.id,
                    timetable_entry_id=r.timetable_entry_id,
                    on_date=r.on_date,
                    course_code=course.code if course else None,
                    slot_name=slots[e.time_slot_id].name if e and e.time_slot_id in slots else None,
                    section_name=sections[e.section_id].name if e and e.section_id in sections else None,
                    staff_id=e.staff_id if e else None,
                    staff_name=staff[e.staff_id].full_name if e and e.staff_id in staff else None,
                    substitute_staff_id=r.substitute_staff_id,
                    substitute_name=(
                        staff[r.substitute_staff_id].full_name if r.substitute_staff_id in staff else None
                    ),
                    reason=strip_tag(r.reason),
                    source=r.source,
                    status=r.status,
                    leave_id=leave_of(r.reason),
                    approved_by=r.approved_by,
                    created_at=r.created_at,
                )
            )
        return out

    async def slot_window(self, entry: TimetableEntry) -> tuple[TimeSlot, time, time]:
        slot = await self.slots.get_one(entry.time_slot_id)
        span = await self.slots.span(slot, entry.slot_span) if entry.slot_span > 1 else [slot]
        return slot, span[0].start_time, span[-1].end_time

    async def staff_user_ids(self, staff_ids: Sequence[uuid.UUID | None]) -> list[uuid.UUID]:
        rows = await self._rows(Staff, staff_ids)
        return [s.user_id for s in rows.values() if s.user_id]

    async def hod_user_ids(self, department_id: uuid.UUID | None) -> list[uuid.UUID]:
        if department_id is None:
            return []
        from app.models.platform import Role, UserRole

        rows = await self.db.execute(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.slug == "hod", UserRole.scope_type == "department", UserRole.scope_id == department_id)
        )
        return list(dict.fromkeys(rows.scalars().all()))


def now_utc() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


__all__ = ["TT", "TimetableBase", "matches_week", "minutes", "now_utc", "rule", "week_start"]
