"""``analytics`` demo seeder (Prompts/35 §35.2) — ``seed_demo_institution.py --only analytics``.

Enables ``analytics.core`` / ``analytics.early_warning`` (and Phase 27 ``mentoring.early_warning``), then writes: KPI
targets (institution row; a stricter college override on university tenants), 3 institution dashboard layout overrides
(principal / HOD / accountant — reorder + one hidden widget each), up to 400 interventions stored as Phase 27
``mentoring_sessions`` (``mode='intervention'``, ``concerns.items=[type]``) on the active mentor assignments of flagged
students (spread over the term, some with follow-ups), digest schedules (weekly principal / registrar, daily HOD), then
refreshes all 13 read models (platform role — ``REFRESH … CONCURRENTLY``) and evaluates the KPI targets once (opens the
first breaches / history row). Idempotent: interventions are skipped when any exist; settings / layouts are upserts.
"""

import random
from datetime import date, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

INTERVENTIONS = 400


@seeder(
    "analytics",
    after=[
        "student_support",
        "hostel",
        "library",
        "placement",
        "research",
        "phd",
        "governance",
        "accreditation",
        "affiliation",
    ],
)
async def seed_analytics(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.db.session import bind_tenant, set_tenant
    from app.models.mentoring import MentorAssignment, MentoringSession, RiskFlag
    from app.models.platform import College, Institution, InstitutionSetting
    from app.services.analytics.chart_service import ensure_catalogue
    from app.services.analytics.kpi_service import KpiService
    from app.services.analytics.readmodel_service import refresh_views
    from app.services.feature_service import FeatureService

    ensure_catalogue()
    db = ctx.db
    rng = random.Random(35)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in ("analytics.core", "analytics.early_warning", "mentoring.early_warning"):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 35)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   analytics: {key} not enabled ({exc})")

    async def put_setting(category: str, key: str, value: object, college_id: object = None) -> None:
        row = (
            await db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == inst.id,
                    InstitutionSetting.category == category,
                    InstitutionSetting.key == key,
                    InstitutionSetting.college_id.is_(None)
                    if college_id is None
                    else InstitutionSetting.college_id == college_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                InstitutionSetting(
                    institution_id=inst.id,
                    college_id=college_id,
                    category=category,
                    key=key,
                    value=value,
                    value_type="json",
                )
            )
            ctx.count("institution_settings")
        else:
            row.value = value

    # ---- KPI targets / recipients / digest roles ------------------------------------------------------------------
    await put_setting(
        "analytics",
        "targets",
        {
            "attendance_pct": 75,
            "fee_collection_pct": 90,
            "result_pass_pct": 85,
            "placement_pct": 70,
            "grievance_sla_pct": 95,
        },
    )
    await put_setting(
        "analytics",
        "alert_recipients",
        {
            "default": ["institution_admin", "vice_chancellor", "registrar"],
            "attendance_pct": ["vice_chancellor", "hod"],
        },
    )
    colleges = (
        (await db.execute(select(College).where(College.institution_id == inst.id, College.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    if ctx.institution_type == "university" and len(colleges) > 1:
        await put_setting("analytics", "targets", {"attendance_pct": 80, "fee_collection_pct": 92}, colleges[1].id)

    # ---- institution layout overrides (principal / HOD / accountant) --------------------------------------------------
    layouts = {
        "vice_chancellor": (["risk_high", "attendance_avg_pct", "students_active"], "research.publications_trend"),
        "hod": (["attendance.pct_by_batch", "risk.high"], "research.publications_by_department"),
        "accountant": (["fees.collection_by_mode_daily", "fee_collected_today"], "fees.day_book_status"),
    }
    from app.core.dashboards import DASHBOARD_REGISTRY

    for role, (first, hidden) in layouts.items():
        keys = [w.key for w in DASHBOARD_REGISTRY.get(role, [])]
        order = [k for k in first if k in keys] + [k for k in keys if k not in first and k != hidden]
        widgets = [{"key": k, "position": i} for i, k in enumerate(order)] + [{"key": hidden, "hidden": True}]
        await put_setting("analytics_meta", f"layout:{role}", {"columns": 4, "widgets": widgets, "updated_by": "seed"})

    # ---- digests -------------------------------------------------------------------------------------------------------
    for did, cadence, roles, hour in (
        ("8a1f0c7e-35aa-4c35-9d35-000000000001", "weekly", ["vice_chancellor", "registrar"], 7),
        ("8a1f0c7e-35aa-4c35-9d35-000000000002", "daily", ["hod"], 7),
    ):
        await put_setting(
            "analytics_meta",
            f"digest:{did}",
            {
                "cadence": cadence,
                "roles": roles,
                "user_ids": [],
                "channels": ["in_app", "email"],
                "hour": hour,
                "created_by": "seed",
                "last_sent_at": None,
            },
        )
    await db.flush()

    # ---- interventions (Phase 27 mentoring_sessions) --------------------------------------------------------------------
    existing = (
        await db.execute(
            select(func.count())
            .select_from(MentoringSession)
            .where(MentoringSession.institution_id == inst.id, MentoringSession.mode == "intervention")
        )
    ).scalar_one()
    if not existing:
        flagged = (
            await db.execute(
                select(RiskFlag, MentorAssignment)
                .join(
                    MentorAssignment,
                    (MentorAssignment.student_program_enrollment_id == RiskFlag.student_program_enrollment_id)
                    & (MentorAssignment.status == "active"),
                )
                .where(RiskFlag.institution_id == inst.id, RiskFlag.level.in_(("high", "medium")))
                .order_by(RiskFlag.score.desc())
            )
        ).all()
        types = [
            "mentor_meeting",
            "guardian_call",
            "counselling",
            "fee_plan",
            "remedial_class",
            "hostel_warden",
            "other",
        ]
        today = date.today()
        n = 0
        pool = list(flagged)
        while pool and n < INTERVENTIONS:
            f, a = pool[n % len(pool)]
            t = rng.choice(types)
            held = today - timedelta(days=rng.randint(0, 75))
            db.add(
                MentoringSession(
                    institution_id=inst.id,
                    mentor_assignment_id=a.id,
                    held_on=held,
                    mode="intervention",
                    notes=f"Demo intervention ({t.replace('_', ' ')})",
                    concerns={
                        "items": [t],
                        "intervention_type": t,
                        "logged_by": "seed",
                        "risk_level": f.level,
                        "risk_flag_id": str(f.id),
                    },
                    action_items=[],
                    follow_up_on=held + timedelta(days=14) if rng.random() < 0.4 else None,
                    is_confidential=False,
                )
            )
            n += 1
        for _ in range(n):
            ctx.count("mentoring_sessions(intervention)")
        if not pool:
            print(
                "   analytics: no flagged students with mentors — run --only student_support first; interventions skipped"
            )
    await db.commit()

    # ---- read models + KPI evaluation ----------------------------------------------------------------------------------
    try:
        out = await refresh_views(None)
        print("   analytics: refreshed " + ", ".join(f"{o['view']}={o.get('rows', o.get('skipped'))}" for o in out))
    except Exception as exc:  # noqa: BLE001 - views missing (alembic < 0035) → report and continue
        print(f"   analytics: read-model refresh failed ({str(exc)[:200]})")
        return
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    res = await KpiService(db, None, institution_id=inst.id).evaluate()
    print(f"   analytics: KPI evaluation opened={res['opened']} closed={res['closed']}")
    await db.commit()
