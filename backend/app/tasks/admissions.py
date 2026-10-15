"""Admissions tasks — Prompts/08 §08.7.

Jobs (run as the requesting user through ``load_principal`` so scopes and audit apply as for the API):
``jobs.admissions.merit_generate`` (rank a draft merit list), ``jobs.admissions.allotment_run`` (a counselling round's
seat allotment under ``FOR UPDATE`` seat locks), ``jobs.admissions.import`` (counselling CSV) and
``jobs.admissions.export`` (XLSX → signed ``result_url``). Beat (per institution with the feature on):
``admissions.lapse_allotments`` (hourly), ``admissions.close_cycles`` (daily 00:20) and
``enquiries.follow_up_reminders`` (daily 09:00, the institution's local date).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal


async def _progress_fn(ctx: JobContext, db: Any) -> Any:
    async def progress(pct: int, message: str) -> None:
        await ctx.progress(db, pct, message)

    return progress


@celery.task(name="jobs.admissions.merit_generate", queue="reports")
@job("admissions.merit_generate", queue="reports")
async def admissions_merit_generate(ctx: JobContext, db: Any, merit_list_id: str, **_: Any) -> dict[str, Any]:
    from app.services.admissions.merit_service import MeritService

    principal = await _principal(db, ctx)
    return await MeritService(db, principal).run_generate(uuid.UUID(merit_list_id), await _progress_fn(ctx, db))


@celery.task(name="jobs.admissions.allotment_run", queue="reports")
@job("admissions.allotment_run", queue="reports")
async def admissions_allotment_run(ctx: JobContext, db: Any, round_id: str, **_: Any) -> dict[str, Any]:
    from app.services.admissions.counselling_service import CounsellingService

    principal = await _principal(db, ctx)
    summary = await CounsellingService(db, principal).allot(
        uuid.UUID(round_id), persist=True, progress=await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{summary.allotted} allotted, {summary.upgraded} upgraded")
    return summary.model_dump(mode="json", exclude={"allotments"})


@celery.task(name="jobs.admissions.import", queue="reports")
@job("admissions.import", queue="reports")
async def admissions_import(
    ctx: JobContext, db: Any, cycle_id: str, key: str, mapping: dict[str, str] | None = None, **_: Any
) -> dict[str, Any]:
    from app.core.files import storage
    from app.services.admissions.application_service import ApplicationService

    principal = await _principal(db, ctx)
    content = await storage.get(key)
    report = await ApplicationService(db, principal).run_import(
        uuid.UUID(cycle_id), content, mapping, await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{report['succeeded']} imported, {len(report['failed'])} failed")
    return report


@celery.task(name="jobs.admissions.export", queue="reports")
@job("admissions.export", queue="reports")
async def admissions_export(
    ctx: JobContext, db: Any, filters: dict[str, Any] | None = None, **_: Any
) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.admissions.application_service import ApplicationService

    principal = await _principal(db, ctx)
    clean: dict[str, Any] = {}
    for k, v in (filters or {}).items():
        clean[k] = uuid.UUID(v) if k.endswith("_id") and isinstance(v, str) else v
    content = await ApplicationService(db, principal).export_xlsx(**clean)
    key = build_key(ctx.institution_id or "platform", "admission-exports", "applicants.xlsx")
    await storage.put(key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    await ctx.progress(db, 100, "Export ready")
    return {"result_url": storage.signed_url(key, 24 * 3600), "bytes": len(content)}


# ---- Beat ------------------------------------------------------------------------------------------------------------
@celery.task(name="beat.admissions.lapse_allotments", queue="scheduled")
def lapse_allotments() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.admissions.counselling_service import CounsellingService

        return await CounsellingService(db, None, institution_id=iid).lapse_due()

    return run_async(_for_institutions("admissions.counselling_allotment", one, "admissions_lapse_allotments"))


@celery.task(name="beat.admissions.close_cycles", queue="scheduled")
def close_cycles() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.admissions.cycle_service import CycleService

        return await CycleService(db, None, institution_id=iid).close_due()

    return run_async(_for_institutions("admissions.cycles", one, "admissions_close_cycles"))


@celery.task(name="beat.enquiries.follow_up_reminders", queue="scheduled")
def follow_up_reminders() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.admissions.enquiry_service import EnquiryService

        return await EnquiryService(db, None, institution_id=iid).follow_up_reminders(today)

    return run_async(_for_institutions("admissions.enquiry_crm", one, "enquiries_follow_up_reminders"))
