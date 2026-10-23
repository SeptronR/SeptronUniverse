"""Shared plumbing of the Phase 16 services — on the Phase 15 ``ResultBase``.

``item_context(item_id)`` loads an exam-registration item with its registration, enrolment, student, course and paper
and checks visibility (own / ward enrolment for learners, ``exams:view_all|reval|malpractice|manage`` staff for the
rest); ``correction_run`` creates and computes a Phase 15 run for the affected (enrolment, course) pairs — the COE
verifies / approves / publishes it, unless ``auto_publish`` (system releases) chains the steps as the system actor.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.curriculum import Course
from app.models.exams import ExamPaper, ExamRegistration, ExamRegistrationItem, ExamSession
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.fee_scope import own_enrollment_ids
from app.services.results.result_service import ResultBase


@dataclass
class ItemContext:
    item: ExamRegistrationItem
    registration: ExamRegistration
    enrolment: StudentProgramEnrollment
    student: Student
    course: Course
    paper: ExamPaper
    session: ExamSession

    @property
    def student_name(self) -> str:
        return " ".join(x for x in (self.student.first_name, self.student.last_name) if x)


class PostResultBase(ResultBase):
    audit_module = "results"
    STAFF_ACTIONS: tuple[tuple[str, str], ...] = (
        ("exams", "view_all"),
        ("exams", "reval"),
        ("exams", "malpractice"),
        ("exams", "manage"),
        ("results", "view_all"),
    )

    def is_staff(self) -> bool:
        return any(self.can(m, a) for m, a in self.STAFF_ACTIONS)

    async def mine(self, enrolment_id: uuid.UUID) -> bool:
        if self.principal is None:
            return True
        row = (
            await self.db.execute(
                select(StudentProgramEnrollment.id).where(
                    StudentProgramEnrollment.id == enrolment_id,
                    StudentProgramEnrollment.id.in_(own_enrollment_ids(self.principal, advisees=False)),
                )
            )
        ).first()
        return row is not None

    async def item_context(self, item_id: uuid.UUID, *, for_update: bool = False) -> ItemContext:
        q = (
            select(
                ExamRegistrationItem,
                ExamRegistration,
                StudentProgramEnrollment,
                Student,
                Course,
                ExamPaper,
                ExamSession,
            )
            .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == ExamRegistration.student_program_enrollment_id
            )
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .join(Course, Course.id == ExamRegistrationItem.course_id)
            .join(ExamPaper, ExamPaper.id == ExamRegistrationItem.exam_paper_id)
            .join(ExamSession, ExamSession.id == ExamRegistration.exam_session_id)
            .where(ExamRegistrationItem.id == item_id, ExamRegistrationItem.institution_id == self.inst)
        )
        if for_update:
            q = q.with_for_update(of=ExamRegistrationItem)
        row = (await self.db.execute(q)).first()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Exam registration item not found")
        ctx = ItemContext(*row)
        if not self.is_staff() and not await self.mine(ctx.enrolment.id):
            raise APIError(404, ErrorCode.NOT_FOUND, "Exam registration item not found")
        return ctx

    async def correction_run(
        self,
        session_id: uuid.UUID,
        pairs: list[tuple[uuid.UUID, uuid.UUID]],
        *,
        run_type: str = "correction",
        marks_delta: dict[str, Any] | None = None,
        ignore_holds: bool = False,
        auto_publish: bool = False,
    ) -> uuid.UUID | None:
        """Create + compute a run for the affected rows; returns the run id (``None`` when nothing to do)."""
        from app.schemas.results import PublishRequest, RunAction, RunCreateRequest, RunScope
        from app.services.results.result_service import ResultRunService

        if not pairs:
            return None
        svc = ResultRunService(self.db, self.principal, self.request, self.inst)
        run = await svc.create_run(
            RunCreateRequest(
                exam_session_id=session_id,
                run_type=run_type,  # type: ignore[arg-type]
                scope=RunScope(
                    enrollment_ids=sorted({e for e, _ in pairs}),
                    course_ids=sorted({c for _, c in pairs}),
                    marks_delta=marks_delta or {},
                    ignore_holds=ignore_holds,
                ),
            )
        )
        await svc.compute(run.id)
        if auto_publish:
            await svc.verify(run.id, RunAction(acknowledge_anomalies=True, comment="system release"))
            await svc.approve(run.id, RunAction(comment="system release"))
            await svc.publish(run.id, PublishRequest(notify=True))
        return run.id
