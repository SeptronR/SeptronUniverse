"""Platform endpoints — Prompts/01 §01.8: public config, read-only mode, mobile remote config.

Public routes (no auth, listed in ``PUBLIC_ROUTES``): ``GET /public/config``, ``GET /platform/read-only``,
``GET|POST /mobile/config``. ``POST /platform/read-only`` needs ``settings:manage`` (tenant window) — the platform
window additionally requires the super admin (service rule 1) — and the ``platform.read_only_mode`` feature.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.platform import (
    MobileConfigRequest,
    MobileConfigResponse,
    PublicConfig,
    ReadOnlyModeRequest,
    ReadOnlyState,
)
from app.services.platform_service import PlatformService
from app.services.read_only_service import ReadOnlyService
from app.utils.response import ok

router = APIRouter(tags=["platform"])


@router.get(
    "/public/config",
    summary="Platform configuration for clients (packs, themes, captcha, app versions)",
    response_model=Envelope[PublicConfig],
)
async def public_config(
    request: Request,
    institution: str | None = Query(default=None, max_length=60, description="institution slug (optional)"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    slug = institution or getattr(request.state, "institution_slug", None)
    return ok(await PlatformService(db).public_config(slug))


@router.get(
    "/platform/read-only", summary="Current read-only state (platform + tenant)", response_model=Envelope[ReadOnlyState]
)
async def read_only_state(request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    inst = getattr(request.state, "institution_id", None)
    return ok(await ReadOnlyService(db).state(inst))


@router.post(
    "/platform/read-only",
    summary="Open or close a read-only window (tenant: settings:manage; platform: super admin)",
    dependencies=[feature_required("platform.read_only_mode")],
    response_model=Envelope[ReadOnlyState],
)
async def set_read_only(
    body: ReadOnlyModeRequest,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    state = await ReadOnlyService(db, principal).set(body, request)
    return ok(state, message="Read-only mode updated")


@router.get(
    "/mobile/config",
    summary="Mobile remote config (min versions, force update, maintenance banner)",
    response_model=Envelope[MobileConfigResponse],
)
async def mobile_config_get(
    platform: str = Query(default="android", pattern="^(android|ios|web)$"),
    app_version: str | None = Query(default=None, max_length=20, pattern=r"^\d+(\.\d+){0,3}$"),
    institution_slug: str | None = Query(default=None, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    body = MobileConfigRequest(platform=platform, app_version=app_version, institution_slug=institution_slug)  # type: ignore[arg-type]
    return ok(await PlatformService(db).mobile_config(body))


@router.post(
    "/mobile/config",
    summary="Mobile remote config (POST variant used by the app bootstrap)",
    response_model=Envelope[MobileConfigResponse],
)
async def mobile_config_post(body: MobileConfigRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PlatformService(db).mobile_config(body))
