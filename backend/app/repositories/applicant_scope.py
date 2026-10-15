"""Row visibility of the admissions module — Prompts/08 "Visibility rules" (docs/Authorization_and_Visibility.md §3).

Applicants:

* **self** — ``applicants.user_id = principal.id`` (the applicant portal; ``applicant`` role, time-boxed);
* **unit** — only with ``admissions:view_all``: an ``institution`` assignment (admissions office, registrar,
  institution admin) sees every applicant; a ``college`` assignment (``college_admin``, a college-scoped admissions
  officer) the applicants with a preference for a programme of that college; a ``department`` assignment (``hod``) the
  applicants with a preference for a programme of that department (read-only — the HOD holds no
  ``admissions:update``); a ``faculty`` assignment the departments of the faculty.

Enquiries: the assigned counsellor (ownership ``assigned_to``) plus ``admissions:view_all`` (institution → all,
college → ``enquiries.college_id``).

Cycles, seat matrix and merit lists are readable by every holder of ``admissions:view`` (no row predicate).
The institution tab is reported as ``all`` (Phase 02 resolver naming).
"""

from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, OwnershipLink, register_link, register_module
from app.models.academic import Program
from app.models.admissions import Applicant, ApplicantPreference, Enquiry
from app.models.platform import Department
from app.utils.response import VisibilityMeta

UNIT_TABS = ("department", "faculty", "college")
SELF_SCOPES = {"self", "own", "mine"}


def _ids(principal: Any, scope_type: str) -> list[Any]:
    return [sid for st, sid in getattr(principal, "scopes", []) if st == scope_type and sid is not None]


def _institution(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or any(
        st == "institution" for st, _ in getattr(principal, "scopes", [])
    )


def may_view_all(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or bool(principal.has("admissions", "view_all"))


def may_view_pii(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or bool(principal.has("admissions", "view_pii"))


def scope_tabs(principal: Any) -> list[str]:
    if not may_view_all(principal):
        return []
    tabs = [t for t in UNIT_TABS if _ids(principal, t)]
    if _institution(principal):
        tabs.append("all")
    return tabs


def applicant_visibility(principal: Any) -> VisibilityMeta:
    tabs = scope_tabs(principal)
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=may_view_pii(principal))


def effective_scope(principal: Any, scope: str | None) -> str:
    tabs = scope_tabs(principal)
    if scope is None:
        return "all" if "all" in tabs else (tabs[0] if tabs else "self")
    if scope in SELF_SCOPES:
        return "self"
    if scope == "all":
        return "all"
    return scope if scope in tabs else "self"


def self_predicate(principal: Any) -> ColumnElement[bool]:
    pred: ColumnElement[bool] = Applicant.user_id == principal.id
    return pred


def _preferring(program_filter: Any) -> ColumnElement[bool]:
    return Applicant.id.in_(
        select(ApplicantPreference.applicant_id).where(
            ApplicantPreference.program_id.in_(select(Program.id).where(program_filter))
        )
    )


def _college_pref(college_ids: list[Any]) -> ColumnElement[bool]:
    return Applicant.id.in_(
        select(ApplicantPreference.applicant_id).where(ApplicantPreference.college_id.in_(college_ids))
    )


def applicant_predicate(principal: Any, scope: str | None = "all") -> ColumnElement[bool]:
    eff = effective_scope(principal, scope)
    if getattr(principal, "is_super_admin", False):
        return true() if eff != "self" else self_predicate(principal)
    own = self_predicate(principal)
    if eff == "self":
        return own
    parts: list[ColumnElement[bool]] = []
    if may_view_all(principal):
        if eff == "all" and _institution(principal):
            inst: ColumnElement[bool] = Applicant.institution_id == principal.institution_id
            return inst
        wanted = UNIT_TABS if eff == "all" else (eff,)
        if "department" in wanted and _ids(principal, "department"):
            parts.append(_preferring(Program.department_id.in_(_ids(principal, "department"))))
        if "faculty" in wanted and _ids(principal, "faculty"):
            parts.append(
                _preferring(
                    Program.department_id.in_(
                        select(Department.id).where(Department.faculty_id.in_(_ids(principal, "faculty")))
                    )
                )
            )
        if "college" in wanted and _ids(principal, "college"):
            parts.append(_college_pref(_ids(principal, "college")))
    parts.append(own)
    return or_(*parts)


def visible_applicant_ids(principal: Any, scope: str | None = "all") -> Any:
    return select(Applicant.id).where(Applicant.deleted_at.is_(None), applicant_predicate(principal, scope))


def enquiry_predicate(principal: Any, scope: str | None = "all") -> ColumnElement[bool]:
    if getattr(principal, "is_super_admin", False):
        return true()
    mine: ColumnElement[bool] = Enquiry.assigned_to == principal.id
    if scope in SELF_SCOPES or not may_view_all(principal):
        return mine
    if _institution(principal):
        return true()
    colleges = _ids(principal, "college")
    return or_(mine, Enquiry.college_id.in_(colleges)) if colleges else or_(mine, false())


register_module(
    ModuleVisibility(
        module="admissions",
        model=Applicant,
        self_predicate=lambda p, m: m.user_id == p.id,  # type: ignore[attr-defined]
        scope_columns={"institution": "institution_id"},
    )
)
register_link(
    OwnershipLink(module="admissions", name="preferences", predicate=lambda p, m: applicant_predicate(p, "all"))
)

__all__ = [
    "applicant_predicate",
    "applicant_visibility",
    "effective_scope",
    "enquiry_predicate",
    "may_view_all",
    "may_view_pii",
    "scope_tabs",
    "self_predicate",
    "visible_applicant_ids",
]
