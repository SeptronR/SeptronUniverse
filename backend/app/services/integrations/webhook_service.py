"""Outbound webhooks, dead letters and inbound provider webhooks — Prompts/41 §41.6.

Outbound (``integrations.api_keys_webhooks``; ``integrations:webhooks``)
1. Subscriptions: https URLs only, events from :data:`EVENT_CATALOGUE` (or ``*``), a generated secret (shown once,
   AES-GCM encrypted), custom headers / auto-disable flag in ``integrations_meta webhook:<id>``.
2. Fan-out (consumer ``webhooks.fanout`` on every domain event): one ``webhook_deliveries`` row per matching active
   subscription. The envelope ``{id, type, occurred_at, institution_id, data, version}`` drops PII keys.
3. Delivery (Beat ``webhooks.retry_due`` every minute, ``FOR UPDATE SKIP LOCKED``): POST with
   ``X-Universe-Signature: t=<ts>, v1=HMAC-SHA256(secret, "<ts>.<body>")``, ``X-Universe-Event``,
   ``X-Universe-Delivery``; 2xx → ``delivered``; else retry after ``webhooks.retry_schedule_s`` (60 s, 5 min,
   30 min, 2 h, 12 h); after 5 attempts → ``dead`` + ``integrations.webhook_dead_letter``; 100 consecutive dead →
   the webhook is auto-disabled and the tenant notified. Manual retry / replay of dead deliveries resets attempts.
Dead letters: outbox ``domain_events(status='dead')``, ``webhook_deliveries(status='dead')`` and notifications that
exhausted retries (``message_logs status='failed'``) — replay re-queues, discard marks them with a reason (audited).
Inbound: ``verify`` the provider signature through the connection's adapter, idempotency on the provider event id
(``idempotency_keys`` route ``webhook:<provider>``; duplicates answer 200 without side effects), dispatch to the
owning module, keep a Redis stream log (``inbound:{inst}``, 2 000 entries) with replay.
"""

from __future__ import annotations

import builtins
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.notifications.notify import notify_event
from app.db.session import redis_client
from app.models.platform import Webhook, WebhookDelivery
from app.schemas.integrations import (
    DeadLetterOut,
    DeliveryOut,
    EventCatalogueItem,
    InboundEventOut,
    WebhookCreatedOut,
    WebhookIn,
    WebhookOut,
)

log = structlog.get_logger()
META = "integrations_meta"
RETRY_SCHEDULE = (60, 300, 1800, 7200, 43200)
DEAD_AFTER = 5
AUTO_DISABLE_AFTER = 100
PII_KEYS = frozenset(
    {
        "aadhaar",
        "aadhaar_encrypted",
        "phone",
        "mobile",
        "email",
        "dob",
        "pan",
        "bank_details",
        "address",
        "password",
        "token",
        "otp",
    }
)

_EVENTS: tuple[tuple[str, str], ...] = (
    ("student.created", "A student record was created"),
    ("student.admitted", "An applicant was admitted"),
    ("student.updated", "A student record changed"),
    ("enrollment.created", "A programme enrolment started"),
    ("registration.approved", "Course registration approved"),
    ("attendance.finalized", "Attendance of a session finalised"),
    ("marks.locked", "Internal marks locked"),
    ("exam.registration_submitted", "Exam registration submitted"),
    ("hall_ticket.issued", "Hall ticket issued"),
    ("result.published", "Results published"),
    ("results.revaluation_decided", "Revaluation decided"),
    ("fee.invoice_created", "Fee invoice raised"),
    ("fees.invoice_created", "Fee invoice raised"),
    ("fee.paid", "Fee payment received"),
    ("fees.payment_received", "Fee payment received"),
    ("fee.refunded", "Fee refunded"),
    ("scholarship.sanctioned", "Scholarship sanctioned"),
    ("hostel.checked_in", "Hostel check-in"),
    ("hostel.leave_approved", "Out-pass approved"),
    ("library.issued", "Book issued"),
    ("library.returned", "Book returned"),
    ("placement.offer_recorded", "Placement offer recorded"),
    ("placement.drive_published", "Drive published"),
    ("document.issued", "Document issued"),
    ("documents.issued", "Document issued"),
    ("leave.approved", "Staff leave approved"),
    ("payroll.paid", "Payroll paid"),
    ("staff.created", "Staff record created"),
    ("applicant.submitted", "Application submitted"),
    ("admission.allotted", "Seat allotted"),
    ("event.registered", "Event registration"),
    ("grievance.created", "Grievance raised"),
    ("grievance.resolved", "Grievance resolved"),
    ("announcement.published", "Announcement published"),
    ("degree.awarded", "Degree awarded"),
    ("transcript.issued", "Transcript issued"),
    ("alumni.donation_received", "Donation received"),
    ("website.enquiry_received", "Website enquiry"),
    ("website.notice_published", "Website notice published"),
    ("imports.applied", "Data import applied"),
    ("ping", "Test delivery"),
)
EVENT_CATALOGUE: dict[str, str] = dict(_EVENTS)


def catalogue() -> builtins.list[EventCatalogueItem]:
    return [
        EventCatalogueItem(
            event_type=k,
            description=v,
            payload_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}, "type": {"type": "string"}, "data": {"type": "object"}},
            },
        )
        for k, v in _EVENTS
    ]


def strip_pii(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: strip_pii(v)
            for k, v in data.items()
            if k.lower() not in PII_KEYS and not k.lower().endswith("_encrypted")
        }
    if isinstance(data, list):
        return [strip_pii(v) for v in data]
    return data


def sign(secret: str, ts: int, body: bytes) -> str:
    return f"t={ts}, v1=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


async def _meta(db: Any, inst: Any, key: str) -> dict[str, Any]:
    r = (
        await db.execute(
            text(
                "SELECT value FROM institution_settings WHERE institution_id = :i AND category = :c AND key = :k AND college_id IS NULL"
            ),
            {"i": inst, "c": META, "k": key},
        )
    ).first()
    return dict(r[0]) if r and isinstance(r[0], dict) else {}


async def _put_meta(db: Any, inst: Any, key: str, value: dict[str, Any]) -> None:
    await db.execute(
        text(
            "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, is_public, created_at, updated_at) "
            "VALUES (:id, :i, NULL, :c, :k, CAST(:v AS jsonb), 'json', FALSE, NOW(), NOW()) "
            "ON CONFLICT (institution_id, college_id, category, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"id": uuid.uuid4(), "i": inst, "c": META, "k": key, "v": json.dumps(value, default=str)},
    )


class WebhookService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = principal.institution_id

    def _writer(self) -> None:
        if not (self.principal.has("integrations", "webhooks") or self.principal.has("integrations", "manage")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")

    async def _out(self, w: Webhook) -> WebhookOut:
        meta = await _meta(self.db, self.inst, f"webhook:{w.id}")
        stats = {
            r[0]: int(r[1])
            for r in (
                await self.db.execute(
                    text(
                        "SELECT status, count(*) FROM webhook_deliveries WHERE webhook_id = :w AND institution_id = :i GROUP BY 1"
                    ),
                    {"w": w.id, "i": self.inst},
                )
            ).all()
        }
        return WebhookOut(
            id=w.id,
            name=w.name,
            url=w.url,
            events=list(w.events or []),
            is_active=w.is_active,
            headers=dict(meta.get("headers") or {}),
            secret_hint=str(meta.get("hint") or "••••"),
            stats=stats,
            auto_disabled=bool(meta.get("auto_disabled")),
            created_at=w.created_at,
        )

    async def list(self) -> builtins.list[WebhookOut]:
        rows = (
            await self.db.execute(
                select(Webhook).where(Webhook.institution_id == self.inst).order_by(Webhook.created_at)
            )
        ).scalars()
        return [await self._out(w) for w in rows]

    async def _get(self, wid: uuid.UUID) -> Webhook:
        w = await self.db.get(Webhook, wid)
        if w is None or w.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Webhook not found")
        return w

    def _validate(self, body: WebhookIn) -> None:
        bad = [e for e in body.events if e != "*" and e not in EVENT_CATALOGUE]
        if bad:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown events: {', '.join(bad)}", {"field": "events"})

    async def create(self, body: WebhookIn) -> WebhookCreatedOut:
        self._writer()
        self._validate(body)
        from app.core.security import encrypt_secret

        secret = "whsec_" + secrets.token_urlsafe(32)
        w = Webhook(
            institution_id=self.inst,
            name=body.name,
            url=body.url,
            secret_encrypted=encrypt_secret(secret),
            events=body.events,
            is_active=body.is_active,
            created_by=self.principal.id,
        )
        self.db.add(w)
        await self.db.flush()
        await _put_meta(
            self.db, self.inst, f"webhook:{w.id}", {"headers": body.headers, "hint": secret[-4:], "consecutive_dead": 0}
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="webhook_create",
            record_type="webhook",
            record_id=w.id,
            new={"url": w.url, "events": w.events},
            request=self.request,
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="integrations.webhook_created",
            payload={"id": str(w.id)},
            aggregate_type="webhook",
            aggregate_id=w.id,
        )
        return WebhookCreatedOut(**(await self._out(w)).model_dump(), secret=secret)

    async def update(self, wid: uuid.UUID, body: WebhookIn) -> WebhookOut:
        self._writer()
        self._validate(body)
        w = await self._get(wid)
        w.name, w.url, w.events, w.is_active = body.name, body.url, body.events, body.is_active
        meta = await _meta(self.db, self.inst, f"webhook:{w.id}")
        await _put_meta(
            self.db,
            self.inst,
            f"webhook:{w.id}",
            {
                **meta,
                "headers": body.headers,
                **({"auto_disabled": False, "consecutive_dead": 0} if body.is_active else {}),
            },
        )
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="webhook_update",
            record_type="webhook",
            record_id=w.id,
            request=self.request,
        )
        return await self._out(w)

    async def delete(self, wid: uuid.UUID) -> None:
        self._writer()
        w = await self._get(wid)
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="webhook_delete",
            record_type="webhook",
            record_id=w.id,
            request=self.request,
        )
        await self.db.delete(w)

    async def rotate_secret(self, wid: uuid.UUID) -> WebhookCreatedOut:
        self._writer()
        from app.core.security import encrypt_secret

        w = await self._get(wid)
        secret = "whsec_" + secrets.token_urlsafe(32)
        w.secret_encrypted = encrypt_secret(secret)
        meta = await _meta(self.db, self.inst, f"webhook:{w.id}")
        await _put_meta(self.db, self.inst, f"webhook:{w.id}", {**meta, "hint": secret[-4:]})
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="webhook_rotate",
            record_type="webhook",
            record_id=w.id,
            request=self.request,
        )
        return WebhookCreatedOut(**(await self._out(w)).model_dump(), secret=secret)

    async def test(self, wid: uuid.UUID, event_type: str) -> DeliveryOut:
        self._writer()
        w = await self._get(wid)
        eid = uuid.uuid4()
        d = WebhookDelivery(
            id=uuid.uuid4(),
            institution_id=self.inst,
            webhook_id=w.id,
            event_id=eid,
            event_type=event_type or "ping",
            status="pending",
            attempts=0,
            next_retry_at=datetime.now(UTC),
        )
        self.db.add(d)
        await self.db.flush()
        await redis_client.set(
            f"whpayload:{d.id}",
            json.dumps(
                {
                    "id": str(eid),
                    "type": d.event_type,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "institution_id": str(self.inst),
                    "data": {"message": "ping"},
                    "version": "1",
                }
            ),
            ex=7 * 86400,
        )
        await deliver(self.db, d)
        return delivery_out(d)

    async def deliveries(
        self, webhook_id: uuid.UUID | None, status: str | None, event_type: str | None
    ) -> builtins.list[DeliveryOut]:
        q = select(WebhookDelivery).where(WebhookDelivery.institution_id == self.inst)
        if webhook_id:
            q = q.where(WebhookDelivery.webhook_id == webhook_id)
        if status:
            q = q.where(WebhookDelivery.status == status)
        if event_type:
            q = q.where(WebhookDelivery.event_type == event_type)
        return [
            delivery_out(d)
            for d in (await self.db.execute(q.order_by(WebhookDelivery.created_at.desc()).limit(300))).scalars()
        ]

    async def delivery(self, did: uuid.UUID) -> DeliveryOut:
        d = (
            await self.db.execute(
                select(WebhookDelivery).where(WebhookDelivery.id == did, WebhookDelivery.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if d is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Delivery not found")
        out = delivery_out(d)
        raw = await redis_client.get(f"whpayload:{d.id}")
        out.payload = json.loads(raw) if raw else None
        return out

    async def retry(self, ids: builtins.list[uuid.UUID], all_dead: bool, webhook_id: uuid.UUID | None) -> int:
        self._writer()
        sql = "UPDATE webhook_deliveries SET status = 'pending', attempts = 0, next_retry_at = NOW() WHERE institution_id = :i AND "
        params: dict[str, Any] = {"i": self.inst}
        if all_dead:
            sql += "status = 'dead'" + (" AND webhook_id = :w" if webhook_id else "")
            params["w"] = webhook_id
        else:
            sql += "id = ANY(:ids)"
            params["ids"] = ids
        n = int(getattr(await self.db.execute(text(sql), params), "rowcount", 0) or 0)
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="webhook_replay",
            record_type="webhook_delivery",
            record_id=None,
            new={"count": n, "all_dead": all_dead},
            request=self.request,
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="integrations.webhook_replayed",
            payload={"count": n},
            aggregate_type="webhook",
        )
        return n


def delivery_out(d: WebhookDelivery) -> DeliveryOut:
    return DeliveryOut(
        id=d.id,
        webhook_id=d.webhook_id,
        event_id=d.event_id,
        event_type=d.event_type,
        status=d.status,
        attempts=d.attempts,
        response_code=d.response_code,
        response_body=(d.response_body or "")[:500] or None,
        next_retry_at=d.next_retry_at,
        delivered_at=d.delivered_at,
        created_at=d.created_at,
    )


# ---- fan-out / delivery (platform session in tasks) ----------------------------------------------------------------------------
async def fanout(db: Any, event: dict[str, Any]) -> int:
    inst = event.get("institution_id")
    etype = str(event.get("event_type") or "")
    if not inst or etype.startswith(("integrations.webhook", "notification.")):
        return 0
    hooks = (
        (await db.execute(select(Webhook).where(Webhook.institution_id == inst, Webhook.is_active.is_(True))))
        .scalars()
        .all()
    )
    n = 0
    for w in hooks:
        if "*" not in (w.events or []) and etype not in (w.events or []):
            continue
        d = WebhookDelivery(
            id=uuid.uuid4(),
            institution_id=w.institution_id,
            webhook_id=w.id,
            event_id=uuid.UUID(str(event.get("event_id") or uuid.uuid4())),
            event_type=etype,
            status="pending",
            attempts=0,
            next_retry_at=datetime.now(UTC),
        )
        db.add(d)
        await redis_client.set(
            f"whpayload:{d.id}",
            json.dumps(
                {
                    "id": str(d.event_id),
                    "type": etype,
                    "occurred_at": str(event.get("occurred_at") or datetime.now(UTC).isoformat()),
                    "institution_id": str(inst),
                    "data": strip_pii(event.get("payload") or {}),
                    "version": "1",
                },
                default=str,
            ),
            ex=7 * 86400,
        )
        n += 1
    await db.flush()
    return n


async def deliver(db: Any, d: WebhookDelivery) -> str:
    import httpx

    from app.core.security import decrypt_secret

    w = await db.get(Webhook, d.webhook_id)
    if w is None or not w.is_active:
        d.status = "dead"
        await db.flush()
        return d.status
    raw = await redis_client.get(f"whpayload:{d.id}") or json.dumps(
        {"id": str(d.event_id), "type": d.event_type, "data": {}}
    )
    body = str(raw).encode()
    ts = int(time.time())
    meta = await _meta(db, w.institution_id, f"webhook:{w.id}")
    headers = {
        **dict(meta.get("headers") or {}),
        "Content-Type": "application/json",
        "X-Universe-Signature": sign(decrypt_secret(bytes(w.secret_encrypted)), ts, body),
        "X-Universe-Event": d.event_type,
        "X-Universe-Delivery": str(d.id),
    }
    d.attempts += 1
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as c:
            r = await c.post(w.url, content=body, headers=headers)
        d.response_code, d.response_body = r.status_code, r.text[:2000]
        ok = 200 <= r.status_code < 300
    except Exception as exc:  # noqa: BLE001 - the receiver's failure is the delivery result
        d.response_code, d.response_body, ok = None, str(exc)[:500], False
    if ok:
        d.status, d.delivered_at, d.next_retry_at = "delivered", datetime.now(UTC), None
        meta["consecutive_dead"] = 0
    elif d.attempts >= DEAD_AFTER:
        d.status, d.next_retry_at = "dead", None
        meta["consecutive_dead"] = int(meta.get("consecutive_dead", 0)) + 1
        await notify_event(
            db,
            w.institution_id,
            "integrations.webhook_dead_letter",
            audience={"roles": ["integration_admin"]},
            context={"webhook": w.name, "event_type": d.event_type, "route": "/admin/integrations/webhooks"},
        )
        if meta["consecutive_dead"] >= AUTO_DISABLE_AFTER:
            w.is_active = False
            meta["auto_disabled"] = True
            await events.emit(
                db,
                institution_id=w.institution_id,
                event_type="integrations.webhook_auto_disabled",
                payload={"id": str(w.id)},
                aggregate_type="webhook",
                aggregate_id=w.id,
            )
    else:
        d.status = "failed"
        d.next_retry_at = datetime.now(UTC) + timedelta(
            seconds=RETRY_SCHEDULE[min(d.attempts - 1, len(RETRY_SCHEDULE) - 1)]
        )
    await _put_meta(db, w.institution_id, f"webhook:{w.id}", meta)
    await db.flush()
    return d.status


async def retry_due(db: Any, limit: int = 200) -> dict[str, int]:
    rows = (
        (
            await db.execute(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.status.in_(("pending", "failed")),
                    WebhookDelivery.next_retry_at <= datetime.now(UTC),
                )
                .order_by(WebhookDelivery.next_retry_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, int] = {}
    for d in rows:
        s = await deliver(db, d)
        out[s] = out.get(s, 0) + 1
    return out


# ---- dead letters ---------------------------------------------------------------------------------------------------------
class DeadLetterService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = principal.institution_id

    async def list(self, kind: str | None) -> builtins.list[DeadLetterOut]:
        out: builtins.list[DeadLetterOut] = []
        if kind in (None, "outbox"):
            for r in (
                await self.db.execute(
                    text(
                        "SELECT id, event_type, last_error, attempts, created_at FROM domain_events WHERE institution_id = :i AND status = 'dead' ORDER BY created_at DESC LIMIT 200"
                    ),
                    {"i": self.inst},
                )
            ).mappings():
                out.append(
                    DeadLetterOut(
                        kind="outbox",
                        id=r["id"],
                        type=r["event_type"],
                        error=r["last_error"],
                        attempts=r["attempts"],
                        created_at=r["created_at"],
                    )
                )
        if kind in (None, "webhook"):
            for r in (
                await self.db.execute(
                    text(
                        "SELECT id, event_type, response_body, attempts, created_at FROM webhook_deliveries WHERE institution_id = :i AND status = 'dead' ORDER BY created_at DESC LIMIT 200"
                    ),
                    {"i": self.inst},
                )
            ).mappings():
                out.append(
                    DeadLetterOut(
                        kind="webhook",
                        id=r["id"],
                        type=r["event_type"],
                        error=(r["response_body"] or "")[:300],
                        attempts=r["attempts"],
                        created_at=r["created_at"],
                    )
                )
        if kind in (None, "notification"):
            for r in (
                await self.db.execute(
                    text(
                        "SELECT id, event_type, error, created_at FROM message_logs WHERE institution_id = :i AND status = 'failed' ORDER BY created_at DESC LIMIT 200"
                    ),
                    {"i": self.inst},
                )
            ).mappings():
                out.append(
                    DeadLetterOut(
                        kind="notification",
                        id=r["id"],
                        type=r["event_type"] or "notification",
                        error=r["error"],
                        created_at=r["created_at"],
                    )
                )
        return out

    async def replay(self, kind: str, ids: builtins.list[uuid.UUID]) -> int:
        if kind == "outbox":
            sql = "UPDATE domain_events SET status = 'pending', attempts = 0, last_error = NULL WHERE institution_id = :i AND id = ANY(:ids) AND status = 'dead'"
        elif kind == "webhook":
            sql = "UPDATE webhook_deliveries SET status = 'pending', attempts = 0, next_retry_at = NOW() WHERE institution_id = :i AND id = ANY(:ids) AND status = 'dead'"
        else:
            sql = "UPDATE message_logs SET status = 'deferred', error = NULL WHERE institution_id = :i AND id = ANY(:ids) AND status = 'failed'"
        n = int(getattr(await self.db.execute(text(sql), {"i": self.inst, "ids": ids}), "rowcount", 0) or 0)
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="dead_letter_replay",
            record_type=kind,
            record_id=None,
            new={"count": n},
            request=self.request,
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="integrations.dead_letter_replayed",
            payload={"kind": kind, "count": n},
            aggregate_type="dead_letter",
        )
        return n

    async def discard(self, kind: str, ids: builtins.list[uuid.UUID], reason: str | None) -> int:
        table, col = {
            "outbox": ("domain_events", "last_error"),
            "webhook": ("webhook_deliveries", "response_body"),
            "notification": ("message_logs", "error"),
        }[kind]
        status = "discarded" if kind != "notification" else "cancelled"
        sql = f"UPDATE {table} SET status = :s, {col} = :r WHERE institution_id = :i AND id = ANY(:ids)"  # noqa: S608 - fixed identifiers
        n = int(
            getattr(
                await self.db.execute(
                    text(sql), {"s": status, "r": f"discarded: {reason or ''}"[:500], "i": self.inst, "ids": ids}
                ),
                "rowcount",
                0,
            )
            or 0
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="dead_letter_discard",
            record_type=kind,
            record_id=None,
            new={"count": n, "reason": reason},
            request=self.request,
        )
        return n


# ---- inbound log ---------------------------------------------------------------------------------------------------------
async def log_inbound(
    inst: Any,
    provider: str,
    connection_id: str | None,
    event_type: str | None,
    event_id: str | None,
    processed: bool,
    duplicate: bool,
    error: str | None,
    body: bytes,
) -> str:
    entry = {
        "provider": provider,
        "connection_id": connection_id or "",
        "event_type": event_type or "",
        "event_id": event_id or "",
        "processed": "1" if processed else "0",
        "duplicate": "1" if duplicate else "0",
        "error": (error or "")[:300],
        "received_at": datetime.now(UTC).isoformat(),
        "body": body[:20000].decode(errors="ignore"),
    }
    try:
        return str(await redis_client.xadd(f"inbound:{inst}", entry, maxlen=2000, approximate=True))  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return ""


async def inbound_list(inst: Any, provider: str | None) -> builtins.list[InboundEventOut]:
    try:
        rows = await redis_client.xrevrange(f"inbound:{inst}", count=300)
    except Exception:  # noqa: BLE001
        rows = []
    out = []
    for rid, e in rows:
        if provider and e.get("provider") != provider:
            continue
        out.append(
            InboundEventOut(
                id=str(rid),
                provider=e.get("provider", ""),
                connection_id=e.get("connection_id") or None,
                event_type=e.get("event_type") or None,
                event_id=e.get("event_id") or None,
                processed=e.get("processed") == "1",
                duplicate=e.get("duplicate") == "1",
                error=e.get("error") or None,
                received_at=e.get("received_at"),
            )
        )
    return out


async def inbound_entry(inst: Any, entry_id: str) -> dict[str, Any] | None:
    rows = await redis_client.xrange(f"inbound:{inst}", min=entry_id, max=entry_id)
    return dict(rows[0][1]) if rows else None
