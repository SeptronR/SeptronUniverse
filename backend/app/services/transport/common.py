"""Shared plumbing of the Phase 21 services — on the Phase 07 ``StudentServiceBase``.

**Visibility** (Prompts/21 "Visibility rules"):

* **fleet / routes** — institution assignments with ``transport:manage|view_all`` (transport manager, accountant,
  auditor) see all (``all``); college-scoped holders (college admin) their college's vehicles / routes; drivers their
  own vehicle (``vehicles.driver_staff_id``) and its routes; passengers read routes only through ``/transport/me`` and
  the public route list;
* **allocations** — own (student ``person_id`` = the caller's student, staff = the caller's staff record), wards
  (``student_guardians``), advisees (``transport:view`` class advisors), department / faculty units for ``view_all``
  holders scoped there (HOD — enrolment department for students, staff department for staff), the caller's colleges
  (route ``college_id``), all for institution-scoped ``manage|view_all``;
* **trips** — the fleet scope above, drivers their own trips (``transport_trips.driver_staff_id``).

``person_id`` of a student allocation is ``students.id``; the fee invoice goes to the student's current enrolment.
"""

import math
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicYear
from app.models.hr import Staff
from app.models.platform import Department
from app.models.students import Student, StudentProgramEnrollment
from app.models.transport import TransportAllocation, TransportRoute, TransportTrip, Vehicle
from app.repositories.fee_scope import own_student_ids
from app.services.students.common import StudentServiceBase

T = "transport"
READ_ACTIONS = ("view_all", "manage")


def now_utc() -> datetime:
    return datetime.now(UTC)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def institution_scope(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def is_reader(p: Any) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or any(p.has(T, a) for a in READ_ACTIONS)


def my_staff_ids(p: Any) -> Any:
    return select(Staff.id).where(Staff.user_id == getattr(p, "id", None), Staff.deleted_at.is_(None))


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def segment_distance_m(lat: float, lng: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from a point to segment a–b on a local equirectangular projection (good to metres at city scale)."""
    k = math.cos(math.radians(lat)) * 111320.0
    px, py = lng * k, lat * 110540.0
    ax, ay, bx, by = a[1] * k, a[0] * 110540.0, b[1] * k, b[0] * 110540.0
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def fleet_predicate(p: Any, college_col: Any, driver_col: Any | None = None) -> ColumnElement[bool]:
    """Vehicles / routes / trips the principal may read (``driver_col`` = the row's driver staff id)."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    parts: list[ColumnElement[bool]] = []
    if is_reader(p):
        if institution_scope(p):
            return true()
        if _ids(p, "college"):
            parts.append(college_col.in_(_ids(p, "college")))
    if driver_col is not None and p.has(T, "driver"):
        parts.append(driver_col.in_(my_staff_ids(p)))
    return or_(*parts) if parts else false()


def route_predicate(p: Any) -> ColumnElement[bool]:
    driver_routes = (
        TransportRoute.vehicle_id.in_(select(Vehicle.id).where(Vehicle.driver_staff_id.in_(my_staff_ids(p))))
        if p is not None and getattr(p, "id", None) is not None and p.has(T, "driver")
        else false()
    )
    return or_(fleet_predicate(p, TransportRoute.college_id), driver_routes)


def trip_predicate(p: Any) -> ColumnElement[bool]:
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    parts: list[ColumnElement[bool]] = []
    if is_reader(p):
        if institution_scope(p):
            return true()
        if _ids(p, "college"):
            parts.append(
                TransportTrip.route_id.in_(
                    select(TransportRoute.id).where(TransportRoute.college_id.in_(_ids(p, "college")))
                )
            )
    if p.has(T, "driver"):
        parts.append(TransportTrip.driver_staff_id.in_(my_staff_ids(p)))
    return or_(*parts) if parts else false()


def allocation_predicate(p: Any, *, department_only: bool = False) -> ColumnElement[bool]:
    A = TransportAllocation
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    if not department_only and is_reader(p) and institution_scope(p):
        return true()
    parts: list[ColumnElement[bool]] = [
        (A.person_type == "student") & A.person_id.in_(own_student_ids(p, wards=True, advisees=p.has(T, "view"))),
        (A.person_type == "staff") & A.person_id.in_(my_staff_ids(p)),
    ]
    depts = _ids(p, "department")
    faculties = _ids(p, "faculty")
    if p.has(T, "view_all") and (depts or faculties):
        dept_ids: Any = list(depts)
        if faculties:
            dept_ids = select(Department.id).where(
                or_(Department.id.in_(depts or [uuid.uuid4()]), Department.faculty_id.in_(faculties))
            )
        parts.append(
            (A.person_type == "student")
            & A.person_id.in_(
                select(StudentProgramEnrollment.student_id).where(
                    StudentProgramEnrollment.department_id.in_(dept_ids), StudentProgramEnrollment.status == "active"
                )
            )
        )
        parts.append(
            (A.person_type == "staff") & A.person_id.in_(select(Staff.id).where(Staff.department_id.in_(dept_ids)))
        )
    if not department_only and is_reader(p) and _ids(p, "college"):
        parts.append(A.route_id.in_(select(TransportRoute.id).where(TransportRoute.college_id.in_(_ids(p, "college")))))
    return or_(*parts)


def visibility_scopes(p: Any) -> list[str]:
    if p is None or getattr(p, "is_super_admin", False):
        return ["all"]
    tabs = ["own"]
    if _ids(p, "department") and p.has(T, "view_all"):
        tabs.append("department")
    if _ids(p, "college") and is_reader(p):
        tabs.append("college")
    if institution_scope(p) and is_reader(p):
        tabs.append("all")
    return tabs


class TransportBase(StudentServiceBase):
    audit_module = "transport"

    def require(self, *actions: str) -> None:
        if any(self.can(T, a) for a in actions) or self.can(T, "manage"):
            return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, f"transport:{'|'.join(actions)} required")

    async def feature(self, key: str) -> bool:
        from app.core.features import is_enabled

        return await is_enabled(self.inst, key)

    async def require_feature(self, key: str) -> None:
        if not await self.feature(key):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature {key} is disabled", {"feature": key})

    async def my_staff(self) -> Staff | None:
        if self.actor_id is None:
            return None
        return (
            await self.db.execute(
                select(Staff).where(Staff.user_id == self.actor_id, Staff.institution_id == self.inst)
            )
        ).scalar_one_or_none()

    async def my_student(self) -> Student | None:
        if self.actor_id is None:
            return None
        return (
            await self.db.execute(
                select(Student).where(
                    Student.user_id == self.actor_id, Student.institution_id == self.inst, Student.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

    async def vehicle(self, vehicle_id: uuid.UUID, *, for_update: bool = False) -> Vehicle:
        q = select(Vehicle).where(
            Vehicle.id == vehicle_id,
            Vehicle.institution_id == self.inst,
            Vehicle.deleted_at.is_(None),
            fleet_predicate(self.principal, Vehicle.college_id, Vehicle.driver_staff_id),
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Vehicle not found")
        return row

    async def route(self, route_id: uuid.UUID, *, for_update: bool = False, any_scope: bool = False) -> TransportRoute:
        q = select(TransportRoute).where(TransportRoute.id == route_id, TransportRoute.institution_id == self.inst)
        if not any_scope:
            q = q.where(route_predicate(self.principal))
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Route not found")
        return row

    async def trip(self, trip_id: uuid.UUID, *, for_update: bool = False, any_scope: bool = False) -> TransportTrip:
        q = select(TransportTrip).where(TransportTrip.id == trip_id, TransportTrip.institution_id == self.inst)
        if not any_scope:
            q = q.where(trip_predicate(self.principal))
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Trip not found")
        return row

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

    async def current_enrolment(self, student_id: uuid.UUID) -> StudentProgramEnrollment | None:
        return (
            await self.db.execute(
                select(StudentProgramEnrollment)
                .where(StudentProgramEnrollment.student_id == student_id, StudentProgramEnrollment.status == "active")
                .order_by(StudentProgramEnrollment.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def invoice(
        self, enrol_id: uuid.UUID, source_id: uuid.UUID, amount_paise: int, label: str, due: date | None = None
    ) -> uuid.UUID | None:
        """Phase 12 linkage invoice (``source_type='transport_allocation'``, head ``TRANSPORT``)."""
        from datetime import timedelta

        from app.schemas.fees import InvoiceCreate, InvoiceItemIn
        from app.services.fees.invoice_service import InvoiceService

        if amount_paise <= 0:
            return None
        inv = await InvoiceService(self.db, None, self.request, self.inst).create_invoice(
            InvoiceCreate(
                enrollment_id=enrol_id,
                source_type="transport_allocation",
                source_id=source_id,
                description=label[:200],
                items=[InvoiceItemIn(description=label[:200], amount_paise=amount_paise, head_code="TRANSPORT")],
                due_date=due or await self.today() + timedelta(days=15),
                allow_multiple=True,
            )
        )
        return inv.id

    async def person_users(self, person_type: str, person_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        if not person_ids:
            return {}
        model: Any = Student if person_type == "student" else Staff
        return {
            pid: uid
            for pid, uid in (
                await self.db.execute(select(model.id, model.user_id).where(model.id.in_(person_ids)))
            ).all()
            if uid
        }

    async def guardian_users(self, student_ids: list[uuid.UUID]) -> list[uuid.UUID]:
        from app.models.students import StudentGuardian

        if not student_ids:
            return []
        return [
            u
            for u in (
                await self.db.execute(
                    select(StudentGuardian.user_id).where(
                        StudentGuardian.student_id.in_(student_ids),
                        StudentGuardian.user_id.is_not(None),
                        StudentGuardian.portal_access.is_(True),
                    )
                )
            )
            .scalars()
            .all()
            if u
        ]

    async def passenger_users(self, route_id: uuid.UUID, stop_id: uuid.UUID | None = None) -> list[uuid.UUID]:
        q = select(TransportAllocation.person_type, TransportAllocation.person_id).where(
            TransportAllocation.route_id == route_id, TransportAllocation.status.in_(("active", "suspended"))
        )
        if stop_id is not None:
            q = q.where(TransportAllocation.stop_id == stop_id)
        rows = (await self.db.execute(q)).all()
        out: list[uuid.UUID] = []
        for kind in ("student", "staff"):
            out += list((await self.person_users(kind, [pid for t, pid in rows if t == kind])).values())
        return out

    async def manager_audience(self) -> dict[str, Any]:
        return {"roles": ["transport_manager"]}

    async def staff_name(self, staff_id: uuid.UUID | None) -> str | None:
        if staff_id is None:
            return None
        s = (await self.db.execute(select(Staff).where(Staff.id == staff_id))).scalar_one_or_none()
        return s.full_name if s else None
