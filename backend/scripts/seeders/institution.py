"""``institution`` demo seeder (Prompts/03 §03.2) — ``seed_demo_institution.py --type university --only institution``.

On top of ``base`` (institution, colleges A/B/C, faculty ENG, departments, roles, users):

* the institution profile (statutory ids, head, vision/mission, website) and college statutory ids / exam-centre flag;
* ``seed_institution_defaults(pack)`` — the settings template rows, the pack grading scale(s) and the
  institution-wide number sequences;
* for the university profile: ``institution.multi_college`` and ``institution.faculties`` switched on (both default
  off; the demo university has three colleges and a faculty) — platform overrides, like the super admin would;
* the current institution-wide academic year (June → May around today) with the Odd term current and
  ``in_progress`` and the Even term ``planned``;
* the pack's national holidays inside that year plus a few institution holidays.

Idempotent: existing rows are kept; the verification script ``03_institution.ps1`` creates its own college / years
so re-running this seeder never collides with it.
"""

from datetime import UTC, date, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select

from app.models.academic import AcademicTerm, AcademicYear
from app.models.platform import College, Holiday, Institution, InstitutionProfile

HOLIDAYS: tuple[tuple[str, int, int, str], ...] = (
    ("Independence Day", 8, 15, "public"),
    ("Gandhi Jayanti", 10, 2, "public"),
    ("Diwali", 10, 20, "public"),
    ("Christmas", 12, 25, "public"),
    ("Republic Day", 1, 26, "public"),
    ("Holi", 3, 4, "public"),
    ("Founders' Day", 9, 5, "institution"),
)


@seeder("institution", after=["base"])
async def seed_institution(ctx: SeedContext) -> None:
    from app.db.session import bind_tenant, set_tenant
    from app.services.feature_service import FeatureService
    from app.services.institution_defaults import seed_institution_defaults

    inst = (
        await ctx.db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))
    ).scalar_one_or_none()
    if inst is None:
        raise SystemExit(f"institution {ctx.profile['slug']} missing - run --only base first")
    bind_tenant(ctx.db, inst.id)
    await set_tenant(ctx.db, inst.id)

    # ---- profile -----------------------------------------------------------------------------------------------
    if not inst.aishe_code:
        inst.short_name = inst.short_name or "SDU"
        inst.aishe_code = "U-0999"
        inst.aicte_pid = "1-9999999999"
        inst.naac_id = "KAUNGN99999"
        inst.ugc_status = "2(f) & 12(B)"
        inst.website_url = f"https://{ctx.profile['slug']}.septronuniverse.in"
        inst.contact = {"email": f"office@{ctx.profile['slug']}.septronuniverse.in", "phone": "+91 80 4000 0000"}
        inst.address = {"line1": "1 University Road", "city": "Bengaluru", "state": "Karnataka", "pincode": "560001"}
        ctx.count("institution_profile_updates")
    profile, _ = await ctx.get_or_create(
        InstitutionProfile,
        {
            "established_year": 1998,
            "vision": "Knowledge that serves society.",
            "mission": "Outcome-based education, research and community engagement.",
            "head_title": "Vice Chancellor" if inst.institution_type == "university" else "Principal",
            "head_name": "Dr. A. Demo",
            "social_links": {"website": inst.website_url},
        },
        institution_id=inst.id,
    )
    colleges = (
        (await ctx.db.execute(select(College).where(College.institution_id == inst.id, College.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    for college in colleges:
        if college.code == "A" and not college.is_exam_centre:
            college.is_exam_centre = True
            college.exam_centre_code = "EC-A01"
            college.aishe_code = "C-10001"

    # ---- pack defaults: settings, grading scale, number sequences ------------------------------------------------
    conn = await ctx.db.connection()
    defaults = await conn.run_sync(lambda c: seed_institution_defaults(c, inst.id, inst.regulatory_pack))
    for key in ("settings", "grading_scales", "number_sequences"):
        if defaults[key]:
            ctx.count(f"defaults.{key}", defaults[key])

    # ---- features: multi-college + faculties for the university profile --------------------------------------------
    if inst.institution_type == "university":
        service = FeatureService(ctx.db)
        effective = await service.effective(inst.id)
        for key in ("institution.multi_college", "institution.faculties"):
            if key not in effective:
                await service.set_platform_flag(
                    inst.id, key, enabled=True, reason="demo seed (Phase 03)", config=None, confirm_dependencies=True
                )
                ctx.count("feature_overrides")

    # ---- current academic year + terms -------------------------------------------------------------------------
    today = datetime.now(UTC).date()
    start_year = today.year if today.month >= 6 else today.year - 1
    name = f"{start_year}-{(start_year + 1) % 100:02d}"
    year, created = await ctx.get_or_create(
        AcademicYear,
        {"start_date": date(start_year, 6, 1), "end_date": date(start_year + 1, 5, 31), "is_current": False},
        institution_id=inst.id,
        college_id=None,
        name=name,
    )
    if created:
        others = (
            await ctx.db.execute(
                select(AcademicYear).where(
                    AcademicYear.institution_id == inst.id,
                    AcademicYear.college_id.is_(None),
                    AcademicYear.is_current.is_(True),
                    AcademicYear.id != year.id,
                )
            )
        ).scalars()
        current_exists = any(True for _ in others)
        year.is_current = not current_exists
        await ctx.db.flush()
    odd_start, odd_end = date(start_year, 7, 1), date(start_year, 11, 30)
    even_start, even_end = date(start_year + 1, 1, 4), date(start_year + 1, 5, 15)
    odd_status = "in_progress" if odd_start <= today <= odd_end else ("planned" if today < odd_start else "exam")
    for seq, (tname, ttype, start, end, status, current) in enumerate(
        (
            ("Odd Semester", "odd", odd_start, odd_end, odd_status, today < even_start),
            (
                "Even Semester",
                "even",
                even_start,
                even_end,
                "planned" if today < even_start else "in_progress",
                today >= even_start,
            ),
        ),
        start=1,
    ):
        await ctx.get_or_create(
            AcademicTerm,
            {
                "name": tname,
                "start_date": start,
                "end_date": end,
                "registration_start": start - timedelta(days=21),
                "registration_end": start + timedelta(days=7),
                "add_drop_end": start + timedelta(days=14),
                "last_instruction_date": end - timedelta(days=21),
                "status": status,
                "is_current": current and year.is_current,
            },
            institution_id=inst.id,
            college_id=None,
            academic_year_id=year.id,
            term_type=ttype,
            sequence=seq,
        )

    # ---- holidays inside the year ------------------------------------------------------------------------------
    for hname, month, day, htype in HOLIDAYS:
        d = date(start_year if month >= 6 else start_year + 1, month, day)
        await ctx.get_or_create(
            Holiday,
            {"holiday_type": htype, "applies_to": "all"},
            institution_id=inst.id,
            college_id=None,
            holiday_date=d,
            name=hname,
        )
    await ctx.db.flush()
    _ = profile
