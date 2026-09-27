"""Development-only routes (registered when ``APP_ENV=development`` — Prompts/01 §01.11 step 7, Prompts/02 §02.11).

``POST /_dev/jobs/sleep?seconds=5`` enqueues the ``jobs.sleep`` job so the tray / WebSocket progress stream can be
exercised before any business module exists. Protected like every route (``jobs:view`` + ``core.background_jobs``).
``&inline=true`` runs the job body inside the API process (no Celery worker needed — e.g. the fakeredis launcher);
the row, progress events and ``job.finished`` event are produced exactly as a worker would.

Phase 02 adds the fixtures its verification script needs before the real modules exist:
``PUT /_dev/users/{id}/validity`` (step 11 — expire a time-boxed account) and ``PUT /_dev/plans/{code}`` (step 14 —
lower a plan's seat limit; Phase 38 ships the real super-admin plan editor). Both are super-admin only and vanish
outside ``APP_ENV=development``.

Phase 03 adds ``POST /_dev/number-sequences/{id}/next`` (step 9 — consume a value the way a business module will;
``settings:manage`` + ``institution.number_sequences_custom``).
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required, super_admin_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db, get_platform_db
from app.models.platform import User
from app.models.saas import SubscriptionPlan
from app.schemas.common import Envelope
from app.schemas.institution import NumberSequenceNext
from app.schemas.platform import JobResponse
from app.services.job_service import JobService
from app.services.sequence_service import SequenceService
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


@router.put(
    "/users/{id}/validity",
    summary="Set a user's valid_from/valid_to (dev fixture)",
    response_model=Envelope[dict[str, Any]],
)
async def set_user_validity(
    id: uuid.UUID,
    valid_from: datetime | None = Body(default=None, embed=True),
    valid_to: datetime | None = Body(default=None, embed=True),
    principal: Principal = Depends(super_admin_required()),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    user = (await db.execute(select(User).where(User.id == id))).scalar_one_or_none()
    if user is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "User not found")
    user.valid_from, user.valid_to = valid_from, valid_to
    await db.flush()
    return ok({"user_id": str(user.id), "valid_from": valid_from, "valid_to": valid_to})


@router.put(
    "/plans/{code}", summary="Set a subscription plan's limits (dev fixture)", response_model=Envelope[dict[str, Any]]
)
async def set_plan_limits(
    code: str,
    student_limit: int | None = Body(default=None, embed=True),
    staff_limit: int | None = Body(default=None, embed=True),
    principal: Principal = Depends(super_admin_required()),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    plan = (await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == code))).scalar_one_or_none()
    if plan is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Plan not found")
    await db.execute(
        update(SubscriptionPlan)
        .where(SubscriptionPlan.id == plan.id)
        .values(student_limit=student_limit, staff_limit=staff_limit)
    )
    return ok({"code": code, "student_limit": student_limit, "staff_limit": staff_limit})


@router.post(
    "/number-sequences/{id}/next",
    summary="Reserve the next value of a sequence (dev fixture)",
    dependencies=[feature_required("institution.number_sequences_custom")],
    response_model=Envelope[NumberSequenceNext],
)
async def next_sequence_value(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SequenceService(db, principal, request).next_by_id(id))
