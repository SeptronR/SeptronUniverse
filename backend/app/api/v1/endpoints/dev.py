"""Development-only routes (registered when ``APP_ENV=development`` — Prompts/01 §01.11 step 7).

``POST /_dev/jobs/sleep?seconds=5`` enqueues the ``jobs.sleep`` job so the tray / WebSocket progress stream can be
exercised before any business module exists. Protected like every route (``jobs:view`` + ``core.background_jobs``).
``&inline=true`` runs the job body inside the API process (no Celery worker needed — e.g. the fakeredis launcher);
the row, progress events and ``job.finished`` event are produced exactly as a worker would.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.platform import JobResponse
from app.services.job_service import JobService
from app.utils.response import ok

router = APIRouter(prefix="/_dev", tags=["dev"])


@router.post(
    "/jobs/sleep", status_code=202, summary="Enqueue a sleep job (dev only)", response_model=Envelope[JobResponse]
)
async def dev_sleep_job(
    request: Request,
    seconds: int = Query(5, ge=1, le=300),
    inline: bool = Query(False, description="run the job body in-process (no worker) — dev only"),
    principal: Principal = Depends(permission_required("jobs", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await JobService(db, principal).enqueue("sleep", {"seconds": seconds}, queue="reports", request=request)
    if inline:
        from app.core import jobs as jobs_core
        from app.tasks import platform as platform_tasks  # registers jobs.sleep in this process

        await db.commit()  # the worker path would see a committed row; keep the same contract
        body = platform_tasks.sleep_job.run.__wrapped__
        request.app.state.inline_jobs = getattr(request.app.state, "inline_jobs", set())
        task = asyncio.create_task(jobs_core._run(body, row.id))  # noqa: SLF001
        request.app.state.inline_jobs.add(task)
        task.add_done_callback(request.app.state.inline_jobs.discard)
    return ok(JobResponse.model_validate(row), message="Job queued")
