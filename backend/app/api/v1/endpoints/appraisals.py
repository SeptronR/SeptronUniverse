"""Appraisals (PBAS) and CAS applications — Prompts/06 §06.8 (``[hr:appraisal; self]`` {hr.appraisal_pbas},
``[hr:cas; self]`` {hr.cas_promotions}). Every staff member holds ``hr:view`` and files their own; reviews and
decisions act on the workflow step addressed to the caller (engine 403 otherwise); screening / deciding CAS needs
``hr:cas``."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.enums.hr import AppraisalStatus, CasStatus
from app.schemas.common import Envelope
from app.schemas.recruitment import (
    AppraisalOut,
    AppraisalReviewIn,
    AppraisalSelfIn,
    CasApplicationIn,
    CasApplicationOut,
    CasDecideIn,
    CasScreenIn,
)
from app.services.appraisal_service import AppraisalService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["hr"])

SELF_OR_HR = any_permission_required(("hr", "view"), ("hr", "appraisal"), ("hr", "cas"))
PBAS = [feature_required("hr.appraisal_pbas")]
CAS = [feature_required("hr.cas_promotions")]


@router.get(
    "/appraisals/schema", summary="The pack's PBAS schema", response_model=Envelope[dict[str, Any]], dependencies=PBAS
)
async def pbas_schema(
    request: Request, principal: Principal = Depends(SELF_OR_HR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok((await AppraisalService(db, principal, request).pack()).hr.pbas_schema)


@router.get(
    "/appraisals",
    summary="Appraisals (self / team / all per visibility + reviewer link)",
    response_model=Envelope[list[AppraisalOut]],
    dependencies=PBAS,
)
async def list_appraisals(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = None,
    status: AppraisalStatus | None = None,
    academic_year_id: uuid.UUID | None = None,
    principal: Principal = Depends(SELF_OR_HR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await AppraisalService(db, principal, request).list_page(
        params, scope, status.value if status else None, academic_year_id
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/appraisals",
    status_code=201,
    summary="Save my self-appraisal (draft; research items auto-filled)",
    response_model=Envelope[AppraisalOut],
    dependencies=PBAS,
)
async def save_appraisal(
    body: AppraisalSelfIn,
    request: Request,
    principal: Principal = Depends(SELF_OR_HR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AppraisalService(db, principal, request).save_self(body), message="Self-appraisal saved")


@router.get("/appraisals/{id}", summary="Appraisal detail", response_model=Envelope[AppraisalOut], dependencies=PBAS)
async def get_appraisal(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF_OR_HR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AppraisalService(db, principal, request).get(id))


@router.post(
    "/appraisals/{id}/submit",
    summary="Submit my self-appraisal (workflow hr.appraisal)",
    response_model=Envelope[AppraisalOut],
    dependencies=PBAS,
)
async def submit_appraisal(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF_OR_HR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AppraisalService(db, principal, request).submit(id), message="Submitted for review")


@router.post(
    "/appraisals/{id}/review",
    summary="Review (acts on the workflow step)",
    response_model=Envelope[AppraisalOut],
    dependencies=PBAS,
)
async def review_appraisal(
    id: uuid.UUID,
    body: AppraisalReviewIn,
    request: Request,
    principal: Principal = Depends(SELF_OR_HR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AppraisalService(db, principal, request).review(id, body))


@router.get(
    "/cas-applications", summary="CAS applications", response_model=Envelope[list[CasApplicationOut]], dependencies=CAS
)
async def list_cas(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = None,
    status: CasStatus | None = None,
    principal: Principal = Depends(SELF_OR_HR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await AppraisalService(db, principal, request).list_cas(
        params, scope, status.value if status else None
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/cas-applications",
    status_code=201,
    summary="Apply for CAS promotion (eligibility computed)",
    response_model=Envelope[CasApplicationOut],
    dependencies=CAS,
)
async def create_cas(
    body: CasApplicationIn,
    request: Request,
    principal: Principal = Depends(SELF_OR_HR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AppraisalService(db, principal, request).create_cas(body), message="CAS application created")


@router.post(
    "/cas-applications/{id}/submit",
    summary="Submit (workflow hr.cas)",
    response_model=Envelope[CasApplicationOut],
    dependencies=CAS,
)
async def submit_cas(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF_OR_HR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AppraisalService(db, principal, request).submit_cas(id), message="Submitted")


@router.post(
    "/cas-applications/{id}/screen",
    summary="Screening / interview status",
    response_model=Envelope[CasApplicationOut],
    dependencies=CAS,
)
async def screen_cas(
    id: uuid.UUID,
    body: CasScreenIn,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "cas")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AppraisalService(db, principal, request).screen_cas(id, body))


@router.post(
    "/cas-applications/{id}/decide",
    summary="Approve (promotion) / reject — acts on the workflow step",
    response_model=Envelope[CasApplicationOut],
    dependencies=CAS,
)
async def decide_cas(
    id: uuid.UUID,
    body: CasDecideIn,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "cas")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AppraisalService(db, principal, request).decide_cas(id, body))
