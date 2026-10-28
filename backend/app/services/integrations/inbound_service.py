"""Inbound provider webhooks — Prompts/41 §41.6 ``inbound_webhook_service``.

``POST /api/v1/webhooks/in/{provider}/{connection_id}`` (public; the Phase 04 ``/webhooks/{provider}/{channel}``,
Phase 12 ``/webhooks/payments/{provider}``, Phase 24 WhatsApp and Phase 31 plagiarism routes stay as they are):
1. Body ≤ 1 MB (413); the connection must exist and be enabled; the adapter verifies the signature
   (``verify_webhook(body, signature)`` from ``X-Signature`` / provider headers) — failure → 401 + audit row.
2. Idempotency: the provider event id (``webhook_parse``) is recorded in ``idempotency_keys``
   (``route='webhook:<provider>'``, 30 days); a duplicate answers 200 ``{duplicate: true}`` with no side effect.
3. Dispatch to the owning module: payments → Phase 12 ``PaymentService.webhook``; SMS / e-mail delivery reports →
   Phase 04 ``message_logs`` by ``provider_message_id``; device punches (ZKTeco ADMS / RFID HTTP) and every other
   capability → domain event ``integrations.inbound_received`` with the parsed payload (module consumers: Phase 06 /
   11 punches, Phase 18 DigiLocker acks, Phase 26 eSign callbacks, Phase 19 Koha events …).
4. Every call lands in the inbound log (Redis stream ``inbound:{inst}``) — replay re-runs the dispatch from the
   stored body (idempotency still applies to module side effects).
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.integrations.hub import build_adapter, decrypt_config
from app.services.integrations.webhook_service import log_inbound

MAX_BODY = 1024 * 1024
SIG_HEADERS = (
    "x-signature",
    "x-razorpay-signature",
    "stripe-signature",
    "x-hub-signature-256",
    "x-zoom-signature",
    "x-device-token",
)


async def handle(
    db: AsyncSession, request: Request, provider: str, connection_id: uuid.UUID, body: bytes, *, replay: bool = False
) -> dict[str, Any]:
    if len(body) > MAX_BODY:
        raise APIError(413, ErrorCode.VALIDATION, "Payload too large")
    from app.db.session import bind_tenant, set_tenant

    row = (
        (
            await db.execute(
                text(
                    "SELECT id, institution_id, capability, provider, config_encrypted, public_config, is_sandbox, status FROM integration_connections WHERE id = :c"
                ),
                {"c": connection_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["provider"] != provider or row["status"] == "disabled":
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown connection")
    inst = row["institution_id"]
    bind_tenant(db, inst)
    await set_tenant(db, inst)
    cfg = {
        **{k: v for k, v in (row["public_config"] or {}).items() if k not in ("is_default", "kid")},
        **decrypt_config(row["config_encrypted"]),
    }
    adapter = build_adapter(row["capability"], provider, cfg, connection_id=row["id"], sandbox=row["is_sandbox"])
    signature = next((request.headers.get(h) for h in SIG_HEADERS if request.headers.get(h)), "")
    verifier = getattr(adapter, "verify_webhook", None)
    if not replay and callable(verifier) and provider != "mock" and not verifier(body=body, signature=signature):
        await log_inbound(inst, provider, str(connection_id), None, None, False, False, "invalid signature", body)
        await log_audit(
            db,
            principal=None,
            module="integrations",
            action="inbound_rejected",
            record_type="integration_connection",
            record_id=row["id"],
            new={"provider": provider},
            request=request,
        )
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid webhook signature")
    parser = getattr(adapter, "webhook_parse", None)
    try:
        parsed: Any = parser(body) if callable(parser) and provider != "mock" else json.loads(body or b"{}")
    except Exception as exc:  # noqa: BLE001 - a malformed body is a 422, logged
        await log_inbound(inst, provider, str(connection_id), None, None, False, False, f"parse: {exc}", body)
        raise APIError(422, ErrorCode.VALIDATION, "Malformed webhook body") from exc
    event_id = str(
        (parsed.get("event_id") if isinstance(parsed, dict) else None) or hashlib.sha256(body).hexdigest()[:40]
    )
    event_type = str(parsed.get("type") if isinstance(parsed, dict) else "batch")
    if not replay:
        seen = (
            await db.execute(
                text(
                    "SELECT 1 FROM idempotency_keys WHERE institution_id = :i AND route = :r AND idempotency_key = :k"
                ),
                {"i": inst, "r": f"webhook:{provider}", "k": event_id[:120]},
            )
        ).first()
        if seen:
            await log_inbound(inst, provider, str(connection_id), event_type, event_id, False, True, None, body)
            return {"duplicate": True, "event_id": event_id}
        await db.execute(
            text(
                "INSERT INTO idempotency_keys (id, institution_id, user_id, idempotency_key, route, request_hash, status, response_code, created_at, expires_at) "
                "VALUES (:id, :i, NULL, :k, :r, :h, 'completed', 200, NOW(), :e)"
            ),
            {
                "id": uuid.uuid4(),
                "i": inst,
                "k": event_id[:120],
                "r": f"webhook:{provider}",
                "h": hashlib.sha256(body).hexdigest(),
                "e": datetime.now(UTC) + timedelta(days=30),
            },
        )
    error = None
    try:
        await dispatch(db, request, inst, row["capability"], provider, parsed, body, signature or "")
    except APIError as exc:
        error = exc.message
    await log_inbound(inst, provider, str(connection_id), event_type, event_id, error is None, False, error, body)
    return {"processed": error is None, "event_id": event_id, "error": error}


async def dispatch(
    db: AsyncSession,
    request: Request,
    inst: Any,
    capability: str,
    provider: str,
    parsed: Any,
    body: bytes,
    signature: str,
) -> None:
    if capability == "payment":
        from app.services.fees.payment_service import PaymentService

        await PaymentService(db, None, request, inst).webhook(provider, body, signature, json.loads(body or b"{}"))
        return
    if capability in ("sms", "email") and isinstance(parsed, dict) and parsed.get("reference"):
        status = {"delivered": "delivered", "failed": "failed", "bounced": "failed", "undelivered": "failed"}.get(
            str(parsed.get("status")), None
        )
        if status:
            await db.execute(
                text(
                    "UPDATE message_logs SET status = :s, delivered_at = CASE WHEN :s = 'delivered' THEN NOW() ELSE delivered_at END WHERE institution_id = :i AND provider_message_id = :r"
                ),
                {"s": status, "i": inst, "r": str(parsed["reference"])},
            )
        return
    await events.emit(
        db,
        institution_id=inst,
        event_type="integrations.inbound_received",
        payload={
            "capability": capability,
            "provider": provider,
            "data": parsed if isinstance(parsed, (dict, list)) else {},
        },
        aggregate_type="integration_connection",
    )
