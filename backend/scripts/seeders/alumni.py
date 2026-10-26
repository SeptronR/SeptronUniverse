"""``alumni`` demo seeder (Prompts/29 §29.2) — ``seed_demo_institution.py --only alumni``.

Enables the Phase 29 features (jobs board, fundraising, 80G), then: alumni profiles for 6 graduated batches (≈4,000 —
``students(status='alumni')`` stubs; 40 % claimed / verified, 60 % consent to contact, 25 % willing to mentor),
employment histories (current company from the Phase 28 company list when present, else a fixed list; some with a
past job), 12 alumni events on the Phase 25 engine (2 upcoming with fees), 60 jobs (5 pending moderation), 4
campaigns (1 restricted endowment), 500 donations (online / offline, 120 with 80G receipt numbers, 3 corporate) and
engagement scores. Demo users ``alumni.coord`` (coordinator), ``alumni.a`` (verified, consents contact + directory),
``alumni.b`` (verified, no consents) — credentials go to LOCAL_TEST_CREDENTIALS.md only — and ``alumni.1`` is linked
to a verified profile; ``ALM-LEGACY-0001`` is an unclaimed legacy profile for the claim flow. Idempotent: skipped when
the institution has alumni profiles.
"""

import random
import uuid
from datetime import UTC, date, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

CITIES = ("Bengaluru", "Hyderabad", "Chennai", "Pune", "Mumbai", "Delhi", "Kochi", "Coimbatore", "Mysuru", "Noida")
ABROAD = (("San Jose", "USA"), ("London", "UK"), ("Singapore", "Singapore"), ("Dubai", "UAE"), ("Toronto", "Canada"))
COMPANIES = (
    "Infosys", "TCS", "Wipro", "Accenture", "Cognizant", "HCLTech", "Capgemini", "Deloitte", "Amazon", "Microsoft",
    "Google", "Bosch", "Siemens", "Tata Motors", "L&T", "Zoho", "Freshworks", "Flipkart", "HDFC Bank", "ICICI Bank",
)  # fmt: skip
ROLES = ("Software Engineer", "Senior Engineer", "Analyst", "Consultant", "Manager", "Data Scientist", "Lead Engineer")
FIRST = (
    "Arjun",
    "Priya",
    "Rahul",
    "Ananya",
    "Vikram",
    "Sneha",
    "Karthik",
    "Divya",
    "Rohan",
    "Meera",
    "Aditya",
    "Kavya",
)
LAST = ("Rao", "Sharma", "Iyer", "Reddy", "Nair", "Gupta", "Menon", "Patel", "Kumar", "Shetty", "Joshi", "Das")
EVENT_TITLES = (
    ("reunion", "Silver Jubilee Reunion"), ("meet", "Bengaluru Chapter Meet"), ("webinar", "Careers in AI — alumni talk"),
    ("mentorship", "Mentorship kick-off"), ("meet", "Hyderabad Chapter Meet"), ("webinar", "Higher studies abroad"),
    ("reunion", "Decennial Reunion"), ("meet", "Alumni Day"), ("webinar", "Founders' fireside chat"),
    ("mentorship", "Mock interviews by alumni"), ("meet", "Pune Chapter Meet"), ("reunion", "Homecoming"),
)  # fmt: skip
CAMPAIGNS = (
    ("Library modernisation", 2_500_000_00, False),
    ("Merit scholarships 2026", 1_000_000_00, False),
    ("Centre of Excellence in AI — endowment", 5_000_000_00, True),
    ("Sports complex", 1_500_000_00, False),
)


@seeder("alumni", after=["students", "hr", "placement", "facilities", "accounting", "documents"])
async def seed_alumni(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from seeders.base import _password

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.security import encrypt_secret, hash_password
    from app.db.session import bind_tenant, set_tenant
    from app.enums.alumni import DEFAULT_DIRECTORY_FIELDS, DIRECTORY_FIELDS
    from app.models.academic import Program
    from app.models.alumni import (
        AlumniEmploymentHistory,
        AlumniEvent,
        AlumniJob,
        AlumniProfile,
        Donation,
        FundraisingCampaign,
    )
    from app.models.events import Event
    from app.models.platform import College, Institution, InstitutionSetting, Role, User, UserRole
    from app.models.students import Student
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(29)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(AlumniProfile).where(AlumniProfile.institution_id == inst.id))
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in ("alumni.core", "alumni.portal", "alumni.jobs_board", "alumni.fundraising", "alumni.donations_80g"):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 29)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   alumni: {key} not enabled ({exc})")

    now = datetime.now(UTC)
    today = now.date()
    users = {u.username: u for u in (await db.execute(select(User).where(User.institution_id == inst.id))).scalars()}
    roles = {
        r.slug: r
        for r in (
            await db.execute(select(Role).where(Role.institution_id == inst.id, Role.deleted_at.is_(None)))
        ).scalars()
    }

    def meta(kind: str, rid: object, value: dict) -> None:
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="alumni_meta",
                key=f"{kind}:{rid}",
                value=value,
                value_type="json",
            )
        )

    async def demo_user(
        username: str, name: str, role: str, scope: str, user_type: str, label: str | None = None
    ) -> User:
        u = users.get(username)
        if u is None:
            pwd = _password()
            u = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@example.com",
                display_name=name,
                user_type=user_type,
                password_hash=hash_password(pwd),
                is_verified=True,
                must_change_password=False,
                locale="en-IN",
                timezone="Asia/Kolkata",
            )
            db.add(u)
            await db.flush()
            users[username] = u
            ctx.count("users")
            ctx.credentials.append((label or role, username, pwd))
            if role in roles:
                db.add(
                    UserRole(
                        institution_id=inst.id, user_id=u.id, role_id=roles[role].id, scope_type=scope, scope_id=None
                    )
                )
        return u

    coord = await demo_user("alumni.coord", "Alumni Coordinator", "alumni_coordinator", "institution", "staff")
    user_a = await demo_user("alumni.a", "Alumna A (verified, consents)", "alumni", "self", "alumni", "alumni_a")
    user_b = await demo_user("alumni.b", "Alumnus B (verified, no consents)", "alumni", "self", "alumni", "alumni_b")
    user_1 = users.get("alumni.1")

    colleges = list((await db.execute(select(College).where(College.institution_id == inst.id))).scalars())
    programs = list(
        (
            await db.execute(select(Program).where(Program.institution_id == inst.id, Program.deleted_at.is_(None)))
        ).scalars()
    )
    if not colleges or not programs:
        print("   alumni: no colleges / programmes — skipped")
        return
    try:
        from app.models.placement import Company

        plc = [
            c.name
            for c in (await db.execute(select(Company).where(Company.institution_id == inst.id).limit(40))).scalars()
        ]
    except Exception:  # noqa: BLE001 - placement not seeded
        plc = []
    company_pool = list(plc or COMPANIES)

    # ---- profiles: 6 graduated batches ---------------------------------------------------------------------------------------
    total = int(ctx.profile.get("alumni_count") or 4000)
    years = [today.year - k for k in range(1, 7)]
    profiles: list[AlumniProfile] = []
    verified_ids: list[uuid.UUID] = []
    for i in range(total):
        year = years[i % len(years)]
        prog = programs[i % len(programs)]
        college = next((c for c in colleges if c.id == prog.college_id), colleges[0])
        seq = i + 1
        reg = f"ALM{year % 100:02d}{seq:05d}"
        first, last = rng.choice(FIRST), rng.choice(LAST)
        st = Student(
            institution_id=inst.id,
            college_id=college.id,
            registration_number=reg,
            first_name=first,
            last_name=last,
            dob=date(year - 22, rng.randint(1, 12), rng.randint(1, 28)),
            gender=rng.choice(("male", "female")),
            email=f"{first.lower()}.{last.lower()}.{reg.lower()}@example.com",
            phone=f"+9198{rng.randint(10**7, 10**8 - 1)}",
            status="alumni",
        )
        db.add(st)
        await db.flush()
        verified = rng.random() < 0.40
        abroad = rng.random() < 0.08
        city, country = rng.choice(ABROAD) if abroad else (rng.choice(CITIES), "India")
        employed = rng.random() < 0.82
        company = rng.choice(company_pool) if employed else None
        a = AlumniProfile(
            institution_id=inst.id,
            student_id=st.id,
            graduation_year=year,
            program_id=prog.id,
            current_company=company,
            designation=rng.choice(ROLES) if company else None,
            city=city,
            country=country,
            linkedin_url=f"https://www.linkedin.com/in/{first.lower()}-{last.lower()}-{seq}"
            if rng.random() < 0.5
            else None,
            email=st.email,
            phone=st.phone,
            is_verified=verified,
            willing_to_mentor=rng.random() < 0.25,
            willing_to_recruit=rng.random() < 0.10,
            consent_contact=rng.random() < 0.60,
            last_updated_by_alumni_at=now - timedelta(days=rng.randint(10, 700)) if verified else None,
        )
        db.add(a)
        profiles.append(a)
        if i % 500 == 499:
            await db.flush()
    await db.flush()
    for a in profiles:
        verified = a.is_verified
        higher = None if a.current_company or rng.random() < 0.5 else {"university": "IISc", "program": "M.Tech"}
        consent = [
            f
            for f in DIRECTORY_FIELDS
            if f in DEFAULT_DIRECTORY_FIELDS or (a.consent_contact and f in ("email", "linkedin_url"))
        ]
        meta(
            "profile",
            a.id,
            {
                "claim_status": "verified" if verified else "unclaimed",
                "legacy": True,
                "source": "seed",
                "consent_directory_fields": consent if rng.random() < 0.85 else [],
                "higher_studies": higher,
                "chapter": a.city if a.city in ("Bengaluru", "Hyderabad", "Pune") else None,
                "profile_updates": rng.randint(0, 4) if verified else 0,
            },
        )
        if verified:
            verified_ids.append(a.id)
        if a.current_company:
            if rng.random() < 0.35:
                db.add(
                    AlumniEmploymentHistory(
                        institution_id=inst.id,
                        alumni_id=a.id,
                        company=rng.choice(company_pool),
                        designation=rng.choice(ROLES),
                        from_on=date((a.graduation_year or today.year), 7, 1),
                        to_on=date((a.graduation_year or today.year) + 1, 12, 31),
                        is_current=False,
                    )
                )
            db.add(
                AlumniEmploymentHistory(
                    institution_id=inst.id,
                    alumni_id=a.id,
                    company=a.current_company,
                    designation=a.designation,
                    from_on=date((a.graduation_year or today.year) + 1, 1, 15),
                    is_current=True,
                )
            )
    ctx.count("students", len(profiles))
    ctx.count("alumni_profiles", len(profiles))
    await db.flush()

    # demo identities: alumni.a / alumni.b / alumni.1 on verified profiles; one legacy unclaimed profile
    verified_profiles = [a for a in profiles if a.is_verified]
    for user, consents in ((user_a, True), (user_b, False), (user_1, True)):
        if user is None or not verified_profiles:
            continue
        a = verified_profiles.pop(0)
        a.user_id = user.id
        a.city = "Bengaluru"
        a.consent_contact = consents
        st = (await db.execute(select(Student).where(Student.id == a.student_id))).scalar_one()
        st.user_id = user.id
        row = (
            await db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == inst.id,
                    InstitutionSetting.category == "alumni_meta",
                    InstitutionSetting.key == f"profile:{a.id}",
                )
            )
        ).scalar_one()
        row.value = {
            **row.value,
            "consent_directory_fields": list(DIRECTORY_FIELDS) if consents else [],
            "claim_status": "verified",
        }
    legacy = next((a for a in profiles if not a.is_verified and a.user_id is None), None)
    if legacy is not None:
        st = (await db.execute(select(Student).where(Student.id == legacy.student_id))).scalar_one()
        st.registration_number = "ALM-LEGACY-0001"
        legacy.email = st.email = "legacy.alumnus@example.com"
    await db.flush()

    # ---- events on the Phase 25 engine ---------------------------------------------------------------------------------------
    events = 0
    for k, (etype, title) in enumerate(EVENT_TITLES):
        upcoming = k < 2
        held = today + timedelta(days=20 + 10 * k) if upcoming else today - timedelta(days=30 * (k + 1))
        fee = (100_000 if k == 0 else 50_000) if upcoming else 0
        e = Event(
            institution_id=inst.id,
            event_type="alumni",
            title=title,
            description=f"{title} for the alumni community.",
            from_on=held,
            to_on=held,
            venue_text="Main auditorium" if etype != "webinar" else "Online",
            registration_fee_paise=fee or None,
            naac_criterion="5.4.1",
            status="scheduled" if upcoming else "completed",
            participants_count=None if upcoming else rng.randint(40, 300),
            created_by=coord.id,
        )
        db.add(e)
        await db.flush()
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="facilities_meta",
                key=f"event:{e.id}",
                value={
                    "registration": {
                        "open": upcoming,
                        "fee_paise": fee,
                        "capacity": 400,
                        "audience": "public",
                        "waitlist": True,
                    }
                },
                value_type="json",
            )
        )
        ae = AlumniEvent(
            institution_id=inst.id,
            title=title,
            held_on=held,
            venue=e.venue_text,
            event_type=etype,
            registrations_count=0 if upcoming else int(e.participants_count or 0),
            event_id=e.id,
        )
        db.add(ae)
        await db.flush()
        meta(
            "alumni_event",
            ae.id,
            {
                "webinar_url": "https://meet.example.com/alumni" if etype == "webinar" else None,
                "invited": rng.randint(200, 1500),
            },
        )
        events += 1
    ctx.count("alumni_events", events)

    # ---- jobs board -------------------------------------------------------------------------------------------------------------------
    posters = [a for a in profiles if a.is_verified]
    for k in range(60):
        a = rng.choice(posters)
        pending = k < 5
        expired = 5 <= k < 10
        j = AlumniJob(
            institution_id=inst.id,
            posted_by_alumni_id=a.id,
            title=rng.choice(ROLES),
            company=a.current_company or rng.choice(company_pool),
            location=rng.choice(CITIES),
            description="Referral opening shared by an alumnus.",
            apply_url=f"https://careers.example.com/jobs/{1000 + k}",
            expires_on=today - timedelta(days=3) if expired else today + timedelta(days=rng.randint(10, 60)),
            is_active=not pending and not expired,
        )
        db.add(j)
        await db.flush()
        meta(
            "job",
            j.id,
            {
                "status": "pending" if pending else "expired" if expired else "approved",
                "clicks": 0 if pending else rng.randint(0, 120),
                "open_to_students": rng.random() < 0.5,
            },
        )
    ctx.count("alumni_jobs", 60)

    # ---- campaigns + donations ---------------------------------------------------------------------------------------------------------
    camps: list[FundraisingCampaign] = []
    for k, (title, goal, restricted) in enumerate(CAMPAIGNS):
        c = FundraisingCampaign(
            institution_id=inst.id,
            title=title,
            purpose=f"{title}: support from our alumni and friends.",
            goal_paise=goal,
            from_on=today - timedelta(days=200 - 30 * k),
            to_on=today + timedelta(days=120 + 30 * k),
            status="closed" if k == 3 else "active",
        )
        db.add(c)
        await db.flush()
        camps.append(c)
        meta(
            "campaign",
            c.id,
            {"is_restricted_fund": restricted, "ledger_account_id": None, "is_public": True, "milestones": []},
        )
    ctx.count("fundraising_campaigns", len(camps))

    counters: dict[str, int] = {}
    donors = [a for a in profiles if a.is_verified] or profiles
    receipts = 0
    for k in range(500):
        corporate = k < 3
        individual = 3 <= k < 60
        a = None if corporate or individual else rng.choice(donors)
        on = today - timedelta(days=rng.randint(0, 540))
        mode = "online" if rng.random() < 0.55 else rng.choice(("bank_transfer", "cheque", "upi", "cash"))
        amount = (
            rng.choice((25_00_000_00, 10_00_000_00, 5_00_000_00))
            if corporate
            else rng.choice((1_000_00, 2_000_00, 5_000_00, 10_000_00, 25_000_00, 50_000_00))
        )
        if mode == "cash":
            amount = min(amount, 2_000_00)
        camp = rng.choice(camps) if rng.random() < 0.85 else None
        if camp is not None and camp.status == "closed" and on > today - timedelta(days=20):
            camp = None
        if a is not None:
            ref = {"alumni_id": str(a.id), "name": f"Alumnus {a.graduation_year}", "email": a.email}
            if a.user_id:
                ref["user_id"] = str(a.user_id)
        elif corporate:
            org = ("Nimbus Technologies", "Vertex Systems", "Helix Labs")[k]
            ref = {
                "organisation": org,
                "name": org,
                "csr_reference": f"CSR/{today.year}/{k + 1:03d}",
                "address": "Bengaluru",
            }
        else:
            ref = {
                "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                "email": f"donor{k}@example.com",
                "anonymous": rng.random() < 0.2,
            }
        is_80g = receipts < 120 and mode != "cash" and rng.random() < 0.4
        pan = f"ABCPD{rng.randint(1000, 9999)}K" if is_80g or corporate else None
        d = Donation(
            institution_id=inst.id,
            donor_type="corporate" if corporate else "individual" if individual else "alumni",
            donor_ref=ref,
            campaign_id=camp.id if camp else None,
            amount_paise=amount,
            on_date=on,
            mode=mode,
            is_80g=is_80g,
            pan_encrypted=encrypt_secret(pan) if pan else None,
        )
        if is_80g:
            fy_start = on.year if on.month >= 4 else on.year - 1
            fy = f"{fy_start}-{(fy_start + 1) % 100:02d}"
            counters[fy] = counters.get(fy, 0) + 1
            d.receipt_no = f"80G/{fy}/{counters[fy]:05d}"
            receipts += 1
        db.add(d)
        await db.flush()
        meta(
            "donation",
            d.id,
            {"reference": f"UTR{rng.randint(10**9, 10**10 - 1)}" if mode != "cash" else None, "wants_80g": is_80g},
        )
        if camp is not None:
            camp.raised_paise = int(camp.raised_paise or 0) + amount
    for fy, n in counters.items():
        meta("seq80g", fy, {"next": n + 1})
    for c in camps:
        pct = 100 * c.raised_paise / c.goal_paise if c.goal_paise else 0
        row = (
            await db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == inst.id,
                    InstitutionSetting.category == "alumni_meta",
                    InstitutionSetting.key == f"campaign:{c.id}",
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.value = {**row.value, "milestones": [m for m in (25, 50, 75, 100) if pct >= m]}
    ctx.count("donations", 500)
    ctx.count("donation_receipts_80g", receipts)
    await db.flush()

    # ---- engagement scores ---------------------------------------------------------------------------------------------------------------
    from app.services.alumni.profile_service import ProfileService

    svc = ProfileService(db, None, institution_id=inst.id)
    scored = 0
    for a in profiles:
        if a.is_verified:
            await svc.compute_engagement(a)
            scored += 1
    ctx.count("engagement_scores", scored)
    await db.flush()
