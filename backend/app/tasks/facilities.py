"""Calendar, events & facilities tasks — Prompts/25 §25.7.

Jobs: ``calendar.pdf``, ``event.certificates``, ``facilities.report``, ``visitor.pii_purge``,
``wallet.settlement_report``. Beat: calendar reminders (15 min), event reminders (daily), SLA scan (10 min), ticket
auto-close (daily), AMC expiry (daily), visitor pass expiry (hourly), SOS escalation (every minute), equipment overdue
(daily), insurance expiry (weekly), counselling no-show (hourly), wallet limits reset (daily).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.calendar.pdf", queue="reports")
@job("calendar.pdf", queue="reports")
async def calendar_pdf(ctx: JobContext, db: Any, academic_year_id: str | None = None, **_: Any) -> dict[str, Any]:
    from app.services.facilities.calendar_service import CalendarService

    principal = await _principal(db, ctx)
    out = await CalendarService(db, principal).year_pdf(uuid.UUID(academic_year_id) if academic_year_id else None)
    await ctx.progress(db, 100, f"{out['entries']} entries")
    return out


@celery.task(name="jobs.event.certificates", queue="documents")
@job("event.certificates", queue="documents")
async def event_certificates(
    ctx: JobContext, db: Any, event_id: str, only_attended: bool = True, **_: Any
) -> dict[str, Any]:
    from app.services.facilities.event_service import EventService

    principal = await _principal(db, ctx)
    n = await EventService(db, principal).issue_certificates(uuid.UUID(event_id), only_attended)
    await ctx.progress(db, 100, f"{n} certificate(s)")
    return {"issued": n}


@celery.task(name="jobs.facilities.report", queue="reports")
@job("facilities.report", queue="reports")
async def facilities_report(
    ctx: JobContext, db: Any, kind: str, date_from: str | None = None, date_to: str | None = None, **_: Any
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.core.files import build_key, get_storage
    from app.services.facilities.booking_service import BookingService
    from app.services.facilities.event_service import EventService
    from app.services.facilities.service_desk_service import ServiceDeskService
    from app.services.facilities.sports_service import SportsService
    from app.services.facilities.visitor_service import VisitorService
    from app.services.facilities.wallet_service import WalletService

    principal = await _principal(db, ctx)
    d1 = date.fromisoformat(date_to) if date_to else date.today()
    d0 = date.fromisoformat(date_from) if date_from else d1 - timedelta(days=30)
    rows: list[dict[str, Any]]
    if kind == "events":
        rows = [e.model_dump(mode="json") for e in await EventService(db, principal).list_events()]
    elif kind == "bookings":
        rows = await BookingService(db, principal).usage(
            datetime.combine(d0, datetime.min.time(), tzinfo=UTC), datetime.combine(d1, datetime.max.time(), tzinfo=UTC)
        )
    elif kind == "service_desk":
        rows = await ServiceDeskService(db, principal).export_rows()
    elif kind == "visitors":
        rows = await VisitorService(db, principal).register(d1)
    elif kind == "sports":
        rows = [p.model_dump(mode="json") for p in await SportsService(db, principal).participation()]
    else:
        rows = [t.model_dump(mode="json") for t in await WalletService(db, principal).ledger(5000)]
    import csv
    import io

    buf = io.StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (v if not isinstance(v, dict | list) else str(v)) for k, v in r.items()})
    key = build_key(principal.institution_id, "facilities", f"{kind}-{d1.isoformat()}.csv")
    storage = get_storage()
    await storage.put(key, buf.getvalue().encode("utf-8"), "text/csv")
    await ctx.progress(db, 100, f"{len(rows)} row(s)")
    return {"rows": len(rows), "result_url": storage.signed_url(key)}


@celery.task(name="jobs.visitor.pii_purge", queue="scheduled")
@job("visitor.pii_purge", queue="scheduled")
async def visitor_pii_purge(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.facilities.visitor_service import VisitorService

    principal = await _principal(db, ctx)
    return {"purged": await VisitorService(db, principal).purge_pii()}


@celery.task(name="jobs.wallet.settlement_report", queue="reports")
@job("wallet.settlement_report", queue="reports")
async def wallet_settlement(ctx: JobContext, db: Any, on: str | None = None, **_: Any) -> dict[str, Any]:
    from app.services.facilities.wallet_service import WalletService

    principal = await _principal(db, ctx)
    svc = WalletService(db, principal)
    day = date.fromisoformat(on) if on else await svc.today()
    out = [(await svc.settlement(c.id, day)).model_dump(mode="json") for c in await svc.canteens()]
    return {"canteens": out}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, fn: Any) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        return int(await fn(db, iid))

    return run_async(_for_institutions(feature, one, label))


def _svc(path: str, cls: str, method: str) -> Any:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.facilities.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return fn


@celery.task(name="beat.calendar.reminders", queue="scheduled")
def calendar_reminders() -> dict[str, int]:
    return _beat("calendar_reminders", "calendar.core", _svc("calendar_service", "CalendarService", "reminders"))


@celery.task(name="beat.event.reminders", queue="scheduled")
def event_reminders() -> dict[str, int]:
    return _beat("event_reminders", "events.core", _svc("event_service", "EventService", "reminders"))


@celery.task(name="beat.service_desk.sla_scan", queue="scheduled")
def sla_scan() -> dict[str, int]:
    return _beat(
        "service_desk_sla_scan",
        "facilities.service_desk",
        _svc("service_desk_service", "ServiceDeskService", "sla_scan"),
    )


@celery.task(name="beat.service_desk.auto_close", queue="scheduled")
def auto_close() -> dict[str, int]:
    return _beat(
        "service_desk_auto_close",
        "facilities.service_desk",
        _svc("service_desk_service", "ServiceDeskService", "auto_close"),
    )


@celery.task(name="beat.amc.expiry_scan", queue="scheduled")
def amc_expiry() -> dict[str, int]:
    return _beat(
        "amc_expiry_scan", "facilities.amc", _svc("service_desk_service", "ServiceDeskService", "amc_expiry_scan")
    )


@celery.task(name="beat.visitor.expire_passes", queue="scheduled")
def expire_passes() -> dict[str, int]:
    return _beat(
        "visitor_expire_passes", "facilities.visitor_gate", _svc("visitor_service", "VisitorService", "expire_passes")
    )


@celery.task(name="beat.visitor.pii_purge", queue="scheduled")
def pii_purge() -> dict[str, int]:
    return _beat("visitor_pii_purge", "facilities.visitor_gate", _svc("visitor_service", "VisitorService", "purge_pii"))


@celery.task(name="beat.emergency.escalation", queue="scheduled")
def sos_escalation() -> dict[str, int]:
    return _beat(
        "emergency_escalation", "facilities.emergency_sos", _svc("emergency_service", "EmergencyService", "escalation")
    )


@celery.task(name="beat.equipment.overdue_scan", queue="scheduled")
def equipment_overdue() -> dict[str, int]:
    return _beat(
        "equipment_overdue_scan",
        "facilities.equipment_booking",
        _svc("booking_service", "BookingService", "overdue_scan"),
    )


@celery.task(name="beat.insurance.expiry_scan", queue="scheduled")
def insurance_expiry() -> dict[str, int]:
    return _beat(
        "insurance_expiry_scan",
        "facilities.health_centre",
        _svc("health_service", "HealthService", "insurance_expiry_scan"),
    )


@celery.task(name="beat.counselling.no_show_mark", queue="scheduled")
def no_show_mark() -> dict[str, int]:
    return _beat(
        "counselling_no_show",
        "facilities.counselling_appointments",
        _svc("counselling_service", "CounsellingService", "no_show_mark"),
    )


@celery.task(name="beat.wallet.limits_reset", queue="scheduled")
def wallet_limits_reset() -> dict[str, int]:
    return _beat(
        "wallet_limits_reset", "facilities.canteen_wallet", _svc("wallet_service", "WalletService", "limits_reset")
    )
