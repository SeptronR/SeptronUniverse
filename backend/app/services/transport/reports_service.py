"""Transport reports — Prompts/21 §21.6 ``reports_service``.

Route occupancy, fee collection (Phase 12 invoices with ``source_type='transport_allocation'``), on-time % (stop arrivals
within 5 min of the scheduled time over the last 30 days), cost per km per vehicle, compliance register, fuel efficiency
(km / l), trips per driver; ``stats`` feeds the transport dashboard and ``metrics`` the Phase 32 facility counts
(``transport_vehicles``, ``transport_students``). Inline JSON or an XLSX export job.
"""

import io
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.tenancy import institution_tz
from app.enums.transport import LIVE_ALLOCATION
from app.models.fees import FeeInvoice
from app.models.hr import Staff
from app.models.transport import (
    TransportAllocation,
    TransportRoute,
    TransportStop,
    TransportTrip,
    TripStopEvent,
    Vehicle,
)
from app.schemas.transport import RouteStatsResponse, TransportReport
from app.services.transport.common import TransportBase
from app.services.transport.fleet_service import FleetService
from app.services.transport.route_service import RouteService
from app.services.transport.trip_service import TripService

KINDS = ("occupancy", "fees", "on_time", "cost_per_km", "compliance", "fuel", "driver_trips")
ON_TIME_MIN = 5


class TransportReportsService(TransportBase):
    def _sub(self, cls: Any) -> Any:
        return cls(self.db, self.principal, self.request, self.inst)

    async def on_time(self, days: int = 30) -> tuple[float | None, list[dict[str, Any]]]:
        since = await self.today() - timedelta(days=days)
        tz = institution_tz(await self.institution())
        rows = (
            await self.db.execute(
                select(TransportTrip, TripStopEvent, TransportStop, TransportRoute.code)
                .join(TripStopEvent, TripStopEvent.trip_id == TransportTrip.id)
                .join(TransportStop, TransportStop.id == TripStopEvent.stop_id)
                .join(TransportRoute, TransportRoute.id == TransportTrip.route_id)
                .where(
                    TransportTrip.institution_id == self.inst,
                    TransportTrip.trip_date >= since,
                    TripStopEvent.arrived_at.is_not(None),
                )
            )
        ).all()
        per: dict[str, list[int]] = {}
        for t, e, s, code in rows:
            planned = s.pickup_time if t.direction == "pickup" else s.drop_time
            if planned is None:
                continue
            late = (e.arrived_at - datetime.combine(t.trip_date, planned, tzinfo=tz)).total_seconds() / 60
            per.setdefault(code, []).append(1 if late <= ON_TIME_MIN else 0)
        out = [
            {"route": k, "arrivals": len(v), "on_time_pct": round(100 * sum(v) / len(v), 1)}
            for k, v in sorted(per.items())
        ]
        total = [x for v in per.values() for x in v]
        return (round(100 * sum(total) / len(total), 1) if total else None), out

    async def report(self, kind: str) -> TransportReport:
        if kind not in KINDS:
            raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
        rows: list[dict[str, Any]] = []
        if kind == "occupancy":
            for r in await self._sub(RouteService).list_routes():
                cap = r.capacity or 0
                rows.append(
                    {
                        "route": r.code,
                        "name": r.name,
                        "vehicle": r.vehicle_registration,
                        "capacity": cap,
                        "allocated": r.capacity_used,
                        "occupancy_pct": round(100 * r.capacity_used / cap, 1) if cap else None,
                    }
                )
        elif kind == "fees":
            for code, n, total, paid, bal in (
                await self.db.execute(
                    select(
                        TransportRoute.code,
                        func.count(FeeInvoice.id),
                        func.coalesce(func.sum(FeeInvoice.total_paise), 0),
                        func.coalesce(func.sum(FeeInvoice.paid_paise), 0),
                        func.coalesce(func.sum(FeeInvoice.balance_paise), 0),
                    )
                    .join(TransportAllocation, TransportAllocation.id == FeeInvoice.source_id)
                    .join(TransportRoute, TransportRoute.id == TransportAllocation.route_id)
                    .where(FeeInvoice.institution_id == self.inst, FeeInvoice.source_type == "transport_allocation")
                    .group_by(TransportRoute.code)
                    .order_by(TransportRoute.code)
                )
            ).all():
                rows.append(
                    {
                        "route": code,
                        "invoices": n,
                        "billed_paise": int(total),
                        "collected_paise": int(paid),
                        "due_paise": int(bal),
                    }
                )
        elif kind == "on_time":
            rows = (await self.on_time())[1]
        elif kind in ("cost_per_km", "fuel"):
            fleet = self._sub(FleetService)
            for v in await fleet.list_vehicles():
                c = await fleet.cost_stats(v.id)
                rows.append({"vehicle": v.registration_no, **c})
        elif kind == "compliance":
            rows = await self._sub(FleetService).compliance()
        elif kind == "driver_trips":
            since = await self.today() - timedelta(days=30)
            for name_first, name_last, status, n in (
                await self.db.execute(
                    select(Staff.first_name, Staff.last_name, TransportTrip.status, func.count())
                    .join(Staff, Staff.id == TransportTrip.driver_staff_id)
                    .where(TransportTrip.institution_id == self.inst, TransportTrip.trip_date >= since)
                    .group_by(Staff.first_name, Staff.last_name, TransportTrip.status)
                )
            ).all():
                rows.append({"driver": " ".join(x for x in (name_first, name_last) if x), "status": status, "trips": n})
        return TransportReport(kind=kind, columns=list(rows[0]) if rows else [], rows=rows)

    async def report_xlsx(self, kind: str) -> dict[str, Any]:
        from openpyxl import Workbook

        from app.core.files import build_key, storage

        rep = await self.report(kind)
        wb = Workbook()
        ws = wb.active
        ws.title = kind[:30]
        ws.append(rep.columns)
        for r in rep.rows:
            ws.append([r.get(c) for c in rep.columns])
        buf = io.BytesIO()
        wb.save(buf)
        key = build_key(self.inst, "transport-reports", f"{kind}-{uuid.uuid4().hex[:8]}.xlsx")
        await storage.put(key, buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return {"result_url": key, "rows": len(rep.rows), "report": kind}

    async def stats(self) -> RouteStatsResponse:
        out = RouteStatsResponse()
        vs = await self._sub(FleetService).list_vehicles()
        out.vehicles = len([v for v in vs if v.status != "retired"])
        out.vehicles_active = len([v for v in vs if v.status == "active"])
        out.compliance_alerts = sum(len(v.chips) for v in vs)
        summ = await self._sub(RouteService).summary()
        out.routes = summ["routes"]
        out.occupancy_pct = round(100 * summ["used"] / summ["capacity"], 1) if summ["capacity"] else 0.0
        for kind, n in (
            await self.db.execute(
                select(TransportAllocation.person_type, func.count())
                .where(TransportAllocation.institution_id == self.inst, TransportAllocation.status.in_(LIVE_ALLOCATION))
                .group_by(TransportAllocation.person_type)
            )
        ).all():
            if kind == "student":
                out.students = n
            else:
                out.staff = n
        trips = await self._sub(TripService).list_trips()
        out.trips_today = len(trips)
        out.in_progress = len([t for t in trips if t.status == "in_progress"])
        out.delayed = len([t for t in trips if (t.delay_minutes or 0) > 15])  # noqa: PLR2004
        out.on_time_pct = (await self.on_time())[0]
        costs = [c for c in (await self.report("cost_per_km")).rows if c.get("cost_per_km")]
        out.cost_per_km = round(sum(c["cost_per_km"] for c in costs) / len(costs), 2) if costs else None
        return out

    async def metrics(self) -> dict[str, int]:
        vehicles = (
            await self.db.execute(
                select(func.count())
                .select_from(Vehicle)
                .where(Vehicle.institution_id == self.inst, Vehicle.deleted_at.is_(None), Vehicle.status != "retired")
            )
        ).scalar_one()
        students = (
            await self.db.execute(
                select(func.count(func.distinct(TransportAllocation.person_id))).where(
                    TransportAllocation.institution_id == self.inst,
                    TransportAllocation.person_type == "student",
                    TransportAllocation.status.in_(LIVE_ALLOCATION),
                )
            )
        ).scalar_one()
        return {"transport_vehicles": int(vehicles), "transport_students": int(students)}
