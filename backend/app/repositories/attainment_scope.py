"""Row visibility of OBE attainment and the CQI register — Prompts/17 "Visibility rules", registered through the Phase
02 resolver like ``assessment_scope.py``.

* **CO attainment** (offering-anchored): faculty of the offering (any ``course_offering_faculty`` role) and its
  coordinator (``coordinator_staff_id``); unit holders of ``obe:view|view_all|manage`` over the offering's department
  (HOD), faculty (dean), college; institution assignments (OBE coordinator, IQAC, COE, registrar, VC, auditor) → all.
  Students never match here — their optional self view goes through ``learner_offering_ids`` in the service, gated by
  setting ``obe.show_students``.
* **PO attainment** (programme-anchored): the same unit rule over ``programs.department_id`` / ``college_id``.
* **CQI actions**: owner (``owner_staff_id``), the units of the action's scope (offering / course / programme
  department) and institution holders.
"""

from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.academic import Program
from app.models.curriculum import Course
from app.models.obe_attainment import CqiAction
from app.models.offerings import CourseOffering
from app.models.platform import Department
from app.repositories.assessment_scope import UNIT_TABS, _ids, _institution, staff_ids, taught_ids
from app.utils.response import VisibilityMeta

UNIT_ACTIONS = ("view", "view_all", "manage", "configure", "export")


def unit_reader(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(p.has("obe", a) for a in UNIT_ACTIONS)


def visibility(p: Any) -> VisibilityMeta:
    tabs = [t for t in UNIT_TABS if _ids(p, t)] if unit_reader(p) else []
    if unit_reader(p) and _institution(p):
        tabs.append("all")
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=False)


def _unit_parts(p: Any, dept_col: Any, college_col: Any) -> list[ColumnElement[bool]]:
    parts: list[ColumnElement[bool]] = []
    if _ids(p, "department"):
        parts.append(dept_col.in_(_ids(p, "department")))
    if _ids(p, "faculty"):
        parts.append(dept_col.in_(select(Department.id).where(Department.faculty_id.in_(_ids(p, "faculty")))))
    if _ids(p, "college"):
        parts.append(college_col.in_(_ids(p, "college")))
    return parts


def offering_predicate(p: Any) -> ColumnElement[bool]:
    """``course_offerings`` whose CO attainment the principal may read."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    own: ColumnElement[bool] = or_(
        CourseOffering.id.in_(taught_ids(p)), CourseOffering.coordinator_staff_id.in_(staff_ids(p))
    )
    if not unit_reader(p):
        return own
    if _institution(p):
        inst: ColumnElement[bool] = CourseOffering.institution_id == p.institution_id
        return inst
    return or_(own, *_unit_parts(p, CourseOffering.department_id, CourseOffering.college_id))


def program_predicate(p: Any) -> ColumnElement[bool]:
    """``programs`` whose PO attainment the principal may read (faculty: none)."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None or not unit_reader(p):
        return false()
    if _institution(p):
        inst: ColumnElement[bool] = Program.institution_id == p.institution_id
        return inst
    parts = _unit_parts(p, Program.department_id, Program.college_id)
    return or_(*parts) if parts else false()


def cqi_predicate(p: Any) -> ColumnElement[bool]:
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    own: ColumnElement[bool] = CqiAction.owner_staff_id.in_(staff_ids(p))
    if not unit_reader(p):
        return own
    if _institution(p):
        inst: ColumnElement[bool] = CqiAction.institution_id == p.institution_id
        return inst
    offerings = select(CourseOffering.id).where(
        or_(false(), *_unit_parts(p, CourseOffering.department_id, CourseOffering.college_id))
    )
    courses = select(Course.id).where(or_(false(), *_unit_parts(p, Course.department_id, Course.college_id)))
    programs = select(Program.id).where(or_(false(), *_unit_parts(p, Program.department_id, Program.college_id)))
    return or_(
        own,
        CqiAction.scope_id.in_(offerings) & (CqiAction.scope_type == "offering"),
        CqiAction.scope_id.in_(courses) & (CqiAction.scope_type == "course"),
        CqiAction.scope_id.in_(programs) & (CqiAction.scope_type == "program"),
    )


register_module(
    ModuleVisibility(
        module="obe",
        model=CqiAction,
        self_predicate=lambda p, m: CqiAction.owner_staff_id.in_(staff_ids(p)),
        scope_columns={"institution": "institution_id"},
    )
)
