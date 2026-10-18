"""Row visibility of internal marks, LMS, projects and the question bank — Prompts/13 "Visibility rules", registered
through the Phase 02 resolver like ``registration_scope.py`` / ``fee_scope.py``.

Offering-anchored modules (``marks``, ``lms``):

* **faculty** — offerings they teach (``registration_scope.taught_offering_ids``: any ``course_offering_faculty``
  role, offering not completed / cancelled) — plus finished offerings they taught (read);
* **students** — offerings with a *confirmed* registration item of their own enrolment; parents — their consented
  wards' offerings (marks read-only, own ward rows only);
* **unit** — with ``<module>:view_all``: department (HOD) / faculty (dean) / college over the offering's department
  or college; institution assignments → every offering (reported as ``all``). Exam cell / COE / registrar / auditor
  hold institution-scoped ``marks:view_all``.

Rows *inside* an offering (internal marks, submissions, attempts, content views) narrow further for learners to their
own enrolment (``own_enrollment_ids``). ``projects`` add the member / guide / panel links; ``questions`` the author
(``created_by``) plus department sharing with ``lms:view_all``.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.assessment import InternalMark
from app.models.hr import Staff
from app.models.lms import CourseModule
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.platform import Department
from app.models.projects import ProjectMember, StudentProject
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.repositories.fee_scope import own_enrollment_ids
from app.utils.response import VisibilityMeta

UNIT_TABS = ("department", "faculty", "college")


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def _institution(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def may_view_all(p: Any, module: str) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or bool(p.has(module, "view_all"))


def visibility(p: Any, module: str = "marks") -> VisibilityMeta:
    tabs = [t for t in UNIT_TABS if _ids(p, t)] if may_view_all(p, module) else []
    if may_view_all(p, module) and _institution(p):
        tabs.append("all")
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=False)


def staff_ids(p: Any) -> Any:
    return select(Staff.id).where(Staff.user_id == p.id, Staff.deleted_at.is_(None))


def taught_ids(p: Any, *, include_finished: bool = True) -> Any:
    q = select(CourseOfferingFaculty.offering_id).where(CourseOfferingFaculty.staff_id.in_(staff_ids(p)))
    if not include_finished:
        q = q.join(CourseOffering, CourseOffering.id == CourseOfferingFaculty.offering_id).where(
            CourseOffering.status.notin_(("completed", "cancelled"))
        )
    return q


def learner_offering_ids(p: Any, *, wards: bool = True) -> Any:
    """Offerings with a confirmed item of the principal's own (or consented ward's) enrolment."""
    return (
        select(CourseRegistrationItem.offering_id)
        .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
        .where(
            CourseRegistrationItem.status == "confirmed",
            CourseRegistration.student_program_enrollment_id.in_(own_enrollment_ids(p, wards=wards, advisees=False)),
        )
    )


def offering_predicate(p: Any, module: str, scope: str | None = None) -> ColumnElement[bool]:
    """Predicate over ``course_offerings`` the principal may read in ``module``."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    own = or_(CourseOffering.id.in_(taught_ids(p)), CourseOffering.id.in_(learner_offering_ids(p)))
    if scope in ("self", "own", "mine") or not may_view_all(p, module):
        return own
    if _institution(p) and scope in (None, "all"):
        inst: ColumnElement[bool] = CourseOffering.institution_id == p.institution_id
        return inst
    parts: list[ColumnElement[bool]] = [own]
    wanted = UNIT_TABS if scope in (None, "all") else (scope,)
    if "department" in wanted and _ids(p, "department"):
        parts.append(CourseOffering.department_id.in_(_ids(p, "department")))
    if "faculty" in wanted and _ids(p, "faculty"):
        parts.append(
            CourseOffering.department_id.in_(select(Department.id).where(Department.faculty_id.in_(_ids(p, "faculty"))))
        )
    if "college" in wanted and _ids(p, "college"):
        parts.append(CourseOffering.college_id.in_(_ids(p, "college")))
    return or_(*parts)


def visible_offering_ids(p: Any, module: str = "marks", scope: str | None = None) -> Any:
    return select(CourseOffering.id).where(CourseOffering.deleted_at.is_(None), offering_predicate(p, module, scope))


def teaches(p: Any, offering_id: uuid.UUID) -> Any:
    return select(CourseOfferingFaculty.id).where(
        CourseOfferingFaculty.offering_id == offering_id, CourseOfferingFaculty.staff_id.in_(staff_ids(p))
    )


def project_predicate(p: Any, scope: str | None = None) -> ColumnElement[bool]:
    """Members (self / wards), guide / co-guide, panel members (``project_reviews.panel`` user ids) and units."""
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    from app.models.projects import ProjectReview

    member = StudentProject.id.in_(
        select(ProjectMember.project_id).where(
            ProjectMember.student_program_enrollment_id.in_(own_enrollment_ids(p, advisees=False))
        )
    )
    guide = or_(StudentProject.guide_staff_id.in_(staff_ids(p)), StudentProject.co_guide_staff_id.in_(staff_ids(p)))
    panel = StudentProject.id.in_(
        select(ProjectReview.project_id).where(ProjectReview.panel.contains([{"user_id": str(p.id)}]))
    )
    own = or_(member, guide, panel)
    if scope in ("self", "own", "mine") or not may_view_all(p, "projects"):
        return own
    return or_(own, StudentProject.offering_id.in_(visible_offering_ids(p, "projects", scope)))


def _marks_self(p: Any, m: Any) -> ColumnElement[bool]:
    pred: ColumnElement[bool] = m.student_program_enrollment_id.in_(own_enrollment_ids(p, advisees=False))
    return pred


register_module(
    ModuleVisibility(
        module="marks", model=InternalMark, self_predicate=_marks_self, scope_columns={"institution": "institution_id"}
    )
)
def _lms_self(p: Any, m: Any) -> ColumnElement[bool]:
    pred: ColumnElement[bool] = m.offering_id.in_(learner_offering_ids(p))
    return pred


register_module(
    ModuleVisibility(
        module="lms",
        model=CourseModule,
        self_predicate=_lms_self,
        scope_columns={"institution": "institution_id"},
    )
)
register_module(
    ModuleVisibility(
        module="projects",
        model=StudentProject,
        self_predicate=lambda p, m: project_predicate(p, "self"),
        scope_columns={"institution": "institution_id"},
    )
)
