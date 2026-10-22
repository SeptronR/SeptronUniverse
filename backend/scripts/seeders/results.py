"""``results`` demo seeder (Prompts/15 §15.2) — ``seed_demo_institution.py --type university --only results``.

On top of ``exams`` (regular session with papers, confirmed registrations, eligibility):

* the session moves to ``valuation``; hall attendance is recorded for the theory papers that have candidates (every
  17th candidate absent), so they can be bundled;
* every such paper except the last one (left uncoded for ``15_results.ps1``) is bundled (30 per bundle), coded,
  dispatched / received; round 1 is assigned to a teacher who does not teach the course and valued (marks around
  62 % of the maximum); with ``exams.double_valuation`` on, the session runs double valuation and round 2 goes to a
  second evaluator with ~6 % of the scripts outside the tolerance (third valuation assigned and valued);
* reconciliation, one moderation action (``add_flat 2``, proposed by the exam cell, approved / applied by the COE) on
  the first paper, decode by the decoder;
* a provisional run (computed), then a final run verified (anomalies acknowledged), approved and published with three
  enrolments withheld; grade cards generated; a correction run (+5 ESE for one student) published as version 2;
* legacy results imported for the previous batch, terms 1–4 (CSV in storage; two rows with invalid grades).

Idempotent: everything runs only while the session has no published result run.
"""

import random
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


@seeder("results", after=["exams"])
async def seed_results(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401  (``is_enabled`` needs the full registry outside the API process)
    from app.core.errors import APIError
    from app.core.features import is_enabled
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import AcademicTerm, Batch
    from app.models.exams import ExamAttendance, ExamPaper, ExamRegistration, ExamRegistrationItem, ExamSession
    from app.models.hr import Staff
    from app.models.platform import Institution, User
    from app.models.results import ResultProcessingRun, StudentCourseResult
    from app.models.valuation import AnswerScriptBundle
    from app.schemas.results import PublishRequest, RunAction, RunCreateRequest, RunScope
    from app.schemas.valuation import (
        AssignValuationRequest,
        BundleCreateRequest,
        CustodyLogCreate,
        ModerationProposal,
        ThirdValuationAssign,
        ValuationSubmit,
    )
    from app.services.auth_service import load_principal
    from app.services.results.coding_service import CodingService
    from app.services.results.grade_card_service import GradeCardService
    from app.services.results.result_service import ResultRunService
    from app.services.results.valuation_service import ValuationService

    db = ctx.db
    rng = random.Random(15)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)

    async def principal(name: str) -> object | None:
        u = (
            await db.execute(select(User).where(User.institution_id == inst.id, User.username == name))
        ).scalar_one_or_none()
        return await load_principal(db, u.id) if u else None

    admin = await principal("inst.admin")
    cell = await principal("exam.cell") or admin
    coe = await principal("coe") or admin
    decoder = await principal("decoder") or coe
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
    s = (
        await db.execute(
            select(ExamSession).where(
                ExamSession.institution_id == inst.id,
                ExamSession.name == f"{term.name} — End-semester (regular)",
            )
        )
    ).scalar_one_or_none()
    if s is None:
        print("   results: no regular exam session — run --only exams first")
        return
    if (
        await db.execute(
            select(func.count())
            .select_from(ResultProcessingRun)
            .where(ResultProcessingRun.exam_session_id == s.id, ResultProcessingRun.status == "published")
        )
    ).scalar_one():
        return
    double = await is_enabled(inst.id, "exams.double_valuation")
    s.status = "valuation"
    s.valuation_mode = "double" if double else "single"
    await db.flush()

    # ---- hall attendance for theory papers with candidates ---------------------------------------------------------
    papers = list(
        (
            await db.execute(
                select(ExamPaper)
                .where(ExamPaper.exam_session_id == s.id, ExamPaper.paper_type == "theory")
                .order_by(ExamPaper.paper_code)
            )
        ).scalars()
    )
    seeded: list[ExamPaper] = []
    for pp in papers:
        items = list(
            (
                await db.execute(
                    select(ExamRegistrationItem)
                    .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                    .where(
                        ExamRegistrationItem.exam_paper_id == pp.id,
                        ExamRegistration.status == "confirmed",
                        ExamRegistrationItem.status != "cancelled",
                    )
                )
            ).scalars()
        )
        if not items:
            continue
        have = set(
            (
                await db.execute(
                    select(ExamAttendance.exam_registration_item_id).where(
                        ExamAttendance.exam_registration_item_id.in_([i.id for i in items])
                    )
                )
            ).scalars()
        )
        for k, it in enumerate(items):
            if it.id in have:
                continue
            absent = k % 17 == 5 or it.eligibility == "detained"
            db.add(
                ExamAttendance(
                    institution_id=inst.id,
                    exam_registration_item_id=it.id,
                    status="absent" if absent else "present",
                    answer_booklet_number=None if absent else f"AB{(pp.paper_code or '')[:10]}{k + 1:04d}",
                )
            )
            it.status = "absent" if absent else "appeared"
            ctx.count("hall_attendance")
        pp.status = "conducted"
        seeded.append(pp)
        if len(seeded) >= 7:
            break
    await db.flush()
    if len(seeded) < 2:
        print("   results: fewer than two papers with candidates — nothing to value")
        return

    # ---- coding, custody, valuation ----------------------------------------------------------------------------------
    coding = CodingService(db, cell, institution_id=inst.id)
    vals_cell = ValuationService(db, cell, institution_id=inst.id)
    staff = list(
        (
            await db.execute(
                select(Staff).where(
                    Staff.institution_id == inst.id,
                    Staff.deleted_at.is_(None),
                    Staff.staff_category == "teaching",
                    Staff.user_id.is_not(None),
                )
            )
        ).scalars()
    )
    if not staff:
        print("   results: no teaching staff with accounts — nothing to value")
        return
    for pi, pp in enumerate(seeded[:-1]):  # the last paper stays uncoded / unvalued for the verify script
        if (
            await db.execute(select(func.count()).select_from(AnswerScriptBundle).where(AnswerScriptBundle.exam_paper_id == pp.id))
        ).scalar_one():
            continue
        bundles = await coding.create_bundles(pp.id, BundleCreateRequest(size=30))
        ctx.count("bundles", len(bundles))
        for b in bundles:
            await coding.code(b.id)
            await coding.custody(b.id, CustodyLogCreate(action="dispatched", location="Valuation centre"))
            await coding.custody(b.id, CustodyLogCreate(action="received", location="Valuation centre"))
        rounds = (1, 2) if double else (1,)
        used: set[object] = set()
        for rnd in rounds:
            evaluator = None
            for st in rng.sample(staff, len(staff)):
                if st.id in used:
                    continue
                try:
                    await vals_cell.assign(
                        pp.id,
                        AssignValuationRequest(
                            bundle_ids=[b.id for b in bundles], evaluator_staff_id=st.id, round=rnd, remuneration_paise=None
                        ),
                    )
                    evaluator = st
                    used.add(st.id)
                    break
                except APIError:
                    continue
            if evaluator is None:
                break
            ctx.count("valuation_assignments", len(bundles))
            ev = ValuationService(db, await load_principal(db, evaluator.user_id), institution_id=inst.id)  # type: ignore[arg-type]
            for b in bundles:
                for k, sc in enumerate(await ev.bundle_scripts(b.id)):
                    base = Decimal(str(max(0.0, min(float(pp.max_marks), rng.gauss(0.62, 0.16) * float(pp.max_marks)))))
                    if rnd == 2:
                        shift = 0.22 if k % 16 == 3 else rng.uniform(-0.05, 0.05)  # ~6 % beyond the 15 % tolerance
                        base = Decimal(str(max(0.0, min(float(pp.max_marks), float(base) + shift * float(pp.max_marks)))))
                    await ev.submit_valuation(sc.id, rnd, ValuationSubmit(marks=base.quantize(Decimal("0.5"))))
                    ctx.count("script_valuations")
                await ev.submit_bundle(b.id)
        summary = await vals_cell.reconcile(pp.id)
        if summary.needs_third:
            third = next((st for st in staff if st.id not in used), None)
            if third is not None:
                try:
                    await vals_cell.third_assign(pp.id, ThirdValuationAssign(evaluator_staff_id=third.id))
                    ev3 = ValuationService(db, await load_principal(db, third.user_id), institution_id=inst.id)  # type: ignore[arg-type]
                    for b in await ev3.my_bundles():
                        if b.valuation_round != 3:
                            continue
                        for sc in await ev3.bundle_scripts(b.bundle_id):
                            await ev3.submit_valuation(sc.id, 3, ValuationSubmit(marks=Decimal(str(round(float(pp.max_marks) * 0.6)))))
                        await ev3.submit_bundle(b.bundle_id)
                    await vals_cell.reconcile(pp.id)
                    ctx.count("third_valuations")
                except APIError as exc:
                    print(f"   third valuation skipped: {exc.message}")
        if pi == 0:
            m = await vals_cell.propose(
                pp.id,
                ModerationProposal(action_type="add_flat", rule={"marks": 2}, justification="Paper found harder than the blueprint"),
            )
            vcoe = ValuationService(db, coe, institution_id=inst.id)
            await vcoe.approve(m.id)
            await vcoe.apply(m.id)
            ctx.count("moderation_actions")
        try:
            await ValuationService(db, decoder, institution_id=inst.id).decode(pp.id)
            ctx.count("papers_decoded")
        except APIError as exc:
            print(f"   decode skipped for {pp.paper_code}: {exc.message}")

    # ---- result runs -------------------------------------------------------------------------------------------------
    runs = ResultRunService(db, cell, institution_id=inst.id)
    prov = await runs.create_run(RunCreateRequest(exam_session_id=s.id, run_type="provisional"))
    await runs.compute(prov.id)
    ctx.count("result_runs")
    final = await runs.create_run(RunCreateRequest(exam_session_id=s.id, run_type="final"))
    out = await runs.compute(final.id)
    ctx.count("result_runs")
    await runs.verify(final.id, RunAction(acknowledge_anomalies=True, comment="Anomalies reviewed (demo)"))
    coe_runs = ResultRunService(db, coe, institution_id=inst.id)
    await coe_runs.approve(final.id, RunAction(comment="Approved (demo)"))
    enr_ids = list(
        (
            await db.execute(
                select(StudentCourseResult.student_program_enrollment_id)
                .where(StudentCourseResult.run_id == final.id)
                .distinct()
                .order_by(StudentCourseResult.student_program_enrollment_id)
            )
        ).scalars()
    )
    await coe_runs.publish(final.id, PublishRequest(audience="student", notify=False, withhold_ids=enr_ids[-3:]))
    ctx.count("published_rows", int((out.stats or {}).get("rows", 0)))
    cards = await GradeCardService(db, coe, institution_id=inst.id).generate_for_run(final.id)
    ctx.count("grade_cards", cards["generated"])

    # correction → version 2 for one student / course
    row = (
        await db.execute(
            select(StudentCourseResult)
            .where(
                StudentCourseResult.run_id == final.id,
                StudentCourseResult.result_status.in_(("pass", "fail")),
                StudentCourseResult.student_program_enrollment_id.notin_(enr_ids[-3:]),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is not None:
        corr = await runs.create_run(
            RunCreateRequest(
                exam_session_id=s.id,
                run_type="correction",
                scope=RunScope(
                    enrollment_ids=[row.student_program_enrollment_id],
                    course_ids=[row.course_id],
                    marks_delta={f"{row.student_program_enrollment_id}:{row.course_id}": Decimal(5)},
                ),
            )
        )
        await runs.compute(corr.id)
        await runs.verify(corr.id, RunAction(acknowledge_anomalies=True))
        await coe_runs.approve(corr.id, RunAction())
        await coe_runs.publish(corr.id, PublishRequest(notify=False))
        await GradeCardService(db, coe, institution_id=inst.id).generate_for_run(corr.id)
        ctx.count("result_versions")

    # ---- legacy import for the previous batch ---------------------------------------------------------------------------
    await _legacy(ctx, db, inst, admin)
    _ = (Batch,)


async def _legacy(ctx: SeedContext, db: object, inst: object, admin: object) -> None:
    from sqlalchemy import select as sel

    from app.core.errors import APIError
    from app.core.files import build_key, storage
    from app.models.academic import Batch, ProgramRegulation
    from app.models.curriculum import Course
    from app.models.students import Student, StudentProgramEnrollment
    from app.schemas.results import LegacyImportCreate
    from app.services.results.legacy_import_service import LegacyImportService

    batches = list(
        (await db.execute(sel(Batch).where(Batch.institution_id == inst.id).order_by(Batch.admission_year))).scalars()  # type: ignore[attr-defined]
    )
    if len(batches) < 2:
        return
    batch = batches[0] if batches[0].admission_year < batches[-1].admission_year else batches[-1]
    studs = (
        await db.execute(  # type: ignore[attr-defined]
            sel(Student.registration_number)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
            .where(StudentProgramEnrollment.batch_id == batch.id)
            .limit(25)
        )
    ).scalars().all()
    if not studs:
        return
    reg = (await db.execute(sel(ProgramRegulation.regulation_id).where(ProgramRegulation.id == batch.program_regulation_id))).scalar_one()  # type: ignore[attr-defined]
    codes = (await db.execute(sel(Course.code, Course.credits).where(Course.regulation_id == reg).limit(5))).all()  # type: ignore[attr-defined]
    grades = ["O", "A+", "A", "B+", "B", "C", "P"]
    svc = LegacyImportService(db, admin, institution_id=inst.id)  # type: ignore[arg-type,attr-defined]
    for term_number in range(1, 5):
        lines = ["reg_no,course_code,course_title,credits,cia,ese,total,grade,gp,attempt"]
        for n, rno in enumerate(studs):
            for j, (code, credits) in enumerate(codes or [("LEG101", 3)]):
                c = f"{code}" if term_number == 1 else f"L{term_number}{j:02d}{code}"[:30]
                g = grades[(n + j + term_number) % len(grades)]
                if term_number == 1 and n < 2 and j == 0:
                    g = "Z"  # two invalid grades for the validation report
                lines.append(f"{rno},{c},Legacy course {c},{credits},30,40,70,{g},,1")
        key = build_key(inst.id, "results/legacy", f"batch-{batch.code}-t{term_number}.csv")  # type: ignore[attr-defined]
        await storage.put(key, "\n".join(lines).encode(), "text/csv")
        try:
            imp = await svc.create(LegacyImportCreate(batch_id=batch.id, term_number=term_number, file_url=key), None)
            await svc.validate(imp.id)
            await svc.apply(imp.id)
            ctx.count("legacy_imports")
        except APIError as exc:
            print(f"   legacy import t{term_number} skipped: {exc.message}")
