"""Settings — Prompts/03 §03.8 (router included with ``feature_required("core.settings")``).

``GET /settings`` (``settings:view``) returns the typed template merged with the institution's values (one entry per
category, or the ``category`` asked for); ``PUT /settings`` (``settings:manage``) bulk-updates with type validation;
``GET /settings/public`` is unauthenticated (``PUBLIC_ROUTES``) and exposes only ``is_public`` keys + the resolved
theme of the tenant named by ``?institution=<slug>`` / ``X-Institution-Slug`` / ``X-Institution-Id``;
``POST /settings/test-provider`` sends a test SMS / e-mail / WhatsApp / push through the adapter registry (202).
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.db.session import bind_tenant, get_db, set_tenant
from app.repositories.institution_repository import InstitutionRepository
from app.schemas.audit import AuditRowOut, FeatureChangeLogOut
from app.schemas.common import Envelope
from app.schemas.settings import (
    EffectiveSettingOut,
    ProviderTestRequest,
    ProviderTestResponse,
    PublicSettingsResponse,
    SettingDefOut,
    SettingsBulkUpdate,
    SettingsCategoryResponse,
    SettingsDiffOut,
    SettingsExportOut,
    SettingsHistoryOut,
    SettingsImportIn,
    SettingsImportReport,
)
from app.services.audit.feature_change_service import FeatureChangeService
from app.services.audit.settings_admin_service import SettingsAdminService
from app.services.settings_service import SettingsService
from app.utils.response import ok

router = APIRouter(tags=["settings"])

VIEW = any_permission_required(("settings", "view"), ("settings", "manage"))
MANAGE = permission_required("settings", "manage")
FEATURE_LOG = any_permission_required(("features", "view"), ("audit_logs", "view_all"), ("audit_logs", "manage"))
PLATFORM_LOG = any_permission_required(("audit_logs", "view_all"), ("audit_logs", "manage"))


# ---- Phase 37: catalogue / effective / history / import-export / reset / overrides (before /settings/{key}) --------
@router.get(
    "/settings/catalogue",
    summary="Settings catalogue (metadata of every key)",
    response_model=Envelope[list[SettingDefOut]],
)
async def catalogue(
    request: Request,
    category: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=80),
    scope: str | None = Query(None, pattern="^(platform|institution|college)$"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SettingsAdminService(db, principal, request).catalogue(category, q, scope))


@router.get(
    "/settings/effective",
    summary="Effective values with source badges",
    response_model=Envelope[list[EffectiveSettingOut]],
)
async def effective(
    request: Request,
    college_id: uuid.UUID | None = None,
    category: str | None = Query(None, max_length=40),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SettingsAdminService(db, principal, request).effective(college_id, category))


@router.get(
    "/settings/history",
    summary="Change history per key (from audit_logs)",
    response_model=Envelope[list[SettingsHistoryOut]],
)
async def history(
    request: Request,
    key: str | None = Query(None, max_length=120),
    category: str | None = Query(None, max_length=40),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SettingsAdminService(db, principal, request).history(key, category, date_from, date_to))


@router.get(
    "/settings/changes-since", summary="What changed since a date", response_model=Envelope[list[SettingsDiffOut]]
)
async def changes_since(
    request: Request,
    since: datetime = Query(),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SettingsAdminService(db, principal, request).changes_since(since))


@router.get("/settings/export", summary="Export settings (JSON)", response_model=Envelope[SettingsExportOut])
async def export_settings(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SettingsAdminService(db, principal, request).export())


@router.post(
    "/settings/import", summary="Import settings (dry run first)", response_model=Envelope[SettingsImportReport]
)
async def import_settings(
    body: SettingsImportIn,
    request: Request,
    dry_run: bool = True,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await SettingsAdminService(db, principal, request).import_(body.json_, dry_run, body.reason)
    return ok(out, message="Dry run" if dry_run else "Settings imported")


@router.get(
    "/settings/feature-changes",
    summary="Feature flag change log of the tenant",
    response_model=Envelope[list[FeatureChangeLogOut]],
)
async def feature_changes(
    request: Request,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(FEATURE_LOG),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FeatureChangeService(db, principal, request).feature_changes(date_from, date_to))


@router.get(
    "/settings/platform-actions",
    summary="Platform (super admin) actions affecting the tenant",
    response_model=Envelope[list[AuditRowOut]],
)
async def platform_actions(
    request: Request,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(PLATFORM_LOG),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FeatureChangeService(db, principal, request).platform_actions(date_from, date_to))


@router.post(
    "/settings/{key}/reset", summary="Reset a key to its default", response_model=Envelope[list[EffectiveSettingOut]]
)
async def reset_setting(
    key: str,
    request: Request,
    reason: str | None = Query(None, max_length=500),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SettingsAdminService(db, principal, request).reset(key, reason), message="Reset to default")


@router.delete(
    "/settings/{key}/override", summary="Clear a college override", response_model=Envelope[list[EffectiveSettingOut]]
)
async def clear_override(
    key: str,
    request: Request,
    college_id: uuid.UUID = Query(),
    reason: str | None = Query(None, max_length=500),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await SettingsAdminService(db, principal, request).clear_override(key, college_id, reason),
        message="Override cleared",
    )


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
    out = await SettingsService(db, principal).bulk_update(body.items, request, reason=body.reason, strict=True)
    return ok(out, message="Settings saved")


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
