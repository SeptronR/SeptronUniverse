"""Super-admin tenant administration — Prompts/03 §03.8 ``/platform/institutions`` (onboarding wizard, list, detail,
suspend / activate). Cross-tenant by nature: the platform session (BYPASSRLS) and ``super_admin_permission`` — an
institution admin's own ``institutions:manage`` never opens these routes."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, super_admin_permission
from app.core.idempotency import idempotency_key, store
from app.db.session import get_platform_db
from app.enums.institution import InstitutionStatus
from app.schemas.common import Envelope
from app.schemas.institution import (
    OnboardingRequest,
    OnboardingResponse,
    PlatformInstitutionResponse,
    PlatformInstitutionUpdate,
    SuspendRequest,
)
from app.services.institution_service import InstitutionService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(prefix="/platform/institutions", tags=["platform-institutions"])


@router.post(
    "",
    status_code=201,
    summary="Onboard a new institution (roles, pack defaults, plan, first admin)",
    response_model=Envelope[OnboardingResponse],
)
async def onboard(
    body: OnboardingRequest,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(super_admin_permission("institutions", "create")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    response = ok(await InstitutionService(db, principal, request).onboard(body), message="Institution onboarded")
    await store(request, response, db, 201)
    return response


@router.get("", summary="Institutions (tenants)", response_model=Envelope[list[PlatformInstitutionResponse]])
async def list_institutions(
    request: Request,
    params: PageParams = Depends(page_params),
    q: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, pattern="^(pending|active|suspended|archived)$"),
    principal: Principal = Depends(super_admin_permission("institutions", "manage")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    rows, pagination = await InstitutionService(db, principal, request).platform_list(params, q, status)
    return ok(rows, pagination=pagination)


@router.get("/{id}", summary="Institution detail", response_model=Envelope[PlatformInstitutionResponse])
async def get_institution(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(super_admin_permission("institutions", "manage")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await InstitutionService(db, principal, request).platform_get(id))


@router.put("/{id}", summary="Update an institution", response_model=Envelope[PlatformInstitutionResponse])
async def update_institution(
    id: uuid.UUID,
    body: PlatformInstitutionUpdate,
    request: Request,
    principal: Principal = Depends(super_admin_permission("institutions", "manage")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await InstitutionService(db, principal, request).platform_update(id, body), message="Institution updated")


@router.post(
    "/{id}/suspend",
    summary="Suspend (logins refused, sessions revoked)",
    response_model=Envelope[PlatformInstitutionResponse],
)
async def suspend(
    id: uuid.UUID,
    request: Request,
    body: SuspendRequest | None = None,
    principal: Principal = Depends(super_admin_permission("institutions", "manage")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    reason = body.reason if body else None
    row = await InstitutionService(db, principal, request).set_status(id, InstitutionStatus.SUSPENDED, reason)
    return ok(row, message="Institution suspended")


@router.post(
    "/{id}/activate",
    summary="Re-activate a suspended institution",
    response_model=Envelope[PlatformInstitutionResponse],
)
async def activate(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(super_admin_permission("institutions", "manage")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    row = await InstitutionService(db, principal, request).set_status(id, InstitutionStatus.ACTIVE, None)
    return ok(row, message="Institution activated")
