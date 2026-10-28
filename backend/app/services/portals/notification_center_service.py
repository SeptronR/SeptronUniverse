"""Notification centre — Prompts/39 §39.6 ``notification_center_service`` (extends Phase 04, self only).

Business rules
1. Counts: unread per category, cached in Redis ``ncount:{user}`` for 60 s and dropped on every mark-read /
   snooze / new in-app row (dispatcher); pending acknowledgements counted from the Phase 04 announcements.
2. ``GET /notifications/{id}`` marks the row read and returns its route; routes are validated (relative paths only).
3. Mark read: explicit ids, or ``all`` (optionally per category); emits ``notification.read`` / ``read_all``.
4. Snooze: ``snooze:{user}:{category}`` (TTL = hours) — the dispatcher stores the in-app row but defers push /
   e-mail / SMS / WhatsApp (``deferred``) until it lapses; ``hours=0`` clears it. Mandatory categories can't snooze.
5. Preferences matrix (categories × channels, quiet hours, digest): in-app is always on; the policy-locked
   categories (exams, fees, security, emergency) refuse an in-app opt-out with 422; quiet hours / digest are stored
   once in ``users.preferences['notifications']`` and written to every category row so the Phase 04 dispatcher
   honours them.
6. Digest (Beat ``notifications.digest_daily|weekly``): users whose digest matches get one e-mail + push summarising
   unread notifications by category (in addition to the Phase 04 bundling of deferred messages).
7. Test: ``notify_event('portal.test', …)`` to self on the chosen channels.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core import events
from app.core.errors import APIError, ErrorCode
from app.core.notifications.catalogue import CATEGORIES, MANDATORY_CATEGORIES
from app.core.notifications.notify import notify_event
from app.db.session import redis_client
from app.enums.portals import POLICY_LOCKED_IN_APP
from app.repositories.notification_repository import PreferenceRepository
from app.schemas.communication import QuietHours
from app.schemas.portals import (
    CategoryChannels,
    MarkReadIn,
    MarkReadOut,
    NotificationCounts,
    NotificationDetail,
    PreferencesIn,
    PreferencesOut,
    SnoozeIn,
)
from app.services.portals.common import PortalBase
from app.services.preference_service import ALL_CHANNELS, default_channels

COUNT_KEY = "ncount:{user}"
SNOOZE_KEY = "snooze:{user}:{category}"


async def drop_counts(user_id: Any) -> None:
    await redis_client.delete(COUNT_KEY.format(user=user_id))


async def is_snoozed(user_id: Any, category: str) -> bool:
    return bool(await redis_client.exists(SNOOZE_KEY.format(user=user_id, category=category)))


def safe_route(route: Any) -> str | None:
    if not isinstance(route, str) or not route.startswith("/") or route.startswith("//") or len(route) > 300:
        return None
    return route


class NotificationCenterService(PortalBase):
    # ---- rule 1 -------------------------------------------------------------------------------------------------
    async def counts(self) -> NotificationCounts:
        key = COUNT_KEY.format(user=self.principal.id)
        cached = await redis_client.get(key)
        if cached:
            by_cat: dict[str, int] = json.loads(cached)
        else:
            rows = await self.rows(
                "SELECT coalesce(category, 'system') AS c, count(*) AS n FROM notifications "
                "WHERE user_id = :u AND NOT is_read GROUP BY 1",
                u=self.principal.id,
            )
            by_cat = {r["c"]: int(r["n"]) for r in rows}
            await redis_client.set(key, json.dumps(by_cat), ex=60)
        snoozed: dict[str, datetime] = {}
        now = datetime.now(UTC)
        for cat in CATEGORIES:
            ttl = await redis_client.ttl(SNOOZE_KEY.format(user=self.principal.id, category=cat))
            if ttl and ttl > 0:
                snoozed[cat] = now + timedelta(seconds=int(ttl))
        pending = 0
        if self.principal.has_feature("comms.announcements"):
            from app.services.announcement_service import AnnouncementService

            pending = len(await AnnouncementService(self.db, self.principal, self.request).mine(True))
        return NotificationCounts(
            unread=sum(by_cat.values()), unread_by_category=by_cat, snoozed=snoozed, pending_ack=pending
        )

    # ---- rule 2 -------------------------------------------------------------------------------------------------
    async def open(self, notification_id: uuid.UUID) -> NotificationDetail:
        rows = await self.rows(
            "UPDATE notifications SET is_read = TRUE, read_at = coalesce(read_at, NOW()) WHERE id = :n AND user_id = :u "
            "RETURNING id, title, body, category, event_type, link, is_read, read_at, created_at",
            n=notification_id,
            u=self.principal.id,
        )
        if not rows:
            raise APIError(404, ErrorCode.NOT_FOUND, "Notification not found")
        r = rows[0]
        await drop_counts(self.principal.id)
        link = r["link"] or {}
        return NotificationDetail(
            id=r["id"],
            title=r["title"],
            body=r["body"],
            category=r["category"],
            event_type=r["event_type"],
            route=safe_route(link.get("route")),
            priority=str(link.get("priority") or "normal"),
            is_read=True,
            read_at=r["read_at"],
            created_at=r["created_at"],
        )

    # ---- rule 3 -------------------------------------------------------------------------------------------------
    async def mark_read(self, body: MarkReadIn) -> MarkReadOut:
        if not body.all and not body.ids:
            raise APIError(422, ErrorCode.VALIDATION, "Pass ids or all=true")
        sql = "UPDATE notifications SET is_read = TRUE, read_at = NOW() WHERE user_id = :u AND NOT is_read"
        params: dict[str, Any] = {"u": self.principal.id}
        if not body.all:
            sql += " AND id = ANY(:ids)"
            params["ids"] = body.ids
        if body.category:
            sql += " AND category = :c"
            params["c"] = body.category
        res = await self.db.execute(text(sql), params)
        marked = int(getattr(res, "rowcount", 0) or 0)
        await drop_counts(self.principal.id)
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="notification.read_all" if body.all else "notification.read",
            payload={"user_id": str(self.principal.id), "category": body.category, "count": marked},
            aggregate_type="user",
            aggregate_id=self.principal.id,
            actor_user_id=self.principal.id,
        )
        return MarkReadOut(marked=marked, unread=(await self.counts()).unread)

    # ---- rule 4 -------------------------------------------------------------------------------------------------
    async def snooze(self, body: SnoozeIn) -> NotificationCounts:
        if body.category not in CATEGORIES:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown category {body.category!r}", {"field": "category"})
        if body.category in MANDATORY_CATEGORIES:
            raise APIError(422, ErrorCode.VALIDATION, f"{body.category} notifications cannot be snoozed")
        key = SNOOZE_KEY.format(user=self.principal.id, category=body.category)
        if body.hours == 0:
            await redis_client.delete(key)
        else:
            await redis_client.set(key, "1", ex=body.hours * 3600)
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="notification.snoozed",
            payload={"user_id": str(self.principal.id), "category": body.category, "hours": body.hours},
            aggregate_type="user",
            aggregate_id=self.principal.id,
            actor_user_id=self.principal.id,
        )
        return await self.counts()

    # ---- rule 5 -------------------------------------------------------------------------------------------------
    def _general(self) -> dict[str, Any]:
        return dict((self.principal.user.preferences or {}).get("notifications") or {})

    async def preferences(self) -> PreferencesOut:
        stored = {p.category: p for p in await PreferenceRepository(self.db).for_user(self.principal.id)}
        general = self._general()
        default_digest = await self.setting("notifications", "digest_default") or "none"
        cats: list[CategoryChannels] = []
        for cat in CATEGORIES:
            p = stored.get(cat)
            locked = ["in_app"]
            if cat in MANDATORY_CATEGORIES:
                locked = list(default_channels(cat))
            cats.append(
                CategoryChannels(
                    category=cat,
                    channels=list(p.channels) if p else default_channels(cat),  # type: ignore[arg-type]
                    locked=locked,  # type: ignore[arg-type]
                    available=ALL_CHANNELS,  # type: ignore[arg-type]
                )
            )
        devices = await self.rows(
            "SELECT 1 FROM device_tokens WHERE user_id = :u AND provider = 'webpush' AND is_active LIMIT 1",
            u=self.principal.id,
        )
        qh = general.get("quiet_hours")
        return PreferencesOut(
            categories=cats,
            quiet_hours=QuietHours.model_validate(qh) if qh else None,
            digest=general.get("digest") or default_digest,
            push_subscribed=bool(devices),
            available_channels=ALL_CHANNELS,
        )

    async def update_preferences(self, body: PreferencesIn) -> PreferencesOut:
        general = self._general()
        if body.quiet_hours is not None:
            general["quiet_hours"] = body.quiet_hours.model_dump(by_alias=True)
        if body.clear_quiet_hours:
            general.pop("quiet_hours", None)
        if body.digest is not None:
            general["digest"] = body.digest
        repo = PreferenceRepository(self.db)
        stored = {p.category: p for p in await repo.for_user(self.principal.id)}
        incoming = {c.category: c for c in body.categories}
        for c in body.categories:
            if c.category not in CATEGORIES:
                raise APIError(422, ErrorCode.VALIDATION, f"Unknown category {c.category!r}", {"field": "category"})
            if "in_app" not in c.channels and c.category in POLICY_LOCKED_IN_APP:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"In-app {c.category} notifications are required by institution policy",
                    {"field": c.category, "channel": "in_app"},
                )
            if c.category in MANDATORY_CATEGORIES and set(default_channels(c.category)) - set(c.channels):
                raise APIError(422, ErrorCode.VALIDATION, f"{c.category} notifications cannot be switched off")
        touched = set(incoming) | (
            set(CATEGORIES) if body.quiet_hours or body.clear_quiet_hours or body.digest else set()
        )
        for cat in touched:
            channels: list[str]
            if cat in incoming:
                channels = sorted({"in_app", *[str(x) for x in incoming[cat].channels]}, key=ALL_CHANNELS.index)
            elif cat in stored:
                channels = list(stored[cat].channels)
            else:
                channels = default_channels(cat)
            await repo.upsert(
                self.inst, self.principal.id, cat, channels, general.get("quiet_hours"), general.get("digest") or "none"
            )
        prefs = dict(self.principal.user.preferences or {})
        prefs["notifications"] = general
        self.principal.user.preferences = prefs
        await self.db.execute(
            text("UPDATE users SET preferences = CAST(:p AS jsonb) WHERE id = :u"),
            {"p": json.dumps(prefs, default=str), "u": self.principal.id},
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="preferences.updated",
            payload={
                "user_id": str(self.principal.id),
                "categories": sorted(incoming),
                "digest": general.get("digest"),
            },
            aggregate_type="user",
            aggregate_id=self.principal.id,
            actor_user_id=self.principal.id,
        )
        return await self.preferences()

    # ---- rule 7 -------------------------------------------------------------------------------------------------
    async def test(self, category: str, channels: list[str]) -> dict[str, Any]:
        await notify_event(
            self.db,
            self.inst,
            "portal.test",
            audience={"user_ids": [str(self.principal.id)]},
            context={"title": "Test notification", "body": f"This is a test ({category}).", "route": "/"},
            channels=channels,
            actor_user_id=self.principal.id,
        )
        return {"queued": True, "channels": channels}


# ---- rule 6 (Beat) ----------------------------------------------------------------------------------------------------
async def send_unread_digests(db: Any, period: str) -> int:
    rows = (
        await db.execute(
            text(
                "SELECT u.id, u.institution_id, coalesce(n.category, 'system') AS c, count(*) AS cnt FROM users u "
                "JOIN notifications n ON n.user_id = u.id AND NOT n.is_read "
                "AND n.created_at > NOW() - (CASE WHEN :p = 'weekly' THEN INTERVAL '7 days' ELSE INTERVAL '1 day' END) "
                "WHERE u.preferences->'notifications'->>'digest' = :p AND u.is_active GROUP BY 1, 2, 3"
            ),
            {"p": period},
        )
    ).all()
    by_user: dict[tuple[Any, Any], dict[str, int]] = {}
    for uid, inst, cat, cnt in rows:
        by_user.setdefault((uid, inst), {})[cat] = int(cnt)
    for (uid, inst), cats in by_user.items():
        summary = ", ".join(f"{c}: {n}" for c, n in sorted(cats.items()))
        await notify_event(
            db,
            inst,
            "notifications.unread_digest",
            audience={"user_ids": [str(uid)]},
            context={"period": period, "summary": summary, "total": sum(cats.values()), "route": "/"},
            channels=["email", "push"],
        )
    return len(by_user)
