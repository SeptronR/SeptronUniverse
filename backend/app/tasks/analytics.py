"""Analytics tasks — Prompts/35 §35.7.

Jobs: ``analytics.refresh_view`` / ``analytics.refresh_all`` (manual refresh with progress), ``analytics.chart_export``
(csv / xlsx), ``analytics.digest`` (send a digest now), ``analytics.kpi_evaluate``, ``risk.cohort_export`` (xlsx).
Beat: ``analytics.refresh_scheduler`` (every 5 min: views whose interval elapsed and are dirty; ``mv_kpi_daily`` last,
then KPI evaluation per tenant), ``analytics.digest_daily`` / ``analytics.digest_weekly`` (hourly tick — schedules fire at
their hour, IST), ``risk.intervention_reminders`` (daily).
Consumers: the domain events of the source modules mark views dirty and drop the chart cache
(``analytics.invalidate``); ``risk.computed`` → cohort / intervention-due alerts (``analytics.risk_alerts``);
``feature_flag.changed`` drops the chart cache (widgets hide on the next render).
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer
from app.tasks.research import XLSX, xlsx_bytes


async def _upload(principal: Any, name: str, content: bytes, mime: str) -> str:
    from app.core.files import build_key, get_storage

    key = build_key(principal.institution_id, "analytics", name)
    storage = get_storage()
    await storage.put(key, content, mime)
    return storage.signed_url(key)


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.analytics.refresh_all", queue="reports")
@job("analytics.refresh_all", queue="reports")
async def refresh_all(ctx: JobContext, db: Any, views: list[str] | None = None, **_: Any) -> dict[str, Any]:
    from app.services.analytics.read_models import VIEW_NAMES
    from app.services.analytics.readmodel_service import ReadModelService, refresh_views

    principal = await _principal(db, ctx)
    wanted = [v for v in VIEW_NAMES if not views or v in views]
    if wanted and "mv_kpi_daily" not in wanted:
        wanted.append("mv_kpi_daily")
    done: list[dict[str, Any]] = []
    for i, view in enumerate(wanted, start=1):
        done += await refresh_views([view])
        await ctx.progress(db, int(100 * i / len(wanted)), f"{view} refreshed")
    await ReadModelService(db, principal).invalidate_all_charts()
    from app.services.analytics.kpi_service import KpiService

    await KpiService(db, principal).evaluate()
    return {"views": done}


@celery.task(name="jobs.analytics.refresh_view", queue="reports")
@job("analytics.refresh_view", queue="reports")
async def refresh_view(ctx: JobContext, db: Any, view: str, **_: Any) -> dict[str, Any]:
    from app.services.analytics.readmodel_service import refresh_views

    await _principal(db, ctx)
    return {"views": await refresh_views([view])}


@celery.task(name="jobs.analytics.chart_export", queue="reports")
@job("analytics.chart_export", queue="reports")
async def chart_export(
    ctx: JobContext,
    db: Any,
    key: str,
    scope: str | None = None,
    dims: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    format: str = "xlsx",
    **_: Any,
) -> dict[str, Any]:
    from app.services.analytics.chart_service import ChartService

    principal = await _principal(db, ctx)
    svc = ChartService(db, principal)
    data = await svc.render(key, scope=scope, dims=dims or {}, params=params or {}, use_cache=False)
    cols = data.table["columns"]
    rows = [dict(zip(cols, r, strict=False)) for r in data.table["rows"]]
    if format == "csv":
        url = await _upload(principal, f"{key}.csv", (await svc.table_csv(data)).encode(), "text/csv")
    else:
        url = await _upload(principal, f"{key}.xlsx", xlsx_bytes(data.title[:31], rows), XLSX)
    return {"result_url": url, "rows": len(rows)}


@celery.task(name="jobs.analytics.digest", queue="reports")
@job("analytics.digest", queue="reports")
async def digest(ctx: JobContext, db: Any, digest_id: str, **_: Any) -> dict[str, Any]:
    from app.services.analytics.digest_service import DigestService

    principal = await _principal(db, ctx)
    return await DigestService(db, principal).send(digest_id)


@celery.task(name="jobs.analytics.kpi_evaluate", queue="reports")
@job("analytics.kpi_evaluate", queue="reports")
async def kpi_evaluate(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.analytics.kpi_service import KpiService

    principal = await _principal(db, ctx)
    return await KpiService(db, principal).evaluate()


@celery.task(name="jobs.risk.cohort_export", queue="reports")
@job("risk.cohort_export", queue="reports")
async def cohort_export(
    ctx: JobContext, db: Any, kind: str = "cohort", term_id: str | None = None, scope: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.analytics.risk_analytics_service import RiskAnalyticsService

    principal = await _principal(db, ctx)
    rows = await RiskAnalyticsService(db, principal).export_rows(uuid.UUID(term_id) if term_id else None, kind, scope)
    url = await _upload(principal, f"risk-{kind}.xlsx", xlsx_bytes(f"risk {kind}", rows), XLSX)
    return {"result_url": url, "rows": len(rows)}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
@celery.task(name="beat.analytics.refresh_scheduler", queue="scheduled")
def refresh_scheduler() -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        from app.services.analytics.readmodel_service import scheduler_tick

        out = await scheduler_tick()
        if "mv_kpi_daily" in out.get("refreshed", []):

            async def one(db: Any, iid: uuid.UUID, today: date) -> int:
                from app.services.analytics.kpi_service import KpiService

                res = await KpiService(db, None, institution_id=iid).evaluate()
                return int(res.get("opened", 0))

            out["kpi"] = await _for_institutions("analytics.core", one, "analytics_kpi_evaluate")
        return out

    return run_async(run())


def _digest_tick(cadence: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.analytics.digest_service import DigestService

        hour = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).hour  # IN pack: institution time ≈ IST
        svc = DigestService(db, None, institution_id=iid)
        n = 0
        for did in await svc.due(cadence, hour):
            await svc.send(did)
            n += 1
        return n

    return run_async(_for_institutions("analytics.core", one, f"analytics_digest_{cadence}"))


@celery.task(name="beat.analytics.digest_daily", queue="scheduled")
def digest_daily() -> dict[str, int]:
    return _digest_tick("daily")


@celery.task(name="beat.analytics.digest_weekly", queue="scheduled")
def digest_weekly() -> dict[str, int]:
    if (datetime.now(UTC) + timedelta(hours=5, minutes=30)).weekday() != 0:
        return {"count": 0}
    return _digest_tick("weekly")


@celery.task(name="beat.risk.intervention_reminders", queue="scheduled")
def intervention_reminders() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.analytics.risk_analytics_service import RiskAnalyticsService

        return await RiskAnalyticsService(db, None, institution_id=iid).follow_up_reminders()

    return run_async(_for_institutions("analytics.early_warning", one, "risk_intervention_reminders"))


# ---- consumers ------------------------------------------------------------------------------------------------------------
def _iid(event: dict[str, Any]) -> uuid.UUID | None:
    inst = event.get("institution_id")
    return uuid.UUID(str(inst)) if inst else None


INVALIDATING_EVENTS = [
    "student.created",
    "student.updated",
    "student.status_changed",
    "registration.submitted",
    "registration.approved",
    "attendance.finalized",
    "attendance.below_threshold",
    "marks.submitted",
    "marks.verified",
    "fees.invoice_created",
    "fees.payment_received",
    "fees.refunded",
    "exams.*",
    "results.published",
    "hr.*",
    "leave.*",
    "admissions.*",
    "hostel.*",
    "library.*",
    "placement.*",
    "service_request.*",
    "grievance.*",
    "risk.computed",
    "metrics.publish",
]


@consumer("analytics.invalidate", events=INVALIDATING_EVENTS)
async def on_source_event(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    if iid is None:
        return
    from app.services.analytics.readmodel_service import ReadModelService

    await ReadModelService(db, None, institution_id=iid).mark_dirty(str(event.get("event_type") or ""))


@consumer("analytics.feature_changed", events=["feature_flag.changed"])
async def on_feature_changed(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    if iid is None:
        return
    from app.services.analytics.readmodel_service import ReadModelService

    await ReadModelService(db, None, institution_id=iid).invalidate_all_charts()


@consumer("analytics.risk_alerts", events=["risk.computed"])
async def on_risk_computed(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    p = event.get("payload") or {}
    if iid is None or not p.get("term_id"):
        return
    from app.core.features import is_enabled

    try:
        if not await is_enabled(iid, "analytics.early_warning"):
            return
    except KeyError:
        return
    from app.services.analytics.risk_analytics_service import RiskAnalyticsService

    await RiskAnalyticsService(db, None, institution_id=iid).after_compute(uuid.UUID(str(p["term_id"])))
