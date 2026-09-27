"""Background jobs helper + ``@job`` decorator — Prompts/00_PREREQUISITE_Project_Setup.md §3.16, Prompts/01 §01.6.

``await jobs.enqueue(db, principal, job_type, params)`` creates the ``background_jobs`` row and sends the Celery task
(``apply_async(args=[job_id], queue=...)``). Tasks wrapped with ``@job("hall_tickets.generate", queue="documents")``
receive a ``JobContext`` whose ``progress(pct, message)`` updates the row and publishes on ``jobs:{user}``; the wrapper
marks ``running → succeeded | failed | cancelled``, honours ``cancel_requested`` between chunks, records
``result_url``/``result``/``error`` and emits the ``job.finished`` domain event (outbox). ``JobService``
(``services/job_service.py``) adds listing, cancel and cleanup on top.
"""

import contextlib
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.aio import run_async
from app.core.errors import APIError, ErrorCode
from app.models.platform import BackgroundJob, DomainEvent

QUEUES = ("notifications", "emails", "documents", "reports", "integrations", "scheduled")
TERMINAL = {"succeeded", "failed", "cancelled"}

log = structlog.get_logger()


class JobCancelled(Exception):
    """Raised inside a task when ``cancel_requested`` was set; the wrapper marks the job ``cancelled``."""


class JobContext:
    def __init__(
        self,
        job_id: uuid.UUID,
        institution_id: uuid.UUID | None,
        requested_by: uuid.UUID | None,
        job_type: str | None = None,
    ):
        self.job_id = job_id
        self.institution_id = institution_id
        self.requested_by = requested_by
        self.job_type = job_type

    async def progress(self, db: AsyncSession, pct: int, message: str | None = None) -> None:
        pct = max(0, min(100, int(pct)))
        await db.execute(
            update(BackgroundJob).where(BackgroundJob.id == self.job_id).values(progress_pct=pct, message=message)
        )
        await db.commit()
        await publish_progress(
            self.requested_by,
            {
                "job_id": str(self.job_id),
                "job_type": self.job_type,
                "status": "running",
                "progress_pct": pct,
                "message": message,
            },
        )
        await self.check_cancelled(db)

    async def check_cancelled(self, db: AsyncSession) -> None:
        flag = (
            await db.execute(select(BackgroundJob.cancel_requested).where(BackgroundJob.id == self.job_id))
        ).scalar_one_or_none()
        if flag:
            raise JobCancelled()


async def publish_progress(user_id: uuid.UUID | None, payload: dict[str, Any]) -> None:
    """Fan out on the Redis channel the WebSocket hub relays to the jobs tray (``jobs:{user}``)."""
    if not user_id:
        return
    from app.db.session import redis_client

    with contextlib.suppress(Exception):  # degraded Redis never fails a job
        await redis_client.publish(f"jobs:{user_id}", json.dumps(payload, default=str))


def send_after_commit(db: AsyncSession, task_name: str, args: list[Any], queue: str, task_id: str) -> None:
    """Queue a Celery message to be sent once ``db`` commits (dropped if the transaction rolls back)."""
    from sqlalchemy import event

    sync = db.sync_session
    pending: list[tuple[str, list[Any], str, str]] = sync.info.setdefault("celery_after_commit", [])
    pending.append((task_name, args, queue, task_id))
    if sync.info.get("celery_hooks"):
        return
    sync.info["celery_hooks"] = True

    @event.listens_for(sync, "after_commit")
    def _send(session: Any) -> None:
        from app.tasks.celery_app import celery

        messages = session.info.pop("celery_after_commit", [])
        for name, task_args, q, tid in messages:
            try:
                celery.send_task(name, args=task_args, queue=q, task_id=tid)
            except Exception as exc:  # noqa: BLE001 - the row stays queued; jobs.cleanup / a retry can pick it up
                log.warning("job_send_failed", task=name, error=str(exc)[:200])

    @event.listens_for(sync, "after_rollback")
    def _drop(session: Any) -> None:
        session.info.pop("celery_after_commit", None)


async def enqueue(
    db: AsyncSession,
    principal: Any,
    job_type: str,
    params: dict[str, Any] | None = None,
    *,
    queue: str = "reports",
    task_name: str | None = None,
) -> BackgroundJob:
    """Create the job row and hand it to Celery. ``task_name`` defaults to ``jobs.<job_type>``."""
    if queue not in QUEUES:
        raise APIError(400, ErrorCode.VALIDATION, f"Unknown queue {queue!r}")
    row = BackgroundJob(
        institution_id=getattr(principal, "institution_id", None),
        job_type=job_type,
        params=params or {},
        status="queued",
        requested_by=getattr(principal, "id", None),
    )
    db.add(row)
    await db.flush()
    # The worker claims the row by id, so the Celery message must not leave before the row is committed: an idle
    # worker otherwise reads "no such queued job" and drops it (found by the live 01_platform.ps1). The task id is
    # assigned now and the message is sent from the session's after_commit hook (discarded on rollback).
    task_id = str(uuid.uuid4())
    row.celery_task_id = task_id
    await db.flush()
    send_after_commit(db, task_name or f"jobs.{job_type}", [str(row.id)], queue, task_id)
    await publish_progress(
        row.requested_by, {"job_id": str(row.id), "job_type": job_type, "status": "queued", "progress_pct": 0}
    )
    return row


def job(job_type: str, queue: str = "reports") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Wrap a Celery task body ``async def fn(ctx: JobContext, db: AsyncSession, **params)``.

    Creates/updates the ``background_jobs`` row, streams progress on ws channel ``jobs:{user}``, honours
    ``cancel_requested`` and records ``result_url``/``result``/``error``.
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(job_id: str, *args: Any, **kwargs: Any) -> Any:
            return run_async(_run(fn, uuid.UUID(job_id), *args, **kwargs))

        wrapper.__job_type__ = job_type  # type: ignore[attr-defined]
        wrapper.__queue__ = queue  # type: ignore[attr-defined]
        return wrapper

    return deco


async def _run(fn: Callable[..., Any], job_id: uuid.UUID, *args: Any, **kwargs: Any) -> Any:
    # bookkeeping (claim the row, record the outcome) runs on the platform session — the worker has no tenant context
    # yet and RLS would hide a tenant's job from the app role; the job body itself runs on tenant_session(institution)
    from app.db.session import PlatformSessionLocal, tenant_session

    now = datetime.now(UTC)
    structlog.contextvars.bind_contextvars(job_id=str(job_id))
    try:
        async with PlatformSessionLocal() as db:
            row = (
                await db.execute(
                    select(BackgroundJob).where(BackgroundJob.id == job_id).with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if row is None or row.status != "queued" or row.cancel_requested:
                # unknown, already started/finished elsewhere, or cancelled while queued (JobService.cancel closed it)
                return None
            row.status, row.started_at = "running", now
            await db.commit()
            ctx = JobContext(job_id, row.institution_id, row.requested_by, row.job_type)
            params = dict(row.params or {})
        await publish_progress(
            ctx.requested_by, {"job_id": str(job_id), "job_type": ctx.job_type, "status": "running", "progress_pct": 0}
        )
        session = await tenant_session(ctx.institution_id) if ctx.institution_id else PlatformSessionLocal()
        result_url: str | None = None
        result_json: dict[str, Any] | None = None
        try:
            result = await fn(ctx, session, *args, **{**params, **kwargs})
            await session.commit()
            status, error = "succeeded", None
            if isinstance(result, dict):
                result_url = result.get("result_url")
                result_json = result
        except JobCancelled:
            await session.rollback()
            status, error = "cancelled", None
        except Exception as exc:  # noqa: BLE001 - the failure is recorded on the job row
            await session.rollback()
            status, error = "failed", str(exc)[:2000]
            log.warning("job_failed", job_type=ctx.job_type, error=error)
        finally:
            await session.close()
        finished_at = datetime.now(UTC)
        async with PlatformSessionLocal() as db:
            await db.execute(
                update(BackgroundJob)
                .where(BackgroundJob.id == job_id)
                .values(
                    status=status,
                    error=error,
                    result_url=result_url,
                    result=result_json,
                    progress_pct=100 if status == "succeeded" else BackgroundJob.progress_pct,
                    finished_at=finished_at,
                )
            )
            # job.finished rides the outbox like every other domain event (Prompts/01 §01.7)
            db.add(
                DomainEvent(
                    institution_id=ctx.institution_id,
                    event_type="job.finished",
                    aggregate_type="background_job",
                    aggregate_id=job_id,
                    payload={
                        "job_id": str(job_id),
                        "job_type": ctx.job_type,
                        "status": status,
                        "result_url": result_url,
                        "error": error,
                    },
                    actor_user_id=ctx.requested_by,
                )
            )
            await db.commit()
        await publish_progress(
            ctx.requested_by,
            {
                "job_id": str(job_id),
                "job_type": ctx.job_type,
                "status": status,
                "progress_pct": 100 if status == "succeeded" else None,
                "result_url": result_url,
                "error": error,
            },
        )
        return result_json
    finally:
        structlog.contextvars.unbind_contextvars("job_id")
