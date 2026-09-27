"""Settings — Prompts/03 §03.8 (router included with ``feature_required("core.settings")``).

``GET /settings`` (``settings:view``) returns the typed template merged with the institution's values (one entry per
category, or the ``category`` asked for); ``PUT /settings`` (``settings:manage``) bulk-updates with type validation;
``GET /settings/public`` is unauthenticated (``PUBLIC_ROUTES``) and exposes only ``is_public`` keys + the resolved
theme of the tenant named by ``?institution=<slug>`` / ``X-Institution-Slug`` / ``X-Institution-Id``;
``POST /settings/test-provider`` sends a test SMS / e-mail / WhatsApp / push through the adapter registry (202).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.db.session import bind_tenant, get_db, set_tenant
from app.repositories.institution_repository import InstitutionRepository
from app.schemas.common import Envelope
from app.schemas.settings import (
    ProviderTestRequest,
    ProviderTestResponse,
    PublicSettingsResponse,
    SettingsBulkUpdate,
    SettingsCategoryResponse,
)
from app.services.settings_service import SettingsService
from app.utils.response import ok

router = APIRouter(tags=["settings"])


@router.get(
    "/settings",
    summary="Settings by category (typed template + values)",
    response_model=Envelope[list[SettingsCategoryResponse]],
)
async def get_settings(
    request: Request,
    category: str | None = Query(default=None, max_length=40),
    college_id: uuid.UUID | None = Query(default=None, description="merge this college's overrides"),
    principal: Principal = Depends(permission_required("settings", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SettingsService(db, principal).get(request, category, college_id))


@router.put(
    "/settings",
    summary="Bulk update settings (typed, audited)",
    response_model=Envelope[list[SettingsCategoryResponse]],
)
async def update_settings(
    body: SettingsBulkUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SettingsService(db, principal).bulk_update(body.items, request), message="Settings saved")


@router.get(
    "/settings/public", summary="Public settings + theme (no auth)", response_model=Envelope[PublicSettingsResponse]
)
async def public_settings(
    request: Request,
    institution: str | None = Query(default=None, max_length=60, description="institution slug"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    inst_id: uuid.UUID | None = None
    slug = institution or getattr(request.state, "institution_slug", None)
    if slug:
        row = await InstitutionRepository(db).by_slug(slug)
        inst_id = row.id if row is not None else None
    elif getattr(request.state, "institution_id", None):
        inst_id = uuid.UUID(str(request.state.institution_id))
    if inst_id is not None:
        # unauthenticated: pin the RLS context to the resolved tenant (the app role sees nothing otherwise)
        bind_tenant(db, inst_id)
        await set_tenant(db, inst_id)
    return ok(await SettingsService(db).public(inst_id))


@router.post(
    "/settings/test-provider",
    status_code=202,
    summary="Send a test SMS / e-mail / WhatsApp / push (message_logs row)",
    response_model=Envelope[ProviderTestResponse],
)
async def test_provider(
    body: ProviderTestRequest,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SettingsService(db, principal).test_channel(body, request), message="Test message sent")
