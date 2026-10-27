"""Tasks of Phase 37 — Prompts/37 §37.7.

Jobs: ``retention.purge`` / ``retention.archive`` / ``retention.restore`` (the audit / exam-audit exports run as the
Phase 36 ``report.run`` of the registered ``audit.explorer`` / ``exams.audit_trail`` reports).
Beat (UTC crontabs; institution time IST in the comments): ``audit.digest_daily`` (00:15), ``audit.chain_verify_daily``
(01:00; the whole previous month on the 1st), ``security.anomaly_scan`` (every 5 min), ``retention.purge_daily``
(03:30), ``retention.archive_monthly`` (1st of the month, 02:00). ``partitions.ensure_next_month`` stays in Phase 01.
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal


# ---- jobs -----------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.retention.purge", queue="reports")
@job("retention.purge", queue="reports")
async def retention_purge(ctx: JobContext, db: Any, data_class: str, dry_run: bool = False, **_: Any) -> dict[str, Any]:
    from app.services.audit.retention_service import RetentionService

    principal = await _principal(db, ctx)
    return await RetentionService(db, principal, institution_id=ctx.institution_id).purge_now(data_class, dry_run)


@celery.task(name="jobs.retention.archive", queue="reports")
@job("retention.archive", queue="reports")
async def retention_archive(ctx: JobContext, db: Any, data_class: str, period: str, **_: Any) -> dict[str, Any]:
    from app.services.audit.retention_service import RetentionService

    principal = await _principal(db, ctx)
    return await RetentionService(db, principal, institution_id=ctx.institution_id).archive_now(data_class, period)


@celery.task(name="jobs.retention.restore", queue="reports")
@job("retention.restore", queue="reports")
async def retention_restore(ctx: JobContext, db: Any, manifest_id: str, **_: Any) -> dict[str, Any]:
    from app.services.audit.retention_service import RetentionService

    principal = await _principal(db, ctx)
    return await RetentionService(db, principal, institution_id=ctx.institution_id).restore_now(manifest_id)


# ---- Beat -----------------------------------------------------------------------------------------------------------
def _each(label: str, feature: str, fn: Any) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        return int(await fn(db, iid, today))

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.audit.digest_daily", queue="scheduled")
def digest_daily() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.audit.chain_service import ChainService

        return await ChainService(db, None, institution_id=iid).daily_digest(today)

    return _each("audit_digest_daily", "core.audit_logs", fn)


@celery.task(name="beat.audit.chain_verify_daily", queue="scheduled")
def chain_verify_daily() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.audit.chain_service import ChainService

        return await ChainService(db, None, institution_id=iid).daily_verify(today)

    return _each("audit_chain_verify_daily", "core.audit_logs", fn)


@celery.task(name="beat.security.anomaly_scan", queue="scheduled")
def anomaly_scan() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.audit.security_service import SecurityService

        return await SecurityService(db, None, institution_id=iid).scan()

    return _each("security_anomaly_scan", "core.audit_logs", fn)


@celery.task(name="beat.retention.purge_daily", queue="scheduled")
def purge_daily() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.audit.retention_service import RetentionService

        return await RetentionService(db, None, institution_id=iid).purge_all()

    return _each("retention_purge_daily", "core.settings", fn)


@celery.task(name="beat.retention.archive_monthly", queue="scheduled")
def archive_monthly() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.audit.retention_service import RetentionService

        return await RetentionService(db, None, institution_id=iid).archive_due()

    return _each("retention_archive_monthly", "core.settings", fn)
