"""``post_result`` demo seeder (Prompts/16 §16.2) — ``seed_demo_institution.py --only post_result``.

On top of ``results``: a discipline committee, reval requests of mixed types / states (some marks changed),
malpractice cases across stages, transcript requests and a published term rank list with a gold medal.
Idempotent: skipped when the session already has reval requests.
"""

from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


@seeder("post_result", after=["results"])
async def seed_post_result(ctx: SeedContext) -> None:  # noqa: C901, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.db.session import bind_tenant, set_tenant
    from app.models.exams import ExamRegistrationItem, ExamSession
    from app.models.platform import Institution, User
    from app.models.post_result import Committee, RevalRequest
    from app.models.results import ResultProcessingRun, StudentCourseResult
    from app.models.students import StudentProgramEnrollment
    from app.schemas.post_result import (
        InquiryUpdate,
        MalpracticeCaseCreate,
        MalpracticeDecision,
        MedalAwardCreate,
        RankListPublish,
        TranscriptRequestCreate,
    )
    from app.services.auth_service import load_principal
    from app.services.post_result.malpractice_service import MalpracticeService
    from app.services.post_result.rank_service import RankService
    from app.services.post_result.transcript_service import TranscriptService

    db = ctx.db
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)

    async def principal(name: str) -> object | None:
        u = (await db.execute(select(User).where(User.institution_id == inst.id, User.username == name))).scalar_one_or_none()
        return await load_principal(db, u.id) if u else None

    admin = await principal("inst.admin")
    coe = await principal("coe") or admin
    registrar = await principal("registrar") or admin
    run = (
        await db.execute(
            select(ResultProcessingRun)
            .where(ResultProcessingRun.institution_id == inst.id, ResultProcessingRun.status == "published")
            .order_by(ResultProcessingRun.published_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None or run.exam_session_id is None:
        print("   post_result: no published result run — run --only results first")
        return
    s = (await db.execute(select(ExamSession).where(ExamSession.id == run.exam_session_id))).scalar_one()
    if (await db.execute(select(func.count()).select_from(RevalRequest).where(RevalRequest.exam_session_id == s.id))).scalar_one():
        return

    db.add(Committee(institution_id=inst.id, name="Examination discipline committee", committee_type="discipline"))
    await db.flush()
    ctx.count("committees")

    rows = list(
        (
            await db.execute(
                select(StudentCourseResult).where(
                    StudentCourseResult.exam_session_id == s.id,
                    StudentCourseResult.is_current.is_(True),
                    StudentCourseResult.status == "published",
                    StudentCourseResult.result_status.in_(("pass", "fail")),
                    StudentCourseResult.exam_registration_item_id.is_not(None),
                )
                .limit(40)
            )
        ).scalars()
    )
    types = ("revaluation", "retotaling", "photocopy", "revaluation", "revaluation")
    states = ("submitted", "fee_paid", "evaluated", "no_change", "marks_changed")
    changed = 0
    for i, r in enumerate(rows[:25]):
        st = states[i % len(states)]
        if st == "marks_changed":
            changed += 1
        orig = r.ese_marks or Decimal(40)
        db.add(
            RevalRequest(
                institution_id=inst.id,
                exam_session_id=s.id,
                exam_registration_item_id=r.exam_registration_item_id,
                request_type=types[i % len(types)],
                status=st,
                original_marks=orig,
                revised_marks=orig + 8 if st == "marks_changed" else (orig + 2 if st in ("evaluated", "no_change") else None),
                delta=Decimal(8) if st == "marks_changed" else (Decimal(2) if st in ("evaluated", "no_change") else None),
                refund_due=st == "marks_changed",
            )
        )
        ctx.count("reval_requests")
    await db.flush()

    mal = MalpracticeService(db, coe, institution_id=inst.id)
    for i, r in enumerate(rows[25:30]):
        try:
            c = await mal.create(
                MalpracticeCaseCreate(
                    exam_registration_item_id=r.exam_registration_item_id,  # type: ignore[arg-type]
                    category=("copying", "device", "material", "misconduct", "impersonation")[i],
                    invigilator_report="Reported by the hall invigilator (demo)",
                )
            )
            ctx.count("malpractice_cases")
            if i >= 1:
                await mal.inquiry(c.id, InquiryUpdate())
            if i >= 3:
                await mal.decide(
                    c.id,
                    MalpracticeDecision(
                        punishment="debar_terms" if i == 4 else "cancel_paper",
                        debar_terms=2 if i == 4 else None,
                        decision_text="Decided by the committee (demo)",
                    ),
                )
        except APIError as exc:
            print(f"   malpractice case skipped: {exc.message}")
    _ = ExamRegistrationItem

    enrs = list(
        (
            await db.execute(
                select(StudentCourseResult.student_program_enrollment_id)
                .where(StudentCourseResult.run_id == run.id)
                .distinct()
                .limit(12)
            )
        ).scalars()
    )
    tsvc = TranscriptService(db, registrar, institution_id=inst.id)
    for i, e in enumerate(enrs):
        try:
            t = await tsvc.request_transcript(
                TranscriptRequestCreate(transcript_type="consolidated" if i % 3 else "provisional", copies=1 + i % 2, enrollment_id=e)
            )
            ctx.count("transcripts")
            if i % 4 == 0:
                continue
            await tsvc.on_paid(t.id)
            if i % 4 >= 2:
                await tsvc.mark_approved(await tsvc.tr(t.id))
                await tsvc.generate(t.id)
                if i % 4 == 3:
                    from app.schemas.post_result import TranscriptIssueRequest

                    await tsvc.issue(t.id, TranscriptIssueRequest())
        except APIError as exc:
            print(f"   transcript skipped: {exc.message}")

    if enrs:
        batch = (await db.execute(select(StudentProgramEnrollment.batch_id).where(StudentProgramEnrollment.id == enrs[0]))).scalar_one()
        rk = RankService(db, coe, institution_id=inst.id)
        out = await rk.publish(RankListPublish(batch_id=batch, term_id=s.term_id, top_n=10))
        ctx.count("rank_lists")
        if out.entries and out.entries[0].student_program_enrollment_id:
            try:
                await rk.award(
                    MedalAwardCreate(batch_id=batch, medal="gold", student_program_enrollment_id=out.entries[0].student_program_enrollment_id)
                )
                ctx.count("medals")
            except APIError as exc:
                print(f"   medal skipped: {exc.message}")
    print(f"   post_result: {changed} reval requests with marks changed")
