"""Feature-flag endpoints — Prompts/02 §02.8 (router included with ``feature_required("core.rbac")``).

``GET /features`` is the registry; ``/institutions/{id}/features`` the per-tenant effective state (super admin, or the
institution admin for their own tenant); ``PUT /institutions/{id}/features/{key}`` is the platform toggle (super admin
only — ``features:manage`` is platform-only); ``PUT /features/{key}/institution-toggle`` is the institution admin's own
switch (``features:institution_toggle``). The tenant-scoped routes pin the RLS context to the institution in the path
so the super admin's session can read/write its ``institution_feature_flags`` rows.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required, super_admin_required
from app.core.errors import APIError, ErrorCode
from app.db.session import bind_tenant, get_db, get_platform_db, set_tenant
from app.schemas.common import Envelope
from app.schemas.features import (
    ApplyPlanDefaultsResponse,
    FeatureDefResponse,
    FeatureMatrixResponse,
    FeatureToggleRequest,
    InstitutionFeatureFlagResponse,
    InstitutionFeaturesResponse,
    InstitutionToggleRequest,
)
from app.services.feature_service import FeatureService, institution_exists
from app.utils.response import ok

router = APIRouter(tags=["features"])


async def _tenant_context(db: AsyncSession, principal: Principal, institution_id: uuid.UUID) -> None:
    """Super admin: pin RLS to the target tenant. Institution users: only their own institution."""
    if not principal.is_super_admin and principal.institution_id != institution_id:
        raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")
    bind_tenant(db, institution_id)
    await set_tenant(db, institution_id)
    if not await institution_exists(db, institution_id):
        raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")


@router.get("/features", summary="Feature registry (definitions)", response_model=Envelope[list[FeatureDefResponse]])
async def list_features(
    principal: Principal = Depends(permission_required("features", "view")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FeatureService(db, principal).list_definitions())


@router.get(
    "/institutions/{id}/features",
    summary="Effective feature flags of an institution (+ change log)",
    response_model=Envelope[InstitutionFeaturesResponse],
)
async def institution_features(
    id: uuid.UUID,
    principal: Principal = Depends(permission_required("features", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _tenant_context(db, principal, id)
    return ok(await FeatureService(db, principal).list_institution_flags(id))


@router.put(
    "/institutions/{id}/features/{key}",
    summary="Platform toggle for one feature (super admin)",
    response_model=Envelope[InstitutionFeatureFlagResponse],
)
async def set_platform_flag(
    id: uuid.UUID,
    key: str,
    body: FeatureToggleRequest,
    request: Request,
    principal: Principal = Depends(super_admin_required()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _tenant_context(db, principal, id)
    result = await FeatureService(db, principal).set_platform_flag(
        id,
        key,
        enabled=body.enabled,
        reason=body.reason,
        config=body.config,
        confirm_dependencies=body.confirm_dependencies,
        request=request,
    )
    return ok(result, message=f"Feature {'enabled' if body.enabled else 'disabled'}")


@router.post(
    "/institutions/{id}/features/apply-plan-defaults",
    summary="Reset flags to the plan defaults (overrides survive)",
    response_model=Envelope[ApplyPlanDefaultsResponse],
)
async def apply_plan_defaults(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(super_admin_required()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _tenant_context(db, principal, id)
    return ok(await FeatureService(db, principal).apply_plan_defaults(id, request), message="Plan defaults applied")


@router.put(
    "/features/{key}/institution-toggle",
    summary="Institution admin's own on/off switch for a feature",
    response_model=Envelope[InstitutionFeatureFlagResponse],
)
async def institution_toggle(
    key: str,
    body: InstitutionToggleRequest,
    request: Request,
    principal: Principal = Depends(permission_required("features", "institution_toggle")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if principal.institution_id is None:
        raise APIError(422, ErrorCode.VALIDATION, "An institution context is required")
    result = await FeatureService(db, principal).set_institution_flag(
        principal.institution_id, key, enabled=body.enabled, reason=body.reason, request=request
    )
    return ok(result, message=f"Feature {'enabled' if body.enabled else 'disabled'} for this institution")


@router.get(
    "/platform/features/matrix",
    summary="Institutions × features (super admin)",
    response_model=Envelope[FeatureMatrixResponse],
)
async def feature_matrix(
    principal: Principal = Depends(super_admin_required()), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await FeatureService(db, principal).matrix())
