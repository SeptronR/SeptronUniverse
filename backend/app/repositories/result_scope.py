"""Row visibility of evaluation & results — Prompts/15 "Visibility rules", registered through the Phase 02 resolver.

* course / term results: **self** (own enrolment, published only — the service filters status) and consented
  **wards**; faculty read the results of offerings they teach; ``results:view_all`` holders read their unit tabs
  (college over ``college_id``, department / faculty over the enrolment's department); institution → ``all``;
* evaluators never reach this module — their worklist reads the ``answer_scripts_for_evaluation`` view through
  their own ``valuation_assignments`` (``evaluator_user_id == p.id``).
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.platform import Department
from app.models.results import StudentCourseResult
from app.models.students import StudentProgramEnrollment
from app.repositories.assessment_scope import taught_ids
from app.repositories.fee_scope import own_enrollment_ids
from app.utils.response import VisibilityMeta

UNIT_TABS = ("department", "faculty", "college")


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def institution_scope(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def may_view_all(p: Any) -> bool:
    return (
        p is None
        or bool(getattr(p, "is_super_admin", False))
        or any(p.has("results", a) for a in ("view_all", "compute", "verify", "manage"))
    )


def college_ids(p: Any) -> list[uuid.UUID]:
    return _ids(p, "college")


def visibility(p: Any) -> VisibilityMeta:
    tabs = [t for t in UNIT_TABS if _ids(p, t)] if may_view_all(p) else []
    if may_view_all(p) and institution_scope(p):
        tabs.append("all")
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=False)


def unit_enrollment_ids(p: Any) -> Any | None:
    parts: list[ColumnElement[bool]] = []
    if _ids(p, "department"):
        parts.append(StudentProgramEnrollment.department_id.in_(_ids(p, "department")))
    if _ids(p, "faculty"):
        parts.append(
            StudentProgramEnrollment.department_id.in_(
                select(Department.id).where(Department.faculty_id.in_(_ids(p, "faculty")))
            )
        )
    if _ids(p, "college"):
        parts.append(StudentProgramEnrollment.college_id.in_(_ids(p, "college")))
    return select(StudentProgramEnrollment.id).where(or_(*parts)) if parts else None


def result_predicate(p: Any, scope: str | None = None) -> ColumnElement[bool]:
    """Rows of ``student_course_results`` the principal may read (status filtering is the service's job)."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    own = or_(
        StudentCourseResult.student_program_enrollment_id.in_(own_enrollment_ids(p, advisees=False)),
        StudentCourseResult.offering_id.in_(taught_ids(p)),
    )
    if scope in ("self", "own", "mine") or not may_view_all(p):
        return own
    if institution_scope(p):
        inst: ColumnElement[bool] = StudentCourseResult.institution_id == p.institution_id
        return inst
    unit = unit_enrollment_ids(p)
    return or_(own, StudentCourseResult.student_program_enrollment_id.in_(unit)) if unit is not None else own


def enrollment_predicate(p: Any, col: Any) -> ColumnElement[bool]:
    """Same rule over any ``student_program_enrollment_id`` column (term results, grade cards)."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    own: ColumnElement[bool] = col.in_(own_enrollment_ids(p, advisees=False))
    if not may_view_all(p):
        return own
    if institution_scope(p):
        return true()
    unit = unit_enrollment_ids(p)
    return or_(own, col.in_(unit)) if unit is not None else own


def _self(p: Any, m: Any) -> ColumnElement[bool]:
    return result_predicate(p, "self")


register_module(
    ModuleVisibility(
        module="results",
        model=StudentCourseResult,
        self_predicate=_self,
        scope_columns={"institution": "institution_id", "college": "college_id"},
    )
)
