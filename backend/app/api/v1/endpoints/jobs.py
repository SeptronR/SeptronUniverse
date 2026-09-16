"""Background-job endpoints — Prompts/01 §01.8 (router included with ``feature_required("core.background_jobs")``).

``GET /jobs`` returns the caller's jobs (``jobs:view``), or the institution's with ``jobs:view_all`` (Mine | All tabs via
``meta.visibility``); ``POST /jobs/{id}/cancel`` needs ``jobs:cancel``.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.platform import JobResponse
from app.services.job_service import JobService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", summary="My background jobs (all with jobs:view_all)", response_model=Envelope[list[JobResponse]])
async def list_jobs(
    params: PageParams = Depends(page_params),
    scope: str | None = Query(None, pattern="^(self|own|all)$"),
    status: str | None = Query(None, pattern="^(queued|running|succeeded|failed|cancelled)$"),
    job_type: str | None = Query(None, max_length=80),
    principal: Principal = Depends(permission_required("jobs", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await JobService(db, principal).list(params, scope, status, job_type)
    return ok([JobResponse.model_validate(r) for r in rows], pagination=pagination, visibility=visibility)


@router.get("/{id}", summary="Job status", response_model=Envelope[JobResponse])
async def get_job(
    id: uuid.UUID,
    principal: Principal = Depends(permission_required("jobs", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(JobResponse.model_validate(await JobService(db, principal).get(id)))


@router.post(
    "/{id}/cancel", summary="Request cancellation of a queued/running job", response_model=Envelope[JobResponse]
)
async def cancel_job(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("jobs", "cancel")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    job = await JobService(db, principal).cancel(id, request)
    return ok(JobResponse.model_validate(job), message="Cancellation requested")
