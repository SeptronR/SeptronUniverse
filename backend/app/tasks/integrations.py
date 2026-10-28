"""Tasks of Phase 41 — Prompts/41 §41.7 (integrations hub, webhooks, migration toolkit, exports).

Jobs: ``imports.validate`` / ``imports.apply`` / ``imports.rollback`` (as the requesting user, through the module
services), ``exports.user`` (JSON in the file store, signed link), ``integrations.reencrypt_secrets``.
Beat (UTC): ``webhooks.retry_due`` (every minute), ``api_keys.expiry_reminders`` (Mondays 03:30 = 09:00 IST),
``imports.expire_unapplied`` (daily 20:40 = 02:10 IST). The Phase 01 ``integrations.health`` Beat now records
degraded / failed / recovered through ``connection_service.record_health``.
Consumer ``webhooks.fanout`` on every domain event (``*``) creates the outbound deliveries.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
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
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        try:
            out = await fn(db)
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            raise


@celery.task(name="jobs.imports.validate", queue="reports")
@job("imports.validate", queue="reports")
async def imports_validate(ctx: JobContext, db: Any, import_id: str, **_: Any) -> dict[str, Any]:
    from app.services.integrations.import_service import ImportService

    out = await ImportService(db, await _principal(db, ctx)).validate(uuid.UUID(import_id))
    return {"valid_rows": out.valid_rows, "error_rows": out.error_rows}


@celery.task(name="jobs.imports.apply", queue="reports")
@job("imports.apply", queue="reports")
async def imports_apply(
    ctx: JobContext, db: Any, import_id: str, on_conflict: str = "skip", **_: Any
) -> dict[str, Any]:
    from app.services.integrations.import_service import ImportService

    out = await ImportService(db, await _principal(db, ctx)).apply(uuid.UUID(import_id), on_conflict)
    return dict(out.report or {})


@celery.task(name="jobs.imports.rollback", queue="reports")
@job("imports.rollback", queue="reports")
async def imports_rollback(ctx: JobContext, db: Any, import_id: str, reason: str = "", **_: Any) -> dict[str, Any]:
    from app.services.integrations.import_service import ImportService

    out = await ImportService(db, await _principal(db, ctx)).rollback(uuid.UUID(import_id), reason)
    return dict(out.report or {})


@celery.task(name="jobs.exports.user", queue="reports")
@job("exports.user", queue="reports")
async def exports_user(ctx: JobContext, db: Any, user_id: str, **_: Any) -> dict[str, Any]:
    from app.core.files import storage
    from app.services.integrations.import_service import export_user

    data = await export_user(db, ctx.institution_id, uuid.UUID(user_id))  # type: ignore[arg-type]
    key = f"{ctx.institution_id}/exports/user-{user_id}-{uuid.uuid4().hex[:8]}.json"
    await storage.put(key, json.dumps(data, default=str, indent=1).encode(), "application/json")
    from app.core.notifications.notify import notify_event

    await notify_event(
        db,
        ctx.institution_id,
        "exports.ready",
        audience={"user_ids": [str(ctx.requested_by)]},
        context={"route": "/admin/exports"},
    )
    return {"result_url": storage.signed_url(key, 7 * 86400), "sections": len(data)}


@celery.task(name="jobs.integrations.reencrypt_secrets", queue="reports")
@job("integrations.reencrypt_secrets", queue="reports")
async def reencrypt(ctx: JobContext, db: Any, kid: str = "v2", **_: Any) -> dict[str, Any]:
    from app.services.integrations.connection_service import reencrypt_all

    return {"connections": await _platform(lambda pdb: reencrypt_all(pdb, kid))}


@celery.task(name="beat.webhooks.retry_due", queue="scheduled")
def webhooks_retry_due() -> dict[str, int]:
    from app.services.integrations.webhook_service import retry_due

    out: dict[str, int] = run_async(_platform(retry_due))
    if out:
        log.info("beat_webhooks_retry_due", **out)
    return out


@celery.task(name="beat.api_keys.expiry_reminders", queue="scheduled")
def api_key_reminders() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        from app.core.notifications.notify import notify_event

        rows = (
            await db.execute(
                text(
                    "SELECT id, institution_id, name, expires_at FROM api_keys WHERE is_active AND expires_at BETWEEN NOW() AND NOW() + INTERVAL '7 days'"
                )
            )
        ).all()
        for _kid, inst, name, exp in rows:
            await notify_event(
                db,
                inst,
                "integrations.api_key_expiring",
                audience={"roles": ["integration_admin"]},
                context={"name": name, "expires_at": exp.isoformat(), "route": "/admin/integrations/api-keys"},
            )
        return {"reminded": len(rows)}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.imports.expire_unapplied", queue="scheduled")
def imports_expire() -> dict[str, int]:
    async def fn(db: Any) -> dict[str, int]:
        res = await db.execute(
            text(
                "UPDATE data_imports SET status = 'expired' WHERE status IN ('uploaded', 'validated') AND created_at < :t"
            ),
            {"t": datetime.now(UTC) - timedelta(days=7)},
        )
        return {"expired": int(getattr(res, "rowcount", 0) or 0)}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@consumer("webhooks.fanout", events=["*"])
async def webhooks_fanout(db: Any, event: dict[str, Any]) -> None:
    from app.services.integrations.webhook_service import fanout

    await fanout(db, event)
