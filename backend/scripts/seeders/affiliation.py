"""``affiliation`` demo seeder (Prompts/34 §34.2) — ``seed_demo_institution.py --type university --only affiliation``.

University tenant ``demo-uni`` only (other profiles are skipped). Enables ``affiliation.core | inspections |
data_submissions | fees | exam_centres``, then writes: the college registry — A stays constituent, B becomes affiliated,
C autonomous (its programmes ``exam_authority=autonomous_college``), D affiliated (submissions late), plus 58 affiliated
(``AF01``…), 4 autonomous (``AU01``…) and 2 constituent (``K1``, ``K2``) colleges with a department and two programmes
each (60 affiliated + 5 autonomous + 3 constituent), profiles (affiliation numbers, AISHE / AICTE ids, geo for centre
allocation, vault documents); the current-year fee schedule; programme approvals for every programme of the
affiliated / autonomous colleges (permanent / provisional with validity, a few expiring); applications for the current
year across statuses (renewals, 4 intake increases, 2 programme additions with inspections and deficiencies, 1
autonomy) with college invoices (``payer_type=college``); data submissions for the current term per college in mixed
states (some returned, most accepted / locked; D's practical marks missing → gated); exam centres for the central
session with assigned colleges and chief superintendents. Demo users ``uni.vc`` (vice_chancellor), ``inspector.1``
(faculty, linked to a staff member), ``college.principal.b`` (college_admin @B), ``college.exam.coord.b`` /
``college.exam.coord.c`` (college_exam_coordinator), ``college.admin.c``, ``college.admin.d`` — credentials go to
LOCAL_TEST_CREDENTIALS.md only. Idempotent: skipped when applications exist.
"""

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select

AFFILIATED_EXTRA = 58
AUTONOMOUS_EXTRA = 4
CONSTITUENT_EXTRA = 2


@seeder("affiliation", after=["governance", "results"])
async def seed_affiliation(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from seeders.base import _password, _phone

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.security import hash_password
    from app.db.session import bind_tenant, set_tenant
    from app.enums.affiliation import FEE_SCHEDULE_TEMPLATE
    from app.models.academic import AcademicTerm, AcademicYear, Program
    from app.models.affiliation import (
        AffiliationApplication,
        AffiliationFeeSchedule,
        AffiliationProgramApproval,
        CollegeDataSubmission,
        ExamCentre,
    )
    from app.models.exams import ExamRegistration, ExamSession
    from app.models.hr import Staff
    from app.models.platform import College, Department, Institution, InstitutionSetting, Role, User, UserRole
    from app.services.feature_service import FeatureService

    if ctx.institution_type != "university":
        print("   affiliation: university profile only — skipped")
        return
    db = ctx.db
    rng = random.Random(34)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(
            select(func.count())
            .select_from(AffiliationApplication)
            .where(AffiliationApplication.institution_id == inst.id)
        )
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "institution.multi_college",
        "affiliation.core",
        "affiliation.inspections",
        "affiliation.fees",
        "affiliation.data_submissions",
        "affiliation.exam_centres",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 34)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   affiliation: {key} not enabled ({exc})")

    now = datetime.now(UTC)
    today = now.date()
    year = (
        await db.execute(
            select(AcademicYear)
            .where(AcademicYear.institution_id == inst.id)
            .order_by(AcademicYear.is_current.desc(), AcademicYear.start_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    term = (
        await db.execute(
            select(AcademicTerm)
            .where(AcademicTerm.institution_id == inst.id, AcademicTerm.is_current.is_(True))
            .order_by(AcademicTerm.college_id.is_(None).desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if year is None or term is None:
        print("   affiliation: no current academic year / term — run the institution / academics seeders; skipped")
        return
    staff = list(
        (
            await db.execute(
                select(Staff)
                .where(Staff.institution_id == inst.id, Staff.deleted_at.is_(None))
                .order_by(Staff.employee_id)
            )
        ).scalars()
    )
    teaching = [s for s in staff if s.staff_category == "teaching"] or staff
    if len(teaching) < 6:
        print("   affiliation: fewer than 6 staff — run the hr seeder first; skipped")
        return

    def meta(kind: str, rid: object, value: dict[str, Any]) -> None:
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="affiliation_meta",
                key=f"{kind}:{rid}",
                value=value,
                value_type="json",
            )
        )

    # ---- colleges ----------------------------------------------------------------------------------------------------
    # include soft-deleted rows: (institution_id, code) is unique regardless of deleted_at
    all_colleges = list((await db.execute(select(College).where(College.institution_id == inst.id))).scalars())
    by_code = {c.code: c for c in all_colleges}
    colleges = {c.code: c for c in all_colleges if c.deleted_at is None}
    base_lat, base_lng = 13.05, 80.22

    def geo(i: int) -> dict[str, Any]:
        return {
            "line1": f"Campus road {i}",
            "city": "Chennai",
            "state": "Tamil Nadu",
            "lat": round(base_lat + rng.uniform(-0.6, 0.6), 4),
            "lng": round(base_lng + rng.uniform(-0.6, 0.6), 4),
        }

    specs: list[tuple[str, str, str]] = [("D", "College of Arts & Commerce", "affiliated")]
    specs += [(f"AF{i:02d}", f"Affiliated College {i:02d}", "affiliated") for i in range(1, AFFILIATED_EXTRA + 1)]
    specs += [(f"AU{i:02d}", f"Autonomous College {i:02d}", "autonomous") for i in range(1, AUTONOMOUS_EXTRA + 1)]
    specs += [(f"K{i}", f"Constituent College {i}", "constituent") for i in range(1, CONSTITUENT_EXTRA + 1)]
    for i, (code, name, ctype) in enumerate(specs, start=1):
        if code in colleges:
            continue
        if code in by_code:  # a demo college soft-deleted by an earlier test run: revive it
            by_code[code].deleted_at = None
            by_code[code].is_active = True
            colleges[code] = by_code[code]
            continue
        c = College(
            institution_id=inst.id,
            code=code,
            name=name,
            college_type=ctype,
            address=geo(i),
            is_active=True,
        )
        db.add(c)
        colleges[code] = c
        ctx.count("colleges")
    await db.flush()
    for code, ctype in (("A", "constituent"), ("B", "affiliated"), ("C", "autonomous")):
        if code in colleges:
            colleges[code].college_type = ctype
    for i, c in enumerate(sorted(colleges.values(), key=lambda x: x.code), start=1):
        if not c.address or "lat" not in (c.address or {}):
            c.address = {**(c.address or {}), **geo(100 + i)}
        if c.college_type in ("affiliated", "autonomous"):
            since = date(2000 + rng.randint(0, 20), 7, 1)
            c.affiliated_since = c.affiliated_since or since
            c.affiliation_number = c.affiliation_number or f"AFF/{since.year}/{c.code}"
            c.aishe_code = c.aishe_code or f"C-{20000 + i}"
            c.aicte_pid = c.aicte_pid or (f"1-{4000000 + i}" if i % 3 == 0 else None)
    await db.flush()

    # departments + programmes for the new colleges
    programs: dict[uuid.UUID, list[Program]] = {}
    for p in (await db.execute(select(Program).where(Program.institution_id == inst.id))).scalars():
        programs.setdefault(p.college_id, []).append(p)
    for code, c in colleges.items():
        if programs.get(c.id):
            continue
        dept = Department(
            institution_id=inst.id, college_id=c.id, code=f"GEN{code}"[:20], name=f"General Studies ({code})"
        )
        db.add(dept)
        await db.flush()
        for pcode, pname, degree, level, intake in (
            ("BSC-CS", "B.Sc. Computer Science", "B.Sc.", "ug", 60),
            ("BCOM", "B.Com.", "B.Com.", "ug", 120),
        ):
            p = Program(
                institution_id=inst.id,
                college_id=c.id,
                department_id=dept.id,
                code=pcode,
                name=pname,
                degree_name=degree,
                level=level,
                duration_years=3,
                total_terms=6,
                sanctioned_intake=intake,
                lateral_intake=0,
                approving_body="university",
                exam_authority="autonomous_college" if c.college_type == "autonomous" else "university",
                status="active",
            )
            db.add(p)
            programs.setdefault(c.id, []).append(p)
            ctx.count("programs")
    await db.flush()
    for c in colleges.values():
        if c.college_type == "autonomous":
            for p in programs.get(c.id, []):
                p.exam_authority = "autonomous_college"

    # ---- fee schedule (current year) --------------------------------------------------------------------------------
    have = {
        r.fee_type
        for r in (
            await db.execute(select(AffiliationFeeSchedule).where(AffiliationFeeSchedule.academic_year_id == year.id))
        ).scalars()
    }
    for fee_type, amount, per_unit in FEE_SCHEDULE_TEMPLATE:
        if fee_type not in have:
            db.add(
                AffiliationFeeSchedule(
                    institution_id=inst.id,
                    academic_year_id=year.id,
                    fee_type=fee_type,
                    amount_paise=amount,
                    per_unit=per_unit,
                )
            )
            ctx.count("affiliation_fee_schedules")
    await db.flush()

    # ---- programme approvals ----------------------------------------------------------------------------------------
    order_seq = 0

    def next_order() -> str:
        nonlocal order_seq
        order_seq += 1
        return f"AO/{today.year}/S{order_seq:04d}"

    gated = [c for c in colleges.values() if c.college_type in ("affiliated", "autonomous")]
    for c in gated:
        permanent = c.affiliated_since is not None and c.affiliated_since.year < 2015
        for j, p in enumerate(programs.get(c.id, [])):
            valid_to = (
                year.start_date.replace(year=year.start_date.year + 5) - timedelta(days=1)
                if permanent
                else year.end_date
            )
            if not permanent and j == 0 and rng.random() < 0.15:
                valid_to = today + timedelta(days=rng.randint(20, 80))  # expiring within the reminder window
            db.add(
                AffiliationProgramApproval(
                    institution_id=inst.id,
                    college_id=c.id,
                    program_id=p.id,
                    academic_year_id=year.id,
                    sanctioned_intake=int(p.sanctioned_intake or 60),
                    lateral_intake=int(p.lateral_intake or 0),
                    approval_status="permanent" if permanent else "provisional",
                    order_no=next_order(),
                    valid_from=year.start_date,
                    valid_to=valid_to,
                    conditions={"seeded": True},
                )
            )
            ctx.count("affiliation_program_approvals")
        meta(
            "college",
            c.id,
            {
                "last_inspection_on": (
                    today - timedelta(days=365 * (4 if c.code == "D" else rng.randint(1, 3)))
                ).isoformat(),
                "documents": [
                    {
                        "key": "aicte_approval",
                        "title": "AICTE extension of approval",
                        "file_url": f"https://files.example.in/{c.code}/eoa.pdf",
                        "valid_to": (today + timedelta(days=rng.randint(-30, 400))).isoformat(),
                        "uploaded_at": now.isoformat(),
                    },
                    {
                        "key": "naac",
                        "title": "NAAC certificate",
                        "file_url": f"https://files.example.in/{c.code}/naac.pdf",
                        "valid_to": (today + timedelta(days=rng.randint(100, 1500))).isoformat(),
                        "uploaded_at": now.isoformat(),
                    },
                ],
            },
        )
    await db.flush()

    # ---- users ------------------------------------------------------------------------------------------------------
    users = {u.username: u for u in (await db.execute(select(User).where(User.institution_id == inst.id))).scalars()}
    roles = {
        r.slug: r
        for r in (
            await db.execute(select(Role).where(Role.institution_id == inst.id, Role.deleted_at.is_(None)))
        ).scalars()
    }

    async def demo_user(
        username: str, name: str, role: str, scope: str, scope_id: uuid.UUID | None = None, *, label: str | None = None
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
            ctx.credentials.append((label or role, username, pwd))
        if role in roles:
            has = (
                await db.execute(
                    select(UserRole).where(
                        UserRole.user_id == u.id, UserRole.role_id == roles[role].id, UserRole.scope_id == scope_id
                    )
                )
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

    await demo_user("uni.vc", "Vice Chancellor", "vice_chancellor", "institution", label="vice_chancellor_uni")
    inspector = await demo_user("inspector.1", "Inspection Committee Member", "faculty", "self", label="inspector")
    await demo_user(
        "college.principal.b",
        "Principal (College B)",
        "college_admin",
        "college",
        colleges["B"].id,
        label="college_principal_b",
    )
    await demo_user(
        "college.exam.coord.b",
        "Exam Coordinator (B)",
        "college_exam_coordinator",
        "college",
        colleges["B"].id,
        label="college_exam_coordinator_b",
    )
    await demo_user(
        "college.admin.c", "College Admin (C)", "college_admin", "college", colleges["C"].id, label="college_admin_c"
    )
    await demo_user(
        "college.exam.coord.c",
        "Exam Coordinator (C)",
        "college_exam_coordinator",
        "college",
        colleges["C"].id,
        label="college_exam_coordinator_c",
    )
    await demo_user(
        "college.admin.d", "College Admin (D)", "college_admin", "college", colleges["D"].id, label="college_admin_d"
    )
    await db.flush()
    linked = {s.user_id for s in staff if s.user_id}
    insp_staff = next((s for s in teaching if s.user_id == inspector.id), None)
    if insp_staff is None:
        insp_staff = next((s for s in teaching if s.user_id is None), teaching[0])
        if insp_staff.user_id is None and inspector.id not in linked:
            insp_staff.user_id = inspector.id
    colleges["B"].principal_staff_id = colleges["B"].principal_staff_id or teaching[1].id
    await db.flush()

    # ---- applications -------------------------------------------------------------------------------------------------
    from app.schemas.fees import InvoiceCreate, InvoiceItemIn
    from app.services.fees.invoice_service import InvoiceService

    inv_svc = InvoiceService(db, None, None, inst.id)
    app_seq = 0
    schedule = {
        r.fee_type: r
        for r in (
            await db.execute(select(AffiliationFeeSchedule).where(AffiliationFeeSchedule.academic_year_id == year.id))
        ).scalars()
    }

    async def invoice(a: AffiliationApplication, fee_types: list[str], units: int, paid: bool) -> uuid.UUID | None:
        items = []
        for t in fee_types:
            s = schedule.get(t)
            if s is None:
                continue
            n = units if s.per_unit != "flat" else 1
            items.append(
                InvoiceItemIn(
                    description=f"{t.replace('_', ' ').title()} ({n})",
                    amount_paise=int(s.amount_paise) * n,
                    head_code="AFFIL",
                )
            )
        if not items:
            return None
        try:
            async with db.begin_nested():
                inv = await inv_svc.create_invoice(
                    InvoiceCreate(
                        payer_type="college",
                        payer_id=a.college_id,
                        source_type="affiliation_application",
                        source_id=a.id,
                        description="Affiliation application fee",
                        items=items,
                        due_date=today + timedelta(days=30),
                    ),
                    notify=False,
                )
                inv.college_id = a.college_id
                if paid:
                    inv.paid_paise, inv.balance_paise, inv.status = inv.total_paise, 0, "paid"
                await db.flush()
                ctx.count("fee_invoices")
                return inv.id
        except Exception as exc:  # noqa: BLE001 - fee heads missing: the application keeps a pending fee
            print(f"   affiliation: invoice skipped ({str(exc)[:80]})")
            return None

    async def application(
        c: College,
        app_type: str,
        status: str,
        progs: list[dict[str, Any]],
        *,
        fee_types: list[str],
        units: int = 1,
        inspection: bool = False,
        deficiencies: list[dict[str, Any]] | None = None,
        decided: bool = False,
    ) -> AffiliationApplication:
        nonlocal app_seq
        app_seq += 1
        number = f"AFF/{today.year}/{app_seq:04d}"
        a = AffiliationApplication(
            institution_id=inst.id,
            college_id=c.id,
            academic_year_id=year.id,
            application_type=app_type,
            programs=progs,
            documents={
                k: f"https://files.example.in/{c.code}/{k}.pdf"
                for k in (
                    "faculty_roster",
                    "finance",
                    "anti_ragging",
                    "labs_library",
                    "aicte_approval",
                    "noc_state",
                    "land_building",
                    "fee_regulatory",
                    "autonomy_report",
                    "naac_certificate",
                    "migration_plan",
                )
            },
            status=status,
        )
        db.add(a)
        await db.flush()
        paid = status not in ("draft", "submitted")
        a.fee_invoice_id = await invoice(a, fee_types, units, paid) if status != "draft" else None
        m: dict[str, Any] = {
            "number": number,
            "inspection_required": inspection,
            "fee_settled": paid,
            "timeline": [{"at": now.isoformat(), "by": None, "action": "seeded", "status": status}],
        }
        if inspection and status not in ("draft", "submitted", "fee_paid", "scrutiny"):
            members = [insp_staff.id, *[s.id for s in rng.sample(teaching, 2) if s.id != insp_staff.id]]
            a.inspection_committee = {
                "staff_ids": [str(x) for x in members],
                "external": [{"name": "Dr. External Expert", "organisation": "AICTE panel"}],
                "convenor_staff_id": str(members[0]),
                "mode": "physical",
                "round": 1,
            }
            a.inspection_on = (
                today + timedelta(days=7) if status == "inspection_scheduled" else today - timedelta(days=12)
            )
            m["rounds"] = 1
            if status != "inspection_scheduled":
                a.inspection_report_url = f"https://files.example.in/{c.code}/inspection-r1.pdf"
                m["reports"] = [{"round": 1, "report_url": a.inspection_report_url, "recommendation": "conditional"}]
                m["recommendation"] = "conditional"
        if deficiencies:
            a.deficiencies = deficiencies
        if decided:
            a.order_no = next_order()
            a.order_url = f"/api/v1/affiliation/applications/{a.id}/order.pdf"
            m["decision"] = {
                "decision": status,
                "conditions": ["Fill faculty vacancies within six months"] if status == "conditional" else [],
                "order_no": a.order_no,
                "order_date": (today - timedelta(days=rng.randint(5, 40))).isoformat(),
                "order_url": a.order_url,
            }
        meta("app", a.id, m)
        ctx.count("affiliation_applications")
        return a

    def prog_rows(c: College, *, increase: int = 0) -> list[dict[str, Any]]:
        return [
            {
                "program_id": str(p.id),
                "program_code": p.code,
                "program_name": p.name,
                "current_intake": int(p.sanctioned_intake or 60),
                "requested_intake": int(p.sanctioned_intake or 60) + increase,
                "lateral_intake": 0,
            }
            for p in programs.get(c.id, [])[:1]
        ]

    affiliated = sorted([c for c in gated if c.college_type == "affiliated"], key=lambda x: x.code)
    renewal_states = ["approved"] * 10 + ["compliance_pending"] * 3 + ["fee_paid"] * 4 + ["submitted"] * 3
    for c, st in zip([x for x in affiliated if x.code not in ("B", "D")][:20], renewal_states, strict=False):
        await application(c, "renewal", st, prog_rows(c), fee_types=["continuation"], decided=st == "approved")
    increase = [colleges["B"], *[x for x in affiliated if x.code.startswith("AF")][20:23]]
    defs_open = [
        {
            "id": "D1-1",
            "area": "Laboratories",
            "observation": "Lab equipment short of the AICTE norm",
            "severity": "critical",
            "status": "open",
            "due_on": (today + timedelta(days=18)).isoformat(),
            "round": 1,
        },
        {
            "id": "D1-2",
            "area": "Library",
            "observation": "Journals subscription lapsed",
            "severity": "minor",
            "status": "responded",
            "due_on": (today + timedelta(days=18)).isoformat(),
            "response_text": "Renewed for 2026",
            "evidence_url": "https://files.example.in/evidence/journals.pdf",
            "round": 1,
        },
    ]
    for c, st in zip(increase, ["scrutiny", "inspection_scheduled", "inspected", "approved"], strict=False):
        await application(
            c,
            "intake_increase",
            st,
            prog_rows(c, increase=60),
            fee_types=["intake_increase", "inspection"],
            units=60,
            inspection=True,
            deficiencies=defs_open if st == "inspected" else None,
            decided=st == "approved",
        )
    for c, st in zip(
        [x for x in affiliated if x.code.startswith("AF")][23:25], ["inspected", "compliance_pending"], strict=False
    ):
        new_prog = [
            {
                "new": {
                    "code": "MCA",
                    "name": "Master of Computer Applications",
                    "level": "pg",
                    "duration_years": 2,
                    "total_terms": 4,
                    "intake": 60,
                },
                "program_code": "MCA",
                "program_name": "Master of Computer Applications",
                "requested_intake": 60,
                "lateral_intake": 0,
            }
        ]
        await application(
            c,
            "program_addition",
            st,
            new_prog,
            fee_types=["affiliation", "inspection"],
            inspection=True,
            deficiencies=[{**d, "status": "closed" if st == "compliance_pending" else d["status"]} for d in defs_open],
        )
    autonomy_college = next(x for x in affiliated if x.code == "AF01")
    await application(
        autonomy_college,
        "autonomy",
        "inspection_scheduled",
        [],
        fee_types=["recognition", "inspection"],
        inspection=True,
    )
    await db.flush()

    # ---- data submissions (current term) ----------------------------------------------------------------------------
    # the central session with the most registrations (the regular end-semester session, not the arrear one)
    central = (
        await db.execute(
            select(ExamSession)
            .outerjoin(ExamRegistration, ExamRegistration.exam_session_id == ExamSession.id)
            .where(
                ExamSession.institution_id == inst.id,
                ExamSession.college_id.is_(None),
                ExamSession.deleted_at.is_(None),
            )
            .group_by(ExamSession.id)
            .order_by(func.count(ExamRegistration.id).desc(), ExamSession.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    exam_types = ["cia_marks", "attendance_eligibility", "practical_marks", "exam_registrations"]
    other_types = ["student_registrations", "course_registrations", "internal_faculty_list"]
    due = {t: (term.start_date + timedelta(days=30)) for t in other_types}
    li = term.last_instruction_date or term.end_date
    due.update(
        {
            "cia_marks": li + timedelta(days=7),
            "attendance_eligibility": li + timedelta(days=3),
            "practical_marks": li + timedelta(days=10),
            "exam_registrations": li + timedelta(days=2),
        }
    )
    for c in sorted(gated, key=lambda x: x.code):
        types = other_types + ([] if c.college_type == "autonomous" else exam_types)
        for t in types:
            if c.code == "D" and t == "practical_marks":
                continue  # D: practical marks missing → gated for the central session
            roll = rng.random()
            status = (
                "locked"
                if roll < 0.45
                else "accepted"
                if roll < 0.8
                else "verified"
                if roll < 0.88
                else "returned"
                if roll < 0.95
                else "submitted"
            )
            if c.code == "B":
                status = "locked"
            exists = (
                await db.execute(
                    select(CollegeDataSubmission).where(
                        CollegeDataSubmission.college_id == c.id,
                        CollegeDataSubmission.term_id == term.id,
                        CollegeDataSubmission.submission_type == t,
                    )
                )
            ).scalar_one_or_none()
            s = exists or CollegeDataSubmission(
                institution_id=inst.id, college_id=c.id, term_id=term.id, submission_type=t
            )
            s.status = status
            s.exam_session_id = central.id if central is not None and t in exam_types else None
            s.record_count = rng.randint(80, 900)
            s.submitted_at = now - timedelta(days=rng.randint(1, 20))
            s.submitted_by = None
            if status in ("verified", "accepted", "locked"):
                s.verified_at = s.submitted_at + timedelta(days=1)
            if status == "locked":
                s.locked_at = s.submitted_at + timedelta(days=2)
            if status == "returned":
                s.remarks = "Marks for two papers missing — resubmit"
            if exists is None:
                db.add(s)
                ctx.count("college_data_submissions")
            await db.flush()
            late = c.code == "D" or rng.random() < 0.15
            meta(
                "sub",
                s.id,
                {
                    "version": 2 if status == "returned" and rng.random() < 0.5 else 1,
                    "source": "file" if rng.random() < 0.2 else "system",
                    "due_on": due[t].isoformat(),
                    "late": late,
                    "returns": 1 if status == "returned" else 0,
                },
            )

    # ---- exam centres (central session) -----------------------------------------------------------------------------
    if central is not None:
        centre_colleges = [colleges["A"], colleges["B"], *[x for x in affiliated if x.code.startswith("AF")][:6]]
        centres = []
        for i, c in enumerate(centre_colleges, start=1):
            code = f"EC{i:02d}"
            exists = (
                await db.execute(
                    select(ExamCentre).where(ExamCentre.exam_session_id == central.id, ExamCentre.centre_code == code)
                )
            ).scalar_one_or_none()
            if exists is not None:
                centres.append(exists)
                continue
            cs = teaching[(i + 2) % len(teaching)]
            ec = ExamCentre(
                institution_id=inst.id,
                exam_session_id=central.id,
                college_id=c.id,
                centre_code=code,
                chief_superintendent_staff_id=cs.id,
                capacity=500 if c.code == "B" else rng.choice([300, 400, 600]),
                assigned_colleges=[],
            )
            c.is_exam_centre, c.exam_centre_code = True, c.exam_centre_code or code
            db.add(ec)
            centres.append(ec)
            ctx.count("exam_centres")
        await db.flush()
        others = [c for c in affiliated if c not in centre_colleges]
        for k, c in enumerate(others):
            ec = centres[k % len(centres)]
            ec.assigned_colleges = [*(ec.assigned_colleges or []), str(c.id)]
        regs = (
            await db.execute(
                select(func.count()).select_from(ExamRegistration).where(ExamRegistration.exam_session_id == central.id)
            )
        ).scalar_one()
        print(f"   affiliation: central session {central.name} — {len(centres)} centres, {regs} registrations")
    await db.flush()
    print(
        f"   affiliation: {len(gated)} affiliated / autonomous colleges, "
        f"{sum(1 for c in colleges.values() if c.college_type == 'constituent')} constituent"
    )
