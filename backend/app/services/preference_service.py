"""Notification preferences, in-app notifications and push devices — Prompts/04 §04.6 ``preference_service`` /
``device_service`` (all self-only).

Business rules
1. ``get`` lists every catalogue category with the user's stored choice or the default (every channel the category's
   events use); mandatory categories (security, emergency) are shown but cannot be switched off (422 on update).
2. ``update`` upserts per category: channels ⊆ in_app/sms/whatsapp/email/push (``in_app`` is always kept), quiet
   hours ``{from, to}`` in the institution's local time, digest none/daily/weekly.
3. ``unsubscribe`` (public, signed token ``user:category`` HMAC) removes the e-mail and SMS channels of a category.
4. Notifications: list/unread count/mark read (one or all) — the caller's rows only.
5. Devices (``comms.push``): register upserts on ``(provider, token)`` (a token moving to another user is re-bound);
   default topics ``role:<slug>`` for every role and ``college:<id>`` for college assignments; unregister deactivates.
"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.notifications.catalogue import CATEGORIES, EVENTS, MANDATORY_CATEGORIES
from app.models.communication import Notification
from app.models.platform import DeviceToken
from app.repositories.notification_repository import DeviceRepository, NotificationRepository, PreferenceRepository
from app.schemas.communication import (
    DeviceRegister,
    DeviceResponse,
    NotificationResponse,
    PreferenceItem,
    PreferenceResponse,
    QuietHours,
)
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

ALL_CHANNELS = ["in_app", "sms", "whatsapp", "email", "push"]


def default_channels(category: str) -> list[str]:
    chans: set[str] = {"in_app"}
    for ev in EVENTS:
        if ev.category == category:
            chans |= set(ev.channels)
    return [c for c in ALL_CHANNELS if c in chans]


def unsubscribe_token(user_id: uuid.UUID, category: str) -> str:
    sig = hmac.new(settings.SECRET_KEY.encode(), f"{user_id}:{category}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{user_id}.{category}.{sig}"


class PreferenceService:
    def __init__(self, db: AsyncSession, principal: Any):
        self.db, self.principal = db, principal
        self.prefs = PreferenceRepository(db)
        self.notifications = NotificationRepository(db, principal)

    # ---- rule 1 / 2 -----------------------------------------------------------------------------------------------
    async def get(self) -> PreferenceResponse:
        stored = {p.category: p for p in await self.prefs.for_user(self.principal.id)}
        items = []
        for cat in CATEGORIES:
            p = stored.get(cat)
            items.append(
                PreferenceItem(
                    category=cat,
                    channels=list(p.channels) if p else default_channels(cat),  # type: ignore[arg-type]
                    quiet_hours=QuietHours.model_validate(p.quiet_hours) if p and p.quiet_hours else None,
                    digest=(p.digest if p else "none"),  # type: ignore[arg-type]
                    mandatory=cat in MANDATORY_CATEGORIES,
                )
            )
        return PreferenceResponse(items=items, available_channels=ALL_CHANNELS)

    async def update(self, items: list[PreferenceItem]) -> PreferenceResponse:
        for item in items:
            if item.category not in CATEGORIES:
                raise APIError(422, ErrorCode.VALIDATION, f"Unknown category {item.category!r}", {"field": "category"})
            if item.category in MANDATORY_CATEGORIES and set(default_channels(item.category)) - set(item.channels):
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"{item.category} notifications cannot be switched off",
                    {"field": item.category},
                )
            channels: list[str] = sorted({"in_app", *item.channels}, key=ALL_CHANNELS.index)
            await self.prefs.upsert(
                self.principal.institution_id,
                self.principal.id,
                item.category,
                channels,
                item.quiet_hours.model_dump(by_alias=True) if item.quiet_hours else None,
                item.digest,
            )
        return await self.get()

    # ---- rule 4 ---------------------------------------------------------------------------------------------------
    async def notifications_page(
        self, params: PageParams, unread_only: bool, category: str | None
    ) -> tuple[list[NotificationResponse], PaginationMeta, VisibilityMeta]:
        rows, pagination = await self.notifications.mine(self.principal.id, params, unread_only, category)
        out = []
        for n in rows:
            r = NotificationResponse.model_validate(n)
            r.route = (n.link or {}).get("route")
            out.append(r)
        return out, pagination, VisibilityMeta(self=True, scopes=[], default="self")

    async def unread(self) -> int:
        return await self.notifications.unread_count(self.principal.id)

    async def mark_read(self, notification_id: uuid.UUID | None) -> int:
        n = await self.notifications.mark_read(self.principal.id, notification_id)
        if notification_id is not None and n == 0:
            exists = await self.db.get(Notification, notification_id)
            if exists is None or exists.user_id != self.principal.id:
                raise APIError(404, ErrorCode.NOT_FOUND, "Notification not found")
        return n

    # ---- rule 5 ---------------------------------------------------------------------------------------------------
    async def register_device(self, body: DeviceRegister) -> DeviceResponse:
        repo = DeviceRepository(self.db)
        topics = set(body.topics) | {f"role:{r}" for r in getattr(self.principal, "roles", [])}
        topics |= {f"college:{sid}" for st, sid in getattr(self.principal, "scopes", []) if st == "college" and sid}
        row = await repo.by_token(body.provider, body.token)
        now = datetime.now(UTC)
        if row is None:
            row = DeviceToken(
                institution_id=self.principal.institution_id,
                user_id=self.principal.id,
                provider=body.provider,
                platform=body.platform,
                token=body.token,
                topics=sorted(topics),
                is_active=True,
                last_seen_at=now,
            )
            self.db.add(row)
        else:
            row.user_id, row.institution_id = self.principal.id, self.principal.institution_id
            row.platform, row.topics, row.is_active, row.last_seen_at = body.platform, sorted(topics), True, now
        await self.db.flush()
        return DeviceResponse.model_validate(row)

    async def unregister_device(self, provider: str, token: str) -> None:
        row = await DeviceRepository(self.db).by_token(provider, token)
        if row is None or row.user_id != self.principal.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Device not registered")
        row.is_active = False
        await self.db.flush()


# ---- rule 3 (public) --------------------------------------------------------------------------------------------------
async def unsubscribe(db: AsyncSession, token: str) -> dict[str, str]:
    try:
        user_part, category, sig = token.split(".", 2)
        user_id = uuid.UUID(user_part)
    except ValueError:
        raise APIError(422, ErrorCode.VALIDATION, "Malformed unsubscribe token") from None
    if not hmac.compare_digest(unsubscribe_token(user_id, category), token) or category in MANDATORY_CATEGORIES:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid unsubscribe link")
    repo = PreferenceRepository(db)
    current = next((p for p in await repo.for_user(user_id) if p.category == category), None)
    channels = [c for c in (current.channels if current else default_channels(category)) if c not in ("email", "sms")]
    from sqlalchemy import text

    inst = (
        await db.execute(text("SELECT institution_id FROM users WHERE id = :u"), {"u": user_id})
    ).scalar_one_or_none()
    await repo.upsert(
        inst,
        user_id,
        category,
        channels or ["in_app"],
        current.quiet_hours if current else None,
        current.digest if current else "none",
    )
    _ = sig
    return {"category": category, "channels": ",".join(channels or ["in_app"])}
