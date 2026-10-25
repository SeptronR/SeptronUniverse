"""``transport`` demo seeder (Prompts/21 §21.2) — ``seed_demo_institution.py --only transport``.

Enables the transport features and creates the demo users ``transport.mgr`` (transport manager), ``driver.1`` /
``driver.2`` (drivers with staff records; passwords go to ``LOCAL_TEST_CREDENTIALS.md`` only). Then 12 vehicles (2 with
insurance expiring within the alert window; ``driver.1`` drives V1 on route R1, ``driver.2`` V2 on R2), 10 routes × 8
stops with fees, times and coordinates radiating from the campus, up to 700 student (``student.1`` first, on R1 stop 3)
and 60 staff allocations (fee invoices for students when ``transport.fees`` is on), GPS devices for 8 vehicles, trips
for the last 10 working days (completed) with simulated GPS traces, stop events and boarding / alighting events, and 6
months of maintenance and fuel logs. Idempotent: skipped when vehicles exist.
"""

import math
import random
import uuid
from datetime import UTC, date, datetime, time, timedelta

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import func, insert, select

CAMPUS = (12.9716, 77.5946)
USERS = [
    # (username, display, role slug, credential label, employee id)
    ("transport.mgr", "Transport Manager", "transport_manager", "transport_mgr", "T9001"),
    ("driver.1", "Driver One", "driver", "driver_1", "T9002"),
    ("driver.2", "Driver Two", "driver", "driver_2", "T9003"),
]


def _offset(lat: float, lng: float, km: float, bearing_deg: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    return (lat + km * math.cos(b) / 110.54, lng + km * math.sin(b) / (111.32 * math.cos(math.radians(lat))))


@seeder("transport", after=["students", "hr", "fees"])
async def seed_transport(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    from seeders.base import _password, _phone

    import app.features  # noqa: F401
    from app.core.errors import APIError
    from app.core.security import hash_password
    from app.core.tenancy import institution_tz, today_for
    from app.db.session import bind_tenant, set_tenant
    from app.models.academic import AcademicYear
    from app.models.hr import Staff
    from app.models.platform import College, Institution, Role, User, UserRole
    from app.models.students import Student, StudentProgramEnrollment
    from app.models.transport import (
        GpsDevice,
        TransportAllocation,
        TransportRoute,
        TransportStop,
        TransportTrip,
        TripPassengerEvent,
        TripStopEvent,
        Vehicle,
        VehicleFuelLog,
        VehicleGpsLog,
        VehicleMaintenance,
    )
    from app.services.feature_service import FeatureService
    from app.services.transport.gps_service import token_hash

    db = ctx.db
    rng = random.Random(21)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if (
        await db.execute(select(func.count()).select_from(Vehicle).where(Vehicle.institution_id == inst.id))
    ).scalar_one():
        return

    features = FeatureService(db)
    effective = await features.effective(inst.id)
    for key in ("transport.core", "transport.gps_live", "transport.staff", "transport.fees"):
        if key in effective:
            continue
        try:
            await features.set_platform_flag(
                inst.id, key, enabled=True, reason="demo seed (Phase 21)", config=None, confirm_dependencies=True
            )
            ctx.count("feature_overrides")
        except (APIError, KeyError) as exc:
            print(f"   transport: {key} not enabled ({exc})")
    fees_on = "transport.fees" in await features.effective(inst.id)

    today = today_for(inst)
    tz = institution_tz(inst)
    year = (
        await db.execute(
            select(AcademicYear)
            .where(AcademicYear.institution_id == inst.id)
            .order_by(AcademicYear.is_current.desc(), AcademicYear.start_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if year is None:
        print("   transport: no academic year — run the institution seeder first")
        return
    roles = {r.slug: r for r in (await db.execute(select(Role).where(Role.institution_id == inst.id))).scalars()}
    colleges = list(
        (await db.execute(select(College).where(College.institution_id == inst.id).order_by(College.code))).scalars()
    )

    # ---- demo users + staff records ------------------------------------------------------------------------------
    staff_of: dict[str, Staff] = {}
    for username, display, slug, label, emp in USERS:
        user = (
            await db.execute(select(User).where(User.institution_id == inst.id, User.username == username))
        ).scalar_one_or_none()
        if user is None:
            pwd = _password()
            user = User(
                institution_id=inst.id,
                username=username,
                email=f"{username}@{ctx.profile['slug']}.septronuniverse.in",
                phone=_phone(username),
                display_name=display,
                user_type="staff",
                password_hash=hash_password(pwd),
                is_verified=True,
                must_change_password=False,
                locale="en-IN",
                timezone="Asia/Kolkata",
            )
            db.add(user)
            await db.flush()
            ctx.count("users")
            ctx.credentials.append((label, username, pwd))
        if (
            slug in roles
            and (
                await db.execute(
                    select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == roles[slug].id)
                )
            ).scalar_one_or_none()
            is None
        ):
            db.add(
                UserRole(
                    institution_id=inst.id,
                    user_id=user.id,
                    role_id=roles[slug].id,
                    scope_type="institution" if slug == "transport_manager" else "self",
                    scope_id=None,
                )
            )
            ctx.count("user_roles")
        st = (await db.execute(select(Staff).where(Staff.user_id == user.id))).scalar_one_or_none()
        if st is None:
            first, _, last = display.partition(" ")
            st = Staff(
                institution_id=inst.id,
                college_id=colleges[0].id if colleges else None,
                user_id=user.id,
                employee_id=emp,
                first_name=first,
                last_name=last or None,
                phone=user.phone,
                staff_category="non_teaching",
                joining_date=today - timedelta(days=900),
            )
            db.add(st)
            await db.flush()
            ctx.count("staff")
        staff_of[username] = st
    # eight more (user-less) drivers for the rest of the fleet
    extra_drivers = []
    for i in range(10):
        emp = f"T91{i:02d}"
        st = (
            await db.execute(select(Staff).where(Staff.institution_id == inst.id, Staff.employee_id == emp))
        ).scalar_one_or_none()
        if st is None:
            st = Staff(
                institution_id=inst.id,
                employee_id=emp,
                first_name=rng.choice(["Ravi", "Suresh", "Manju", "Ganesh", "Prakash", "Naveen"]),
                last_name=rng.choice(["Kumar", "Gowda", "Rao", "Shetty"]),
                phone=f"+91987600{i:04d}",
                staff_category="non_teaching",
            )
            db.add(st)
            await db.flush()
        extra_drivers.append(st)
    drivers = [staff_of["driver.1"], staff_of["driver.2"], *extra_drivers]

    # ---- fleet ------------------------------------------------------------------------------------------------------
    vehicles: list[Vehicle] = []
    for i in range(12):
        v = Vehicle(
            institution_id=inst.id,
            college_id=(colleges[1].id if i >= 10 and len(colleges) > 1 else colleges[0].id) if colleges else None,
            registration_no=f"KA01AB{1001 + i}",
            vehicle_type="bus" if i < 10 else "van",
            capacity=50 if i < 10 else 12,
            make_model=rng.choice(["Tata Starbus", "Ashok Leyland Lynx", "Eicher Skyline"])
            if i < 10
            else "Force Traveller",
            year=2018 + i % 6,
            driver_staff_id=drivers[i].id if i < len(drivers) else None,
            insurance_expiry=today + timedelta(days=12 + i) if i in (3, 7) else today + timedelta(days=200 + 10 * i),
            fitness_expiry=today + timedelta(days=300 + i),
            permit_expiry=today + timedelta(days=400 + i),
            puc_expiry=today + timedelta(days=90 + 5 * i),
        )
        db.add(v)
        vehicles.append(v)
    await db.flush()
    ctx.count("vehicles", len(vehicles))

    devices = 0
    for v in vehicles[:8]:
        d = GpsDevice(
            institution_id=inst.id,
            device_id=f"GPS-{v.registration_no}",
            vehicle_id=v.id,
            token_hash=token_hash(f"demo-{v.registration_no}-{uuid.uuid4().hex}"),
            last_seen_at=datetime.now(UTC) - timedelta(hours=rng.randint(1, 30)),
        )
        db.add(d)
        await db.flush()
        v.gps_device_id = d.id
        devices += 1
    ctx.count("gps_devices", devices)

    # ---- routes & stops -----------------------------------------------------------------------------------------------
    areas = [
        "Jayanagar",
        "Whitefield",
        "Yelahanka",
        "Banashankari",
        "Hebbal",
        "Electronic City",
        "Rajajinagar",
        "KR Puram",
        "Kengeri",
        "Malleshwaram",
    ]
    routes: list[TransportRoute] = []
    stops: dict[uuid.UUID, list[TransportStop]] = {}
    for i, area in enumerate(areas):
        r = TransportRoute(
            institution_id=inst.id,
            college_id=vehicles[i].college_id,
            code=f"R{i + 1}",
            name=f"{area} – Campus",
            vehicle_id=vehicles[i].id,
            distance_km=round(8 * 1.6 + rng.random() * 3, 1),
            fee_paise=1800000,
        )
        db.add(r)
        await db.flush()
        routes.append(r)
        bearing = i * 36
        stops[r.id] = []
        for s in range(8):
            km = (8 - s) * 1.6  # stop 1 is the farthest; stop 8 next to the campus
            lat, lng = _offset(*CAMPUS, km, bearing + rng.uniform(-6, 6))
            pickup = (datetime.combine(today, time(7, 0)) + timedelta(minutes=6 * s)).time()
            drop = (datetime.combine(today, time(16, 30)) + timedelta(minutes=6 * (7 - s))).time()
            st = TransportStop(
                institution_id=inst.id,
                route_id=r.id,
                name=f"{area} Stop {s + 1}",
                sequence=s + 1,
                lat=round(lat, 6),
                lng=round(lng, 6),
                pickup_time=pickup,
                drop_time=drop,
                fee_paise=int(1200000 + (8 - s) * 150000),
            )
            db.add(st)
            stops[r.id].append(st)
        await db.flush()
    ctx.count("transport_routes", len(routes))
    ctx.count("transport_stops", sum(len(x) for x in stops.values()))

    # ---- allocations --------------------------------------------------------------------------------------------------
    s1 = (
        await db.execute(
            select(Student.id)
            .join(User, User.id == Student.user_id)
            .where(User.institution_id == inst.id, User.username == "student.1")
        )
    ).scalar_one_or_none()
    stu = list(
        (
            await db.execute(
                select(Student.id, StudentProgramEnrollment.id)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(
                    Student.institution_id == inst.id,
                    StudentProgramEnrollment.status == "active",
                    Student.deleted_at.is_(None),
                )
                .order_by(Student.registration_number)
                .limit(1200)
            )
        ).all()
    )
    enrol_of = dict(stu)
    student_ids = list(dict.fromkeys(([s1] if s1 in enrol_of else []) + [s for s, _ in stu]))[:700]
    staff_ids = list(
        (
            await db.execute(
                select(Staff.id)
                .where(
                    Staff.institution_id == inst.id,
                    Staff.status == "active",
                    Staff.id.notin_([d.id for d in drivers] + [staff_of["transport.mgr"].id]),
                )
                .limit(60)
            )
        ).scalars()
    )
    alloc_rows: list[TransportAllocation] = []
    cap_left = {r.id: 50 for r in routes}
    for n, sid in enumerate(student_ids):
        if n == 0 and sid == s1:
            r, stop = routes[0], stops[routes[0].id][2]
        else:
            open_routes = [r for r in routes if cap_left[r.id] > 0]
            if not open_routes:
                break
            r = rng.choice(open_routes)
            stop = rng.choice(stops[r.id])
        cap_left[r.id] -= 1
        alloc_rows.append(
            TransportAllocation(
                institution_id=inst.id,
                person_type="student",
                person_id=sid,
                route_id=r.id,
                stop_id=stop.id,
                academic_year_id=year.id,
                from_on=year.start_date,
                to_on=year.end_date,
                status="active",
            )
        )
    for sid in staff_ids:
        open_routes = [r for r in routes if cap_left[r.id] > 0]
        if not open_routes:
            break
        r = rng.choice(open_routes)
        cap_left[r.id] -= 1
        alloc_rows.append(
            TransportAllocation(
                institution_id=inst.id,
                person_type="staff",
                person_id=sid,
                route_id=r.id,
                stop_id=rng.choice(stops[r.id]).id,
                academic_year_id=year.id,
                from_on=year.start_date,
                to_on=year.end_date,
                status="active",
            )
        )
    db.add_all(alloc_rows)
    await db.flush()
    ctx.count("transport_allocations", len(alloc_rows))
    if fees_on:
        from app.services.transport.allocation_service import AllocationService

        svc = AllocationService(db, None, institution_id=inst.id)
        stop_by_id = {s.id: s for ss in stops.values() for s in ss}
        route_by_id = {r.id: r for r in routes}
        invoiced = 0
        for a in alloc_rows:
            if a.person_type != "student" or a.person_id not in enrol_of:
                continue
            fee = svc.fee_of(route_by_id[a.route_id], stop_by_id[a.stop_id])  # type: ignore[index]
            try:
                async with db.begin_nested():
                    a.fee_invoice_id = await svc.invoice(
                        enrol_of[a.person_id], a.id, fee, f"Transport fee — {route_by_id[a.route_id].code}"
                    )
                invoiced += 1
            except APIError as exc:
                print(f"   transport: invoice skipped ({exc.message})")
                break
        ctx.count("fee_invoices", invoiced)

    # ---- trips for the last 10 working days with traces -----------------------------------------------------------------
    days: list[date] = []
    d = today - timedelta(days=1)
    while len(days) < 10:
        if d.weekday() < 6:
            days.append(d)
        d -= timedelta(days=1)
    by_route: dict[uuid.UUID, list[TransportAllocation]] = {}
    for a in alloc_rows:
        by_route.setdefault(a.route_id, []).append(a)
    gps_rows: list[dict] = []
    stop_rows: list[dict] = []
    pass_rows: list[dict] = []
    trips = 0
    for day in sorted(days):
        for i, r in enumerate(routes):
            v = vehicles[i]
            for direction in ("pickup", "drop"):
                seq = stops[r.id] if direction == "pickup" else list(reversed(stops[r.id]))
                planned0 = seq[0].pickup_time if direction == "pickup" else seq[0].drop_time
                start = datetime.combine(day, planned0, tzinfo=tz) - timedelta(minutes=5)  # type: ignore[arg-type]
                t = TransportTrip(
                    institution_id=inst.id,
                    route_id=r.id,
                    vehicle_id=v.id,
                    driver_staff_id=v.driver_staff_id,
                    trip_date=day,
                    direction=direction,
                    status="completed",
                    started_at=start,
                )
                db.add(t)
                await db.flush()
                trips += 1
                late = rng.choice([0, 0, 1, 2, 3, 5, 8, 12, 20])
                at = start
                prev = None
                for s in seq:
                    planned = s.pickup_time if direction == "pickup" else s.drop_time
                    arrive = datetime.combine(day, planned, tzinfo=tz) + timedelta(minutes=late + rng.randint(-1, 2))  # type: ignore[arg-type]
                    if prev is not None and v.gps_device_id:
                        for k in range(1, 5):
                            f = k / 5
                            gps_rows.append(
                                {
                                    "id": uuid.uuid4(),
                                    "institution_id": inst.id,
                                    "vehicle_id": v.id,
                                    "trip_id": t.id,
                                    "lat": round(float(prev.lat) + (float(s.lat) - float(prev.lat)) * f, 6),
                                    "lng": round(float(prev.lng) + (float(s.lng) - float(prev.lng)) * f, 6),
                                    "speed_kmh": round(rng.uniform(18, 42), 1),
                                    "heading": i * 36 % 360,
                                    "recorded_at": (at + (arrive - at) * f).astimezone(UTC),
                                }
                            )
                    stop_rows.append(
                        {
                            "id": uuid.uuid4(),
                            "institution_id": inst.id,
                            "trip_id": t.id,
                            "stop_id": s.id,
                            "arrived_at": arrive,
                            "departed_at": arrive + timedelta(minutes=1),
                        }
                    )
                    for a in by_route.get(r.id, []):
                        if a.stop_id == s.id and rng.random() < 0.85:  # noqa: PLR2004
                            pass_rows.append(
                                {
                                    "id": uuid.uuid4(),
                                    "institution_id": inst.id,
                                    "trip_id": t.id,
                                    "person_type": a.person_type,
                                    "person_id": a.person_id,
                                    "event": "board" if direction == "pickup" else "alight",
                                    "stop_id": s.id,
                                    "occurred_at": arrive,
                                    "source": "qr",
                                }
                            )
                    at, prev = arrive, s
                t.ended_at = at + timedelta(minutes=8)
    for chunk in range(0, len(gps_rows), 2000):
        await db.execute(insert(VehicleGpsLog), gps_rows[chunk : chunk + 2000])
    if stop_rows:
        await db.execute(insert(TripStopEvent), stop_rows)
    for chunk in range(0, len(pass_rows), 2000):
        await db.execute(insert(TripPassengerEvent), pass_rows[chunk : chunk + 2000])
    ctx.count("transport_trips", trips)
    ctx.count("vehicle_gps_logs", len(gps_rows))
    ctx.count("trip_stop_events", len(stop_rows))
    ctx.count("trip_passenger_events", len(pass_rows))

    # ---- maintenance & fuel (6 months) ------------------------------------------------------------------------------------
    m_rows = f_rows = 0
    for i, v in enumerate(vehicles):
        odo = 40000 + i * 5000
        for week in range(26, 0, -1):
            day = today - timedelta(weeks=week)
            odo += rng.randint(250, 420)
            if week % 2 == 0:
                litres = round(rng.uniform(45, 70), 2)
                db.add(
                    VehicleFuelLog(
                        institution_id=inst.id,
                        vehicle_id=v.id,
                        filled_on=day,
                        litres=litres,
                        cost_paise=int(litres * 9500),
                        odometer=odo,
                    )
                )
                f_rows += 1
            if week % 8 == 0:
                db.add(
                    VehicleMaintenance(
                        institution_id=inst.id,
                        vehicle_id=v.id,
                        maintenance_type=rng.choice(["service", "tyres", "brakes", "battery"]),
                        service_date=day,
                        odometer=odo,
                        cost_paise=rng.randint(400000, 1800000),
                        vendor=rng.choice(["City Motors", "Ashok Service Point", "Tata Authorised Workshop"]),
                        next_due_date=day + timedelta(days=60),
                    )
                )
                m_rows += 1
    await db.flush()
    ctx.count("vehicle_fuel_log", f_rows)
    ctx.count("vehicle_maintenance", m_rows)
