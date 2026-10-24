"""Routes & stops — Prompts/21 §21.6 ``route_service``.

Routes with ordered stops (``sequence`` unique per route — the reorder endpoint renumbers 1..n through a negative pass so
the unique index never trips), per-stop ``fee_paise`` falling back to the route fee, coordinates and pickup / drop
times; capacity = the route vehicle's ``capacity``; a change of vehicle, times or stops notifies the allocated
passengers (``transport.route_changed``); route sheet as PDF; public list (names, stops, times — no vehicles).
"""

import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.transport import LIVE_ALLOCATION
from app.models.transport import TransportAllocation, TransportRoute, TransportStop, Vehicle
from app.schemas.transport import PublicRouteOut, RouteIn, RouteOut, RouteUpdate, StopIn, StopOut, StopsReorder
from app.services.students.common import snap
from app.services.transport.common import TransportBase, route_predicate, rule

KEYS = ("code", "name", "vehicle_id", "fee_paise", "distance_km", "is_active")


class RouteService(TransportBase):
    async def stops_of(self, route_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[TransportStop]]:
        out: dict[uuid.UUID, list[TransportStop]] = {r: [] for r in route_ids}
        if not route_ids:
            return out
        for s in (
            await self.db.execute(
                select(TransportStop).where(TransportStop.route_id.in_(route_ids)).order_by(TransportStop.sequence)
            )
        ).scalars():
            out[s.route_id].append(s)
        return out

    async def outs(self, rows: list[TransportRoute], *, with_stops: bool = True) -> list[RouteOut]:
        ids = [r.id for r in rows]
        stops = await self.stops_of(ids) if with_stops else {}
        vehicles = {
            v.id: v
            for v in (
                await self.db.execute(
                    select(Vehicle).where(
                        Vehicle.id.in_({r.vehicle_id for r in rows if r.vehicle_id} or {uuid.uuid4()})
                    )
                )
            ).scalars()
        }
        used: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(TransportAllocation.route_id, func.count())
                    .where(
                        TransportAllocation.route_id.in_(ids or [uuid.uuid4()]),
                        TransportAllocation.status.in_(LIVE_ALLOCATION),
                    )
                    .group_by(TransportAllocation.route_id)
                )
            ).all()  # type: ignore[arg-type]
        )
        per_stop: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(TransportAllocation.stop_id, func.count())
                    .where(
                        TransportAllocation.route_id.in_(ids or [uuid.uuid4()]),
                        TransportAllocation.status.in_(LIVE_ALLOCATION),
                    )
                    .group_by(TransportAllocation.stop_id)
                )
            ).all()  # type: ignore[arg-type]
        )
        out = []
        for r in rows:
            v = vehicles.get(r.vehicle_id) if r.vehicle_id else None
            o = RouteOut(
                id=r.id,
                college_id=r.college_id,
                code=r.code,
                name=r.name,
                vehicle_id=r.vehicle_id,
                vehicle_registration=v.registration_no if v else None,
                driver_name=await self.staff_name(v.driver_staff_id) if v else None,
                distance_km=float(r.distance_km) if r.distance_km is not None else None,
                fee_paise=r.fee_paise,
                is_active=r.is_active,
                capacity=v.capacity if v else None,
                capacity_used=int(used.get(r.id, 0)),
            )
            o.stops = [self.stop_out(s, r, int(per_stop.get(s.id, 0))) for s in stops.get(r.id, [])]
            out.append(o)
        return out

    @staticmethod
    def stop_out(s: TransportStop, r: TransportRoute, passengers: int = 0) -> StopOut:
        return StopOut(
            id=s.id,
            route_id=s.route_id,
            name=s.name,
            sequence=s.sequence,
            lat=float(s.lat) if s.lat is not None else None,
            lng=float(s.lng) if s.lng is not None else None,
            pickup_time=s.pickup_time,
            drop_time=s.drop_time,
            fee_paise=s.fee_paise,
            effective_fee_paise=int(s.fee_paise if s.fee_paise is not None else r.fee_paise or 0),
            passengers=passengers,
        )

    async def list_routes(self, college_id: uuid.UUID | None = None, active: bool | None = None) -> list[RouteOut]:
        q = select(TransportRoute).where(TransportRoute.institution_id == self.inst, route_predicate(self.principal))
        if college_id:
            q = q.where(TransportRoute.college_id == college_id)
        if active is not None:
            q = q.where(TransportRoute.is_active.is_(active))
        return await self.outs(list((await self.db.execute(q.order_by(TransportRoute.code))).scalars()))

    async def public_routes(self) -> list[PublicRouteOut]:
        rows = list(
            (
                await self.db.execute(
                    select(TransportRoute)
                    .where(TransportRoute.institution_id == self.inst, TransportRoute.is_active.is_(True))
                    .order_by(TransportRoute.code)
                )
            ).scalars()
        )
        stops = await self.stops_of([r.id for r in rows])
        return [
            PublicRouteOut(
                id=r.id,
                code=r.code,
                name=r.name,
                stops=[
                    {
                        "id": str(s.id),
                        "name": s.name,
                        "sequence": s.sequence,
                        "pickup_time": s.pickup_time.isoformat() if s.pickup_time else None,
                        "drop_time": s.drop_time.isoformat() if s.drop_time else None,
                        "fee_paise": int(s.fee_paise if s.fee_paise is not None else r.fee_paise or 0),
                    }
                    for s in stops[r.id]
                ],
            )
            for r in rows
        ]

    async def get(self, route_id: uuid.UUID) -> RouteOut:
        return (await self.outs([await self.route(route_id)]))[0]

    async def _vehicle_ok(self, vehicle_id: uuid.UUID | None) -> None:
        if vehicle_id is None:
            return
        v = await self.vehicle(vehicle_id)
        if v.status == "retired":
            raise rule("A retired vehicle cannot run a route", "VEHICLE_RETIRED")

    async def create(self, body: RouteIn) -> RouteOut:
        self.require("manage")
        await self._vehicle_ok(body.vehicle_id)
        if (
            await self.db.execute(
                select(TransportRoute.id).where(
                    TransportRoute.institution_id == self.inst, TransportRoute.code == body.code
                )
            )
        ).first():
            raise rule("Route code already used", "DUPLICATE_CODE")
        r = TransportRoute(institution_id=self.inst, **body.model_dump(exclude={"stops"}))
        self.db.add(r)
        await self.db.flush()
        for i, s in enumerate(body.stops, start=1):
            self.db.add(TransportStop(institution_id=self.inst, route_id=r.id, **(s.model_dump() | {"sequence": i})))
        await self.db.flush()
        await self._audit("create", "transport_route", r.id, None, snap(r, KEYS))
        return await self.get(r.id)

    async def update(self, route_id: uuid.UUID, body: RouteUpdate) -> RouteOut:
        self.require("manage")
        r = await self.route(route_id, for_update=True)
        data = body.model_dump(exclude_unset=True)
        if "vehicle_id" in data:
            await self._vehicle_ok(data["vehicle_id"])
            if data["vehicle_id"] is not None:
                cap = (
                    await self.db.execute(select(Vehicle.capacity).where(Vehicle.id == data["vehicle_id"]))
                ).scalar_one()
                used = (await self.outs([r], with_stops=False))[0].capacity_used
                if cap is not None and used > cap:
                    raise rule("The new vehicle is smaller than the route's allocations", "CAPACITY_FULL", used=used)
        old = snap(r, KEYS)
        for k, v in data.items():
            setattr(r, k, v)
        await self.db.flush()
        await self._audit("update", "transport_route", r.id, old, snap(r, KEYS))
        if {"vehicle_id", "is_active"} & set(data):
            await self.route_changed(r, "vehicle" if "vehicle_id" in data else "status")
        return await self.get(r.id)

    async def delete(self, route_id: uuid.UUID) -> None:
        self.require("manage")
        r = await self.route(route_id, for_update=True)
        live = (
            await self.db.execute(
                select(func.count())
                .select_from(TransportAllocation)
                .where(TransportAllocation.route_id == r.id, TransportAllocation.status.in_(LIVE_ALLOCATION))
            )
        ).scalar_one()
        if live:
            raise rule("The route has active allocations — deactivate it instead", "ROUTE_IN_USE", allocations=live)
        r.is_active = False
        await self._audit("deactivate", "transport_route", r.id, None, None)

    async def route_changed(self, r: TransportRoute, what: str) -> None:
        users = await self.passenger_users(r.id)
        await self._notify("transport.route_changed", users, {"route": r.name, "change": what}, guardians=True)
        await self._emit("transport.route_changed", {"route_id": str(r.id), "change": what}, "transport_route", r.id)

    # ---- stops ----------------------------------------------------------------------------------------------------------
    async def stops(self, route_id: uuid.UUID) -> list[StopOut]:
        return (await self.get(route_id)).stops

    async def add_stop(self, route_id: uuid.UUID, body: StopIn) -> StopOut:
        self.require("manage")
        r = await self.route(route_id, for_update=True)
        top = (
            await self.db.execute(
                select(func.coalesce(func.max(TransportStop.sequence), 0)).where(TransportStop.route_id == r.id)
            )
        ).scalar_one()
        seq = body.sequence or top + 1
        if seq <= top:  # insert: shift the tail up (descending to dodge the unique index)
            tail = (
                (
                    await self.db.execute(
                        select(TransportStop)
                        .where(TransportStop.route_id == r.id, TransportStop.sequence >= seq)
                        .order_by(TransportStop.sequence.desc())
                    )
                )
                .scalars()
                .all()
            )
            for t in tail:
                t.sequence += 1
                await self.db.flush()
        s = TransportStop(institution_id=self.inst, route_id=r.id, **(body.model_dump() | {"sequence": seq}))
        self.db.add(s)
        await self.db.flush()
        await self._audit("create", "transport_stop", s.id, None, snap(s, ("name", "sequence", "fee_paise")))
        await self.route_changed(r, "stops")
        return self.stop_out(s, r)

    async def update_stop(self, stop_id: uuid.UUID, body: StopIn) -> StopOut:
        self.require("manage")
        s = (
            await self.db.execute(
                select(TransportStop).where(TransportStop.id == stop_id, TransportStop.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Stop not found")
        r = await self.route(s.route_id)
        old = snap(s, ("name", "pickup_time", "drop_time", "fee_paise"))
        for k, v in body.model_dump(exclude_unset=True, exclude={"sequence"}).items():
            setattr(s, k, v)
        await self.db.flush()
        await self._audit(
            "update", "transport_stop", s.id, old, snap(s, ("name", "pickup_time", "drop_time", "fee_paise"))
        )
        if old["pickup_time"] != (s.pickup_time.isoformat() if s.pickup_time else None) or old["drop_time"] != (
            s.drop_time.isoformat() if s.drop_time else None
        ):
            await self.route_changed(r, "times")
        return self.stop_out(s, r)

    async def reorder(self, route_id: uuid.UUID, body: StopsReorder) -> list[StopOut]:
        self.require("manage")
        r = await self.route(route_id, for_update=True)
        rows = {
            s.id: s
            for s in (await self.db.execute(select(TransportStop).where(TransportStop.route_id == r.id))).scalars()
        }
        if set(body.stop_ids) != set(rows) or len(body.stop_ids) != len(rows):
            raise APIError(422, ErrorCode.VALIDATION, "stop_ids must list every stop of the route exactly once")
        for i, sid in enumerate(body.stop_ids, start=1):
            rows[sid].sequence = -i
        await self.db.flush()
        for s in rows.values():
            s.sequence = -s.sequence
        await self.db.flush()
        await self._audit("reorder", "transport_route", r.id, None, {"stop_ids": [str(x) for x in body.stop_ids]})
        await self.route_changed(r, "stops")
        return await self.stops(r.id)

    async def sheet_lines(self, route_id: uuid.UUID) -> tuple[str, list[str]]:
        o = await self.get(route_id)
        lines = [
            f"Route {o.code} — {o.name}",
            f"Vehicle: {o.vehicle_registration or '-'}   Driver: {o.driver_name or '-'}   Capacity: {o.capacity or '-'}"
            f"   Allocated: {o.capacity_used}",
            "",
            "#   Stop                                Pickup   Drop     Fee (Rs)   Passengers",
        ]
        for s in o.stops:
            lines.append(
                f"{s.sequence:<3} {s.name[:34]:<35} {s.pickup_time.strftime('%H:%M') if s.pickup_time else '-':<8} "
                f"{s.drop_time.strftime('%H:%M') if s.drop_time else '-':<8} {s.effective_fee_paise / 100:>9.2f}   {s.passengers}"
            )
        return f"Route sheet {o.code}", lines

    async def polyline(self, route_id: uuid.UUID) -> list[tuple[float, float]]:
        return [
            (float(s.lat), float(s.lng))
            for s in (await self.stops_of([route_id]))[route_id]
            if s.lat is not None and s.lng is not None
        ]

    async def summary(self) -> dict[str, Any]:
        rows = await self.list_routes(active=True)
        return {
            "routes": len(rows),
            "capacity": sum(r.capacity or 0 for r in rows),
            "used": sum(r.capacity_used for r in rows),
        }
