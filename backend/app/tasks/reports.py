"""Tasks on the ``reports`` queue — Prompts/36 §36.7 (other phases' ``reports.<task>`` names also route here).

Jobs: ``report.run`` (registry report → file; legacy ``/…/reports/{kind}`` aliases and schedule deliveries too),
``report.builder_run`` (ad-hoc builder definition), ``report.statutory_generate`` / ``report.statutory_pack``,
``report.schedule_deliver`` (a saved builder report delivered by a schedule).
Beat: ``reports.schedules_tick`` (every 5 min), ``reports.retention_purge`` (daily 02:30 IST),
``reports.statutory_due_calendar`` (weekly).
Consumers: ``academic_term.status_changed`` → termly schedules; ``accreditation.submission_due`` → statutory due
reminders for the linked code.
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.report.run", queue="reports")
@job("report.run", queue="reports")
async def report_run(
    ctx: JobContext,
    db: Any,
    key: str,
    params: dict[str, Any] | None = None,
    format: str = "xlsx",
    scope: str | None = None,
    deliver_to: dict[str, Any] | None = None,
    schedule_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.services.reports.report_service import ReportService

    principal = await _principal(db, ctx)
    svc = ReportService(db, principal, institution_id=ctx.institution_id)
    return await svc.execute(
        ctx.job_id, key, params or {}, format, scope=scope, deliver_to=deliver_to, job=ctx, schedule_id=schedule_id
    )


@celery.task(name="jobs.report.builder_run", queue="reports")
@job("report.builder_run", queue="reports")
async def builder_run(
    ctx: JobContext, db: Any, definition: dict[str, Any], format: str = "xlsx", **_: Any
) -> dict[str, Any]:
    from app.services.reports.builder_service import BuilderService

    principal = await _principal(db, ctx)
    return await BuilderService(db, principal, institution_id=ctx.institution_id).execute_job(
        ctx.job_id, definition, format
    )


@celery.task(name="jobs.report.schedule_deliver", queue="reports")
@job("report.schedule_deliver", queue="reports")
async def schedule_deliver(
    ctx: JobContext,
    db: Any,
    saved_report_id: str,
    format: str = "xlsx",
    deliver_to: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.schemas.reports import BuilderDefinition
    from app.services.reports.builder_service import BuilderService

    principal = await _principal(db, ctx)
    svc = BuilderService(db, principal, institution_id=ctx.institution_id)
    v, _saved = await svc.saved(saved_report_id)
    definition = BuilderDefinition.model_validate({**(v.get("definition") or {}), "name": v.get("name")})
    out = await svc.execute_job(ctx.job_id, definition.model_dump(mode="json"), format)
    if deliver_to and deliver_to.get("user_ids"):
        await svc._notify(  # noqa: SLF001 - same delivery template as the registry runs
            "reports.scheduled_delivery",
            [uuid.UUID(str(u)) for u in deliver_to["user_ids"]],
            {"report": v.get("name"), "key": out["key"], "rows": out["rows"], "url": out["result_url"]},
        )
        out["delivery"] = list(deliver_to["user_ids"])
    return out


@celery.task(name="jobs.report.statutory_generate", queue="reports")
@job("report.statutory_generate", queue="reports")
async def statutory_generate(
    ctx: JobContext,
    db: Any,
    code: str,
    period_label: str,
    discipline: str | None = None,
    college_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.services.reports.statutory_service import StatutoryService

    principal = await _principal(db, ctx)
    svc = StatutoryService(db, principal, institution_id=ctx.institution_id)
    return await svc.generate_now(ctx.job_id, code, period_label, discipline, college_id, job=ctx)


@celery.task(name="jobs.report.statutory_pack", queue="reports")
@job("report.statutory_pack", queue="reports")
async def statutory_pack(
    ctx: JobContext, db: Any, code: str, period_label: str, discipline: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.reports.statutory_service import StatutoryService

    principal = await _principal(db, ctx)
    return await StatutoryService(db, principal, institution_id=ctx.institution_id).pack_now(
        ctx.job_id, code, period_label, discipline
    )


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, fn: Any) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        return int(await fn(db, iid))

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.reports.schedules_tick", queue="scheduled")
def schedules_tick() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.reports.schedule_service import ScheduleService

        return await ScheduleService(db, None, institution_id=iid).tick()

    return _beat("reports_schedules_tick", "reports.scheduled", fn)


@celery.task(name="beat.reports.retention_purge", queue="scheduled")
def retention_purge() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.reports.report_service import ReportService

        return await ReportService(db, None, institution_id=iid).retention_purge()

    return _beat("reports_retention_purge", "reports.core", fn)


@celery.task(name="beat.reports.statutory_due_calendar", queue="scheduled")
def statutory_due_calendar() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.reports.statutory_service import StatutoryService

        return await StatutoryService(db, None, institution_id=iid).due_reminders()

    return _beat("reports_statutory_due_calendar", "reports.statutory", fn)


# ---- consumers ----------------------------------------------------------------------------------------------------------------
@consumer("reports.termly_schedules", events=["academic_term.status_changed"])
async def termly_schedules(db: Any, event: dict[str, Any]) -> None:
    from app.core.features import is_enabled
    from app.services.reports.schedule_service import ScheduleService

    iid = uuid.UUID(str(event["institution_id"]))
    if not await is_enabled(iid, "reports.scheduled"):
        return
    p = event.get("payload") or {}
    await ScheduleService(db, None, institution_id=iid).on_term_status(
        str(p.get("term_id") or ""), str(p.get("to") or p.get("status") or "")
    )


@consumer("reports.submission_due", events=["accreditation.submission_due"])
async def submission_due(db: Any, event: dict[str, Any]) -> None:
    from app.core.features import is_enabled
    from app.services.reports.statutory_service import StatutoryService

    iid = uuid.UUID(str(event["institution_id"]))
    if await is_enabled(iid, "reports.statutory"):
        await StatutoryService(db, None, institution_id=iid).due_reminders()
