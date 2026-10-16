"""``offerings`` demo seeder (Prompts/09 §09.2) — ``seed_demo_institution.py --type university --only offerings``.

On top of ``students`` (batches 2024/2025 in their real terms, 400 students) for the institution-wide current term:

* offerings from the curriculum for B.Tech CSE 2024 (term 5) / 2025 (term 3) and MBA 2025 (term 3) — 2 sections each,
  baskets included (PE-I: CS351 / CS352 × 2 sections = 4 offerings, 30 seats) — status ``open``; ``faculty.1`` teaches
  section A of the 2025 CSE courses (CS201 / CS202 / MA201), other CSE teaching staff the rest;
* windows: *Regular registration* (open now, advisor approval), *Add / drop* (until +30 days) and *Arrear
  registration* (open now);
* B.Tech CSE 2024 and MBA 2025 bulk-registered (mandatory courses, approved → confirmed); 20 PE-I choice forms from
  2024 CSE students; one 2024 student (``student.arrear``) with an open arrear in CS203; the 2025 student with the
  registration hold becomes ``student.hold``; a new staff user ``faculty.3`` (CSE, not allocated). The three demo
  logins are written to ``LOCAL_TEST_CREDENTIALS.md`` (``student_arrear`` / ``student_hold`` / ``faculty_3``).
  ``student.1`` stays unregistered (the verification script registers it).

Idempotent: offerings dedupe on (term, course, section), windows on their name, users on the username.
"""

import uuid
from datetime import UTC, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select

from app.core.security import hash_password
from app.models.academic import AcademicTerm, Batch, Program
from app.models.curriculum import Course, ElectiveBasket, ElectiveBasketCourse
from app.models.hr import Staff
from app.models.offerings import CourseOffering, CourseOfferingFaculty
from app.models.platform import Department, Institution, Role, User, UserRole
from app.models.registration import ElectiveChoiceForm, RegistrationWindow, StudentArrear
from app.models.students import Student, StudentHold, StudentProgramEnrollment, StudentTermRecord


async def _login(ctx: SeedContext, inst_id: uuid.UUID, user: User, label: str) -> None:
    from seeders.base import _password

    pwd = _password()
    user.password_hash, user.must_change_password = hash_password(pwd), False
    ctx.credentials.append((label, user.username, pwd))


@seeder("offerings", after=["students"])
async def seed_offerings(ctx: SeedContext) -> None:
    from seeders.base import _password
    from seeders.students import _phone

    from app.db.session import bind_tenant, set_tenant
    from app.schemas.offerings import BulkFromCurriculumRequest
    from app.schemas.registration import BulkRegisterRequest
    from app.services.auth_service import load_principal
    from app.services.registration.offering_service import OfferingService
    from app.services.registration.registration_service import RegistrationService

    inst = (await ctx.db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(ctx.db, inst.id)
    await set_tenant(ctx.db, inst.id)
    admin = (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "inst.admin"))
    ).scalar_one()
    principal = await load_principal(ctx.db, admin.id)
    term = (
        await ctx.db.execute(
            select(AcademicTerm).where(
                AcademicTerm.institution_id == inst.id,
                AcademicTerm.college_id.is_(None),
                AcademicTerm.is_current.is_(True),
                AcademicTerm.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    programs = {p.code: p for p in (await ctx.db.execute(select(Program).where(Program.institution_id == inst.id))).scalars()}
    batches: dict[tuple[str, int], Batch] = {}
    for code, year in (("BTECH-CSE", 2024), ("BTECH-CSE", 2025), ("MBA", 2025)):
        b = (
            await ctx.db.execute(
                select(Batch).where(
                    Batch.program_id == programs[code].id, Batch.admission_year == year, Batch.entry_type == "regular",
                    Batch.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        batches[(code, year)] = b

    svc = OfferingService(ctx.db, principal, None, inst.id)
    out = await svc.bulk_from_curriculum(
        BulkFromCurriculumRequest(
            term_id=term.id, batch_ids=[b.id for b in batches.values()], sections_per_course=2, include_baskets=True
        ),
        dry_run=False,
    )
    ctx.created["course_offerings"] = ctx.created.get("course_offerings", 0) + out.to_create
    offs = list(
        (await ctx.db.execute(select(CourseOffering).where(CourseOffering.term_id == term.id, CourseOffering.deleted_at.is_(None)))).scalars()
    )
    courses = {c.id: c for c in (await ctx.db.execute(select(Course).where(Course.id.in_([o.course_id for o in offs])))).scalars()}
    pe = (
        await ctx.db.execute(
            select(ElectiveBasket).where(
                ElectiveBasket.program_regulation_id == batches[("BTECH-CSE", 2024)].program_regulation_id,
                ElectiveBasket.code == "PE-I",
            )
        )
    ).scalar_one_or_none()
    pe_courses = set()
    if pe is not None:
        pe_courses = set(
            (await ctx.db.execute(select(ElectiveBasketCourse.course_id).where(ElectiveBasketCourse.basket_id == pe.id))).scalars()
        )
    for o in offs:
        if o.status == "planned":
            o.status = "open"
        if o.course_id in pe_courses and o.enrolled_count == 0:
            o.max_seats = 30
    await ctx.db.flush()

    # faculty
    cse = (await ctx.db.execute(select(Department).where(Department.institution_id == inst.id, Department.code == "CSE"))).scalar_one()
    f1 = (await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "faculty.1"))).scalar_one_or_none()
    f1_staff = (await ctx.db.execute(select(Staff).where(Staff.user_id == f1.id))).scalar_one_or_none() if f1 else None
    teachers = list(
        (
            await ctx.db.execute(
                select(Staff).where(
                    Staff.institution_id == inst.id, Staff.department_id == cse.id, Staff.staff_category == "teaching",
                    Staff.status != "exited", Staff.deleted_at.is_(None),
                ).order_by(Staff.employee_id)
            )
        ).scalars()
    )
    pool = [s for s in teachers if f1_staff is None or s.id != f1_staff.id]
    # faculty.3: a CSE teacher without a login gets one and is never allocated
    f3_user = (await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "faculty.3"))).scalar_one_or_none()
    f3_staff = None
    if f3_user is None:
        f3_staff = next((s for s in pool if s.user_id is None), None)
        pwd = _password()
        f3_user = User(
            institution_id=inst.id, username="faculty.3", email=f"faculty.3@{ctx.profile['slug']}.septronuniverse.in",
            phone=_phone("faculty.3"), display_name="Faculty Member Three", user_type="staff",
            password_hash=hash_password(pwd), is_verified=True, must_change_password=False, locale="en-IN",
            timezone="Asia/Kolkata",
        )
        ctx.db.add(f3_user)
        await ctx.db.flush()
        ctx.credentials.append(("faculty_3", "faculty.3", pwd))
        role = (await ctx.db.execute(select(Role).where(Role.institution_id == inst.id, Role.slug == "faculty"))).scalar_one()
        ctx.db.add(UserRole(institution_id=inst.id, user_id=f3_user.id, role_id=role.id, scope_type="self"))
        if f3_staff is not None:
            f3_staff.user_id = f3_user.id
        ctx.count("users")
    else:
        f3_staff = (await ctx.db.execute(select(Staff).where(Staff.user_id == f3_user.id))).scalar_one_or_none()
    pool = [s for s in pool if f3_staff is None or s.id != f3_staff.id] or teachers
    existing_fac = set((await ctx.db.execute(select(CourseOfferingFaculty.offering_id))).scalars())
    n = 0
    for o in sorted(offs, key=lambda x: (str(x.course_id), x.section_code)):
        if o.id in existing_fac or o.department_id != cse.id:
            continue
        c = courses[o.course_id]
        staff = f1_staff if (f1_staff and o.section_code == "A" and c.code in ("CS201", "CS202", "MA201")) else pool[n % len(pool)]
        n += 1
        hours = int(c.lecture_hours or 3) + int(c.tutorial_hours or 0)
        ctx.db.add(
            CourseOfferingFaculty(institution_id=inst.id, offering_id=o.id, staff_id=staff.id, role="coordinator", hours_per_week=hours)
        )
        o.coordinator_staff_id = staff.id
        ctx.count("course_offering_faculty")
    await ctx.db.flush()

    # windows
    now = datetime.now(UTC)
    for name, wtype, start, end, advisor in (
        ("Regular registration", "regular", now - timedelta(days=2), now + timedelta(days=20), True),
        ("Add / drop", "add_drop", now - timedelta(days=1), now + timedelta(days=30), True),
        ("Arrear registration", "arrear", now - timedelta(days=1), now + timedelta(days=20), True),
    ):
        w = (
            await ctx.db.execute(
                select(RegistrationWindow).where(RegistrationWindow.term_id == term.id, RegistrationWindow.name == name)
            )
        ).scalar_one_or_none()
        if w is None:
            ctx.db.add(
                RegistrationWindow(
                    institution_id=inst.id, term_id=term.id, name=name, window_type=wtype, starts_at=start, ends_at=end,
                    requires_advisor_approval=advisor, status="open", created_by=admin.id,
                )
            )
            ctx.count("registration_windows")
    await ctx.db.flush()

    # demo logins: student.hold (registration hold, 2025 CSE) and student.arrear (2024 CSE, open arrear in CS203)
    hold_user = (
        await ctx.db.execute(
            select(User)
            .join(Student, Student.user_id == User.id)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
            .join(StudentHold, StudentHold.student_program_enrollment_id == StudentProgramEnrollment.id)
            .where(StudentHold.hold_type == "registration", StudentHold.released_at.is_(None), User.institution_id == inst.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if hold_user is not None and not any(label == "student_hold" for label, *_ in ctx.credentials):
        await _login(ctx, inst.id, hold_user, "student_hold")
    cse24 = batches[("BTECH-CSE", 2024)]
    active24 = list(
        (
            await ctx.db.execute(
                select(StudentProgramEnrollment, Student)
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .join(StudentTermRecord, StudentTermRecord.student_program_enrollment_id == StudentProgramEnrollment.id)
                .where(
                    StudentProgramEnrollment.batch_id == cse24.id, StudentProgramEnrollment.status == "active",
                    StudentTermRecord.term_id == term.id,
                )
                .order_by(Student.registration_number)
            )
        ).all()
    )
    cs203 = (
        await ctx.db.execute(
            select(Course).where(Course.code == "CS203", Course.institution_id == inst.id, Course.status == "active")
        )
    ).scalars().first()
    if active24 and cs203 is not None:
        e_arr, s_arr = active24[-1]
        if (await ctx.db.execute(select(StudentArrear).where(StudentArrear.student_program_enrollment_id == e_arr.id, StudentArrear.course_id == cs203.id))).scalar_one_or_none() is None:
            ctx.db.add(StudentArrear(institution_id=inst.id, student_program_enrollment_id=e_arr.id, course_id=cs203.id, attempts=1, status="open"))
            ctx.count("student_arrears")
        u = (await ctx.db.execute(select(User).where(User.id == s_arr.user_id))).scalar_one_or_none()
        if u is not None and (await ctx.db.execute(select(StudentArrear).where(StudentArrear.student_program_enrollment_id == e_arr.id))).first() and ctx.created.get("student_arrears"):
            await _login(ctx, inst.id, u, "student_arrear")
    await ctx.db.flush()

    # choice forms (20 PE-I forms from 2024 CSE students, spread submission times)
    if pe is not None and len(pe_courses) >= 2:
        ordered = sorted(pe_courses, key=str)
        for k, (e, _s) in enumerate(active24[:20]):
            if (await ctx.db.execute(select(ElectiveChoiceForm).where(ElectiveChoiceForm.student_program_enrollment_id == e.id, ElectiveChoiceForm.elective_basket_id == pe.id, ElectiveChoiceForm.term_id == term.id))).scalar_one_or_none():
                continue
            first, second = (ordered[0], ordered[1]) if k % 3 else (ordered[1], ordered[0])
            ctx.db.add(
                ElectiveChoiceForm(
                    institution_id=inst.id, student_program_enrollment_id=e.id, elective_basket_id=pe.id, term_id=term.id,
                    choices=[{"course_id": str(first), "priority": 1}, {"course_id": str(second), "priority": 2}],
                    status="submitted", submitted_at=now - timedelta(hours=40 - k),
                )
            )
            ctx.count("elective_choice_forms")
        await ctx.db.flush()

    # bulk registration (mandatory courses, auto-approved) for B.Tech CSE 2024 and MBA 2025
    reg = RegistrationService(ctx.db, principal, None, inst.id)
    for key in (("BTECH-CSE", 2024), ("MBA", 2025)):
        res = await reg.bulk_register(BulkRegisterRequest(batch_id=batches[key].id, term_id=term.id))
        ctx.created["course_registrations"] = ctx.created.get("course_registrations", 0) + res.registrations_approved
    await svc.recount(term.id)
