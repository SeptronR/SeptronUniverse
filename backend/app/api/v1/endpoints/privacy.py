"""Privacy, entitlements and the one-time install — Prompts/02 §02.8.

Consents {privacy.dpdp_consent} and data-subject requests {privacy.data_subject_requests} are self-service; the
privacy officer (``settings:manage``) sees every request of the institution. ``GET /entitlements`` needs
``settings:view``. ``POST /install`` is public and guarded by ``INSTALL_SECRET_KEY`` (409 once installed).
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, authenticated, permission_required
from app.core.features import feature_required
from app.core.rate_limit import rate_limited
from app.db.session import get_db, get_platform_db
from app.schemas.common import Envelope
from app.schemas.privacy import (
    ConsentRequest,
    ConsentResponse,
    DataSubjectRequestCreate,
    DataSubjectRequestResponse,
    DsrOut,
)
from app.schemas.saas import EntitlementsResponse, InstallRequest, InstallResponse
from app.services.entitlement_service import EntitlementService
from app.services.install_service import InstallService
from app.services.hardening.privacy_office import PrivacyOfficeService
from app.services.privacy_service import PrivacyService
from app.utils.response import ok

router = APIRouter(tags=["privacy"])


@router.post(
    "/consents",
    status_code=201,
    summary="Record or withdraw a consent",
    response_model=Envelope[ConsentResponse],
    dependencies=[feature_required("privacy.dpdp_consent")],
)
async def record_consent(
    body: ConsentRequest,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PrivacyService(db, principal).record_consent(body, request), message="Consent recorded")


@router.get(
    "/consents/me",
    summary="My current consents (latest decision per purpose)",
    response_model=Envelope[list[ConsentResponse]],
    dependencies=[feature_required("privacy.dpdp_consent")],
)
async def my_consents(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyService(db, principal).my_consents())


@router.post(
    "/data-subject-requests",
    status_code=201,
    summary="Raise a data-subject request (access / export / correction / erasure)",
    response_model=Envelope[DsrOut],
    dependencies=[feature_required("privacy.data_subject_requests")],
)
async def create_dsr(
    body: DataSubjectRequestCreate,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # Phase 43: on-behalf (guardian) requests, identity OTP, timeline — the privacy office workflow
    return ok(await PrivacyOfficeService(db, principal, request).create(body), message="Request received")


@router.get(
    "/data-subject-requests/me",
    summary="My data-subject requests",
    response_model=Envelope[list[DataSubjectRequestResponse]],
    dependencies=[feature_required("privacy.data_subject_requests")],
)
async def my_dsrs(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyService(db, principal).my_requests())


@router.get(
    "/data-subject-requests",
    summary="Data-subject requests (Mine | All for the privacy officer)",
    response_model=Envelope[list[DsrOut]],
    dependencies=[feature_required("privacy.data_subject_requests")],
)
async def all_dsrs(
    scope: str = Query(default="all", pattern="^(mine|all)$"),
    status: str | None = Query(default=None, max_length=20),
    principal: Principal = Depends(
        any_permission_required(("privacy", "manage"), ("privacy", "view_all"), ("settings", "manage"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).list(scope, status))


@router.get("/entitlements", summary="Plan, status, limits and usage", response_model=Envelope[EntitlementsResponse])
async def entitlements(
    principal: Principal = Depends(permission_required("settings", "view")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EntitlementService(db, principal).entitlements())


@router.post(
    "/install",
    summary="One-time platform bootstrap (INSTALL_SECRET_KEY)",
    response_model=Envelope[InstallResponse],
    dependencies=[rate_limited("install", limit=5, window=300)],
)
async def install(
    body: InstallRequest, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    result = await InstallService(db).install(
        install_key=body.install_key,
        email=body.super_admin_email,
        password=body.super_admin_password,
        username=body.super_admin_username,
        request=request,
    )
    return ok(InstallResponse(**result), message="Platform installed")
