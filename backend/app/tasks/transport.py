"""Transport tasks — Prompts/21 §21.7.

Jobs (run as the requesting user): ``transport.schedule_trips``, ``transport.bulk_allocate``, ``transport.year_end_close``,
``transport.reports_export``, ``transport.gps_export``. Consumer ``transport.payment`` on ``fees.payment_received``
(transport invoices paid → suspended allocations active again). Beat: ``transport.document_expiry_scan`` (daily),
``transport.gps_partition_maintenance`` (monthly), ``transport.trip_autoclose`` / ``transport.fee_suspension``
(nightly), ``transport.live_cache_cleanup`` (hourly), ``transport.schedule_ahead`` (daily top-up of the next 7 days).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer


@celery.task(name="jobs.transport.schedule_trips", queue="reports")
@job("transport.schedule_trips", queue="reports")
async def schedule_trips(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.transport import TripScheduleRequest
    from app.services.transport.trip_service import TripService

    principal = await _principal(db, ctx)
    body = TripScheduleRequest(**{k: v for k, v in params.items() if k in TripScheduleRequest.model_fields})
    out = await TripService(db, principal).schedule(body)
    await ctx.progress(db, 100, f"{out.created} trip(s)")
    return out.model_dump(mode="json")


@celery.task(name="jobs.transport.bulk_allocate", queue="reports")
@job("transport.bulk_allocate", queue="reports")
async def bulk_allocate(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.transport import AllocationBulk
    from app.services.transport.allocation_service import AllocationService

    principal = await _principal(db, ctx)
    body = AllocationBulk(**{k: v for k, v in params.items() if k in AllocationBulk.model_fields})
    out = await AllocationService(db, principal).bulk(body)
    await ctx.progress(db, 100, f"{out.allocated} allocated / {len(out.failed)} failed")
    return out.model_dump(mode="json")


@celery.task(name="jobs.transport.year_end_close", queue="reports")
@job("transport.year_end_close", queue="reports")
async def year_end_close(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.transport.allocation_service import AllocationService

    principal = await _principal(db, ctx)
    out = await AllocationService(db, principal).year_end_close()
    await ctx.progress(db, 100, f"{out['closed']} closed")
    return out


@celery.task(name="jobs.transport.reports_export", queue="reports")
@job("transport.reports_export", queue="reports")
async def reports_export(ctx: JobContext, db: Any, kind: str, **_: Any) -> dict[str, Any]:
    from app.services.transport.reports_service import TransportReportsService

    principal = await _principal(db, ctx)
    out = await TransportReportsService(db, principal).report_xlsx(kind)
    await ctx.progress(db, 100, f"{out['rows']} rows")
    return out


@celery.task(name="jobs.transport.gps_export", queue="reports")
@job("transport.gps_export", queue="reports")
async def gps_export(ctx: JobContext, db: Any, trip_id: str, **_: Any) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.transport.gps_service import GpsService

    principal = await _principal(db, ctx)
    svc = GpsService(db, principal)
    tr = await svc.trace(uuid.UUID(trip_id))
    key = build_key(svc.inst, "transport-gpx", f"trip-{trip_id}.gpx")
    await storage.put(key, svc.gpx(tr).encode(), "application/gpx+xml")
    await ctx.progress(db, 100, f"{tr.total_points} points")
    return {"result_url": key, "points": tr.total_points}


@consumer("transport.payment", events=["fees.payment_received"])
async def payment(db: Any, event: dict[str, Any]) -> None:
    from app.services.transport.allocation_service import AllocationService

    p = event.get("payload") or {}
    if p.get("source_type") != "transport_allocation" or not p.get("invoice_id"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await AllocationService(db, None, institution_id=iid).payment_received(uuid.UUID(str(p["invoice_id"])))


def _beat(label: str, feature: str, fn: Any) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        out = await fn(db, iid, today)
        return int(out if isinstance(out, int) else sum(v for v in out.values() if isinstance(v, int)))

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.transport.document_expiry_scan", queue="scheduled")
def document_expiry_scan() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.transport.fleet_service import FleetService

        return await FleetService(db, None, institution_id=iid).expiry_scan()

    return _beat("transport_document_expiry_scan", "transport.core", fn)


@celery.task(name="beat.transport.gps_partition_maintenance", queue="scheduled")
def gps_partition_maintenance() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> dict[str, int]:
        from app.services.transport.gps_service import GpsService

        return await GpsService(db, None, institution_id=iid).partition_maintenance(today)

    return _beat("transport_gps_partition_maintenance", "transport.gps_live", fn)


@celery.task(name="beat.transport.trip_autoclose", queue="scheduled")
def trip_autoclose() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.transport.trip_service import TripService

        return await TripService(db, None, institution_id=iid).autoclose()

    return _beat("transport_trip_autoclose", "transport.core", fn)


@celery.task(name="beat.transport.fee_suspension", queue="scheduled")
def fee_suspension() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.transport.allocation_service import AllocationService

        return await AllocationService(db, None, institution_id=iid).fee_suspension()

    return _beat("transport_fee_suspension", "transport.fees", fn)


@celery.task(name="beat.transport.live_cache_cleanup", queue="scheduled")
def live_cache_cleanup() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.transport.gps_service import GpsService

        return await GpsService(db, None, institution_id=iid).live_cache_cleanup()

    return _beat("transport_live_cache_cleanup", "transport.gps_live", fn)


@celery.task(name="beat.transport.schedule_ahead", queue="scheduled")
def schedule_ahead() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.transport.trip_service import TripService

        return await TripService(db, None, institution_id=iid).schedule_ahead(7)

    return _beat("transport_schedule_ahead", "transport.core", fn)
