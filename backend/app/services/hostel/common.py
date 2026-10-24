"""Shared plumbing of the Phase 20 services — on the Phase 07 ``StudentServiceBase``.

**Visibility** (Prompts/20 "Visibility rules"):

* **hostels** — wardens own the hostels whose ``warden_staff_id`` is their staff record (plus any role assignment
  scoped ``hostel:<id>`` — gate staff, deputy wardens); college-scoped holders see their college's hostels; institution
  assignments (registrar, institution admin, auditor) see all (reported as ``all``); HODs / class advisors have no
  hostel list access of their own;
* **resident rows** (allocations, leaves, mess, discipline, visitors, roll-call entries) — own / consented wards /
  advisees (class advisors), the hostels above, and department / faculty units of the enrolment for ``view_all``
  holders (HOD — a ``hostel_id`` filter never widens that).

``invoice(...)`` raises Phase 12 linkage invoices; ``student_ref`` decorates enrolments.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicYear, Program
from app.models.hostel import Hostel
from app.models.hr import Staff
from app.models.platform import Department
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.fee_scope import own_enrollment_ids
from app.schemas.hostel import HostelStudentRef
from app.services.students.common import StudentServiceBase

UNIT_ACTIONS = ("view_all", "manage", "allot", "warden", "roll_call", "mess_manage", "discipline", "gate")


def now_utc() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def institution_scope(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def hostel_reader(p: Any) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or any(p.has("hostel", a) for a in UNIT_ACTIONS)


def warden_hostel_ids(p: Any) -> Any:
    staff = select(Staff.id).where(Staff.user_id == p.id, Staff.deleted_at.is_(None))
    return select(Hostel.id).where(
        or_(Hostel.warden_staff_id.in_(staff), Hostel.id.in_(_ids(p, "hostel") or [uuid.uuid4()]))
    )


def hostel_predicate(p: Any) -> ColumnElement[bool]:
    """``hostels`` the principal may see (structure / occupancy / hostel-anchored queues)."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None or not hostel_reader(p):
        return false()
    if institution_scope(p) and (p.has("hostel", "view_all") or p.has("hostel", "manage")):
        inst: ColumnElement[bool] = Hostel.institution_id == p.institution_id
        return inst
    parts: list[ColumnElement[bool]] = [Hostel.id.in_(warden_hostel_ids(p))]
    if _ids(p, "college") and (p.has("hostel", "view_all") or p.has("hostel", "manage")):
        parts.append(Hostel.college_id.in_(_ids(p, "college")))
    return or_(*parts)


def visibility_scopes(p: Any) -> list[str]:
    if p is None or getattr(p, "is_super_admin", False):
        return ["all"]
    tabs = []
    if hostel_reader(p):
        tabs.append("own")
    if _ids(p, "department") and p.has("hostel", "view_all"):
        tabs.append("department")
    if _ids(p, "college") and (p.has("hostel", "view_all") or p.has("hostel", "manage")):
        tabs.append("college")
    if institution_scope(p) and (p.has("hostel", "view_all") or p.has("hostel", "manage")):
        tabs.append("all")
    return tabs


def visible_hostel_ids(p: Any) -> Any:
    return select(Hostel.id).where(Hostel.deleted_at.is_(None), hostel_predicate(p))


def resident_predicate(
    p: Any, enrol_col: Any, hostel_col: Any | None, *, department_only: bool = False
) -> ColumnElement[bool]:
    """Rows keyed by an enrolment (+ optionally a hostel) the principal may read."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    own: ColumnElement[bool] = enrol_col.in_(own_enrollment_ids(p, advisees=p.has("hostel", "view")))
    parts: list[ColumnElement[bool]] = [own]
    depts = _ids(p, "department")
    faculties = _ids(p, "faculty")
    if p.has("hostel", "view_all") and (depts or faculties):
        dq: list[ColumnElement[bool]] = []
        if depts:
            dq.append(StudentProgramEnrollment.department_id.in_(depts))
        if faculties:
            dq.append(
                StudentProgramEnrollment.department_id.in_(
                    select(Department.id).where(Department.faculty_id.in_(faculties))
                )
            )
        parts.append(enrol_col.in_(select(StudentProgramEnrollment.id).where(or_(*dq))))
    if department_only:
        return or_(*parts)
    if hostel_col is not None and hostel_reader(p):
        parts.append(hostel_col.in_(visible_hostel_ids(p)))
    return or_(*parts)


class HostelBase(StudentServiceBase):
    audit_module = "hostel"

    def require(self, *actions: str) -> None:
        if any(self.can("hostel", a) for a in actions) or self.can("hostel", "manage"):
            return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, f"hostel:{'|'.join(actions)} required")

    async def hostel(self, hostel_id: uuid.UUID, *, for_update: bool = False) -> Hostel:
        q = select(Hostel).where(
            Hostel.id == hostel_id,
            Hostel.institution_id == self.inst,
            Hostel.deleted_at.is_(None),
            hostel_predicate(self.principal),
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Hostel not found")
        return row

    async def owns_hostel(self, hostel_id: uuid.UUID) -> bool:
        if self.principal is None or getattr(self.principal, "is_super_admin", False):
            return True
        hit = (
            await self.db.execute(select(Hostel.id).where(Hostel.id == hostel_id, hostel_predicate(self.principal)))
        ).first()
        return hit is not None

    async def require_hostel(self, hostel_id: uuid.UUID, *actions: str) -> None:
        """Operational actions on a hostel: the action (or manage) **and** the hostel inside the caller's scope (403)."""
        self.require(*actions)
        if not await self.owns_hostel(hostel_id):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "This hostel is not yours")

    async def academic_year(self) -> AcademicYear:
        row = (
            await self.db.execute(
                select(AcademicYear)
                .where(AcademicYear.institution_id == self.inst, AcademicYear.deleted_at.is_(None))
                .order_by(AcademicYear.is_current.desc(), AcademicYear.start_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            raise rule("No academic year configured", "NO_ACADEMIC_YEAR")
        return row

    async def refs(self, enrol_ids: list[uuid.UUID]) -> dict[uuid.UUID, HostelStudentRef]:
        if not enrol_ids:
            return {}
        rows = (
            await self.db.execute(
                select(StudentProgramEnrollment.id, Student, Program.code)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .join(Program, Program.id == StudentProgramEnrollment.program_id)
                .where(StudentProgramEnrollment.id.in_(list(set(enrol_ids))))
            )
        ).all()
        return {
            eid: HostelStudentRef(
                enrollment_id=eid,
                student_id=s.id,
                name=" ".join(x for x in (s.first_name, s.last_name) if x),
                registration_number=s.registration_number,
                gender=getattr(s, "gender", None),
                program_code=pc,
            )
            for eid, s, pc in rows
        }

    async def ref(self, enrol_id: uuid.UUID) -> HostelStudentRef:
        return (await self.refs([enrol_id])).get(enrol_id) or HostelStudentRef(enrollment_id=enrol_id)

    async def my_enrolment(self, enrollment_id: uuid.UUID | None = None) -> StudentProgramEnrollment:
        """The caller's own active enrolment (students), or a given one for staff with hostel:allot|manage."""
        if enrollment_id is not None and (self.can("hostel", "allot") or self.can("hostel", "manage")):
            e = (
                await self.db.execute(
                    select(StudentProgramEnrollment).where(
                        StudentProgramEnrollment.id == enrollment_id,
                        StudentProgramEnrollment.institution_id == self.inst,
                    )
                )
            ).scalar_one_or_none()
        else:
            q = select(StudentProgramEnrollment).where(
                StudentProgramEnrollment.id.in_(own_enrollment_ids(self.principal, wards=False, advisees=False)),
                StudentProgramEnrollment.status == "active",
            )
            if enrollment_id is not None:
                q = q.where(StudentProgramEnrollment.id == enrollment_id)
            e = (await self.db.execute(q.limit(1))).scalar_one_or_none()
        if e is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found")
        return e

    async def mine(self, *, wards: bool = False) -> list[uuid.UUID]:
        if self.principal is None:
            return []
        return list(
            (await self.db.execute(own_enrollment_ids(self.principal, wards=wards, advisees=False))).scalars().all()
        )

    async def invoice(
        self, enrol_id: uuid.UUID, source_type: str, source_id: uuid.UUID, items: list[tuple[str, int, str]], label: str
    ) -> uuid.UUID:
        """Phase 12 linkage invoice; ``items`` = (description, paise, head code)."""
        from datetime import timedelta

        from app.schemas.fees import InvoiceCreate, InvoiceItemIn
        from app.services.fees.invoice_service import InvoiceService

        inv = await InvoiceService(self.db, None, self.request, self.inst).create_invoice(
            InvoiceCreate(
                enrollment_id=enrol_id,
                source_type=source_type,
                source_id=source_id,
                description=label[:200],
                items=[InvoiceItemIn(description=d[:200], amount_paise=a, head_code=h) for d, a, h in items if a > 0],
                due_date=await self.today() + timedelta(days=15),
                allow_multiple=True,
            )
        )
        return inv.id

    async def warden_user(self, hostel: Hostel) -> uuid.UUID | None:
        if hostel.warden_staff_id is None:
            return None
        return (
            await self.db.execute(select(Staff.user_id).where(Staff.id == hostel.warden_staff_id))
        ).scalar_one_or_none()

    async def guardian_users(self, enrol_id: uuid.UUID) -> list[uuid.UUID]:
        from app.models.students import StudentGuardian

        return [
            u
            for u in (
                await self.db.execute(
                    select(StudentGuardian.user_id)
                    .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == StudentGuardian.student_id)
                    .where(StudentProgramEnrollment.id == enrol_id, StudentGuardian.user_id.is_not(None))
                )
            )
            .scalars()
            .all()
            if u
        ]

    async def student_user(self, enrol_id: uuid.UUID) -> uuid.UUID | None:
        return (
            await self.db.execute(
                select(Student.user_id)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == enrol_id)
            )
        ).scalar_one_or_none()
