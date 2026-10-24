"""``hostel`` demo seeder (Prompts/20 §20.2) — ``seed_demo_institution.py --only hostel``.

Enables the hostel features, then per college a boys and a girls hostel (3 blocks × 4 floors × 10 rooms, double /
triple), fee plans for the current year, mess plans (veg / non-veg / jain) and hostel applications for active students
(scored by distance / category / CGPA). The allotment run allots in score order (the rest wait-listed); most allottees
are checked in (fees marked paid for the demo), a few room-change requests, mess subscriptions with 30 days of meal
attendance and rebates, last month's bills, leaves in every status (late returns and one absconding), 7 nights of
roll-call, visitors, complaints, disciplinary records and 20 staff quarters with 15 allocations. The demo warden
(``warden.h1``) wardens the first boys hostel, the gate user is scoped to it. Idempotent: skipped when hostels exist.
"""

import random
from datetime import UTC, date, datetime, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select, text


@seeder("hostel", after=["students", "hr", "fees"])
async def seed_hostel(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import AcademicYear
    from app.models.fees import FeeInvoice
    from app.models.hostel import (
        Hostel,
        HostelAllocation,
        HostelApplication,
        HostelComplaint,
        HostelDisciplinaryRecord,
        HostelFeePlan,
        HostelLeave,
        HostelRollCall,
        HostelRollCallEntry,
        HostelVisitor,
        MessAttendance,
        MessPlan,
        MessSubscription,
        RoomChangeRequest,
        StaffQuarter,
        StaffQuarterAllocation,
    )
    from app.models.hr import Staff
    from app.models.platform import College, Institution, User
    from app.models.students import Student, StudentProgramEnrollment
    from app.schemas.hostel import AllotmentRunRequest, HostelBlockIn, HostelIn, MessBillRunRequest, RoomBulkCreate
    from app.services.auth_service import load_principal
    from app.services.feature_service import FeatureService
    from app.services.hostel.allocation_service import AllocationService
    from app.services.hostel.mess_service import MessService
    from app.services.hostel.structure_service import StructureService

    db = ctx.db
    rng = random.Random(20)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(Hostel).where(Hostel.institution_id == inst.id))
    ).scalar_one():
        return

    async def principal(name: str) -> object | None:
        u = (
            await db.execute(select(User).where(User.institution_id == inst.id, User.username == name))
        ).scalar_one_or_none()
        return await load_principal(db, u.id) if u else None

    admin = await principal("inst.admin")
    registrar = await principal("registrar") or admin

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "hostel.core",
        "hostel.mess",
        "hostel.mess_billing",
        "hostel.leave_outpass",
        "hostel.gate_qr",
        "hostel.night_roll_call",
        "hostel.room_change",
        "hostel.visitors",
        "hostel.complaints",
        "hostel.discipline",
        "hostel.staff_quarters",
        "portals.warden",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 20)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   hostel: {key} not enabled ({exc})")

    today = today_for(inst)
    year = (
        await db.execute(
            select(AcademicYear)
            .where(AcademicYear.institution_id == inst.id)
            .order_by(AcademicYear.is_current.desc(), AcademicYear.start_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if year is None:
        print("   hostel: no academic year — run the institution seeder first")
        return
    warden_staff = (
        await db.execute(
            select(Staff.id)
            .join(User, User.id == Staff.user_id)
            .where(User.institution_id == inst.id, User.username == "warden.h1")
        )
    ).scalar_one_or_none()

    structure = StructureService(db, registrar, institution_id=inst.id)
    colleges = (
        (await db.execute(select(College).where(College.institution_id == inst.id).order_by(College.code).limit(2)))
        .scalars()
        .all()
    )
    hostels: list[Hostel] = []
    for c in colleges:
        for kind in ("boys", "girls"):
            out = await structure.create(
                HostelIn(
                    college_id=c.id,
                    name=f"{c.code} {'Boys' if kind == 'boys' else 'Girls'} Hostel 1",
                    hostel_type=kind,
                    warden_staff_id=warden_staff if kind == "boys" and not hostels else None,
                )  # type: ignore[arg-type]
            )
            h = (await db.execute(select(Hostel).where(Hostel.id == out.id))).scalar_one()
            hostels.append(h)
            for bname in ("A", "B", "C"):
                blk = await structure.create_block(h.id, HostelBlockIn(name=bname, floors=4))
                await structure.bulk_rooms(
                    h.id,
                    RoomBulkCreate(
                        block_id=blk.id,
                        floor_from=1,
                        floor_to=4,
                        rooms_per_floor=10,
                        room_type="double" if bname != "C" else "triple",
                        number_pattern=f"{bname}{{floor}}{{seq:02}}",
                    ),
                )
                ctx.count("hostel_blocks")
            for rt, fee, dep in (("double", 3500000, 500000), ("triple", 2800000, 500000), ("single", 4500000, 500000)):
                db.add(
                    HostelFeePlan(
                        institution_id=inst.id,
                        hostel_id=h.id,
                        room_type=rt,
                        academic_year_id=year.id,
                        fee_per_term_paise=fee,
                        caution_deposit_paise=dep,
                        mess_advance_paise=0,
                    )
                )
            for name, diet, fee in (("Veg", "veg", 350000), ("Non-veg", "nonveg", 420000), ("Jain", "jain", 370000)):
                db.add(
                    MessPlan(
                        institution_id=inst.id,
                        hostel_id=h.id,
                        name=f"{h.name} {name}",
                        diet=diet,
                        monthly_fee_paise=fee,
                        menu={
                            d: {
                                "breakfast": "Idli / poha",
                                "lunch": "Rice, dal, sabzi",
                                "snacks": "Tea, biscuits",
                                "dinner": "Roti, curry",
                            }
                            for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
                        },
                    )
                )
    await db.flush()
    ctx.count("hostels", len(hostels))
    if warden_staff is None and hostels:
        print("   hostel: warden.h1 has no staff record — wardens unset")
    warden_user = (
        await db.execute(select(User).where(User.institution_id == inst.id, User.username == "warden.h1"))
    ).scalar_one_or_none()
    if warden_user is not None and hostels:
        # wardens own hostels through ``warden_staff_id``; without a staff row the role is scoped to the hostel instead
        await db.execute(
            text(
                "UPDATE user_roles SET scope_type = 'hostel', scope_id = :h WHERE user_id = :u "
                "AND role_id IN (SELECT id FROM roles WHERE slug = 'hostel_warden')"
            ),
            {"h": hostels[0].id, "u": warden_user.id},
        )
    gate_user = (
        await db.execute(select(User).where(User.institution_id == inst.id, User.username == "gate.h1"))
    ).scalar_one_or_none()
    if gate_user is not None and hostels:
        await db.execute(
            text(
                "UPDATE user_roles SET scope_type = 'hostel', scope_id = :h WHERE user_id = :u "
                "AND role_id IN (SELECT id FROM roles WHERE slug = 'hostel_gate_staff')"
            ),
            {"h": hostels[0].id, "u": gate_user.id},
        )

    # ---- applications + allotment ----
    students = (
        await db.execute(
            select(StudentProgramEnrollment, Student)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(StudentProgramEnrollment.institution_id == inst.id, StudentProgramEnrollment.status == "active")
            .order_by(Student.registration_number)
            .limit(600)
        )
    ).all()
    by_college: dict[object, dict[str, list[Hostel]]] = {}
    for h in hostels:
        by_college.setdefault(h.college_id, {}).setdefault(h.hostel_type, []).append(h)
    alloc = AllocationService(db, registrar, institution_id=inst.id)
    apps = 0
    for e, st in students:
        kind = "girls" if (st.gender or "").lower() == "female" else "boys"
        choices = by_college.get(e.college_id, {}).get(kind) or [h for h in hostels if h.hostel_type == kind]
        if not choices:
            continue
        distance = rng.choice([5, 30, 80, 150, 250, 400])
        db.add(
            HostelApplication(
                institution_id=inst.id,
                student_program_enrollment_id=e.id,
                academic_year_id=year.id,
                hostel_preference=[str(h.id) for h in choices],
                room_type_pref=rng.choice(["double", "triple"]),
                distance_km=distance,
                priority_score=await alloc.score(e, st, distance),
                status="applied",
            )
        )
        apps += 1
    await db.flush()
    ctx.count("hostel_applications", apps)
    summary = await alloc.run_allotment(AllotmentRunRequest(academic_year_id=year.id))
    ctx.count("hostel_allotted", summary.allotted)
    ctx.count("hostel_waitlisted", summary.waitlisted)

    allocations = list(
        (
            await db.execute(
                select(HostelAllocation).where(
                    HostelAllocation.institution_id == inst.id, HostelAllocation.status == "allotted"
                )
            )
        )
        .scalars()
        .all()
    )
    keep_unpaid = max(len(allocations) // 12, 1)
    from app.schemas.hostel import CheckInRequest

    checked = []
    for a in allocations[keep_unpaid:]:
        for inv_id in (a.fee_invoice_id, a.caution_deposit_invoice_id):
            if inv_id:
                await db.execute(
                    text(
                        "UPDATE fee_invoices SET status = 'paid', paid_paise = total_paise, balance_paise = 0 WHERE id = :i"
                    ),
                    {"i": inv_id},
                )
        await db.flush()
        try:
            await alloc.check_in(
                a.id,
                CheckInRequest(
                    room_condition={"walls": "ok", "furniture": "ok"}, inventory=["bed", "table", "chair", "cupboard"]
                ),
            )
            checked.append(a)
        except APIError as exc:
            print(f"   hostel: check-in skipped ({exc.message})")
    ctx.count("hostel_checked_in", len(checked))
    _ = FeeInvoice

    for a in checked[:20]:
        db.add(
            RoomChangeRequest(
                institution_id=inst.id,
                allocation_id=a.id,
                reason=rng.choice(["Room-mate conflict", "Closer to the lab block", "Medical — ground floor needed"]),
                status="requested",
            )
        )
    ctx.count("room_change_requests", min(20, len(checked)))

    # ---- mess subscriptions, attendance, rebates, bills ----
    plans = {
        p.hostel_id: p
        for p in (await db.execute(select(MessPlan).where(MessPlan.institution_id == inst.id, MessPlan.diet == "veg")))
        .scalars()
        .all()
    }
    subs = []
    month_start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    for a in checked:
        plan = plans.get(a.hostel_id)
        if plan is None:
            continue
        s = MessSubscription(
            institution_id=inst.id,
            student_program_enrollment_id=a.student_program_enrollment_id,
            mess_plan_id=plan.id,
            from_on=month_start,
            status="active",
        )
        db.add(s)
        subs.append(s)
    await db.flush()
    ctx.count("mess_subscriptions", len(subs))
    for i, s in enumerate(subs[:120]):
        for d in range(30):
            day = today - timedelta(days=d + 1)
            rebate = i < 10 and 5 <= d < 11
            for meal in ("breakfast", "lunch", "dinner"):
                if not rebate and rng.random() < 0.15:
                    continue
                db.add(
                    MessAttendance(
                        institution_id=inst.id,
                        mess_subscription_id=s.id,
                        on_date=day,
                        meal=meal,
                        status="rebate" if rebate else "taken",
                        source=rng.choice(["qr", "manual"]),
                    )
                )
    await db.flush()
    mess_admin = await principal("warden.h1") or registrar
    try:
        bills = await MessService(db, registrar, institution_id=inst.id).bill_run(
            MessBillRunRequest(month=month_start).month
        )
        ctx.count("mess_bills", bills.bills)
    except APIError as exc:
        print(f"   hostel: bill run skipped ({exc.message})")
    _ = mess_admin

    # ---- leaves (all statuses), roll-calls, visitors, complaints, discipline ----
    now = datetime.now(UTC)
    statuses = ["requested", "approved", "rejected", "out", "returned", "late_return"]
    for i, a in enumerate(checked[:200]):
        status = "absconding" if i == 0 else statuses[i % len(statuses)]
        start = (
            now - timedelta(days=rng.randint(1, 20), hours=rng.randint(0, 10))
            if status not in ("requested", "approved")
            else now + timedelta(days=rng.randint(1, 5))
        )
        end = start + timedelta(hours=rng.choice([4, 10, 48, 72]))
        if status in ("out",):
            start, end = now - timedelta(hours=3), now + timedelta(hours=5)
        if status == "absconding":
            start, end = now - timedelta(days=2), now - timedelta(hours=20)
        leave = HostelLeave(
            institution_id=inst.id,
            student_program_enrollment_id=a.student_program_enrollment_id,
            hostel_id=a.hostel_id,
            leave_type="out_pass" if (end - start) <= timedelta(hours=24) else "home_leave",
            from_at=start,
            to_at=end,
            destination=rng.choice(["Home", "City market", "Hospital", "Relative's place"]),
            reason="Demo",
            guardian_consent="otp_verified" if (end - start) > timedelta(hours=24) else "not_required",
            status=status,
            actual_out_at=start + timedelta(minutes=10)
            if status in ("out", "returned", "late_return", "absconding")
            else None,
            actual_return_at=end + timedelta(minutes=95 if status == "late_return" else -30)
            if status in ("returned", "late_return")
            else None,
            late_minutes=65 if status == "late_return" else (0 if status == "returned" else None),
            qr_token=f"hl{rng.getrandbits(192):048x}" if status in ("approved", "out") else None,
        )
        db.add(leave)
    ctx.count("hostel_leaves", min(200, len(checked)))
    for h in hostels:
        residents = [a for a in checked if a.hostel_id == h.id]
        for n in range(7):
            rc = HostelRollCall(
                institution_id=inst.id,
                hostel_id=h.id,
                on_date=today - timedelta(days=n + 1),
                taken_by=getattr(registrar, "id", None),
            )
            db.add(rc)
            await db.flush()
            for a in residents:
                db.add(
                    HostelRollCallEntry(
                        institution_id=inst.id,
                        roll_call_id=rc.id,
                        allocation_id=a.id,
                        status=rng.choices(["present", "absent", "on_leave"], weights=[90, 4, 6])[0],
                    )
                )
            ctx.count("hostel_roll_calls")
    for i, a in enumerate(checked[:40]):
        db.add(
            HostelVisitor(
                institution_id=inst.id,
                hostel_id=a.hostel_id,
                student_program_enrollment_id=a.student_program_enrollment_id,
                visitor_name=rng.choice(["R. Kumar", "S. Devi", "M. Rao", "A. Singh"]),
                relation=rng.choice(["father", "mother", "sibling", "guardian"]),
                phone=f"98{rng.randint(10000000, 99999999)}",
                id_proof_type="Aadhaar",
                id_proof_no=f"XXXX{rng.randint(1000, 9999)}",
                in_at=now - timedelta(days=i % 15, hours=2),
                out_at=now - timedelta(days=i % 15, hours=1) if i % 4 else None,
            )
        )
    ctx.count("hostel_visitors", min(40, len(checked)))
    for i, a in enumerate(checked[:25]):
        db.add(
            HostelComplaint(
                institution_id=inst.id,
                hostel_id=a.hostel_id,
                student_program_enrollment_id=a.student_program_enrollment_id,
                category=["electrical", "plumbing", "cleaning", "wifi", "food"][i % 5],
                description="Demo complaint — please look into it.",
                status=["open", "assigned", "in_progress", "resolved", "closed"][i % 5],
            )
        )
    ctx.count("hostel_complaints", min(25, len(checked)))
    for i, a in enumerate(checked[25:33]):
        db.add(
            HostelDisciplinaryRecord(
                institution_id=inst.id,
                student_program_enrollment_id=a.student_program_enrollment_id,
                hostel_id=a.hostel_id,
                incident_on=today - timedelta(days=i * 3 + 2),
                description=[
                    "Late return without intimation",
                    "Noise after lights-out",
                    "Unauthorised guest",
                    "Damage to furniture",
                ][i % 4],
                action=["warning", "fine", "warning", "fine"][i % 4],
                fine_paise=50000 if i % 2 else None,
            )
        )
    ctx.count("hostel_disciplinary_records", min(8, max(len(checked) - 25, 0)))

    # ---- staff quarters ----
    staff_rows = (
        (
            await db.execute(
                select(Staff.id).where(Staff.institution_id == inst.id, Staff.deleted_at.is_(None)).limit(15)
            )
        )
        .scalars()
        .all()
    )
    for i in range(20):
        q = StaffQuarter(
            institution_id=inst.id,
            college_id=colleges[0].id,
            unit_code=f"Q-{i + 1:02d}",
            quarter_type=["Type II", "Type III", "Type IV"][i % 3],
            rent_paise=[150000, 250000, 400000][i % 3],
            status="vacant",
        )
        db.add(q)
        await db.flush()
        if i < len(staff_rows):
            db.add(
                StaffQuarterAllocation(
                    institution_id=inst.id,
                    quarter_id=q.id,
                    staff_id=staff_rows[i],
                    from_on=today - timedelta(days=30 * (i + 1)),
                    rent_deduction=True,
                )
            )
            q.status = "allocated"
    ctx.count("staff_quarters", 20)
    ctx.count("staff_quarter_allocations", min(15, len(staff_rows)))
    await db.flush()
    _ = date
