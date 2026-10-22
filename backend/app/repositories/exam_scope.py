"""Row visibility of exam administration — Prompts/14 "Visibility rules", registered through the Phase 02 resolver.

* registrations: **self** (own enrolment) and consented **wards**; faculty read the registrations of students with
  confirmed items in offerings they teach (``registration_scope.taught_offering_ids``); **unit** tabs with
  ``exams:view_all`` — college over ``exam_registrations.college_id``, department / faculty over the enrolment's
  department; institution → ``all``;
* QP assignments: own ``setter_staff_id`` or an external setter whose ``external_setter.user_id`` is the caller
  (time-boxed ``external_examiner`` accounts); exam cell / COE (``exams:qp`` with ``view_all`` or ``qp_print``) all.
"""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, false, or_, select, true

from app.core.authz.visibility import ModuleVisibility, register_module
from app.models.exams import ExamRegistration, QuestionPaperAssignment
from app.models.platform import Department
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import StudentProgramEnrollment
from app.repositories.assessment_scope import staff_ids
from app.repositories.fee_scope import own_enrollment_ids
from app.repositories.registration_scope import taught_offering_ids
from app.utils.response import VisibilityMeta

UNIT_TABS = ("department", "faculty", "college")


def _ids(p: Any, st: str) -> list[uuid.UUID]:
    return [sid for t, sid in getattr(p, "scopes", []) if t == st and sid is not None]


def _institution(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or any(t == "institution" for t, _ in getattr(p, "scopes", []))


def may_view_all(p: Any) -> bool:
    return bool(getattr(p, "is_super_admin", False)) or bool(p.has("exams", "view_all"))


def visibility(p: Any) -> VisibilityMeta:
    tabs = [t for t in UNIT_TABS if _ids(p, t)] if may_view_all(p) else []
    if may_view_all(p) and _institution(p):
        tabs.append("all")
    pii = bool(getattr(p, "is_super_admin", False)) or bool(p.has("students", "view_pii"))
    return VisibilityMeta(self=True, scopes=tabs, default=tabs[0] if tabs else "self", pii=pii)


def registration_predicate(p: Any, scope: str | None = None) -> ColumnElement[bool]:
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if getattr(p, "id", None) is None:
        return false()
    own = or_(
        ExamRegistration.student_program_enrollment_id.in_(own_enrollment_ids(p, advisees=False)),
        ExamRegistration.student_program_enrollment_id.in_(
            select(CourseRegistration.student_program_enrollment_id)
            .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
            .where(
                CourseRegistrationItem.status == "confirmed",
                CourseRegistrationItem.offering_id.in_(taught_offering_ids(p)),
            )
        ),
    )
    if scope in ("self", "own", "mine") or not may_view_all(p):
        return own
    if _institution(p) and scope in (None, "all"):
        inst: ColumnElement[bool] = ExamRegistration.institution_id == p.institution_id
        return inst
    wanted = UNIT_TABS if scope in (None, "all") else (scope,)
    parts: list[ColumnElement[bool]] = [own]
    if "college" in wanted and _ids(p, "college"):
        parts.append(ExamRegistration.college_id.in_(_ids(p, "college")))
    if "faculty" in wanted and _ids(p, "faculty"):
        parts.append(
            ExamRegistration.student_program_enrollment_id.in_(
                select(StudentProgramEnrollment.id).where(
                    StudentProgramEnrollment.department_id.in_(
                        select(Department.id).where(Department.faculty_id.in_(_ids(p, "faculty")))
                    )
                )
            )
        )
    if "department" in wanted and _ids(p, "department"):
        parts.append(
            ExamRegistration.student_program_enrollment_id.in_(
                select(StudentProgramEnrollment.id).where(
                    StudentProgramEnrollment.department_id.in_(_ids(p, "department"))
                )
            )
        )
    return or_(*parts)


def qp_predicate(p: Any) -> ColumnElement[bool]:
    if p is None or getattr(p, "is_super_admin", False):
        return true()
    if p.has("exams", "qp_print") or (p.has("exams", "qp") and may_view_all(p)):
        return true()
    pred: ColumnElement[bool] = or_(
        QuestionPaperAssignment.setter_staff_id.in_(staff_ids(p)),
        QuestionPaperAssignment.external_setter["user_id"].astext == str(p.id),
    )
    return pred


def _reg_self(p: Any, m: Any) -> ColumnElement[bool]:
    return registration_predicate(p, "self")


register_module(
    ModuleVisibility(
        module="exams",
        model=ExamRegistration,
        self_predicate=_reg_self,
        scope_columns={"institution": "institution_id", "college": "college_id"},
    )
)
