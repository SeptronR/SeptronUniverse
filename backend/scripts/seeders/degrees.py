"""``degrees`` demo seeder (Prompts/18 §18.2) — ``seed_demo_institution.py --only degrees``.

On top of ``attainment``: enables the credential / ABC features (when their dependencies are available), runs the
eligibility engine for the oldest batch, overrides most ineligible checks to eligible (demo council equivalence —
keeps ~15 ineligible with real reasons), marks 2 enrolments as NEP diploma exits, opens a convocation with
registrations (about a fifth in absentia, fees settled), recommends → approves → issues awards, issues 10 provisional
certificates first, pushes credentials (mock DigiLocker) and ABC rows, and revokes / reissues one award.
Idempotent: skipped when a convocation exists.
"""

from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


@seeder("degrees", after=["attainment"])
async def seed_degrees(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import Batch
    from app.models.degrees import Convocation, ConvocationRegistration, DegreeAwarded
    from app.models.platform import Institution, User
    from app.models.students import StudentProgramEnrollment
    from app.schemas.degrees import (
        AbcPushRequest,
        ApproveRequest,
        AwardBatchRequest,
        ConvocationIn,
        ConvocationRegister,
        ConvocationStatusChange,
        CredentialPushRequest,
        EligibilityOverride,
        EligibilityRunRequest,
        IssueRequest,
        ReissueRequest,
        RevokeRequest,
    )
    from app.services.auth_service import load_principal
    from app.services.degrees.award_service import AwardService
    from app.services.degrees.convocation_service import ConvocationService
    from app.services.degrees.credential_service import CredentialService
    from app.services.degrees.eligibility_service import EligibilityService
    from app.services.feature_service import FeatureService

    db = ctx.db
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(Convocation).where(Convocation.institution_id == inst.id))
    ).scalar_one():
        return

    async def principal(name: str) -> object | None:
        u = (
            await db.execute(select(User).where(User.institution_id == inst.id, User.username == name))
        ).scalar_one_or_none()
        return await load_principal(db, u.id) if u else None

    admin = await principal("inst.admin")
    registrar = await principal("registrar") or admin

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in ("degrees.digilocker_nad", "degrees.abc_push", "degrees.esign"):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 18)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   degrees: {key} not enabled ({exc})")

    batch = (
        await db.execute(select(Batch).where(Batch.institution_id == inst.id).order_by(Batch.admission_year).limit(1))
    ).scalar_one_or_none()
    if batch is None:
        print("   degrees: no batch — run the academics / students seeders first")
        return
    enrolments = list(
        (
            await db.execute(
                select(StudentProgramEnrollment)
                .where(StudentProgramEnrollment.batch_id == batch.id, StudentProgramEnrollment.status.in_(("active", "completed")))
                .order_by(StudentProgramEnrollment.created_at)
            )
        )
        .scalars()
        .all()
    )
    # two NEP diploma exits
    for e in enrolments[-2:]:
        e.status, e.exit_award, e.exit_date = "exited_early", "diploma", today_for(inst)
        e.credits_earned = Decimal("85")
    await db.flush()

    elig = EligibilityService(db, registrar, institution_id=inst.id)
    summary = await elig.run(EligibilityRunRequest(batch_id=batch.id, include_exits=True))
    ctx.count("eligibility_checks", summary.checked)
    ctx.count("exit_awards", summary.exit_awards)
    checks = await elig.list_checks(batch.id, None, False, summary.run_id)
    keep = min(15, max(len(checks) // 4, 2))
    for c in checks[: max(len(checks) - keep, 0)]:
        await elig.override(
            c.id, EligibilityOverride(decision="eligible", reason="Demo: council-approved credit equivalence")
        )
        ctx.count("eligibility_overrides")

    conv_svc = ConvocationService(db, registrar, institution_id=inst.id)
    today = today_for(inst)
    from datetime import timedelta

    conv = await conv_svc.create(
        ConvocationIn(
            name=f"{today.year} Annual Convocation",
            held_on=today + timedelta(days=30),
            venue="Main auditorium",
            registration_deadline=today + timedelta(days=14),
            fee_paise=150000,
        )
    )
    await conv_svc.change_status(conv.id, ConvocationStatusChange(status="registration_open"))
    eligible = [c for c in await elig.list_checks(batch.id, None, True) if c.enrollment.status in ("active", "completed")]
    for i, c in enumerate(eligible[:150]):
        try:
            reg = await conv_svc.register(
                conv.id,
                ConvocationRegister(
                    enrollment_id=c.enrollment.id,
                    mode="absentia" if i % 5 == 4 else "in_person",
                    gown_size=("S", "M", "L", "XL")[i % 4],
                    guests=i % 3,
                ),
            )
            await conv_svc.on_paid(reg.id)
            ctx.count("convocation_registrations")
        except APIError as exc:
            print(f"   degrees: registration skipped ({exc.message})")

    awards = AwardService(db, registrar, institution_id=inst.id)
    # provisional certificates before the degrees are issued
    for c in eligible[:10]:
        try:
            await awards.provisional(c.enrollment.id)
            ctx.count("provisional_certificates")
        except APIError:
            pass
    preview = await awards.award_batch(AwardBatchRequest(convocation_id=conv.id, award_type="degree"))
    ctx.count("awards_recommended", preview.created)
    rows = (
        (
            await db.execute(
                select(DegreeAwarded).where(
                    DegreeAwarded.institution_id == inst.id, DegreeAwarded.status == "recommended"
                )
            )
        )
        .scalars()
        .all()
    )
    for a in rows:
        await awards.approve(a.id, ApproveRequest(comment="Academic Council (demo)"))
        if a.award_type in ("degree", "honours"):
            await awards.issue(a.id, IssueRequest(esign=True))
            ctx.count("awards_issued")
    issued = (
        (
            await db.execute(
                select(DegreeAwarded)
                .where(DegreeAwarded.institution_id == inst.id, DegreeAwarded.status == "issued")
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if len(issued) >= 2:
        await awards.revoke(issued[0].id, RevokeRequest(reason="Demo: issued in error"))
        await awards.reissue(issued[1].id, ReissueRequest(reason="Demo: name spelling corrected"))
        ctx.count("awards_revoked_or_reissued", 2)

    creds = CredentialService(db, registrar, institution_id=inst.id)
    try:
        out = await creds.push(CredentialPushRequest(entity_type="degree", batch_id=batch.id, channel="digilocker"))
        ctx.count("credentials_pushed", out.acknowledged + out.pushed)
    except APIError as exc:
        print(f"   degrees: credential push skipped ({exc.message})")
    abc = await creds.abc_push(AbcPushRequest())
    ctx.count("abc_rows_pushed", abc.acknowledged + abc.pushed)
    attended = (
        (
            await db.execute(
                select(ConvocationRegistration)
                .where(ConvocationRegistration.convocation_id == conv.id, ConvocationRegistration.mode == "in_person")
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    for r in attended:
        r.status = "attended"
    await db.flush()
