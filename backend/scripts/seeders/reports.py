"""``reports`` demo seeder (Prompts/36 §36.2) — ``seed_demo_institution.py --only reports``.

Enables ``reports.core`` / ``reports.scheduled`` / ``reports.statutory``, then writes (through the Phase 36 services, so
every row passes the same validation / visibility as the API):

* saved builder reports — 3 per key module (students, fees, HR, attendance, placement), shared with the module roles;
* 25 favourites across roles (``users.preferences['reports']``);
* 6 schedules (daily fee collection → accountant / principal, weekly attendance shortfall → HODs, monthly HR headcount
  → HR, termly results summary → registrar, weekly placement funnel, monthly grievance SLA → IQAC);
* 40 completed report runs with files (``background_jobs`` ``report.run`` rows rendered by ``ReportService.execute``
  as the role holder — each file contains only that caller's rows);
* one signed-off AISHE and one signed-off NIRF statutory set for the previous academic year (files registered in
  ``issued_documents``, linked on the Phase 32 ``compliance_submissions`` row).

Idempotent: schedules / saved reports are skipped when present, runs top up to 40, statutory sets are kept once
signed off.
"""

import random
import uuid
from datetime import UTC, date, datetime
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select, text

RUNS = 40


@seeder("reports", after=["analytics", "accreditation", "placement", "student_support", "governance"])
async def seed_reports(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.db.session import bind_tenant, set_tenant
    from app.models.platform import BackgroundJob, Institution, User
    from app.schemas.reports import BuilderDefinition, SavedReportIn, ScheduleIn, StatutoryReviewAction
    from app.services.auth_service import load_principal
    from app.services.feature_service import FeatureService
    from app.services.reports.builder_service import BuilderService
    from app.services.reports.common import ensure_registry
    from app.services.reports.report_service import ReportService
    from app.services.reports.schedule_service import ScheduleService
    from app.services.reports.statutory_sections import parse_period
    from app.services.reports.statutory_service import StatutoryService

    ensure_registry()
    db = ctx.db
    rng = random.Random(36)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    inst_id = inst.id  # the row expires on rollback (statutory step); keep the id
    bind_tenant(db, inst_id)
    await set_tenant(db, inst_id)

    features = FeatureService(db)
    effective = await features.effective(inst_id)
    for key in ("reports.core", "reports.scheduled", "reports.statutory"):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst_id, key, enabled=True, reason="demo seed (Phase 36)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   reports: {key} not enabled ({exc})")
    await db.commit()

    async def holders(slug: str) -> list[uuid.UUID]:
        rows = await db.execute(
            text(
                "SELECT DISTINCT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id JOIN users u ON u.id = ur.user_id "
                "WHERE r.slug = :s AND (ur.institution_id = :i OR r.institution_id = :i) AND u.deleted_at IS NULL "
                "AND u.is_active ORDER BY ur.user_id"
            ),
            {"s": slug, "i": inst_id},
        )
        return [r[0] for r in rows.all()]

    async def principal_of(slug: str, index: int = 0) -> Any:
        users = await holders(slug)
        if not users:
            return None
        p = await load_principal(db, users[min(index, len(users) - 1)])
        bind_tenant(db, inst_id)
        await set_tenant(db, inst_id)
        return p

    admin = await principal_of("institution_admin")
    if admin is None:
        print("   reports: no institution_admin user — run the base seed first; skipped")
        return

    # ---- saved builder reports (3 per key module) -----------------------------------------------------------------------
    saved_existing = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM institution_settings WHERE institution_id = :i AND category = 'reports_meta' AND key LIKE 'saved:%'"
            ),
            {"i": inst_id},
        )
    ).scalar_one()
    if not saved_existing:
        builder = BuilderService(db, admin, institution_id=inst_id)
        defs: list[tuple[str, dict[str, Any], list[str]]] = [
            (
                "Students by category and gender",
                {
                    "model_key": "students",
                    "group_by": ["category", "gender"],
                    "aggregates": [{"field": "*", "fn": "count"}],
                },
                ["registrar", "hod"],
            ),
            (
                "Students per programme",
                {
                    "model_key": "students",
                    "joins": ["program"],
                    "group_by": ["program.code"],
                    "aggregates": [{"field": "*", "fn": "count"}, {"field": "cgpa", "fn": "avg"}],
                },
                ["registrar"],
            ),
            (
                "Active students — contact sheet",
                {
                    "model_key": "students",
                    "columns": ["registration_number", "name", "phone", "email", "status"],
                    "filters": [{"field": "status", "op": "eq", "value": "active"}],
                },
                [],
            ),
            (
                "Outstanding invoices",
                {
                    "model_key": "fee_invoices",
                    "columns": ["invoice_number", "registration_number", "balance_paise", "due_date", "status"],
                    "filters": [{"field": "balance_paise", "op": "gt", "value": 0}],
                },
                ["accountant"],
            ),
            (
                "Collection by mode",
                {
                    "model_key": "fee_payments",
                    "group_by": ["payment_mode"],
                    "aggregates": [{"field": "amount_paise", "fn": "sum"}, {"field": "*", "fn": "count"}],
                },
                ["accountant"],
            ),
            (
                "Dues by category",
                {
                    "model_key": "fee_invoices",
                    "group_by": ["category"],
                    "aggregates": [{"field": "balance_paise", "fn": "sum"}],
                },
                ["accountant"],
            ),
            (
                "Staff by department",
                {
                    "model_key": "staff",
                    "joins": ["department"],
                    "group_by": ["department.code"],
                    "aggregates": [{"field": "*", "fn": "count"}],
                },
                ["hr_officer"],
            ),
            (
                "Leave days by status",
                {
                    "model_key": "staff",
                    "joins": ["department", "leaves"],
                    "group_by": ["department.code", "leaves.status"],
                    "aggregates": [{"field": "leaves.days_count", "fn": "sum"}],
                },
                ["hr_officer"],
            ),
            (
                "Staff contact sheet",
                {"model_key": "staff", "columns": ["employee_id", "name", "designation", "phone", "email"]},
                [],
            ),
            (
                "Attendance below 75%",
                {
                    "model_key": "attendance_summaries",
                    "columns": ["registration_number", "name", "course", "pct"],
                    "filters": [{"field": "pct", "op": "lt", "value": 75}],
                },
                ["hod"],
            ),
            (
                "Average attendance per course",
                {
                    "model_key": "attendance_summaries",
                    "group_by": ["course"],
                    "aggregates": [{"field": "pct", "fn": "avg"}],
                },
                ["hod"],
            ),
            (
                "Attendance eligibility mix",
                {
                    "model_key": "attendance_summaries",
                    "group_by": ["eligibility"],
                    "aggregates": [{"field": "*", "fn": "count"}],
                },
                [],
            ),
            (
                "Offers by company",
                {
                    "model_key": "placements",
                    "group_by": ["company"],
                    "aggregates": [{"field": "*", "fn": "count"}, {"field": "ctc_paise", "fn": "max"}],
                },
                ["placement_officer"],
            ),
            (
                "Offers by sector",
                {
                    "model_key": "placements",
                    "group_by": ["sector"],
                    "aggregates": [{"field": "ctc_paise", "fn": "avg"}],
                },
                ["placement_officer"],
            ),
            (
                "Placed students",
                {
                    "model_key": "placements",
                    "columns": ["registration_number", "name", "company", "ctc_paise", "status"],
                },
                [],
            ),
        ]
        for name, definition, roles in defs:
            try:
                async with db.begin_nested():
                    await builder.create_saved(
                        SavedReportIn(
                            name=name, definition=BuilderDefinition.model_validate(definition), share_with_roles=roles
                        )
                    )
                ctx.count("saved_reports")
            except (APIError, ValueError) as exc:
                print(f"   reports: saved report {name!r} skipped ({str(exc)[:120]})")
        await db.commit()

    # ---- favourites (25 across roles) -------------------------------------------------------------------------------------
    favs = {
        "accountant": [
            "fees.collection_register",
            "fees.daily_collection",
            "fees.dues_position",
            "scholarships.applications",
            "fees.defaulters",
        ],
        "registrar": [
            "admissions.register",
            "results.register",
            "degrees.register",
            "students.list_export",
            "students.category_gender",
        ],
        "hod": [
            "attendance.register",
            "attendance.shortfall_list",
            "results.summary",
            "assessment.marks_sheet",
            "hr.leave_register",
        ],
        "hr_officer": ["hr.staff_list", "hr.headcount", "hr.leave_register", "payroll.register", "hr.staff_list"],
        "iqac_coordinator": [
            "accreditation.metric_values",
            "grievance.sla_summary",
            "research.publications_list",
            "events.list",
            "placement.funnel",
        ],
    }
    for slug, keys in favs.items():
        users = await holders(slug)
        if not users:
            continue
        user = (await db.execute(select(User).where(User.id == users[0]))).scalar_one()
        prefs = dict(user.preferences or {})
        rp = dict(prefs.get("reports") or {})
        current = list(rp.get("favourites") or [])
        for k in keys:
            if k not in current:
                current.append(k)
                ctx.count("report_favourites")
        rp["favourites"] = current
        prefs["reports"] = rp
        user.preferences = prefs
    await db.commit()

    # ---- schedules (6) -------------------------------------------------------------------------------------------------------
    sched_existing = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM institution_settings WHERE institution_id = :i AND category = 'reports_meta' AND key LIKE 'schedule:%'"
            ),
            {"i": inst_id},
        )
    ).scalar_one()
    if not sched_existing:
        ss = ScheduleService(db, admin, institution_id=inst_id)
        plans: list[dict[str, Any]] = [
            {
                "name": "Daily fee collection",
                "key": "fees.daily_collection",
                "cadence": "daily",
                "at": "07:30",
                "recipients": {"roles": ["accountant", "principal"]},
                "format": "xlsx",
            },
            {
                "name": "Weekly attendance shortfall (HODs)",
                "key": "attendance.shortfall_list",
                "cadence": "weekly",
                "weekday": 0,
                "at": "07:00",
                "recipients": {"roles": ["hod"]},
                "format": "xlsx",
            },
            {
                "name": "Monthly HR headcount",
                "key": "hr.headcount",
                "cadence": "monthly",
                "day_of_month": 1,
                "at": "08:00",
                "recipients": {"roles": ["hr_officer"]},
                "format": "pdf",
            },
            {
                "name": "Termly results summary",
                "key": "results.summary",
                "cadence": "termly",
                "at": "09:00",
                "recipients": {"roles": ["registrar"]},
                "format": "xlsx",
                "params": {},
            },
            {
                "name": "Weekly placement funnel",
                "key": "placement.funnel",
                "cadence": "weekly",
                "weekday": 4,
                "at": "17:00",
                "recipients": {"roles": ["placement_officer"]},
                "format": "xlsx",
            },
            {
                "name": "Monthly grievance SLA (IQAC)",
                "key": "grievance.sla_summary",
                "cadence": "monthly",
                "day_of_month": 5,
                "at": "10:00",
                "recipients": {"roles": ["iqac_coordinator"]},
                "format": "pdf",
            },
        ]
        for plan in plans:
            try:
                async with db.begin_nested():
                    await ss.create(ScheduleIn.model_validate(plan))
                ctx.count("report_schedules")
            except (APIError, ValueError) as exc:
                print(f"   reports: schedule {plan['name']!r} skipped ({str(exc)[:120]})")
        await db.commit()

    # ---- 40 completed runs with files ----------------------------------------------------------------------------------------
    have = (
        await db.execute(
            select(func.count())
            .select_from(BackgroundJob)
            .where(
                BackgroundJob.institution_id == inst_id,
                BackgroundJob.job_type == "report.run",
                BackgroundJob.status == "succeeded",
            )
        )
    ).scalar_one()
    plan_runs: list[tuple[str, str, str]] = [
        ("accountant", "fees.collection_register", "xlsx"),
        ("accountant", "fees.daily_collection", "pdf"),
        ("accountant", "fees.dues_position", "csv"),
        ("accountant", "scholarships.applications", "xlsx"),
        ("registrar", "admissions.register", "pdf"),
        ("registrar", "results.register", "xlsx"),
        ("registrar", "degrees.register", "pdf"),
        ("registrar", "students.list_export", "csv"),
        ("registrar", "students.category_gender", "json"),
        ("hod", "attendance.shortfall_list", "xlsx"),
        ("hod", "results.summary", "pdf"),
        ("hod", "attendance.offering_summary", "csv"),
        ("hr_officer", "hr.staff_list", "xlsx"),
        ("hr_officer", "hr.headcount", "pdf"),
        ("hr_officer", "hr.leave_register", "pdf"),
        ("iqac_coordinator", "grievance.sla_summary", "xlsx"),
        ("iqac_coordinator", "events.list", "csv"),
        ("controller_of_examinations", "exams.progress", "xlsx"),
        ("placement_officer", "placement.funnel", "xlsx"),
        ("placement_officer", "placement.offers_list", "csv"),
        ("librarian", "library.issue_register", "pdf"),
        ("institution_admin", "audit.activity", "xlsx"),
    ]
    made = 0
    i = 0
    while have + made < RUNS and i < RUNS * 2:
        slug, key, fmt = plan_runs[i % len(plan_runs)]
        i += 1
        p = await principal_of(slug, rng.randint(0, 2))
        if p is None:
            continue
        job = BackgroundJob(
            institution_id=inst_id,
            job_type="report.run",
            params={"key": key, "params": {}, "format": fmt, "seed": True},
            status="running",
            requested_by=p.id,
            started_at=datetime.now(UTC),
        )
        db.add(job)
        await db.flush()
        try:
            async with db.begin_nested():
                res = await ReportService(db, p, institution_id=inst_id).execute(job.id, key, {}, fmt)
            job.status, job.result, job.result_url = "succeeded", res, res.get("result_url")
            job.progress_pct, job.finished_at = 100, datetime.now(UTC)
            made += 1
            ctx.count("report_runs")
        except Exception as exc:  # noqa: BLE001 - a module without data / feature off: record the failure like a real run
            job.status, job.error, job.finished_at = "failed", str(exc)[:500], datetime.now(UTC)
        await db.commit()
        bind_tenant(db, inst_id)
        await set_tenant(db, inst_id)

    # ---- signed-off AISHE + NIRF for the previous academic year --------------------------------------------------------------
    today = date.today()
    start = today.year - 1 if today.month >= 7 else today.year - 2
    label = parse_period(str(start), "academic_year").label
    for code, gen_role, discipline in (("aishe", "registrar", None), ("nirf", "iqac_coordinator", "engineering")):
        gp = await principal_of(gen_role) or admin
        svc = StatutoryService(db, gp, institution_id=inst_id)
        st = await svc.state(code, label, discipline)
        if st.get("status") == "signed_off":
            continue
        try:
            async with db.begin_nested():
                if not st:
                    await svc.generate_now(None, code, label, discipline)
                    ctx.count("statutory_generations")
                await svc.review(code, label, StatutoryReviewAction(action="request_review"), discipline)
                for role in await svc.signoff_roles(code):
                    signer = None
                    for slug in {"principal": ("vice_chancellor", "institution_admin", "college_admin")}.get(
                        role, (role,)
                    ):
                        signer = await principal_of(slug)
                        if signer is not None:
                            break
                    if signer is None:
                        continue
                    await StatutoryService(db, signer, institution_id=inst_id).review(
                        code,
                        label,
                        StatutoryReviewAction(action="sign_off", role=role, remarks="demo sign-off"),
                        discipline,
                    )
                    ctx.count("statutory_signoffs")
            await db.commit()
        except (APIError, ValueError) as exc:
            await db.rollback()
            print(f"   reports: statutory {code} {label} not completed ({str(exc)[:160]})")
        bind_tenant(db, inst_id)
        await set_tenant(db, inst_id)
    print(f"   reports: runs +{made} (have {have + made}), statutory period {label}")
