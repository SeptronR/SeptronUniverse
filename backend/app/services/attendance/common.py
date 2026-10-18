"""Shared plumbing of the Phase 11 services — repositories, ``attendance.*`` settings, regulation rules per enrolment
(``RulesResolver``: ``attendance_min_pct`` / ``condonation_floor_pct`` / ``condonation_fee_paise`` /
``attendance_mode`` / ``cia_pass_min_pct``), the marking permission of a session and the percentage arithmetic.

Built on the Phase 10 ``TimetableBase`` (→ Phase 09 ``RegistrationBase`` → Phase 07 ``StudentServiceBase``): tenant,
audit, outbox, notifications, institution-local ``today``, terms, the caller's staff row and the department filter.

**Percentages** (Prompts/11 §11.6 ``summary_service``)::

    pct = (present + on_duty + late) / (marked − exempt) × 100      (100 when nothing counted yet)
    sessions_needed_for_threshold = smallest n with (attended + n) / (counted + n) ≥ min
    sessions_can_miss            = largest m with attended / (counted + m) ≥ min

``leave`` / ``medical`` count as not attended (they are stored as such; the DDL ``absent`` column holds every
not-attended mark). Only sessions that were conducted / had attendance taken count.
"""

import math
import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.academic import BatchSection
from app.models.offerings import CourseOfferingFaculty
from app.models.students import Student, StudentProgramEnrollment
from app.models.timetable import ClassSession, Room
from app.repositories.attendance_repository import (
    AttendanceRepository,
    CondonationRepository,
    EligibilityRepository,
    OdRepository,
    SummaryRepository,
)
from app.repositories.timetable_scope import is_staff
from app.services.academics.rules import RulesResolver
from app.services.timetable.common import TimetableBase, now_utc, rule

ATT = "attendance"


def q2(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct_of(attended: int, counted: int) -> float:
    if counted <= 0:
        return 100.0
    return round(attended * 100.0 / counted, 2)


def band(pct: float, min_pct: float, floor_pct: float) -> str:
    if pct >= min_pct:
        return "eligible"
    if pct >= floor_pct:
        return "condonable"
    return "not_eligible"


def sessions_needed(attended: int, counted: int, min_pct: float) -> int:
    if counted <= 0 or pct_of(attended, counted) >= min_pct or min_pct >= 100:
        return 0
    return max(0, math.ceil((min_pct * counted - 100 * attended) / (100 - min_pct)))


def sessions_can_miss(attended: int, counted: int, min_pct: float) -> int:
    if min_pct <= 0:
        return 9999
    return max(0, math.floor(100 * attended / min_pct - counted))


def totals_of(c: dict[str, int]) -> dict[str, int]:
    """DDL counters from the aggregate (``absent`` = every not-attended mark)."""
    present, late, od, exempt = c.get("present", 0), c.get("late", 0), c.get("on_duty", 0), c.get("exempt", 0)
    total = c.get("marked", 0)
    return {
        "total_sessions": total,
        "present": present,
        "late": late,
        "on_duty": od,
        "exempt": exempt,
        "absent": max(0, total - present - late - od - exempt),
    }


def attended_counted(t: dict[str, int]) -> tuple[int, int]:
    return t["present"] + t["on_duty"] + t["late"], t["total_sessions"] - t["exempt"]


def student_name(s: Student | None) -> str | None:
    if s is None:
        return None
    return " ".join(p for p in (s.first_name, s.last_name) if p)


class AttendanceBase(TimetableBase):
    audit_module = ATT

    def __init__(
        self, db: AsyncSession, principal: Any, request: Request | None = None, institution_id: uuid.UUID | None = None
    ):
        super().__init__(db, principal, request, institution_id)
        self.marks = AttendanceRepository(db, principal, self.inst)
        self.summaries = SummaryRepository(db, principal, self.inst)
        self.ods = OdRepository(db, principal, self.inst)
        self.condonations = CondonationRepository(db, principal, self.inst)
        self.elig = EligibilityRepository(db, principal, self.inst)
        self._rules: dict[uuid.UUID, dict[str, Any]] = {}

    # ---- context -------------------------------------------------------------------------------------------------
    async def att_setting(self, key: str, default: Any = None, college_id: uuid.UUID | None = None) -> Any:
        value = await self.setting(ATT, key, college_id)
        return default if value is None else value

    async def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo((await self.institution()).timezone or "Asia/Kolkata")
        except Exception:  # noqa: BLE001
            return ZoneInfo("Asia/Kolkata")

    async def local_now(self) -> datetime:
        return now_utc().astimezone(await self.tz())

    async def rules_for_pr(self, pr_id: uuid.UUID) -> dict[str, Any]:
        if pr_id not in self._rules:
            try:
                self._rules[pr_id] = await RulesResolver(self.db).for_program_regulation(pr_id)
            except APIError:
                self._rules[pr_id] = {"attendance_min_pct": 75, "condonation_floor_pct": 65}
        return self._rules[pr_id]

    async def enrolments(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[StudentProgramEnrollment, Student]]:
        ids = [i for i in set(ids) if i]
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(StudentProgramEnrollment, Student)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(StudentProgramEnrollment.id.in_(ids))
            )
        ).all()
        return {e.id: (e, s) for e, s in rows}

    async def thresholds(self, enrolment: StudentProgramEnrollment | None) -> tuple[float, float]:
        if enrolment is None:
            return 75.0, 65.0
        r = await self.rules_for_pr(enrolment.program_regulation_id)
        return float(r.get("attendance_min_pct") or 75), float(r.get("condonation_floor_pct") or 0)

    async def session_labels(self, s: ClassSession) -> dict[str, Any]:
        oc = await self.offering_courses([s.offering_id])
        course = oc.get(s.offering_id, (None, None))[1]
        rooms = await self._rows(Room, [s.room_id])
        section_id = await self.marks.section_of(s)
        sections = await self._rows(BatchSection, [section_id])
        return {
            "course_code": course.code if course else None,
            "course_title": course.title if course else None,
            "room_code": rooms[s.room_id].code if s.room_id in rooms else None,
            "section_name": sections[section_id].name if section_id in sections else None,
        }

    # ---- who may mark ------------------------------------------------------------------------------------------------
    async def teaches(self, s: ClassSession) -> bool:
        me = await self.my_staff()
        if me is None:
            return False
        if s.staff_id == me.id:  # substituted sessions belong to the substitute
            return True
        n = (
            await self.db.execute(
                select(func.count()).where(
                    CourseOfferingFaculty.offering_id == s.offering_id, CourseOfferingFaculty.staff_id == me.id
                )
            )
        ).scalar_one()
        return bool(n)

    async def unit_admin(self, s: ClassSession) -> bool:
        """HOD (department) / registrar (institution) — ``attendance:view_all`` or ``edit_finalized`` over the unit."""
        if self.principal is None or getattr(self.principal, "is_super_admin", False):
            return True
        if not (self.can(ATT, "view_all") or self.can(ATT, "edit_finalized")):
            return False
        depts = await self.department_filter()
        if depts is None:
            return True
        off = (await self.offering_courses([s.offering_id])).get(s.offering_id, (None, None))[0]
        return off is not None and off.department_id in depts

    async def may_mark(self, s: ClassSession) -> bool:
        if self.principal is None or getattr(self.principal, "is_super_admin", False):
            return True
        if not self.can(ATT, "mark"):
            return False
        return await self.teaches(s) or await self.unit_admin(s)

    async def assert_mark(self, s: ClassSession) -> None:
        if not await self.may_mark(s):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may mark attendance of your own sessions only")

    def assert_staff(self) -> None:
        if not is_staff(self.principal):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Staff only")

    async def assert_markable(self, s: ClassSession) -> None:
        if s.attendance_status == "finalized":
            raise APIError(409, ErrorCode.RECORD_LOCKED, "Attendance of this session is finalized")
        if s.status not in ("scheduled", "conducted"):
            raise rule(f"The session is {s.status}", "SESSION_NOT_ACTIVE")
        today = await self.today()
        ahead = int(await self.att_setting("future_marking_days", 0))
        if s.session_date > today + timedelta(days=ahead):
            raise rule("The session is in the future", "FUTURE_SESSION", session_date=s.session_date.isoformat())

    async def assert_student_visible(self, enrolment_id: uuid.UUID) -> uuid.UUID:
        """Staff filing for a student: the enrolment must be one they teach / advise, or in their units."""
        from app.repositories.timetable_scope import record_predicate

        found = (
            await self.db.execute(
                select(StudentProgramEnrollment.id).where(
                    StudentProgramEnrollment.id == enrolment_id,
                    StudentProgramEnrollment.institution_id == self.inst,
                    record_predicate(self.principal, None, StudentProgramEnrollment.id, "all"),
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        return enrolment_id

    async def learner(self, ward_id: uuid.UUID | None = None) -> tuple[Student, StudentProgramEnrollment]:
        """The calling student, or a consented ward of the calling parent (404 otherwise)."""
        if ward_id is None:
            return await self.me()
        from app.repositories.timetable_scope import learner_enrollment_ids

        row = (
            await self.db.execute(
                select(Student, StudentProgramEnrollment)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(
                    Student.id == ward_id,
                    StudentProgramEnrollment.id.in_(learner_enrollment_ids(self.principal)),
                    StudentProgramEnrollment.status.in_(("active", "provisional", "admitted", "detained")),
                )
                .order_by(StudentProgramEnrollment.created_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        return row[0], row[1]


def as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


__all__ = [
    "ATT",
    "AttendanceBase",
    "as_date",
    "attended_counted",
    "band",
    "pct_of",
    "q2",
    "rule",
    "sessions_can_miss",
    "sessions_needed",
    "student_name",
    "totals_of",
]
