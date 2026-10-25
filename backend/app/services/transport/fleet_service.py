"""Fleet — Prompts/21 §21.6 ``fleet_service``.

Vehicles with statutory document expiries (insurance / fitness / permit / PUC → compliance chips ``ok | expiring |
expired | missing`` against ``transport.expiry_alert_days``); the daily expiry scan notifies the transport office and,
with ``transport.block_expired_vehicles``, moves a vehicle with an expired insurance / fitness / permit to
``maintenance`` and cancels its scheduled future trips. Drivers must hold the ``driver`` role. Maintenance and fuel logs
(drivers add for their own vehicle); ``cost_per_km`` = (fuel + maintenance cost) / km from odometer deltas.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.transport import BLOCKING_DOCUMENTS, DOCUMENTS
from app.models.hr import Staff
from app.models.transport import TransportTrip, Vehicle, VehicleFuelLog, VehicleMaintenance
from app.schemas.transport import (
    ComplianceChip,
    VehicleFuelIn,
    VehicleFuelOut,
    VehicleIn,
    VehicleMaintenanceIn,
    VehicleMaintenanceOut,
    VehicleOut,
    VehicleUpdate,
)
from app.services.students.common import snap
from app.services.transport.common import TransportBase, fleet_predicate, my_staff_ids, now_utc, rule

KEYS = ("registration_no", "vehicle_type", "capacity", "driver_staff_id", "status", *[f"{d}_expiry" for d in DOCUMENTS])


def chips_for(v: Vehicle, today: date, alert_days: int) -> list[ComplianceChip]:
    out = []
    for d in DOCUMENTS:
        exp: date | None = getattr(v, f"{d}_expiry")
        if exp is None:
            out.append(ComplianceChip(document=d, state="missing"))
            continue
        left = (exp - today).days
        state = "expired" if left < 0 else "expiring" if left <= alert_days else "ok"
        out.append(ComplianceChip(document=d, expiry=exp, state=state, days_left=left))  # type: ignore[arg-type]
    return out


class FleetService(TransportBase):
    async def alert_days(self) -> int:
        return int(await self.setting("transport", "expiry_alert_days") or 30)

    async def outs(self, rows: list[Vehicle]) -> list[VehicleOut]:
        today, days = await self.today(), await self.alert_days()
        names: dict[Any, str] = {}
        ids = {v.driver_staff_id for v in rows if v.driver_staff_id}
        if ids:
            names = {
                s.id: s.full_name for s in (await self.db.execute(select(Staff).where(Staff.id.in_(ids)))).scalars()
            }
        out = []
        for v in rows:
            chips = chips_for(v, today, days)
            o = VehicleOut.model_validate(v, from_attributes=True)
            o.driver_name = names.get(v.driver_staff_id)
            o.compliance = chips
            o.chips = [f"{c.document}_{c.state}" for c in chips if c.state in ("expiring", "expired")]
            out.append(o)
        return out

    async def list_vehicles(self, status: str | None = None, college_id: uuid.UUID | None = None) -> list[VehicleOut]:
        q = select(Vehicle).where(
            Vehicle.institution_id == self.inst,
            Vehicle.deleted_at.is_(None),
            fleet_predicate(self.principal, Vehicle.college_id, Vehicle.driver_staff_id),
        )
        if status:
            q = q.where(Vehicle.status == status)
        if college_id:
            q = q.where(Vehicle.college_id == college_id)
        return await self.outs(list((await self.db.execute(q.order_by(Vehicle.registration_no))).scalars()))

    async def compliance(self) -> list[dict[str, Any]]:
        out = []
        for v in await self.list_vehicles():
            for c in v.compliance:
                if c.state != "ok":
                    out.append(
                        {"vehicle_id": str(v.id), "registration_no": v.registration_no, **c.model_dump(mode="json")}
                    )
        return sorted(out, key=lambda r: (r["days_left"] is None, r["days_left"] or 0))

    async def _check_driver(self, staff_id: uuid.UUID | None) -> None:
        if staff_id is None:
            return
        from app.models.platform import Role, UserRole

        hit = (
            await self.db.execute(
                select(Staff.id)
                .join(UserRole, UserRole.user_id == Staff.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Staff.id == staff_id, Staff.institution_id == self.inst, Role.slug == "driver")
            )
        ).first()
        if hit is None:
            raise rule("The driver must be a staff member holding the driver role", "NOT_A_DRIVER", 422)

    async def get(self, vehicle_id: uuid.UUID) -> VehicleOut:
        return (await self.outs([await self.vehicle(vehicle_id)]))[0]

    async def create(self, body: VehicleIn) -> VehicleOut:
        self.require("manage")
        await self._check_driver(body.driver_staff_id)
        reg = body.registration_no.upper().replace(" ", "")
        if (
            await self.db.execute(
                select(Vehicle.id).where(Vehicle.institution_id == self.inst, Vehicle.registration_no == reg)
            )
        ).first():
            raise rule("A vehicle with this registration exists", "DUPLICATE_REGISTRATION")
        v = Vehicle(institution_id=self.inst, **body.model_dump(exclude={"registration_no"}), registration_no=reg)
        self.db.add(v)
        await self.db.flush()
        await self._audit("create", "vehicle", v.id, None, snap(v, KEYS))
        await self._emit(
            "transport.vehicle_created", {"vehicle_id": str(v.id), "registration_no": reg}, "vehicle", v.id
        )
        return await self.get(v.id)

    async def update(self, vehicle_id: uuid.UUID, body: VehicleUpdate) -> VehicleOut:
        self.require("manage")
        v = await self.vehicle(vehicle_id, for_update=True)
        if body.version is not None and body.version != v.version:
            raise APIError(409, ErrorCode.CONFLICT, "The vehicle was changed by someone else", {"version": v.version})
        data = body.model_dump(exclude_unset=True, exclude={"version"})
        if "driver_staff_id" in data:
            await self._check_driver(data["driver_staff_id"])
        old = snap(v, KEYS)
        for k, val in data.items():
            setattr(v, k, val)
        v.version += 1
        await self.db.flush()
        await self._audit("update", "vehicle", v.id, old, snap(v, KEYS))
        await self._emit(
            "transport.vehicle_updated", {"vehicle_id": str(v.id), "fields": sorted(data)}, "vehicle", v.id
        )
        return await self.get(v.id)

    async def retire(self, vehicle_id: uuid.UUID) -> VehicleOut:
        self.require("manage")
        v = await self.vehicle(vehicle_id, for_update=True)
        old = snap(v, KEYS)
        v.status, v.is_active = "retired", False
        cancelled = await self._cancel_future_trips(v.id)
        await self._audit("retire", "vehicle", v.id, old, snap(v, KEYS))
        await self._emit(
            "transport.vehicle_retired", {"vehicle_id": str(v.id), "trips_cancelled": cancelled}, "vehicle", v.id
        )
        return await self.get(v.id)

    async def delete(self, vehicle_id: uuid.UUID) -> None:
        self.require("manage")
        v = await self.vehicle(vehicle_id, for_update=True)
        used = (
            await self.db.execute(
                select(func.count()).select_from(TransportTrip).where(TransportTrip.vehicle_id == v.id)
            )
        ).scalar_one()
        if used:
            raise rule("The vehicle has trips — retire it instead", "VEHICLE_IN_USE")
        v.deleted_at, v.deleted_by, v.is_active = now_utc(), self.actor_id, False
        await self._audit("delete", "vehicle", v.id, snap(v, KEYS), None)

    async def _cancel_future_trips(self, vehicle_id: uuid.UUID) -> int:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(TransportTrip).where(
                        TransportTrip.vehicle_id == vehicle_id,
                        TransportTrip.status == "scheduled",
                        TransportTrip.trip_date > today,
                    )
                )
            )
            .scalars()
            .all()
        )
        for t in rows:
            t.status = "cancelled"
        return len(rows)

    # ---- logs --------------------------------------------------------------------------------------------------------
    async def _log_vehicle(self, vehicle_id: uuid.UUID, *, adding: bool) -> Vehicle:
        v = await self.vehicle(vehicle_id)
        if self.can("transport", "manage"):
            return v
        if adding:
            mine = (await self.db.execute(my_staff_ids(self.principal))).scalars().all()
            if v.driver_staff_id not in mine:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Not your vehicle")
        return v

    async def maintenance(self, vehicle_id: uuid.UUID) -> list[VehicleMaintenanceOut]:
        await self._log_vehicle(vehicle_id, adding=False)
        rows = (
            await self.db.execute(
                select(VehicleMaintenance)
                .where(VehicleMaintenance.vehicle_id == vehicle_id)
                .order_by(VehicleMaintenance.service_date.desc())
            )
        ).scalars()
        return [VehicleMaintenanceOut.model_validate(r, from_attributes=True) for r in rows]

    async def add_maintenance(self, vehicle_id: uuid.UUID, body: VehicleMaintenanceIn) -> VehicleMaintenanceOut:
        await self._log_vehicle(vehicle_id, adding=True)
        r = VehicleMaintenance(institution_id=self.inst, vehicle_id=vehicle_id, **body.model_dump())
        self.db.add(r)
        await self.db.flush()
        await self._audit(
            "create", "vehicle_maintenance", r.id, None, snap(r, ("vehicle_id", "cost_paise", "odometer"))
        )
        return VehicleMaintenanceOut.model_validate(r, from_attributes=True)

    async def fuel(self, vehicle_id: uuid.UUID) -> list[VehicleFuelOut]:
        await self._log_vehicle(vehicle_id, adding=False)
        rows = (
            await self.db.execute(
                select(VehicleFuelLog)
                .where(VehicleFuelLog.vehicle_id == vehicle_id)
                .order_by(VehicleFuelLog.filled_on.desc())
            )
        ).scalars()
        return [VehicleFuelOut.model_validate(r, from_attributes=True) for r in rows]

    async def add_fuel(self, vehicle_id: uuid.UUID, body: VehicleFuelIn) -> VehicleFuelOut:
        await self._log_vehicle(vehicle_id, adding=True)
        r = VehicleFuelLog(
            institution_id=self.inst,
            vehicle_id=vehicle_id,
            filled_on=body.filled_on,
            litres=body.litres,
            cost_paise=body.cost_paise,
            odometer=body.odometer,
            filled_by=self.actor_id,
        )
        self.db.add(r)
        await self.db.flush()
        await self._audit("create", "vehicle_fuel", r.id, None, snap(r, ("vehicle_id", "litres", "cost_paise")))
        return VehicleFuelOut.model_validate(r, from_attributes=True)

    async def cost_stats(self, vehicle_id: uuid.UUID) -> dict[str, Any]:
        """km from the odometer spread of fuel + maintenance logs; ``cost_per_km`` in rupees, ``km_per_litre``."""
        fuel = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(VehicleFuelLog.cost_paise), 0),
                    func.coalesce(func.sum(VehicleFuelLog.litres), 0),
                    func.min(VehicleFuelLog.odometer),
                    func.max(VehicleFuelLog.odometer),
                ).where(VehicleFuelLog.vehicle_id == vehicle_id)
            )
        ).one()
        mnt = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(VehicleMaintenance.cost_paise), 0),
                    func.min(VehicleMaintenance.odometer),
                    func.max(VehicleMaintenance.odometer),
                ).where(VehicleMaintenance.vehicle_id == vehicle_id)
            )
        ).one()
        odos = [x for x in (fuel[2], fuel[3], mnt[1], mnt[2]) if x is not None]
        km = (max(odos) - min(odos)) if len(odos) >= 2 else 0  # noqa: PLR2004
        cost = int(fuel[0]) + int(mnt[0])
        litres = float(fuel[1] or 0)
        return {
            "km": km,
            "fuel_paise": int(fuel[0]),
            "maintenance_paise": int(mnt[0]),
            "litres": litres,
            "cost_per_km": round(cost / 100 / km, 2) if km else None,
            "km_per_litre": round(km / litres, 2) if km and litres else None,
        }

    # ---- Beat ----------------------------------------------------------------------------------------------------------
    async def expiry_scan(self) -> int:
        """Daily: notify at ``alert_days`` / 7 / 1 days left and on expiry; block expired vehicles when configured."""
        today, days = await self.today(), await self.alert_days()
        block = bool(await self.setting("transport", "block_expired_vehicles"))
        n = 0
        rows = (
            (
                await self.db.execute(
                    select(Vehicle).where(
                        Vehicle.institution_id == self.inst, Vehicle.deleted_at.is_(None), Vehicle.status != "retired"
                    )
                )
            )
            .scalars()
            .all()
        )
        for v in rows:
            for c in chips_for(v, today, days):
                if c.days_left is None:
                    continue
                if c.days_left in (days, 7, 1):
                    await self._notify(
                        "transport.document_expiring",
                        [],
                        {"vehicle": v.registration_no, "document": c.document, "days": c.days_left},
                        audience=await self.manager_audience(),
                    )
                    await self._emit(
                        "transport.document_expiring",
                        {"vehicle_id": str(v.id), "document": c.document, "days_left": c.days_left},
                        "vehicle",
                        v.id,
                    )
                    n += 1
                elif c.days_left == 0 or (
                    c.days_left < 0 and block and c.document in BLOCKING_DOCUMENTS and v.status == "active"
                ):
                    await self._emit(
                        "transport.document_expired", {"vehicle_id": str(v.id), "document": c.document}, "vehicle", v.id
                    )
                    if c.days_left == 0:
                        await self._notify(
                            "transport.document_expiring",
                            [],
                            {"vehicle": v.registration_no, "document": c.document, "days": 0},
                            audience=await self.manager_audience(),
                        )
                    n += 1
                if c.state == "expired" and block and c.document in BLOCKING_DOCUMENTS and v.status == "active":
                    v.status = "maintenance"
                    await self._cancel_future_trips(v.id)
                    await self._audit("block_expired", "vehicle", v.id, None, {"document": c.document})
        return n
