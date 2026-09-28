"""In-app notifications, preferences and push devices — Prompts/04 §04.8 (router: ``core.notifications_inapp``).

Every route is self-only (``authenticated``); preferences add ``{comms.preferences}``, devices ``{comms.push}``.
``GET /notification-preferences/unsubscribe?token=`` is public (``PUBLIC_ROUTES``; signed token).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, authenticated
from app.core.features import feature_required
from app.db.session import get_db, get_platform_db
from app.schemas.common import Envelope
from app.schemas.communication import (
    DeviceRegister,
    DeviceResponse,
    NotificationResponse,
    PreferenceResponse,
    PreferenceUpdate,
    UnreadCount,
)
from app.services.preference_service import PreferenceService, unsubscribe
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["notifications"])


@router.get("/notifications", summary="My notifications", response_model=Envelope[list[NotificationResponse]])
async def my_notifications(
    params: PageParams = Depends(page_params),
    unread: bool = False,
    category: str | None = Query(default=None, max_length=40),
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await PreferenceService(db, principal).notifications_page(params, unread, category)
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get("/notifications/unread-count", summary="Unread notifications", response_model=Envelope[UnreadCount])
async def unread_count(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(UnreadCount(unread=await PreferenceService(db, principal).unread()))


@router.post("/notifications/read-all", summary="Mark every notification read", response_model=Envelope[UnreadCount])
async def read_all(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await PreferenceService(db, principal).mark_read(None)
    return ok(UnreadCount(unread=0))


@router.post("/notifications/{id}/read", summary="Mark a notification read", response_model=Envelope[UnreadCount])
async def read_one(
    id: uuid.UUID, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    service = PreferenceService(db, principal)
    await service.mark_read(id)
    return ok(UnreadCount(unread=await service.unread()))


@router.get(
    "/notification-preferences/me",
    summary="My notification preferences",
    dependencies=[feature_required("comms.preferences")],
    response_model=Envelope[PreferenceResponse],
)
async def my_preferences(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PreferenceService(db, principal).get())


@router.put(
    "/notification-preferences/me",
    summary="Update my notification preferences",
    dependencies=[feature_required("comms.preferences")],
    response_model=Envelope[PreferenceResponse],
)
async def update_preferences(
    body: PreferenceUpdate, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PreferenceService(db, principal).update(body.items), message="Preferences saved")


@router.get(
    "/notification-preferences/unsubscribe",
    summary="One-click unsubscribe (signed link)",
    response_model=Envelope[dict[str, str]],
)
async def unsubscribe_link(
    token: str = Query(max_length=200), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await unsubscribe(db, token), message="You are unsubscribed")


@router.post(
    "/devices",
    status_code=201,
    summary="Register a push token",
    dependencies=[feature_required("comms.push")],
    response_model=Envelope[DeviceResponse],
)
async def register_device(
    body: DeviceRegister, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PreferenceService(db, principal).register_device(body), message="Device registered")


@router.delete(
    "/devices",
    summary="Unregister a push token",
    dependencies=[feature_required("comms.push")],
    response_model=Envelope[None],
)
async def unregister_device(
    provider: str = Query(pattern="^(fcm|webpush|expo)$"),
    token: str = Query(max_length=4096),
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await PreferenceService(db, principal).unregister_device(provider, token)
    return ok(None, message="Device unregistered")


@router.post(
    "/webhooks/{provider}/{channel}",
    summary="Provider delivery / bounce / read callback (signed)",
    response_model=Envelope[dict[str, str]],
)
async def provider_webhook(
    provider: str, channel: str, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    from app.schemas.communication import WebhookCallback
    from app.services.communication_service import apply_webhook

    raw = await request.body()
    body = WebhookCallback.model_validate_json(raw)
    return ok(await apply_webhook(db, provider[:30], channel[:20], raw, request.headers.get("X-Signature"), body))
