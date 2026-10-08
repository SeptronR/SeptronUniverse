"""Audit trail — Prompts/00_PREREQUISITE_Project_Setup.md §3.19.

``log_audit`` is the explicit call from services (every mutation, coding standard 7). ``audit_fallback`` is used by
``AuditMiddleware`` when a 2xx mutation route forgot to call it. The hash chain (``prev_hash`` → ``hash``) is
computed by the DB trigger in Database_Schema.sql §35; the application supplies a content hash for the row.
"""

import hashlib
import json
import uuid
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import AuditLog

log = structlog.get_logger()


def _content_hash(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, default=str, sort_keys=True).encode()).hexdigest()


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


async def log_audit(
    db: AsyncSession,
    *,
    principal: Any,
    module: str,
    action: str,
    record_type: str,
    record_id: uuid.UUID | None,
    old: dict[str, Any] | None = None,
    new: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Explicit audit call from services. The DB trigger computes the hash chain."""
    user_id = getattr(principal, "id", None)
    institution_id = getattr(principal, "institution_id", None)
    row = AuditLog(
        institution_id=institution_id,
        user_id=user_id,
        impersonator_id=getattr(principal, "impersonator_id", None),
        module=module,
        action=action,
        record_type=record_type,
        record_id=record_id,
        old_values=old,
        new_values=new,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent") if request else None,
        request_id=getattr(request.state, "request_id", None) if request else None,
        hash=_content_hash(institution_id, user_id, module, action, record_type, record_id, old, new),
    )
    db.add(row)
    await db.flush()
    if request is not None:
        request.state.audited = True
    return row


async def audit_fallback(request: Request, status: int) -> None:
    """Middleware fallback for mutations that skipped ``log_audit``: records the route in its own short transaction."""
    from app.db.session import SessionLocal, bind_tenant

    module = request.url.path.split("/")[3] if request.url.path.startswith("/api/v1/") else "http"
    institution_id = getattr(request.state, "institution_id", None)
    user_id = getattr(request.state, "user_id", None)
    try:
        async with SessionLocal() as db:
            if institution_id:
                bind_tenant(db, institution_id)  # audit_logs is RLS-scoped: pin the tenant like get_db does
            db.add(
                AuditLog(
                    institution_id=uuid.UUID(str(institution_id)) if institution_id else None,
                    user_id=user_id,
                    module=module[:60],
                    action=request.method.lower(),
                    record_type="http_route",
                    record_id=None,
                    new_values={"path": request.url.path, "status": status},
                    ip=_client_ip(request),
                    user_agent=request.headers.get("user-agent"),
                    request_id=getattr(request.state, "request_id", None),
                    hash=_content_hash(institution_id, user_id, request.url.path, status),
                )
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - never fail the response because the fallback audit failed
        log.warning("audit_fallback_failed", path=request.url.path, error=str(exc))
