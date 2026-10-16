"""Row visibility of the registration module — Prompts/09 "Visibility rules" (docs/Authorization_and_Visibility.md §3),
modelled on ``student_scope.py`` / ``applicant_scope.py``.

A registration (and its items, waitlist rows, choice forms and arrears) hangs off a ``student_program_enrollments``
row, so one predicate family over enrolments covers them all:

* **self** — the enrolment's student is the principal (``students.user_id``);
* **wards** — parents read their consented wards' registrations (the services return *confirmed* items only);
* **advisees** — ``student_scope.advisees_predicate`` (latest term record in a section the principal advises — a
  ``batch_sections.class_advisor_staff_id`` holder or a ``class_advisor`` @offering assignment naming the section or a
  real offering targeted at the section);
* **unit** — only with ``registration:view_all``: ``department`` assignments see enrolments of those departments,
  ``faculty`` the departments of the faculty, ``college`` the enrolment's college and ``institution`` everyone.

``scope`` narrows a list exactly like the students module: ``self``/``own``/``mine`` (= the ownership links — the
*Advisees* tab of a class advisor), ``department`` / ``faculty`` / ``college`` or ``all``; a scope the caller does not
hold narrows silently to the ownership links and ``meta.visibility.scopes`` lists only the held tabs (an advisor asking
``?scope=all`` gets the advisees and ``scopes=[]``). The institution tab is reported as ``all``.

This module also appends the **own offerings** link to ``student_scope.OWNERSHIP_LINKS`` and registers it on the
``students`` module: faculty see the students with *confirmed* items in offerings they teach
(``course_offering_faculty.staff_id`` → their staff row) while the offering runs (not ``completed`` / ``cancelled``)
— needed by attendance (Phase 11) and marks (Phase 13).
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, OwnershipLink, register_link, register_module
from app.models.hr import Staff
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.platform import Department
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentProgramEnrollment
from app.repositories import student_scope
from app.repositories.student_scope import advisees_predicate, self_predicate, wards_predicate
from app.utils.response import VisibilityMeta

UNIT_TABS = ("department", "faculty", "college")
SELF_SCOPES = {"self", "own", "mine", "advisees"}


def _ids(principal: Any, scope_type: str) -> list[uuid.UUID]:
    return [sid for st, sid in getattr(principal, "scopes", []) if st == scope_type and sid is not None]


def _institution(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or any(
        st == "institution" for st, _ in getattr(principal, "scopes", [])
    )


def may_view_all(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or bool(principal.has("registration", "view_all"))


def scope_tabs(principal: Any) -> list[str]:
    if not may_view_all(principal):
        return []
    tabs = [t for t in UNIT_TABS if _ids(principal, t)]
    if _institution(principal):
        tabs.append("all")
    return tabs


def registration_visibility(principal: Any) -> VisibilityMeta:
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


# ---- enrolment predicates -------------------------------------------------------------------------------------------
def _students_where(pred: ColumnElement[bool]) -> Any:
    return select(Student.id).where(Student.deleted_at.is_(None), pred)


def own_enrollment_predicate(principal: Any, *, wards: bool = True) -> ColumnElement[bool]:
    parts = [self_predicate(principal), advisees_predicate(principal)]
    if wards:
        parts.append(wards_predicate(principal))
    return StudentProgramEnrollment.student_id.in_(_students_where(or_(*parts)))


def enrollment_predicate(principal: Any, scope: str | None = "all") -> ColumnElement[bool]:
    """Predicate over ``student_program_enrollments`` rows whose registrations the principal may read in ``scope``."""
    eff = effective_scope(principal, scope)
    if getattr(principal, "is_super_admin", False) and eff == "all":
        return true()
    own = own_enrollment_predicate(principal)
    if eff == "self":
        return own
    parts: list[ColumnElement[bool]] = []
    if may_view_all(principal):
        if eff == "all" and _institution(principal):
            inst: ColumnElement[bool] = StudentProgramEnrollment.institution_id == principal.institution_id
            return inst
        wanted = UNIT_TABS if eff == "all" else (eff,)
        if "department" in wanted and _ids(principal, "department"):
            parts.append(StudentProgramEnrollment.department_id.in_(_ids(principal, "department")))
        if "faculty" in wanted and _ids(principal, "faculty"):
            parts.append(
                StudentProgramEnrollment.department_id.in_(
                    select(Department.id).where(Department.faculty_id.in_(_ids(principal, "faculty")))
                )
            )
        if "college" in wanted and _ids(principal, "college"):
            parts.append(StudentProgramEnrollment.college_id.in_(_ids(principal, "college")))
    if eff == "all" or not parts:
        parts.append(own)
    return or_(*parts)


def visible_enrollment_ids(principal: Any, scope: str | None = "all") -> Any:
    return select(StudentProgramEnrollment.id).where(
        StudentProgramEnrollment.deleted_at.is_(None), enrollment_predicate(principal, scope)
    )


def ward_enrollment_ids(principal: Any) -> Any:
    return select(StudentProgramEnrollment.id).where(
        StudentProgramEnrollment.deleted_at.is_(None),
        StudentProgramEnrollment.student_id.in_(_students_where(wards_predicate(principal))),
    )


# ---- own offerings (faculty) ----------------------------------------------------------------------------------------
def taught_offering_ids(principal: Any) -> Any:
    """Offerings the principal teaches (any ``course_offering_faculty`` role) that are still running."""
    return (
        select(CourseOfferingFaculty.offering_id)
        .join(CourseOffering, CourseOffering.id == CourseOfferingFaculty.offering_id)
        .where(
            CourseOffering.deleted_at.is_(None),
            CourseOffering.status.notin_(("completed", "cancelled")),
            CourseOfferingFaculty.staff_id.in_(
                select(Staff.id).where(Staff.user_id == principal.id, Staff.deleted_at.is_(None))
            ),
        )
    )


def own_offerings_predicate(principal: Any) -> ColumnElement[bool]:
    """``students`` rows with a confirmed item in an offering the principal teaches (Phase 11/13 rosters)."""
    if getattr(principal, "id", None) is None:
        return false()
    return Student.id.in_(
        select(StudentProgramEnrollment.student_id)
        .join(CourseRegistration, CourseRegistration.student_program_enrollment_id == StudentProgramEnrollment.id)
        .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
        .where(
            CourseRegistrationItem.status == "confirmed",
            CourseRegistrationItem.offering_id.in_(taught_offering_ids(principal)),
        )
    )


student_scope.OWNERSHIP_LINKS.append(("own_offerings", own_offerings_predicate))
register_link(OwnershipLink(module="students", name="own_offerings", predicate=lambda p, m: own_offerings_predicate(p)))


def _registration_self(p: Any, m: Any) -> ColumnElement[bool]:
    return and_(m.student_program_enrollment_id.in_(visible_enrollment_ids(p, "self")))


register_module(
    ModuleVisibility(
        module="registration",
        model=CourseRegistration,
        self_predicate=_registration_self,
        scope_columns={"institution": "institution_id", "college": "college_id"},
    )
)

__all__ = [
    "effective_scope",
    "enrollment_predicate",
    "may_view_all",
    "own_offerings_predicate",
    "registration_visibility",
    "scope_tabs",
    "taught_offering_ids",
    "visible_enrollment_ids",
    "ward_enrollment_ids",
]
