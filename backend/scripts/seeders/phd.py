"""``phd`` demo seeder (Prompts/31 §31.2) — ``seed_demo_institution.py --only phd``.

Enables the Phase 31 features (all off by default) with the plagiarism / repository adapter keys, marks teaching staff
as recognised guides (cadres professor / associate / assistant — loads near the cadre limits), creates one PhD
programme (``level='phd'``) per department with admission batches and writes 180 scholars across statuses (40
coursework, 90 registered, 20 synopsis / thesis, 15 under evaluation / viva, 10 awarded, 5 discontinued), doctoral
committees and meetings, half-yearly progress reports (3 unsatisfactory chains), fellowships with 12 months of
disbursements, 25 requests, thesis submissions with similarity results, examiner panels with reports, 8 vivas, 10
awards linked to Phase 18 ``degrees_awarded(award_type='phd')`` and ETD uploads (mock handles). Demo users
``guide.a`` (professor, 7 scholars), ``guide.b`` (assistant professor, 4 scholars — at the limit), ``guide.c``,
``dean.res``, ``scholar.1`` (registered, guide.a), ``scholar.new`` (admitted), ``scholar.thesis`` (thesis stage),
``scholar.unsat`` (one unsatisfactory report) — credentials go to LOCAL_TEST_CREDENTIALS.md only. Idempotent: skipped
when research scholars exist.
"""

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

FIRST = ("Aarav", "Diya", "Ishaan", "Meera", "Kabir", "Ananya", "Rohan", "Sneha", "Vikram", "Lakshmi", "Arjun",
         "Kavya", "Siddharth", "Priya", "Nikhil", "Pooja", "Rahul", "Divya", "Karthik", "Nandini")  # fmt: skip
LAST = ("Iyer", "Sharma", "Nair", "Reddy", "Menon", "Gupta", "Rao", "Pillai", "Das", "Kulkarni", "Joshi", "Bose",
        "Patel", "Krishnan", "Verma")  # fmt: skip
AREAS = ("Deep learning for medical imaging", "Power quality in smart grids", "Federated learning at the edge",
         "Antenna arrays for 6G", "Composite materials for aerospace", "NLP for Indian languages",
         "IoT security protocols", "Renewable energy forecasting", "VLSI low-power design",
         "Supply chain optimisation")  # fmt: skip
EXAMINERS = (("Dr. R. Subramanian", "IIT Bombay", "Maharashtra", "India"),
             ("Prof. A. Chatterjee", "Jadavpur University", "West Bengal", "India"),
             ("Dr. M. Fernandes", "University of Lisbon", None, "Portugal"),
             ("Prof. S. Kapoor", "IIT Delhi", "Delhi", "India"),
             ("Dr. L. Wang", "National University of Singapore", None, "Singapore"),
             ("Prof. K. Bhat", "NIT Karnataka", "Karnataka", "India"))  # fmt: skip
PLAN = (("coursework", 40), ("registered", 90), ("synopsis_submitted", 10), ("thesis_submitted", 10),
        ("under_evaluation", 7), ("viva_scheduled", 8), ("awarded", 10), ("discontinued", 5))  # fmt: skip


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


def _periods(reg: date, upto: date) -> list[str]:
    out: list[str] = []
    y, h = reg.year, 1 if reg.month <= 6 else 2
    while True:
        end = date(y, 6, 30) if h == 1 else date(y, 12, 31)
        if end > upto:
            return out
        out.append(f"{y}-H{h}")
        y, h = (y, 2) if h == 1 else (y + 1, 1)


@seeder("phd", after=["hr", "students", "degrees", "research"])
async def seed_phd(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from seeders.base import _password, _phone

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.security import hash_password
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import Batch, Program, ProgramRegulation
    from app.models.degrees import DegreeAwarded
    from app.models.hr import FacultyProfile, Staff
    from app.models.phd import (
        DcMeeting,
        DoctoralCommittee,
        EtdUpload,
        FellowshipDisbursement,
        ResearchScholar,
        ScholarFellowship,
        ScholarProgressReport,
        ScholarRequest,
        ThesisExaminer,
        ThesisSubmission,
        VivaVoce,
    )
    from app.models.platform import Department, Institution, InstitutionSetting, Role, User, UserRole
    from app.models.research import Publication
    from app.models.students import Student, StudentProgramEnrollment
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(31)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(
            select(func.count()).select_from(ResearchScholar).where(ResearchScholar.institution_id == inst.id)
        )
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "integrations.plagiarism",
        "integrations.koha_dspace_shodhganga",
        "phd.core",
        "phd.coursework",
        "phd.dc_meetings",
        "phd.progress_reports",
        "phd.scholar_portal",
        "portals.scholar",
        "phd.fellowships",
        "phd.extensions_guide_change",
        "phd.thesis_plagiarism",
        "phd.external_examiners",
        "phd.viva",
        "phd.etd_upload",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 31)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   phd: {key} not enabled ({exc})")

    now = datetime.now(UTC)
    today = now.date()
    users = {u.username: u for u in (await db.execute(select(User).where(User.institution_id == inst.id))).scalars()}
    roles = {
        r.slug: r
        for r in (
            await db.execute(select(Role).where(Role.institution_id == inst.id, Role.deleted_at.is_(None)))
        ).scalars()
    }
    depts = list((await db.execute(select(Department).where(Department.institution_id == inst.id))).scalars())
    teaching = list(
        (
            await db.execute(
                select(Staff)
                .where(Staff.institution_id == inst.id, Staff.staff_category == "teaching", Staff.deleted_at.is_(None))
                .order_by(Staff.employee_id)
            )
        ).scalars()
    )
    by_dept: dict[uuid.UUID | None, list[Staff]] = {}
    for s in teaching:
        by_dept.setdefault(s.department_id, []).append(s)
    # departments that run a programme and have at least 4 teaching staff
    progs = list(
        (
            await db.execute(select(Program).where(Program.institution_id == inst.id, Program.deleted_at.is_(None)))
        ).scalars()
    )
    host = [d for d in depts if len(by_dept.get(d.id, [])) >= 4 and any(p.department_id == d.id for p in progs)][:4]
    if not host:
        print("   phd: no department with teaching staff and a programme — skipped")
        return

    def meta(kind: str, rid: object, value: dict) -> None:
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="phd_meta",
                key=f"{kind}:{rid}",
                value=value,
                value_type="json",
            )
        )

    async def demo_user(
        username: str, name: str, role: str, scope: str, user_type: str, label: str, scope_id: uuid.UUID | None = None
    ) -> User:
        u = users.get(username)
        if u is None:
            pwd = _password()
            u = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@{ctx.profile['slug']}.septronuniverse.in",
                phone=_phone(username),
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
            ctx.credentials.append((label, username, pwd))
        if role in roles:
            has = (
                await db.execute(select(UserRole).where(UserRole.user_id == u.id, UserRole.role_id == roles[role].id))
            ).first()
            if has is None:
                db.add(
                    UserRole(
                        institution_id=inst.id,
                        user_id=u.id,
                        role_id=roles[role].id,
                        scope_type=scope,
                        scope_id=scope_id,
                    )
                )
        return u

    # ---- guides ----------------------------------------------------------------------------------------------------------
    cadres = (("professor", 8), ("associate", 6), ("assistant", 4))
    guides: list[tuple[Staff, int]] = []
    for d in host:
        for k, gst in enumerate(by_dept[d.id][:6]):
            cadre, cap = cadres[k % 3]
            fp = (
                await db.execute(select(FacultyProfile).where(FacultyProfile.staff_id == gst.id))
            ).scalar_one_or_none()
            if fp is None:
                fp = FacultyProfile(institution_id=inst.id, staff_id=gst.id)
                db.add(fp)
            fp.is_phd, fp.is_phd_guide, fp.cadre = True, True, cadre
            fp.guide_recognition_no = fp.guide_recognition_no or f"RG/{today.year - 5 + k}/{gst.employee_id}"
            guides.append((gst, cap))
    await db.flush()
    ctx.count("phd_guides", len(guides))

    def link(username: str, st: Staff) -> None:
        u = users.get(username)
        if u is not None and st.user_id is None:
            st.user_id = u.id

    def free_guide(cap: int, skip: tuple[Staff, ...] = ()) -> Staff:
        """A guide of the cadre with no linked user yet (so the demo account can be linked to it)."""
        pool = [g for g, c in guides if c == cap and g not in skip]
        return next((g for g in pool if g.user_id is None), pool[0] if pool else guides[0][0])

    guide_a = free_guide(8)  # professor
    guide_b = free_guide(4)  # assistant professor (load limit 4)
    guide_c = free_guide(6, (guide_a, guide_b))  # associate professor
    for uname, label, guide_st in (
        ("guide.a", "research_guide_a", guide_a),
        ("guide.b", "research_guide_b", guide_b),
        ("guide.c", "research_guide_c", guide_c),
    ):
        await demo_user(uname, f"Guide {uname[-1].upper()}", "research_guide", "self", "staff", label)
        link(uname, guide_st)
    await demo_user("dean.res", "Dean (Research)", "dean", "institution", "staff", "dean_research")
    await demo_user("research.cell", "Research Cell", "research_cell", "institution", "staff", "research_cell")
    await db.flush()

    # ---- programmes / batches --------------------------------------------------------------------------------------------
    phd_prog: dict[uuid.UUID, tuple[Program, ProgramRegulation]] = {}
    for d in host:
        base = next(p for p in progs if p.department_id == d.id)
        pr0 = (
            await db.execute(select(ProgramRegulation).where(ProgramRegulation.program_id == base.id).limit(1))
        ).scalar_one_or_none()
        if pr0 is None:
            continue
        prog = Program(
            institution_id=inst.id,
            college_id=base.college_id,
            faculty_id=base.faculty_id,
            department_id=d.id,
            code=f"PHD-{d.code}"[:30],
            name=f"Doctor of Philosophy ({d.name})"[:200],
            degree_name="Doctor of Philosophy",
            specialization=d.name[:120],
            level="phd",
            mode="regular",
            term_pattern="semester",
            duration_years=Decimal("3.0"),
            total_terms=6,
            max_duration_years=Decimal("6.0"),
            sanctioned_intake=20,
            exam_authority=base.exam_authority,
            status="active",
        )
        db.add(prog)
        await db.flush()
        pr = ProgramRegulation(
            institution_id=inst.id,
            program_id=prog.id,
            regulation_id=pr0.regulation_id,
            total_credits_required=Decimal("12.0"),
            status="active",
        )
        db.add(pr)
        await db.flush()
        phd_prog[d.id] = (prog, pr)
    if not phd_prog:
        print("   phd: no programme regulation to reuse — skipped")
        return
    ctx.count("programs", len(phd_prog))
    batches: dict[tuple[uuid.UUID, int], Batch] = {}

    async def batch(d: Department, year: int) -> Batch:
        key = (d.id, year)
        if key not in batches:
            prog, pr = phd_prog[d.id]
            b = Batch(
                institution_id=inst.id,
                college_id=prog.college_id,
                program_id=prog.id,
                program_regulation_id=pr.id,
                admission_year=year,
                code=f"{prog.code}-{year}"[:40],
                name=f"PhD {d.code} {year}",
                expected_graduation_year=year + 3,
            )
            db.add(b)
            await db.flush()
            batches[key] = b
        return batches[key]

    # ---- scholars --------------------------------------------------------------------------------------------------------
    loads: dict[uuid.UUID, int] = {g.id: 0 for g, _ in guides}
    caps = {g.id: cap for g, cap in guides}
    target_load = {guide_a.id: 7, guide_b.id: 4}

    def pick_guide(dept_id: uuid.UUID, closed: bool) -> Staff:
        pool = [g for g, _ in guides if g.department_id == dept_id] or [g for g, _ in guides]
        if closed:  # awarded / discontinued scholars do not count against the load
            return rng.choice(pool)
        for g in pool:
            if g.id in target_load and loads[g.id] < target_load[g.id]:
                return g
        free = [
            g for g in pool if g.id not in target_load and loads[g.id] < caps[g.id] - (1 if rng.random() < 0.5 else 0)
        ]
        return min(free or pool, key=lambda g: loads[g.id])

    host_with_prog = [d for d in host if d.id in phd_prog]
    statuses = [s for s, n in PLAN for _ in range(n)]
    scholars: list[tuple[ResearchScholar, Student, Department]] = []

    for i, status in enumerate(statuses):
        d = host_with_prog[i % len(host_with_prog)]
        prog, pr = phd_prog[d.id]
        years_in = {"coursework": 0, "registered": rng.choice((1, 2, 3)), "discontinued": 2}.get(status, 4)
        adm = date(today.year - years_in, 7, 15) if years_in else today - timedelta(days=rng.randint(30, 200))
        b = await batch(d, adm.year)
        seq = i + 1
        first, last = rng.choice(FIRST), rng.choice(LAST)
        gender = rng.choice(("male", "female"))
        st = Student(
            institution_id=inst.id,
            college_id=prog.college_id,
            registration_number=f"PHD{adm.year % 100:02d}{seq:04d}",
            first_name=first,
            last_name=last,
            dob=date(adm.year - rng.randint(24, 32), rng.randint(1, 12), rng.randint(1, 28)),
            gender=gender,
            email=f"{first.lower()}.{last.lower()}.phd{seq}@example.com",
            phone=f"+9197{rng.randint(10**7, 10**8 - 1)}",
            status="dropped_out" if status == "discontinued" else "active",
        )
        db.add(st)
        await db.flush()
        e = StudentProgramEnrollment(
            institution_id=inst.id,
            college_id=prog.college_id,
            student_id=st.id,
            program_id=prog.id,
            batch_id=b.id,
            program_regulation_id=pr.id,
            department_id=d.id,
            admission_date=adm,
            status="withdrawn" if status == "discontinued" else "active",
        )
        db.add(e)
        await db.flush()
        closed = status in ("awarded", "discontinued")
        g = pick_guide(d.id, closed)
        if not closed:
            loads[g.id] += 1
        reg = None if status == "coursework" else _add_months(adm, rng.randint(6, 11))
        admitted = status == "coursework" and i % 4 == 0
        if status == "coursework":
            cw = "pending" if admitted else "in_progress"
        else:
            cw = "exempted" if rng.random() < 0.1 else "completed"
        mode = "part_time" if rng.random() < 0.15 else "full_time"
        fellowship = "none" if mode == "part_time" else rng.choice(("jrf", "jrf", "srf", "institution", "none"))
        s = ResearchScholar(
            institution_id=inst.id,
            student_program_enrollment_id=e.id,
            guide_staff_id=g.id,
            co_guide_staff_id=None,
            mode=mode,
            fellowship_type=fellowship,
            registration_date=reg,
            coursework_status=cw,
            coursework_exemption_reason="M.Phil coursework completed" if cw == "exempted" else None,
            research_area=rng.choice(AREAS),
            max_duration_end=_add_months(reg, 72 + (24 if gender == "female" else 0)) if reg else None,
            status="admitted" if admitted else status,
        )
        db.add(s)
        scholars.append((s, st, d))
        if i % 50 == 49:
            await db.flush()
    await db.flush()
    ctx.count("research_scholars", len(scholars))
    smeta: dict[uuid.UUID, dict[str, Any]] = {
        s.id: {"timeline": [{"at": now.isoformat(), "action": "seeded", "status": s.status}]} for s, _, _ in scholars
    }

    # demo scholar accounts
    def first_of(status: str, guide: Staff | None = None) -> tuple[ResearchScholar, Student, Department]:
        return next(x for x in scholars if x[0].status == status and (guide is None or x[0].guide_staff_id == guide.id))

    recent_a = [
        x
        for x in scholars
        if x[0].status == "registered"
        and x[0].guide_staff_id == guide_a.id
        and x[0].registration_date is not None
        and x[0].registration_date > _add_months(today, -20)
    ]
    picks = {
        # registered with guide.a, inside the minimum duration (synopsis → 409 MIN_DURATION)
        "scholar.1": (recent_a[0] if recent_a else first_of("registered", guide_a), "research_scholar_1"),
        "scholar.new": (first_of("admitted"), "research_scholar_new"),
        # registered for more than the minimum duration, coursework done, no tagged paper yet (synopsis → 409 first)
        "scholar.thesis": (
            next(
                x
                for x in scholars
                if x[0].status == "registered"
                and x[0].coursework_status == "completed"
                and x[0].registration_date is not None
                and x[0].registration_date <= _add_months(today, -26)
            ),
            "research_scholar_thesis",
        ),
    }
    taken = {p[0][0].id for p in picks.values()}
    picks["scholar.unsat"] = (
        next(
            x
            for x in scholars
            if x[0].status == "registered" and x[0].guide_staff_id != guide_a.id and x[0].id not in taken
        ),
        "research_scholar_unsat",
    )
    for uname, ((_s, st, _), label) in picks.items():
        u = await demo_user(uname, f"{st.first_name} {st.last_name}", "research_scholar", "self", "student", label)
        st.user_id = u.id
    await db.flush()

    # ---- DCs / meetings / progress reports -------------------------------------------------------------------------------
    registered = [x for x in scholars if x[0].registration_date is not None]
    unsat_one = picks["scholar.unsat"][0][0].id
    demo_ids = {p[0][0].id for p in picks.values()}
    unsat_chains = {x[0].id for x in registered if x[0].status == "registered" and x[0].id not in demo_ids}
    unsat_chains = set(list(unsat_chains)[:3])
    n_reports = 0
    for s, _, d in registered:
        pool = [g for g, _ in guides if g.department_id == d.id and g.id != s.guide_staff_id]
        members: list[dict[str, Any]] = [{"staff_id": str(s.guide_staff_id), "role": "convenor"}]
        members += [{"staff_id": str(m.id), "role": "member"} for m in pool[:1]]
        members.append(
            {"external": {"name": "Dr. P. Raman", "affiliation": "Anna University", "email": "p.raman@example.org"}, "role": "external"}
        )  # fmt: skip
        db.add(
            DoctoralCommittee(
                institution_id=inst.id, scholar_id=s.id, members=members, constituted_on=s.registration_date
            )
        )
        assert s.registration_date is not None
        labels = _periods(s.registration_date, today)
        for k in range(1, min(4, len(labels) + 1) + 1):
            met_on = _add_months(s.registration_date, 6 * k - 3)
            if met_on > today:
                break
            db.add(
                DcMeeting(
                    institution_id=inst.id,
                    scholar_id=s.id,
                    meeting_no=k,
                    held_on=met_on,
                    minutes=f"Meeting {k}: progress reviewed.{' Recommended JRF to SRF upgrade.' if k == 4 else ''}",
                    recommendations=[{"id": f"r{k}", "text": "Submit a journal paper", "due_on": _add_months(met_on, 6).isoformat(), "done": k < 3}],
                    status="approved",
                )
            )  # fmt: skip
        for j, label in enumerate(labels):
            rating = "satisfactory"
            if s.id in unsat_chains and j >= len(labels) - 2:
                rating = "unsatisfactory"
            if s.id == unsat_one and j == len(labels) - 1:
                rating = "unsatisfactory"
            is_last = j == len(labels) - 1
            db.add(
                ScholarProgressReport(
                    institution_id=inst.id,
                    scholar_id=s.id,
                    period_label=label,
                    report_url=f"mock://progress/{s.id}/{label}.pdf",
                    summary="Literature review, experiments and a draft paper.",
                    guide_remarks=None if is_last and rng.random() < 0.3 else "Good progress.",
                    dc_rating=None if is_last and rng.random() < 0.3 else rating,
                    status="dc_reviewed" if not is_last or rng.random() < 0.7 else "guide_reviewed",
                    reviewed_at=now,
                )
            )
            n_reports += 1
    for sid in unsat_chains:
        smeta[sid]["cancellation_review"] = {"reason": "unsatisfactory_progress", "streak": 2, "on": today.isoformat()}
    await db.flush()
    ctx.count("doctoral_committees", len(registered))
    ctx.count("scholar_progress_reports", n_reports)
    for s, _, _ in [x for x in registered if x[0].id in unsat_chains]:
        req = ScholarRequest(
            institution_id=inst.id,
            scholar_id=s.id,
            request_type="cancellation_review",
            details={"reason": "unsatisfactory_progress", "streak": 2},
            status="requested",
        )
        db.add(req)
    await db.flush()

    # ---- fellowships (12 months of disbursements) ------------------------------------------------------------------------
    amounts = {"jrf": 3700000, "srf": 4200000, "institution": 2500000}
    n_disb = 0
    for s, _, _ in [x for x in registered if x[0].fellowship_type != "none" and x[0].status not in ("discontinued",)][
        :70
    ]:
        f = ScholarFellowship(
            institution_id=inst.id,
            scholar_id=s.id,
            fellowship_type=s.fellowship_type,
            monthly_paise=amounts.get(s.fellowship_type, 3100000),
            from_on=s.registration_date or today,
            contingency_paise=2000000,
            hra_applicable=rng.random() < 0.6,
            funding_source={"jrf": "UGC", "srf": "CSIR"}.get(s.fellowship_type, "Institution"),
            status="closed" if s.status == "awarded" else "active",
        )
        db.add(f)
        await db.flush()
        for k in range(12, 0, -1):
            mo = _add_months(today.replace(day=1), -k)
            st_ = "paid" if k > 1 else rng.choice(("pending", "approved", "held"))
            d_ = FellowshipDisbursement(
                institution_id=inst.id,
                fellowship_id=f.id,
                month=mo.replace(day=1),
                amount_paise=f.monthly_paise + (int(f.monthly_paise * 0.24) if f.hra_applicable else 0),
                status=st_,
                payroll_ref=f"PAYOUT/{mo:%Y%m}" if st_ == "paid" else None,
                paid_at=now - timedelta(days=30 * k) if st_ == "paid" else None,
            )
            db.add(d_)
            n_disb += 1
        await db.flush()
    ctx.count("fellowship_disbursements", n_disb)

    # ---- requests ----------------------------------------------------------------------------------------------------------
    kinds = ("extension", "change_of_guide", "mode_change", "leave", "coursework_exemption")
    for k in range(25):
        s = registered[(k * 7) % len(registered)][0]
        t = kinds[k % len(kinds)]
        details: dict[str, Any] = {"reason": "Demo request"}
        if t == "extension":
            details["months"] = 6 * (1 + k % 2)
        elif t == "change_of_guide":
            details["new_guide_staff_id"] = str(guide_c.id)
        elif t == "mode_change":
            details["new_mode"] = "part_time" if s.mode == "full_time" else "full_time"
        elif t == "leave":
            details |= {
                "leave_type": "medical",
                "from_on": today.isoformat(),
                "to_on": (today + timedelta(days=30)).isoformat(),
            }
        db.add(
            ScholarRequest(
                institution_id=inst.id,
                scholar_id=s.id,
                request_type=t,
                details=details,
                status=("requested", "approved", "rejected", "in_review")[k % 4],
                decided_at=now if k % 4 in (1, 2) else None,
            )
        )
    await db.flush()
    ctx.count("scholar_requests", 25)

    # ---- thesis / examiners / viva / awards / ETD --------------------------------------------------------------------------
    late = [x for x in scholars if x[0].status in ("synopsis_submitted", "thesis_submitted", "under_evaluation", "viva_scheduled", "awarded")]  # fmt: skip
    n_exam = n_viva = n_award = 0
    for s, st, _d in late:
        assert s.registration_date is not None
        syn = ThesisSubmission(
            institution_id=inst.id,
            scholar_id=s.id,
            stage="synopsis",
            title=f"{s.research_area}: methods and applications",
            file_url=f"mock://thesis/{s.id}/synopsis.pdf",
            submitted_at=datetime.combine(_add_months(s.registration_date, 30), datetime.min.time(), UTC),
            similarity_pct=Decimal(rng.randint(3, 9)),
            plagiarism_report_url=f"mock://plagiarism/{s.id}/synopsis",
            ai_generated_pct=Decimal(rng.randint(0, 5)),
            status="dc_approved" if s.status != "synopsis_submitted" or rng.random() < 0.5 else "plagiarism_checked",
        )
        db.add(syn)
        await db.flush()
        meta("thesis", syn.id, {"ai_declaration": True, "flags": []})
        db.add(
            Publication(
                institution_id=inst.id,
                staff_id=s.guide_staff_id,
                scholar_id=s.id,
                pub_type="journal",
                title=f"{s.research_area} — a study",
                venue="IEEE Access",
                year=today.year - 1,
                indexing="scie",
                authors=[{"name": f"{st.first_name} {st.last_name}", "scholar_id": str(s.id)}, {"name": "Guide", "staff_id": str(s.guide_staff_id)}],
                author_position=1,
                is_verified=True,
            )
        )  # fmt: skip
        if s.status == "synopsis_submitted":
            continue
        th = ThesisSubmission(
            institution_id=inst.id,
            scholar_id=s.id,
            stage="thesis",
            title=f"{s.research_area}: methods and applications",
            file_url=f"mock://thesis/{s.id}/thesis.pdf",
            submitted_at=datetime.combine(_add_months(s.registration_date, 40), datetime.min.time(), UTC),
            similarity_pct=Decimal(
                rng.choice((4, 6, 8, 9) if s.status in ("viva_scheduled", "awarded") else (4, 6, 8, 9, 14))
            ),
            plagiarism_report_url=f"mock://plagiarism/{s.id}/thesis",
            ai_generated_pct=Decimal(rng.randint(0, 6)),
        )
        th.status = "dc_approved" if (th.similarity_pct or 0) <= 10 else "submitted"
        db.add(th)
        await db.flush()
        flags = [] if (th.similarity_pct or 0) <= 10 else ["SIMILARITY_EXCEEDED"]
        if s.status == "thesis_submitted" or th.status != "dc_approved":
            meta("thesis", th.id, {"ai_declaration": True, "flags": flags})
            continue
        recs = []
        for k, (name, aff, state, country) in enumerate(EXAMINERS[:3] if n_exam % 2 else EXAMINERS[3:]):
            done = s.status in ("viva_scheduled", "awarded") or k < 1
            rec = rng.choice(("accept", "minor")) if done else None
            if rec:
                recs.append(rec)
            db.add(
                ThesisExaminer(
                    institution_id=inst.id,
                    thesis_id=th.id,
                    examiner={"name": name, "affiliation": aff, "email": f"examiner{k}.{n_exam}@example.org"},
                    is_external=True,
                    state=state,
                    country=country,
                    invited_at=now - timedelta(days=90),
                    accepted_at=now - timedelta(days=85),
                    report_url=f"mock://reports/{th.id}/{k}.pdf" if done else None,
                    report_received_at=now - timedelta(days=rng.randint(10, 40)) if done else None,
                    recommendation=rec,
                    remuneration_paise=500000 if done else None,
                    status="report_received" if done else "accepted",
                )
            )
            n_exam += 1
        consolidated = "viva_eligible" if len(recs) == 3 else "pending"
        tmeta: dict[str, Any] = {"ai_declaration": True, "flags": flags, "consolidated": consolidated}
        if s.status in ("viva_scheduled", "awarded"):
            held = s.status == "awarded"
            v = VivaVoce(
                institution_id=inst.id,
                thesis_id=th.id,
                scheduled_at=now + timedelta(days=rng.randint(5, 40)) if not held else now - timedelta(days=rng.randint(60, 200)),
                venue_or_link="Seminar Hall 1 / https://meet.example.org/viva",
                panel=[{"name": "Guide", "role": "guide", "staff_id": str(s.guide_staff_id)}, {"name": EXAMINERS[0][0], "role": "external_examiner"}],
                held_at=now - timedelta(days=rng.randint(60, 200)) if held else None,
                result="recommended" if held else None,
                report_url=f"mock://viva/{th.id}.pdf" if held else None,
            )  # fmt: skip
            db.add(v)
            await db.flush()
            meta("viva", v.id, {"open_defence": True})
            n_viva += not held
        if s.status == "awarded":
            on = today - timedelta(days=rng.randint(20, 400))
            e = (
                await db.execute(
                    select(StudentProgramEnrollment).where(
                        StudentProgramEnrollment.id == s.student_program_enrollment_id
                    )
                )
            ).scalar_one()
            da = DegreeAwarded(
                institution_id=inst.id,
                student_program_enrollment_id=e.id,
                award_type="phd",
                degree_name="Doctor of Philosophy",
                specialization=s.research_area[:120] if s.research_area else None,
                date_of_award=on,
                status="council_approved",
            )
            db.add(da)
            await db.flush()
            smeta[s.id]["etd_due_on"] = (on + timedelta(days=30)).isoformat()
            tmeta["award"] = {
                "status": "awarded",
                "date_of_award": on.isoformat(),
                "degree_awarded_id": str(da.id),
                "etd_due_on": (on + timedelta(days=30)).isoformat(),
            }
            n_award += 1
            uploaded = n_award % 3 != 0
            up = EtdUpload(
                institution_id=inst.id,
                thesis_id=th.id,
                repository="shodhganga",
                handle=f"10603/{400000 + n_award}" if uploaded else None,
                uploaded_at=now - timedelta(days=5) if uploaded else None,
                status="uploaded" if uploaded else ("failed" if n_award % 2 else "pending"),
                response={"provider": "mock"},
            )
            db.add(up)
        meta("thesis", th.id, tmeta)
    await db.flush()
    ctx.count("thesis_examiners", n_exam)
    ctx.count("viva_voce", n_viva)
    ctx.count("degrees_awarded", n_award)
    for sid, value in smeta.items():
        meta("scholar", sid, value)
    await db.flush()
