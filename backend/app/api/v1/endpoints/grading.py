"""Grading scales and assessment schemes — Prompts/05 §05.8 ``[exams:configure]`` (router included with
``feature_required("academics.regulations")``). Reads also accept ``regulations:view`` — the regulation workspace
shows the schemes of its regulation to the curriculum staff."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.db.session import get_db
from app.schemas.academics import (
    AssessmentComponentsReplace,
    AssessmentSchemeCreate,
    AssessmentSchemeResponse,
    AssessmentSchemeUpdate,
    GradingScaleCreate,
    GradingScaleResponse,
    GradingScaleUpdate,
)
from app.schemas.common import Envelope
from app.services.grading_service import GradingService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["academics"])

GRADING_READ = any_permission_required(("exams", "configure"), ("regulations", "view"))
CONFIGURE = permission_required("exams", "configure")


@router.get("/grading-scales", summary="Grading scales", response_model=Envelope[list[GradingScaleResponse]])
async def list_scales(
    request: Request,
    params: PageParams = Depends(page_params),
    regulation_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=80),
    principal: Principal = Depends(GRADING_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await GradingService(db, principal, request).list_scales(params, regulation_id, q)
    return ok(rows, pagination=pagination)


@router.post(
    "/grading-scales", status_code=201, summary="Create a grading scale", response_model=Envelope[GradingScaleResponse]
)
async def create_scale(
    body: GradingScaleCreate,
    request: Request,
    principal: Principal = Depends(CONFIGURE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GradingService(db, principal, request).create_scale(body), message="Grading scale created")


@router.put("/grading-scales/{id}", summary="Update a grading scale", response_model=Envelope[GradingScaleResponse])
async def update_scale(
    id: uuid.UUID,
    body: GradingScaleUpdate,
    request: Request,
    principal: Principal = Depends(CONFIGURE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GradingService(db, principal, request).update_scale(id, body), message="Grading scale saved")


@router.get(
    "/assessment-schemes", summary="Assessment schemes", response_model=Envelope[list[AssessmentSchemeResponse]]
)
async def list_schemes(
    request: Request,
    params: PageParams = Depends(page_params),
    regulation_id: uuid.UUID | None = None,
    principal: Principal = Depends(GRADING_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await GradingService(db, principal, request).list_schemes(params, regulation_id)
    return ok(rows, pagination=pagination)


@router.post(
    "/assessment-schemes",
    status_code=201,
    summary="Create an assessment scheme (+ components)",
    response_model=Envelope[AssessmentSchemeResponse],
)
async def create_scheme(
    body: AssessmentSchemeCreate,
    request: Request,
    principal: Principal = Depends(CONFIGURE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GradingService(db, principal, request).create_scheme(body), message="Scheme created")


@router.put("/assessment-schemes/{id}", summary="Update a scheme", response_model=Envelope[AssessmentSchemeResponse])
async def update_scheme(
    id: uuid.UUID,
    body: AssessmentSchemeUpdate,
    request: Request,
    principal: Principal = Depends(CONFIGURE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GradingService(db, principal, request).update_scheme(id, body), message="Scheme saved")


@router.put(
    "/assessment-schemes/{id}/components",
    summary="Replace the components (Σ scaled_to = cia_max)",
    response_model=Envelope[AssessmentSchemeResponse],
)
async def replace_components(
    id: uuid.UUID,
    body: AssessmentComponentsReplace,
    request: Request,
    principal: Principal = Depends(CONFIGURE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GradingService(db, principal, request).replace_components(id, body), message="Components saved")
