"""Row visibility of the HR modules — Prompts/06 "Visibility rules" (the canonical self vs ``view_all`` example).

Every HR record hangs off a ``staff`` row, so one predicate family covers the staff master and every staff-linked
table (leaves, staff attendance, payroll, appraisals):

* **self** — ``staff.user_id = principal.id`` (every staff member sees their own profile, leaves, attendance, payslips);
* **unit** — only with the module's ``view_all`` permission: ``department`` assignments see the staff of those
  departments (``hod`` @department), ``faculty`` assignments the staff of the faculty's departments (``dean``),
  ``college`` assignments the staff of the college (``college_admin``) and an ``institution`` assignment everyone
  (accountant, hr_officer, registrar, auditor …);
* **approver** (leaves) — a leave whose workflow has an open step addressed to the principal.

``scope`` narrows a list: ``self`` / ``team`` (department ∪ faculty) / ``department`` / ``faculty`` / ``college`` /
``all`` (everything visible). A scope the caller does not hold narrows silently to ``self`` (docs/Authorization §4) —
``faculty.1`` asking ``?scope=all`` gets its own rows and ``meta.visibility.scopes = []``. Without ``scope`` the
default tab applies: the narrowest unit tab (``department`` for a HOD, ``all`` for the office roles), else ``self``.

``register_module("hr")`` lets ``BaseRepository.get()`` answer 404 for an invisible staff row (``hod.ece`` reading a
CSE member).
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, OwnershipLink, register_link, register_module
from app.models.hr import Staff
from app.models.platform import Department, WorkflowStep
from app.utils.response import VisibilityMeta

# module → the permission that opens the unit scopes
VIEW_ALL: dict[str, tuple[str, str]] = {
    "hr": ("hr", "view_all"),
    "leaves": ("leaves", "view_all"),
    "attendance": ("attendance", "staff_view_all"),
    "payroll": ("payroll", "view_all"),
    "appraisals": ("hr", "view_all"),
    "workload": ("faculty", "view_all"),
}
UNIT_TABS = ("department", "faculty", "college")
SELF_SCOPES = {"self", "own", "mine"}
TEAM_SCOPES = {"team": ("department", "faculty"), "department": ("department",), "faculty": ("faculty",)}


def _ids(principal: Any, scope_type: str) -> list[uuid.UUID]:
    return [sid for st, sid in getattr(principal, "scopes", []) if st == scope_type and sid is not None]


def _institution(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or any(
        st == "institution" for st, _ in getattr(principal, "scopes", [])
    )


def may_view_all(principal: Any, module: str) -> bool:
    if getattr(principal, "is_super_admin", False):
        return True
    return bool(principal.has(*VIEW_ALL[module]))


def scope_tabs(principal: Any, module: str) -> list[str]:
    """Unit tabs beyond *Mine* the caller may open for the module (``[]`` without ``view_all``)."""
    if not may_view_all(principal, module):
        return []
    tabs = [t for t in UNIT_TABS if _ids(principal, t)]
    if _institution(principal):
        tabs.append("all")
    return tabs


def hr_visibility(principal: Any, module: str, pii: bool = False) -> VisibilityMeta:
    tabs = scope_tabs(principal, module)
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=pii)


def effective_scope(principal: Any, module: str, scope: str | None) -> str:
    """The scope a list actually applies: the default tab without one; an unheld scope narrows to ``self``."""
    tabs = scope_tabs(principal, module)
    if scope is None:
        return tabs[0] if tabs else "self"
    if scope in SELF_SCOPES:
        return "self"
    if scope == "all":
        return "all"  # everything visible (self ∪ units ∪ institution)
    wanted = TEAM_SCOPES.get(scope, (scope,))
    return scope if any(w in tabs for w in wanted) else "self"


def staff_predicate(principal: Any, module: str, scope: str | None = "all") -> ColumnElement[bool]:
    """Predicate over ``staff`` rows visible to the principal in ``scope`` (see the module docstring)."""
    eff = effective_scope(principal, module, scope)
    self_pred: ColumnElement[bool] = Staff.user_id == principal.id
    if eff == "self":
        return self_pred
    if getattr(principal, "is_super_admin", False) and eff == "all":
        return true()
    parts: list[ColumnElement[bool]] = []
    if may_view_all(principal, module):
        if eff == "all" and _institution(principal):
            inst_pred: ColumnElement[bool] = Staff.institution_id == principal.institution_id
            return inst_pred
        wanted = UNIT_TABS if eff == "all" else TEAM_SCOPES.get(eff, (eff,))
        if "department" in wanted and _ids(principal, "department"):
            parts.append(Staff.department_id.in_(_ids(principal, "department")))
        if "faculty" in wanted and _ids(principal, "faculty"):
            parts.append(
                Staff.department_id.in_(
                    select(Department.id).where(Department.faculty_id.in_(_ids(principal, "faculty")))
                )
            )
        if "college" in wanted and _ids(principal, "college"):
            parts.append(Staff.college_id.in_(_ids(principal, "college")))
    if eff == "all" or not parts:
        parts.append(self_pred)
    return or_(*parts)


def visible_staff_ids(principal: Any, module: str, scope: str | None = "all") -> Any:
    """``SELECT staff.id`` subquery for staff-linked tables (``Model.staff_id.in_(...)``)."""
    return select(Staff.id).where(Staff.deleted_at.is_(None), staff_predicate(principal, module, scope))


def approver_instances(principal: Any) -> Any:
    """Workflow instances with an open step addressed to the principal (leave approver link)."""
    return select(WorkflowStep.instance_id).where(
        WorkflowStep.approver_user_id == principal.id, WorkflowStep.status.in_(("pending", "escalated"))
    )


def _faculty_unit(p: Any, model: type) -> ColumnElement[bool]:
    ids = _ids(p, "faculty")
    if not ids or not p.has("hr", "view_all"):
        return false()
    m: Any = model
    return m.department_id.in_(select(Department.id).where(Department.faculty_id.in_(ids)))  # type: ignore[no-any-return]


register_module(
    ModuleVisibility(
        module="hr",
        model=Staff,
        self_predicate=lambda p, m: m.user_id == p.id,  # type: ignore[attr-defined]
        scope_columns={"institution": "institution_id", "college": "college_id", "department": "department_id"},
    )
)
register_link(OwnershipLink(module="hr", name="faculty_unit", predicate=_faculty_unit))
