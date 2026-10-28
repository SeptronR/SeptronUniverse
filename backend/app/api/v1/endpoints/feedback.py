"""In-app feedback endpoint — Prompts/01 §01.8 (router included with ``feature_required("platform.in_app_feedback")``)."""

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.platform import FeedbackCreate, FeedbackResponse
from app.services.feedback_service import FeedbackService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", status_code=201, summary="Submit in-app feedback", response_model=Envelope[FeedbackResponse])
async def create_feedback(
    body: FeedbackCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("dashboard", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.core.rate_limit import check_rate
    from app.enums.portals import FEEDBACK_RATE

    await check_rate("feedback", str(principal.id), *FEEDBACK_RATE)  # Phase 39: 10 per 10 minutes per user
    row = await FeedbackService(db, principal).create(body, request)
    response = ok(FeedbackResponse.model_validate(row), message="Thanks for the feedback")
    await store(request, response, db, 201)
    return response


@router.get(
    "/me", summary="My feedback and its triage status (Phase 38)", response_model=Envelope[list[FeedbackResponse]]
)
async def my_feedback(
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(permission_required("dashboard", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await FeedbackService(db, principal).mine(params)
    return ok([FeedbackResponse.model_validate(r) for r in rows], pagination=pagination)
