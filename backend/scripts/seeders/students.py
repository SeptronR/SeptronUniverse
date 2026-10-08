"""``students`` demo seeder (Prompts/07 §07.2 / §07.11 step 1) — ``seed_demo_institution.py --type university --only students``.

On top of ``hr`` (programmes, R2024, batches 2024/2025 with sections, advisor / HOD staff rows, the current year):

* the two past academic years (2024-25, 2025-26, institution-wide, closed) so term records carry real history;
* batches moved to their real term (B.Tech CSE 2024 → 5 with sections A–D, 2025 → 3; MBA 2025 → 3; MBA 2024 → 4,
  ``graduating``) and ``advisor.1`` as class advisor of 2025-BTECH-CSE section B;
* **400 students** through ``StudentService.create_record`` (registration numbers from the ``regno:{yyyy}:{programme}``
  sequences, users, enrolments, current-term records, guardians, consent records) — B.Tech CSE 2024: 200 active
  (2 with 5 open arrears → detained by the promotion) + 2 on break after term 4 (84 credits — the NEP-exit fixture);
  B.Tech CSE 2025: 118 active + 2 exited after term 2 with a certificate; MBA 2025: 60; MBA 2024: 18 completed
  (awaiting the degree, Phase 18). Past term records carry SGPA / CGPA / credits; a few students are on warning /
  probation;
* ``student.1`` is a 2025 B.Tech CSE student in section B (advisee of ``advisor.1``) with guardian ``parent.1``
  (portal access, consent on) and a pending ``conduct`` undertaking; the new demo user ``parent.noconsent`` guards a
  student whose ``guardian_portal_consent`` is off; the new demo user ``principal`` (vice_chancellor) approves step 2
  of ``students.transfer`` — both written to ``LOCAL_TEST_CREDENTIALS.md`` (``parent_noconsent`` /
  ``vice_chancellor``);
* undertakings (``anti_ragging`` + ``conduct``) accepted for the current year, documents for 20 students (one expiring),
  5 holds (one released), 3 credit transfers (2 approved, 1 waiting for the HOD in ``students.credit_transfer``).

Idempotent: students are keyed by ``enrolment_number`` ``DEMO0001…``; demo users, sections, terms and holds by their
natural keys. Services run as ``inst.admin`` (audit rows and outbox events as for the API; notifications off).
"""

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select, text

from app.core.security import hash_password
from app.models.academic import AcademicTerm, AcademicYear, Batch, BatchSection, Program
from app.models.curriculum import Course
from app.models.hr import Staff
from app.models.platform import Institution, Role, User, UserRole
from app.models.students import (
    CreditTransfer,
    Student,
    StudentDocument,
    StudentGuardian,
    StudentHold,
    StudentProgramEnrollment,
    StudentTermRecord,
    StudentUndertaking,
)

FIRST_M = [
    "Aarav",
    "Vihaan",
    "Arjun",
    "Sai",
    "Reyansh",
    "Krishna",
    "Ishaan",
    "Rohan",
    "Kabir",
    "Aditya",
    "Rahul",
    "Karthik",
    "Nikhil",
    "Pranav",
    "Siddharth",
    "Varun",
    "Yash",
    "Harsh",
    "Manish",
    "Tejas",
]
FIRST_F = [
    "Ananya",
    "Diya",
    "Aadhya",
    "Saanvi",
    "Ira",
    "Myra",
    "Kavya",
    "Meera",
    "Priya",
    "Riya",
    "Sneha",
    "Pooja",
    "Lakshmi",
    "Nandini",
    "Divya",
    "Shreya",
    "Ishita",
    "Tanvi",
    "Aditi",
    "Neha",
]
LAST = [
    "Sharma",
    "Verma",
    "Iyer",
    "Reddy",
    "Nair",
    "Patel",
    "Gupta",
    "Rao",
    "Menon",
    "Das",
    "Mehta",
    "Kulkarni",
    "Joshi",
    "Pillai",
    "Banerjee",
    "Chatterjee",
    "Shetty",
    "Hegde",
    "Naidu",
    "Bose",
]
CATEGORIES = ["GEN"] * 9 + ["OBC-NCL"] * 5 + ["SC"] * 3 + ["ST"] * 1 + ["EWS"] * 2
QUOTAS = ["STATE", "STATE", "ALL_INDIA", "MANAGEMENT"]
BLOOD = ["O+", "B+", "A+", "AB+", "O-", "B-", "A-"]
EXTRA_USERS = [
    # (username, display name, role slug, credential label)
    ("parent.noconsent", "Parent (no consent)", "parent", "parent_noconsent"),
    ("principal", "Principal", "vice_chancellor", "vice_chancellor"),
]
# (programme, admission year, count, plan)
PLAN: list[tuple[str, int, int, str]] = [
    ("BTECH-CSE", 2024, 202, "cse2024"),
    ("BTECH-CSE", 2025, 120, "cse2025"),
    ("MBA", 2025, 60, "mba2025"),
    ("MBA", 2024, 18, "mba2024"),
]
SGPA_TRACK = [Decimal("8.1"), Decimal("7.6"), Decimal("7.9"), Decimal("8.3")]


def _luhn_apaar(seed: int) -> str:
    base = f"9{seed:010d}"[-11:]
    total = 0
    for i, ch in enumerate(reversed(base + "0")):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    return base + str((10 - total % 10) % 10)


_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]
_INV = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]


def _aadhaar(seed: int) -> str:
    """A Verhoeff-valid demo Aadhaar number (never a real one: the 2xxx… block below is synthetic)."""
    base = f"2{seed:010d}"[-11:]
    c = 0
    for i, ch in enumerate(reversed(base)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return base + str(_INV[c])


def _phone(seed: str) -> str:
    return f"+9197{int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % 10**8:08d}"


@seeder("students", after=["hr"])
async def seed_students(ctx: SeedContext) -> None:
    from seeders.base import _password

    from app.db.session import bind_tenant, set_tenant
    from app.services.auth_service import load_principal

    inst = (await ctx.db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(ctx.db, inst.id)
    await set_tenant(ctx.db, inst.id)
    roles = {
        r.slug: r
        for r in (
            await ctx.db.execute(select(Role).where(Role.institution_id == inst.id, Role.deleted_at.is_(None)))
        ).scalars()
    }
    for username, display, slug, label in EXTRA_USERS:
        user = (
            await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == username))
        ).scalar_one_or_none()
        if user is None:
            pwd = _password()
            user = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@{ctx.profile['slug']}.septronuniverse.in",
                phone=_phone(username),
                display_name=display,
                user_type="guardian" if slug == "parent" else "staff",
                password_hash=hash_password(pwd),
                is_verified=True,
                must_change_password=False,
                locale="en-IN",
                timezone="Asia/Kolkata",
            )
            ctx.db.add(user)
            await ctx.db.flush()
            ctx.count("users")
            ctx.credentials.append((label, username, pwd))
        if (
            await ctx.db.execute(
                select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == roles[slug].id)
            )
        ).first() is None:
            scope = "self" if slug == "parent" else "institution"
            ctx.db.add(UserRole(institution_id=inst.id, user_id=user.id, role_id=roles[slug].id, scope_type=scope))
            ctx.count("user_roles")
    await ctx.db.flush()

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
    ).scalar_one_or_none()
    if current is None:
        raise SystemExit("run --only institution first (no current institution-wide academic term)")
    year = (await ctx.db.execute(select(AcademicYear).where(AcademicYear.id == current.academic_year_id))).scalar_one()
    start_year = year.start_date.year
    past = await _past_terms(ctx, inst.id, start_year)  # {(year, "odd"|"even"): term}
    odd = current.term_type == "odd"

    programs = {
        p.code: p
        for p in (
            await ctx.db.execute(select(Program).where(Program.institution_id == inst.id, Program.deleted_at.is_(None)))
        ).scalars()
    }
    if "BTECH-CSE" not in programs or "MBA" not in programs:
        raise SystemExit("run --only academics first (BTECH-CSE / MBA are missing)")
    batches: dict[tuple[str, int], Batch] = {}
    for code, admission_year, _, _ in PLAN:
        batch = (
            await ctx.db.execute(
                select(Batch).where(
                    Batch.program_id == programs[code].id,
                    Batch.admission_year == admission_year,
                    Batch.entry_type == "regular",
                    Batch.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if batch is None:
            raise SystemExit(f"batch {admission_year} of {code} is missing — run --only academics first")
        term_now = (start_year - admission_year) * 2 + (1 if odd else 2)
        total = programs[code].total_terms
        if term_now > total:
            batch.current_term_number, batch.status = total, "graduating"
        else:
            batch.current_term_number = term_now
        batches[(code, admission_year)] = batch
    await ctx.db.flush()
    cse24 = batches[("BTECH-CSE", 2024)]
    for name in ("C", "D"):
        if (
            await ctx.db.execute(
                select(BatchSection).where(BatchSection.batch_id == cse24.id, BatchSection.name == name)
            )
        ).scalar_one_or_none() is None:
            ctx.db.add(BatchSection(institution_id=inst.id, batch_id=cse24.id, name=name, capacity=60))
            ctx.count("batch_sections")
    await ctx.db.flush()
    await _advisor(ctx, principal, inst.id, batches[("BTECH-CSE", 2025)])

    existing = {
        e
        for (e,) in (
            await ctx.db.execute(
                select(Student.enrolment_number).where(
                    Student.institution_id == inst.id, Student.enrolment_number.like("DEMO%")
                )
            )
        ).all()
    }
    if len(existing) >= sum(n for _, _, n, _ in PLAN):
        print("   students already seeded")
        await _extras(ctx, principal, inst, batches, past, current)
        return

    from app.schemas.students import GuardianIn, StudentCreate
    from app.services.student_service import StudentService

    service = StudentService(ctx.db, principal, None, inst.id)
    pw_hash = hash_password(_password() + "x")  # demo student accounts: unknown password (student.1 keeps its own)
    users = {
        u.username: u for u in (await ctx.db.execute(select(User).where(User.institution_id == inst.id))).scalars()
    }
    serial = 0
    for code, admission_year, count, plan in PLAN:
        batch = batches[(code, admission_year)]
        sections = list(
            (
                await ctx.db.execute(
                    select(BatchSection).where(BatchSection.batch_id == batch.id).order_by(BatchSection.name)
                )
            ).scalars()
        )
        for n in range(count):
            serial += 1
            marker = f"DEMO{serial:04d}"
            if marker in existing:
                continue
            female = serial % 2 == 0
            first = (FIRST_F if female else FIRST_M)[serial % 20]
            last = LAST[(serial * 7) % 20]
            is_student1 = plan == "cse2025" and n == 0
            section = sections[n % len(sections)] if sections else None
            if plan == "cse2025":
                section = sections[1] if is_student1 or n % 2 == 1 else sections[0]
            body = StudentCreate(
                first_name=first if not is_student1 else "Student",
                last_name=last if not is_student1 else "One",
                dob=date(admission_year - 18, 1 + serial % 12, 1 + serial % 27),
                gender="F" if female else "M",
                blood_group=BLOOD[serial % len(BLOOD)],
                category=CATEGORIES[serial % len(CATEGORIES)],
                admission_quota=QUOTAS[serial % len(QUOTAS)],
                phone=_phone(marker),
                email=f"{first.lower()}.{last.lower()}.{serial}@students.{ctx.profile['slug']}.septronuniverse.in",
                current_address={"line1": f"{serial} MG Road", "city": "Bengaluru", "state": "Karnataka"},
                permanent_address={"line1": f"{serial} Station Road", "city": "Mysuru", "state": "Karnataka"},
                emergency_contact={"name": f"{FIRST_M[serial % 20]} {last}", "phone": _phone(marker + "f")},
                aadhaar=_aadhaar(100000 + serial) if serial % 3 == 0 or is_student1 else None,
                apaar_id=_luhn_apaar(500000 + serial),
                program_id=programs[code].id,
                batch_id=batch.id,
                section_id=section.id if section else None,
                roll_number=f"{admission_year % 100}{code[:3]}{(section.name if section else 'A')}{n + 1:03d}",
                admission_date=date(admission_year, 8, 1),
                admission_mode="counselling",
                enrolment_number=marker,
                status="active",
                guardians=[
                    GuardianIn(
                        relation="father",
                        name=f"{FIRST_M[(serial + 3) % 20]} {last}",
                        phone=_phone(marker + "f"),
                        occupation="Engineer" if serial % 2 else "Teacher",
                        is_primary=True,
                        create_portal_user=False,
                    ),
                    GuardianIn(
                        relation="mother",
                        name=f"{FIRST_F[(serial + 5) % 20]} {last}",
                        phone=_phone(marker + "m"),
                        create_portal_user=False,
                    ),
                ],
                create_user=not is_student1,
            )
            created = await service.create_record(
                body, "seed", audit=False, password_hash=pw_hash, seat_check=False, notify=False
            )
            student, enrolment = created.student, created.enrollment
            if is_student1:
                s1 = users.get("student.1")
                if s1 is not None:
                    student.user_id = s1.id
            await _history(ctx, inst.id, plan, n, student, enrolment, batch, programs[code], past, current)
            if serial % 50 == 0:
                await ctx.db.flush()
                print(f"   {serial} students")
        ctx.count("students", count)
    await ctx.db.flush()
    await _extras(ctx, principal, inst, batches, past, current)


async def _past_terms(
    ctx: SeedContext, institution_id: uuid.UUID, start_year: int
) -> dict[tuple[int, str], AcademicTerm]:
    """Institution-wide years 2024-25 and 2025-26 (closed) before the current one."""
    out: dict[tuple[int, str], AcademicTerm] = {}
    for y in (start_year - 2, start_year - 1):
        name = f"{y}-{(y + 1) % 100:02d}"
        year, created = await ctx.get_or_create(
            AcademicYear,
            {"start_date": date(y, 6, 1), "end_date": date(y + 1, 5, 31), "is_current": False, "is_locked": True},
            institution_id=institution_id,
            college_id=None,
            name=name,
        )
        for seq, (ttype, start, end) in enumerate(
            (("odd", date(y, 7, 1), date(y, 11, 30)), ("even", date(y + 1, 1, 4), date(y + 1, 5, 15))), start=1
        ):
            term, _ = await ctx.get_or_create(
                AcademicTerm,
                {
                    "name": f"{'Odd' if ttype == 'odd' else 'Even'} Semester",
                    "start_date": start,
                    "end_date": end,
                    "status": "closed",
                    "is_current": False,
                    "is_locked": True,
                },
                institution_id=institution_id,
                college_id=None,
                academic_year_id=year.id,
                term_type=ttype,
                sequence=seq,
            )
            out[(y, ttype)] = term
        _ = created
    await ctx.db.flush()
    return out


def _past_term(past: dict[tuple[int, str], AcademicTerm], admission_year: int, term_number: int) -> AcademicTerm | None:
    year = admission_year + (term_number - 1) // 2
    return past.get((year, "odd" if term_number % 2 == 1 else "even"))


async def _history(
    ctx: SeedContext,
    institution_id: uuid.UUID,
    plan: str,
    n: int,
    student: Student,
    enrolment: StudentProgramEnrollment,
    batch: Batch,
    program: Program,
    past: dict[tuple[int, str], AcademicTerm],
    current: AcademicTerm,
) -> None:
    """Completed past term records (SGPA / CGPA / credits) and the plan's special cases."""
    current_record = (
        await ctx.db.execute(
            select(StudentTermRecord).where(
                StudentTermRecord.student_program_enrollment_id == enrolment.id, StudentTermRecord.term_id == current.id
            )
        )
    ).scalar_one_or_none()
    section_id = current_record.section_id if current_record else None
    roll = current_record.roll_number if current_record else None
    last_completed = {"cse2024": 4, "cse2025": 2, "mba2025": 2, "mba2024": 4}[plan]
    on_break = plan == "cse2024" and n >= 200
    exited = plan == "cse2025" and n >= 118
    weak = (plan == "cse2024" and n in (10, 11)) or (plan == "cse2025" and n == 5)
    credits = Decimal("0")
    cgpa_sum = Decimal("0")
    for t in range(1, last_completed + 1):
        term = _past_term(past, batch.admission_year, t)
        if term is None:
            continue
        sgpa = SGPA_TRACK[(t + n) % 4] - (Decimal("3.4") if weak and t >= last_completed - 1 else Decimal("0"))
        cgpa_sum += sgpa
        earned = Decimal("21") if not weak else Decimal("15")
        credits += earned
        ctx.db.add(
            StudentTermRecord(
                institution_id=institution_id,
                student_program_enrollment_id=enrolment.id,
                term_id=term.id,
                term_number=t,
                section_id=section_id,
                roll_number=roll,
                status="completed",
                credits_registered=Decimal("21"),
                credits_earned=earned,
                sgpa=sgpa,
                cgpa=(cgpa_sum / t).quantize(Decimal("0.01")),
                attendance_pct=Decimal("82.5") + (n % 10),
                result_status="pass",
            )
        )
    enrolment.credits_earned = credits
    enrolment.cgpa = (cgpa_sum / last_completed).quantize(Decimal("0.01")) if last_completed else None
    if weak:
        enrolment.academic_standing = "probation" if plan == "cse2025" else "warning"
    if (on_break or exited or plan == "mba2024") and current_record is not None:
        await ctx.db.delete(current_record)
    if on_break:
        enrolment.status, student.status = "break", "on_break"
        enrolment.credits_earned = Decimal("84")
    elif exited:
        enrolment.status, enrolment.exit_award = "exited_early", "certificate"
        enrolment.exit_date = date(batch.admission_year + 1, 6, 15)
        enrolment.credits_earned = Decimal("42")
        student.status = "exited"
        if student.user_id:
            user = (await ctx.db.execute(select(User).where(User.id == student.user_id))).scalar_one()
            user.is_active = False
    elif plan == "mba2024":
        enrolment.status = "completed"
    elif current_record is not None:
        current_record.status = "in_progress"
    await ctx.db.flush()


async def _advisor(ctx: SeedContext, principal: Any, institution_id: uuid.UUID, batch: Batch) -> None:
    from app.repositories.department_repository import UnitHolderRepository
    from app.schemas.academics import AdvisorAssign
    from app.services.batch_service import BatchService

    section = (
        await ctx.db.execute(select(BatchSection).where(BatchSection.batch_id == batch.id, BatchSection.name == "B"))
    ).scalar_one_or_none()
    advisor = (
        await ctx.db.execute(select(User).where(User.institution_id == institution_id, User.username == "advisor.1"))
    ).scalar_one_or_none()
    if section is None or advisor is None:
        return
    holders = await UnitHolderRepository(ctx.db).holders("class_advisor", "offering", [section.id])
    if section.id in holders:
        return
    staff = (await ctx.db.execute(select(Staff).where(Staff.user_id == advisor.id))).scalar_one_or_none()
    await BatchService(ctx.db, principal).assign_advisor(
        batch.id, section.id, AdvisorAssign(staff_id=staff.id) if staff else AdvisorAssign(user_id=advisor.id)
    )
    ctx.count("class_advisors")


async def _extras(
    ctx: SeedContext,
    principal: Any,
    inst: Institution,
    batches: dict[tuple[str, int], Batch],
    past: dict[tuple[int, str], AcademicTerm],
    current: AcademicTerm,
) -> None:
    """Guardians with portal users, consent off, arrears, undertakings, documents, holds and credit transfers."""
    users = {
        u.username: u for u in (await ctx.db.execute(select(User).where(User.institution_id == inst.id))).scalars()
    }
    by_marker = {
        s.enrolment_number: s
        for s in (
            await ctx.db.execute(
                select(Student).where(Student.institution_id == inst.id, Student.enrolment_number.like("DEMO%"))
            )
        ).scalars()
    }
    if not by_marker:
        return
    cse2025_first = 202 + 1  # DEMO0203 = student.1 (first B.Tech CSE 2025 student)
    s1 = by_marker.get(f"DEMO{cse2025_first:04d}")
    noconsent = by_marker.get(f"DEMO{cse2025_first + 2:04d}")
    for student, username, relation in ((s1, "parent.1", "father"), (noconsent, "parent.noconsent", "mother")):
        user = users.get(username)
        if student is None or user is None:
            continue
        g = (
            (
                await ctx.db.execute(
                    select(StudentGuardian).where(
                        StudentGuardian.student_id == student.id, StudentGuardian.relation == relation
                    )
                )
            )
            .scalars()
            .first()
        )
        if g is not None and g.user_id != user.id:
            g.user_id, g.portal_access, g.name = user.id, True, user.display_name or g.name
            ctx.count("guardian_portal_links")
    if s1 is not None:
        s1_user = users.get("student.1")
        if s1_user is not None and s1.user_id is None:
            s1.user_id = s1_user.id
        if s1_user is not None:
            s1.phone, s1.email = s1_user.phone, s1_user.email
        s1.dob, s1.guardian_portal_consent = date(2006, 3, 14), True
    if noconsent is not None:
        noconsent.guardian_portal_consent = False
    await ctx.db.flush()

    # detention fixture: two B.Tech CSE 2024 students with five open arrears (rules.max_backlogs_for_promotion = 4)
    from app.models.academic import ProgramRegulation

    regulation_id = (
        await ctx.db.execute(
            select(ProgramRegulation.regulation_id).where(
                ProgramRegulation.id == batches[("BTECH-CSE", 2024)].program_regulation_id
            )
        )
    ).scalar_one()
    courses = list(
        (
            await ctx.db.execute(
                select(Course.id)
                .where(
                    Course.regulation_id == regulation_id,
                    Course.code.in_(["CS101", "MA101", "PH101", "CS102", "MA102", "CS201"]),
                )
                .order_by(Course.code)
                .limit(5)
            )
        ).scalars()
    )
    term1 = _past_term(past, 2024, 1)
    for marker in ("DEMO0021", "DEMO0022"):
        student = by_marker.get(marker)
        if student is None:
            continue
        enrolment = (
            (
                await ctx.db.execute(
                    select(StudentProgramEnrollment).where(StudentProgramEnrollment.student_id == student.id)
                )
            )
            .scalars()
            .first()
        )
        if enrolment is None:
            continue
        for course_id in courses:
            await ctx.db.execute(
                text(
                    "INSERT INTO student_arrears (institution_id, student_program_enrollment_id, course_id, "
                    "first_failed_term_id, last_attempt_term_id, attempts, status) VALUES (:i, :e, :c, :t, :t, 1, 'open') "
                    "ON CONFLICT (student_program_enrollment_id, course_id) DO NOTHING"
                ),
                {"i": inst.id, "e": enrolment.id, "c": course_id, "t": term1.id if term1 else None},
            )
    ctx.count("student_arrears", 10)

    # undertakings (anti_ragging + conduct) for every seeded student; student.1 keeps conduct pending
    templates = {
        r.k: r.id
        for r in (
            await ctx.db.execute(
                text(
                    "SELECT layout->>'undertaking_type' AS k, id FROM document_templates WHERE institution_id IS NULL "
                    "AND template_type = 'undertaking' AND layout->>'pack' = :p"
                ),
                {"p": inst.regulatory_pack or "IN"},
            )
        ).all()
    }
    year = (await ctx.db.execute(select(AcademicYear).where(AcademicYear.id == current.academic_year_id))).scalar_one()
    accepted_at = datetime(year.start_date.year, 7, 10, 5, 0, tzinfo=UTC)
    done = {
        (r.student_id, r.undertaking_type)
        for r in (
            await ctx.db.execute(
                select(StudentUndertaking.student_id, StudentUndertaking.undertaking_type).where(
                    StudentUndertaking.institution_id == inst.id
                )
            )
        ).all()
    }
    added = 0
    for marker, student in by_marker.items():
        if student.status not in ("active", "on_break"):
            continue
        for kind in ("anti_ragging", "conduct"):
            if (student.id, kind) in done or (student is s1 and kind == "conduct"):
                continue
            ctx.db.add(
                StudentUndertaking(
                    institution_id=inst.id,
                    student_id=student.id,
                    undertaking_type=kind,
                    template_id=templates.get(kind),
                    accepted_at=accepted_at + timedelta(minutes=int(marker[4:]) % 600),
                    ip="10.0.0.12",
                    user_agent="seed",
                )
            )
            added += 1
    if added:
        ctx.count("student_undertakings", added)
    await ctx.db.flush()

    # documents: 20 students, one expiring in 20 days (Beat students.document_expiry)
    if (await ctx.db.execute(select(func.count()).where(StudentDocument.institution_id == inst.id))).scalar_one() == 0:
        from app.core.files import build_key, storage
        from app.utils.pdf import simple_pdf

        key = build_key(inst.id, "student-documents", "demo-marksheet.pdf")
        await storage.put(key, simple_pdf(["Class XII statement of marks (demo)"], "Marksheet"), "application/pdf")
        url = storage.signed_url(key, 10 * 365 * 24 * 3600)
        today = datetime.now(UTC).date()
        for i, student in enumerate(list(by_marker.values())[:20]):
            ctx.db.add(
                StudentDocument(
                    institution_id=inst.id,
                    student_id=student.id,
                    doc_type="class_12_marksheet",
                    file_url=url,
                    verified_by=principal.id,
                    verified_at=datetime.now(UTC),
                )
            )
            if i == 0:
                ctx.db.add(
                    StudentDocument(
                        institution_id=inst.id,
                        student_id=student.id,
                        doc_type="income_certificate",
                        file_url=url,
                        expires_on=today + timedelta(days=20),
                        verified_by=principal.id,
                        verified_at=datetime.now(UTC),
                    )
                )
        ctx.count("student_documents", 21)
        await ctx.db.flush()

    # holds: 5 (library / exam / registration / hostel open, one library released)
    if (await ctx.db.execute(select(func.count()).where(StudentHold.institution_id == inst.id))).scalar_one() == 0:
        specs = [
            ("DEMO0031", "library", "Two books overdue since August", None),
            ("DEMO0032", "exam", "Lab record not submitted", None),
            ("DEMO0215", "registration", "Fee balance from the previous term", None),
            ("DEMO0330", "hostel", "Room damage charges pending", None),
            ("DEMO0040", "library", "Lost book — replaced", datetime.now(UTC)),
        ]
        for marker, kind, reason, released in specs:
            student = by_marker.get(marker)
            if student is None:
                continue
            enrolment = (
                (
                    await ctx.db.execute(
                        select(StudentProgramEnrollment).where(StudentProgramEnrollment.student_id == student.id)
                    )
                )
                .scalars()
                .first()
            )
            if enrolment is None:
                continue
            ctx.db.add(
                StudentHold(
                    institution_id=inst.id,
                    student_program_enrollment_id=enrolment.id,
                    hold_type=kind,
                    reason=reason,
                    placed_by=principal.id,
                    released_by=principal.id if released else None,
                    released_at=released,
                    source_type="manual",
                )
            )
        ctx.count("student_holds", 5)
        await ctx.db.flush()

    # credit transfers: two approved NPTEL courses and one waiting for the HOD (workflow students.credit_transfer)
    if (await ctx.db.execute(select(func.count()).where(CreditTransfer.institution_id == inst.id))).scalar_one() == 0:
        target = by_marker.get("DEMO0005")
        enrolment = None
        if target is not None:
            enrolment = (
                (
                    await ctx.db.execute(
                        select(StudentProgramEnrollment).where(StudentProgramEnrollment.student_id == target.id)
                    )
                )
                .scalars()
                .first()
            )
        if enrolment is not None:
            for code, title, score in (
                ("noc24-cs01", "Programming in Java", Decimal("84")),
                ("noc24-cs08", "Cloud Computing", Decimal("72")),
            ):
                ctx.db.add(
                    CreditTransfer(
                        institution_id=inst.id,
                        student_program_enrollment_id=enrolment.id,
                        term_id=_past_term(past, 2024, 3).id if _past_term(past, 2024, 3) else None,
                        source="nptel",
                        source_course_code=code,
                        source_title=title,
                        source_institution="NPTEL (IIT Madras)",
                        credits=Decimal("3"),
                        source_grade="Elite",
                        source_score_pct=score,
                        status="approved",
                        approved_by=principal.id,
                        approved_at=datetime.now(UTC),
                    )
                )
            await ctx.db.flush()
            from app.schemas.students import CreditTransferCreate
            from app.services.credit_transfer_service import CreditTransferService

            await CreditTransferService(ctx.db, principal, None, inst.id).create(
                CreditTransferCreate(
                    student_id=target.id,
                    source="swayam",
                    source_course_code="ugc24-ge12",
                    source_title="Introduction to Psychology",
                    source_institution="SWAYAM",
                    credits=Decimal("2"),
                    source_score_pct=Decimal("68"),
                )
            )
            ctx.count("credit_transfers", 3)
    await ctx.db.flush()
