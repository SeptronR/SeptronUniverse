"""Super-admin tenant administration — Prompts/03 §03.8 ``/platform/institutions`` (onboarding wizard, list, detail,
suspend / activate), extended by Prompts/38 §38.8: the wizard takes a template / trial / custom domain
(``institution_admin_service.onboard``, synchronous so the wizard can show the one-time password; self-serve
registrations provision through the ``tenant.provision`` job), the list filters by status / plan / type / health and returns plan, seats, storage and health, the
detail aggregates subscription, usage, flags, connections, tickets, impersonations and chain integrity. Lifecycle,
export, reset and erasure live in ``saas_platform.py``. Cross-tenant by nature: the platform session (BYPASSRLS);
support agents read (``platform:view``), writes stay super admin only."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, platform_permission, super_admin_permission
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
from app.schemas.saas import InstitutionAdminOut, InstitutionDetailOut
from app.services.institution_service import InstitutionService
from app.services.saas.institution_admin_service import InstitutionAdminService
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
    response = ok(await InstitutionAdminService(db, principal, request).onboard(body), message="Institution onboarded")
    await store(request, response, db, 201)
    return response


@router.get(
    "", summary="Institutions with plan, seats, storage and health", response_model=Envelope[list[InstitutionAdminOut]]
)
async def list_institutions(
    q: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, pattern="^(pending|active|suspended|archived)$"),
    plan: str | None = Query(default=None, max_length=30),
    type: str | None = Query(default=None, max_length=30),  # noqa: A002
    health: str | None = Query(default=None, pattern="^(ok|degraded|failing|none)$"),
    principal: Principal = Depends(platform_permission("platform", "view")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await InstitutionAdminService(db, principal).list_institutions(status, plan, type, q, health))


@router.get(
    "/{id}",
    summary="Institution detail (subscription, usage, flags, health, tickets, chain integrity)",
    response_model=Envelope[InstitutionDetailOut],
)
async def get_institution(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(platform_permission("platform", "view")),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await InstitutionAdminService(db, principal, request).detail(id))


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
