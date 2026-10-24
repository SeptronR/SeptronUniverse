"""Row visibility of degree eligibility, convocation registrations, awards and credentials — Prompts/18 "Visibility
rules", registered through the Phase 02 resolver like ``result_scope.py``.

* **self / wards** — own enrolments (students, alumni) and consented wards (parents) via ``own_enrollment_ids``;
* **units** — holders of ``degrees:view_all|manage|award|issue|convocation_manage`` over the enrolment's department
  (HOD), faculty (dean) or college (college admin); institution assignments (registrar, COE, VC, IQAC, auditor) → all.
"""

from typing import Any

from sqlalchemy import ColumnElement, false, or_, true

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.degrees import DegreeAwarded
from app.repositories.fee_scope import own_enrollment_ids
from app.repositories.result_scope import institution_scope, unit_enrollment_ids

UNIT_ACTIONS = ("view_all", "manage", "award", "issue", "convocation_manage")


def unit_reader(p: Any) -> bool:
    return p is None or bool(getattr(p, "is_super_admin", False)) or any(p.has("degrees", a) for a in UNIT_ACTIONS)


def enrollment_predicate(p: Any, col: Any) -> ColumnElement[bool]:
    """Predicate over any ``student_program_enrollment_id`` column."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    own: ColumnElement[bool] = col.in_(own_enrollment_ids(p, advisees=False))
    if not unit_reader(p):
        return own
    if institution_scope(p):
        return true()
    unit = unit_enrollment_ids(p)
    return or_(own, col.in_(unit)) if unit is not None else own


register_module(
    ModuleVisibility(
        module="degrees",
        model=DegreeAwarded,
        self_predicate=lambda p, m: DegreeAwarded.student_program_enrollment_id.in_(
            own_enrollment_ids(p, advisees=False)
        ),
        scope_columns={"institution": "institution_id"},
    )
)
