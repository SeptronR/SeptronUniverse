"""Tasks on the ``documents`` queue — Prompts/26 §26.7 (names ``documents.<task>`` route here via task_routes).

Jobs: ``documents.bulk_generate`` (with the ZIP), ``documents.backfill_register`` (one-time, per institution),
``documents.registers_export`` (CSV) and ``documents.retention_purge``. Consumers: ``fees.payment_received``
(``source_type='certificate_request'`` → the request proceeds to approval) and ``no_dues.cleared`` (TC / migration
requests waiting on no-dues). Beat: ``documents.request_sla_scan`` (daily), ``documents.pickup_reminders`` (weekly),
``documents.signed_link_cleanup`` (hourly) and ``documents.preview_cleanup`` (daily). Signed links are stateless HMAC
tokens and previews are never stored, so the two cleanups only prune single-use markers / stale verification-log
days.
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
@celery.task(name="jobs.documents.bulk_generate", queue="documents")
@job("documents.bulk_generate", queue="documents")
async def bulk_generate(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.documents import DocBulkGenerateRequest
    from app.services.documents.bulk_service import BulkService

    principal = await _principal(db, ctx)
    body = DocBulkGenerateRequest.model_validate(params)

    async def progress(pct: int, message: str) -> None:
        await ctx.progress(db, pct, message)

    report = await BulkService(db, principal).run(body, ctx.job_id, progress)
    await ctx.progress(db, 100, f"{report['ok']} ok, {len(report['failed'])} failed")
    return report


@celery.task(name="jobs.documents.backfill_register", queue="documents")
@job("documents.backfill_register", queue="documents")
async def backfill_register(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.documents.backfill_service import BackfillService

    principal = await _principal(db, ctx) if ctx.requested_by else None
    report = await BackfillService(db, principal, institution_id=ctx.institution_id).run()
    await ctx.progress(db, 100, "back-filled")
    return report


@celery.task(name="jobs.documents.registers_export", queue="documents")
@job("documents.registers_export", queue="documents")
async def registers_export(ctx: JobContext, db: Any, register: str, **_: Any) -> dict[str, Any]:
    from app.core.files import build_key, get_storage
    from app.services.documents.registers_service import RegistersService

    principal = await _principal(db, ctx)
    csv = await RegistersService(db, principal).export_csv(register)
    key = build_key(ctx.institution_id or "platform", "documents/registers", f"{register}-{ctx.job_id}.csv")
    await get_storage().put(key, csv.encode(), "text/csv")
    return {"register": register, "key": key, "url": get_storage().signed_url(key, 3600)}


@celery.task(name="jobs.documents.retention_purge", queue="documents")
@job("documents.retention_purge", queue="documents")
async def retention_purge(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    return {"purged": await _purge_logs(db, ctx.institution_id)}


async def _purge_logs(db: Any, iid: Any, keep_days: int = 400) -> int:
    from sqlalchemy import text

    res = await db.execute(
        text(
            "DELETE FROM institution_settings WHERE institution_id = :i AND category = 'documents_meta' "
            "AND key LIKE 'verifylog:%' AND to_date(substr(key, 11), 'YYYY-MM-DD') < CURRENT_DATE - :d"
        ),
        {"i": iid, "d": keep_days},
    )
    return int(res.rowcount or 0)


# ---- consumers -------------------------------------------------------------------------------------------------------------
@consumer("documents.request_paid", events=["fees.payment_received"])
async def request_paid(db: Any, event: dict[str, Any]) -> None:
    from app.services.documents.request_service import RequestService

    p = event.get("payload") or {}
    if p.get("source_type") != "certificate_request" or not p.get("source_id"):
        return
    if p.get("invoice_status") not in (None, "paid"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await RequestService(db, None, institution_id=iid).on_paid(uuid.UUID(str(p["source_id"])))


@consumer("documents.no_dues_cleared", events=["no_dues.cleared"])
async def no_dues_cleared(db: Any, event: dict[str, Any]) -> None:
    from app.services.documents.request_service import RequestService

    p = event.get("payload") or {}
    if not p.get("student_program_enrollment_id"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await RequestService(db, None, institution_id=iid).on_no_dues_cleared(
        uuid.UUID(str(p["student_program_enrollment_id"]))
    )


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.documents.request_service import RequestService

        if method == "purge":
            return await _purge_logs(db, iid)
        if method == "noop":
            return 0
        return int(await getattr(RequestService(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.documents.request_sla_scan", queue="scheduled")
def request_sla_scan() -> dict[str, int]:
    return _beat("documents_request_sla_scan", "documents.certificate_requests", "sla_scan")


@celery.task(name="beat.documents.pickup_reminders", queue="scheduled")
def pickup_reminders() -> dict[str, int]:
    return _beat("documents_pickup_reminders", "documents.certificate_requests", "pickup_reminders")


@celery.task(name="beat.documents.signed_link_cleanup", queue="scheduled")
def signed_link_cleanup() -> dict[str, int]:
    return _beat("documents_signed_link_cleanup", "documents.watermark_signed_links", "noop")


@celery.task(name="beat.documents.preview_cleanup", queue="scheduled")
def preview_cleanup() -> dict[str, int]:
    return _beat("documents_preview_cleanup", "documents.templates", "purge")
