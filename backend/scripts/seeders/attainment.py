"""``attainment`` demo seeder (Prompts/17 §17.2) — ``seed_demo_institution.py --only attainment``.

On top of ``post_result``: enables ``obe.attainment`` / ``obe.cqi`` / ``obe.nba_export`` (and ``obe.indirect_surveys``
when its dependency is available), saves a config for every programme with outcomes, tags the CIA questions of the
published term's offerings to COs (question-wise marks split from the totals where missing), adds a course-exit survey
with mock responses for 6 offerings and a programme-exit survey tagged to POs, computes CO runs for every offering of
the published term (``force`` — demo CIA is not fully locked), a PO run for batch 2024 and 8 CQI actions.
Idempotent: skipped when attainment runs exist.
"""

import hashlib
import random
from datetime import timedelta
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


@seeder("attainment", after=["post_result"])
async def seed_attainment(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import Batch, Program
    from app.models.assessment import AssessmentQuestion, InternalMark, OfferingAssessment
    from app.models.curriculum import AssessmentComponent
    from app.models.exams import ExamSession
    from app.models.hr import Staff
    from app.models.obe import CourseOutcome, OutcomeDefinition
    from app.models.obe_attainment import AttainmentRun, FeedbackResponse, FeedbackSurvey
    from app.models.offerings import CourseOffering, CourseOfferingTarget
    from app.models.platform import Institution, User
    from app.models.results import ResultProcessingRun
    from app.schemas.obe_attainment import AttainmentConfigIn, CqiActionIn, CqiStatusChange, CqiVerify, PoRunRequest
    from app.services.auth_service import load_principal
    from app.services.feature_service import FeatureService
    from app.services.obe.co_service import CoAttainmentService
    from app.services.obe.config_service import AttainmentConfigService
    from app.services.obe.cqi_service import CqiService
    from app.services.obe.po_service import PoAttainmentService

    db = ctx.db
    rng = random.Random(17)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(AttainmentRun).where(AttainmentRun.institution_id == inst.id))
    ).scalar_one():
        return

    async def principal(name: str) -> object | None:
        u = (
            await db.execute(select(User).where(User.institution_id == inst.id, User.username == name))
        ).scalar_one_or_none()
        return await load_principal(db, u.id) if u else None

    admin = await principal("inst.admin")
    obe = await principal("obe") or admin

    # ---- features ----------------------------------------------------------------------------------------------------
    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in ("obe.attainment", "obe.cqi", "obe.nba_export", "obe.indirect_surveys"):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 17)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   attainment: {key} not enabled ({exc})")

    # ---- published term ----------------------------------------------------------------------------------------------
    run = (
        await db.execute(
            select(ResultProcessingRun)
            .where(ResultProcessingRun.institution_id == inst.id, ResultProcessingRun.status == "published")
            .order_by(ResultProcessingRun.published_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None or run.exam_session_id is None:
        print("   attainment: no published result run — run --only results first")
        return
    term_id = (await db.execute(select(ExamSession.term_id).where(ExamSession.id == run.exam_session_id))).scalar_one()
    offerings = (
        (
            await db.execute(
                select(CourseOffering)
                .where(
                    CourseOffering.institution_id == inst.id,
                    CourseOffering.term_id == term_id,
                    CourseOffering.deleted_at.is_(None),
                )
                .order_by(CourseOffering.created_at)
            )
        )
        .scalars()
        .all()
    )

    # ---- configs for programmes with outcomes ------------------------------------------------------------------------
    cfg = AttainmentConfigService(db, obe, institution_id=inst.id)
    programs = (
        (
            await db.execute(
                select(Program).where(
                    Program.institution_id == inst.id,
                    Program.id.in_(
                        select(OutcomeDefinition.scope_id).where(
                            OutcomeDefinition.scope_type == "program", OutcomeDefinition.outcome_type == "PO"
                        )
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for p in programs:
        await cfg.put(
            AttainmentConfigIn(
                scope_type="program",
                scope_id=p.id,
                levels=[{"level": 1, "min_pct": 40}, {"level": 2, "min_pct": 50}, {"level": 3, "min_pct": 60}],  # type: ignore[list-item]
            )
        )
        ctx.count("attainment_configs")

    # ---- CO-tag CIA questions + question-wise marks ------------------------------------------------------------------
    for o in offerings:
        cos = (
            (
                await db.execute(
                    select(CourseOutcome).where(CourseOutcome.course_id == o.course_id).order_by(CourseOutcome.sequence)
                )
            )
            .scalars()
            .all()
        )
        if not cos:
            continue
        assessments = (
            (
                await db.execute(
                    select(OfferingAssessment)
                    .join(AssessmentComponent, AssessmentComponent.id == OfferingAssessment.component_id)
                    .where(OfferingAssessment.offering_id == o.id, AssessmentComponent.category == "cia")
                )
            )
            .scalars()
            .all()
        )
        for n, a in enumerate(assessments):
            qs = (
                (await db.execute(select(AssessmentQuestion).where(AssessmentQuestion.offering_assessment_id == a.id)))
                .scalars()
                .all()
            )
            if not qs:
                mx = Decimal(str(a.max_marks))
                split = [mx * Decimal("0.3"), mx * Decimal("0.3"), mx - mx * Decimal("0.6")]
                qs = []
                for i, part in enumerate(split):
                    q = AssessmentQuestion(
                        institution_id=inst.id,
                        offering_assessment_id=a.id,
                        question_no=f"Q{i + 1}",
                        max_marks=part.quantize(Decimal("0.01")),
                        co_id=cos[(n * 2 + i) % len(cos)].id,
                    )
                    db.add(q)
                    qs.append(q)
                await db.flush()
                ctx.count("assessment_questions", 3)
            total_max = sum(float(q.max_marks) for q in qs) or 1.0
            for m in (
                (
                    await db.execute(
                        select(InternalMark).where(
                            InternalMark.offering_assessment_id == a.id, InternalMark.marks.is_not(None)
                        )
                    )
                )
                .scalars()
                .all()
            ):
                if m.question_wise and any(not str(k).startswith("_") for k in m.question_wise):
                    continue
                ratio = float(m.marks) / total_max  # type: ignore[arg-type]
                qw = {}
                for q in qs:
                    jitter = max(0.0, min(1.0, ratio + rng.uniform(-0.12, 0.12)))
                    qw[q.question_no] = round(float(q.max_marks) * jitter, 1)
                m.question_wise = qw
    await db.flush()

    # ---- surveys -----------------------------------------------------------------------------------------------------
    course_exit = FeedbackSurvey(
        institution_id=inst.id,
        survey_type="course_exit",
        term_id=term_id,
        title="Course exit survey (demo)",
        questions=[{"id": f"q{i}", "text": f"I can achieve CO{i}", "co": f"CO{i}", "scale": 5} for i in range(1, 7)],
        status="closed",
    )
    db.add(course_exit)
    await db.flush()
    for o in offerings[:6]:
        for r in range(12):
            db.add(
                FeedbackResponse(
                    institution_id=inst.id,
                    survey_id=course_exit.id,
                    respondent_hash=hashlib.sha256(f"{o.id}:{r}".encode()).hexdigest(),
                    target_type="offering",
                    target_id=o.id,
                    answers={f"q{i}": rng.choice((2, 3, 3, 4, 4, 5)) for i in range(1, 7)},
                )
            )
            ctx.count("feedback_responses")
    for p in programs:
        pos = (
            (
                await db.execute(
                    select(OutcomeDefinition.code).where(
                        OutcomeDefinition.scope_type == "program",
                        OutcomeDefinition.scope_id == p.id,
                        OutcomeDefinition.outcome_type.in_(("PO", "PSO")),
                    )
                )
            )
            .scalars()
            .all()
        )
        exit_s = FeedbackSurvey(
            institution_id=inst.id,
            survey_type="program_exit",
            title=f"Programme exit survey {p.code} (demo)",
            questions=[{"id": c.lower(), "text": f"Attainment of {c}", "outcome": c, "scale": 5} for c in pos],
            status="closed",
        )
        db.add(exit_s)
        await db.flush()
        for r in range(20):
            db.add(
                FeedbackResponse(
                    institution_id=inst.id,
                    survey_id=exit_s.id,
                    respondent_hash=hashlib.sha256(f"{p.id}:{r}".encode()).hexdigest(),
                    target_type="program",
                    target_id=p.id,
                    answers={c.lower(): rng.choice((2, 3, 4, 4, 5)) for c in pos},
                )
            )
            ctx.count("feedback_responses")
    await db.flush()

    # ---- CO runs (published term) + PO run for batch 2024 ------------------------------------------------------------
    co = CoAttainmentService(db, obe, institution_id=inst.id)
    stats = await co.run_many([o.id for o in offerings], force=True)
    ctx.count("co_runs", stats["computed"])
    po = PoAttainmentService(db, obe, institution_id=inst.id)
    batches = (
        (
            await db.execute(
                select(Batch)
                .join(CourseOfferingTarget, CourseOfferingTarget.batch_id == Batch.id)
                .where(CourseOfferingTarget.offering_id.in_([o.id for o in offerings] or [inst.id]))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    pick = [b for b in batches if b.admission_year == 2024] or batches[:1]
    for b in pick:
        try:
            await po.request_run(b.program_id, b.id, PoRunRequest(), inline=True)
            ctx.count("po_runs")
        except APIError as exc:
            print(f"   attainment: PO run {b.code} skipped ({exc.message})")

    # ---- CQI actions -------------------------------------------------------------------------------------------------
    hod = (
        await db.execute(
            select(Staff.id)
            .join(User, User.id == Staff.user_id)
            .where(User.institution_id == inst.id, User.username == "hod.cse")
        )
    ).scalar_one_or_none()
    fac = (
        await db.execute(
            select(Staff.id)
            .join(User, User.id == Staff.user_id)
            .where(User.institution_id == inst.id, User.username == "faculty.1")
        )
    ).scalar_one_or_none()
    cqi = CqiService(db, obe, institution_id=inst.id)
    today = today_for(inst)
    gaps = []
    for b in pick:
        gaps += await po.gaps(b.program_id, b.id, 0.0)
    targets = gaps[:8]
    while len(targets) < 8 and offerings:
        o = offerings[len(targets) % len(offerings)]
        targets.append(None)  # type: ignore[arg-type]
    for i, g in enumerate(targets[:8]):
        if g is not None:
            body = CqiActionIn(
                scope_type="program" if g.scope == "program" else "offering",
                scope_id=g.scope_id,
                outcome_id=g.outcome_id,
                gap=round(g.gap, 2),
                action_text=g.suggested_action,
                owner_staff_id=hod if i % 2 == 0 else fac,
                due_on=today + timedelta(days=30 - i * 7),
            )
        else:
            o = offerings[i % len(offerings)]
            body = CqiActionIn(
                scope_type="offering",
                scope_id=o.id,
                action_text="Add tutorial sessions on weak COs and re-check the question-to-CO map",
                owner_staff_id=fac or hod,
                due_on=today + timedelta(days=21 - i * 5),
            )
        try:
            a = await cqi.create(body)
        except APIError as exc:
            print(f"   attainment: CQI action skipped ({exc.message})")
            continue
        ctx.count("cqi_actions")
        if i % 4 >= 1:
            await cqi.change_status(a.id, CqiStatusChange(status="in_progress"))
        if i % 4 >= 2:
            await cqi.change_status(a.id, CqiStatusChange(status="done", evidence_url=f"demo/cqi/evidence-{i}.pdf"))
        if i % 4 == 3:
            await cqi.verify(a.id, CqiVerify(approve=True, comment="Evidence reviewed (demo)"))
    await db.flush()
