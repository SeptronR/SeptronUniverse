"""Background-job service — Prompts/01 §01.6 (``background_jobs`` + Celery + the ``jobs:{user}`` tray channel).

Business rules
1. ``enqueue`` writes the ``background_jobs`` row inside the caller's transaction and hands the id to Celery
   (``jobs.<job_type>`` unless ``task_name`` overrides it); the row is the source of truth for the tray.
2. Visibility: a requester sees their own jobs; ``jobs:view_all`` widens to the institution; super admin sees all
   (``app/services/platform/visibility.py``). ``get`` answers 404 (never 403) for invisible rows.
3. ``cancel`` sets ``cancel_requested``; a job that never started is closed as ``cancelled`` immediately (and the
   Celery message revoked); a running job stops at its next ``ctx.progress()`` / ``check_cancelled()`` chunk.
   Terminal jobs (succeeded/failed/cancelled) answer ``409 CONFLICT``.
4. ``progress`` publishes ``{job_id, progress_pct, message}`` on ``jobs:{user_id}`` (Redis pub/sub → WebSocket hub).
5. ``cleanup`` (Beat ``jobs.cleanup``, daily 03:00) purges succeeded jobs older than ``JOB_RETENTION_DAYS`` and rows
   past ``expires_at``; result files under ``/uploads`` are deleted with them.
"""

import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.platform.visibility  # noqa: F401
from app.core import events, jobs
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.models.platform import BackgroundJob
from app.repositories.platform_repository import JobRepository
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

log = structlog.get_logger()


class JobService:
    def __init__(self, db: AsyncSession, principal: Principal | None = None):
        self.db, self.principal = db, principal
        self.repo = JobRepository(db, principal)

    async def enqueue(
        self,
        job_type: str,
        params: dict[str, Any] | None = None,
        *,
        queue: str = "reports",
        task_name: str | None = None,
        request: Request | None = None,
    ) -> BackgroundJob:
        """Rule 1 — row + Celery message; audited as ``jobs:enqueue``."""
        row = await jobs.enqueue(self.db, self.principal, job_type, params, queue=queue, task_name=task_name)
        if self.principal is not None:
            await log_audit(
                self.db,
                principal=self.principal,
                module="jobs",
                action="enqueue",
                record_type="background_job",
                record_id=row.id,
                new={"job_type": job_type, "queue": queue, "params": params or {}},
                request=request,
            )
        return row

    async def list(
        self, params: PageParams, scope: str | None = None, status: str | None = None, job_type: str | None = None
    ) -> tuple[list[BackgroundJob], PaginationMeta, VisibilityMeta | None]:
        rows, pagination = await self.repo.list_jobs(params, scope, status, job_type)
        return list(rows), pagination, self.repo.visibility_meta()

    async def get(self, job_id: uuid.UUID) -> BackgroundJob:
        return await self.repo.get(job_id)

    async def cancel(self, job_id: uuid.UUID, request: Request | None = None) -> BackgroundJob:
        """Rule 3."""
        job = await self.repo.get(job_id, for_update=True)
        if job.status in {"succeeded", "failed", "cancelled"}:
            raise APIError(409, ErrorCode.CONFLICT, f"Job is already {job.status}", {"status": job.status})
        was_queued = job.status == "queued"
        job = await self.repo.request_cancel(job)
        if was_queued and job.celery_task_id:
            from app.tasks.celery_app import celery

            with contextlib.suppress(Exception):  # broker hiccups never fail the cancel request
                celery.control.revoke(job.celery_task_id)
        if self.principal is not None:
            await log_audit(
                self.db,
                principal=self.principal,
                module="jobs",
                action="cancel",
                record_type="background_job",
                record_id=job.id,
                new={"status": job.status, "cancel_requested": True},
                request=request,
            )
        await jobs.publish_progress(
            job.requested_by,
            {"job_id": str(job.id), "status": job.status, "cancel_requested": True, "job_type": job.job_type},
        )
        if job.status == "cancelled":
            await events.emit(
                self.db,
                institution_id=job.institution_id,
                event_type="job.finished",
                payload={"job_id": str(job.id), "job_type": job.job_type, "status": "cancelled"},
                aggregate_type="background_job",
                aggregate_id=job.id,
                actor_user_id=getattr(self.principal, "id", None),
            )
        return job

    async def cleanup(self, retention_days: int | None = None) -> dict[str, int]:
        """Rule 5 — Beat job body (no principal; runs on the platform session)."""
        from app.core.files import storage

        cutoff = datetime.now(UTC) - timedelta(days=retention_days or settings.JOB_RETENTION_DAYS)
        rows = await self.repo.purge_succeeded(cutoff)
        files = 0
        for row in rows:
            key = _upload_key(row.result_url)
            if key:
                with contextlib.suppress(Exception):
                    await storage.delete(key)
                    files += 1
            await self.db.delete(row)
        await self.db.flush()
        if rows:
            log.info("jobs_cleanup", purged=len(rows), files=files, cutoff=cutoff.isoformat())
        return {"purged": len(rows), "files": files}


def _upload_key(result_url: str | None) -> str | None:
    """``/uploads/{key}?sig=…`` → ``{key}`` for the local backend; S3 presigned URLs are left to bucket lifecycle rules."""
    if not result_url or not result_url.startswith("/uploads/"):
        return None
    return result_url[len("/uploads/") :].split("?", 1)[0] or None
