"""``facilities`` demo seeder (Prompts/25 §25.2) — ``seed_demo_institution.py --only facilities``.

Enables the Phase 25 features, then: 20 manual calendar entries, 60 events across types / statuses with registrations
/ attendance / certificates, 150 room bookings (20 rejected as conflicts), 30 equipment bookings (bookable assets),
400 service requests across SLA states, 5 AMC contracts, 200 visitor passes, 6 SOS drills, 300 confidential health
visits, counselling slots for 3 counsellors with bookings, 12 sports teams, 20 sports events with participation,
25 lost & found items, 2 canteens with wallets (≤ 500 students) and transactions. Idempotent: skipped when events exist.
"""

import random
import secrets
import uuid
from datetime import UTC, datetime, time, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, select


@seeder("facilities", after=["timetable", "inventory", "fees", "hr", "students"])
async def seed_facilities(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.tenancy import today_for
    from app.db.session import bind_tenant, set_tenant
    from app.enums.facilities import NAAC_DEFAULTS, SLA_HOURS
    from app.models.calendar import CalendarEvent
    from app.models.events import Event, EventRegistration
    from app.models.facilities import (
        AmcContract,
        Canteen,
        CounsellingAppointment,
        EmergencyAlert,
        EquipmentBooking,
        HealthVisit,
        InsurancePolicy,
        LostFoundItem,
        RoomBooking,
        ServiceRequest,
        SportsEvent,
        SportsParticipation,
        SportsTeam,
        VisitorPass,
        WalletAccount,
        WalletTransaction,
    )
    from app.models.hr import Staff
    from app.models.inventory import Asset, Supplier
    from app.models.platform import Institution, InstitutionSetting, User
    from app.models.students import Student, StudentProgramEnrollment
    from app.models.timetable import Room
    from app.services.feature_service import FeatureService

    db = ctx.db
    rng = random.Random(25)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (await db.execute(select(func.count()).select_from(Event).where(Event.institution_id == inst.id))).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in (
        "calendar.core",
        "calendar.ical",
        "calendar.personal_feed",
        "events.core",
        "events.certificates",
        "facilities.room_booking",
        "facilities.service_desk",
        "facilities.equipment_booking",
        "facilities.lost_found",
        "facilities.amc",
        "facilities.visitor_gate",
        "facilities.emergency_sos",
        "facilities.health_centre",
        "facilities.counselling_appointments",
        "facilities.sports",
        "facilities.canteen_wallet",
    ):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 25)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   facilities: {key} not enabled ({exc})")

    today = today_for(inst)
    now = datetime.now(UTC)
    users = list(
        (await db.execute(select(User).where(User.institution_id == inst.id).order_by(User.username))).scalars()
    )
    by_name = {u.username: u for u in users}
    actor = by_name.get("registrar") or (users[0] if users else None)
    actor_id = actor.id if actor else None
    staff = list(
        (
            await db.execute(select(Staff).where(Staff.institution_id == inst.id).order_by(Staff.employee_id).limit(60))
        ).scalars()
    )
    students = list(
        (
            await db.execute(
                select(Student)
                .where(Student.institution_id == inst.id)
                .order_by(Student.registration_number)
                .limit(500)
            )
        ).scalars()
    )
    enrols = list(
        (
            await db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.institution_id == inst.id).limit(500)
            )
        ).scalars()
    )
    rooms = list(
        (
            await db.execute(select(Room).where(Room.institution_id == inst.id, Room.deleted_at.is_(None)).limit(40))
        ).scalars()
    )
    suppliers = list((await db.execute(select(Supplier).where(Supplier.institution_id == inst.id).limit(10))).scalars())
    req_users = [u.id for u in users[:80]] or ([actor_id] if actor_id else [])
    if not req_users:
        print("   facilities: no users — run --only base first")
        return

    def dt(days: float, hour: int = 10) -> datetime:
        return datetime.combine(today + timedelta(days=int(days)), time(hour, 0), tzinfo=UTC)

    # ---- calendar ---------------------------------------------------------------------------------------------------------
    for i, (title, et) in enumerate(
        [
            ("Foundation day", "general"),
            ("Parent-teacher meeting", "meeting"),
            ("Internal assessment 1 window", "exam"),
            ("Fee payment last date", "deadline"),
            ("Sports day", "general"),
            ("Library week", "academic"),
        ]
        * 4
    ):
        if i >= 20:
            break
        db.add(
            CalendarEvent(
                institution_id=inst.id,
                title=title,
                event_type=et,
                starts_at=dt(i * 9 - 30),
                all_day=True,
                created_by=actor_id,
            )
        )
        ctx.count("calendar_events")

    # ---- events ------------------------------------------------------------------------------------------------------------
    types = [
        "conference",
        "seminar",
        "workshop",
        "fdp",
        "guest_lecture",
        "cultural",
        "sports",
        "outreach",
        "exhibition",
        "alumni",
    ]
    statuses = ["proposed"] * 8 + ["approved"] * 8 + ["scheduled"] * 22 + ["completed"] * 18 + ["cancelled"] * 4
    events: list[Event] = []
    for i in range(60):
        st = statuses[i]
        et = types[i % len(types)]
        org = staff[i % len(staff)] if staff else None
        start = today + timedelta(days=(-60 + i * 2) if st == "completed" else (5 + i))
        e = Event(
            institution_id=inst.id,
            college_id=org.college_id if org else None,
            event_type=et,
            title=f"{et.replace('_', ' ').title()} {i + 1}: {rng.choice(['AI in education', 'Green campus', 'Startup culture', 'Research ethics', 'Digital India'])}",
            organiser_department_id=org.department_id if org else None,
            organiser_staff_id=org.id if org else None,
            from_on=start,
            to_on=start + timedelta(days=rng.choice([0, 0, 1, 2])),
            venue_room_id=rooms[i % len(rooms)].id if rooms and i % 3 == 0 else None,
            venue_text=None if rooms and i % 3 == 0 else "Main auditorium",
            budget_paise=rng.choice([0, 0, 2500000, 5000000, 10000000]) or None,
            naac_criterion=NAAC_DEFAULTS.get(et),
            registration_fee_paise=50000 if i % 4 == 0 else None,
            status=st,
            created_by=org.user_id if org and org.user_id else actor_id,
        )
        db.add(e)
        events.append(e)
    await db.flush()
    ctx.count("events", len(events))
    for e in events:
        reg = {
            "open": e.status in ("scheduled", "approved"),
            "fee_paise": e.registration_fee_paise or 0,
            "capacity": 120,
            "audience": "public" if e.event_type in ("conference", "cultural") else "institution",
            "waitlist": True,
        }
        db.add(
            InstitutionSetting(
                institution_id=inst.id,
                college_id=None,
                category="facilities_meta",
                key=f"event:{e.id}",
                value={"registration": reg},
                value_type="json",
            )
        )
        if e.status not in ("scheduled", "completed"):
            continue
        for s in rng.sample(students, min(len(students), rng.randint(10, 40))):
            attended = e.status == "completed" and rng.random() < 0.8
            db.add(
                EventRegistration(
                    institution_id=inst.id,
                    event_id=e.id,
                    person_type="student",
                    person_id=s.id,
                    external={
                        "qr_token": secrets.token_urlsafe(12),
                        "waitlisted": False,
                        **(
                            {
                                "certificate_id": str(uuid.uuid4()),
                                "certificate_no": f"CERT/DEMO/{rng.randint(10000, 99999)}",
                            }
                            if attended and rng.random() < 0.7
                            else {}
                        ),
                    },
                    attended=attended,
                )
            )
            ctx.count("event_registrations")
        if e.status == "completed":
            e.participants_count = rng.randint(20, 120)
            e.external_participants_count = rng.randint(0, 30)

    # ---- room bookings -----------------------------------------------------------------------------------------------------
    if rooms:
        for i in range(150):
            r = rooms[i % len(rooms)]
            f = dt(rng.randint(-20, 30), rng.choice([9, 11, 14, 16]))
            status = "rejected" if i < 20 else rng.choice(["approved", "approved", "requested", "cancelled"])
            db.add(
                RoomBooking(
                    institution_id=inst.id,
                    room_id=r.id,
                    requested_by=rng.choice(req_users),
                    purpose=rng.choice(
                        ["Club meeting", "Guest talk", "Workshop", "Review meeting", "Practice session"]
                    ),
                    from_at=f,
                    to_at=f + timedelta(hours=2),
                    expected_headcount=rng.randint(10, 60),
                    status=status,
                )
            )
            ctx.count("room_bookings")

    # ---- equipment ---------------------------------------------------------------------------------------------------------
    assets = list((await db.execute(select(Asset).where(Asset.institution_id == inst.id).limit(10))).scalars())
    for a in assets[:6]:
        a.is_bookable = True
    for i in range(30 if assets else 0):
        a = assets[i % min(6, len(assets))]
        f = dt(rng.randint(-10, 15), 9)
        db.add(
            EquipmentBooking(
                institution_id=inst.id,
                asset_id=a.id,
                requested_by=rng.choice(req_users),
                from_at=f,
                to_at=f + timedelta(hours=6),
                purpose="Event / lab use",
                status=rng.choice(["requested", "approved", "handed_over", "returned", "rejected"]),
                approved_by=actor_id,
            )
        )
        ctx.count("equipment_bookings")

    # ---- service desk ------------------------------------------------------------------------------------------------------
    cats = list(SLA_HOURS)
    for i in range(400):
        cat = cats[i % len(cats)]
        created = now - timedelta(hours=rng.randint(1, 24 * 40))
        due = created + timedelta(hours=SLA_HOURS[cat])
        status = rng.choice(["open", "assigned", "in_progress", "resolved", "closed", "closed", "closed", "reopened"])
        resolved = (
            created + timedelta(hours=rng.randint(1, SLA_HOURS[cat] * 2)) if status in ("resolved", "closed") else None
        )
        db.add(
            ServiceRequest(
                institution_id=inst.id,
                college_id=rooms[0].college_id if rooms else None,
                ticket_number=f"SR/{today.year}/D{i + 1:05d}",
                category=cat,
                location_room_id=rooms[i % len(rooms)].id if rooms else None,
                description=f"Demo {cat} issue #{i + 1}",
                priority=rng.choice(["low", "normal", "normal", "high", "urgent"]),
                requested_by=rng.choice(req_users),
                assigned_to=rng.choice(req_users) if status != "open" else None,
                sla_due_at=due,
                status=status,
                resolution="Fixed" if resolved else None,
                rating=rng.randint(3, 5) if status == "closed" else None,
                resolved_at=resolved,
                closed_at=resolved + timedelta(days=1) if status == "closed" and resolved else None,
                created_at=created,
            )
        )
        ctx.count("service_requests")

    # ---- AMC ---------------------------------------------------------------------------------------------------------------
    for i, sup in enumerate(suppliers[:5]):
        db.add(
            AmcContract(
                institution_id=inst.id,
                supplier_id=sup.id,
                asset_category=["it", "electrical", "civil", "network", "furniture"][i],
                from_on=today - timedelta(days=300),
                to_on=today + timedelta(days=[25, 60, 120, 200, 365][i]),
                value_paise=rng.randint(5, 50) * 1000000,
                sla={"it": 6, "electrical": 12},
                status="active",
            )
        )
        ctx.count("amc_contracts")

    # ---- visitors ----------------------------------------------------------------------------------------------------------
    for i in range(200):
        vf = now - timedelta(days=rng.randint(0, 60), hours=rng.randint(0, 8))
        st = rng.choice(["issued", "inside", "exited", "exited", "expired"])
        db.add(
            VisitorPass(
                institution_id=inst.id,
                visitor={
                    "name": f"Visitor {i + 1}",
                    "phone": f"98{rng.randint(10000000, 99999999)}",
                    "organisation": rng.choice(["Vendor", "Parent", "Guest", "Courier"]),
                },
                host_user_id=rng.choice(req_users),
                purpose="Meeting",
                valid_from=vf,
                valid_to=vf + timedelta(hours=8),
                gate_in_at=vf + timedelta(minutes=10) if st in ("inside", "exited") else None,
                gate_out_at=vf + timedelta(hours=3) if st == "exited" else None,
                pass_code=f"VPD{i + 1:05d}",
                status=st,
                created_by=actor_id,
            )
        )
        ctx.count("visitor_passes")

    # ---- SOS drills ----------------------------------------------------------------------------------------------------------
    for i in range(6):
        at = now - timedelta(days=i * 12 + 2)
        db.add(
            EmergencyAlert(
                institution_id=inst.id,
                raised_by_user_id=rng.choice(req_users),
                alert_type=["sos", "fire", "medical", "security", "sos", "fire"][i],
                location={"lat": 17.385 + i / 1000, "lng": 78.4867, "text": f"Block {chr(65 + i)}"},
                message="Drill",
                status="resolved",
                responders={"roles": ["security_officer"], "drill": True, "timeline": []},
                acknowledged_by=actor_id,
                acknowledged_at=at + timedelta(minutes=2),
                resolved_at=at + timedelta(minutes=20),
                created_at=at,
            )
        )
        ctx.count("emergency_alerts")

    # ---- health ---------------------------------------------------------------------------------------------------------------
    medical = by_name.get("medical.off") or actor
    for i in range(300 if students else 0):
        s = students[i % len(students)]
        db.add(
            HealthVisit(
                institution_id=inst.id,
                person_type="student",
                person_id=s.id,
                visited_at=now - timedelta(days=rng.randint(0, 180)),
                complaint=rng.choice(["Fever", "Headache", "Sprain", "Cold", "Stomach ache"]),
                diagnosis="Viral / minor",
                treatment="Rest, paracetamol",
                referred_to="City hospital" if i % 25 == 0 else None,
                attended_by=medical.id if medical else None,
            )
        )
        ctx.count("health_visits")
    for s in students[:60]:
        db.add(
            InsurancePolicy(
                institution_id=inst.id,
                person_type="student",
                person_id=s.id,
                provider="Star Health",
                policy_no=f"SH{rng.randint(100000, 999999)}",
                coverage_paise=10000000,
                valid_from=today - timedelta(days=200),
                valid_to=today + timedelta(days=rng.randint(-10, 200)),
            )
        )
        ctx.count("insurance_policies")

    # ---- counselling ---------------------------------------------------------------------------------------------------
    for c in staff[:3]:
        for d in range(1, 11):
            booked = students and rng.random() < 0.4
            s = rng.choice(students) if booked else None
            db.add(
                CounsellingAppointment(
                    institution_id=inst.id,
                    counsellor_staff_id=c.id,
                    slot_at=dt(d - 5, 11 + d % 4),
                    duration_minutes=30,
                    person_type="student" if s else None,
                    person_id=s.id if s else None,
                    status=("completed" if d < 5 else "booked") if s else "available",
                )
            )
            ctx.count("counselling_appointments")

    # ---- sports ---------------------------------------------------------------------------------------------------------------
    sports = ["Cricket", "Football", "Basketball", "Volleyball", "Athletics", "Badminton"]
    teams = []
    for i in range(12):
        members = [str(e.id) for e in rng.sample(enrols, min(len(enrols), 11))] if enrols else []
        t = SportsTeam(
            institution_id=inst.id,
            sport=sports[i % 6],
            name=f"{sports[i % 6]} {'A' if i < 6 else 'B'}",
            level="institution",
            coach_staff_id=staff[i % len(staff)].id if staff else None,
            members=members,
        )
        db.add(t)
        teams.append(t)
    await db.flush()
    ctx.count("sports_teams", len(teams))
    for i in range(20):
        se = SportsEvent(
            institution_id=inst.id,
            title=f"{sports[i % 6]} meet {i + 1}",
            sport=sports[i % 6],
            level=["institution", "inter_college", "university", "state"][i % 4],
            from_on=today - timedelta(days=i * 9),
            venue="Main ground",
        )
        db.add(se)
        await db.flush()
        ctx.count("sports_events")
        t = teams[i % len(teams)]
        for eid in (t.members or [])[:5]:
            db.add(
                SportsParticipation(
                    institution_id=inst.id,
                    sports_event_id=se.id,
                    student_program_enrollment_id=uuid.UUID(eid),
                    team_id=t.id,
                    result=rng.choice(["Winner", "Runner-up", "Participated"]),
                    position=rng.choice(["1", "2", None]),
                    evidence_url="/files/demo-certificate.pdf",
                )
            )
            ctx.count("sports_participation")

    # ---- lost & found ------------------------------------------------------------------------------------------------------
    for _i in range(25):
        db.add(
            LostFoundItem(
                institution_id=inst.id,
                description=rng.choice(["Water bottle", "Calculator", "ID card", "Umbrella", "Earphones"]),
                found_at=now - timedelta(days=rng.randint(0, 120)),
                location="Library",
                reported_by=rng.choice(req_users),
                status=rng.choice(["reported", "reported", "claimed", "disposed"]),
            )
        )
        ctx.count("lost_found_items")

    # ---- canteen & wallet ----------------------------------------------------------------------------------------------
    canteens = [
        Canteen(
            institution_id=inst.id,
            name="Central canteen",
            location="Block A",
            vendor_id=suppliers[0].id if suppliers else None,
            menu=[{"item": "Tea", "price_paise": 1000}, {"item": "Meals", "price_paise": 6000}],
        ),
        Canteen(
            institution_id=inst.id,
            name="Food court",
            location="Block C",
            menu=[{"item": "Coffee", "price_paise": 1500}, {"item": "Sandwich", "price_paise": 4000}],
        ),
    ]
    db.add_all(canteens)
    ctx.count("canteens", 2)
    for s in students[:500]:
        acc = WalletAccount(institution_id=inst.id, person_type="student", person_id=s.id, balance_paise=0)
        db.add(acc)
        await db.flush()
        bal = 0
        for _ in range(rng.randint(1, 4)):
            amt = rng.choice([10000, 20000, 50000])
            bal += amt
            db.add(
                WalletTransaction(
                    institution_id=inst.id,
                    account_id=acc.id,
                    txn_type="topup",
                    amount_paise=amt,
                    merchant="online",
                    reference="demo",
                )
            )
            spend = min(bal, rng.randint(1000, 15000))
            bal -= spend
            db.add(
                WalletTransaction(
                    institution_id=inst.id,
                    account_id=acc.id,
                    txn_type="debit",
                    amount_paise=spend,
                    merchant=rng.choice(canteens).name,
                    reference="demo",
                )
            )
        acc.balance_paise = bal
        ctx.count("wallet_accounts")
    await db.flush()
