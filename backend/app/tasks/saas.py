"""Tasks of Phase 38 — Prompts/38 §38.7 (super admin & SaaS operations).

Jobs: ``tenant.export`` / ``tenant.reset`` / ``tenant.erase`` / ``tenant.provision``, ``billing.invoice_generate``,
``billing.invoice_pdf``, ``usage.meter_month`` / ``usage.meter_incremental`` (on demand), ``usage.export``,
``support.diagnostics_snapshot``, ``help.import``, ``announcement.deliver``; ``saas.health_probe`` (retry of chosen
connections). Beat (UTC crontabs, as Phase 37; IST in ``beat.py``): ``usage.meter_incremental`` (daily 19:30 UTC =
01:00 IST), ``usage.meter_month`` (1st 01:00 UTC — the previous month), ``billing.invoices_monthly`` (1st 00:30 UTC =
06:00 IST), ``billing.dunning`` (02:30 = 08:00 IST), ``subscriptions.state_machine`` (02:45 UTC),
``support.sla_scan`` (every 15 min), ``support.auto_close`` (03:10 UTC),
``registrations.expire`` (hourly), ``demo.reset_nightly`` (``demo.reset_cron``, checked every 15 min),
``platform.health_rollup`` (every 5 min), ``impersonation.auto_stop`` (every minute; also activates scheduled
read-only windows). Consumers: ``audit.chain_broken`` / ``audit.anomaly_detected`` → platform alerts,
``outbox.dead_letter`` → platform alert, ``integrations.health_checked`` → outage rollup, ``feature_flag.changed`` →
dashboard cache drop.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _principal
from app.tasks.outbox import consumer

log = structlog.get_logger()


async def _platform(fn: Any) -> Any:
    """Run ``fn(db)`` on the platform session (cross-tenant; BYPASSRLS) and commit."""
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        try:
            out = await fn(db)
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            raise


async def _actor(db: Any, ctx: JobContext) -> Any:
    if ctx.requested_by is None:
        from app.services.saas.registration_service import SystemPlatformActor

        return SystemPlatformActor()
    return await _principal(db, ctx)


# ---- jobs -------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.tenant.export", queue="reports")
@job("tenant.export", queue="reports")
async def tenant_export(
    ctx: JobContext,
    db: Any,
    institution_id: str,
    export_id: str,
    include: list[str],
    format: str = "json",
    email: str | None = None,
    **_: Any,
) -> dict[str, Any]:  # noqa: A002
    from app.services.saas.institution_admin_service import InstitutionAdminService

    principal = await _actor(db, ctx)
    await ctx.progress(db, 5, "Dumping tenant tables")
    return await InstitutionAdminService(db, principal).export_now(
        uuid.UUID(institution_id), export_id, include, format, email
    )


@celery.task(name="jobs.tenant.reset", queue="reports")
@job("tenant.reset", queue="reports")
async def tenant_reset(ctx: JobContext, db: Any, institution_id: str, **_: Any) -> dict[str, Any]:
    from app.services.saas.institution_admin_service import InstitutionAdminService

    principal = await _actor(db, ctx)
    return await InstitutionAdminService(db, principal).reset_now(uuid.UUID(institution_id))


@celery.task(name="jobs.tenant.erase", queue="reports")
@job("tenant.erase", queue="reports")
async def tenant_erase(ctx: JobContext, db: Any, institution_id: str, reason: str, **_: Any) -> dict[str, Any]:
    from app.services.saas.institution_admin_service import InstitutionAdminService

    principal = await _actor(db, ctx)
    return await InstitutionAdminService(db, principal).erase_now(uuid.UUID(institution_id), reason)


@celery.task(name="jobs.tenant.provision", queue="reports")
@job("tenant.provision", queue="reports")
async def tenant_provision(ctx: JobContext, db: Any, registration_id: str, **_: Any) -> dict[str, Any]:
    from app.services.saas.registration_service import RegistrationService

    await ctx.progress(db, 10, "Provisioning the institution")
    return await RegistrationService(db, None).provision_now(uuid.UUID(registration_id))


@celery.task(name="jobs.billing.invoice_generate", queue="reports")
@job("billing.invoice_generate", queue="reports")
async def invoice_generate(
    ctx: JobContext, db: Any, period: str | None = None, institution_id: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.saas.subscription_service import SubscriptionService

    inst = uuid.UUID(institution_id) if institution_id else None
    return await SubscriptionService(db, await _actor(db, ctx)).generate_period(period, inst)


@celery.task(name="jobs.billing.invoice_pdf", queue="documents")
@job("billing.invoice_pdf", queue="documents")
async def invoice_pdf(ctx: JobContext, db: Any, institution_id: str, number: str, **_: Any) -> dict[str, Any]:
    from app.services.saas.subscription_service import SubscriptionService

    svc = SubscriptionService(db, None)
    doc = await svc._invoice(uuid.UUID(institution_id), number)
    doc["pdf_key"] = await svc.render_invoice_pdf(doc)
    await svc.tput(uuid.UUID(institution_id), f"invoice:{number}", doc)
    return {"number": number, "pdf_key": doc["pdf_key"]}


@celery.task(name="jobs.usage.meter_month", queue="reports")
@job("usage.meter_month", queue="reports")
async def usage_meter_month_job(ctx: JobContext, db: Any, period: str | None = None, **_: Any) -> dict[str, Any]:
    from app.services.saas.usage_service import UsageService

    month = date.fromisoformat(f"{period}-01") if period else None
    return await UsageService(db, None).meter_all(month)


@celery.task(name="jobs.usage.export", queue="reports")
@job("usage.export", queue="reports")
async def usage_export(
    ctx: JobContext, db: Any, from_month: str | None = None, to_month: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.core.files import get_storage
    from app.services.saas.usage_service import UsageService

    data = await UsageService(db, await _actor(db, ctx)).export_csv(from_month, to_month)
    key = f"platform/usage/{datetime.now(UTC):%Y%m%dT%H%M%S}-usage.csv"
    storage = get_storage()
    await storage.put(key, data, "text/csv")
    return {"result_url": storage.signed_url(key, ttl=7 * 86400), "bytes": len(data)}


@celery.task(name="jobs.support.diagnostics_snapshot", queue="reports")
@job("support.diagnostics_snapshot", queue="reports")
async def diagnostics_snapshot(ctx: JobContext, db: Any, ticket_id: str, **_: Any) -> dict[str, Any]:
    from app.schemas.saas import TicketReply
    from app.services.saas.support_service import SupportService

    svc = SupportService(db, await _actor(db, ctx))
    diag = await svc.diagnostics(uuid.UUID(ticket_id))
    await svc.reply(
        uuid.UUID(ticket_id),
        TicketReply(text="Diagnostics snapshot:\n" + diag.model_dump_json(indent=1)[:9000], internal=True),
    )
    return {"ticket": diag.ticket_number}


@celery.task(name="jobs.help.import", queue="reports")
@job("help.import", queue="reports")
async def help_import(ctx: JobContext, db: Any, articles: list[dict[str, Any]], **_: Any) -> dict[str, Any]:
    from app.schemas.saas import HelpImport
    from app.services.saas.support_service import SupportService

    return await SupportService(db, await _actor(db, ctx)).help_import(HelpImport(articles=articles))  # type: ignore[arg-type]


@celery.task(name="jobs.announcement.deliver", queue="notifications")
@job("announcement.deliver", queue="notifications")
async def announcement_deliver(ctx: JobContext, db: Any, announcement_id: str, **_: Any) -> dict[str, Any]:
    from app.services.saas.announcement_service import AnnouncementService

    return await AnnouncementService(db, None).deliver(uuid.UUID(announcement_id))


@celery.task(name="saas.health_probe", queue="integrations")
def health_probe(connection_ids: list[str]) -> dict[str, int]:
    from app.tasks.platform import _integrations_health

    out = run_async(_integrations_health([uuid.UUID(c) for c in connection_ids]))
    run_async(_platform(lambda db: _rollup(db)))
    return dict(out)


async def _rollup(db: Any) -> dict[str, int]:
    from app.services.saas.health_service import HealthService

    return await HealthService(db, None).rollup()


# ---- Beat -------------------------------------------------------------------------------------------------------------
def _beat(label: str, fn: Any) -> Any:
    out = run_async(_platform(fn))
    log.info(label, result=out)
    return out


@celery.task(name="beat.usage.meter_incremental", queue="scheduled")
def usage_meter_incremental() -> Any:
    from app.services.saas.usage_service import UsageService, cache_api_cap

    async def fn(db: Any) -> Any:
        svc = UsageService(db, None)
        out = await svc.meter_all(None)
        for (iid,) in (await db.execute(text("SELECT id FROM institutions WHERE deleted_at IS NULL"))).all():
            await cache_api_cap(iid, (await svc.caps(iid)).get("api_calls_per_day"))
        return out

    return _beat("usage_meter_incremental", fn)


@celery.task(name="beat.usage.meter_month", queue="scheduled")
def usage_meter_month() -> Any:
    from app.services.saas.usage_service import UsageService

    previous = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    return _beat("usage_meter_month", lambda db: UsageService(db, None).meter_all(previous))


@celery.task(name="beat.billing.invoices_monthly", queue="scheduled")
def invoices_monthly() -> Any:
    from app.services.saas.subscription_service import SubscriptionService

    return _beat("billing_invoices_monthly", lambda db: SubscriptionService(db, None).generate_period(None))


@celery.task(name="beat.billing.dunning", queue="scheduled")
def dunning() -> Any:
    from app.services.saas.subscription_service import SubscriptionService

    return _beat("billing_dunning", lambda db: SubscriptionService(db, None).dunning())


@celery.task(name="beat.subscriptions.state_machine", queue="scheduled")
def subscriptions_state_machine() -> Any:
    from app.services.saas.subscription_service import SubscriptionService

    return _beat("subscriptions_state_machine", lambda db: SubscriptionService(db, None).state_machine())


@celery.task(name="beat.support.sla_scan", queue="scheduled")
def sla_scan() -> Any:
    from app.services.saas.support_service import SupportService

    return _beat("support_sla_scan", lambda db: SupportService(db, None).sla_scan())


@celery.task(name="beat.support.auto_close", queue="scheduled")
def auto_close() -> Any:
    from app.services.saas.support_service import SupportService

    return _beat("support_auto_close", lambda db: SupportService(db, None).auto_close())


@celery.task(name="beat.registrations.expire", queue="scheduled")
def registrations_expire() -> Any:
    from app.services.saas.registration_service import RegistrationService

    return _beat("registrations_expire", lambda db: RegistrationService(db, None).expire())


@celery.task(name="beat.platform.health_rollup", queue="scheduled")
def health_rollup() -> Any:
    return _beat("platform_health_rollup", _rollup)


@celery.task(name="beat.impersonation.auto_stop", queue="scheduled")
def impersonation_auto_stop() -> Any:
    from app.services.saas.impersonation_service import ImpersonationService
    from app.services.saas.read_only_schedule_service import ReadOnlyScheduleService

    async def fn(db: Any) -> dict[str, int]:
        return {
            "stopped": await ImpersonationService(db, None).auto_stop(),
            "read_only_windows": await ReadOnlyScheduleService(db, None).activate_due(),
        }

    return _beat("impersonation_auto_stop", fn)


@celery.task(name="beat.demo.reset_nightly", queue="scheduled")
def demo_reset_nightly() -> Any:
    """Every 15 minutes: when ``demo.reset_cron`` is due (UTC) and the slot was not run yet, reset each demo tenant."""
    from app.services.reports.schedule_service import cron_next
    from app.services.saas.institution_admin_service import InstitutionAdminService

    async def fn(db: Any) -> dict[str, Any]:
        svc = InstitutionAdminService(db, None)
        cron = str(await svc.setting("demo.reset_cron") or "0 2 * * *")
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        slot = now - timedelta(minutes=now.minute % 15)
        try:
            due_at = cron_next(cron, slot - timedelta(minutes=1))
        except ValueError:
            return {"due": False, "error": f"invalid demo.reset_cron {cron!r}"}
        if due_at >= slot + timedelta(minutes=15) or due_at > now:
            return {"due": False}
        if await svc.pget("demo:last_reset") == due_at.isoformat():
            return {"due": True, "skipped": "already ran"}
        await svc.pput("demo:last_reset", due_at.isoformat())
        slugs = list(await svc.setting("demo.institution_slugs") or [])
        done = []
        for (iid,) in (
            await db.execute(
                text("SELECT id FROM institutions WHERE slug = ANY(:s) AND deleted_at IS NULL"), {"s": slugs}
            )
        ).all():
            done.append(await svc.reset_now(iid))
        return {"due": True, "reset": done}

    return _beat("demo_reset_nightly", fn)


# ---- consumers --------------------------------------------------------------------------------------------------------
@consumer("saas.platform_alerts", events=["audit.chain_broken", "audit.anomaly_detected", "outbox.dead_letter"])
async def platform_alerts(db: Any, event: dict[str, Any]) -> None:
    """Phase 37 chain breaks / anomalies (and dead letters) become platform alerts on the super-admin dashboard."""
    from app.services.saas.dashboard_service import PlatformDashboardService

    kind = {
        "audit.chain_broken": "chain_broken",
        "audit.anomaly_detected": "anomaly",
        "outbox.dead_letter": "dead_letter",
    }[str(event.get("event_type"))]
    inst = event.get("institution_id")
    payload = dict(event.get("payload") or {})

    async def fn(pdb: Any) -> str:
        return await PlatformDashboardService(pdb, None).record_alert(
            kind, uuid.UUID(str(inst)) if inst else None, payload
        )

    await _platform(fn)


@consumer("saas.health_rollup", events=["integrations.health_checked", "integrations.connection_disabled"])
async def health_checked(db: Any, event: dict[str, Any]) -> None:
    await _platform(_rollup)


@consumer("saas.dashboard_cache", events=["feature_flag.changed", "subscription.changed", "institution.*"])
async def dashboard_cache(db: Any, event: dict[str, Any]) -> None:
    import contextlib

    from app.db.session import redis_client
    from app.services.saas.dashboard_service import CACHE_KEY

    with contextlib.suppress(Exception):
        await redis_client.delete(CACHE_KEY)
