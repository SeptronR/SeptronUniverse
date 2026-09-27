"""Delivery — task ``notifications.deliver`` (Prompts/04 §04.6 ``delivery.py``).

1. Load the ``message_logs`` row (platform session — delivery is cross-tenant bookkeeping) and the parked body.
2. Provider: ``institution_settings[integrations.provider_overrides][channel]`` → platform default
   (``SMS_PROVIDER`` / ``EMAIL_PROVIDER`` / ``WHATSAPP_PROVIDER`` / ``PUSH_PROVIDER``) → ``mock``; the adapter comes
   from the registry (unknown providers resolve to the mock adapter until Phase 41 ships the live ones).
3. Compliance (IN pack): an SMS through a live provider must carry a registered ``dlt_templates.template_id``
   (``notification_templates.dlt_template_id``) → else ``failed`` / ``DLT_TEMPLATE_MISSING``; a WhatsApp message needs
   an ``approved`` ``whatsapp_templates`` row (``WA_TEMPLATE_NOT_APPROVED``) unless a customer-service session is open
   (an inbound ``conversation_sessions`` activity within 24 h).
4. Send, then ``sent`` + ``provider_message_id`` / or ``failed`` + error; ``notification.sent|failed`` events. Failed
   sends are retried by Beat ``notifications.retry_failed`` with backoff (1, 5, 30 min; three attempts kept in Redis).
Provider callbacks (``POST /webhooks/{provider}/{channel}``) move the row to delivered/bounced/read.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.config import settings
from app.db.session import redis_client
from app.models.communication import MessageLog
from app.repositories.message_log_repository import MessageLogRepository
from app.repositories.template_repository import TemplateRepository
from app.services.notifications.dispatcher import body_key

log = structlog.get_logger()

PLATFORM_PROVIDER = {
    "sms": lambda: settings.SMS_PROVIDER,
    "email": lambda: settings.EMAIL_PROVIDER,
    "whatsapp": lambda: settings.WHATSAPP_PROVIDER,
    "push": lambda: settings.PUSH_PROVIDER,
}
RETRY_BACKOFF_MIN = (1, 5, 30)


class DeliveryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


async def provider_for(db: AsyncSession, institution_id: uuid.UUID | None, channel: str) -> str:
    if institution_id is not None:
        row = (
            await db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                    "AND category = 'integrations' AND key = 'provider_overrides'"
                ),
                {"i": institution_id},
            )
        ).first()
        if row and isinstance(row[0], dict) and row[0].get(channel):
            return str(row[0][channel])
    getter = PLATFORM_PROVIDER.get(channel)
    return (getter() if getter else None) or "mock"


async def _compliance(db: AsyncSession, row: MessageLog, provider: str) -> dict[str, Any]:
    """Rule 3 — returns extra adapter kwargs (DLT ids, WhatsApp template) or raises ``DeliveryError``."""
    extra: dict[str, Any] = {}
    if row.institution_id is None or row.channel not in ("sms", "whatsapp"):
        return extra
    pack = (
        await db.execute(text("SELECT regulatory_pack FROM institutions WHERE id = :i"), {"i": row.institution_id})
    ).scalar_one_or_none()
    tmpl = None
    if row.template_id:
        tmpl = (
            await db.execute(
                text(
                    "SELECT dlt_template_id, whatsapp_template_name, language FROM notification_templates WHERE id = :t"
                ),
                {"t": row.template_id},
            )
        ).first()
    repo = TemplateRepository(db)
    if row.channel == "sms" and provider != "mock" and pack == "IN":
        dlt_id = tmpl.dlt_template_id if tmpl else None
        dlt = await repo.dlt_by_template_id(row.institution_id, dlt_id) if dlt_id else None
        if dlt is None or dlt.status != "approved":
            raise DeliveryError(
                "DLT_TEMPLATE_MISSING", "SMS in India needs an approved DLT template id on the notification template"
            )
        extra.update({"dlt_template_id": dlt.template_id, "sender_id": dlt.sender_id, "dlt_entity_id": dlt.entity_id})
    if row.channel == "whatsapp" and provider != "mock":
        session_open = (
            await db.execute(
                text(
                    "SELECT 1 FROM conversation_sessions WHERE institution_id = :i AND channel = 'whatsapp' "
                    "AND external_id = :to AND last_activity_at > NOW() - INTERVAL '24 hours' LIMIT 1"
                ),
                {"i": row.institution_id, "to": row.recipient},
            )
        ).first()
        name = tmpl.whatsapp_template_name if tmpl else None
        wa = await repo.wa_by_name(row.institution_id, name, tmpl.language if tmpl else "en") if name else None
        if session_open is None and (wa is None or wa.status != "approved"):
            raise DeliveryError(
                "WA_TEMPLATE_NOT_APPROVED",
                "WhatsApp template messages need an approved template outside a 24 h session",
            )
        if wa is not None:
            extra["whatsapp_template"] = wa.name
    return extra


async def deliver(db: AsyncSession, log_id: uuid.UUID) -> str:
    from app.integrations.registry import get_adapter

    repo = MessageLogRepository(db)
    row = await repo.get(log_id)
    if row is None or row.status not in ("queued", "deferred", "failed"):
        return row.status if row else "missing"
    parked = await redis_client.get(body_key(row.id))
    content = json.loads(parked) if parked else {"subject": row.subject, "body": row.body_preview or ""}
    provider = await provider_for(db, row.institution_id, row.channel)
    row.provider = provider
    try:
        extra = await _compliance(db, row, provider)
        adapter = get_adapter(row.channel, provider)
        to = row.recipient.split(":", 1)[1] if row.channel == "push" and ":" in row.recipient else row.recipient
        result = await adapter.send(to=to, body=content.get("body") or "", subject=content.get("subject"), **extra)
        row.status = "sent"
        row.sent_at = datetime.now(UTC)
        row.error = None
        if isinstance(result, dict):
            row.provider_message_id = str(result.get("reference") or result.get("id") or "")[:120] or None
            if result.get("cost_paise") is not None:
                row.cost_paise = int(result["cost_paise"])
    except DeliveryError as exc:
        row.status, row.error = "failed", f"{exc.code}: {exc}"
    except Exception as exc:  # noqa: BLE001 - provider errors are recorded and retried
        row.status, row.error = "failed", f"PROVIDER_ERROR: {str(exc)[:400]}"
    await db.flush()
    await events.emit(
        db,
        institution_id=row.institution_id,
        event_type="notification.sent" if row.status == "sent" else "notification.failed",
        payload={"message_log_id": str(row.id), "channel": row.channel, "provider": provider, "error": row.error},
        aggregate_type="message_log",
        aggregate_id=row.id,
    )
    log.info("notification_delivered", log_id=str(row.id), channel=row.channel, provider=provider, status=row.status)
    return row.status


async def retry_due(db: AsyncSession) -> dict[str, int]:
    """Beat ``notifications.retry_failed``: deferred rows whose quiet hours ended and failed rows due for a retry."""
    from app.core.jobs import send_after_commit
    from app.repositories.notification_repository import PreferenceRepository
    from app.services.notifications.dispatcher import in_quiet_hours

    repo = MessageLogRepository(db)
    now = datetime.now(UTC)
    counts = {"deferred": 0, "failed": 0}
    for row in await repo.due(("deferred", "failed"), now - timedelta(minutes=1)):
        if row.status == "failed":
            if (row.error or "").startswith(("DLT_", "WA_")):
                continue  # compliance failures need a configuration change, not a retry
            attempts = int(await redis_client.incr(f"msgretry:{row.id}"))
            await redis_client.expire(f"msgretry:{row.id}", 86400)
            if attempts > len(RETRY_BACKOFF_MIN) or now - row.created_at < timedelta(
                minutes=RETRY_BACKOFF_MIN[attempts - 1]
            ):
                continue
            counts["failed"] += 1
        else:
            if row.user_id is not None:
                from app.core.notifications.catalogue import category_of

                pref = (await PreferenceRepository(db).for_users([row.user_id], category_of(row.event_type or ""))).get(
                    row.user_id
                )
                tz = (
                    await db.execute(text("SELECT timezone FROM institutions WHERE id = :i"), {"i": row.institution_id})
                ).scalar_one_or_none() or "Asia/Kolkata"
                if pref is not None and (pref.digest or "none") != "none":
                    continue  # digest rows go out with notifications.digest
                if pref is not None and in_quiet_hours(pref.quiet_hours, tz):
                    continue
            counts["deferred"] += 1
        row.status = "queued"
        send_after_commit(
            db,
            "notifications.deliver",
            [str(row.id)],
            "emails" if row.channel == "email" else "notifications",
            str(uuid.uuid4()),
        )
    await db.flush()
    return counts


async def send_digests(db: AsyncSession, period: str) -> int:
    """Beat ``notifications.digest``: one message per user and channel bundling the deferred digest rows."""
    from app.core.jobs import send_after_commit

    rows = (
        (
            await db.execute(
                text(
                    "SELECT m.id, m.user_id, m.channel, m.institution_id, m.recipient, m.subject, m.body_preview "
                    "FROM message_logs m JOIN notification_preferences p ON p.user_id = m.user_id "
                    "WHERE m.status = 'deferred' AND p.digest = :d ORDER BY m.created_at"
                ),
                {"d": period},
            )
        )
        .mappings()
        .all()
    )
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((str(r["user_id"]), r["channel"]), []).append(dict(r))
    repo = MessageLogRepository(db)
    sent = 0
    for (user_id, channel), items in groups.items():
        body = "\n".join(f"• {i['subject'] or ''}: {i['body_preview'] or ''}" for i in items)
        digest = await repo.add(
            institution_id=items[0]["institution_id"],
            user_id=uuid.UUID(user_id),
            recipient=items[0]["recipient"],
            channel=channel,
            event_type="notifications.digest",
            subject=f"Your {period} digest ({len(items)})",
            body_preview=body[:255],
            status="queued",
        )
        await redis_client.set(body_key(digest.id), json.dumps({"subject": digest.subject, "body": body}), ex=3 * 86400)
        await db.execute(
            text(
                "UPDATE message_logs SET status = 'sent', error = 'bundled in digest ' || :d WHERE id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"d": str(digest.id), "ids": [str(i["id"]) for i in items]},
        )
        send_after_commit(
            db,
            "notifications.deliver",
            [str(digest.id)],
            "emails" if channel == "email" else "notifications",
            str(uuid.uuid4()),
        )
        sent += 1
    return sent
