"""Row visibility of the students module — Prompts/07 "Visibility rules" (docs/Authorization_and_Visibility.md §3).

Every student-linked record (enrolments, term records, holds, documents, guardians, undertakings, transfers, credit
transfers) hangs off a ``students`` row, so one predicate family covers them all:

* **self** — ``students.user_id = principal.id`` (the student portal);
* **wards** — a guardian row with ``user_id = principal.id`` and ``portal_access``, on a student whose
  ``guardian_portal_consent`` is on (the parent portal; consent off hides the ward completely → 404);
* **advisees** — students whose *latest* term record (of an open enrolment) sits in a section the principal advises:
  ``batch_sections.class_advisor_staff_id`` = the principal's staff row, or a ``class_advisor`` @offering assignment
  whose scope id is the section (Phase 05) or a real course offering targeted at the section (Phase 09). Faculty see
  students of their own offerings (``registration_scope`` appends ``own_offerings``, Phase 09) and mentors their
  mentees from Phase 27 — both append to ``OWNERSHIP_LINKS``;
* **unit** — only with ``students:view_all``: ``department`` assignments see students enrolled in those departments
  (``student_program_enrollments.department_id``), ``faculty`` assignments the departments of the faculty, ``college``
  assignments ``students.college_id`` and an ``institution`` assignment everyone.

``scope`` narrows a list: ``self``/``own``/``mine`` (the ownership links), ``department`` / ``faculty`` / ``college`` or
``all`` (everything visible). A scope the caller does not hold narrows silently to the ownership links (a faculty
member asking ``?scope=all`` gets their advisees and ``meta.visibility.scopes = []``). The institution tab is reported
as ``all`` (Phase 02 resolver naming; the prompt's ``["institution"]``).

``register_module("students")`` + the links let ``BaseRepository.get()`` / ``VisibilityResolver.meta()`` behave like
the other modules; the curriculum link (Phase 05 note) lets students and parents read the programme-regulation they
are enrolled in.
"""

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select, true
from sqlalchemy.orm import aliased

from app.core.authz.visibility import ModuleVisibility, OwnershipLink, register_link, register_module
from app.enums.students import OPEN_ENROLLMENT
from app.models.academic import BatchSection
from app.models.hr import Staff
from app.models.offerings import CourseOfferingTarget
from app.models.platform import Department
from app.models.students import Student, StudentGuardian, StudentProgramEnrollment, StudentTermRecord
from app.utils.response import VisibilityMeta

UNIT_TABS = ("department", "faculty", "college")
SELF_SCOPES = {"self", "own", "mine"}

# ownership links over ``students`` rows — (name, predicate(principal) -> expression); later phases append
OwnershipPredicate = Callable[[Any], ColumnElement[bool]]
OWNERSHIP_LINKS: list[tuple[str, OwnershipPredicate]] = []


def _ids(principal: Any, scope_type: str) -> list[uuid.UUID]:
    return [sid for st, sid in getattr(principal, "scopes", []) if st == scope_type and sid is not None]


def _institution(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or any(
        st == "institution" for st, _ in getattr(principal, "scopes", [])
    )


def may_view_all(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or bool(principal.has("students", "view_all"))


def scope_tabs(principal: Any) -> list[str]:
    """Unit tabs beyond *Mine* the caller may open (``[]`` without ``students:view_all``)."""
    if not may_view_all(principal):
        return []
    tabs = [t for t in UNIT_TABS if _ids(principal, t)]
    if _institution(principal):
        tabs.append("all")
    return tabs


def student_visibility(principal: Any) -> VisibilityMeta:
    tabs = scope_tabs(principal)
    pii = bool(getattr(principal, "is_super_admin", False)) or bool(principal.has("students", "view_pii"))
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=pii)


def effective_scope(principal: Any, scope: str | None) -> str:
    tabs = scope_tabs(principal)
    if scope is None:
        return tabs[0] if tabs else "self"
    if scope in SELF_SCOPES:
        return "self"
    if scope == "all":
        return "all"
    return scope if scope in tabs else "self"


# ---- ownership links ------------------------------------------------------------------------------------------------
def self_predicate(principal: Any) -> ColumnElement[bool]:
    pred: ColumnElement[bool] = Student.user_id == principal.id
    return pred


def wards_predicate(principal: Any) -> ColumnElement[bool]:
    return and_(
        Student.guardian_portal_consent.is_(True),
        Student.id.in_(
            select(StudentGuardian.student_id).where(
                StudentGuardian.user_id == principal.id, StudentGuardian.portal_access.is_(True)
            )
        ),
    )


def advised_sections(principal: Any) -> Any:
    """Section ids the principal advises (staff-row holder ∪ ``class_advisor`` @offering assignments on a section)."""
    by_staff = select(BatchSection.id).where(
        BatchSection.class_advisor_staff_id.in_(
            select(Staff.id).where(Staff.user_id == principal.id, Staff.deleted_at.is_(None))
        )
    )
    offering_ids = _ids(principal, "offering") if principal.has("students", "view") else []
    if offering_ids:
        # a section id (Phase 05 assignments) or a real course offering (Phase 09) → the sections it targets
        targeted = select(CourseOfferingTarget.section_id).where(
            CourseOfferingTarget.offering_id.in_(offering_ids), CourseOfferingTarget.section_id.is_not(None)
        )
        return by_staff.union(
            select(BatchSection.id).where(BatchSection.id.in_(offering_ids)),
            select(BatchSection.id).where(BatchSection.id.in_(targeted)),
        )
    return by_staff


def advisees_predicate(principal: Any) -> ColumnElement[bool]:
    latest = aliased(StudentTermRecord)
    record = aliased(StudentTermRecord)
    newest = (
        select(func.max(latest.term_number))
        .where(latest.student_program_enrollment_id == StudentProgramEnrollment.id)
        .scalar_subquery()
    )
    return Student.id.in_(
        select(StudentProgramEnrollment.student_id)
        .join(record, record.student_program_enrollment_id == StudentProgramEnrollment.id)
        .where(
            StudentProgramEnrollment.deleted_at.is_(None),
            StudentProgramEnrollment.status.in_(OPEN_ENROLLMENT),
            record.term_number == newest,
            record.section_id.in_(advised_sections(principal)),
        )
    )


OWNERSHIP_LINKS.extend([("self", self_predicate), ("wards", wards_predicate), ("advisees", advisees_predicate)])


def own_predicate(principal: Any) -> ColumnElement[bool]:
    return or_(*(fn(principal) for _, fn in OWNERSHIP_LINKS))


# ---- unit scopes ----------------------------------------------------------------------------------------------------
def _enrolled_in(department_ids: Any) -> ColumnElement[bool]:
    return Student.id.in_(
        select(StudentProgramEnrollment.student_id).where(
            StudentProgramEnrollment.deleted_at.is_(None), StudentProgramEnrollment.department_id.in_(department_ids)
        )
    )


def student_predicate(principal: Any, scope: str | None = "all") -> ColumnElement[bool]:
    """Predicate over ``students`` rows visible to the principal in ``scope`` (see the module docstring)."""
    eff = effective_scope(principal, scope)
    if getattr(principal, "is_super_admin", False) and eff in ("all", "self"):
        return true() if eff == "all" else own_predicate(principal)
    own = own_predicate(principal)
    if eff == "self":
        return own
    parts: list[ColumnElement[bool]] = []
    if may_view_all(principal):
        if eff == "all" and _institution(principal):
            inst_pred: ColumnElement[bool] = Student.institution_id == principal.institution_id
            return inst_pred
        wanted = UNIT_TABS if eff == "all" else (eff,)
        if "department" in wanted and _ids(principal, "department"):
            parts.append(_enrolled_in(_ids(principal, "department")))
        if "faculty" in wanted and _ids(principal, "faculty"):
            parts.append(
                _enrolled_in(select(Department.id).where(Department.faculty_id.in_(_ids(principal, "faculty"))))
            )
        if "college" in wanted and _ids(principal, "college"):
            parts.append(Student.college_id.in_(_ids(principal, "college")))
    if eff == "all" or not parts:
        parts.append(own)
    return or_(*parts)


def visible_student_ids(principal: Any, scope: str | None = "all") -> Any:
    """``SELECT students.id`` subquery for student-linked tables (``Model.student_id.in_(...)``)."""
    return select(Student.id).where(Student.deleted_at.is_(None), student_predicate(principal, scope))


def visible_enrollment_ids(principal: Any, scope: str | None = "all") -> Any:
    return select(StudentProgramEnrollment.id).where(
        StudentProgramEnrollment.deleted_at.is_(None),
        StudentProgramEnrollment.student_id.in_(visible_student_ids(principal, scope)),
    )


def relation_flags(principal: Any, student: Student, ward_ids: set[uuid.UUID]) -> tuple[bool, bool]:
    """(is_self, is_ward) for response decoration."""
    return student.user_id == getattr(principal, "id", None), student.id in ward_ids


# ---- curriculum through the enrolment (Phase 05 note) ---------------------------------------------------------------
def enrolled_program_regulations(principal: Any) -> Any:
    """Programme-regulations the principal is enrolled in (self) or whose consented wards are."""
    return select(StudentProgramEnrollment.program_regulation_id).where(
        StudentProgramEnrollment.deleted_at.is_(None),
        StudentProgramEnrollment.student_id.in_(
            select(Student.id).where(
                Student.deleted_at.is_(None), or_(self_predicate(principal), wards_predicate(principal))
            )
        ),
    )


def _curriculum_link(p: Any, model: type) -> ColumnElement[bool]:
    m: Any = model
    return m.id.in_(enrolled_program_regulations(p))  # type: ignore[no-any-return]


register_module(
    ModuleVisibility(
        module="students",
        model=Student,
        self_predicate=lambda p, m: m.user_id == p.id,  # type: ignore[attr-defined]
        scope_columns={"institution": "institution_id", "college": "college_id"},
    )
)
register_link(OwnershipLink(module="students", name="wards", predicate=lambda p, m: wards_predicate(p)))
register_link(OwnershipLink(module="students", name="advisees", predicate=lambda p, m: advisees_predicate(p)))
register_link(OwnershipLink(module="curriculum", name="enrolment", predicate=_curriculum_link))

__all__ = [
    "OWNERSHIP_LINKS",
    "advisees_predicate",
    "effective_scope",
    "enrolled_program_regulations",
    "may_view_all",
    "own_predicate",
    "scope_tabs",
    "self_predicate",
    "student_predicate",
    "student_visibility",
    "visible_enrollment_ids",
    "visible_student_ids",
    "wards_predicate",
]
