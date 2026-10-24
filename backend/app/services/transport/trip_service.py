"""Trips — Prompts/21 §21.6 ``trip_service``.

1. Scheduling: for each working day (``transport.working_days``, Mon=0; not a student holiday of the route's college or
   the institution; inside an academic term) a ``pickup`` and a ``drop`` trip per active route whose vehicle is
   ``active`` (vehicles in ``maintenance`` are reported as blocked); ad-hoc trips (events, exams) are created manually;
   cancellations notify the passengers and their guardians.
2. Driver: ``start`` (``in_progress``, odometer), ``end`` (``completed``; km from the odometer pair, else from the GPS
   trace), ``stop-event`` (arrived / departed — manual or the GPS geofence), passenger ``scan`` (ID-card / app QR →
   ``board | alight``; 409 ``NOT_ALLOCATED``; ``warning=FEE_SUSPENDED``), manifest per stop with masked phones;
   ``delay_minutes`` = arrival − scheduled stop time; > 15 min → ``transport.trip_delayed`` (once per trip).
3. Guardians get ``transport.boarded`` / ``transport.alighted`` (``transport.notify_boarding``).

Odometer readings live in Redis for the trip's life (``transport:odo:{trip}``) and in the audit log — the section 20 trip
row has no odometer columns.
"""

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.authz.masking import mask_value
from app.core.errors import APIError, ErrorCode
from app.core.tenancy import institution_tz
from app.enums.transport import DELAY_ALERT_MIN, LIVE_ALLOCATION
from app.models.academic import AcademicTerm
from app.models.hr import Staff
from app.models.platform import Holiday
from app.models.students import Student
from app.models.transport import (
    TransportAllocation,
    TransportRoute,
    TransportStop,
    TransportTrip,
    TripPassengerEvent,
    TripStopEvent,
    Vehicle,
)
from app.schemas.transport import (
    ManifestPassenger,
    ManifestResponse,
    ManifestStop,
    PassengerScanRequest,
    PassengerScanResponse,
    StopEventIn,
    TripCancel,
    TripCreate,
    TripEndRequest,
    TripOut,
    TripScheduleRequest,
    TripScheduleSummary,
    TripStartRequest,
)
from app.services.transport.common import TransportBase, my_staff_ids, now_utc, rule, trip_predicate


async def _redis() -> Any:
    from app.db.session import redis_client

    return redis_client


class TripService(TransportBase):
    # ---- read -------------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[TransportTrip]) -> list[TripOut]:
        if not rows:
            return []
        ids = [t.id for t in rows]
        route_ids = {t.route_id for t in rows}
        routes = {
            r.id: r
            for r in (await self.db.execute(select(TransportRoute).where(TransportRoute.id.in_(route_ids)))).scalars()
        }
        vehicles = {
            v.id: v
            for v in (
                await self.db.execute(select(Vehicle).where(Vehicle.id.in_({t.vehicle_id for t in rows})))
            ).scalars()
        }
        drivers = {
            s.id: s.full_name
            for s in (
                await self.db.execute(
                    select(Staff).where(
                        Staff.id.in_({t.driver_staff_id for t in rows if t.driver_staff_id} or {uuid.uuid4()})
                    )
                )
            ).scalars()
        }
        stops: dict[uuid.UUID, list[TransportStop]] = {r: [] for r in route_ids}
        for s in (
            await self.db.execute(
                select(TransportStop).where(TransportStop.route_id.in_(route_ids)).order_by(TransportStop.sequence)
            )
        ).scalars():
            stops[s.route_id].append(s)
        events: dict[uuid.UUID, dict[uuid.UUID, TripStopEvent]] = {t: {} for t in ids}
        for e in (await self.db.execute(select(TripStopEvent).where(TripStopEvent.trip_id.in_(ids)))).scalars():
            events[e.trip_id][e.stop_id] = e
        boarded: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(TripPassengerEvent.trip_id, func.count(func.distinct(TripPassengerEvent.person_id)))
                    .where(TripPassengerEvent.trip_id.in_(ids), TripPassengerEvent.event == "board")
                    .group_by(TripPassengerEvent.trip_id)
                )
            ).all()  # type: ignore[arg-type]
        )
        manifest: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(TransportAllocation.route_id, func.count())
                    .where(TransportAllocation.route_id.in_(route_ids), TransportAllocation.status.in_(LIVE_ALLOCATION))
                    .group_by(TransportAllocation.route_id)
                )
            ).all()  # type: ignore[arg-type]
        )
        tz = institution_tz(await self.institution())
        out = []
        for t in rows:
            rs = stops.get(t.route_id, [])
            if t.direction == "drop":
                rs = list(reversed(rs))
            ev = events[t.id]
            done = [s for s in rs if s.id in ev and ev[s.id].arrived_at]
            nxt = next((s for s in rs if s.id not in ev or not ev[s.id].arrived_at), None)
            r, v = routes.get(t.route_id), vehicles.get(t.vehicle_id)
            out.append(
                TripOut(
                    id=t.id,
                    route_id=t.route_id,
                    route_code=r.code if r else None,
                    vehicle_id=t.vehicle_id,
                    vehicle_registration=v.registration_no if v else None,
                    driver_staff_id=t.driver_staff_id,
                    driver_name=drivers.get(t.driver_staff_id) if t.driver_staff_id else None,
                    trip_date=t.trip_date,
                    direction=t.direction,
                    status=t.status,
                    started_at=t.started_at,
                    ended_at=t.ended_at,
                    stops_total=len(rs),
                    stops_done=len(done),
                    progress_pct=int(100 * len(done) / len(rs)) if rs else 0,
                    next_stop=nxt.name if nxt and t.status == "in_progress" else None,
                    delay_minutes=self._delay(t, rs, ev, tz),
                    boarded=int(boarded.get(t.id, 0)),
                    manifest=int(manifest.get(t.route_id, 0)),
                )
            )
        return out

    @staticmethod
    def _delay(t: TransportTrip, stops: list[TransportStop], ev: dict[uuid.UUID, TripStopEvent], tz: Any) -> int | None:
        worst: int | None = None
        for s in stops:
            e = ev.get(s.id)
            planned = s.pickup_time if t.direction == "pickup" else s.drop_time
            if e is None or e.arrived_at is None or planned is None:
                continue
            sched = datetime.combine(t.trip_date, planned, tzinfo=tz)
            d = int((e.arrived_at - sched).total_seconds() // 60)
            worst = d if worst is None else max(worst, d)
        return worst

    async def list_trips(
        self, on: date | None = None, route_id: uuid.UUID | None = None, status: str | None = None
    ) -> list[TripOut]:
        q = select(TransportTrip).where(TransportTrip.institution_id == self.inst, trip_predicate(self.principal))
        q = q.where(TransportTrip.trip_date == (on or await self.today()))
        if route_id:
            q = q.where(TransportTrip.route_id == route_id)
        if status:
            q = q.where(TransportTrip.status == status)
        return await self.outs(
            list(
                (await self.db.execute(q.order_by(TransportTrip.direction.desc(), TransportTrip.created_at))).scalars()
            )
        )

    async def driver_trips(self, on: date | None = None) -> list[TripOut]:
        self.require("driver")
        q = select(TransportTrip).where(
            TransportTrip.institution_id == self.inst,
            TransportTrip.trip_date == (on or await self.today()),
            TransportTrip.driver_staff_id.in_(my_staff_ids(self.principal)),
        )
        return await self.outs(list((await self.db.execute(q.order_by(TransportTrip.direction.desc()))).scalars()))

    async def get(self, trip_id: uuid.UUID) -> TripOut:
        t = await self.trip(trip_id)
        out = (await self.outs([t]))[0]
        out.km = await self._km(t)
        return out

    # ---- schedule ---------------------------------------------------------------------------------------------------------
    async def _working(self, d: date, college_id: uuid.UUID | None) -> bool:
        days = await self.setting("transport", "working_days")
        if d.weekday() not in (days if isinstance(days, list) and days else [0, 1, 2, 3, 4, 5]):
            return False
        hol = (
            await self.db.execute(
                select(Holiday.id).where(
                    Holiday.institution_id == self.inst,
                    Holiday.deleted_at.is_(None),
                    Holiday.holiday_date <= d,
                    func.coalesce(Holiday.end_date, Holiday.holiday_date) >= d,
                    Holiday.applies_to.in_(("all", "students")),
                    or_(Holiday.college_id.is_(None), Holiday.college_id == college_id),
                )
            )
        ).first()
        if hol is not None:
            return False
        term = (
            await self.db.execute(
                select(AcademicTerm.id).where(
                    AcademicTerm.institution_id == self.inst,
                    AcademicTerm.start_date <= d,
                    AcademicTerm.end_date >= d,
                )
            )
        ).first()
        return term is not None

    async def schedule(self, body: TripScheduleRequest) -> TripScheduleSummary:
        self.require("manage")
        if body.date_to < body.date_from or (body.date_to - body.date_from).days > 62:  # noqa: PLR2004
            raise APIError(422, ErrorCode.VALIDATION, "Schedule at most two months at a time")
        q = select(TransportRoute).where(
            TransportRoute.institution_id == self.inst,
            TransportRoute.is_active.is_(True),
            TransportRoute.vehicle_id.is_not(None),
        )
        if body.route_ids:
            q = q.where(TransportRoute.id.in_(body.route_ids))
        routes = list((await self.db.execute(q)).scalars())
        vehicles = {
            v.id: v
            for v in (
                await self.db.execute(
                    select(Vehicle).where(Vehicle.id.in_({r.vehicle_id for r in routes} or {uuid.uuid4()}))
                )
            ).scalars()
        }
        existing = {
            (t.route_id, t.trip_date, t.direction)
            for t in (
                await self.db.execute(
                    select(TransportTrip).where(
                        TransportTrip.institution_id == self.inst,
                        TransportTrip.trip_date.between(body.date_from, body.date_to),
                    )
                )
            ).scalars()
        }
        out = TripScheduleSummary()
        blocked: set[str] = set()
        d = body.date_from
        while d <= body.date_to:
            any_day = False
            for r in routes:
                v = vehicles.get(r.vehicle_id)  # type: ignore[arg-type]
                if v is None or v.status != "active":
                    if v is not None:
                        blocked.add(v.registration_no)
                    continue
                if not await self._working(d, r.college_id):
                    continue
                any_day = True
                for direction in ("pickup", "drop"):
                    if (r.id, d, direction) in existing:
                        continue
                    self.db.add(
                        TransportTrip(
                            institution_id=self.inst,
                            route_id=r.id,
                            vehicle_id=v.id,
                            driver_staff_id=v.driver_staff_id,
                            trip_date=d,
                            direction=direction,
                        )
                    )
                    out.created += 1
            if not any_day:
                out.skipped_days.append(d)
            d += timedelta(days=1)
        await self.db.flush()
        out.blocked_vehicles = sorted(blocked)
        await self._emit(
            "transport.trip_scheduled",
            {"from": body.date_from.isoformat(), "to": body.date_to.isoformat(), "created": out.created},
            "transport_trip",
            None,
        )
        return out

    async def create(self, body: TripCreate) -> TripOut:
        self.require("manage")
        r = await self.route(body.route_id)
        vid = body.vehicle_id or r.vehicle_id
        if vid is None:
            raise APIError(422, ErrorCode.VALIDATION, "The route has no vehicle — pass vehicle_id")
        v = await self.vehicle(vid)
        if v.status != "active":
            raise rule("The vehicle is not active", "VEHICLE_BLOCKED", status_=v.status)
        t = TransportTrip(
            institution_id=self.inst,
            route_id=r.id,
            vehicle_id=v.id,
            driver_staff_id=body.driver_staff_id or v.driver_staff_id,
            trip_date=body.trip_date,
            direction=body.direction,
        )
        self.db.add(t)
        await self.db.flush()
        await self._audit(
            "create", "transport_trip", t.id, None, {"route": r.code, "date": body.trip_date.isoformat(), "adhoc": True}
        )
        return (await self.outs([t]))[0]

    async def cancel(self, trip_id: uuid.UUID, body: TripCancel) -> TripOut:
        self.require("manage")
        t = await self.trip(trip_id, for_update=True)
        if t.status in ("completed", "cancelled"):
            raise rule("The trip is already over", "TRIP_OVER")
        t.status = "cancelled"
        r = await self.route(t.route_id, any_scope=True)
        users = await self.passenger_users(t.route_id)
        await self._notify(
            "transport.trip_cancelled",
            users,
            {"route": r.name, "date": t.trip_date.isoformat(), "direction": t.direction, "reason": body.reason},
            guardians=True,
        )
        await self._audit("cancel", "transport_trip", t.id, None, {"reason": body.reason})
        await self._emit(
            "transport.trip_cancelled", {"trip_id": str(t.id), "reason": body.reason}, "transport_trip", t.id
        )
        return (await self.outs([t]))[0]

    # ---- driver ------------------------------------------------------------------------------------------------------------
    async def own_trip(self, trip_id: uuid.UUID, *, for_update: bool = False) -> TransportTrip:
        t = await self.trip(trip_id, for_update=for_update)
        if self.can("transport", "manage"):
            return t
        mine = (await self.db.execute(my_staff_ids(self.principal))).scalars().all()
        if t.driver_staff_id not in mine:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Not your trip")
        return t

    async def start(self, trip_id: uuid.UUID, body: TripStartRequest) -> TripOut:
        self.require("driver")
        t = await self.own_trip(trip_id, for_update=True)
        if t.status != "scheduled":
            raise rule("Only a scheduled trip can start", "TRIP_NOT_SCHEDULED", status_=t.status)
        if body.vehicle_id and body.vehicle_id != t.vehicle_id:
            v = await self.vehicle(body.vehicle_id)
            if v.status != "active":
                raise rule("The vehicle is not active", "VEHICLE_BLOCKED")
            t.vehicle_id = v.id
        t.status, t.started_at = "in_progress", now_utc()
        if body.odometer is not None:
            await (await _redis()).set(f"transport:odo:{t.id}", body.odometer, ex=86400 * 2)
        await self.db.flush()
        await self._audit("start", "transport_trip", t.id, None, {"odometer": body.odometer})
        await self._emit(
            "transport.trip_started", {"trip_id": str(t.id), "route_id": str(t.route_id)}, "transport_trip", t.id
        )
        return (await self.outs([t]))[0]

    async def end(self, trip_id: uuid.UUID, body: TripEndRequest) -> TripOut:
        self.require("driver")
        t = await self.own_trip(trip_id, for_update=True)
        if t.status != "in_progress":
            raise rule("Only a running trip can end", "TRIP_NOT_RUNNING", status_=t.status)
        t.status, t.ended_at = "completed", now_utc()
        km: float | None = None
        r = await _redis()
        start = await r.get(f"transport:odo:{t.id}")
        if body.odometer is not None and start is not None and body.odometer >= int(start):
            km = float(body.odometer - int(start))
            await r.set(f"transport:km:{t.id}", km, ex=86400 * 120)
        await self.db.flush()
        await self._audit("end", "transport_trip", t.id, None, {"odometer": body.odometer, "km": km})
        await self._emit("transport.trip_ended", {"trip_id": str(t.id), "km": km}, "transport_trip", t.id)
        await r.hdel(f"transport:live:{self.inst}", str(t.vehicle_id))
        out = (await self.outs([t]))[0]
        out.km = km if km is not None else await self._km(t)
        return out

    async def _km(self, t: TransportTrip) -> float | None:
        stored = await (await _redis()).get(f"transport:km:{t.id}")
        if stored is not None:
            return float(stored)
        from app.services.transport.gps_service import GpsService

        tr = await GpsService(self.db, self.principal, self.request, self.inst).trace_points(t.id)
        return round(tr[1], 1) if tr[0] else None

    async def stop_event(self, trip_id: uuid.UUID, body: StopEventIn, *, auto: bool = False) -> dict[str, Any]:
        if not auto:
            self.require("driver")
            t = await self.own_trip(trip_id)
        else:
            t = await self.trip(trip_id, any_scope=True)
        if t.status != "in_progress":
            raise rule("The trip is not running", "TRIP_NOT_RUNNING")
        s = (
            await self.db.execute(
                select(TransportStop).where(TransportStop.id == body.stop_id, TransportStop.route_id == t.route_id)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(422, ErrorCode.VALIDATION, "The stop is not on this trip's route")
        e = (
            await self.db.execute(
                select(TripStopEvent).where(TripStopEvent.trip_id == t.id, TripStopEvent.stop_id == s.id)
            )
        ).scalar_one_or_none()
        if e is None:
            e = TripStopEvent(institution_id=self.inst, trip_id=t.id, stop_id=s.id)
            self.db.add(e)
        at = body.at or now_utc()
        if body.event == "arrived":
            if e.arrived_at is not None and auto:
                return {"stop_id": str(s.id), "duplicate": True}
            e.arrived_at = e.arrived_at or at
        else:
            e.arrived_at = e.arrived_at or at
            e.departed_at = at
        await self.db.flush()
        await self._emit(
            f"transport.stop_{body.event}",
            {"trip_id": str(t.id), "stop_id": str(s.id), "auto": auto},
            "transport_trip",
            t.id,
        )
        if body.event == "arrived":
            await self._delay_check(t, s, e)
        return {"stop_id": str(s.id), "arrived_at": e.arrived_at, "departed_at": e.departed_at}

    async def _delay_check(self, t: TransportTrip, s: TransportStop, e: TripStopEvent) -> None:
        planned = s.pickup_time if t.direction == "pickup" else s.drop_time
        if planned is None or e.arrived_at is None:
            return
        tz = institution_tz(await self.institution())
        delay = int((e.arrived_at - datetime.combine(t.trip_date, planned, tzinfo=tz)).total_seconds() // 60)
        if delay <= DELAY_ALERT_MIN:
            return
        if not await (await _redis()).set(f"transport:delayed:{t.id}", 1, ex=86400, nx=True):
            return
        r = await self.route(t.route_id, any_scope=True)
        users = await self.passenger_users(t.route_id)
        await self._notify("transport.trip_delayed", users, {"route": r.name, "minutes": delay}, guardians=True)
        await self._notify(
            "transport.trip_delayed", [], {"route": r.name, "minutes": delay}, audience=await self.manager_audience()
        )
        await self._emit(
            "transport.trip_delayed", {"trip_id": str(t.id), "delay_minutes": delay}, "transport_trip", t.id
        )

    async def manifest(self, trip_id: uuid.UUID) -> ManifestResponse:
        t = await self.own_trip(trip_id) if not self.can("transport", "view_all") else await self.trip(trip_id)
        stops = list(
            (
                await self.db.execute(
                    select(TransportStop).where(TransportStop.route_id == t.route_id).order_by(TransportStop.sequence)
                )
            ).scalars()
        )
        if t.direction == "drop":
            stops.reverse()
        ev = {
            e.stop_id: e
            for e in (await self.db.execute(select(TripStopEvent).where(TripStopEvent.trip_id == t.id))).scalars()
        }
        allocs = (
            (
                await self.db.execute(
                    select(TransportAllocation).where(
                        TransportAllocation.route_id == t.route_id,
                        TransportAllocation.status.in_(LIVE_ALLOCATION),
                        or_(TransportAllocation.from_on.is_(None), TransportAllocation.from_on <= t.trip_date),
                    )
                )
            )
            .scalars()
            .all()
        )
        pe = (
            (await self.db.execute(select(TripPassengerEvent).where(TripPassengerEvent.trip_id == t.id)))
            .scalars()
            .all()
        )
        boarded = {p.person_id for p in pe if p.event == "board"}
        alighted = {p.person_id for p in pe if p.event == "alight"}
        people: dict[uuid.UUID, tuple[str, str | None]] = {}
        stu = [a.person_id for a in allocs if a.person_type == "student"]
        stf = [a.person_id for a in allocs if a.person_type == "staff"]
        if stu:
            for su in (await self.db.execute(select(Student).where(Student.id.in_(stu)))).scalars():
                people[su.id] = (su.full_name, su.phone)
        if stf:
            for sf in (await self.db.execute(select(Staff).where(Staff.id.in_(stf)))).scalars():
                people[sf.id] = (sf.full_name, sf.phone)
        out = ManifestResponse(trip_id=t.id, total=len(allocs), boarded=len(boarded))
        for s in stops:
            e = ev.get(s.id)
            out.stops.append(
                ManifestStop(
                    stop_id=s.id,
                    stop=s.name,
                    sequence=s.sequence,
                    arrived_at=e.arrived_at if e else None,
                    departed_at=e.departed_at if e else None,
                    passengers=[
                        ManifestPassenger(
                            person_type=a.person_type,
                            person_id=a.person_id,
                            name=people.get(a.person_id, ("?", None))[0],
                            phone=mask_value(people.get(a.person_id, ("?", None))[1], "phone"),
                            boarded=a.person_id in boarded,
                            alighted=a.person_id in alighted,
                            suspended=a.status == "suspended",
                        )
                        for a in allocs
                        if a.stop_id == s.id
                    ],
                )
            )
        return out

    async def _resolve(self, body: PassengerScanRequest) -> tuple[str, uuid.UUID]:
        if body.person_id is not None:
            return body.person_type, body.person_id
        raw = (body.qr or "").strip()
        if not raw:
            raise APIError(422, ErrorCode.VALIDATION, "qr or person_id is required")
        kind = "student"
        for prefix in ("staff:", "student:"):
            if raw.lower().startswith(prefix):
                kind, raw = prefix[:-1], raw[len(prefix) :]
        raw = raw.rsplit("/", 1)[-1]  # verification URLs end in the id
        try:
            return kind, uuid.UUID(raw)
        except ValueError:
            pass
        st = (
            await self.db.execute(
                select(Student.id).where(Student.institution_id == self.inst, Student.registration_number == raw)
            )
        ).scalar_one_or_none()
        if st is not None:
            return "student", st
        sf = (
            await self.db.execute(select(Staff.id).where(Staff.institution_id == self.inst, Staff.employee_id == raw))
        ).scalar_one_or_none()
        if sf is not None:
            return "staff", sf
        raise rule("Unknown ID card", "UNKNOWN_QR", 404)

    async def passenger_scan(self, trip_id: uuid.UUID, body: PassengerScanRequest) -> PassengerScanResponse:
        self.require("driver")
        t = await self.own_trip(trip_id)
        if t.status != "in_progress":
            raise rule("Start the trip before scanning", "TRIP_NOT_RUNNING")
        kind, pid = await self._resolve(body)
        a = (
            (
                await self.db.execute(
                    select(TransportAllocation).where(
                        TransportAllocation.route_id == t.route_id,
                        TransportAllocation.person_type == kind,
                        TransportAllocation.person_id == pid,
                        TransportAllocation.status.in_(LIVE_ALLOCATION),
                    )
                )
            )
            .scalars()
            .first()
        )
        if a is None:
            raise rule("The passenger is not allocated to this route", "NOT_ALLOCATED")
        ev = TripPassengerEvent(
            institution_id=self.inst,
            trip_id=t.id,
            person_type=kind,
            person_id=pid,
            event=body.event,
            stop_id=body.stop_id or a.stop_id,
            source="qr" if body.qr else "app",
        )
        self.db.add(ev)
        await self.db.flush()
        await self.db.refresh(ev)
        model: Any = Student if kind == "student" else Staff
        name = (await self.db.execute(select(model).where(model.id == pid))).scalar_one()
        await self._emit(
            f"transport.passenger_{'boarded' if body.event == 'board' else 'alighted'}",
            {
                "trip_id": str(t.id),
                "person_type": kind,
                "person_id": str(pid),
                "stop_id": str(ev.stop_id) if ev.stop_id else None,
            },
            "transport_trip",
            t.id,
        )
        notify = await self.setting("transport", "notify_boarding")
        if kind == "student" and (notify is None or bool(notify)):
            guardians = await self.guardian_users([pid])
            await self._notify(
                "transport.boarded" if body.event == "board" else "transport.alighted",
                guardians,
                {
                    "student": name.full_name,
                    "at": ev.occurred_at.astimezone(institution_tz(await self.institution())).strftime("%H:%M"),
                },
            )
        return PassengerScanResponse(
            event_id=ev.id,
            person_name=name.full_name,
            event=ev.event,
            stop_id=ev.stop_id,
            occurred_at=ev.occurred_at,
            warning="FEE_SUSPENDED" if a.status == "suspended" else None,
        )

    # ---- Beat ----------------------------------------------------------------------------------------------------------------
    async def autoclose(self) -> int:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(TransportTrip).where(
                        TransportTrip.institution_id == self.inst,
                        TransportTrip.status.in_(("in_progress", "scheduled")),
                        TransportTrip.trip_date < today,
                    )
                )
            )
            .scalars()
            .all()
        )
        for t in rows:
            if t.status == "in_progress":
                t.status, t.ended_at = "completed", now_utc()
                await self._audit("autoclose", "transport_trip", t.id, None, {"flag": "auto_closed"})
            else:
                t.status = "cancelled"
                await self._audit("autoclose", "transport_trip", t.id, None, {"flag": "never_started"})
        return len(rows)

    async def schedule_ahead(self, days: int = 7) -> int:
        today = await self.today()
        return (await self.schedule(TripScheduleRequest(date_from=today, date_to=today + timedelta(days=days)))).created
