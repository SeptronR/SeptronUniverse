"""Shared plumbing of the Phase 13 services — on the Phase 07 ``StudentServiceBase`` (tenant, audit, outbox,
notifications, institution-local ``today``, settings).

* ``offering(id, module)`` — a visible offering (404 otherwise, never 403); ``require_teacher`` — the caller teaches
  it (``course_offering_faculty``) or holds ``<module>:manage`` (403);
* ``roster(offering)`` — confirmed registration items of the offering (Phase 11 roster query, all sections);
* ``learner_enrolment(offering)`` — the caller's own confirmed enrolment in the offering (students; 404 otherwise);
* ``write_internal_mark`` — **the single write path into ``internal_marks``** (marks grid, assignment grading, quiz
  push, project reviews): upsert on ``(offering_assessment_id, student_program_enrollment_id)``, ``version`` bump,
  refuses ``submitted / verified / locked`` assessments with 409 ``RECORD_LOCKED``.
"""

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import APIError, ErrorCode
from app.enums.assessment import EDITABLE
from app.models.academic import Program
from app.models.assessment import InternalMark, OfferingAssessment
from app.models.curriculum import Course
from app.models.offerings import CourseOffering
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.assessment_scope import offering_predicate, teaches
from app.repositories.attendance_repository import AttendanceRepository
from app.services.students.common import StudentServiceBase


def q2(v: Any) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rule(message: str, code: str, status: int = 409, **details: Any) -> APIError:
    return APIError(status, ErrorCode.RULE_VIOLATION, message, {"code": code, **details})


def now_utc() -> datetime:
    return datetime.now(UTC)


def student_name(s: Student | None) -> str | None:
    return " ".join(p for p in (s.first_name, s.last_name) if p) if s else None


class AssessmentBase(StudentServiceBase):
    audit_module = "marks"

    # ---- offerings --------------------------------------------------------------------------------------------------
    async def offering(
        self, offering_id: uuid.UUID, module: str = "marks", *, for_update: bool = False
    ) -> CourseOffering:
        q = select(CourseOffering).where(
            CourseOffering.id == offering_id,
            CourseOffering.institution_id == self.inst,
            CourseOffering.deleted_at.is_(None),
            offering_predicate(self.principal, module, "all"),
        )
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course offering not found")
        return row

    async def is_teacher(self, offering_id: uuid.UUID) -> bool:
        if self.principal is None or getattr(self.principal, "is_super_admin", False):
            return True
        return (await self.db.execute(teaches(self.principal, offering_id).limit(1))).first() is not None

    async def require_teacher(self, offering: CourseOffering, module: str = "marks") -> None:
        if await self.is_teacher(offering.id) or self.can(module, "manage"):
            return
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the offering's faculty may do this")

    async def course(self, course_id: uuid.UUID) -> Course:
        row = (await self.db.execute(select(Course).where(Course.id == course_id))).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course not found")
        return row

    async def roster(self, offering: CourseOffering) -> list[Any]:
        """``(enrolment_id, student_id, first, last, reg_no, roll_no, photo, user_id)`` of confirmed items."""
        repo = AttendanceRepository(self.db, self.principal, self.inst)
        return list((await self.db.execute(repo.roster_stmt(offering.id, offering.term_id, None))).all())

    async def roster_ids(self, offering: CourseOffering) -> set[uuid.UUID]:
        return {r[0] for r in await self.roster(offering)}

    async def learner_enrolment(self, offering: CourseOffering) -> uuid.UUID:
        from app.repositories.fee_scope import own_enrollment_ids

        own = set((await self.db.execute(own_enrollment_ids(self.principal, advisees=False))).scalars().all())
        hit = (await self.roster_ids(offering)) & own
        if not hit:
            raise APIError(404, ErrorCode.NOT_FOUND, "You are not registered for this offering")
        return next(iter(hit))

    async def my_enrolment_ids(self) -> set[uuid.UUID]:
        from app.repositories.fee_scope import own_enrollment_ids

        return set((await self.db.execute(own_enrollment_ids(self.principal, advisees=False))).scalars().all())

    async def is_university_program(self, offering: CourseOffering) -> bool:
        authority = (
            await self.db.execute(
                select(Program.exam_authority)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.program_id == Program.id)
                .where(StudentProgramEnrollment.id.in_(list(await self.roster_ids(offering)) or [uuid.uuid4()]))
                .limit(1)
            )
        ).scalar_one_or_none()
        return authority == "university"

    # ---- the single write path ----------------------------------------------------------------------------------------
    async def write_internal_mark(
        self,
        assessment: OfferingAssessment,
        enrol_id: uuid.UUID,
        marks: Decimal | float | None,
        *,
        is_absent: bool = False,
        is_exempt: bool = False,
        question_wise: dict[str, Any] | None = None,
        source: str = "grid",
        force: bool = False,
    ) -> None:
        if assessment.status not in EDITABLE and not force:
            raise APIError(
                409,
                ErrorCode.RECORD_LOCKED,
                f"Assessment {assessment.name} is {assessment.status}",
                {"status": assessment.status},
            )
        value = None if marks is None else q2(marks)
        if value is not None and (value < 0 or value > Decimal(str(assessment.max_marks))):
            raise APIError(
                422, ErrorCode.VALIDATION, f"Marks must be within 0–{assessment.max_marks}", {"code": "OUT_OF_RANGE"}
            )
        stmt = insert(InternalMark).values(
            id=uuid.uuid4(),
            institution_id=self.inst,
            offering_assessment_id=assessment.id,
            student_program_enrollment_id=enrol_id,
            marks=value,
            is_absent=is_absent,
            is_exempt=is_exempt,
            question_wise={**(question_wise or {}), **({"_source": source} if source != "grid" else {})} or None,
            entered_by=self.actor_id,
            version=1,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["offering_assessment_id", "student_program_enrollment_id"],
            set_={
                "marks": stmt.excluded.marks,
                "is_absent": stmt.excluded.is_absent,
                "is_exempt": stmt.excluded.is_exempt,
                "question_wise": stmt.excluded.question_wise,
                "entered_by": stmt.excluded.entered_by,
                "entered_at": now_utc(),
                "version": InternalMark.version + 1,
            },
        )
        await self.db.execute(stmt)
        if assessment.status in ("planned", "conducted"):
            assessment.status = "marks_entry"
        await self.db.flush()
