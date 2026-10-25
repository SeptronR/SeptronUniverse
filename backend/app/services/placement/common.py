"""Shared plumbing of the Phase 28 services (companies, policies, eligibility, drives / offers, profiles, internships,
training, recruiter portal, stats) — on the Phase 27 ``SupportBase`` (people lookups, wards, department predicates, the
``institution_settings`` side store, ScopeTabs).

**Visibility** (Prompts/28 "Visibility rules" / §28.5): self through the caller's enrolments; wards through guardian
links (``placement:wards``); department scope through the enrolment's department (HOD / class advisor holding
``placement:view_all`` at department scope); college scope through ``placement_drives.college_id`` / the enrolment
college; institution-wide for ``placement:view_all`` / ``manage`` at institution scope; **recruiter ownership** through
``companies.recruiter_user_ids @> [user_id]`` — recruiters reach only the drives / applicants of their companies with a
field projection limited to ``placement.consented_fields`` ∩ the student's ``consent_share_profile``.

Side-store kinds (category ``placement_meta``): ``drive:<id>`` (published_at, notified, pending recruiter offers,
recruiter-created flag), ``blacklist:<enrolment>`` (reason / until / source / history), ``training:<id>`` (vendor
cost), ``readiness:<enrolment>`` (training readiness score).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, false, or_, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import cast

from app.models.placement import Company, PlacementDrive, StudentPlacementProfile
from app.models.students import StudentProgramEnrollment
from app.services.student_support.common import (
    SupportBase,
    all_access,
    dept_subquery,
    forbidden,
    is_auditor,
    module_reader,
    not_found,
    now_utc,
    rule,
    scope_ids,
)

__all__ = [
    "PlacementBase",
    "all_access",
    "dept_subquery",
    "forbidden",
    "is_auditor",
    "module_reader",
    "not_found",
    "now_utc",
    "rule",
    "scope_ids",
]

META = "placement_meta"
OFFICER_ACTIONS = ("manage", "drive_manage", "offer_manage", "override_eligibility")


class PlacementBase(SupportBase):
    audit_module = "placement"
    module = "placement"
    meta_category = META

    # ---- roles ------------------------------------------------------------------------------------------------------
    def officer(self) -> bool:
        p = self.principal
        return (
            p is None
            or bool(getattr(p, "is_super_admin", False))
            or any(p.has("placement", a) for a in OFFICER_ACTIONS)
        )

    def require_officer(self, *actions: str) -> None:
        self.require_writer()
        acts = actions or OFFICER_ACTIONS
        if not any(self.can("placement", a) for a in (*acts, "manage")):
            raise forbidden(f"placement:{'|'.join(acts)} required")

    def is_recruiter(self) -> bool:
        p = self.principal
        return p is not None and self.can("placement", "recruiter") and not self.officer()

    async def my_company_ids(self) -> list[uuid.UUID]:
        if self.actor_id is None:
            return []
        rows = await self.db.execute(
            select(Company.id).where(
                Company.institution_id == self.inst,
                Company.deleted_at.is_(None),
                Company.recruiter_user_ids.op("@>")(cast([str(self.actor_id)], JSONB)),
            )
        )
        return [r[0] for r in rows.all()]

    # ---- predicates -------------------------------------------------------------------------------------------------
    async def enrolment_predicate(self, col: Any, scope: str | None = None) -> Any:
        """Rows keyed by an enrolment column: self, wards, department, college, all."""
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return true()
        if scope in (None, "all") and all_access(p, self.module):
            return true()
        parts: list[Any] = []
        if scope in (None, "self", "mine"):
            mine = await self.my_enrollment_ids()
            if mine:
                parts.append(col.in_(mine))
        if scope in (None, "wards") and self.can("placement", "wards"):
            wards = await self.ward_enrollment_ids()
            if wards:
                parts.append(col.in_(wards))
        parts += self.enrolment_dept_predicate(col, scope)
        return or_(*parts) if parts else false()

    async def drive_predicate(self, scope: str | None = None) -> Any:
        """Drives a caller may read: officers / readers by college, recruiters by company, students published only."""
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False):
            return true()
        if all_access(p, self.module):
            return true()
        parts: list[Any] = []
        cols = scope_ids(p, "college")
        if cols and module_reader(p, self.module):
            parts.append(or_(PlacementDrive.college_id.in_(cols), PlacementDrive.college_id.is_(None)))
        elif (scope_ids(p, "department") or scope_ids(p, "faculty")) and module_reader(p, self.module):
            parts.append(PlacementDrive.status != "draft")
        if self.can("placement", "recruiter"):
            companies = await self.my_company_ids()
            if companies:
                parts.append(PlacementDrive.company_id.in_(companies))
        if self.can("placement", "self") or self.can("placement", "wards"):
            parts.append(PlacementDrive.status.in_(("open", "closed", "in_progress", "completed")))
        return or_(*parts) if parts else false()

    async def drive(self, did: uuid.UUID, *, lock: bool = False) -> PlacementDrive:
        stmt = select(PlacementDrive).where(
            PlacementDrive.id == did, PlacementDrive.institution_id == self.inst, await self.drive_predicate()
        )
        if lock:
            stmt = stmt.with_for_update()
        d = (await self.db.execute(stmt)).scalar_one_or_none()
        if d is None:
            raise not_found("Drive")
        return d

    def college_guard(self, college_id: uuid.UUID | None) -> None:
        """A college-scoped officer writes only drives of their colleges (or institution-wide pooled ones)."""
        p = self.principal
        if p is None or all_access(p, self.module):
            return
        cols = scope_ids(p, "college")
        if cols and college_id is not None and college_id not in cols:
            raise forbidden("Drive belongs to another college")

    # ---- lookups ----------------------------------------------------------------------------------------------------
    async def companies_map(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, Company]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        rows = (await self.db.execute(select(Company).where(Company.id.in_(wanted)))).scalars().all()
        return {c.id: c for c in rows}

    async def drives_map(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, PlacementDrive]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        rows = (await self.db.execute(select(PlacementDrive).where(PlacementDrive.id.in_(wanted)))).scalars().all()
        return {d.id: d for d in rows}

    async def profile_of(self, enrollment_id: uuid.UUID, *, lock: bool = False, create: bool = True) -> Any:
        stmt = select(StudentPlacementProfile).where(
            StudentPlacementProfile.student_program_enrollment_id == enrollment_id
        )
        if lock:
            stmt = stmt.with_for_update()
        prof = (await self.db.execute(stmt)).scalar_one_or_none()
        if prof is None and create:
            prof = StudentPlacementProfile(
                institution_id=self.inst, student_program_enrollment_id=enrollment_id, placement_status="unplaced"
            )
            self.db.add(prof)
            await self.db.flush()
        return prof

    async def require_my_enrollment(self) -> StudentProgramEnrollment:
        e = await self.my_enrollment()
        if e is None:
            raise forbidden("No active enrolment for the caller")
        return e

    async def enrollment_by_reg(self, regs: Sequence[str]) -> dict[str, uuid.UUID]:
        """Registration number → current enrolment id."""
        from app.models.students import Student

        wanted = [r.strip() for r in regs if r and r.strip()]
        if not wanted:
            return {}
        rows = await self.db.execute(
            select(Student.registration_number, StudentProgramEnrollment.id)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
            .where(Student.institution_id == self.inst, Student.registration_number.in_(wanted))
            .order_by(StudentProgramEnrollment.admission_date)
        )
        return {r[0]: r[1] for r in rows.all()}

    def in_dept(self) -> Any:
        """``StudentProgramEnrollment`` filter of department-scoped readers (or ``true()``)."""
        p = self.principal
        if p is None or all_access(p, self.module):
            return true()
        if scope_ids(p, "college") and module_reader(p, self.module):
            return StudentProgramEnrollment.college_id.in_(scope_ids(p, "college"))
        if (scope_ids(p, "department") or scope_ids(p, "faculty")) and module_reader(p, self.module):
            return StudentProgramEnrollment.department_id.in_(dept_subquery(p))
        return and_(false())

    def meta_str(self, value: Any) -> str:
        return str(value) if value is not None else ""
