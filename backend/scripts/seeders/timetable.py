"""``timetable`` demo seeder (Prompts/10 §10.2) — ``seed_demo_institution.py --type university --only timetable``.

On top of ``offerings`` (open offerings of the current term with their faculty and section targets):

* 2 buildings (``ACB`` academic block, ``LCX`` lab complex) and 30 rooms: 18 classrooms (``CR101`` …; ``CR118`` seats
  40 — the capacity-warning room), 1 smart class, 6 labs (3 tagged as CSE department labs), 1 auditorium and 4 exam
  halls (``exam_capacity`` = half the seats);
* the ``Default`` slot group (P1–P8 with a break and lunch) for the college when the 0010 revision did not seed it;
* one published timetable per section of every 2024 / 2025 batch: each targeted offering gets its lecture hours as
  single-slot entries (practical hours as a 2-slot lab span) Monday–Friday, placed greedily without room / staff /
  section clashes (each section has a home classroom); published from the term start, so the term's class sessions are
  generated (holidays skipped);
* 3 substitutions on upcoming sessions of ``faculty.1`` (or the first allocated teacher): one approved, two requested;
* an ``estate`` login (``estate_officer`` @institution — rooms and buildings), written to ``LOCAL_TEST_CREDENTIALS.md``
  as ``estate_officer``.

Idempotent: buildings / rooms dedupe on their code, timetables on (term, section), substitutions on (entry, date).
"""

import uuid

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select

from app.models.academic import AcademicTerm, Batch, BatchSection
from app.models.curriculum import Course
from app.models.hr import Staff
from app.models.offerings import CourseOffering, CourseOfferingFaculty, CourseOfferingTarget
from app.models.platform import Department, Institution, Role, User, UserRole
from app.models.timetable import (
    Building,
    ClassSession,
    Room,
    TimeSlot,
    Timetable,
    TimetableEntry,
    TimetableSubstitution,
)

ROOMS: list[tuple[str, str, str, str, int, list[str]]] = (
    [
        ("ACB", f"CR1{n:02d}", f"Classroom 1{n:02d}", "classroom", 70 if n != 18 else 40, ["projector"])
        for n in range(1, 19)
    ]
    + [("ACB", "SC201", "Smart class 201", "smart_class", 80, ["projector", "smart_board", "ac"])]
    + [("LCX", f"LAB{n}", f"Computer lab {n}", "lab", 36, ["computers", "lab:cse"]) for n in range(1, 4)]
    + [("LCX", f"LAB{n}", f"Lab {n}", "lab", 30, ["benches"]) for n in range(4, 7)]
    + [("ACB", "AUD1", "Main auditorium", "auditorium", 300, ["stage", "ac", "pa"])]
    + [("ACB", f"EH{n}", f"Exam hall {n}", "exam_hall", 120, ["cctv"]) for n in range(1, 5)]
)
DAYS = (1, 2, 3, 4, 5)


@seeder("timetable", after=["offerings"])
async def seed_timetable(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from app.db.session import bind_tenant, set_tenant
    from app.schemas.timetable import PublishRequest, SubstitutionCreate, SubstitutionDecision
    from app.services.auth_service import load_principal
    from app.services.timetable.substitution_service import SubstitutionService
    from app.services.timetable.timetable_service import TimetableService

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
    cse = (
        await ctx.db.execute(select(Department).where(Department.institution_id == inst.id, Department.code == "CSE"))
    ).scalar_one()
    college_id = cse.college_id

    # ---- estate officer login ----------------------------------------------------------------------------------
    if (
        await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "estate"))
    ).scalar_one_or_none() is None:
        from seeders.base import _password
        from seeders.students import _phone

        from app.core.security import hash_password

        pwd = _password()
        estate = User(
            institution_id=inst.id,
            username="estate",
            email=f"estate@{ctx.profile['slug']}.septronuniverse.in",
            phone=_phone("estate"),
            display_name="Estate Officer",
            user_type="staff",
            password_hash=hash_password(pwd),
            is_verified=True,
            must_change_password=False,
            locale="en-IN",
            timezone="Asia/Kolkata",
        )
        ctx.db.add(estate)
        await ctx.db.flush()
        role = (
            await ctx.db.execute(select(Role).where(Role.institution_id == inst.id, Role.slug == "estate_officer"))
        ).scalar_one()
        ctx.db.add(UserRole(institution_id=inst.id, user_id=estate.id, role_id=role.id, scope_type="institution"))
        ctx.credentials.append(("estate_officer", "estate", pwd))
        ctx.count("users")

    # ---- buildings & rooms -------------------------------------------------------------------------------------
    buildings: dict[str, Building] = {}
    for code, name, floors in (("ACB", "Academic Block", 4), ("LCX", "Lab Complex", 2)):
        b = (
            await ctx.db.execute(select(Building).where(Building.college_id == college_id, Building.code == code))
        ).scalar_one_or_none()
        if b is None:
            b = Building(institution_id=inst.id, college_id=college_id, code=code, name=name, floors=floors)
            ctx.db.add(b)
            ctx.count("buildings")
        buildings[code] = b
    await ctx.db.flush()
    rooms: dict[str, Room] = {}
    for bcode, code, name, rtype, cap, features in ROOMS:
        r = (
            await ctx.db.execute(select(Room).where(Room.college_id == college_id, Room.code == code))
        ).scalar_one_or_none()
        if r is None:
            tags = [*features, f"dept:{cse.id}"] if "lab:cse" in features else features
            r = Room(
                institution_id=inst.id,
                college_id=college_id,
                building_id=buildings[bcode].id,
                code=code,
                name=name,
                room_type=rtype,
                floor=int(code[-3]) if code.startswith("CR") else (2 if code.startswith("SC") else 0),
                capacity=cap,
                exam_capacity=cap // 2 if rtype in ("exam_hall", "classroom") else None,
                features=tags,
                is_bookable=rtype != "exam_hall",
            )
            ctx.db.add(r)
            ctx.count("rooms")
        rooms[code] = r
    await ctx.db.flush()

    # ---- slots -------------------------------------------------------------------------------------------------
    slots = list(
        (
            await ctx.db.execute(
                select(TimeSlot)
                .where(
                    TimeSlot.college_id == college_id, TimeSlot.slot_group == "Default", TimeSlot.is_active.is_(True)
                )
                .order_by(TimeSlot.sequence)
            )
        ).scalars()
    )
    if not slots:
        from datetime import time

        from app.core.settings_template import SETTINGS_TEMPLATE

        default = next(d.default for d in SETTINGS_TEMPLATE if d.full_key == "timetable.default_slot_group")
        for seq, s in enumerate(default, start=1):
            ctx.db.add(
                TimeSlot(
                    institution_id=inst.id,
                    college_id=college_id,
                    slot_group="Default",
                    name=s["name"],
                    sequence=seq,
                    start_time=time.fromisoformat(s["start_time"]),
                    end_time=time.fromisoformat(s["end_time"]),
                    slot_type=s["slot_type"],
                )
            )
            ctx.count("time_slots")
        await ctx.db.flush()
        slots = list(
            (
                await ctx.db.execute(
                    select(TimeSlot)
                    .where(TimeSlot.college_id == college_id, TimeSlot.slot_group == "Default")
                    .order_by(TimeSlot.sequence)
                )
            ).scalars()
        )
    teaching = [s for s in slots if s.slot_type not in ("break", "lunch")]

    # ---- timetables per section of the 2024 / 2025 batches -------------------------------------------------------------
    batches = list(
        (
            await ctx.db.execute(
                select(Batch).where(
                    Batch.institution_id == inst.id,
                    Batch.admission_year.in_((2024, 2025)),
                    Batch.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    sections = list(
        (
            await ctx.db.execute(
                select(BatchSection)
                .where(BatchSection.batch_id.in_([b.id for b in batches]), BatchSection.is_active.is_(True))
                .order_by(BatchSection.batch_id, BatchSection.name)
            )
        ).scalars()
    )
    # occupancy already taken by live entries of earlier runs
    busy_room: set[tuple[int, uuid.UUID, uuid.UUID]] = set()
    busy_staff: set[tuple[int, uuid.UUID, uuid.UUID]] = set()
    for e in (
        await ctx.db.execute(
            select(TimetableEntry).where(TimetableEntry.term_id == term.id, TimetableEntry.is_active.is_(True))
        )
    ).scalars():
        if e.room_id:
            busy_room.add((e.day_of_week, e.time_slot_id, e.room_id))
        if e.staff_id:
            busy_staff.add((e.day_of_week, e.time_slot_id, e.staff_id))
    classrooms = [rooms[f"CR1{n:02d}"] for n in range(1, 18)]
    labs = [rooms[f"LAB{n}"] for n in range(1, 7)]
    svc = TimetableService(ctx.db, principal, None, inst.id)
    published = 0
    for k, sec in enumerate(sections):
        exists = (
            await ctx.db.execute(
                select(Timetable.id).where(
                    Timetable.term_id == term.id, Timetable.scope_type == "section", Timetable.scope_id == sec.id
                )
            )
        ).first()
        if exists:
            continue
        offs = list(
            (
                await ctx.db.execute(
                    select(CourseOffering)
                    .where(
                        CourseOffering.term_id == term.id,
                        CourseOffering.deleted_at.is_(None),
                        CourseOffering.status.in_(("open", "closed", "in_progress")),
                        CourseOffering.id.in_(
                            select(CourseOfferingTarget.offering_id).where(
                                (CourseOfferingTarget.section_id == sec.id)
                                | (
                                    (CourseOfferingTarget.batch_id == sec.batch_id)
                                    & CourseOfferingTarget.section_id.is_(None)
                                )
                            )
                        ),
                    )
                    .order_by(CourseOffering.course_id)
                )
            ).scalars()
        )
        if not offs:
            continue
        courses = {
            c.id: c
            for c in (await ctx.db.execute(select(Course).where(Course.id.in_([o.course_id for o in offs])))).scalars()
        }
        fac: dict[uuid.UUID, CourseOfferingFaculty] = {}
        for f in (
            await ctx.db.execute(
                select(CourseOfferingFaculty).where(CourseOfferingFaculty.offering_id.in_([o.id for o in offs]))
            )
        ).scalars():
            fac.setdefault(f.offering_id, f)
        home = classrooms[k % len(classrooms)]
        tt = Timetable(
            institution_id=inst.id,
            college_id=college_id,
            term_id=term.id,
            scope_type="section",
            scope_id=sec.id,
            name=f"Section {sec.name}",
            version=1,
            status="draft",
            created_by=admin.id,
        )
        ctx.db.add(tt)
        await ctx.db.flush()
        sec_busy: set[tuple[int, uuid.UUID]] = set()
        for o in offs:
            c = courses.get(o.course_id)
            f = fac.get(o.id)
            staff_id = f.staff_id if f else None
            lectures = min(4, int(c.lecture_hours) if c else 3)
            # a staff allocation caps the weekly scheduled hours (``hours_per_week``; 50-minute slots)
            if f and f.hours_per_week:
                lectures = min(lectures, int(f.hours_per_week * 60 // 50))
            practical = bool(c and c.practical_hours and c.course_type in ("lab", "integrated_lab"))
            placed = 0
            for pass_no in (0, 1):
                for day in DAYS:
                    if placed >= lectures:
                        break
                    for s in teaching:
                        if placed >= lectures:
                            break
                        if (day, s.id) in sec_busy or (staff_id and (day, s.id, staff_id) in busy_staff):
                            continue
                        if (day, s.id, home.id) in busy_room:
                            continue
                        ctx.db.add(
                            TimetableEntry(
                                institution_id=inst.id,
                                timetable_id=tt.id,
                                term_id=term.id,
                                offering_id=o.id,
                                section_id=sec.id,
                                day_of_week=day,
                                time_slot_id=s.id,
                                room_id=home.id,
                                staff_id=staff_id,
                                session_type="lecture",
                                week_pattern="all",
                                slot_span=1,
                                is_active=False,
                            )
                        )
                        sec_busy.add((day, s.id))
                        busy_room.add((day, s.id, home.id))
                        if staff_id:
                            busy_staff.add((day, s.id, staff_id))
                        placed += 1
                        if pass_no == 0:
                            break  # spread: one lecture per day on the first pass
            if practical:
                done = False
                for day in reversed(DAYS):
                    for i in range(len(teaching) - 1):
                        a, b = teaching[i], teaching[i + 1]
                        if b.sequence != a.sequence + 1:
                            continue  # a span may not cross a break
                        if {(day, a.id), (day, b.id)} & sec_busy:
                            continue
                        if staff_id and {(day, a.id, staff_id), (day, b.id, staff_id)} & busy_staff:
                            continue
                        lab = next(
                            (lb for lb in labs if not {(day, a.id, lb.id), (day, b.id, lb.id)} & busy_room), None
                        )
                        if lab is None:
                            continue
                        ctx.db.add(
                            TimetableEntry(
                                institution_id=inst.id,
                                timetable_id=tt.id,
                                term_id=term.id,
                                offering_id=o.id,
                                section_id=sec.id,
                                day_of_week=day,
                                time_slot_id=a.id,
                                room_id=lab.id,
                                staff_id=staff_id,
                                session_type="lab",
                                week_pattern="all",
                                slot_span=2,
                                is_active=False,
                            )
                        )
                        for x in (a, b):
                            sec_busy.add((day, x.id))
                            busy_room.add((day, x.id, lab.id))
                            if staff_id:
                                busy_staff.add((day, x.id, staff_id))
                        done = True
                        break
                    if done:
                        break
        await ctx.db.flush()
        ctx.count("timetables")
        try:
            async with ctx.db.begin_nested():
                out = await svc.publish(tt.id, PublishRequest(effective_from=term.start_date, regenerate_sessions=True))
            ctx.created["class_sessions"] = ctx.created.get("class_sessions", 0) + out.sessions_created
            published += 1
        except Exception as exc:  # noqa: BLE001 - a demo section that cannot publish stays a draft
            print(f"   section {sec.name}: left as draft ({str(exc)[:160]})")  # noqa: T201
    await ctx.db.flush()
    ctx.created["timetables_published"] = ctx.created.get("timetables_published", 0) + published

    # ---- substitutions ------------------------------------------------------------------------------------------
    if not (await ctx.db.execute(select(TimetableSubstitution.id).limit(1))).first():
        today = await svc.today()
        f1 = (
            await ctx.db.execute(select(User).where(User.institution_id == inst.id, User.username == "faculty.1"))
        ).scalar_one_or_none()
        f1_staff = (
            (await ctx.db.execute(select(Staff).where(Staff.user_id == f1.id))).scalar_one_or_none() if f1 else None
        )
        q = select(ClassSession).where(
            ClassSession.term_id == term.id,
            ClassSession.session_date > today,
            ClassSession.status == "scheduled",
            ClassSession.timetable_entry_id.is_not(None),
            ClassSession.staff_id.is_not(None),
        )
        if f1_staff is not None:
            q = q.where(ClassSession.staff_id == f1_staff.id)
        upcoming = list(
            (await ctx.db.execute(q.order_by(ClassSession.session_date, ClassSession.start_time).limit(12))).scalars()
        )
        subs = SubstitutionService(ctx.db, principal, None, inst.id)
        made = 0
        seen_dates: set[tuple[uuid.UUID | None, object]] = set()
        for s in upcoming:
            if made >= 3 or (s.timetable_entry_id, s.session_date) in seen_dates:
                continue
            candidates = list((
                    await ctx.db.execute(
                        select(Staff).where(
                            Staff.institution_id == inst.id,
                            Staff.department_id == cse.id,
                            Staff.staff_category == "teaching",
                            Staff.deleted_at.is_(None),
                            Staff.id != s.staff_id,
                        )
                    )
                ).scalars())
            free = None
            for c in candidates:
                clash = await subs.sessions.overlapping(s.session_date, s.start_time, s.end_time, staff_id=c.id)
                if not clash:
                    free = c
                    break
            try:
                async with ctx.db.begin_nested():
                    row = await subs.create(
                        SubstitutionCreate(
                            entry_id=s.timetable_entry_id,
                            on_date=s.session_date,
                            substitute_staff_id=free.id if free else None,
                            reason="Demo: faculty attending a workshop" if made == 0 else "Demo: personal work",
                        )
                    )
                    if made == 0 and free is not None:
                        await subs.approve(row.id, SubstitutionDecision(comment="Approved (demo)"))
                made += 1
                seen_dates.add((s.timetable_entry_id, s.session_date))
            except Exception as exc:  # noqa: BLE001
                print(f"   substitution skipped: {str(exc)[:120]}")  # noqa: T201
        ctx.created["timetable_substitutions"] = ctx.created.get("timetable_substitutions", 0) + made
