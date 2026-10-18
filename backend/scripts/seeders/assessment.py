"""``assessment`` demo seeder (Prompts/13 §13.2) — ``seed_demo_institution.py --type university --only assessment``.

On top of ``attendance`` (offerings of the current term with confirmed rosters):

* programme outcomes from the NBA / generic template (+ 2 PSOs) for every programme with offerings this term;
* 6 COs per course of the term's offerings with a CO-PO matrix (2–3 POs per CO, levels 1–3, a justification);
* offering assessments instantiated from each offering's scheme; CAT-1 (the first ``cia`` component) gets a question
  map (parts A / B, COs round-robin) and question-wise marks for every rostered student — the first offerings'
  CAT-1 ``locked``, the next ``verified`` / ``submitted``, the rest ``marks_entry``; 2 change requests on locked marks;
* LMS for 10 offerings (2 modules, 3 contents each), 3 assignments with submissions, a 10-MCQ question bank per course
  + blueprint + frozen paper, 2 quizzes with attempts, 5 projects with a review, lesson plans (12 items, 3 delivered)
  and course files.

Idempotent: everything dedupes on its natural key (outcome codes, CO codes, ``(offering, component)``, titles).
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


def _roll(*parts: object) -> float:
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:4], "big") / 2**32


@seeder("assessment", after=["attendance"])
async def seed_assessment(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401  (``is_enabled`` needs the full registry outside the API process)
    from app.core.errors import APIError
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import AcademicTerm, Program
    from app.models.assessment import InternalMark, MarksChangeRequest, OfferingAssessment
    from app.models.content import Question
    from app.models.curriculum import AssessmentComponent, Course
    from app.models.lms import AssignmentSubmission, CourseModule, LessonPlan, LmsAssignment, Quiz, QuizAttempt
    from app.models.obe import CourseOutcome
    from app.models.offerings import CourseOffering
    from app.models.platform import Institution, User
    from app.models.projects import StudentProject
    from app.schemas.assessment import (
        AssessmentQuestionIn,
        MarkRowIn,
        MarksBulkUpsert,
        QuestionMapReplace,
        VerifyRequest,
    )
    from app.schemas.content import BlueprintIn, OptionIn, PaperGenerateRequest, QuestionIn
    from app.schemas.lms import AssignmentIn, ContentIn, LessonPlanIn, LessonPlanReplace, ModuleIn, QuizIn
    from app.schemas.obe import CoIn, CoPoCell, CoPoMatrixReplace, CoReplace, TemplateImport
    from app.schemas.projects import ProjectIn, ReviewIn
    from app.services.assessment.assessment_service import AssessmentService
    from app.services.assessment.content_service import ContentService
    from app.services.assessment.lesson_service import LessonService
    from app.services.assessment.lms_service import LmsService
    from app.services.assessment.obe_service import ObeService
    from app.services.assessment.project_service import ProjectService
    from app.services.auth_service import load_principal

    db = ctx.db
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    admin = (await db.execute(select(User).where(User.institution_id == inst.id, User.username == "inst.admin"))).scalar_one()
    p = await load_principal(db, admin.id)
    today = today_for(inst)
    term = (
        await db.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution_id == inst.id,
                AcademicTerm.college_id.is_(None),
                AcademicTerm.is_current.is_(True),
                AcademicTerm.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    offerings = (
        await db.execute(
            select(CourseOffering)
            .where(CourseOffering.institution_id == inst.id, CourseOffering.term_id == term.id, CourseOffering.deleted_at.is_(None))
            .order_by(CourseOffering.created_at)
        )
    ).scalars().all()
    svc = AssessmentService(db, p, institution_id=inst.id)
    obe = ObeService(db, p, institution_id=inst.id)
    lms = LmsService(db, p, institution_id=inst.id)
    lesson = LessonService(db, p, institution_id=inst.id)
    content = ContentService(db, p, institution_id=inst.id)
    projects = ProjectService(db, p, institution_id=inst.id)

    # ---- OBE definitions ----------------------------------------------------------------------------------------------
    program_ids = set()
    for o in offerings:
        pid = (await db.execute(select(Program.id).join(Course, Course.department_id == Program.department_id).where(Course.id == o.course_id).limit(1))).scalar_one_or_none()
        if pid:
            program_ids.add(pid)
    for pid in program_ids:
        if not (await obe.program_outcomes(pid)).outcomes:
            await obe.import_template(pid, TemplateImport())
            ctx.count("program_outcomes")
    course_ids = list(dict.fromkeys(o.course_id for o in offerings))
    blooms = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
    for cid in course_ids:
        existing = (await db.execute(select(func.count()).select_from(CourseOutcome).where(CourseOutcome.course_id == cid))).scalar_one()
        if existing:
            continue
        course = await svc.course(cid)
        try:
            await obe.replace_cos(cid, CoReplace(outcomes=[CoIn(code=f"CO{i}", statement=f"{course.title}: outcome {i} — students will be able to {blooms[i - 1]} the unit {i} concepts.", bloom_level=blooms[i - 1], sequence=i) for i in range(1, 7)]))
            data = await obe.course_outcomes(cid)
            pos = [x for x in data.program_outcomes if x.outcome_type == "PO"]
            if pos:
                cells = []
                for i, co in enumerate(data.cos):
                    for k in range(2 + i % 2):
                        po = pos[(i * 2 + k) % len(pos)]
                        cells.append(CoPoCell(co_id=co.id, outcome_id=po.id, level=1 + (i + k) % 3, justification=f"{co.code} exercises {po.code}"))
                await obe.replace_matrix(cid, CoPoMatrixReplace(cells=cells))
            ctx.count("course_outcomes", 6)
        except APIError:
            pass

    # ---- assessments + CAT-1 marks -------------------------------------------------------------------------------------
    marked = 0
    for n, o in enumerate(offerings):
        try:
            await svc.instantiate(o.id)
        except APIError:
            continue
        cat1 = (
            await db.execute(
                select(OfferingAssessment)
                .join(AssessmentComponent, AssessmentComponent.id == OfferingAssessment.component_id)
                .where(OfferingAssessment.offering_id == o.id, AssessmentComponent.category == "cia")
                .order_by(AssessmentComponent.sequence)
                .limit(1)
            )
        ).scalar_one_or_none()
        if cat1 is None or (await db.execute(select(func.count()).select_from(InternalMark).where(InternalMark.offering_assessment_id == cat1.id))).scalar_one():
            continue
        cos = (await db.execute(select(CourseOutcome).where(CourseOutcome.course_id == o.course_id).order_by(CourseOutcome.sequence))).scalars().all()
        mx = Decimal(str(cat1.max_marks))
        a_marks = (mx * Decimal("0.4")).quantize(Decimal("1"))
        b_marks = mx - a_marks
        qmap = [AssessmentQuestionIn(question_no="A1", max_marks=float(a_marks / 2), part="A", co_id=cos[0].id if cos else None, bloom_level="remember"),
                AssessmentQuestionIn(question_no="A2", max_marks=float(a_marks - a_marks / 2), part="A", co_id=cos[1].id if len(cos) > 1 else None, bloom_level="understand"),
                AssessmentQuestionIn(question_no="B1", max_marks=float(b_marks / 2), part="B", co_id=cos[2].id if len(cos) > 2 else None, bloom_level="apply"),
                AssessmentQuestionIn(question_no="B2", max_marks=float(b_marks - b_marks / 2), part="B", co_id=cos[3].id if len(cos) > 3 else None, bloom_level="analyze")]
        await svc.replace_questions(cat1.id, QuestionMapReplace(questions=qmap))
        roster = await svc.roster(o)
        rows = []
        for r in roster:
            if _roll(r[0], o.id, "absent") < 0.04:
                rows.append(MarkRowIn(student_program_enrollment_id=r[0], is_absent=True))
                continue
            qw = {q.question_no: round(q.max_marks * (0.45 + 0.5 * _roll(r[0], q.question_no, o.id)) * 2) / 2 for q in qmap}
            rows.append(MarkRowIn(student_program_enrollment_id=r[0], question_wise=qw))
        if not rows:
            continue
        await svc.bulk_upsert(cat1.id, MarksBulkUpsert(rows=rows, source="seed"))
        marked += len(rows)
        stage = n % 4
        if stage >= 1:
            await svc.submit(cat1.id)
        if stage >= 2:
            await svc.verify(cat1.id, VerifyRequest())
        if stage >= 3:
            await svc.lock(cat1.id)
    ctx.count("internal_marks", marked)

    # change requests on locked marks
    if not (await db.execute(select(func.count()).select_from(MarksChangeRequest).where(MarksChangeRequest.institution_id == inst.id))).scalar_one():
        locked = (await db.execute(select(InternalMark).join(OfferingAssessment, OfferingAssessment.id == InternalMark.offering_assessment_id).where(OfferingAssessment.institution_id == inst.id, OfferingAssessment.status == "locked", InternalMark.marks.is_not(None)).limit(2))).scalars().all()
        from app.schemas.assessment import ChangeRequestCreate

        for m in locked:
            try:
                await svc.create_change(ChangeRequestCreate(target_id=m.id, new_value={"marks": float(min(Decimal(str(m.marks)) + 2, Decimal(str((await db.execute(select(OfferingAssessment.max_marks).where(OfferingAssessment.id == m.offering_assessment_id))).scalar_one()))))}, reason="Totalling error on the answer script"))
                ctx.count("marks_change_requests")
            except APIError:
                pass

    # ---- question bank / papers ------------------------------------------------------------------------------------------
    papers: dict[uuid.UUID, uuid.UUID] = {}
    ranked = [o.course_id for size, o in sorted([(len(await svc.roster(o)), o) for o in offerings], key=lambda x: -x[0]) if size]
    for cid in list(dict.fromkeys(ranked))[:4]:
        have = (await db.execute(select(func.count()).select_from(Question).where(Question.course_id == cid))).scalar_one()
        cos = (await db.execute(select(CourseOutcome).where(CourseOutcome.course_id == cid).order_by(CourseOutcome.sequence))).scalars().all()
        if not have:
            for i in range(12):
                await content.create_question(QuestionIn(course_id=cid, co_id=cos[i % len(cos)].id if cos else None, question_type="mcq", body_primary=f"Question {i + 1}: which statement is correct?", body_secondary=f"प्रश्न {i + 1}: कौन सा कथन सही है?", marks=1, difficulty=("easy", "medium", "hard")[i % 3], bloom_level=blooms[i % 6], options=[OptionIn(body_primary=f"Option {x}", is_correct=x == "B") for x in "ABCD"]))
            ctx.count("questions", 12)
        from app.models.content import QuestionPaper

        prior = (await db.execute(select(QuestionPaper.id).where(QuestionPaper.course_id == cid, QuestionPaper.status.in_(("frozen", "used"))).limit(1))).scalar_one_or_none()
        if prior is not None:
            papers[cid] = prior
            continue
        bp = await content.create_blueprint(BlueprintIn(course_id=cid, name=f"Quiz blueprint {str(cid)[:6]}", total_marks=10, duration_minutes=15, pattern={"parts": [{"title": "Part A", "count": 10, "marks": 1, "question_types": ["mcq"]}]}))
        paper = await content.generate(PaperGenerateRequest(blueprint_id=bp.id, title="Weekly quiz", purpose="quiz", seed=7))
        await content.freeze(paper.id)
        papers[cid] = paper.id

    # ---- LMS for 10 offerings ---------------------------------------------------------------------------------------------
    now = datetime.now(UTC)
    quizzes_made = assignments_made = 0
    sized = [(len(await svc.roster(o)), o) for o in offerings]
    lms_offerings = [o for size, o in sorted(sized, key=lambda x: -x[0]) if size][:10]
    for n, o in enumerate(lms_offerings):
        if (await db.execute(select(func.count()).select_from(CourseModule).where(CourseModule.offering_id == o.id))).scalar_one():
            continue
        for mi in (1, 2):
            mod = await lms.save_module(o.id, ModuleIn(title=f"Unit {mi}", sequence=mi, is_published=True))
            for ci, (ctype, title) in enumerate((("file", "Lecture notes"), ("video", "Recorded lecture"), ("link", "Further reading"))):
                await lms.save_content(mod.id, ContentIn(content_type=ctype, title=f"{title} — unit {mi}", file_url=f"https://example.invalid/{o.id}/{mi}/{ci}", sequence=ci + 1))  # type: ignore[arg-type]
        await lesson.replace(o.id, LessonPlanReplace(items=[LessonPlanIn(unit_no=1 + i // 4, topic=f"Topic {i + 1}", planned_date=term.start_date + timedelta(days=3 * i), planned_hours=1, sequence=i + 1) for i in range(12)]))
        for item in (await db.execute(select(LessonPlan).where(LessonPlan.offering_id == o.id).order_by(LessonPlan.sequence).limit(3))).scalars().all():
            from app.schemas.lms import DeliverRequest

            await lesson.deliver(item.id, DeliverRequest(actual_date=(item.planned_date or today) + timedelta(days=1)))
        await lesson.course_file(o.id)
        roster = await svc.roster(o)
        if assignments_made < 3 and roster:
            asg = await lms.save_assignment(o.id, AssignmentIn(title="Problem set 1", instructions="Solve the five problems.", due_at=now - timedelta(days=1), max_marks=10, late_penalty_pct_per_day=10, rubric=[{"criterion": "correctness", "max": 7}, {"criterion": "presentation", "max": 3}]))
            await lms.set_assignment_status(asg.id, "published")
            for r in roster[:8]:
                db.add(AssignmentSubmission(institution_id=inst.id, assignment_id=asg.id, student_program_enrollment_id=r[0], text_answer="My answers are attached.", submitted_at=now - timedelta(days=2) if _roll(r[0], "late") > 0.2 else now, is_late=_roll(r[0], "late") <= 0.2, status="submitted"))
            await db.flush()
            assignments_made += 1
        paper_id = papers.get(o.course_id)
        if quizzes_made < 2 and paper_id and roster:
            qz = await lms.save_quiz(o.id, QuizIn(title="Weekly quiz 1", question_paper_id=paper_id, duration_minutes=15, show_result="immediate"))
            quiz = (await db.execute(select(Quiz).where(Quiz.id == qz.id))).scalar_one()
            quiz.status = "published"
            for r in roster[:6]:
                at = QuizAttempt(institution_id=inst.id, quiz_id=quiz.id, student_program_enrollment_id=r[0], attempt_no=1, started_at=now - timedelta(hours=2), answers={}, status="in_progress")
                db.add(at)
                await db.flush()
                await lms._finish(quiz, at, "submitted")
            quizzes_made += 1
        if n < 5 and len(roster) >= 2 and not (await db.execute(select(func.count()).select_from(StudentProject).where(StudentProject.offering_id == o.id))).scalar_one():
            pr = await projects.create(o.id, ProjectIn(title=f"Mini project {n + 1}", project_type="mini", members=[r[0] for r in roster[: min(3, len(roster))]]))
            await projects.review(pr.id, ReviewIn(review_no=1, scheduled_on=today, rubric_scores={"problem": 8, "design": 7, "presentation": 4}, remarks="Good start"))
            ctx.count("projects")
    ctx.count("assignments", assignments_made)
    ctx.count("quizzes", quizzes_made)
    _ = LmsAssignment
