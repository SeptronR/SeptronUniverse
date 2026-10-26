"""``research`` demo seeder (Prompts/30 §30.2) — ``seed_demo_institution.py --only research``.

Enables the Phase 30 professional features (ethics committee, incentives, incubation, API score), links demo users to
teaching staff and then writes: 1,800 publications over the teaching staff (indexing mix, 60 % verified, 20
duplicate-DOI conflicts resolved as co-author tags on one row), 40 patents, 60 funded projects (DST / SERB / AICTE /
UGC / industry; sanctioned ones with a Phase 23 ``grant_ledgers`` row back-linked and utilisation), 25 consultancies
(30 % institution share), 2 ethics committees (IEC / IAEC, bound to committee stubs) with 30 approvals, 120 incentive
requests across statuses, 900 FDP records, 80 awards, 35 MoUs (5 expiring within the alert window) with 60
collaborations, 12 start-ups and API scores for every teaching staff member. Demo users ``research.cell``,
``hod.ece``, ``legal.off``, ``faculty.a`` / ``faculty.b`` (CSE), ``faculty.ece``, ``ethics.chair``, ``ethics.member``
and ``scholar.1`` — credentials go to LOCAL_TEST_CREDENTIALS.md only. ``faculty.a`` has a verified SCI first-author
paper (no incentive yet) and an ORCID iD for the import preview. Idempotent: skipped when publications exist.
"""

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

INDEXING = (("sci", 10), ("scie", 12), ("scopus", 35), ("wos", 8), ("ugc_care", 20), ("other", 10), ("none", 5))
VENUES = {
    "sci": ("Expert Systems with Applications", "IEEE Transactions on Industrial Electronics", "Applied Energy"),
    "scie": ("IEEE Access", "Sensors", "Electronics"),
    "scopus": ("Materials Today: Proceedings", "Journal of Physics: Conference Series", "Procedia Computer Science"),
    "wos": ("Journal of Intelligent & Fuzzy Systems", "Wireless Personal Communications"),
    "ugc_care": ("Indian Journal of Engineering Research", "Journal of the Indian Institute of Science"),
    "other": ("International Journal of Research in Engineering", "IJERT"),
    "none": ("Departmental Proceedings",),
}
TOPICS = (
    "deep learning", "edge computing", "power electronics", "IoT security", "wireless sensor networks",
    "renewable energy", "image segmentation", "natural language processing", "VLSI testing", "smart grids",
    "blockchain", "federated learning", "antenna design", "supply chain analytics", "composite materials",
)  # fmt: skip
AGENCIES = (("DST", "SERB-CRG"), ("SERB", "Core Research Grant"), ("AICTE", "RPS"), ("UGC", "Major Project"),
            ("Industry", "Sponsored research"), ("DBT", "BioCARe"))  # fmt: skip
PARTNERS = (
    ("Infosys", "industry", "India", "placement"), ("Bosch India", "industry", "India", "research"),
    ("IIT Madras", "university", "India", "research"), ("University of Leeds", "university", "UK", "exchange"),
    ("ISRO", "government", "India", "research"), ("Siemens", "industry", "Germany", "academic"),
    ("NIT Trichy", "university", "India", "academic"), ("Tata Elxsi", "industry", "India", "placement"),
    ("Deakin University", "university", "Australia", "exchange"), ("Akshaya Patra", "ngo", "India", "academic"),
)  # fmt: skip


def _pick_weighted(rng: random.Random, items: tuple[tuple[str, int], ...]) -> str:
    return rng.choices([k for k, _ in items], weights=[w for _, w in items])[0]


@seeder("research", after=["hr", "accounting", "facilities", "student_support", "placement"])
async def seed_research(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from seeders.base import _password, _phone

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.security import hash_password
    from app.db.session import bind_tenant, set_tenant
    from app.models.accounting import GrantLedger
    from app.models.hr import FacultyProfile, Staff
    from app.models.platform import Department, Institution, InstitutionSetting, Role, User, UserRole
    from app.models.post_result import Committee
    from app.models.research import (
        Collaboration,
        Consultancy,
        EthicsApproval,
        EthicsCommittee,
        FacultyAward,
        FacultyDevelopment,
        IncubationStartup,
        Mou,
        Patent,
        Publication,
        ResearchIncentive,
        ResearchProject,
    )
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(30)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(Publication).where(Publication.institution_id == inst.id))
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "research.ethics_committee",
        "research.seed_grants_incentives",
        "research.incubation",
        "research.api_score",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 30)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   research: {key} not enabled ({exc})")

    now = datetime.now(UTC)
    today = now.date()
    depts = {
        d.code: d for d in (await db.execute(select(Department).where(Department.institution_id == inst.id))).scalars()
    }
    users = {u.username: u for u in (await db.execute(select(User).where(User.institution_id == inst.id))).scalars()}
    roles = {
        r.slug: r
        for r in (
            await db.execute(select(Role).where(Role.institution_id == inst.id, Role.deleted_at.is_(None)))
        ).scalars()
    }
    teaching = list(
        (
            await db.execute(
                select(Staff)
                .where(Staff.institution_id == inst.id, Staff.staff_category == "teaching", Staff.deleted_at.is_(None))
                .order_by(Staff.employee_id)
            )
        ).scalars()
    )
    if len(teaching) < 8:
        print("   research: fewer than 8 teaching staff — skipped")
        return
    by_dept: dict[uuid.UUID | None, list[Staff]] = {}
    for s in teaching:
        by_dept.setdefault(s.department_id, []).append(s)

    def meta(kind: str, rid: object, value: dict) -> None:
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="research_meta",
                key=f"{kind}:{rid}",
                value=value,
                value_type="json",
            )
        )

    def free_staff(dept_code: str | None) -> Staff | None:
        pool = by_dept.get(depts[dept_code].id, []) if dept_code and dept_code in depts else teaching
        return next((s for s in pool if s.user_id is None), None)

    async def demo_user(
        username: str, name: str, role: str, scope: str, dept_code: str | None, link_staff: bool, label: str
    ) -> tuple[User, Staff | None]:
        u = users.get(username)
        if u is None:
            pwd = _password()
            u = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@{ctx.profile['slug']}.septronuniverse.in",
                phone=_phone(username),
                display_name=name,
                user_type="staff",
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
            ctx.credentials.append((label, username, pwd))
            if role in roles:
                scope_type, scope_id = scope, None
                if scope.startswith("department:"):
                    scope_type, scope_id = "department", depts[scope.split(":", 1)[1]].id
                db.add(
                    UserRole(
                        institution_id=inst.id,
                        user_id=u.id,
                        role_id=roles[role].id,
                        scope_type=scope_type,
                        scope_id=scope_id,
                    )
                )
        staff = (await db.execute(select(Staff).where(Staff.user_id == u.id))).scalar_one_or_none()
        if staff is None and link_staff:
            staff = free_staff(dept_code)
            if staff is not None:
                staff.user_id = u.id
                await db.flush()
        return u, staff

    _, cell = await demo_user(
        "research.cell", "Research Cell", "research_cell", "institution", None, True, "research_cell"
    )
    await demo_user("hod.ece", "Head of Department (ECE)", "hod", "department:ECE", "ECE", True, "hod_ece")
    await demo_user("legal.off", "Legal Officer", "legal_officer", "institution", None, False, "legal_officer")
    _, fa = await demo_user("faculty.a", "Faculty A (CSE)", "faculty", "self", "CSE", True, "faculty_a")
    _, fb = await demo_user("faculty.b", "Faculty B (CSE co-author)", "faculty", "self", "CSE", True, "faculty_b")
    _, fe = await demo_user("faculty.ece", "Faculty (ECE)", "faculty", "self", "ECE", True, "faculty_ece")
    _, chair = await demo_user("ethics.chair", "Ethics Committee Chair", "faculty", "self", None, True, "ethics_chair")
    _, member = await demo_user(
        "ethics.member", "Ethics Committee Member", "faculty", "self", None, True, "ethics_member"
    )
    await demo_user("scholar.1", "Research Scholar One", "research_scholar", "self", None, False, "research_scholar")
    await db.flush()

    def name(s: Staff) -> str:
        return " ".join(x for x in (s.first_name, s.last_name) if x)

    def tag(s: Staff, corresponding: bool = False) -> dict:
        return {"name": name(s), "staff_id": str(s.id), "scholar_id": None, "is_corresponding": corresponding}

    # ---- faculty profiles (ORCID for faculty.a) ---------------------------------------------------------------------------
    profiles = {
        p.staff_id: p
        for p in (await db.execute(select(FacultyProfile).where(FacultyProfile.institution_id == inst.id))).scalars()
    }
    if fa is not None and fa.id in profiles and not profiles[fa.id].orcid:
        profiles[fa.id].orcid = "0000-0002-1825-0097"

    # ---- publications ---------------------------------------------------------------------------------------------------
    total = int(ctx.profile.get("publication_count") or 1800)
    pubs: list[Publication] = []
    cell_staff_id = cell.id if cell else None
    for i in range(total):
        owner = teaching[i % len(teaching)]
        idx = _pick_weighted(rng, INDEXING)
        year = today.year - rng.randint(0, 6)
        co = rng.sample(
            [s for s in by_dept.get(owner.department_id, teaching) if s.id != owner.id] or teaching,
            k=min(2, rng.randint(0, 2)),
        )
        authors = [tag(owner, corresponding=True)] + [tag(s) for s in co] + [{"name": "External Co-author"}]
        rng.shuffle(authors)
        pos = next(k + 1 for k, a in enumerate(authors) if a.get("staff_id") == str(owner.id))
        verified = rng.random() < 0.6
        pt = "conference" if idx in ("scopus", "other") and rng.random() < 0.35 else "journal"
        if rng.random() < 0.03:
            pt = rng.choice(("book", "chapter"))
        p = Publication(
            institution_id=inst.id,
            staff_id=owner.id,
            pub_type=pt,
            title=f"A study of {rng.choice(TOPICS)} for {rng.choice(TOPICS)} ({i + 1})",
            venue=rng.choice(VENUES[idx]),
            year=year,
            doi=f"10.5555/demo.{year}.{i + 1:05d}",
            issn_isbn=f"{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
            indexing=idx,
            impact_factor=Decimal(str(round(rng.uniform(0.5, 9.5), 3))) if idx in ("sci", "scie") else None,
            authors=authors,
            author_position=pos,
            citations=rng.randint(0, 120) if idx != "none" else 0,
            evidence_url=f"https://evidence.example/pub/{i + 1}.pdf",
            is_verified=verified,
            verified_by=cell_staff_id if verified else None,
        )
        db.add(p)
        pubs.append(p)
    await db.flush()
    ctx.count("publications", len(pubs))
    # 20 duplicate-DOI conflicts resolved: the second author's attempt became a co-author claim on the existing row
    for p in rng.sample(pubs, 20):
        other = rng.choice([s for s in teaching if s.id != p.staff_id])
        p.authors = list(p.authors or []) + [tag(other)]
        meta(
            "pub",
            p.id,
            {
                "level": "final" if p.is_verified else "none",
                "source": "manual",
                "history": [{"action": "claimed", "staff_id": str(other.id), "after": "DUPLICATE_DOI"}],
            },
        )
    for p in pubs:
        if not p.is_verified and rng.random() < 0.3:
            meta("pub", p.id, {"level": "department", "source": rng.choice(("manual", "crossref", "orcid"))})
    # faculty.a: a verified SCI first-author paper for the incentive flow
    if fa is not None:
        db.add(
            Publication(
                institution_id=inst.id,
                staff_id=fa.id,
                pub_type="journal",
                title="Federated learning for privacy-preserving campus analytics",
                venue="Expert Systems with Applications",
                year=today.year,
                doi=f"10.5555/demo.sci.{str(fa.id)[:8]}",
                indexing="sci",
                impact_factor=Decimal("8.500"),
                authors=[tag(fa, True)] + ([tag(fb)] if fb else []),
                author_position=1,
                citations=4,
                is_verified=True,
                verified_by=cell_staff_id,
            )
        )
        ctx.count("publications")

    # ---- patents --------------------------------------------------------------------------------------------------------
    for i in range(40):
        s = rng.choice(teaching)
        status = rng.choices(("filed", "published", "granted", "commercialised"), weights=(14, 14, 10, 2))[0]
        filed = today - timedelta(days=rng.randint(60, 2000))
        db.add(
            Patent(
                institution_id=inst.id,
                staff_id=s.id,
                title=f"System and method for {rng.choice(TOPICS)} ({i + 1})",
                application_no=f"20{rng.randint(18, 26)}41{rng.randint(100000, 999999)}",
                country="India",
                filed_on=filed,
                published_on=filed + timedelta(days=540) if status != "filed" else None,
                granted_on=filed + timedelta(days=1100) if status in ("granted", "commercialised") else None,
                status=status,
                co_inventors=[tag(rng.choice(teaching))],
                evidence_url=f"https://evidence.example/patent/{i + 1}.pdf",
            )
        )
    ctx.count("patents", 40)

    # ---- ethics committees --------------------------------------------------------------------------------------------
    committees = []
    for ctype, label in (("iec", "Institutional Ethics Committee"), ("iaec", "Institutional Animal Ethics Committee")):
        stub = Committee(
            institution_id=inst.id,
            name=label,
            committee_type=f"ethics_{ctype}",
            chair_staff_id=chair.id if chair else None,
            constituted_on=today - timedelta(days=400),
            is_active=True,
        )
        db.add(stub)
        await db.flush()
        members = [{"staff_id": str(chair.id), "name": name(chair), "role": "chair"}] if chair else []
        if member is not None:
            members.append({"staff_id": str(member.id), "name": name(member), "role": "member"})
        members += [{"staff_id": str(s.id), "name": name(s), "role": "member"} for s in rng.sample(teaching, 3)]
        ec = EthicsCommittee(
            institution_id=inst.id,
            committee_type=ctype,
            committee_id=stub.id,
            members=members if ctype == "iec" else members[1:],
            registration_no=f"ECR/{rng.randint(100, 999)}/Inst/KA/20{today.year % 100}",
            is_active=True,
        )
        db.add(ec)
        committees.append(ec)
    await db.flush()
    approvals: list[EthicsApproval] = []
    for i in range(30):
        ec = committees[i % 2]
        decided = i < 24
        decision = rng.choice(("approved", "approved", "approved", "revise", "rejected")) if decided else None
        submitted = today - timedelta(days=rng.randint(20, 700))
        a = EthicsApproval(
            institution_id=inst.id,
            ethics_committee_id=ec.id,
            project_title=f"Protocol: {rng.choice(TOPICS)} study {i + 1}",
            pi_staff_id=rng.choice(teaching).id,
            submitted_on=submitted,
            decision=decision,
            approval_no=f"{ec.committee_type.upper()}/{submitted.year}/{i + 1:03d}" if decision == "approved" else None,
            valid_to=submitted + timedelta(days=365) if decision == "approved" else None,
            document_url=f"https://evidence.example/protocol/{i + 1}.pdf",
        )
        db.add(a)
        approvals.append(a)
    await db.flush()
    for a in approvals:
        meta("ethics", a.id, {"category": rng.choice(("exempt", "expedited", "full_review"))})
    ctx.count("ethics_approvals", len(approvals))

    # ---- projects + grant ledgers ---------------------------------------------------------------------------------------
    statuses = ["applied"] * 10 + ["sanctioned"] * 10 + ["ongoing"] * 25 + ["completed"] * 8 + ["closed"] * 7
    for i, status in enumerate(statuses):
        pi = teaching[(i * 7) % len(teaching)]
        agency, scheme = AGENCIES[i % len(AGENCIES)]
        amount = rng.choice((5, 10, 15, 25, 40, 60)) * 10_000_000  # ₹5 L … ₹60 L in paise
        heads = [
            {"name": "equipment", "allocated_paise": amount * 40 // 100, "utilised_paise": 0},
            {"name": "manpower", "allocated_paise": amount * 30 // 100, "utilised_paise": 0},
            {"name": "consumables", "allocated_paise": amount * 15 // 100, "utilised_paise": 0},
            {"name": "travel", "allocated_paise": amount * 5 // 100, "utilised_paise": 0},
            {"name": "contingency", "allocated_paise": amount - amount * 90 // 100, "utilised_paise": 0},
        ]
        start = today - timedelta(days=rng.randint(30, 1100))
        p = ResearchProject(
            institution_id=inst.id,
            pi_staff_id=pi.id,
            co_pi=[{"staff_id": str(rng.choice(teaching).id)}] if rng.random() < 0.5 else [],
            title=f"{rng.choice(TOPICS).title()} for {rng.choice(TOPICS)} — {agency} project {i + 1}",
            funding_agency=agency,
            scheme=scheme,
            sanctioned_paise=amount,
            start_on=start if status != "applied" else None,
            end_on=start + timedelta(days=1095) if status != "applied" else None,
            status=status,
            budget_heads=heads,
            utilisation={"utilised_paise": 0},
        )
        db.add(p)
        await db.flush()
        if status != "applied":
            factor = {"sanctioned": 0.0, "ongoing": rng.uniform(0.2, 0.7), "completed": 0.9, "closed": 0.97}[status]
            received = amount if status in ("completed", "closed") else amount * rng.choice((0, 40, 60)) // 100
            used_heads = [dict(h, utilised_paise=int(h["allocated_paise"] * factor)) for h in heads]
            utilised = min(sum(h["utilised_paise"] for h in used_heads), received)
            g = GrantLedger(
                institution_id=inst.id,
                research_project_id=p.id,
                name=p.title[:160],
                funding_agency=agency,
                sanctioned_paise=amount,
                received_paise=received,
                utilised_paise=utilised,
                budget_heads=used_heads,
                status="closed" if status == "closed" else "active",
            )
            db.add(g)
            await db.flush()
            p.grant_ledger_id, p.received_paise = g.id, received
            p.utilisation = {"utilised_paise": utilised}
            meta(
                "project",
                p.id,
                {
                    "report_periodicity_months": 6,
                    "sanctioned_on": start.isoformat(),
                    "reports": [{"period": "P1", "summary": "Progress as planned"}] if status != "sanctioned" else [],
                },
            )
    ctx.count("research_projects", len(statuses))

    # ---- consultancies --------------------------------------------------------------------------------------------------
    for _ in range(25):
        amount = rng.choice((50_000, 100_000, 200_000, 350_000, 500_000)) * 100
        db.add(
            Consultancy(
                institution_id=inst.id,
                staff_id=rng.choice(teaching).id,
                client=rng.choice(("L&T", "BEL", "Bosch", "KPTCL", "Wipro", "BHEL", "City Corporation")),
                title=f"Testing & consultancy — {rng.choice(TOPICS)}",
                amount_paise=amount,
                institution_share_paise=amount * 30 // 100,
                start_on=today - timedelta(days=rng.randint(10, 900)),
                end_on=today + timedelta(days=rng.randint(-200, 200)),
                status=rng.choice(("ongoing", "completed", "completed")),
            )
        )
    ctx.count("consultancies", 25)

    # ---- incentives -------------------------------------------------------------------------------------------------------
    verified_pubs = [p for p in pubs if p.is_verified and p.indexing in ("sci", "scie", "scopus", "wos", "ugc_care")]
    slab = {
        "sci": (25000, 10000),
        "scie": (20000, 8000),
        "scopus": (10000, 5000),
        "wos": (10000, 5000),
        "ugc_care": (3000, 1000),
    }
    for i in range(120):
        kind = (
            ("publication_incentive", "travel_grant", "seed_grant", "patent_filing_support")[i % 4]
            if i % 2
            else "publication_incentive"
        )
        status = rng.choices(("requested", "approved", "disbursed", "rejected"), weights=(30, 25, 35, 10))[0]
        if kind == "publication_incentive":
            p = verified_pubs[i % len(verified_pubs)]
            first, co = slab[p.indexing or "scopus"]
            amount, staff_id = (first if p.author_position == 1 else co) * 100, p.staff_id
            linked = {"type": "publication", "id": str(p.id), "title": p.title[:120]}
        else:
            amount = {
                "travel_grant": rng.choice((20000, 35000, 50000)),
                "seed_grant": rng.choice((100000, 250000)),
                "patent_filing_support": 30000,
            }[kind] * 100
            staff_id = rng.choice(teaching).id
            linked = {
                "type": "conference" if kind == "travel_grant" else "proposal",
                "id": None,
                "title": f"{kind} {i + 1}",
            }
        r = ResearchIncentive(
            institution_id=inst.id,
            incentive_type=kind,
            staff_id=staff_id,
            amount_paise=amount,
            justification="Demo request",
            linked_entity=linked,
            status=status,
        )
        db.add(r)
    ctx.count("research_incentives", 120)

    # ---- FDP / awards -------------------------------------------------------------------------------------------------------
    for i in range(900):
        s = teaching[i % len(teaching)]
        d = today - timedelta(days=rng.randint(0, 900))
        days = rng.randint(1, 6)
        db.add(
            FacultyDevelopment(
                institution_id=inst.id,
                staff_id=s.id,
                event_type=rng.choice(
                    ("fdp", "fdp", "workshop", "conference", "mooc", "certification", "industry_training")
                ),
                title=f"{rng.choice(('AICTE ATAL FDP', 'NPTEL', 'Workshop', 'STTP', 'Conference'))} on {rng.choice(TOPICS)}",
                organiser=rng.choice(("AICTE", "IIT Bombay", "NITTTR", "IEEE", "Coursera", "In-house")),
                from_on=d,
                to_on=d + timedelta(days=days - 1),
                role=rng.choices(("attended", "organised", "resource_person"), weights=(80, 12, 8))[0],
                hours=Decimal(days * 6),
                certificate_url=f"https://evidence.example/fdp/{i + 1}.pdf",
            )
        )
    ctx.count("faculty_developments", 900)
    for i in range(80):
        db.add(
            FacultyAward(
                institution_id=inst.id,
                staff_id=rng.choice(teaching).id,
                title=rng.choice(
                    ("Best Teacher Award", "Best Paper Award", "Young Scientist Award", "Research Excellence Award")
                ),
                agency=rng.choice(("ISTE", "IEEE", "AICTE", "State Government", "Institution")),
                year=today.year - rng.randint(0, 5),
                level=rng.choice(("institution", "state", "national", "international")),
                evidence_url=f"https://evidence.example/award/{i + 1}.pdf",
            )
        )
    ctx.count("faculty_awards", 80)

    # ---- MoUs / collaborations ---------------------------------------------------------------------------------------------
    mous: list[Mou] = []
    for i in range(35):
        partner, ptype, country, mtype = PARTNERS[i % len(PARTNERS)]
        signed = today - timedelta(days=rng.randint(100, 1500))
        valid_to = (
            today + timedelta(days=rng.randint(10, 80)) if i < 5 else signed + timedelta(days=365 * rng.choice((3, 5)))
        )
        status = "active" if valid_to >= today else "expired"
        m = Mou(
            institution_id=inst.id,
            partner=f"{partner}{'' if i < len(PARTNERS) else f' ({i // len(PARTNERS) + 1})'}",
            partner_type=ptype,
            country=country,
            mou_type=mtype,
            signed_on=signed,
            valid_to=valid_to,
            activities=[{"title": "Guest lectures", "planned": 2}, {"title": "Joint workshop", "planned": 1}],
            document_url=f"https://evidence.example/mou/{i + 1}.pdf",
            coordinator_staff_id=(fa.id if (i == 0 and fa) else rng.choice(teaching).id),
            status=status,
        )
        db.add(m)
        mous.append(m)
    await db.flush()
    for m in mous:
        meta("mou", m.id, {"version": 1})
    for i in range(60):
        m = mous[i % len(mous)]
        d = today - timedelta(days=rng.randint(0, 700))
        db.add(
            Collaboration(
                institution_id=inst.id,
                mou_id=m.id,
                title=f"{rng.choice(('Joint research on', 'Student exchange —', 'Internships —', 'Joint workshop on'))} {rng.choice(TOPICS)}",
                collaboration_type=rng.choice(("joint_research", "exchange", "joint_degree", "internship")),
                participants=[{"staff_id": str(rng.choice(teaching).id)}],
                from_on=d,
                to_on=d + timedelta(days=rng.randint(5, 180)),
                outcomes=["Report submitted"],
            )
        )
    ctx.count("mous", 35)
    ctx.count("collaborations", 60)

    # ---- start-ups --------------------------------------------------------------------------------------------------------
    for i in range(12):
        db.add(
            IncubationStartup(
                institution_id=inst.id,
                name=f"{rng.choice(('Agri', 'Med', 'Edu', 'Fin', 'Robo', 'Green'))}{rng.choice(('Tech', 'Labs', 'AI', 'Works'))} {i + 1}",
                founders=[{"type": rng.choice(("student", "alumni", "faculty")), "name": f"Founder {i + 1}"}],
                sector=rng.choice(("AgriTech", "HealthTech", "EdTech", "FinTech", "CleanTech")),
                stage=rng.choice(("idea", "prototype", "incubated", "funded", "graduated")),
                funding_paise=rng.choice((0, 500000, 2500000, 10000000)) * 100,
                mentor_staff_id=rng.choice(teaching).id,
                registered_on=today - timedelta(days=rng.randint(30, 900)),
                status="active",
            )
        )
    ctx.count("incubation_startups", 12)
    await db.flush()

    # ---- API scores --------------------------------------------------------------------------------------------------------
    from app.services.research.score_service import ScoreService

    svc = ScoreService(db, None, institution_id=inst.id)
    d1, d2 = date(today.year - 1, 4, 1), date(today.year, 3, 31)
    for s in teaching:
        await svc.compute_one(s.id, d1, d2)
    ctx.count("api_scores", len(teaching))
