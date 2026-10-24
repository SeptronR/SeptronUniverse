"""GPS — Prompts/21 §21.6 ``gps_service`` (``transport.gps_live``).

1. Ingestion by a device token (``gps_devices.token_hash`` = sha256) or by the driver's JWT for the running trip; batches
   (offline-buffered) are deduplicated by ``(vehicle_id, recorded_at)``; a single-ping request within 5 s of the previous
   one from the same vehicle is dropped (rate limit). Rows go to the partitioned ``vehicle_gps_logs``; the latest
   position is kept in the Redis hash ``transport:live:{institution}`` and published on ``fleet:{institution}`` (the
   Phase 01 WebSocket hub relays it to fleet readers).
2. ETA = distance along the remaining stops / moving average speed (fallback 20 km/h); a ping within 100 m of the next
   stop records ``arrived`` (geofence); > 500 m off the stop polyline for 3 consecutive pings → ``transport.route_deviation``
   (managers); ETA ≤ ``transport.eta_notify_minutes`` → ``transport.bus_approaching`` once per trip and stop to that
   stop's passengers and their guardians.
3. Replay: the trip trace downsampled to ≤ 500 points, JSON or GPX; raw pings are kept 90 days (Beat drops older
   monthly partitions and prunes the DEFAULT partition).
4. Live scope: fleet readers see every vehicle (college admins their college's), drivers their own, passengers /
   guardians only the vehicle of their (ward's) route while its trip is running.
"""

import hashlib
import json
import math
import secrets
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from app.core.errors import APIError, ErrorCode
from app.enums.transport import DEVIATION_M, DEVIATION_PINGS, GEOFENCE_M, GPS_RETENTION_DAYS, LIVE_ALLOCATION
from app.models.transport import (
    GpsDevice,
    TransportAllocation,
    TransportRoute,
    TransportStop,
    TransportTrip,
    TripStopEvent,
    Vehicle,
    VehicleGpsLog,
)
from app.repositories.fee_scope import own_student_ids
from app.schemas.transport import (
    GpsBatch,
    GpsDeviceIn,
    GpsDeviceOut,
    GpsIngestResult,
    LiveVehicle,
    StopEventIn,
    TracePoint,
    TraceResponse,
)
from app.services.transport.common import (
    TransportBase,
    _ids,
    haversine_m,
    institution_scope,
    is_reader,
    my_staff_ids,
    now_utc,
    rule,
    segment_distance_m,
)

MAX_TRACE = 500
DEFAULT_SPEED_KMH = 20.0


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def token_institution(token: str) -> uuid.UUID | None:
    """Tenant of an active device token, read on the platform session (the device route has no tenant context yet)."""
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as pdb:
        row = (
            await pdb.execute(
                select(GpsDevice.institution_id).where(
                    GpsDevice.token_hash == token_hash(token), GpsDevice.is_active.is_(True)
                )
            )
        ).first()
    return uuid.UUID(str(row[0])) if row else None


async def _redis() -> Any:
    from app.db.session import redis_client

    return redis_client


class GpsService(TransportBase):
    # ---- devices -----------------------------------------------------------------------------------------------------------
    async def device_outs(self, rows: list[GpsDevice], token: str | None = None) -> list[GpsDeviceOut]:
        regs: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(Vehicle.id, Vehicle.registration_no).where(
                        Vehicle.id.in_({d.vehicle_id for d in rows if d.vehicle_id} or {uuid.uuid4()})
                    )
                )
            ).all()  # type: ignore[arg-type]
        )
        return [
            GpsDeviceOut(
                id=d.id,
                device_id=d.device_id,
                vehicle_id=d.vehicle_id,
                vehicle_registration=regs.get(d.vehicle_id),
                is_active=d.is_active,
                last_seen_at=d.last_seen_at,
                token=token,
            )
            for d in rows
        ]

    async def devices(self) -> list[GpsDeviceOut]:
        self.require("manage")
        rows = (
            await self.db.execute(
                select(GpsDevice).where(GpsDevice.institution_id == self.inst).order_by(GpsDevice.device_id)
            )
        ).scalars()
        return await self.device_outs(list(rows))

    async def _device(self, device_id: uuid.UUID) -> GpsDevice:
        d = (
            await self.db.execute(
                select(GpsDevice).where(GpsDevice.id == device_id, GpsDevice.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if d is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "GPS device not found")
        return d

    async def create_device(self, body: GpsDeviceIn) -> GpsDeviceOut:
        self.require("manage")
        if (
            await self.db.execute(
                select(GpsDevice.id).where(GpsDevice.institution_id == self.inst, GpsDevice.device_id == body.device_id)
            )
        ).first():
            raise rule("Device id already registered", "DUPLICATE_DEVICE")
        token = "gps_" + secrets.token_urlsafe(32)
        d = GpsDevice(
            institution_id=self.inst, device_id=body.device_id, vehicle_id=body.vehicle_id, token_hash=token_hash(token)
        )
        self.db.add(d)
        await self.db.flush()
        if body.vehicle_id:
            v = await self.vehicle(body.vehicle_id, for_update=True)
            v.gps_device_id = d.id
        await self._audit(
            "create", "gps_device", d.id, None, {"device_id": d.device_id, "vehicle_id": str(body.vehicle_id)}
        )
        return (await self.device_outs([d], token))[0]

    async def rotate(self, device_id: uuid.UUID) -> GpsDeviceOut:
        self.require("manage")
        d = await self._device(device_id)
        token = "gps_" + secrets.token_urlsafe(32)
        d.token_hash = token_hash(token)
        await self._audit("rotate_token", "gps_device", d.id, None, None)
        return (await self.device_outs([d], token))[0]

    async def delete_device(self, device_id: uuid.UUID) -> None:
        self.require("manage")
        d = await self._device(device_id)
        d.is_active = False
        if d.vehicle_id:
            v = (await self.db.execute(select(Vehicle).where(Vehicle.id == d.vehicle_id))).scalar_one_or_none()
            if v is not None and v.gps_device_id == d.id:
                v.gps_device_id = None
        await self._audit("deactivate", "gps_device", d.id, None, None)

    # ---- ingestion ----------------------------------------------------------------------------------------------------------
    @staticmethod
    async def device_for_token(db: Any, token: str) -> GpsDevice | None:
        row: GpsDevice | None = (
            await db.execute(
                select(GpsDevice).where(GpsDevice.token_hash == token_hash(token), GpsDevice.is_active.is_(True))
            )
        ).scalar_one_or_none()
        return row

    async def _running_trip(self, vehicle_id: uuid.UUID) -> TransportTrip | None:
        return (
            (
                await self.db.execute(
                    select(TransportTrip)
                    .where(TransportTrip.vehicle_id == vehicle_id, TransportTrip.status == "in_progress")
                    .order_by(TransportTrip.started_at.desc())
                )
            )
            .scalars()
            .first()
        )

    async def ingest_device(self, device: GpsDevice, body: GpsBatch) -> GpsIngestResult:
        if device.vehicle_id is None:
            raise rule("The device is not fitted to a vehicle", "DEVICE_UNASSIGNED", 422)
        device.last_seen_at = now_utc()
        trip = await self._running_trip(device.vehicle_id)
        return await self._ingest(device.vehicle_id, trip, body)

    async def ingest_driver(self, body: GpsBatch) -> GpsIngestResult:
        self.require("driver")
        from app.services.transport.trip_service import TripService

        trip: TransportTrip | None
        if body.trip_id:
            trip = await TripService(self.db, self.principal, self.request, self.inst).own_trip(body.trip_id)
        else:
            trip = (
                (
                    await self.db.execute(
                        select(TransportTrip).where(
                            TransportTrip.status == "in_progress",
                            TransportTrip.driver_staff_id.in_(my_staff_ids(self.principal)),
                        )
                    )
                )
                .scalars()
                .first()
            )
        if trip is None or trip.status != "in_progress":
            raise rule("Start a trip before sending GPS", "TRIP_NOT_RUNNING")
        return await self._ingest(trip.vehicle_id, trip, body)

    async def _ingest(self, vehicle_id: uuid.UUID, trip: TransportTrip | None, body: GpsBatch) -> GpsIngestResult:
        r = await _redis()
        res = GpsIngestResult()
        if len(body.pings) == 1 and not await r.set(f"transport:rl:{vehicle_id}", 1, ex=5, nx=True):
            res.rate_limited = 1
            return res
        pings = sorted({p.recorded_at: p for p in body.pings}.values(), key=lambda p: p.recorded_at)
        res.duplicates = len(body.pings) - len(pings)
        seen = set(
            (
                await self.db.execute(
                    select(VehicleGpsLog.recorded_at).where(
                        VehicleGpsLog.vehicle_id == vehicle_id,
                        VehicleGpsLog.recorded_at.between(pings[0].recorded_at, pings[-1].recorded_at),
                    )
                )
            ).scalars()
        )
        fresh = [p for p in pings if p.recorded_at not in seen]
        res.duplicates += len(pings) - len(fresh)
        for p in fresh:
            self.db.add(
                VehicleGpsLog(
                    institution_id=self.inst,
                    vehicle_id=vehicle_id,
                    trip_id=trip.id if trip else None,
                    lat=p.lat,
                    lng=p.lng,
                    speed_kmh=p.speed_kmh,
                    heading=p.heading,
                    recorded_at=p.recorded_at,
                )
            )
        res.accepted = len(fresh)
        await self.db.flush()
        if not fresh:
            return res
        last = fresh[-1]
        live: dict[str, Any] = {
            "vehicle_id": str(vehicle_id),
            "trip_id": str(trip.id) if trip else None,
            "route_id": str(trip.route_id) if trip else None,
            "lat": last.lat,
            "lng": last.lng,
            "speed": last.speed_kmh,
            "heading": last.heading,
            "at": last.recorded_at.isoformat(),
        }
        if trip is not None:
            extra = await self._trip_logic(trip, fresh, res)
            live.update(extra)
        await r.hset(f"transport:live:{self.inst}", str(vehicle_id), json.dumps(live, default=str))
        await r.publish(f"fleet:{self.inst}", json.dumps({"type": "transport.live", **live}, default=str))
        return res

    async def _trip_logic(self, trip: TransportTrip, pings: list[Any], res: GpsIngestResult) -> dict[str, Any]:
        from app.services.transport.trip_service import TripService

        r = await _redis()
        stops = list(
            (
                await self.db.execute(
                    select(TransportStop)
                    .where(TransportStop.route_id == trip.route_id)
                    .order_by(TransportStop.sequence)
                )
            ).scalars()
        )
        if trip.direction == "drop":
            stops.reverse()
        coords = [s for s in stops if s.lat is not None and s.lng is not None]
        arrived = {
            e.stop_id
            for e in (await self.db.execute(select(TripStopEvent).where(TripStopEvent.trip_id == trip.id))).scalars()
            if e.arrived_at
        }
        trips = TripService(self.db, None, self.request, self.inst)
        for p in pings:
            for s in coords:
                if s.id in arrived:
                    continue
                if haversine_m(p.lat, p.lng, float(s.lat), float(s.lng)) <= GEOFENCE_M:  # type: ignore[arg-type]
                    await trips.stop_event(
                        trip.id, StopEventIn(stop_id=s.id, event="arrived", at=p.recorded_at), auto=True
                    )
                    arrived.add(s.id)
                    res.stop_events += 1
            if len(coords) >= 2:  # noqa: PLR2004
                line = [(float(s.lat), float(s.lng)) for s in coords]  # type: ignore[arg-type]
                off = min(segment_distance_m(p.lat, p.lng, line[i], line[i + 1]) for i in range(len(line) - 1))
                key = f"transport:dev:{trip.id}"
                if off > DEVIATION_M:
                    n = await r.incr(key)
                    await r.expire(key, 3600)
                    if n == DEVIATION_PINGS:
                        res.alerts.append("route_deviation")
                        await self._notify(
                            "transport.route_deviation",
                            [],
                            {"trip_id": str(trip.id), "metres": int(off)},
                            audience=await self.manager_audience(),
                        )
                        await self._emit(
                            "transport.route_deviation",
                            {"trip_id": str(trip.id), "metres": int(off)},
                            "transport_trip",
                            trip.id,
                        )
                else:
                    await r.delete(key)
        last = pings[-1]
        speeds = [float(p.speed_kmh) for p in pings if p.speed_kmh]
        if speeds:
            await r.set(f"transport:spd:{trip.id}", sum(speeds) / len(speeds), ex=3600)
        avg = float(await r.get(f"transport:spd:{trip.id}") or 0) or DEFAULT_SPEED_KMH
        remaining = [s for s in coords if s.id not in arrived]
        etas: list[tuple[TransportStop, int]] = []
        dist, prev = 0.0, (last.lat, last.lng)
        for s in remaining:
            dist += haversine_m(prev[0], prev[1], float(s.lat), float(s.lng))  # type: ignore[arg-type]
            prev = (float(s.lat), float(s.lng))  # type: ignore[arg-type]
            etas.append((s, int(round(dist / 1000 / max(avg, 5.0) * 60))))
        notify_min = int(await self.setting("transport", "eta_notify_minutes") or 5)
        for s, eta in etas:
            if eta > notify_min:
                break
            if await r.sadd(f"transport:approach:{trip.id}", str(s.id)):
                await r.expire(f"transport:approach:{trip.id}", 86400)
                await self._approaching(trip, s, eta)
                res.alerts.append(f"bus_approaching:{s.name}")
        nxt = etas[0] if etas else None
        return {"next_stop": nxt[0].name if nxt else None, "eta_min": nxt[1] if nxt else None}

    async def _approaching(self, trip: TransportTrip, stop: TransportStop, eta: int) -> None:
        rows = (
            await self.db.execute(
                select(TransportAllocation.person_type, TransportAllocation.person_id).where(
                    TransportAllocation.route_id == trip.route_id,
                    TransportAllocation.stop_id == stop.id,
                    TransportAllocation.status.in_(LIVE_ALLOCATION),
                )
            )
        ).all()
        users: list[uuid.UUID] = []
        for kind in ("student", "staff"):
            users += list((await self.person_users(kind, [pid for t, pid in rows if t == kind])).values())
        users += await self.guardian_users([pid for t, pid in rows if t == "student"])
        await self._notify("transport.bus_approaching", users, {"stop": stop.name, "minutes": eta})
        await self._emit(
            "transport.bus_approaching",
            {"trip_id": str(trip.id), "stop_id": str(stop.id), "eta_min": eta},
            "transport_trip",
            trip.id,
        )

    # ---- live / replay -------------------------------------------------------------------------------------------------------
    async def _passenger_routes(self) -> set[uuid.UUID]:
        p = self.principal
        rows = (
            await self.db.execute(
                select(TransportAllocation.route_id).where(
                    TransportAllocation.institution_id == self.inst,
                    TransportAllocation.status.in_(LIVE_ALLOCATION),
                    (
                        (TransportAllocation.person_type == "student")
                        & TransportAllocation.person_id.in_(own_student_ids(p, wards=True, advisees=False))
                    )
                    | (
                        (TransportAllocation.person_type == "staff")
                        & TransportAllocation.person_id.in_(my_staff_ids(p))
                    ),
                )
            )
        ).scalars()
        return set(rows)

    async def live(self, route_id: uuid.UUID | None = None, vehicle_id: uuid.UUID | None = None) -> list[LiveVehicle]:
        r = await _redis()
        raw = await r.hgetall(f"transport:live:{self.inst}")
        items = [json.loads(v) for v in raw.values()]
        p = self.principal
        vehicles = {
            v.id: v
            for v in (await self.db.execute(select(Vehicle).where(Vehicle.institution_id == self.inst))).scalars()
        }
        routes = {
            x.id: x
            for x in (
                await self.db.execute(select(TransportRoute).where(TransportRoute.institution_id == self.inst))
            ).scalars()
        }
        allowed: set[uuid.UUID] | None = None  # None = all
        if not (p is None or getattr(p, "is_super_admin", False) or (is_reader(p) and institution_scope(p))):
            allowed = set()
            if is_reader(p) and _ids(p, "college"):
                allowed |= {v.id for v in vehicles.values() if v.college_id in _ids(p, "college")}
            if p.has("transport", "driver"):
                mine = set((await self.db.execute(my_staff_ids(p))).scalars())
                allowed |= {v.id for v in vehicles.values() if v.driver_staff_id in mine}
            mine_routes = await self._passenger_routes()
            running = set(
                (
                    await self.db.execute(
                        select(TransportTrip.vehicle_id).where(
                            TransportTrip.route_id.in_(mine_routes or {uuid.uuid4()}),
                            TransportTrip.status == "in_progress",
                        )
                    )
                ).scalars()
            )
            allowed |= running
        out = []
        for it in items:
            vid = uuid.UUID(it["vehicle_id"])
            if allowed is not None and vid not in allowed:
                continue
            if vehicle_id and vid != vehicle_id:
                continue
            rid = uuid.UUID(it["route_id"]) if it.get("route_id") else None
            if route_id and rid != route_id:
                continue
            v, rt = vehicles.get(vid), routes.get(rid) if rid else None
            out.append(
                LiveVehicle(
                    vehicle_id=vid,
                    registration_no=v.registration_no if v else None,
                    route=rt.name if rt else None,
                    route_id=rid,
                    trip_id=uuid.UUID(it["trip_id"]) if it.get("trip_id") else None,
                    lat=float(it["lat"]),
                    lng=float(it["lng"]),
                    speed=float(it["speed"]) if it.get("speed") is not None else None,
                    heading=it.get("heading"),
                    at=datetime.fromisoformat(it["at"]),
                    next_stop=it.get("next_stop"),
                    eta_min=it.get("eta_min"),
                    deviation=bool(await r.get(f"transport:dev:{it.get('trip_id')}")) if it.get("trip_id") else False,
                )
            )
        return out

    async def trace_points(self, trip_id: uuid.UUID) -> tuple[list[TracePoint], float, int]:
        rows = (
            (
                await self.db.execute(
                    select(VehicleGpsLog).where(VehicleGpsLog.trip_id == trip_id).order_by(VehicleGpsLog.recorded_at)
                )
            )
            .scalars()
            .all()
        )
        km = 0.0
        for a, b in zip(rows, rows[1:], strict=False):
            km += haversine_m(float(a.lat), float(a.lng), float(b.lat), float(b.lng)) / 1000
        step = max(1, math.ceil(len(rows) / MAX_TRACE))
        pts = [
            TracePoint(
                lat=float(x.lat),
                lng=float(x.lng),
                at=x.recorded_at,
                speed=float(x.speed_kmh) if x.speed_kmh is not None else None,
            )
            for x in rows[::step]
        ]
        return pts, km, len(rows)

    async def trace(self, trip_id: uuid.UUID) -> TraceResponse:
        t = await self.trip(trip_id, any_scope=True)
        p = self.principal
        visible = await self.trip_visible(t)
        if not visible and t.route_id in await self._passenger_routes() and t.status == "in_progress":
            visible = True
        if not visible and p is not None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Trip not found")
        pts, km, n = await self.trace_points(t.id)
        return TraceResponse(trip_id=t.id, points=pts, total_points=n, km=round(km, 2))

    async def trip_visible(self, t: TransportTrip) -> bool:
        from app.services.transport.common import trip_predicate

        return (
            await self.db.execute(
                select(TransportTrip.id).where(TransportTrip.id == t.id, trip_predicate(self.principal))
            )
        ).first() is not None

    @staticmethod
    def gpx(tr: TraceResponse) -> str:
        pts = "\n".join(
            f'      <trkpt lat="{p.lat:.6f}" lon="{p.lng:.6f}"><time>{p.at.isoformat()}</time></trkpt>'
            for p in tr.points
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="SeptronUniverse" xmlns="http://www.topografix.com/GPX/1/1">\n'
            f"  <trk><name>trip {tr.trip_id}</name>\n    <trkseg>\n{pts}\n    </trkseg>\n  </trk>\n</gpx>\n"
        )

    # ---- Beat ------------------------------------------------------------------------------------------------------------------
    async def partition_maintenance(self, today: date) -> dict[str, int]:
        """Create this and next month's partitions; drop monthly partitions wholly older than the retention window."""
        created = dropped = 0
        first = today.replace(day=1)
        for m in (first, (first + timedelta(days=32)).replace(day=1)):
            nxt = (m + timedelta(days=32)).replace(day=1)
            name = f"vehicle_gps_logs_y{m.year}m{m.month:02d}"
            exists = (await self.db.execute(text("SELECT to_regclass(:n)"), {"n": name})).scalar()
            if exists:
                continue
            try:
                async with self.db.begin_nested():
                    await self.db.execute(
                        text(
                            f"CREATE TABLE {name} PARTITION OF vehicle_gps_logs "  # noqa: S608 - generated name
                            f"FOR VALUES FROM ('{m.isoformat()}') TO ('{nxt.isoformat()}')"
                        )
                    )
                created += 1
            except Exception:  # noqa: BLE001 - rows of that month already sit in DEFAULT: keep using it
                continue
        cutoff = today - timedelta(days=GPS_RETENTION_DAYS)
        names = (
            (
                await self.db.execute(
                    text(
                        "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                        "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = 'vehicle_gps_logs'"
                    )
                )
            )
            .scalars()
            .all()
        )
        for n in names:
            if not n.startswith("vehicle_gps_logs_y"):
                continue
            y, mth = int(n[18:22]), int(n[23:25])
            upper = (date(y, mth, 1) + timedelta(days=32)).replace(day=1)
            if upper <= cutoff:
                await self.db.execute(text(f"DROP TABLE IF EXISTS {n}"))  # noqa: S608 - name from the catalogue
                dropped += 1
        await self.db.execute(text("DELETE FROM vehicle_gps_logs_default WHERE recorded_at < :c"), {"c": cutoff})
        return {"created": created, "dropped": dropped}

    async def live_cache_cleanup(self) -> int:
        r = await _redis()
        key = f"transport:live:{self.inst}"
        stale = []
        limit = now_utc() - timedelta(hours=1)
        for field, raw in (await r.hgetall(key)).items():
            try:
                if datetime.fromisoformat(json.loads(raw)["at"]) < limit:
                    stale.append(field)
            except (ValueError, KeyError, TypeError):
                stale.append(field)
        if stale:
            await r.hdel(key, *stale)
        return len(stale)

    async def ping_count(self, since: datetime) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(VehicleGpsLog)
                    .where(VehicleGpsLog.institution_id == self.inst, VehicleGpsLog.recorded_at >= since)
                )
            ).scalar_one()
        )
