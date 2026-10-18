"""Row visibility of the timetable module — Prompts/10 "Visibility rules", modelled on ``registration_scope.py`` /
``student_scope.py``.

* **Rooms / slots** — institution-wide read (``timetable:view``); no predicate.
* **Timetables / entries** — institution-wide read for **staff** (every staff template carries
  ``attendance:staff_self``; ``timetable:view_all`` holders too). Students read the timetables of their own section /
  batch / department (term records + enrolment — *self*), parents those of their consented wards, and any entry of an
  offering in which the student (ward) has a **confirmed** item (electives taught to a mixed group).
* **Class sessions** (``module="attendance"`` — Phase 11 shares it): faculty their own sessions (ownership
  ``class_sessions.staff_id`` → their staff row) and the sessions of the offerings they teach
  (``registration_scope.taught_offering_ids``); students / parents the sessions of their (wards') confirmed
  offerings; with ``attendance:view_all`` / ``timetable:view_all`` the held unit scopes — ``department`` (offering
  department), ``faculty`` (its departments), ``college`` and ``institution`` (reported as ``all``).

``scope`` narrows a session list like the other modules: ``self``/``own``/``mine`` → the ownership links, a unit tab
the caller holds → that unit; anything else narrows silently to the ownership links.

**Phase 11 attendance records** (marks, summaries, OD, condonations, eligibility rows) share the ``attendance``
module registered here (``record_predicate``): self / wards (consent-aware, ``learner_enrollment_ids``), the
offerings the caller teaches, the caller's advisees (class advisor of the student's latest section); with
``attendance:view_all`` the held unit scopes over the offering's department (or the enrolment's department for rows
without an offering) / faculty / college, and institution → ``all``.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, OwnershipLink, register_link, register_module
from app.models.hr import Staff
from app.models.offerings import CourseOffering
from app.models.platform import Department
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.models.timetable import ClassSession, Timetable, TimetableEntry
from app.repositories.registration_scope import taught_offering_ids, visible_enrollment_ids, ward_enrollment_ids
from app.utils.response import VisibilityMeta

UNIT_TABS = ("department", "faculty", "college")
SELF_SCOPES = {"self", "own", "mine"}


def _ids(principal: Any, scope_type: str) -> list[uuid.UUID]:
    return [sid for st, sid in getattr(principal, "scopes", []) if st == scope_type and sid is not None]


def _institution(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or any(
        st == "institution" for st, _ in getattr(principal, "scopes", [])
    )


def is_staff(principal: Any) -> bool:
    """Staff read every timetable of the institution (Prompts/10: "institution-wide read for staff")."""
    if principal is None or getattr(principal, "is_super_admin", False):
        return True
    return bool(principal.has("attendance", "staff_self") or principal.has("timetable", "view_all"))


def may_view_all_sessions(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or bool(
        principal.has("attendance", "view_all") or principal.has("timetable", "view_all")
    )


def scope_tabs(principal: Any) -> list[str]:
    if not may_view_all_sessions(principal):
        return []
    tabs = [t for t in UNIT_TABS if _ids(principal, t)]
    if _institution(principal):
        tabs.append("all")
    return tabs


def session_visibility(principal: Any) -> VisibilityMeta:
    tabs = scope_tabs(principal)
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=False)


# ---- student / parent links -------------------------------------------------------------------------------------------
def my_staff_ids(principal: Any) -> Any:
    return select(Staff.id).where(Staff.user_id == principal.id, Staff.deleted_at.is_(None))


def learner_enrollment_ids(principal: Any) -> Any:
    """Enrolments of the principal (student) and of its consented wards (parent)."""
    own = select(StudentProgramEnrollment.id).where(
        StudentProgramEnrollment.deleted_at.is_(None),
        StudentProgramEnrollment.id.in_(visible_enrollment_ids(principal, "self")),
    )
    return own.union(ward_enrollment_ids(principal))


def confirmed_offering_ids(principal: Any) -> Any:
    return (
        select(CourseRegistrationItem.offering_id)
        .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
        .where(
            CourseRegistrationItem.status == "confirmed",
            CourseRegistration.student_program_enrollment_id.in_(learner_enrollment_ids(principal)),
        )
    )


def learner_scope_ids(principal: Any) -> Any:
    """Section / batch / department ids a student (ward) belongs to — any term record + the enrolment."""
    enrol = learner_enrollment_ids(principal)
    return (
        select(StudentTermRecord.section_id)
        .where(StudentTermRecord.student_program_enrollment_id.in_(enrol), StudentTermRecord.section_id.is_not(None))
        .union(
            select(StudentProgramEnrollment.batch_id).where(StudentProgramEnrollment.id.in_(enrol)),
            select(StudentProgramEnrollment.department_id).where(StudentProgramEnrollment.id.in_(enrol)),
        )
    )


# ---- timetables / entries ---------------------------------------------------------------------------------------------
def timetable_predicate(principal: Any) -> ColumnElement[bool]:
    if is_staff(principal):
        return true()
    if getattr(principal, "id", None) is None:
        return false()
    return and_(
        Timetable.status == "published",
        or_(
            Timetable.scope_id.in_(learner_scope_ids(principal)),
            Timetable.id.in_(
                select(TimetableEntry.timetable_id).where(
                    TimetableEntry.offering_id.in_(confirmed_offering_ids(principal))
                )
            ),
        ),
    )


def entry_predicate(principal: Any) -> ColumnElement[bool]:
    if is_staff(principal):
        return true()
    if getattr(principal, "id", None) is None:
        return false()
    return or_(
        TimetableEntry.offering_id.in_(confirmed_offering_ids(principal)),
        TimetableEntry.timetable_id.in_(
            select(Timetable.id).where(
                Timetable.status == "published", Timetable.scope_id.in_(learner_scope_ids(principal))
            )
        ),
    )


# ---- class sessions -----------------------------------------------------------------------------------------------------
def own_sessions_predicate(principal: Any) -> ColumnElement[bool]:
    if getattr(principal, "id", None) is None:
        return false()
    return or_(
        ClassSession.staff_id.in_(my_staff_ids(principal)),
        ClassSession.offering_id.in_(taught_offering_ids(principal)),
        ClassSession.offering_id.in_(confirmed_offering_ids(principal)),
    )


def effective_scope(principal: Any, scope: str | None) -> str:
    tabs = scope_tabs(principal)
    if scope is None:
        return tabs[0] if tabs else "self"
    if scope in SELF_SCOPES:
        return "self"
    if scope == "all":
        return "all" if "all" in tabs else (tabs[0] if tabs else "self")
    return scope if scope in tabs else "self"


def session_predicate(principal: Any, scope: str | None = None) -> ColumnElement[bool]:
    if getattr(principal, "is_super_admin", False) and scope in (None, "all"):
        return true()
    eff = effective_scope(principal, scope)
    own = own_sessions_predicate(principal)
    if eff == "self":
        return own
    if eff == "all" and _institution(principal):
        inst: ColumnElement[bool] = ClassSession.institution_id == principal.institution_id
        return inst
    parts: list[ColumnElement[bool]] = []
    wanted = UNIT_TABS if eff == "all" else (eff,)
    if "department" in wanted and _ids(principal, "department"):
        parts.append(
            ClassSession.offering_id.in_(
                select(CourseOffering.id).where(CourseOffering.department_id.in_(_ids(principal, "department")))
            )
        )
    if "faculty" in wanted and _ids(principal, "faculty"):
        parts.append(
            ClassSession.offering_id.in_(
                select(CourseOffering.id).where(
                    CourseOffering.department_id.in_(
                        select(Department.id).where(Department.faculty_id.in_(_ids(principal, "faculty")))
                    )
                )
            )
        )
    if "college" in wanted and _ids(principal, "college"):
        parts.append(ClassSession.college_id.in_(_ids(principal, "college")))
    if not parts:
        return own
    return or_(*parts)


def _session_self(p: Any, m: Any) -> ColumnElement[bool]:
    return own_sessions_predicate(p)


def _timetable_self(p: Any, m: Any) -> ColumnElement[bool]:
    return timetable_predicate(p)


# ---- Phase 11 attendance records ------------------------------------------------------------------------------------------
def advisee_enrollment_ids(principal: Any) -> Any:
    from app.repositories.student_scope import advisees_predicate

    return select(StudentProgramEnrollment.id).where(
        StudentProgramEnrollment.deleted_at.is_(None),
        StudentProgramEnrollment.student_id.in_(select(Student.id).where(advisees_predicate(principal))),
    )


def own_record_predicate(principal: Any, offering_col: Any, enrollment_col: Any) -> ColumnElement[bool]:
    if getattr(principal, "id", None) is None:
        return false()
    parts = [
        enrollment_col.in_(learner_enrollment_ids(principal)),
        enrollment_col.in_(advisee_enrollment_ids(principal)),
    ]
    if offering_col is not None:
        parts.append(offering_col.in_(taught_offering_ids(principal)))
    else:  # OD / aggregate condonations: students of any offering the caller teaches
        parts.append(
            enrollment_col.in_(
                select(CourseRegistration.student_program_enrollment_id)
                .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
                .where(
                    CourseRegistrationItem.status == "confirmed",
                    CourseRegistrationItem.offering_id.in_(taught_offering_ids(principal)),
                )
            )
        )
    return or_(*parts)


def record_predicate(
    principal: Any, offering_col: Any, enrollment_col: Any, scope: str | None = None
) -> ColumnElement[bool]:
    """Visibility of a Phase 11 row keyed by (offering, enrolment); ``offering_col`` may be ``None``."""
    if principal is None or (getattr(principal, "is_super_admin", False) and scope in (None, "all")):
        return true()
    eff = effective_scope(principal, scope)
    own = own_record_predicate(principal, offering_col, enrollment_col)
    if eff == "self":
        return own
    if eff == "all" and _institution(principal):
        return true()
    wanted = UNIT_TABS if eff == "all" else (eff,)
    depts: list[uuid.UUID] = list(_ids(principal, "department")) if "department" in wanted else []
    if "faculty" in wanted and _ids(principal, "faculty"):
        faculty_depts: Any = select(Department.id).where(Department.faculty_id.in_(_ids(principal, "faculty")))
    else:
        faculty_depts = None
    colleges = _ids(principal, "college") if "college" in wanted else []
    parts: list[ColumnElement[bool]] = []
    if offering_col is not None:
        if depts:
            parts.append(offering_col.in_(select(CourseOffering.id).where(CourseOffering.department_id.in_(depts))))
        if faculty_depts is not None:
            parts.append(
                offering_col.in_(select(CourseOffering.id).where(CourseOffering.department_id.in_(faculty_depts)))
            )
        if colleges:
            parts.append(offering_col.in_(select(CourseOffering.id).where(CourseOffering.college_id.in_(colleges))))
    else:
        enrol = select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.deleted_at.is_(None))
        if depts:
            parts.append(enrollment_col.in_(enrol.where(StudentProgramEnrollment.department_id.in_(depts))))
        if faculty_depts is not None:
            parts.append(enrollment_col.in_(enrol.where(StudentProgramEnrollment.department_id.in_(faculty_depts))))
        if colleges:
            parts.append(enrollment_col.in_(enrol.where(StudentProgramEnrollment.college_id.in_(colleges))))
    if not parts:
        return own
    return or_(own, *parts)


register_module(
    ModuleVisibility(
        module="attendance",
        model=ClassSession,
        self_predicate=_session_self,
        scope_columns={"institution": "institution_id", "college": "college_id"},
    )
)
register_module(
    ModuleVisibility(
        module="timetable",
        model=Timetable,
        self_predicate=_timetable_self,
        scope_columns={"institution": "institution_id", "college": "college_id"},
    )
)
register_link(OwnershipLink(module="attendance", name="own_sessions", predicate=lambda p, m: own_sessions_predicate(p)))

__all__ = [
    "advisee_enrollment_ids",
    "confirmed_offering_ids",
    "effective_scope",
    "entry_predicate",
    "is_staff",
    "learner_enrollment_ids",
    "learner_scope_ids",
    "may_view_all_sessions",
    "my_staff_ids",
    "own_record_predicate",
    "own_sessions_predicate",
    "record_predicate",
    "scope_tabs",
    "session_predicate",
    "session_visibility",
    "timetable_predicate",
]
