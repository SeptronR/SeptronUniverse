"""Shared plumbing of the Phase 27 services (mentoring, risk, grievances, discipline, surveys, clubs) — on the Phase 25
``FacilitiesBase`` (permissions, ScopeTab predicates, people lookups, the ``institution_settings`` side store).

**Visibility** (Prompts/27 "Visibility rules"): rows are narrowed in the services — self (own enrolment / raised by /
subject), wards (guardian links), ownership (mentor ``mentor_assignments.mentor_staff_id``, class advisor
``batch_sections.class_advisor_staff_id`` through the current ``student_term_records.section_id``, committee members
through ``committee_members.user_id`` / ``staff_id``, club advisor ``clubs.faculty_advisor_id``, assignee), then the
caller's departments (HOD — the enrolment's department), colleges (``college_admin``) and institution-wide holders of
the module's ``view_all`` / ``manage``. Faculty hold ``mentoring:manage`` with a ``self`` scope, so the department /
college / all widening only applies to roles assigned at those scopes.

Small facts the section 26 tables have no column for (assignment history, booking notes, referral appointment link,
survey reminders / external tokens) live in ``institution_settings`` rows of category ``support_meta``.
"""

import hashlib
import hmac
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import or_, select

from app.models.academic import AcademicTerm, BatchSection
from app.models.hr import Staff
from app.models.platform import Department, Role, User, UserRole
from app.models.post_result import Committee, CommitteeMember
from app.models.students import Student, StudentGuardian, StudentProgramEnrollment, StudentTermRecord
from app.services.facilities.common import (
    FacilitiesBase,
    all_access,
    dept_subquery,
    forbidden,
    institution_scope,
    is_auditor,
    module_reader,
    not_found,
    now_utc,
    rule,
    scope_ids,
    visibility_scopes,
)

__all__ = [
    "SupportBase",
    "dept_subquery",
    "all_access",
    "forbidden",
    "institution_scope",
    "is_auditor",
    "module_reader",
    "not_found",
    "now_utc",
    "rule",
    "scope_ids",
    "visibility_scopes",
]

META = "support_meta"


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def respondent_hash(secret: str, user_id: uuid.UUID | str, survey_id: uuid.UUID | str) -> str:
    """HMAC(user_id, survey_id, secret) — never maps back to the user (Prompts/27 §27.6 surveys 1)."""
    return hmac.new(secret.encode("utf-8"), f"{user_id}:{survey_id}".encode(), hashlib.sha256).hexdigest()


class SupportBase(FacilitiesBase):
    audit_module = "mentoring"
    module = "mentoring"
    meta_category = META

    # ---- terms ------------------------------------------------------------------------------------------------------
    async def term_or_current(self, term_id: uuid.UUID | None) -> AcademicTerm:
        if term_id is not None:
            t = (
                await self.db.execute(
                    select(AcademicTerm).where(AcademicTerm.id == term_id, AcademicTerm.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if t is None:
                raise not_found("Term")
            return t
        return await self.require_current_term(None)

    # ---- people -----------------------------------------------------------------------------------------------------
    async def my_enrollment(self) -> StudentProgramEnrollment | None:
        st = await self.my_student()
        if st is None:
            return None
        return await self.enrollments.current(st.id)

    async def my_enrollment_ids(self) -> list[uuid.UUID]:
        st = await self.my_student()
        if st is None:
            return []
        rows = await self.db.execute(
            select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.student_id == st.id)
        )
        return [r[0] for r in rows.all()]

    async def ward_enrollment_ids(self) -> list[uuid.UUID]:
        if self.actor_id is None:
            return []
        rows = await self.db.execute(
            select(StudentProgramEnrollment.id)
            .join(StudentGuardian, StudentGuardian.student_id == StudentProgramEnrollment.student_id)
            .where(StudentGuardian.user_id == self.actor_id, StudentGuardian.portal_access.is_(True))
        )
        return [r[0] for r in rows.all()]

    async def enrollment(self, eid: uuid.UUID) -> StudentProgramEnrollment:
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(
                    StudentProgramEnrollment.id == eid, StudentProgramEnrollment.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if e is None:
            raise not_found("Enrolment")
        return e

    async def enrollment_cards(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, dict[str, Any]]:
        """``{enrolment id: {student_id, name, registration_number, department_id, college_id, user_id}}``."""
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        rows = (
            await self.db.execute(
                select(StudentProgramEnrollment, Student)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(StudentProgramEnrollment.id.in_(wanted))
            )
        ).all()
        return {
            e.id: {
                "student_id": s.id,
                "name": s.full_name,
                "registration_number": s.registration_number,
                "department_id": e.department_id,
                "college_id": e.college_id,
                "batch_id": e.batch_id,
                "program_id": e.program_id,
                "user_id": s.user_id,
                "standing": e.academic_standing,
                "status": e.status,
            }
            for e, s in rows
        }

    async def staff_cards(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, dict[str, Any]]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        rows = (await self.db.execute(select(Staff).where(Staff.id.in_(wanted)))).scalars().all()
        return {
            s.id: {
                "name": " ".join(x for x in (s.first_name, s.last_name) if x),
                "user_id": s.user_id,
                "department_id": s.department_id,
                "email": s.email,
                "phone": s.phone,
            }
            for s in rows
        }

    async def staff_user(self, staff_id: uuid.UUID | None) -> uuid.UUID | None:
        if staff_id is None:
            return None
        return (await self.db.execute(select(Staff.user_id).where(Staff.id == staff_id))).scalar_one_or_none()

    async def guardian_users(self, enrollment_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self.db.execute(
            select(StudentGuardian.user_id)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == StudentGuardian.student_id)
            .where(StudentProgramEnrollment.id == enrollment_id, StudentGuardian.user_id.is_not(None))
        )
        return [r[0] for r in rows.all() if r[0]]

    async def role_users(self, slug: str, department_id: uuid.UUID | None = None) -> list[uuid.UUID]:
        """Holders of a role (department-scoped holders of that department first, else institution-wide)."""
        stmt = (
            select(UserRole.user_id, UserRole.scope_type, UserRole.scope_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.slug == slug, or_(UserRole.institution_id == self.inst, UserRole.institution_id.is_(None)))
        )
        rows = (await self.db.execute(stmt)).all()
        if department_id is not None:
            dep = [u for u, st, sid in rows if st == "department" and sid == department_id]
            if dep:
                return dep
        return [u for u, st, _ in rows if st in ("institution", "self")] or [u for u, _, _ in rows]

    async def department_codes(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        rows = await self.db.execute(select(Department.id, Department.code).where(Department.id.in_(wanted)))
        return {r[0]: r[1] for r in rows.all()}

    async def user_display(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        wanted = list({i for i in ids if i})
        if not wanted:
            return {}
        rows = await self.db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(wanted)))
        return {r[0]: r[1] or r[2] for r in rows.all()}

    # ---- ownership subqueries ---------------------------------------------------------------------------------------
    def advisee_subquery(self, staff_id: uuid.UUID) -> Any:
        """Enrolments whose (latest) term record sits in a section the staff member advises."""
        return (
            select(StudentTermRecord.student_program_enrollment_id)
            .join(BatchSection, BatchSection.id == StudentTermRecord.section_id)
            .where(BatchSection.class_advisor_staff_id == staff_id)
        )

    def enrolment_dept_predicate(self, col: Any, scope: str | None = None) -> list[Any]:
        """Department / college widening on an enrolment id column (HOD / college admin)."""
        p = self.principal
        parts: list[Any] = []
        if not module_reader(p, self.module):
            return parts
        units = scope_ids(p, "department") or scope_ids(p, "faculty")
        if scope in (None, "department") and units:
            parts.append(
                col.in_(
                    select(StudentProgramEnrollment.id).where(
                        StudentProgramEnrollment.department_id.in_(dept_subquery(p))
                    )
                )
            )
        if scope in (None, "college") and scope_ids(p, "college"):
            parts.append(
                col.in_(
                    select(StudentProgramEnrollment.id).where(
                        StudentProgramEnrollment.college_id.in_(scope_ids(p, "college"))
                    )
                )
            )
        return parts

    async def my_committee_ids(self) -> list[uuid.UUID]:
        if self.actor_id is None:
            return []
        staff_id = await self.my_staff_id()
        conds = [CommitteeMember.user_id == self.actor_id]
        if staff_id is not None:
            conds.append(CommitteeMember.staff_id == staff_id)
        rows = await self.db.execute(
            select(CommitteeMember.committee_id).where(
                CommitteeMember.institution_id == self.inst,
                or_(*conds),
                or_(CommitteeMember.to_on.is_(None), CommitteeMember.to_on >= date.today()),
            )
        )
        ids = {r[0] for r in rows.all()}
        if staff_id is not None:
            chairs = await self.db.execute(
                select(Committee.id).where(
                    Committee.institution_id == self.inst,
                    or_(Committee.chair_staff_id == staff_id, Committee.secretary_staff_id == staff_id),
                )
            )
            ids |= {r[0] for r in chairs.all()}
        return list(ids)

    async def committee_by_type(self, committee_type: str, college_id: uuid.UUID | None = None) -> Committee | None:
        stmt = select(Committee).where(
            Committee.institution_id == self.inst,
            Committee.committee_type == committee_type,
            Committee.is_active.is_(True),
        )
        rows = (await self.db.execute(stmt.order_by(Committee.created_at))).scalars().all()
        if college_id is not None:
            for c in rows:
                if c.college_id == college_id:
                    return c
        return next((c for c in rows if c.college_id is None), rows[0] if rows else None)

    async def committee_user_ids(self, committee_id: uuid.UUID | None) -> list[uuid.UUID]:
        if committee_id is None:
            return []
        users = {
            r[0]
            for r in (
                await self.db.execute(
                    select(CommitteeMember.user_id).where(
                        CommitteeMember.committee_id == committee_id, CommitteeMember.user_id.is_not(None)
                    )
                )
            ).all()
        }
        staff_users = (
            await self.db.execute(
                select(Staff.user_id)
                .join(CommitteeMember, CommitteeMember.staff_id == Staff.id)
                .where(CommitteeMember.committee_id == committee_id, Staff.user_id.is_not(None))
            )
        ).all()
        users |= {r[0] for r in staff_users}
        c = (await self.db.execute(select(Committee).where(Committee.id == committee_id))).scalar_one_or_none()
        if c is not None:
            for sid in (c.chair_staff_id, c.secretary_staff_id):
                u = await self.staff_user(sid)
                if u:
                    users.add(u)
        return [u for u in users if u]

    async def secret(self) -> str:
        from app.core.config import settings

        return str(getattr(settings, "SECRET_KEY", None) or getattr(settings, "JWT_SECRET", None) or self.inst)

    def visibility(self, *, self_tab: bool, own_tab: bool) -> dict[str, Any]:
        tabs = [t for t in visibility_scopes(self.principal, self.module) if t != "self"]
        lead: list[str] = []
        if self_tab:
            lead.append("mine")
        if own_tab:
            lead.append("own")
        scopes = lead + tabs
        return {"self": self_tab, "scopes": scopes, "default": scopes[-1] if scopes else "mine"}
