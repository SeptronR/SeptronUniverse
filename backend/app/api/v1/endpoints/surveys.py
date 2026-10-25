"""Surveys — Prompts/27 §27.8 {surveys.core} / {surveys.sss}: builder (templates, CO / PO tags, targets, windows,
reminders), lifecycle (open / close / analyse), completion, respondent side (my pending, form, respond with
Idempotency-Key), analytics with the ``min_responses`` guard, comparisons, SSS score and CSV export (job).
``public_router`` serves alumni / employer tokenised links (single use; tenant from the token — ``PUBLIC_ROUTES``).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.core.rate_limit import rate_limited
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.surveys import (
    SvyAnalytics,
    SvyCompare,
    SvyCompletion,
    SvyCreate,
    SvyExternalLinks,
    SvyExternalLinksOut,
    SvyForm,
    SvyOut,
    SvyPending,
    SvyRespond,
    SvyRespondResult,
    SvySssScore,
    SvyUpdate,
)
from app.services.student_support.survey_service import SurveyService
from app.utils.response import ok

router = APIRouter(tags=["surveys"])
public_router = APIRouter(tags=["surveys"])

S = "surveys"
MANAGE = any_permission_required((S, "manage"))
READ = any_permission_required((S, "manage"), (S, "analyse"), (S, "view_all"), (S, "view"))
RESPOND = any_permission_required((S, "respond"), (S, "manage"))
ANALYSE = any_permission_required((S, "analyse"), (S, "manage"), (S, "view_all"))

CORE = [feature_required("surveys.core")]
SSS = [feature_required("surveys.sss")]


@router.get("/surveys", summary="Surveys", response_model=Envelope[list[SvyOut]], dependencies=CORE)
async def list_surveys(
    request: Request,
    status: str | None = None,
    survey_type: str | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).list_surveys(status, survey_type))


@router.post(
    "/surveys",
    status_code=201,
    summary="Create a survey (template questions by type)",
    response_model=Envelope[SvyOut],
    dependencies=CORE,
)
async def create(
    body: SvyCreate, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).create(body), message="Created")


@router.get(
    "/surveys/me/pending",
    summary="My pending surveys (per target)",
    response_model=Envelope[list[SvyPending]],
    dependencies=CORE,
)
async def pending(
    request: Request, principal: Principal = Depends(RESPOND), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).pending())


@router.get(
    "/surveys/sss/score", summary="SSS score (NAAC 2.7.1)", response_model=Envelope[SvySssScore], dependencies=SSS
)
async def sss_score(
    request: Request,
    period: str | None = None,
    principal: Principal = Depends(ANALYSE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).sss_score(period))


@router.get("/surveys/{id}", summary="Survey", response_model=Envelope[SvyOut], dependencies=CORE)
async def get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).get(id))


@router.put("/surveys/{id}", summary="Update a survey", response_model=Envelope[SvyOut], dependencies=CORE)
async def update(
    id: uuid.UUID,
    body: SvyUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).update(id, body))


@router.post("/surveys/{id}/open", summary="Open", response_model=Envelope[SvyOut], dependencies=CORE)
async def open_(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).transition(id, "open"), message="Opened")


@router.post("/surveys/{id}/close", summary="Close", response_model=Envelope[SvyOut], dependencies=CORE)
async def close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).transition(id, "close"), message="Closed")


@router.post(
    "/surveys/{id}/analyse", summary="Analyse (OBE indirect feed)", response_model=Envelope[SvyOut], dependencies=CORE
)
async def analyse(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).transition(id, "analyse"), message="Analysed")


@router.post("/surveys/{id}/remind", summary="Remind non-respondents", response_model=Envelope[dict], dependencies=CORE)
async def remind(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok({"reminded": await SurveyService(db, principal, request).remind(id)})


@router.get(
    "/surveys/{id}/completion",
    summary="Completion dashboard",
    response_model=Envelope[SvyCompletion],
    dependencies=CORE,
)
async def completion(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ANALYSE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).completion(id))


@router.post(
    "/surveys/{id}/external-links",
    status_code=201,
    summary="Tokenised links for alumni / employer respondents",
    response_model=Envelope[SvyExternalLinksOut],
    dependencies=CORE,
)
async def external_links(
    id: uuid.UUID,
    body: SvyExternalLinks,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).external_links(id, body))


@router.get(
    "/surveys/{id}/form", summary="Survey form for a target", response_model=Envelope[SvyForm], dependencies=CORE
)
async def form(
    id: uuid.UUID,
    request: Request,
    target_id: uuid.UUID | None = None,
    principal: Principal = Depends(RESPOND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).form(id, target_id))


@router.post(
    "/surveys/{id}/respond",
    status_code=201,
    summary="Respond (Idempotency-Key; one response per target — 409)",
    response_model=Envelope[SvyRespondResult],
    dependencies=CORE,
)
async def respond(
    id: uuid.UUID,
    body: SvyRespond,
    request: Request,
    key: str | None = Depends(idempotency_key),
    principal: Principal = Depends(RESPOND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    res = ok(await SurveyService(db, principal, request).respond(id, body), message="Thank you")
    await store(request, res, db, 201)
    return res


@router.get(
    "/surveys/{id}/analytics",
    summary="Analytics per target (faculty: own targets after min_responses)",
    response_model=Envelope[SvyAnalytics],
    dependencies=CORE,
)
async def analytics(
    id: uuid.UUID,
    request: Request,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    principal: Principal = Depends(ANALYSE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).analytics(id, target_type, target_id))


@router.get(
    "/surveys/{id}/compare",
    summary="Compare by department / target",
    response_model=Envelope[SvyCompare],
    dependencies=CORE,
)
async def compare(
    id: uuid.UUID,
    request: Request,
    department_id: uuid.UUID | None = None,
    principal: Principal = Depends(ANALYSE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SurveyService(db, principal, request).compare(id, department_id))


@router.get("/surveys/{id}/export", status_code=202, summary="Export responses (job surveys.export)", dependencies=CORE)
async def export(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    await SurveyService(db, principal, request).get(id)
    j = await enqueue(db, principal, "surveys.export", {"survey_id": str(id)}, queue="reports")
    return JSONResponse(status_code=202, content=ok({"job_id": str(j.id)}, message="Queued"))


# ---- public (alumni / employer links) ---------------------------------------------------------------------------------------
async def _tenant(db: AsyncSession, token: str) -> uuid.UUID:
    from app.db.session import bind_tenant, set_tenant

    try:
        iid = uuid.UUID(hex=token.split(".", 1)[0])
    except ValueError:
        raise APIError(404, ErrorCode.NOT_FOUND, "Survey link not found") from None
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "surveys.core"):
        raise APIError(
            403, ErrorCode.FEATURE_DISABLED, "Feature 'surveys.core' is not enabled", {"feature": "surveys.core"}
        )
    return iid


@public_router.get(
    "/surveys/external/{token}",
    summary="External survey form (tokenised link)",
    response_model=Envelope[SvyForm],
    dependencies=[rate_limited("survey_external", limit=30, window=600)],
)
async def external_form(token: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    iid = await _tenant(db, token)
    return ok(await SurveyService(db, None, request, iid).external_form(token))


@public_router.post(
    "/surveys/external/{token}/respond",
    status_code=201,
    summary="External survey response (single use)",
    response_model=Envelope[SvyRespondResult],
    dependencies=[rate_limited("survey_external_respond", limit=10, window=600)],
)
async def external_respond(
    token: str, body: SvyRespond, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    iid = await _tenant(db, token)
    return ok(await SurveyService(db, None, request, iid).external_respond(token, body), message="Thank you")
