"""PWA & web push — Prompts/39 §39.6 ``pwa_service`` (``portals.pwa_push``).

Business rules
1. Manifest per institution (``?institution=<slug>`` or the host / ``X-Institution-*`` tenant): name / short name /
   icons (192, 512, maskable — generated from the logo by ``pwa.icons_generate``; the SVG fallback while none) /
   theme & background colour / ``start_url=/login?source=pwa`` / ``display=standalone`` / ``scope=/``. Served even
   while ``portals.pwa_push`` is off (installability); unknown institution → the platform manifest.
2. ``pwa-config``: cache TTLs (``pwa.cache_ttl``), the SWR route map, the precache list versioned by
   ``BUILD_HASH``, the offline route and the background-sync queues (mark-read / acknowledge / feedback).
3. VAPID public key: ``platform_settings['push.vapid'].public_key`` over ``VAPID_PUBLIC_KEY``.
4. Subscribe: one ``device_tokens`` row per endpoint (``provider='webpush'``, ``token`` = subscription JSON; dedupe by
   ``token::jsonb->>'endpoint'``; a subscription moving to another user is re-bound); topics = requested ∪
   ``role:<slug>`` ∪ ``college:<id>`` ∪ ``persona:<p>`` — identical to the FCM topics (Phase 42). Unsubscribe
   deactivates. ``portal.push_subscribed|unsubscribed`` emitted; the first subscription notifies ``portal.push_enabled``.
5. Test push: one ``message_logs`` row per active subscription delivered through the Phase 04 queue
   (``notifications.deliver`` → ``webpush`` adapter) with the payload ``{title, body, route, category, tag}``.
6. Prune (Beat daily): subscriptions whose last delivery failed with ``PUSH_GONE`` or unseen for 90 days → inactive.
7. Association files from ``platform_settings['mobile.app_ids']`` (``assetlinks.json``,
   ``apple-app-site-association``).
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.jobs import send_after_commit
from app.core.notifications.notify import notify_event
from app.db.session import redis_client
from app.enums.portals import DEFAULT_APP_IDS, DEFAULT_CACHE_TTL, SWR_ROUTES
from app.repositories.message_log_repository import MessageLogRepository
from app.schemas.portals import PushSubscribeIn, PushSubscribeOut, PushTestOut, PushTestRequest, PwaConfigOut
from app.services.notifications.dispatcher import BODY_TTL, body_key
from app.services.portals.common import PortalBase, persona_of
from app.services.portals.portal_service import branding_for

PRECACHE = ["/", "/index.html", "/offline", "/manifest.webmanifest", "/icons/icon.svg", "/locales/en.json"]
SYNC_QUEUES = ["notifications-mark-read", "announcements-ack", "feedback"]


async def _platform_value(db: AsyncSession, key: str) -> Any:
    row = (await db.execute(text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key})).first()
    return row[0] if row else None


async def resolve_institution(db: AsyncSession, slug: str | None, fallback: Any) -> uuid.UUID | None:
    if slug:
        row = (
            await db.execute(
                text("SELECT id FROM institutions WHERE slug = :s AND deleted_at IS NULL"), {"s": slug[:60]}
            )
        ).first()
        return row[0] if row else None
    return uuid.UUID(str(fallback)) if fallback else None


# ---- rule 1 ---------------------------------------------------------------------------------------------------------
async def manifest(db: AsyncSession, institution_id: uuid.UUID | None) -> dict[str, Any]:
    if institution_id is None:
        name, short, theme, bg, icons = (
            "SeptronUniverse",
            "Universe",
            "#4f46e5",
            "#f8fafc",
            [{"src": "/icons/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
        )
    else:
        b = await branding_for(db, institution_id)
        generated = await redis_client.exists(f"pwa_icons:{institution_id}")
        icons = b.icons if generated else [{"src": "/icons/icon.svg", "sizes": "any", "type": "image/svg+xml"}]
        name, short, theme, bg = b.app_name, b.short_name, b.theme_color, b.background_color
    return {
        "id": f"/?institution={institution_id}" if institution_id else "/",
        "name": name,
        "short_name": short,
        "description": f"{name} — student, parent and staff portals",
        "start_url": "/login?source=pwa",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "theme_color": theme,
        "background_color": bg,
        "icons": icons,
        "categories": ["education"],
    }


# ---- rule 2 / 3 -----------------------------------------------------------------------------------------------------
async def pwa_config(db: AsyncSession, institution_id: uuid.UUID | None, push_enabled: bool) -> PwaConfigOut:
    ttl: dict[str, int] = dict(DEFAULT_CACHE_TTL)
    if institution_id is not None:
        row = (
            await db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND category = 'pwa' "
                    "AND key = 'cache_ttl' AND college_id IS NULL LIMIT 1"
                ),
                {"i": institution_id},
            )
        ).first()
        if row and isinstance(row[0], dict):
            ttl.update({k: int(v) for k, v in row[0].items() if isinstance(v, int | float)})
    return PwaConfigOut(
        version=settings.BUILD_HASH,
        cache_ttl=ttl,
        swr_routes=SWR_ROUTES,
        precache=PRECACHE,
        background_sync=SYNC_QUEUES,
        push_enabled=push_enabled,
    )


async def vapid_public_key(db: AsyncSession) -> tuple[str, bool]:
    stored = await _platform_value(db, "push.vapid")
    key = (stored or {}).get("public_key") if isinstance(stored, dict) else None
    key = key or settings.VAPID_PUBLIC_KEY
    return key or "", bool(key)


# ---- rule 7 ---------------------------------------------------------------------------------------------------------
async def association_files(db: AsyncSession) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ids = {**DEFAULT_APP_IDS, **((await _platform_value(db, "mobile.app_ids")) or {})}
    assetlinks = [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": ids["android_package"],
                "sha256_cert_fingerprints": list(ids.get("android_sha256") or []),  # type: ignore[call-overload]
            },
        }
    ]
    app_id = f"{ids.get('ios_team_id') or 'TEAMID'}.{ids['ios_bundle_id']}"
    aasa = {
        "applinks": {"apps": [], "details": [{"appIDs": [app_id], "paths": list(ids.get("paths") or [])}]},  # type: ignore[call-overload]
        "webcredentials": {"apps": [app_id]},
    }
    return assetlinks, aasa


class PushService(PortalBase):
    # ---- rule 4 -------------------------------------------------------------------------------------------------
    def _topics(self, requested: list[str]) -> list[str]:
        topics = {t[:80] for t in requested}
        topics |= {f"role:{r}" for r in self.principal.roles}
        topics |= {f"college:{sid}" for st, sid in self.principal.scopes if st == "college" and sid}
        persona = persona_of(self.principal)
        if persona:
            topics.add(f"persona:{persona}")
        return sorted(topics)

    async def subscribe(self, body: PushSubscribeIn) -> PushSubscribeOut:
        token = json.dumps({"endpoint": body.endpoint, "keys": body.keys.model_dump()}, sort_keys=True)
        topics = self._topics(body.topics)
        existing = await self.rows(
            "SELECT id, user_id, is_active FROM device_tokens WHERE provider = 'webpush' "
            "AND CAST(token AS jsonb)->>'endpoint' = :ep LIMIT 1",
            ep=body.endpoint,
        )
        created = not existing
        had_any = await self.rows(
            "SELECT 1 FROM device_tokens WHERE user_id = :u AND provider = 'webpush' AND is_active LIMIT 1",
            u=self.principal.id,
        )
        if existing:
            did = existing[0]["id"]
            await self.db.execute(
                text(
                    "UPDATE device_tokens SET user_id = :u, institution_id = :i, token = :t, topics = CAST(:tp AS jsonb), "
                    "platform = :p, is_active = TRUE, last_seen_at = NOW(), updated_at = NOW() WHERE id = :id"
                ),
                {
                    "u": self.principal.id,
                    "i": self.inst,
                    "t": token,
                    "tp": json.dumps(topics),
                    "p": body.platform,
                    "id": did,
                },
            )
        else:
            did = uuid.uuid4()
            await self.db.execute(
                text(
                    "INSERT INTO device_tokens (id, institution_id, user_id, provider, platform, token, topics, is_active, "
                    "last_seen_at, created_at, updated_at) VALUES (:id, :i, :u, 'webpush', :p, :t, CAST(:tp AS jsonb), "
                    "TRUE, NOW(), NOW(), NOW())"
                ),
                {
                    "id": did,
                    "i": self.inst,
                    "u": self.principal.id,
                    "p": body.platform,
                    "t": token,
                    "tp": json.dumps(topics),
                },
            )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="portal.push_subscribed",
            payload={"user_id": str(self.principal.id), "device_id": str(did), "topics": topics, "created": created},
            aggregate_type="device_token",
            aggregate_id=did,
            actor_user_id=self.principal.id,
        )
        if not had_any:
            await notify_event(
                self.db,
                self.inst,
                "portal.push_enabled",
                audience={"user_ids": [str(self.principal.id)]},
                context={"route": "/"},
                channels=["in_app"],
            )
        return PushSubscribeOut(id=did, endpoint=body.endpoint, topics=topics, is_active=True, created=created)

    async def unsubscribe(self, endpoint: str) -> None:
        res = await self.db.execute(
            text(
                "UPDATE device_tokens SET is_active = FALSE, updated_at = NOW() WHERE provider = 'webpush' "
                "AND user_id = :u AND CAST(token AS jsonb)->>'endpoint' = :ep"
            ),
            {"u": self.principal.id, "ep": endpoint},
        )
        if not getattr(res, "rowcount", 0):
            raise APIError(404, ErrorCode.NOT_FOUND, "Subscription not found")
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="portal.push_unsubscribed",
            payload={"user_id": str(self.principal.id)},
            aggregate_type="user",
            aggregate_id=self.principal.id,
            actor_user_id=self.principal.id,
        )

    # ---- rule 5 -------------------------------------------------------------------------------------------------
    async def test(self, body: PushTestRequest) -> PushTestOut:
        subs = await self.rows(
            "SELECT token FROM device_tokens WHERE user_id = :u AND provider = 'webpush' AND is_active",
            u=self.principal.id,
        )
        if not subs:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Enable push notifications on this device first")
        payload = {
            "title": body.title,
            "body": body.body,
            "route": body.route or "/",
            "category": "system",
            "tag": "system:test",
        }
        repo = MessageLogRepository(self.db)
        ids: list[uuid.UUID] = []
        for s in subs:
            row = await repo.add(
                institution_id=self.inst,
                user_id=self.principal.id,
                recipient=f"webpush:{s['token']}"[:200],
                channel="push",
                event_type="portal.push_test",
                subject=body.title,
                body_preview=body.body[:255],
                status="queued",
            )
            # the recipient column is 200 chars: the full subscription travels with the parked body
            await redis_client.set(
                body_key(row.id),
                json.dumps({"subject": body.title, "body": body.body, "push": {"payload": payload}, "to": s["token"]}),
                ex=BODY_TTL,
            )
            send_after_commit(self.db, "notifications.deliver", [str(row.id)], "notifications", str(uuid.uuid4()))
            ids.append(row.id)
        return PushTestOut(devices=len(subs), log_ids=ids, payload=payload)


# ---- rule 6 ---------------------------------------------------------------------------------------------------------
async def prune_expired(db: AsyncSession) -> int:
    res = await db.execute(
        text(
            "UPDATE device_tokens SET is_active = FALSE, updated_at = NOW() WHERE provider = 'webpush' AND is_active "
            "AND (last_seen_at < NOW() - INTERVAL '90 days' OR CAST(token AS jsonb)->>'endpoint' LIKE 'https://mock.push/gone%')"
        )
    )
    return int(getattr(res, "rowcount", 0) or 0)


async def mark_icons_generated(institution_id: uuid.UUID) -> None:
    await redis_client.set(f"pwa_icons:{institution_id}", datetime.now(UTC).isoformat())
