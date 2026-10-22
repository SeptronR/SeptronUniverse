"""Row visibility of fees / scholarships / no-dues — Prompts/12 "Visibility rules", registered through the Phase 02
resolver like ``registration_scope.py`` / ``timetable_scope.py``.

Every fee row hangs off a payer; student payers through ``student_program_enrollments``:

* **self** — own enrolments (``students.user_id``) and own applicant rows (``payer_type='applicant'``);
* **wards** — consented wards (parents read and pay);
* **advisees** — class advisors / mentors with ``fees:view`` (``student_scope.advisees_predicate``);
* **unit** — with ``<module>:view_all``: department / faculty / college assignments over the enrolment;
  institution → every row (reported as ``all``). The accountant (``fees:manage``) and auditor hold view_all.

``scope`` narrows like the other modules: ``self`` / ``mine`` → ownership links, a unit tab the caller does not
hold narrows silently to the ownership links.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.admissions import Applicant
from app.models.fees import FeeInvoice, NoDuesRequest, ScholarshipApplication
from app.models.platform import Department
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.student_scope import advisees_predicate, self_predicate, wards_predicate
from app.utils.response import VisibilityMeta

UNIT_TABS = ("department", "faculty", "college")
SELF_SCOPES = {"self", "own", "mine", "advisees", "wards"}


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def _institution(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def may_view_all(p: Any, module: str = "fees") -> bool:
    return bool(getattr(p, "is_super_admin", False)) or bool(p.has(module, "view_all"))


def scope_tabs(p: Any, module: str = "fees") -> list[str]:
    if not may_view_all(p, module):
        return []
    tabs = [t for t in UNIT_TABS if _ids(p, t)]
    if _institution(p):
        tabs.append("all")
    return tabs


def visibility(p: Any, module: str = "fees") -> VisibilityMeta:
    tabs = scope_tabs(p, module)
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=False)


def effective_scope(p: Any, scope: str | None, module: str = "fees") -> str:
    tabs = scope_tabs(p, module)
    if scope is None:
        return tabs[0] if tabs else "self"
    if scope in SELF_SCOPES:
        return "self"
    if scope == "all":
        return "all" if "all" in tabs else (tabs[0] if tabs else "self")
    return scope if scope in tabs else "self"


def own_student_ids(p: Any, *, wards: bool = True, advisees: bool = True) -> Any:
    parts = [self_predicate(p)]
    if wards:
        parts.append(wards_predicate(p))
    if advisees:
        parts.append(advisees_predicate(p))
    return select(Student.id).where(Student.deleted_at.is_(None), or_(*parts))


def own_enrollment_ids(p: Any, *, wards: bool = True, advisees: bool = True) -> Any:
    return select(StudentProgramEnrollment.id).where(
        StudentProgramEnrollment.student_id.in_(own_student_ids(p, wards=wards, advisees=advisees))
    )


def ward_enrollment_ids(p: Any) -> Any:
    return select(StudentProgramEnrollment.id).where(
        StudentProgramEnrollment.student_id.in_(select(Student.id).where(wards_predicate(p)))
    )


def unit_enrollment_ids(p: Any, eff: str, module: str) -> Any | None:
    if not may_view_all(p, module):
        return None
    wanted = UNIT_TABS if eff == "all" else (eff,)
    parts: list[ColumnElement[bool]] = []
    if "department" in wanted and _ids(p, "department"):
        parts.append(StudentProgramEnrollment.department_id.in_(_ids(p, "department")))
    if "faculty" in wanted and _ids(p, "faculty"):
        parts.append(
            StudentProgramEnrollment.department_id.in_(
                select(Department.id).where(Department.faculty_id.in_(_ids(p, "faculty")))
            )
        )
    if "college" in wanted and _ids(p, "college"):
        parts.append(StudentProgramEnrollment.college_id.in_(_ids(p, "college")))
    if not parts:
        return None
    return select(StudentProgramEnrollment.id).where(or_(*parts))


def enrollment_column_predicate(p: Any, col: Any, scope: str | None, module: str) -> ColumnElement[bool]:
    """Predicate over a ``student_program_enrollment_id`` column for the principal and scope."""
    eff = effective_scope(p, scope, module)
    if eff == "all" and _institution(p) and may_view_all(p, module):
        return true()
    own: ColumnElement[bool] = col.in_(own_enrollment_ids(p))
    if eff == "self":
        return own
    unit = unit_enrollment_ids(p, eff, module)
    return or_(own, col.in_(unit)) if unit is not None else own


def invoice_predicate(p: Any, scope: str | None = None) -> ColumnElement[bool]:
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    eff = effective_scope(p, scope)
    if eff == "all" and _institution(p) and may_view_all(p):
        inst: ColumnElement[bool] = FeeInvoice.institution_id == p.institution_id
        return inst
    applicant = and_(
        FeeInvoice.payer_type == "applicant",
        FeeInvoice.payer_id.in_(select(Applicant.id).where(Applicant.user_id == p.id)),
    )
    if getattr(p, "id", None) is None:
        return false()
    enrol = enrollment_column_predicate(p, FeeInvoice.student_program_enrollment_id, scope, "fees")
    return or_(enrol, applicant)


def _invoice_self(p: Any, m: Any) -> ColumnElement[bool]:
    return invoice_predicate(p, "self")


register_module(
    ModuleVisibility(
        module="fees",
        model=FeeInvoice,
        self_predicate=_invoice_self,
        scope_columns={"institution": "institution_id", "college": "college_id"},
    )
)
def _own_enrolment_self(p: Any, m: Any) -> ColumnElement[bool]:
    pred: ColumnElement[bool] = m.student_program_enrollment_id.in_(own_enrollment_ids(p, advisees=False))
    return pred


register_module(
    ModuleVisibility(
        module="scholarships",
        model=ScholarshipApplication,
        self_predicate=_own_enrolment_self,
        scope_columns={"institution": "institution_id"},
    )
)
register_module(
    ModuleVisibility(
        module="no_dues",
        model=NoDuesRequest,
        self_predicate=_own_enrolment_self,
        scope_columns={"institution": "institution_id"},
    )
)
