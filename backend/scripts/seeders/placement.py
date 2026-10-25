"""``placement`` demo seeder (Prompts/28 §28.2) — ``seed_demo_institution.py --only placement``.

Enables the Phase 28 features (recruiter portal included), then: 80 companies across tiers (6 with recruiter users —
credentials go to LOCAL_TEST_CREDENTIALS.md only), a policy per graduating batch (one offer, ₹10 LPA dream threshold),
placement profiles for every final-year student (40 higher-studies and 15 other opt-outs, 4 blacklisted), 40 drives
across statuses with rounds / results (funnels), ≈2,500 applications, ≈320 offers (30 PPO, 20 declined, 8 revoked),
≈600 internships (NOC requested, evaluations), 12 training programmes with attendance / scores and 25 company feedbacks
— scaled down when the demo has fewer final-year students. Idempotent: skipped when the institution has companies.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

SECTORS = ("IT services", "Product", "Core engineering", "BFSI", "Consulting", "Manufacturing", "Telecom", "Analytics")
PREFIX = (
    "Acme", "Nimbus", "Vertex", "Quantum", "Zenith", "Orbit", "Pinnacle", "Helix", "Cobalt", "Summit",
    "Stellar", "Nova", "Apex", "Lumen", "Titan", "Aurora", "Falcon", "Indus", "Sapphire", "Crest",
)  # fmt: skip
SUFFIX = ("Technologies", "Systems", "Labs", "Solutions")
ROUNDS = (("aptitude", "Online aptitude"), ("technical", "Technical interview"), ("hr", "HR interview"))
TRAINING = (
    ("aptitude", "Quantitative aptitude bootcamp"),
    ("aptitude", "Logical reasoning sprint"),
    ("soft_skills", "Communication & presentation"),
    ("soft_skills", "Group discussion practice"),
    ("technical", "Data structures refresher"),
    ("technical", "SQL & databases"),
    ("technical", "Cloud fundamentals"),
    ("technical", "System design basics"),
    ("mock_interview", "Mock technical interviews"),
    ("mock_interview", "Mock HR interviews"),
    ("soft_skills", "Resume writing workshop"),
    ("aptitude", "Verbal ability"),
)


@seeder("placement", after=["students", "hr", "offerings", "attendance", "results", "student_support"])
async def seed_placement(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from seeders.base import _password

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.security import hash_password
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import Batch
    from app.models.placement import (
        Company,
        CompanyFeedback,
        DriveApplication,
        DriveRound,
        DriveRoundResult,
        Internship,
        PlacementDrive,
        PlacementOffer,
        PlacementPolicy,
        StudentPlacementProfile,
        TrainingAttendance,
        TrainingProgram,
    )
    from app.models.platform import Institution, InstitutionSetting, Role, User, UserRole
    from app.models.students import Student, StudentProgramEnrollment
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(28)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(Company).where(Company.institution_id == inst.id))
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "placement.core",
        "placement.internships",
        "placement.training",
        "placement.resume_builder",
        "placement.recruiter_portal",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 28)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   placement: {key} not enabled ({exc})")

    now = datetime.now(UTC)
    today = now.date()
    users = {u.username: u for u in (await db.execute(select(User).where(User.institution_id == inst.id))).scalars()}
    officer = users.get("placement") or users.get("registrar")
    actor_id = officer.id if officer else None

    # ---- final-year students (the earliest admitted active batch per programme) ------------------------------------------
    rows = (
        await db.execute(
            select(StudentProgramEnrollment, Student, Batch.admission_year)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .join(Batch, Batch.id == StudentProgramEnrollment.batch_id)
            .where(StudentProgramEnrollment.institution_id == inst.id, StudentProgramEnrollment.status == "active")
            .order_by(Student.registration_number)
        )
    ).all()
    if not rows:
        print("   placement: no active students — skipped")
        return
    first_year: dict[uuid.UUID, int] = {}
    for e, _, yr in rows:
        first_year[e.program_id] = min(first_year.get(e.program_id, yr), yr)
    finals = [(e, s) for e, s, yr in rows if yr == first_year[e.program_id]]
    if len(finals) < 40:
        finals = [(e, s) for e, s, _ in rows]
    enrols = [e for e, _ in finals]
    print(f"   placement: {len(enrols)} final-year students")

    # ---- companies + recruiters --------------------------------------------------------------------------------------------
    companies: list[Company] = []
    names: set[str] = set()
    tiers = ["super_dream"] * 6 + ["dream"] * 14 + ["core"] * 30 + ["mass"] * 30
    for i in range(80):
        name = f"{PREFIX[i % len(PREFIX)]} {SUFFIX[(i // len(PREFIX)) % len(SUFFIX)]}"
        if name in names:
            name = f"{name} {i}"
        names.add(name)
        c = Company(
            institution_id=inst.id,
            name=name,
            sector=rng.choice(SECTORS),
            website=f"https://{name.lower().replace(' ', '')}.example.com",
            hq_city=rng.choice(("Bengaluru", "Hyderabad", "Pune", "Chennai", "Gurugram", "Mumbai")),
            tier=tiers[i],
            contacts=[
                {
                    "name": f"HR {name.split()[0]}",
                    "designation": "Talent acquisition",
                    "email": f"hr@{name.split()[0].lower()}.example.com",
                }
            ],
            recruiter_user_ids=[],
            is_blacklisted=i == 79,
        )
        db.add(c)
        companies.append(c)
    await db.flush()
    ctx.count("companies", len(companies))
    role = (
        await db.execute(
            select(Role).where(Role.institution_id == inst.id, Role.slug == "recruiter", Role.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    for c in companies[:6]:
        username = f"recruiter.{c.name.split()[0].lower()}"
        user = users.get(username)
        if user is None:
            pwd = _password()
            user = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@example.com",
                display_name=f"Recruiter — {c.name}",
                user_type="external",
                password_hash=hash_password(pwd),
                is_verified=True,
                must_change_password=False,
                locale="en-IN",
                timezone="Asia/Kolkata",
            )
            db.add(user)
            await db.flush()
            ctx.count("users")
            ctx.credentials.append(("recruiter", username, pwd))
        if role is not None:
            db.add(UserRole(institution_id=inst.id, user_id=user.id, role_id=role.id, scope_type="self", scope_id=None))
        c.recruiter_user_ids = [str(user.id)]
    await db.flush()

    # ---- policies per graduating batch -------------------------------------------------------------------------------------
    for bid in {e.batch_id for e in enrols}:
        db.add(
            PlacementPolicy(
                institution_id=inst.id,
                batch_id=bid,
                max_offers=1,
                dream_ctc_threshold_paise=100_000_000,
                allow_upgrade_if_dream=True,
                opt_out_allowed=True,
                rules={"internship_ppo_counts_as_offer": True},
            )
        )
        ctx.count("placement_policies")

    # ---- profiles ----------------------------------------------------------------------------------------------------------
    skills_pool = (
        "python",
        "java",
        "c++",
        "sql",
        "react",
        "ml",
        "embedded",
        "vlsi",
        "autocad",
        "communication",
        "excel",
    )
    profiles: dict[uuid.UUID, StudentPlacementProfile] = {}
    order = list(enrols)
    rng.shuffle(order)
    scale = max(1, len(enrols) // 10)
    n_hs, n_opt, n_bl = min(40, scale * 2), min(15, scale), min(4, max(1, scale // 3))
    for idx, e in enumerate(order):
        p = StudentPlacementProfile(
            institution_id=inst.id,
            student_program_enrollment_id=e.id,
            skills=sorted(rng.sample(skills_pool, k=rng.randint(2, 5))),
            resume_json={
                "summary": "Final-year student seeking a graduate engineer role.",
                "education": [{"degree": "B.Tech", "institution": inst.name, "year": today.year}],
                "projects": [{"title": f"Project {idx % 50}", "tech": "python"}],
            },
            consent_share_profile=rng.random() > 0.05,
            placement_status="unplaced",
        )
        if idx < n_hs:
            p.is_opted_out, p.opt_out_reason, p.placement_status = True, "higher_studies", "opted_out"
            p.higher_studies = {
                "exam": rng.choice(("GATE", "GRE", "CAT")),
                "score": str(rng.randint(60, 99)),
                "country": "India",
            }
        elif idx < n_hs + n_opt:
            p.is_opted_out, p.placement_status = True, "opted_out"
            p.opt_out_reason = rng.choice(("entrepreneurship", "family_business", "govt_exams", "other"))
        elif idx < n_hs + n_opt + n_bl:
            p.is_blacklisted, p.blacklist_reason = True, "Absent after shortlist (demo)"
        db.add(p)
        profiles[e.id] = p
    await db.flush()
    ctx.count("student_placement_profiles", len(profiles))
    for e in order[n_hs + n_opt : n_hs + n_opt + n_bl]:
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="placement_meta",
                key=f"blacklist:{e.id}",
                value={
                    "reason": "Absent after shortlist (demo)",
                    "source": "no_show_after_shortlist",
                    "at": now.isoformat(),
                },
                value_type="json",
            )
        )
    active = [e for e in order if not profiles[e.id].is_opted_out and not profiles[e.id].is_blacklisted]

    # ---- drives / rounds / applications / results / offers -------------------------------------------------------------------
    statuses = ["completed"] * 22 + ["in_progress"] * 6 + ["closed"] * 3 + ["open"] * 5 + ["draft"] * 3 + ["cancelled"]
    target_apps = min(2500, len(active) * 12)
    per_drive = max(5, target_apps // 36)
    offers_made = 0
    accepted_of: dict[uuid.UUID, PlacementOffer] = {}
    ppo_left, declined_left, revoked_left = 30, 20, 8
    target_offers = min(320, int(len(active) * 0.8))
    drives: list[PlacementDrive] = []
    live = [c for c in companies if not c.is_blacklisted]
    for i, st in enumerate(statuses):
        c = live[i % len(live)]
        lpa = {
            "super_dream": rng.randint(15, 30),
            "dream": rng.randint(10, 14),
            "core": rng.randint(6, 9),
            "mass": rng.randint(3, 5),
        }[c.tier or "mass"]
        drive_on = (
            today - timedelta(days=rng.randint(10, 200))
            if st in ("completed", "in_progress", "closed")
            else today + timedelta(days=rng.randint(5, 40))
        )
        d = PlacementDrive(
            institution_id=inst.id,
            company_id=c.id,
            college_id=None,
            title=f"{c.name} — {'Graduate engineer' if c.tier != 'mass' else 'Associate'} {today.year}",
            job_role="Graduate engineer trainee" if c.tier != "mass" else "Associate software engineer",
            job_type="full_time",
            ctc_min_paise=lpa * 10_000_000,
            ctc_max_paise=(lpa + 2) * 10_000_000,
            locations=[c.hq_city or "Bengaluru"],
            eligibility_rules={"min_cgpa": 6.0 if c.tier != "super_dream" else 7.5, "max_active_backlogs": 0},
            registration_deadline=datetime.combine(drive_on - timedelta(days=3), datetime.min.time(), tzinfo=UTC),
            drive_on=drive_on,
            mode="on_campus",
            status=st,
            created_by=actor_id,
        )
        db.add(d)
        drives.append(d)
    await db.flush()
    ctx.count("placement_drives", len(drives))
    app_count = round_results = 0
    for d in drives:
        if d.status in ("draft", "cancelled"):
            continue
        rounds = []
        for n, (rtype, rname) in enumerate(ROUNDS, start=1):
            r = DriveRound(
                institution_id=inst.id,
                drive_id=d.id,
                round_no=n,
                name=rname,
                round_type=rtype,
                scheduled_at=(
                    datetime.combine(d.drive_on, datetime.min.time(), tzinfo=UTC) + timedelta(hours=3 + n * 2)
                    if d.drive_on
                    else None
                ),
                venue=f"Seminar hall {n}",
            )
            db.add(r)
            rounds.append(r)
        await db.flush()
        ctx.count("drive_rounds", len(rounds))
        pool = rng.sample(active, k=min(per_drive, len(active)))
        for e in pool:
            prof = profiles[e.id]
            if e.id in accepted_of and (d.ctc_min_paise or 0) < 100_000_000:
                continue
            a = DriveApplication(
                institution_id=inst.id,
                drive_id=d.id,
                student_program_enrollment_id=e.id,
                eligibility_snapshot={
                    "is_eligible": True,
                    "cgpa": float(e.cgpa) if e.cgpa else None,
                    "reasons": [],
                    "seeded": True,
                },
                is_eligible=True,
                resume_url=prof.resume_url,
                status="applied",
            )
            db.add(a)
            await db.flush()
            app_count += 1
            if d.status == "open":
                continue
            # funnel: 60 % shortlisted, then 70 % / 60 % / 70 % clear the rounds
            if rng.random() > 0.6:
                a.status = "rejected" if d.status == "completed" else "applied"
                continue
            a.status = "shortlisted"
            cleared_all = True
            for r in rounds:
                roll = rng.random()
                status = (
                    "absent"
                    if roll < 0.03
                    else ("cleared" if roll < {1: 0.7, 2: 0.6, 3: 0.75}[r.round_no] else "not_cleared")
                )
                db.add(
                    DriveRoundResult(
                        institution_id=inst.id,
                        application_id=a.id,
                        round_id=r.id,
                        status=status,
                        score=Decimal(rng.randint(35, 98)),
                        recorded_by=actor_id,
                    )
                )
                round_results += 1
                if status != "cleared":
                    a.status = "absent" if status == "absent" else "rejected"
                    cleared_all = False
                    break
                a.status = "in_process"
                if d.status != "completed" and r.round_no == 2:
                    cleared_all = False
                    break
            if not cleared_all or offers_made >= target_offers:
                continue
            a.status = "selected"
            is_ppo = ppo_left > 0 and rng.random() < 0.12
            o = PlacementOffer(
                institution_id=inst.id,
                application_id=a.id,
                company_id=d.company_id,
                role=d.job_role,
                ctc_paise=(d.ctc_min_paise or 40_000_000) + rng.randint(0, 2) * 5_000_000,
                location=(d.locations or ["Bengaluru"])[0],
                offered_on=d.drive_on,
                joining_on=(d.drive_on or today) + timedelta(days=rng.randint(60, 240)),
                status="offered",
                is_ppo=is_ppo,
            )
            db.add(o)
            offers_made += 1
            ppo_left -= 1 if is_ppo else 0
            if declined_left > 0 and rng.random() < 0.08:
                o.status, a.status = "declined", "offer_declined"
                declined_left -= 1
            elif revoked_left > 0 and rng.random() < 0.03:
                o.status = "revoked"
                revoked_left -= 1
            elif e.id in accepted_of:
                o.status = "offered"  # dream offer pending decision for an already placed student
            elif rng.random() < 0.9:
                o.status, a.status = (
                    "joined" if o.joining_on and o.joining_on < today else "accepted"
                ), "offer_accepted"
                accepted_of[e.id] = o
                prof.placement_status = "placed"
    await db.flush()
    ctx.count("drive_applications", app_count)
    ctx.count("drive_round_results", round_results)
    ctx.count("placement_offers", offers_made)

    # ---- internships -------------------------------------------------------------------------------------------------------
    interns = 0
    for e in rng.sample(enrols, k=min(600, len(enrols))):
        start = today - timedelta(days=rng.randint(60, 400))
        weeks = rng.choice((2, 4, 6, 8, 8, 12))
        c = rng.choice(companies)
        done = start + timedelta(weeks=weeks) < today
        ev: dict[str, object] = {"noc": {"requested_at": now.isoformat(), "purpose": "Summer internship"}}
        if done and rng.random() < 0.7:
            ev.update(
                rubric_scores={"work": rng.randint(6, 10), "report": rng.randint(5, 10)},
                marks=float(rng.randint(55, 95)),
                max_marks=100.0,
                evaluated_at=now.isoformat(),
            )
        db.add(
            Internship(
                institution_id=inst.id,
                student_program_enrollment_id=e.id,
                company_id=c.id,
                company_name=c.name,
                role=rng.choice(("Software intern", "Data intern", "Design intern", "Embedded intern")),
                from_on=start,
                to_on=start + timedelta(weeks=weeks),
                stipend_paise=rng.choice((0, 1_000_000, 1_500_000, 2_500_000)),
                mentor=f"Mentor {rng.randint(1, 40)}",
                evaluation=ev,
                status="completed" if done else "ongoing",
            )
        )
        interns += 1
    ctx.count("internships", interns)

    # ---- training ----------------------------------------------------------------------------------------------------------
    batches = sorted({str(e.batch_id) for e in enrols})
    att = 0
    for i, (ttype, title) in enumerate(TRAINING):
        frm = today - timedelta(days=30 * (12 - i))
        sessions = [
            {
                "at": (
                    datetime.combine(frm, datetime.min.time(), tzinfo=UTC) + timedelta(days=2 * k, hours=4)
                ).isoformat(),
                "topic": f"{title} — part {k + 1}",
            }
            for k in range(5)
        ]
        p = TrainingProgram(
            institution_id=inst.id,
            training_type=ttype,
            title=title,
            trainer=rng.choice(("FACE Prep", "TIME", "In-house", "Ethnus")),
            from_on=frm,
            to_on=frm + timedelta(days=10),
            batches=batches,
            sessions=sessions,
        )
        db.add(p)
        await db.flush()
        for e in rng.sample(enrols, k=min(len(enrols), 120)):
            db.add(
                TrainingAttendance(
                    institution_id=inst.id,
                    program_id=p.id,
                    student_program_enrollment_id=e.id,
                    sessions_attended=rng.randint(2, 5),
                    score=(
                        Decimal(rng.randint(40, 98)) if ttype in ("aptitude", "mock_interview", "technical") else None
                    ),
                )
            )
            att += 1
    ctx.count("training_programs", len(TRAINING))
    ctx.count("training_attendance", att)

    # ---- company feedback --------------------------------------------------------------------------------------------------
    done_drives = [d for d in drives if d.status == "completed"]
    for d in rng.sample(done_drives, k=min(25, len(done_drives))):
        db.add(
            CompanyFeedback(
                institution_id=inst.id,
                drive_id=d.id,
                ratings={k: rng.randint(3, 5) for k in ("candidates", "process", "infrastructure", "coordination")},
                remarks="Well-organised drive; candidates were prepared.",
                submitted_by=actor_id,
            )
        )
    ctx.count("company_feedback", min(25, len(done_drives)))
    await db.flush()
