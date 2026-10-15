"""``admissions`` demo seeder (Prompts/08 §08.2) — ``seed_demo_institution.py --type university --only admissions``.

On top of ``students`` (programmes B.Tech CSE @ college A and MBA @ college B, the current academic year):

* the **UG 2026** cycle (slug ``ug-2026``, open, application fee ₹1,000, de-reservation SC/ST → GEN in round 2) with
  B.Tech CSE (intake 120 + 12 lateral, JEE 60 % + Class XII 40 %, min 60 % with 5 % SC/ST relaxation) and MBA
  (intake 60, CAT); the seat matrix (STATE GEN / EWS / OBC-NCL / SC / ST, PWD earmarked, LATERAL) sums to the intake;
* **300 applicants** through ``ApplicationService.create_applicant`` (application numbers from ``application_no``):
  mixed categories / quotas, 20 PwD, 10 lateral, entrance scores and Class XII marks, 1–2 preferences; 40
  ``verified`` (documents verified, application fee paid), 60 ``under_verification``, 100 ``submitted`` and the rest
  ``draft``;
* the demo applicant ``applicant.1`` (role ``applicant``; ``LOCAL_TEST_CREDENTIALS.md`` row ``applicant``) — verified;
* two counselling rounds (round 2 final); 12 enquiries across the stages, half assigned to ``admissions``.

Idempotent: the cycle is keyed by its slug, applicants are created only while the cycle has fewer than 300, rounds by
number, enquiries by phone. Services run as ``inst.admin`` (audit rows and outbox events as for the API; no
notifications — applicants without accounts have no user to notify).
"""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

from app.core.security import hash_password
from app.models.academic import AcademicTerm, AcademicYear, Program
from app.models.admissions import (
    AdmissionCycle,
    AdmissionCycleProgram,
    Applicant,
    ApplicantDocumentVerification,
    CounsellingRound,
    Enquiry,
    SeatMatrix,
)
from app.models.platform import Institution, Role, User, UserRole

FIRST = [
    "Aarav",
    "Diya",
    "Vihaan",
    "Ananya",
    "Arjun",
    "Saanvi",
    "Ishaan",
    "Kavya",
    "Rohan",
    "Meera",
    "Kabir",
    "Ira",
    "Aditya",
    "Myra",
    "Nikhil",
    "Riya",
    "Pranav",
    "Tara",
    "Varun",
    "Zoya",
]
LAST = ["Sharma", "Reddy", "Iyer", "Nair", "Patel", "Gupta", "Rao", "Menon", "Singh", "Das", "Kulkarni", "Joshi"]
CATEGORIES = ["GEN"] * 10 + ["EWS"] * 2 + ["OBC-NCL"] * 6 + ["SC"] * 3 + ["ST"] * 1
BTECH_SEATS = {
    ("STATE", "GEN"): 48,
    ("STATE", "EWS"): 12,
    ("STATE", "OBC-NCL"): 32,
    ("STATE", "SC"): 18,
    ("STATE", "ST"): 8,
    ("PWD", "GEN"): 2,
    ("LATERAL", "GEN"): 8,
    ("LATERAL", "OBC-NCL"): 2,
    ("LATERAL", "SC"): 2,
}
MBA_SEATS = {
    ("STATE", "GEN"): 25,
    ("STATE", "EWS"): 6,
    ("STATE", "OBC-NCL"): 16,
    ("STATE", "SC"): 9,
    ("STATE", "ST"): 4,
}
DOCS = ["photo", "marksheet_12", "marksheet_10"]


@seeder("admissions", after=["students"])
async def seed_admissions(ctx: SeedContext) -> None:
    from seeders.base import _password

    from app.db.session import bind_tenant, set_tenant
    from app.services.admissions.application_service import ApplicationService
    from app.services.auth_service import load_principal

    rng = random.Random(8)
    inst = (await ctx.db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(ctx.db, inst.id)
    await set_tenant(ctx.db, inst.id)
    admin = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "inst.admin"))
    ).scalar_one()
    principal = await load_principal(ctx.db, admin.id)
    current = (
        await ctx.db.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution_id == inst.id,
                AcademicTerm.college_id.is_(None),
                AcademicTerm.is_current.is_(True),
                AcademicTerm.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    year = (await ctx.db.execute(select(AcademicYear).where(AcademicYear.id == current.academic_year_id))).scalar_one()
    programs = {
        p.code: p
        for p in (
            await ctx.db.execute(select(Program).where(Program.institution_id == inst.id, Program.deleted_at.is_(None)))
        ).scalars()
    }
    btech, mba = programs["BTECH-CSE"], programs["MBA"]
    now = datetime.now(UTC)

    cycle, created = await ctx.get_or_create(
        AdmissionCycle,
        defaults={
            "academic_year_id": year.id,
            "name": "UG 2026",
            "level": "ug",
            "application_fee_paise": 100000,
            "opens_at": now - timedelta(days=30),
            "closes_at": now + timedelta(days=60),
            "status": "draft",
            "form_config": {"max_preferences": 3, "strict_eligibility": False, "admission_fee_paise": 2500000},
            "de_reservation_policy": {"convert": {"SC": "GEN", "ST": "GEN"}, "final_round_number": 2},
            "created_by": admin.id,
        },
        institution_id=inst.id,
        slug="ug-2026",
    )
    for program, intake, lateral, source, rules, formula in (
        (
            btech,
            120,
            12,
            "jee",
            {
                "min_qualifying_pct": 60,
                "qualifying_level": "12",
                "subjects": ["PHY", "MAT"],
                "category_relaxation_pct": {"SC": 5, "ST": 5, "PWD": 5},
            },
            [{"field": "entrance_score", "weight": 60, "max": 300}, {"field": "qualifying_pct", "weight": 40}],
        ),
        (
            mba,
            60,
            0,
            "cat",
            {"min_qualifying_pct": 50},
            [{"field": "entrance_score", "weight": 70, "max": 100}, {"field": "qualifying_pct", "weight": 30}],
        ),
    ):
        await ctx.get_or_create(
            AdmissionCycleProgram,
            defaults={
                "institution_id": inst.id,
                "intake": intake,
                "lateral_intake": lateral,
                "entrance_source": source,
                "eligibility_rules": rules,
                "merit_formula": formula,
                "tie_break": ["entrance_score", "dob_asc", "submitted_at"],
            },
            cycle_id=cycle.id,
            program_id=program.id,
            college_id=program.college_id,
        )
        for (quota, category), seats in (BTECH_SEATS if program is btech else MBA_SEATS).items():
            await ctx.get_or_create(
                SeatMatrix,
                defaults={"institution_id": inst.id, "seats": seats, "filled": 0},
                cycle_id=cycle.id,
                program_id=program.id,
                college_id=program.college_id,
                quota=quota,
                category=category,
            )
    if cycle.status == "draft":
        cycle.status = "open"
    for number in (1, 2):
        await ctx.get_or_create(
            CounsellingRound,
            defaults={
                "institution_id": inst.id,
                "name": f"Round {number}",
                "choice_filling_start": now + timedelta(days=61 + 7 * (number - 1)),
                "choice_filling_end": now + timedelta(days=64 + 7 * (number - 1)),
                "reporting_deadline": now + timedelta(days=67 + 7 * (number - 1)),
                "status": "planned",
            },
            cycle_id=cycle.id,
            round_number=number,
        )
    await ctx.db.flush()

    svc = ApplicationService(ctx.db, principal, None, inst.id)
    have = int(
        (
            await ctx.db.execute(select(func.count()).select_from(Applicant).where(Applicant.cycle_id == cycle.id))
        ).scalar_one()
    )
    for i in range(have, 300):
        first, last = FIRST[i % len(FIRST)], LAST[(i * 7) % len(LAST)]
        category = CATEGORIES[i % len(CATEGORIES)]
        lateral = i % 30 == 7  # 10 lateral
        pwd = i % 15 == 3  # 20 PwD
        to_mba = i % 5 == 4
        score = Decimal(rng.randint(90, 290)) if not to_mba else Decimal(rng.randint(40, 99))
        pct = round(rng.uniform(55, 98), 1)
        a, _ = await svc.create_applicant(
            cycle,
            first_name=first,
            last_name=last,
            phone=f"+9190{i:08d}",
            email=f"{first.lower()}.{last.lower()}.{i}@applicants.example.in",
            password=None,
            entry_type="lateral" if lateral else "regular",
            source="online" if i % 4 else "offline",
            create_user=False,
            dob=(now - timedelta(days=365 * (22 if lateral else 18) + i)).date(),
            gender="F" if i % 2 else "M",
            category=category,
            is_pwd=pwd,
            quota_claimed="LATERAL" if lateral else "STATE",
            nationality="Indian",
            domicile_state="Karnataka",
            entrance={
                "exam": "cat" if to_mba else "jee",
                "score": float(score),
                "max_score": 100 if to_mba else 300,
                "year": 2026,
            },
            qualifying_exams=[
                {
                    "level": "diploma" if lateral else "12",
                    "board": "KSEEB",
                    "year": 2026,
                    "pct": pct,
                    "subjects": ["PHY", "CHE", "MAT"],
                }
            ],
        )
        prefs = [(mba.id, mba.college_id)] if to_mba else [(btech.id, btech.college_id)]
        await svc.applicants.replace_preferences(a, prefs)
        status = "verified" if i < 40 else "under_verification" if i < 100 else "submitted" if i < 200 else "draft"
        if status != "draft":
            a.submitted_at = now - timedelta(days=20, minutes=i)
            svc.set_payment(
                a,
                "application",
                {
                    "ref": f"DEMO-APP-{i:04d}",
                    "amount_paise": 100000,
                    "status": "paid" if status != "submitted" else "pending",
                    "provider": "mock",
                    "payer_type": "applicant",
                    "source_type": "application_fee",
                },
            )
            for doc in DOCS:
                ctx.db.add(
                    ApplicantDocumentVerification(
                        institution_id=inst.id,
                        applicant_id=a.id,
                        doc_type=doc,
                        file_url=f"demo://applicants/{a.id}/{doc}.pdf",
                        status="verified" if status == "verified" else "pending",
                        verified_by=admin.id if status == "verified" else None,
                        verified_at=now if status == "verified" else None,
                    )
                )
            a.status = status
        if i % 25 == 0:
            await ctx.db.flush()
        ctx.count("applicants")
    await ctx.db.flush()

    # demo applicant account
    role = (
        await ctx.db.execute(select(Role).where(Role.institution_id == inst.id, Role.slug == "applicant"))
    ).scalar_one()
    user = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "applicant.1"))
    ).scalar_one_or_none()
    if user is None:
        pwd = _password()
        user = User(
            institution_id=inst.id,
            username="applicant.1",
            email=f"applicant.1@{ctx.profile['slug']}.septronuniverse.in",
            phone="+919000099001",
            display_name="Asha Applicant",
            user_type="applicant",
            password_hash=hash_password(pwd),
            is_verified=True,
            must_change_password=False,
            locale="en-IN",
            timezone="Asia/Kolkata",
            valid_to=(cycle.closes_at or now) + timedelta(days=365),
        )
        ctx.db.add(user)
        await ctx.db.flush()
        ctx.db.add(UserRole(institution_id=inst.id, user_id=user.id, role_id=role.id, scope_type="self"))
        ctx.credentials.append(("applicant", "applicant.1", pwd))
        ctx.count("users")
        a, _ = await svc.create_applicant(
            cycle,
            first_name="Asha",
            last_name="Applicant",
            phone="+919000099001",
            email=user.email,
            password=None,
            create_user=False,
            dob=(now - timedelta(days=365 * 18)).date(),
            gender="F",
            category="OBC-NCL",
            quota_claimed="STATE",
            nationality="Indian",
            domicile_state="Karnataka",
            entrance={"exam": "jee", "score": 241.0, "max_score": 300, "year": 2026},
            qualifying_exams=[
                {"level": "12", "board": "CBSE", "year": 2026, "pct": 91.4, "subjects": ["PHY", "CHE", "MAT"]}
            ],
        )
        a.contact = {
            "phone": "+919000099001",
            "email": user.email,
            "guardian_name": "Ravi Applicant",
            "guardian_relation": "father",
            "guardian_phone": "+919000099002",
        }
        a.user_id = user.id
        await svc.applicants.replace_preferences(a, [(btech.id, btech.college_id), (mba.id, mba.college_id)])
        a.submitted_at = now - timedelta(days=10)
        svc.set_payment(
            a,
            "application",
            {
                "ref": "DEMO-APP-A1",
                "amount_paise": 100000,
                "status": "paid",
                "provider": "mock",
                "payer_type": "applicant",
                "source_type": "application_fee",
            },
        )
        for doc in DOCS:
            ctx.db.add(
                ApplicantDocumentVerification(
                    institution_id=inst.id,
                    applicant_id=a.id,
                    doc_type=doc,
                    file_url=f"demo://applicants/{a.id}/{doc}.pdf",
                    status="verified",
                    verified_by=admin.id,
                    verified_at=now,
                )
            )
        a.status = "verified"
        await ctx.db.flush()

    officer = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "admissions"))
    ).scalar_one_or_none()
    stages = [
        "new",
        "new",
        "contacted",
        "contacted",
        "counselled",
        "counselled",
        "applied",
        "applied",
        "admitted",
        "lost",
        "new",
        "contacted",
    ]
    for i, stage in enumerate(stages):
        await ctx.get_or_create(
            Enquiry,
            defaults={
                "name": f"{FIRST[(i + 3) % len(FIRST)]} {LAST[i % len(LAST)]}",
                "email": f"enquiry{i}@example.in",
                "source": ["web", "walk_in", "phone", "referral", "event", "agent"][i % 6],
                "program_interest": ["BTECH-CSE"] if i % 3 else ["MBA"],
                "stage": stage,
                "assigned_to": officer.id if officer and i % 2 == 0 else None,
                "follow_up_on": (now + timedelta(days=i - 3)).date(),
                "notes": [{"at": now.isoformat(), "by": "seed", "text": "Interested in hostel and scholarships"}],
            },
            institution_id=inst.id,
            phone=f"+9188{i:08d}",
        )
    await ctx.db.flush()
