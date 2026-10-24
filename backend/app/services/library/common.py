"""Shared plumbing of the Phase 19 services — on the Phase 07 ``StudentServiceBase`` (tenant, audit, outbox,
notifications, settings, institution-local ``today``).

**Visibility** (Prompts/19 "Visibility rules"):

* members — own card (``library_members.user_id`` = caller), consented wards' cards (parents), and for holders of
  ``library:view_all|manage|circulate|fines`` the members of their units: department (students' enrolment department /
  staff department — HOD), faculty, college; institution assignments → all;
* issues / reservations / fines / ILL — through their member.

``rules(member_type)`` reads ``library.member_rules`` (setting, migration 0019 defaults); ``due_date`` moves a due day
forward past holidays (``holidays`` applying to the member's audience) and the weekly-off days (``library.weekly_off``).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, false, func, or_, select, true

from app.core.errors import APIError, ErrorCode
from app.enums.library import MEMBER_RULES
from app.models.hr import Staff
from app.models.library import LibraryCopy, LibraryMember
from app.models.platform import Department, Holiday, User
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.fee_scope import own_student_ids
from app.services.students.common import StudentServiceBase

UNIT_ACTIONS = ("view_all", "manage", "circulate", "fines")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def now_utc() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def rupees(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


def _scope_ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def _institution(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def unit_reader(p: Any) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or any(p.has("library", a) for a in UNIT_ACTIONS)


def visibility_scopes(p: Any) -> list[str]:
    if not unit_reader(p):
        return []
    tabs = [t for t in ("department", "faculty", "college") if _scope_ids(p, t)]
    if _institution(p):
        tabs.append("all")
    return tabs


def _unit_user_ids(p: Any) -> Any | None:
    """Users (students + staff) in the principal's department / faculty / college scopes."""
    depts = _scope_ids(p, "department")
    faculties = _scope_ids(p, "faculty")
    colleges = _scope_ids(p, "college")
    if not (depts or faculties or colleges):
        return None
    dept_q: list[Any] = []
    if depts:
        dept_q.append(StudentProgramEnrollment.department_id.in_(depts))
    if faculties:
        dept_q.append(
            StudentProgramEnrollment.department_id.in_(
                select(Department.id).where(Department.faculty_id.in_(faculties))
            )
        )
    if colleges:
        dept_q.append(StudentProgramEnrollment.college_id.in_(colleges))
    students = (
        select(Student.user_id)
        .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
        .where(or_(*dept_q), Student.user_id.is_not(None))
    )
    staff_q: list[Any] = []
    if depts:
        staff_q.append(Staff.department_id.in_(depts))
    if faculties:
        staff_q.append(Staff.department_id.in_(select(Department.id).where(Department.faculty_id.in_(faculties))))
    if colleges:
        staff_q.append(Staff.college_id.in_(colleges))
    staff = select(Staff.user_id).where(or_(*staff_q), Staff.user_id.is_not(None))
    return students.union(staff)


def member_predicate(p: Any, scope: str | None = None) -> ColumnElement[bool]:
    """Predicate over ``library_members`` the principal may read (``scope='self'`` limits to own + wards)."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    wards = select(Student.user_id).where(
        Student.id.in_(own_student_ids(p, advisees=False)), Student.user_id.is_not(None)
    )
    own: ColumnElement[bool] = or_(LibraryMember.user_id == p.id, LibraryMember.user_id.in_(wards))
    if scope in ("self", "own", "mine") or not unit_reader(p):
        return own
    if _institution(p) and scope in (None, "all"):
        inst: ColumnElement[bool] = LibraryMember.institution_id == p.institution_id
        return inst
    unit = _unit_user_ids(p)
    return or_(own, LibraryMember.user_id.in_(unit)) if unit is not None else own


def visible_member_ids(p: Any, scope: str | None = None) -> Any:
    return select(LibraryMember.id).where(member_predicate(p, scope))


class LibraryBase(StudentServiceBase):
    audit_module = "library"

    def can_circulate(self) -> bool:
        return self.can("library", "circulate") or self.can("library", "manage")

    def require(self, action: str) -> None:
        if not (self.can("library", action) or self.can("library", "manage")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, f"library:{action} required")

    async def lib_setting(self, key: str, default: Any = None) -> Any:
        v = await self.setting("library", key)
        return default if v is None else v

    async def rules(self, member_type: str) -> dict[str, Any]:
        configured = await self.lib_setting("member_rules") or {}
        base = dict(MEMBER_RULES.get(member_type) or MEMBER_RULES["student"])
        if isinstance(configured, dict) and isinstance(configured.get(member_type), dict):
            base.update(configured[member_type])
        return base

    async def due_date(self, start: date, days: int, audience: str = "students") -> date:
        due = start + timedelta(days=days)
        offs = {
            WEEKDAYS.index(d.lower())
            for d in (await self.lib_setting("weekly_off", ["sunday"]) or [])
            if d.lower() in WEEKDAYS
        }
        rows = (
            await self.db.execute(
                select(Holiday.holiday_date, Holiday.end_date).where(
                    Holiday.institution_id == self.inst,
                    Holiday.deleted_at.is_(None),
                    Holiday.applies_to.in_(("all", audience)),
                    Holiday.holiday_date <= due + timedelta(days=60),
                    (Holiday.end_date.is_(None) & (Holiday.holiday_date >= start)) | (Holiday.end_date >= start),
                )
            )
        ).all()
        closed: set[date] = set()
        for a, b in rows:
            d = a
            while d <= (b or a):
                closed.add(d)
                d += timedelta(days=1)
        guard = 0
        while (due.weekday() in offs or due in closed) and guard < 60:
            due += timedelta(days=1)
            guard += 1
        return due

    # ---- lookups ----------------------------------------------------------------------------------------------------
    async def member(self, member_id: uuid.UUID, *, for_update: bool = False) -> LibraryMember:
        q = select(LibraryMember).where(
            LibraryMember.id == member_id, LibraryMember.institution_id == self.inst, member_predicate(self.principal)
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Library member not found")
        return row

    async def member_by(
        self, *, member_code: str | None = None, user_id: uuid.UUID | None = None, id_card_token: str | None = None
    ) -> LibraryMember:
        q = select(LibraryMember).where(LibraryMember.institution_id == self.inst)
        if member_code:
            q = q.where(LibraryMember.member_code == member_code.strip())
        elif user_id:
            q = q.where(LibraryMember.user_id == user_id)
        elif id_card_token:
            from app.services.student_records_service import verify_token

            res = await verify_token(id_card_token)
            reg = getattr(res, "registration_number", None) if getattr(res, "valid", False) else None
            if not reg:
                raise APIError(404, ErrorCode.NOT_FOUND, "ID card not recognised")
            q = q.where(
                LibraryMember.user_id.in_(
                    select(Student.user_id).where(
                        Student.registration_number == reg, Student.institution_id == self.inst
                    )
                )
            )
        else:
            raise APIError(422, ErrorCode.VALIDATION, "member_code, user_id or id_card_token is required")
        row = (await self.db.execute(q.with_for_update())).scalars().first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Library member not found")
        return row

    async def my_members(self) -> list[LibraryMember]:
        if self.principal is None:
            return []
        return list(
            (
                await self.db.execute(
                    select(LibraryMember).where(
                        LibraryMember.institution_id == self.inst, LibraryMember.user_id == self.principal.id
                    )
                )
            )
            .scalars()
            .all()
        )

    async def copy_by(
        self,
        *,
        barcode: str | None = None,
        accession_number: str | None = None,
        rfid_tag: str | None = None,
        for_update: bool = True,
    ) -> LibraryCopy:
        q = select(LibraryCopy).where(LibraryCopy.institution_id == self.inst)
        if rfid_tag:
            from app.core.features import is_enabled

            if not await is_enabled(self.inst, "library.rfid_barcode"):
                raise APIError(
                    403, ErrorCode.FEATURE_DISABLED, "RFID scanning is not enabled", {"feature": "library.rfid_barcode"}
                )
            q = q.where(LibraryCopy.rfid_tag == rfid_tag.strip())
        elif barcode:
            q = q.where(or_(LibraryCopy.barcode == barcode.strip(), LibraryCopy.accession_number == barcode.strip()))
        elif accession_number:
            q = q.where(LibraryCopy.accession_number == accession_number.strip())
        else:
            raise APIError(422, ErrorCode.VALIDATION, "barcode, accession_number or rfid_tag is required")
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalars().first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Copy not found")
        return row

    async def member_names(self, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not user_ids:
            return {}
        rows = (
            await self.db.execute(
                select(User.id, func.coalesce(User.display_name, User.username)).where(User.id.in_(list(set(user_ids))))
            )
        ).all()
        return {r[0]: r[1] for r in rows}

    async def student_of_user(self, user_id: uuid.UUID) -> tuple[Student | None, StudentProgramEnrollment | None]:
        st = (
            (
                await self.db.execute(
                    select(Student).where(Student.user_id == user_id, Student.institution_id == self.inst)
                )
            )
            .scalars()
            .first()
        )
        if st is None:
            return None, None
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment)
                .where(StudentProgramEnrollment.student_id == st.id, StudentProgramEnrollment.deleted_at.is_(None))
                .order_by(
                    (StudentProgramEnrollment.status == "active").desc(), StudentProgramEnrollment.created_at.desc()
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return st, e
