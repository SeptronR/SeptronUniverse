"""Web push adapter (``push`` / ``webpush``) — Prompts/39 §39.6 ``pwa_service`` (VAPID, RFC 8030).

``to`` is the stored subscription JSON (``{"endpoint", "keys": {"p256dh", "auth"}}``); the body is the portal
payload ``{title, body, route, category, tag}`` (JSON) with ``TTL`` / ``Urgency`` / ``Topic`` (collapse key)
headers. Without ``pywebpush`` or VAPID keys (development) the call is logged like the mock adapter. A 404 / 410
from the push service raises :class:`PushGone` so delivery deactivates the subscription (pruning).
"""

import json
from typing import Any

import structlog

from app.core.config import settings
from app.integrations.registry import register_adapter

log = structlog.get_logger()
SENT: list[dict[str, Any]] = []  # development / verification log of mock deliveries (bounded)


class PushGone(Exception):
    """The push service no longer knows the subscription (HTTP 404 / 410)."""


class WebPushAdapter:
    capability = "push"
    provider = "webpush"

    def __init__(self, **config: Any):
        self.config = config

    async def health(self) -> tuple[bool, str]:
        return bool(settings.VAPID_PRIVATE_KEY), "vapid configured" if settings.VAPID_PRIVATE_KEY else "no vapid key"

    async def send(self, *, to: str, body: str, subject: str | None = None, **extra: Any) -> dict[str, Any]:
        sub = json.loads(to)
        payload = extra.get("payload") or {
            "title": subject or "SeptronUniverse",
            "body": body[:400],
            "route": extra.get("route") or "/",
            "category": extra.get("category") or "system",
            "tag": extra.get("tag") or extra.get("category") or "general",
        }
        if str(sub.get("endpoint", "")).startswith("https://mock.push/gone"):
            raise PushGone("410 Gone (development endpoint)")
        try:
            from pywebpush import WebPushException, webpush  # type: ignore[import-not-found]
        except ImportError:
            webpush = None
        if webpush is None or not settings.VAPID_PRIVATE_KEY or "mock.push" in str(sub.get("endpoint")):
            SENT.append({"endpoint": sub.get("endpoint"), "payload": payload})
            del SENT[:-200]
            log.info("webpush_mock_send", endpoint=str(sub.get("endpoint"))[:80], payload=payload)
            return {"reference": "mock-webpush", "payload": payload}
        try:
            resp = webpush(
                subscription_info=sub,
                data=json.dumps(payload),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=int(extra.get("ttl") or 86400),
                headers={"Urgency": str(extra.get("urgency") or "normal"), "Topic": str(payload["tag"])[:32]},
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                raise PushGone(str(exc)) from exc
            raise
        return {"reference": str(getattr(resp, "status_code", "sent"))}


@register_adapter("push", "webpush")
def _factory(**config: Any) -> WebPushAdapter:
    return WebPushAdapter(**config)
