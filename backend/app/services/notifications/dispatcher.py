"""Dispatcher — consumer of ``notification.requested`` (Prompts/04 §04.6 ``dispatcher.py``).

For every recipient:
1. template: the explicit ``template_id`` or ``TemplateRepository.resolve`` (institution → platform; language = user
   locale → institution locale → en); without any template a minimal ``{{ title }}`` fallback is used so a module
   never loses a notification because a template is missing;
2. channels: the request's channels or the template's, minus channels whose feature is off (``comms.sms`` …),
   minus the channels the user switched off for the event's **category** (``notification_preferences``; mandatory
   categories — security, emergency — ignore opt-outs);
3. quiet hours (the user's window, institution-local time) or a daily/weekly digest → the external message is logged
   ``deferred`` (in-app is always immediate) and sent by ``notifications.retry_failed`` / ``notifications.digest``;
4. render subject/body (sandboxed Jinja2, context + ``name``); ``in_app`` → ``notifications`` row + ``message_logs``
   (``sent``) + WebSocket ``notifications:{user}``; ``push`` → one log per active device token; other channels → a
   ``queued`` log and a ``notifications.deliver`` task sent **after commit** (the full body is parked in Redis
   ``msgbody:{log}`` for 3 days — ``message_logs`` keeps a 255-character preview).
"""

import json
import uuid
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.features import is_enabled
from app.core.jobs import send_after_commit
from app.core.notifications.catalogue import BY_KEY, MANDATORY_CATEGORIES, category_of
from app.core.notifications.templating import render
from app.db.session import redis_client
from app.models.communication import Notification, NotificationTemplate
from app.repositories.message_log_repository import MessageLogRepository
from app.repositories.notification_repository import DeviceRepository, PreferenceRepository
from app.repositories.template_repository import TemplateRepository
from app.services.notifications.recipients import Recipient, resolve_recipients

log = structlog.get_logger()

CHANNEL_FEATURE = {"sms": "comms.sms", "whatsapp": "comms.whatsapp", "email": "comms.email", "push": "comms.push"}
BODY_TTL = 3 * 86400


def body_key(log_id: uuid.UUID | str) -> str:
    return f"msgbody:{log_id}"


async def _snoozed(user_id: uuid.UUID, category: str) -> bool:
    """Phase 39 notification-centre snooze (``snooze:{user}:{category}``): external channels are deferred."""
    try:
        return bool(await redis_client.exists(f"snooze:{user_id}:{category}"))
    except Exception:  # noqa: BLE001 - a Redis hiccup never loses a notification
        return False


def in_quiet_hours(quiet: dict[str, str] | None, tz: str) -> bool:
    if not quiet or not quiet.get("from") or not quiet.get("to"):
        return False
    try:
        now = datetime.now(ZoneInfo(tz)).time()
        start = time.fromisoformat(quiet["from"])
        end = time.fromisoformat(quiet["to"])
    except (ValueError, KeyError):
        return False
    return (start <= now < end) if start < end else (now >= start or now < end)


class Dispatcher:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.templates = TemplateRepository(db)
        self.logs = MessageLogRepository(db)

    async def dispatch(self, event: dict[str, Any]) -> dict[str, int]:
        payload = event.get("payload") or {}
        raw_inst = event.get("institution_id")
        inst = uuid.UUID(str(raw_inst)) if raw_inst else None
        event_type = str(payload.get("event_type") or "notification")
        context: dict[str, Any] = dict(payload.get("context") or {})
        category = category_of(event_type)
        mandatory = category in MANDATORY_CATEGORIES
        inst_row = (
            (
                await self.db.execute(
                    text("SELECT locale, timezone, regulatory_pack FROM institutions WHERE id = :i"), {"i": inst}
                )
            ).first()
            if inst
            else None
        )
        inst_locale = (inst_row.locale if inst_row else None) or "en"
        tz = (inst_row.timezone if inst_row else None) or "Asia/Kolkata"
        explicit: NotificationTemplate | None = None
        if payload.get("template_id") and inst is not None:
            explicit = await self.templates.get(uuid.UUID(payload["template_id"]), inst)
        recipients = await resolve_recipients(self.db, inst, payload.get("audience") or {})
        prefs = await PreferenceRepository(self.db).for_users([r.user_id for r in recipients if r.user_id], category)
        devices = await DeviceRepository(self.db).active_for([r.user_id for r in recipients if r.user_id])
        by_user: dict[uuid.UUID, list[Any]] = {}
        for d in devices:
            by_user.setdefault(d.user_id, []).append(d)
        enabled = {ch: (inst is None or await is_enabled(inst, key)) for ch, key in CHANNEL_FEATURE.items()}
        counts = {"recipients": len(recipients), "in_app": 0, "queued": 0, "deferred": 0, "suppressed": 0}
        template_cache: dict[str, NotificationTemplate | None] = {}
        for r in recipients:
            lang = (r.locale or inst_locale or "en").split("-")[0]
            tmpl: NotificationTemplate | None
            if explicit is not None:
                tmpl = explicit
            else:
                if lang not in template_cache:
                    template_cache[lang] = await self.templates.resolve(inst, event_type, lang)
                tmpl = template_cache[lang]
            wanted = list(payload.get("channels") or (tmpl.channels if tmpl else ["in_app"]))
            if r.direct:
                wanted = [r.direct["channel"]]
            pref = prefs.get(r.user_id) if r.user_id else None
            ctx = {**context, "name": context.get("name") or r.name or ""}
            subject, body = self._render(tmpl, event_type, ctx)
            for channel in dict.fromkeys(wanted):
                if channel != "in_app" and not enabled.get(channel, False):
                    continue
                if pref is not None and not mandatory and channel not in (pref.channels or []):
                    counts["suppressed"] += 1
                    continue
                if channel == "in_app":
                    if r.user_id is not None:
                        await self._in_app(
                            inst, r, event_type, category, subject, body, ctx, tmpl, event.get("event_id")
                        )
                        counts["in_app"] += 1
                    continue
                deferred = not mandatory and (
                    (pref is not None and (in_quiet_hours(pref.quiet_hours, tz) or (pref.digest or "none") != "none"))
                    or (r.user_id is not None and await _snoozed(r.user_id, category))
                )
                targets = self._targets(channel, r, by_user.get(r.user_id, []) if r.user_id else [])
                for to in targets:
                    row = await self.logs.add(
                        institution_id=inst,
                        user_id=r.user_id,
                        recipient=to[:200],
                        channel=channel,
                        event_type=event_type,
                        template_id=tmpl.id if tmpl else None,
                        subject=(subject or None) and subject[:255],
                        body_preview=body[:255],
                        status="deferred" if deferred else "queued",
                        event_id=event.get("event_id"),
                    )
                    parked: dict[str, Any] = {"subject": subject, "body": body}
                    if channel == "push":  # Phase 39 web-push payload {title, body, route, category, tag}
                        parked["to"] = to.split(":", 1)[1] if ":" in to else to
                        ev_def = BY_KEY.get(event_type)
                        route = render(ev_def.link, ctx) if ev_def and ev_def.link else ctx.get("route")
                        parked["push"] = {
                            "payload": {
                                "title": subject,
                                "body": body[:400],
                                "route": route or "/",
                                "category": category,
                                "tag": f"{category}:{ctx.get('id') or event_type}"[:64],
                            },
                            "urgency": "high" if payload.get("priority") in ("high", "urgent") else "normal",
                        }
                    await redis_client.set(body_key(row.id), json.dumps(parked, default=str), ex=BODY_TTL)
                    if deferred:
                        counts["deferred"] += 1
                    else:
                        send_after_commit(
                            self.db,
                            "notifications.deliver",
                            [str(row.id)],
                            "emails" if channel == "email" else "notifications",
                            str(uuid.uuid4()),
                        )
                        counts["queued"] += 1
        log.info("notification_dispatched", event_type=event_type, **counts)
        return counts

    @staticmethod
    def _targets(channel: str, r: Recipient, devices: list[Any]) -> list[str]:
        if r.direct:
            return [r.direct["to"]]
        if channel == "email":
            return [r.email] if r.email else []
        if channel in ("sms", "whatsapp"):
            return [r.phone] if r.phone else []
        if channel == "push":
            return [f"{d.provider}:{d.token}" for d in devices]
        return []

    @staticmethod
    def _render(tmpl: NotificationTemplate | None, event_type: str, ctx: dict[str, Any]) -> tuple[str, str]:
        if tmpl is None:
            ev = BY_KEY.get(event_type)
            title = str(ctx.get("title") or (ev.name if ev else event_type.replace(".", " ").title()))
            return title, str(ctx.get("body") or ctx.get("message") or ctx.get("summary") or title)
        try:
            subject = render(tmpl.subject_template, ctx) or tmpl.name
            body = render(tmpl.body_template, ctx)
        except Exception as exc:  # noqa: BLE001 - a broken template must not lose the notification
            log.warning("template_render_failed", template_id=str(tmpl.id), error=str(exc)[:200])
            subject, body = tmpl.name, str(ctx.get("title") or tmpl.name)
        return subject, body

    async def _in_app(
        self,
        inst: uuid.UUID | None,
        r: Recipient,
        event_type: str,
        category: str,
        subject: str,
        body: str,
        ctx: dict[str, Any],
        tmpl: NotificationTemplate | None,
        event_id: Any = None,
    ) -> None:
        from app.core.ws import publish

        ev = BY_KEY.get(event_type)
        route = render(ev.link, ctx) if ev and ev.link else ctx.get("route")
        link = {"route": route, **{k: str(v) for k, v in ctx.items() if k.endswith("_id")}} if (route or ctx) else None
        n = Notification(
            institution_id=inst,
            user_id=r.user_id,
            title=subject[:200],
            body=body,
            category=category,
            event_type=event_type,
            link=link,
        )
        self.db.add(n)
        await self.db.flush()
        await self.logs.add(
            institution_id=inst,
            user_id=r.user_id,
            recipient=str(r.user_id),
            channel="in_app",
            event_type=event_type,
            template_id=tmpl.id if tmpl else None,
            subject=subject[:255],
            body_preview=body[:255],
            provider="in_app",
            status="sent",
            sent_at=datetime.now(UTC),
            event_id=event_id,  # the in-app row belongs to the same notification.requested event as the others
        )
        await redis_client.delete(f"ncount:{r.user_id}")  # Phase 39 unread-by-category cache
        await publish(
            f"notifications:{r.user_id}",
            {
                "id": str(n.id),
                "title": n.title,
                "body": n.body,
                "category": category,
                "event_type": event_type,
                "route": route,
                "created_at": datetime.now(UTC).isoformat(),
                "read_at": None,
            },
        )
