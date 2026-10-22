"""LMS-lite — Prompts/13 §13.6 ``lms_service``.

1. Modules / contents (file / video / link / text / SCORM / embed), release dates, CO tags; learners see published
   modules and released contents only; ``content_views`` progress (max of pings) → completion %.
2. Assignments: draft → published → closed; submissions (text / files) with attempts, ``is_late`` past ``due_at``
   (refused when ``allow_late`` is off); bulk grading with rubric (Σ criteria) and the late penalty
   (``late_penalty_pct_per_day`` × whole days late); when linked to an ``offering_assessment`` the graded marks are
   scaled to its ``max_marks`` and written through the single write path; similarity check (job, ``PlagiarismChecker``
   adapter — mock in development).
3. Quizzes from a **frozen** question paper: start (attempt row, shuffled questions without answers; attempts beyond
   ``attempts_allowed`` → 409), autosave, submit / auto-submit at ``started_at + duration`` (Beat
   ``quizzes.auto_submit``), auto-score MCQ / MSQ / true-false / numeric / fill-blank, manual score for the rest,
   ``push_to_marks`` → internal marks; proctoring options + events stored on the attempt.
4. Announcements (notify the roster), discussions (threads / posts / upvotes / answers; locked threads → 409), online
   class links (offering link or a ``video_conf`` adapter meeting per session).
"""
# mypy: disable-error-code="arg-type"

import hashlib
import random
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.assessment import AUTO_SCORED
from app.models.assessment import OfferingAssessment
from app.models.content import Question, QuestionOption, QuestionPaper
from app.models.lms import (
    AssignmentSubmission,
    ContentView,
    CourseAnnouncement,
    CourseContent,
    CourseModule,
    DiscussionPost,
    DiscussionThread,
    LmsAssignment,
    Quiz,
    QuizAttempt,
)
from app.models.platform import User
from app.models.students import Student, StudentProgramEnrollment
from app.schemas.lms import (
    AnnouncementIn,
    AnnouncementOut,
    AssignmentIn,
    AssignmentOut,
    AttemptOut,
    ContentIn,
    ContentOut,
    ContentViewPing,
    GradeBulk,
    ManualGrade,
    ModuleIn,
    ModuleOut,
    OnlineLinkRequest,
    PostIn,
    PostOut,
    PushToMarksResult,
    QuizAnswerSave,
    QuizIn,
    QuizOut,
    QuizStartResponse,
    QuizSubmitResponse,
    SubmissionCreate,
    SubmissionOut,
    ThreadIn,
    ThreadOut,
    ThreadPatch,
)
from app.services.assessment.common import AssessmentBase, now_utc, q2, rule, student_name


class LmsService(AssessmentBase):
    audit_module = "lms"

    async def _staff_view(self, offering_id: uuid.UUID) -> bool:
        return await self.is_teacher(offering_id) or self.can("lms", "view_all")

    async def _names(self, enrol_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str | None, str | None]]:
        if not enrol_ids:
            return {}
        rows = (
            await self.db.execute(
                select(StudentProgramEnrollment.id, Student)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(StudentProgramEnrollment.id.in_(enrol_ids))
            )
        ).all()
        return {e: (s.registration_number, student_name(s)) for e, s in rows}

    # ---- 1. modules / contents ------------------------------------------------------------------------------------------------
    async def modules(self, offering_id: uuid.UUID) -> list[ModuleOut]:
        offering = await self.offering(offering_id, "lms")
        staff = await self._staff_view(offering.id)
        q = select(CourseModule).where(CourseModule.offering_id == offering.id).order_by(CourseModule.sequence)
        if not staff:
            q = q.where(CourseModule.is_published.is_(True))
        mods = (await self.db.execute(q)).scalars().all()
        contents = (
            (
                await self.db.execute(
                    select(CourseContent)
                    .where(CourseContent.module_id.in_([m.id for m in mods] or [uuid.uuid4()]))
                    .order_by(CourseContent.sequence)
                )
            )
            .scalars()
            .all()
        )
        mine = await self.my_enrolment_ids() if not staff else set()
        views = (
            {
                v.content_id: v.progress_pct
                for v in (
                    await self.db.execute(
                        select(ContentView).where(
                            ContentView.student_program_enrollment_id.in_(list(mine) or [uuid.uuid4()])
                        )
                    )
                ).scalars()
            }
            if mine
            else {}
        )
        now = now_utc()
        out = []
        for m in mods:
            mo = ModuleOut.model_validate(m)
            for c in contents:
                if c.module_id != m.id or (not staff and c.release_at and c.release_at > now):
                    continue
                co = ContentOut.model_validate(c)
                co.my_progress = views.get(c.id) if mine else None
                mo.contents.append(co)
            if mine and mo.contents:
                mo.completion_pct = round(sum((x.my_progress or 0) for x in mo.contents) / len(mo.contents), 1)
            out.append(mo)
        return out

    async def save_module(
        self, offering_id: uuid.UUID | None, body: ModuleIn, mid: uuid.UUID | None = None
    ) -> ModuleOut:
        if mid:
            m = (
                await self.db.execute(
                    select(CourseModule).where(CourseModule.id == mid, CourseModule.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if m is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Module not found")
            offering = await self.offering(m.offering_id, "lms")
            await self.require_teacher(offering, "lms")
            for k, v in body.model_dump().items():
                setattr(m, k, v)
        else:
            offering = await self.offering(offering_id, "lms")  # type: ignore[arg-type]
            await self.require_teacher(offering, "lms")
            m = CourseModule(institution_id=self.inst, offering_id=offering.id, **body.model_dump())
            self.db.add(m)
        await self.db.flush()
        if m.is_published:
            await self._emit(
                "lms.content_published",
                {"offering_id": str(m.offering_id), "module_id": str(m.id)},
                "course_module",
                m.id,
            )
        return ModuleOut.model_validate(m)

    async def delete_module(self, mid: uuid.UUID) -> None:
        m = (
            await self.db.execute(
                select(CourseModule).where(CourseModule.id == mid, CourseModule.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if m is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Module not found")
        await self.require_teacher(await self.offering(m.offering_id, "lms"), "lms")
        await self.db.delete(m)
        await self.db.flush()

    async def _module(self, mid: uuid.UUID) -> CourseModule:
        m = (
            await self.db.execute(
                select(CourseModule).where(CourseModule.id == mid, CourseModule.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if m is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Module not found")
        await self.offering(m.offering_id, "lms")
        return m

    async def contents(self, mid: uuid.UUID) -> list[ContentOut]:
        m = await self._module(mid)
        return next((x.contents for x in await self.modules(m.offering_id) if x.id == m.id), [])

    async def save_content(self, mid: uuid.UUID | None, body: ContentIn, cid: uuid.UUID | None = None) -> ContentOut:
        if cid:
            c = (
                await self.db.execute(
                    select(CourseContent).where(CourseContent.id == cid, CourseContent.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if c is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Content not found")
            m = await self._module(c.module_id)
            await self.require_teacher(await self.offering(m.offering_id, "lms"), "lms")
            for k, v in body.model_dump().items():
                setattr(c, k, v)
        else:
            m = await self._module(mid)  # type: ignore[arg-type]
            await self.require_teacher(await self.offering(m.offering_id, "lms"), "lms")
            c = CourseContent(institution_id=self.inst, module_id=m.id, created_by=self.actor_id, **body.model_dump())
            self.db.add(c)
        await self.db.flush()
        return ContentOut.model_validate(c)

    async def delete_content(self, cid: uuid.UUID) -> None:
        c = (
            await self.db.execute(
                select(CourseContent).where(CourseContent.id == cid, CourseContent.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if c is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Content not found")
        m = await self._module(c.module_id)
        await self.require_teacher(await self.offering(m.offering_id, "lms"), "lms")
        await self.db.delete(c)
        await self.db.flush()

    async def view(self, cid: uuid.UUID, body: ContentViewPing) -> ContentOut:
        c = (
            await self.db.execute(
                select(CourseContent).where(CourseContent.id == cid, CourseContent.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if c is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Content not found")
        m = await self._module(c.module_id)
        enrol = await self.learner_enrolment(await self.offering(m.offering_id, "lms"))
        v = (
            await self.db.execute(
                select(ContentView)
                .where(ContentView.content_id == c.id, ContentView.student_program_enrollment_id == enrol)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if v is None:
            v = ContentView(
                institution_id=self.inst,
                content_id=c.id,
                student_program_enrollment_id=enrol,
                progress_pct=body.progress_pct,
            )
            self.db.add(v)
            c.view_count += 1
        else:
            v.progress_pct, v.last_viewed_at = max(v.progress_pct, body.progress_pct), now_utc()
        await self.db.flush()
        out = ContentOut.model_validate(c)
        out.my_progress = v.progress_pct
        return out

    # ---- 2. assignments ------------------------------------------------------------------------------------------------------
    async def _assignment(self, aid: uuid.UUID, *, for_update: bool = False) -> LmsAssignment:
        q = select(LmsAssignment).where(LmsAssignment.id == aid, LmsAssignment.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        a = (await self.db.execute(q)).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Assignment not found")
        await self.offering(a.offering_id, "lms")
        return a

    async def assignment_outs(self, rows: list[LmsAssignment]) -> list[AssignmentOut]:
        counts: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(AssignmentSubmission.assignment_id, func.count())
                    .where(AssignmentSubmission.assignment_id.in_([r.id for r in rows] or [uuid.uuid4()]))
                    .group_by(AssignmentSubmission.assignment_id)
                )
            ).all()
        )  # type: ignore[arg-type]
        mine = await self.my_enrolment_ids()
        subs = (
            {
                s.assignment_id: s
                for s in (
                    await self.db.execute(
                        select(AssignmentSubmission)
                        .where(
                            AssignmentSubmission.student_program_enrollment_id.in_(list(mine) or [uuid.uuid4()]),
                            AssignmentSubmission.assignment_id.in_([r.id for r in rows] or [uuid.uuid4()]),
                        )
                        .order_by(AssignmentSubmission.attempt)
                    )
                ).scalars()
            }
            if mine
            else {}
        )
        out = []
        for r in rows:
            o = AssignmentOut.model_validate(r)
            o.submissions = int(counts.get(r.id, 0))
            s = subs.get(r.id)
            if s is not None:
                o.my_submission = {
                    "id": str(s.id),
                    "status": s.status,
                    "is_late": s.is_late,
                    "marks": float(s.marks) if s.marks is not None else None,
                    "feedback": s.feedback,
                    "attempt": s.attempt,
                }
            out.append(o)
        return out

    async def assignments(self, offering_id: uuid.UUID) -> list[AssignmentOut]:
        offering = await self.offering(offering_id, "lms")
        q = (
            select(LmsAssignment)
            .where(LmsAssignment.offering_id == offering.id)
            .order_by(LmsAssignment.created_at.desc())
        )
        if not await self._staff_view(offering.id):
            q = q.where(LmsAssignment.status != "draft")
        return await self.assignment_outs(list((await self.db.execute(q)).scalars().all()))

    async def save_assignment(
        self, offering_id: uuid.UUID | None, body: AssignmentIn, aid: uuid.UUID | None = None
    ) -> AssignmentOut:
        data = body.model_dump()
        for k in ("max_marks", "late_penalty_pct_per_day"):
            if data.get(k) is not None:
                data[k] = Decimal(str(data[k]))
        if aid:
            a = await self._assignment(aid, for_update=True)
            await self.require_teacher(await self.offering(a.offering_id, "lms"), "lms")
            for k, v in data.items():
                setattr(a, k, v)
        else:
            offering = await self.offering(offering_id, "lms")  # type: ignore[arg-type]
            await self.require_teacher(offering, "lms")
            if (
                body.offering_assessment_id
                and (
                    await self.db.execute(
                        select(OfferingAssessment.offering_id).where(
                            OfferingAssessment.id == body.offering_assessment_id
                        )
                    )
                ).scalar_one_or_none()
                != offering.id
            ):
                raise APIError(422, ErrorCode.VALIDATION, "The linked assessment belongs to another offering")
            a = LmsAssignment(
                institution_id=self.inst, offering_id=offering.id, created_by=self.actor_id, status="draft", **data
            )
            self.db.add(a)
        await self.db.flush()
        return (await self.assignment_outs([a]))[0]

    async def set_assignment_status(self, aid: uuid.UUID, status: str) -> AssignmentOut:
        a = await self._assignment(aid, for_update=True)
        offering = await self.offering(a.offering_id, "lms")
        await self.require_teacher(offering, "lms")
        a.status = status
        await self.db.flush()
        if status == "published":
            await self._emit(
                "assignment.published",
                {"assignment_id": str(a.id), "offering_id": str(a.offering_id)},
                "lms_assignment",
                a.id,
            )
            await self._notify(
                "lms.assignment_published",
                [r[7] for r in await self.roster(offering)],
                {"title": a.title, "due": a.due_at.isoformat() if a.due_at else "—"},
            )
        return (await self.assignment_outs([a]))[0]

    async def submissions(self, aid: uuid.UUID) -> list[SubmissionOut]:
        a = await self._assignment(aid)
        q = (
            select(AssignmentSubmission)
            .where(AssignmentSubmission.assignment_id == a.id)
            .order_by(AssignmentSubmission.submitted_at)
        )
        if not await self._staff_view(a.offering_id):
            q = q.where(
                AssignmentSubmission.student_program_enrollment_id.in_(
                    list(await self.my_enrolment_ids()) or [uuid.uuid4()]
                )
            )
        rows = list((await self.db.execute(q)).scalars().all())
        names = await self._names([r.student_program_enrollment_id for r in rows])
        out = []
        for r in rows:
            o = SubmissionOut.model_validate(r)
            o.registration_number, o.student_name = names.get(r.student_program_enrollment_id, (None, None))
            out.append(o)
        return out

    async def submit(self, aid: uuid.UUID, body: SubmissionCreate) -> SubmissionOut:
        a = await self._assignment(aid, for_update=True)
        if a.status != "published":
            raise rule("The assignment is not open for submissions", "NOT_OPEN")
        enrol = await self.learner_enrolment(await self.offering(a.offering_id, "lms"))
        if not body.text_answer and not body.files:
            raise APIError(422, ErrorCode.VALIDATION, "Submit a text answer or files")
        too_big = [f.get("name") for f in body.files or [] if float(f.get("size_mb") or 0) > a.max_file_mb]
        if too_big:
            raise APIError(422, ErrorCode.VALIDATION, f"Files larger than {a.max_file_mb} MB", {"files": too_big})
        late = bool(a.due_at and now_utc() > a.due_at)
        if late and not a.allow_late:
            raise rule("The due date has passed", "PAST_DUE")
        prev = (
            await self.db.execute(
                select(func.max(AssignmentSubmission.attempt)).where(
                    AssignmentSubmission.assignment_id == a.id,
                    AssignmentSubmission.student_program_enrollment_id == enrol,
                )
            )
        ).scalar_one_or_none()
        last = (
            (
                await self.db.execute(
                    select(AssignmentSubmission).where(
                        AssignmentSubmission.assignment_id == a.id,
                        AssignmentSubmission.student_program_enrollment_id == enrol,
                        AssignmentSubmission.attempt == prev,
                    )
                )
            ).scalar_one_or_none()
            if prev
            else None
        )
        if last is not None and last.status not in ("resubmit", "returned"):
            raise APIError(
                409, ErrorCode.CONFLICT, "Already submitted — wait for the faculty to return it for resubmission"
            )
        s = AssignmentSubmission(
            institution_id=self.inst,
            assignment_id=a.id,
            student_program_enrollment_id=enrol,
            files=body.files,
            text_answer=body.text_answer,
            is_late=late,
            attempt=(prev or 0) + 1,
            status="submitted",
        )
        self.db.add(s)
        await self.db.flush()
        return (await self.submissions_by_ids([s.id]))[0]

    async def submissions_by_ids(self, ids: list[uuid.UUID]) -> list[SubmissionOut]:
        rows = list(
            (await self.db.execute(select(AssignmentSubmission).where(AssignmentSubmission.id.in_(ids))))
            .scalars()
            .all()
        )
        names = await self._names([r.student_program_enrollment_id for r in rows])
        out = []
        for r in rows:
            o = SubmissionOut.model_validate(r)
            o.registration_number, o.student_name = names.get(r.student_program_enrollment_id, (None, None))
            out.append(o)
        return out

    async def grade(self, aid: uuid.UUID, body: GradeBulk) -> list[SubmissionOut]:
        a = await self._assignment(aid, for_update=True)
        offering = await self.offering(a.offering_id, "lms")
        await self.require_teacher(offering, "lms")
        linked = (
            (
                await self.db.execute(
                    select(OfferingAssessment)
                    .where(OfferingAssessment.id == a.offering_assessment_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if a.offering_assessment_id
            else None
        )
        ids = []
        for row in body.rows:
            s = (
                await self.db.execute(
                    select(AssignmentSubmission)
                    .where(AssignmentSubmission.id == row.submission_id, AssignmentSubmission.assignment_id == a.id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if s is None:
                raise APIError(404, ErrorCode.NOT_FOUND, f"Submission {row.submission_id} not found")
            marks = Decimal(str(row.marks)) if row.marks is not None else None
            if row.rubric_scores:
                caps = {str(c.get("criterion")): float(c.get("max") or 0) for c in a.rubric or []}
                bad = [k for k, v in row.rubric_scores.items() if k in caps and v > caps[k]]
                if bad:
                    raise APIError(422, ErrorCode.VALIDATION, f"Rubric scores above the maximum: {', '.join(bad)}")
                marks = Decimal(str(sum(row.rubric_scores.values())))
            if marks is not None and a.max_marks is not None and marks > Decimal(str(a.max_marks)):
                raise APIError(422, ErrorCode.VALIDATION, f"Marks above {a.max_marks}")
            if marks is not None and s.is_late and a.late_penalty_pct_per_day and a.due_at:
                days = max(1, (s.submitted_at - a.due_at).days + (1 if (s.submitted_at - a.due_at).seconds else 0))
                marks = q2(marks * max(Decimal(0), 1 - Decimal(str(a.late_penalty_pct_per_day)) * days / 100))
            s.marks, s.rubric_scores, s.feedback, s.status, s.graded_by, s.graded_at = (
                marks,
                row.rubric_scores,
                row.feedback,
                row.status,
                self.actor_id,
                now_utc(),
            )
            await self.db.flush()
            if linked is not None and marks is not None and row.status == "graded" and a.max_marks:
                scaled = q2(marks / Decimal(str(a.max_marks)) * Decimal(str(linked.max_marks)))
                await self.write_internal_mark(linked, s.student_program_enrollment_id, scaled, source="assignment")
            ids.append(s.id)
        await self._audit("grade", "lms_assignment", a.id, None, {"graded": len(ids)})
        await self._emit("assignment.graded", {"assignment_id": str(a.id), "graded": len(ids)}, "lms_assignment", a.id)
        return await self.submissions_by_ids(ids)

    async def similarity(self, aid: uuid.UUID) -> int:
        """Body of the ``lms.similarity_check`` job — ``PlagiarismChecker`` adapter (mock: deterministic %)."""
        from app.integrations.registry import get_adapter

        a = await self._assignment(aid)
        checker = get_adapter("plagiarism", "mock")
        n = 0
        for s in (
            await self.db.execute(
                select(AssignmentSubmission).where(AssignmentSubmission.assignment_id == a.id).with_for_update()
            )
        ).scalars():
            await checker.send(submission_id=str(s.id))
            digest = hashlib.sha256(f"{s.id}{s.text_answer or ''}".encode()).digest()
            s.similarity_pct = q2(digest[0] / 255 * 40)
            s.similarity_report_url = f"mock://similarity/{s.id}"
            n += 1
        await self.db.flush()
        return n

    # ---- 3. quizzes -------------------------------------------------------------------------------------------------------------
    async def _quiz(self, qid: uuid.UUID, *, for_update: bool = False) -> Quiz:
        q = select(Quiz).where(Quiz.id == qid, Quiz.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        quiz = (await self.db.execute(q)).scalar_one_or_none()
        if quiz is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Quiz not found")
        await self.offering(quiz.offering_id, "lms")
        return quiz

    async def quiz_outs(self, rows: list[Quiz]) -> list[QuizOut]:
        papers = {
            p.id: p
            for p in (
                await self.db.execute(
                    select(QuestionPaper).where(
                        QuestionPaper.id.in_([r.question_paper_id for r in rows] or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        mine = await self.my_enrolment_ids()
        attempts = (
            (
                await self.db.execute(
                    select(QuizAttempt).where(
                        QuizAttempt.student_program_enrollment_id.in_(list(mine) or [uuid.uuid4()]),
                        QuizAttempt.quiz_id.in_([r.id for r in rows] or [uuid.uuid4()]),
                    )
                )
            )
            .scalars()
            .all()
            if mine
            else []
        )
        out = []
        for r in rows:
            o = QuizOut.model_validate(r)
            p = papers.get(r.question_paper_id)
            o.total_marks = float(p.total_marks) if p and p.total_marks is not None else None
            show = r.show_result == "immediate" or (r.show_result == "after_close" and r.status == "closed")
            o.my_attempts = [
                {
                    "id": str(x.id),
                    "attempt_no": x.attempt_no,
                    "status": x.status,
                    "total_score": float(x.total_score) if show and x.total_score is not None else None,
                }
                for x in attempts
                if x.quiz_id == r.id
            ]
            out.append(o)
        return out

    async def quizzes(self, offering_id: uuid.UUID) -> list[QuizOut]:
        offering = await self.offering(offering_id, "lms")
        q = select(Quiz).where(Quiz.offering_id == offering.id).order_by(Quiz.created_at.desc())
        if not await self._staff_view(offering.id):
            q = q.where(Quiz.status != "draft")
        return await self.quiz_outs(list((await self.db.execute(q)).scalars().all()))

    async def save_quiz(self, offering_id: uuid.UUID | None, body: QuizIn, qid: uuid.UUID | None = None) -> QuizOut:
        paper = (
            await self.db.execute(
                select(QuestionPaper).where(
                    QuestionPaper.id == body.question_paper_id, QuestionPaper.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if paper is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Question paper not found")
        if paper.status not in ("frozen", "used"):
            raise rule("Freeze the question paper first", "PAPER_NOT_FROZEN", 422)
        if qid:
            quiz = await self._quiz(qid, for_update=True)
            await self.require_teacher(await self.offering(quiz.offering_id, "lms"), "lms")
            for k, v in body.model_dump().items():
                setattr(quiz, k, v)
        else:
            offering = await self.offering(offering_id, "lms")  # type: ignore[arg-type]
            await self.require_teacher(offering, "lms")
            quiz = Quiz(
                institution_id=self.inst,
                offering_id=offering.id,
                created_by=self.actor_id,
                status="draft",
                **body.model_dump(),
            )
            self.db.add(quiz)
        await self.db.flush()
        return (await self.quiz_outs([quiz]))[0]

    async def set_quiz_status(self, qid: uuid.UUID, status: str) -> QuizOut:
        quiz = await self._quiz(qid, for_update=True)
        await self.require_teacher(await self.offering(quiz.offering_id, "lms"), "lms")
        quiz.status = status
        if status == "published":
            paper = (
                await self.db.execute(
                    select(QuestionPaper).where(QuestionPaper.id == quiz.question_paper_id).with_for_update()
                )
            ).scalar_one()
            paper.status = "used"
            await self._emit("quiz.published", {"quiz_id": str(quiz.id)}, "quiz", quiz.id)
        if status == "closed":
            for at in (
                await self.db.execute(
                    select(QuizAttempt)
                    .where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.status == "in_progress")
                    .with_for_update()
                )
            ).scalars():
                await self._finish(quiz, at, "auto_submitted")
        await self.db.flush()
        return (await self.quiz_outs([quiz]))[0]

    async def _paper_questions(self, quiz: Quiz) -> list[tuple[dict[str, Any], Question, list[QuestionOption]]]:
        paper = (
            await self.db.execute(select(QuestionPaper).where(QuestionPaper.id == quiz.question_paper_id))
        ).scalar_one()
        refs = [q for sec in paper.sections or [] for q in sec.get("questions") or []]
        ids = [uuid.UUID(str(r["question_id"])) for r in refs]
        qs = {
            q.id: q
            for q in (await self.db.execute(select(Question).where(Question.id.in_(ids or [uuid.uuid4()])))).scalars()
        }
        opts: dict[uuid.UUID, list[QuestionOption]] = {}
        for o in (
            await self.db.execute(
                select(QuestionOption)
                .where(QuestionOption.question_id.in_(ids or [uuid.uuid4()]))
                .order_by(QuestionOption.sequence)
            )
        ).scalars():
            opts.setdefault(o.question_id, []).append(o)
        return [
            (r, qs[uuid.UUID(str(r["question_id"]))], opts.get(uuid.UUID(str(r["question_id"])), []))
            for r in refs
            if uuid.UUID(str(r["question_id"])) in qs
        ]

    async def start(self, qid: uuid.UUID) -> QuizStartResponse:
        quiz = await self._quiz(qid, for_update=True)
        if quiz.status != "published":
            raise rule("The quiz is not open", "NOT_OPEN")
        now = now_utc()
        if (quiz.starts_at and now < quiz.starts_at) or (quiz.ends_at and now > quiz.ends_at):
            raise rule("Outside the quiz window", "WINDOW_CLOSED")
        enrol = await self.learner_enrolment(await self.offering(quiz.offering_id, "lms"))
        attempts = (
            (
                await self.db.execute(
                    select(QuizAttempt)
                    .where(QuizAttempt.quiz_id == quiz.id, QuizAttempt.student_program_enrollment_id == enrol)
                    .order_by(QuizAttempt.attempt_no)
                )
            )
            .scalars()
            .all()
        )
        live = next((a for a in attempts if a.status == "in_progress"), None)
        if live is None:
            if len(attempts) >= quiz.attempts_allowed:
                raise APIError(409, ErrorCode.CONFLICT, "No attempts left", {"code": "ATTEMPTS_EXHAUSTED"})
            live = QuizAttempt(
                institution_id=self.inst,
                quiz_id=quiz.id,
                student_program_enrollment_id=enrol,
                attempt_no=len(attempts) + 1,
                answers={},
                status="in_progress",
            )
            self.db.add(live)
            await self.db.flush()
        items = await self._paper_questions(quiz)
        if quiz.shuffle_questions:
            random.Random(f"{live.id}").shuffle(items)
        ends = live.started_at + timedelta(minutes=quiz.duration_minutes)
        if quiz.ends_at and quiz.ends_at < ends:
            ends = quiz.ends_at
        qs = [
            {
                "question_id": str(q.id),
                "type": q.question_type,
                "body_primary": q.body_primary,
                "body_secondary": q.body_secondary,
                "marks": float(ref.get("marks") or q.marks),
                "options": [
                    {
                        "id": str(o.id),
                        "label": o.label,
                        "body_primary": o.body_primary,
                        "body_secondary": o.body_secondary,
                    }
                    for o in opts
                ],
            }
            for ref, q, opts in items
        ]
        return QuizStartResponse(
            attempt_id=live.id, attempt_no=live.attempt_no, ends_at=ends, questions=qs, answers=live.answers or {}
        )

    async def _attempt(self, atid: uuid.UUID, *, own: bool = True) -> tuple[QuizAttempt, Quiz]:
        at = (
            await self.db.execute(
                select(QuizAttempt)
                .where(QuizAttempt.id == atid, QuizAttempt.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if at is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Attempt not found")
        if own and at.student_program_enrollment_id not in await self.my_enrolment_ids():
            raise APIError(404, ErrorCode.NOT_FOUND, "Attempt not found")
        quiz = (await self.db.execute(select(Quiz).where(Quiz.id == at.quiz_id))).scalar_one()
        return at, quiz

    async def save_answers(self, atid: uuid.UUID, body: QuizAnswerSave) -> QuizStartResponse:
        at, quiz = await self._attempt(atid)
        if at.status != "in_progress":
            raise APIError(409, ErrorCode.CONFLICT, f"Attempt is {at.status}")
        if now_utc() > at.started_at + timedelta(minutes=quiz.duration_minutes, seconds=30):
            await self._finish(quiz, at, "auto_submitted")
            raise APIError(409, ErrorCode.CONFLICT, "Time is up — the attempt was submitted", {"code": "TIME_UP"})
        at.answers = {**(at.answers or {}), **body.answers}
        if body.proctor_events:
            at.proctor_events = [*(at.proctor_events or []), *body.proctor_events]
            limit = int((quiz.proctoring or {}).get("tab_switch_limit") or 0)
            switches = sum(1 for e in at.proctor_events if e.get("type") == "tab_switch")
            if limit and switches > limit:
                await self._finish(quiz, at, "auto_submitted")
        await self.db.flush()
        return QuizStartResponse(
            attempt_id=at.id,
            attempt_no=at.attempt_no,
            ends_at=at.started_at + timedelta(minutes=quiz.duration_minutes),
            answers=at.answers or {},
        )

    async def _finish(self, quiz: Quiz, at: QuizAttempt, status: str) -> None:
        items = await self._paper_questions(quiz)
        auto = Decimal(0)
        manual_needed = False
        answers = at.answers or {}
        for ref, q, opts in items:
            marks = Decimal(str(ref.get("marks") or q.marks))
            given = answers.get(str(q.id))
            if q.question_type not in AUTO_SCORED:
                manual_needed = True
                continue
            correct_ids = {str(o.id) for o in opts if o.is_correct}
            if q.question_type == "mcq" and given and str(given) in correct_ids or q.question_type == "msq" and isinstance(given, list) and set(map(str, given)) == correct_ids or (
                q.question_type == "true_false"
                and given is not None
                and str(given).lower() == str(q.answer_key).lower()
            ):
                auto += marks
            elif q.question_type in ("numeric", "fill_blank") and given is not None and q.answer_key is not None:
                key = q.answer_key if isinstance(q.answer_key, dict) else {"value": q.answer_key}
                try:
                    tol = float(key.get("tolerance") or 0)
                    if abs(float(given) - float(key.get("value") or 0)) <= tol:
                        auto += marks
                except (TypeError, ValueError):
                    if str(given).strip().lower() == str(key.get("value")).strip().lower():
                        auto += marks
        at.auto_score = q2(auto)
        at.total_score = q2(auto + Decimal(str(at.manual_score or 0)))
        at.submitted_at = now_utc()
        at.status = status if manual_needed or status == "auto_submitted" else "graded"
        if at.status == "auto_submitted" and not manual_needed:
            at.status = "graded"
        await self.db.flush()
        await self._emit("quiz.attempt_submitted", {"quiz_id": str(quiz.id), "attempt_id": str(at.id)}, "quiz", quiz.id)

    async def submit_attempt(self, atid: uuid.UUID) -> QuizSubmitResponse:
        at, quiz = await self._attempt(atid)
        if at.status != "in_progress":
            raise APIError(409, ErrorCode.CONFLICT, f"Attempt is {at.status}")
        await self._finish(quiz, at, "submitted")
        show = quiz.show_result == "immediate"
        return QuizSubmitResponse(
            attempt_id=at.id,
            status=at.status,
            auto_score=float(at.auto_score) if show and at.auto_score is not None else None,
            total_score=float(at.total_score) if show and at.total_score is not None else None,
            show_result=show,
        )

    async def auto_submit(self) -> int:
        n = 0
        rows = (
            await self.db.execute(
                select(QuizAttempt, Quiz)
                .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
                .where(QuizAttempt.institution_id == self.inst, QuizAttempt.status == "in_progress")
            )
        ).all()
        now = now_utc()
        for at, quiz in rows:
            if now > at.started_at + timedelta(minutes=quiz.duration_minutes) or (quiz.ends_at and now > quiz.ends_at):
                await self._finish(quiz, at, "auto_submitted")
                n += 1
        return n

    async def attempts(self, qid: uuid.UUID) -> list[AttemptOut]:
        quiz = await self._quiz(qid)
        q = select(QuizAttempt).where(QuizAttempt.quiz_id == quiz.id).order_by(QuizAttempt.started_at)
        if not await self._staff_view(quiz.offering_id):
            q = q.where(
                QuizAttempt.student_program_enrollment_id.in_(list(await self.my_enrolment_ids()) or [uuid.uuid4()])
            )
        rows = list((await self.db.execute(q)).scalars().all())
        names = await self._names([r.student_program_enrollment_id for r in rows])
        out = []
        for r in rows:
            o = AttemptOut.model_validate(r)
            o.registration_number, o.student_name = names.get(r.student_program_enrollment_id, (None, None))
            out.append(o)
        return out

    async def grade_manual(self, qid: uuid.UUID, body: ManualGrade) -> list[AttemptOut]:
        quiz = await self._quiz(qid)
        await self.require_teacher(await self.offering(quiz.offering_id, "lms"), "lms")
        for row in body.rows:
            at, _ = await self._attempt(uuid.UUID(str(row["attempt_id"])), own=False)
            if at.quiz_id != quiz.id:
                raise APIError(422, ErrorCode.VALIDATION, "Attempt of another quiz")
            at.manual_score = q2(row.get("manual_score") or 0)
            at.total_score = q2(Decimal(str(at.auto_score or 0)) + at.manual_score)
            at.status = "graded"
        await self.db.flush()
        return await self.attempts(quiz.id)

    async def push_to_marks(self, qid: uuid.UUID) -> PushToMarksResult:
        quiz = await self._quiz(qid)
        await self.require_teacher(await self.offering(quiz.offering_id, "lms"), "lms")
        if not quiz.offering_assessment_id:
            raise rule("Link the quiz to an assessment component first", "NOT_LINKED", 422)
        a = (
            await self.db.execute(
                select(OfferingAssessment).where(OfferingAssessment.id == quiz.offering_assessment_id).with_for_update()
            )
        ).scalar_one()
        paper = (
            await self.db.execute(select(QuestionPaper).where(QuestionPaper.id == quiz.question_paper_id))
        ).scalar_one()
        total = Decimal(str(paper.total_marks or 0)) or Decimal(1)
        best: dict[uuid.UUID, Decimal] = {}
        for at in (
            await self.db.execute(
                select(QuizAttempt).where(
                    QuizAttempt.quiz_id == quiz.id, QuizAttempt.status.in_(("graded", "submitted", "auto_submitted"))
                )
            )
        ).scalars():
            if at.total_score is not None:
                best[at.student_program_enrollment_id] = max(
                    best.get(at.student_program_enrollment_id, Decimal(0)), Decimal(str(at.total_score))
                )
        out = PushToMarksResult()
        for enrol, score in best.items():
            await self.write_internal_mark(a, enrol, q2(score / total * Decimal(str(a.max_marks))), source="quiz")
            out.written += 1
        await self._audit("push_to_marks", "quiz", quiz.id, None, {"written": out.written})
        return out

    # ---- 4. announcements / discussions / links ------------------------------------------------------------------------------
    async def announcements(self, offering_id: uuid.UUID) -> list[AnnouncementOut]:
        offering = await self.offering(offering_id, "lms")
        rows = (
            (
                await self.db.execute(
                    select(CourseAnnouncement)
                    .where(CourseAnnouncement.offering_id == offering.id)
                    .order_by(CourseAnnouncement.pinned.desc(), CourseAnnouncement.posted_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [AnnouncementOut.model_validate(r) for r in rows]

    async def announce(self, offering_id: uuid.UUID, body: AnnouncementIn) -> AnnouncementOut:
        offering = await self.offering(offering_id, "lms")
        await self.require_teacher(offering, "lms")
        r = CourseAnnouncement(
            institution_id=self.inst, offering_id=offering.id, posted_by=self.actor_id, **body.model_dump()
        )
        self.db.add(r)
        await self.db.flush()
        await self._notify(
            "lms.announcement",
            [x[7] for x in await self.roster(offering)],
            {"title": body.title, "body": (body.body or "")[:200]},
        )
        return AnnouncementOut.model_validate(r)

    async def threads(self, offering_id: uuid.UUID) -> list[ThreadOut]:
        offering = await self.offering(offering_id, "lms")
        rows = (
            (
                await self.db.execute(
                    select(DiscussionThread)
                    .where(DiscussionThread.offering_id == offering.id)
                    .order_by(DiscussionThread.is_pinned.desc(), DiscussionThread.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )
        counts: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(DiscussionPost.thread_id, func.count())
                    .where(
                        DiscussionPost.thread_id.in_([r.id for r in rows] or [uuid.uuid4()]),
                        DiscussionPost.deleted_at.is_(None),
                    )
                    .group_by(DiscussionPost.thread_id)
                )
            ).all()
        )  # type: ignore[arg-type]
        out = []
        for r in rows:
            o = ThreadOut.model_validate(r)
            o.posts = int(counts.get(r.id, 0))
            out.append(o)
        return out

    async def _member(self, offering_id: uuid.UUID) -> None:
        offering = await self.offering(offering_id, "lms")
        if not await self.is_teacher(offering.id):
            await self.learner_enrolment(offering)

    async def create_thread(self, offering_id: uuid.UUID, body: ThreadIn) -> ThreadOut:
        await self._member(offering_id)
        t = DiscussionThread(
            institution_id=self.inst, offering_id=offering_id, title=body.title, created_by=self.actor_id
        )
        self.db.add(t)
        await self.db.flush()
        if body.body:
            self.db.add(
                DiscussionPost(institution_id=self.inst, thread_id=t.id, author_user_id=self.actor_id, body=body.body)
            )
            await self.db.flush()
        return ThreadOut.model_validate(t)

    async def _thread(self, tid: uuid.UUID, *, for_update: bool = False) -> DiscussionThread:
        q = select(DiscussionThread).where(DiscussionThread.id == tid, DiscussionThread.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        t = (await self.db.execute(q)).scalar_one_or_none()
        if t is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Thread not found")
        await self.offering(t.offering_id, "lms")
        return t

    async def patch_thread(self, tid: uuid.UUID, body: ThreadPatch) -> ThreadOut:
        t = await self._thread(tid, for_update=True)
        await self.require_teacher(await self.offering(t.offering_id, "lms"), "lms")
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(t, k, v)
        await self.db.flush()
        return ThreadOut.model_validate(t)

    async def posts(self, tid: uuid.UUID) -> list[PostOut]:
        t = await self._thread(tid)
        rows = (
            (
                await self.db.execute(
                    select(DiscussionPost)
                    .where(DiscussionPost.thread_id == t.id, DiscussionPost.deleted_at.is_(None))
                    .order_by(DiscussionPost.created_at)
                )
            )
            .scalars()
            .all()
        )
        users = {
            u.id: u
            for u in (
                await self.db.execute(
                    select(User).where(User.id.in_([r.author_user_id for r in rows] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        out = []
        for r in rows:
            o = PostOut.model_validate(r)
            u = users.get(r.author_user_id)
            o.author_name = (u.display_name or u.username) if u else None
            out.append(o)
        return out

    async def create_post(self, tid: uuid.UUID, body: PostIn) -> PostOut:
        t = await self._thread(tid)
        if t.is_locked:
            raise APIError(409, ErrorCode.CONFLICT, "The thread is locked", {"code": "THREAD_LOCKED"})
        await self._member(t.offering_id)
        p = DiscussionPost(
            institution_id=self.inst,
            thread_id=t.id,
            parent_post_id=body.parent_post_id,
            author_user_id=self.actor_id,
            body=body.body,
            attachments=body.attachments,
        )
        self.db.add(p)
        t.updated_at = now_utc()
        await self.db.flush()
        return PostOut.model_validate(p)

    async def _post(self, pid: uuid.UUID) -> tuple[DiscussionPost, DiscussionThread]:
        p = (
            await self.db.execute(
                select(DiscussionPost)
                .where(DiscussionPost.id == pid, DiscussionPost.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if p is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Post not found")
        return p, await self._thread(p.thread_id)

    async def upvote(self, pid: uuid.UUID) -> PostOut:
        p, t = await self._post(pid)
        await self._member(t.offering_id)
        p.upvotes += 1
        await self.db.flush()
        return PostOut.model_validate(p)

    async def mark_answer(self, pid: uuid.UUID) -> PostOut:
        p, t = await self._post(pid)
        if not (await self.is_teacher(t.offering_id) or t.created_by == self.actor_id):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Only the thread author or the faculty may mark the answer"
            )
        p.is_answer = True
        await self.db.flush()
        return PostOut.model_validate(p)

    async def online_link(self, offering_id: uuid.UUID, body: OnlineLinkRequest) -> dict[str, Any]:
        offering = await self.offering(offering_id, "lms", for_update=True)
        await self.require_teacher(offering, "lms")
        link = body.link
        if not link:
            from app.integrations.registry import get_adapter

            meeting = await get_adapter("video_conf", body.provider or "mock").send(topic=str(offering.id))
            link = f"https://meet.example.invalid/{meeting.get('reference')}"
        offering.online_class_link = link
        await self.db.flush()
        return {"offering_id": str(offering.id), "online_class_link": link}

    async def session_meeting(self, session_id: uuid.UUID, body: OnlineLinkRequest) -> dict[str, Any]:
        from app.models.timetable import ClassSession

        s = (
            await self.db.execute(
                select(ClassSession)
                .where(ClassSession.id == session_id, ClassSession.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Session not found")
        out = await self.online_link(s.offering_id, body)
        await self._audit("meeting", "class_session", s.id, None, out)
        return {**out, "session_id": str(s.id)}
