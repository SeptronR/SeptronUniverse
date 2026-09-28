"""Shared plumbing of the Phase 05 services: tenant, audit, outbox events, snapshots and the regulation lock rule."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.services.institution.context import tenant_id


def snap(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in keys:
        v = getattr(obj, k)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, date | datetime):
            v = v.isoformat()
        out[k] = v
    return out


def ensure_structure_editable(regulation: Any) -> None:
    """Courses and structures under an ``active`` (or ``superseded``) regulation are frozen — clone instead
    (docs/Academic_Core_Design.md §1b). Every mutating endpoint of those rows calls this first."""
    if regulation.status in ("active", "superseded"):
        raise APIError(
            409,
            ErrorCode.RECORD_LOCKED,
            f"Regulation {regulation.code} is {regulation.status}: clone it to change courses or structure",
            {"regulation_id": str(regulation.id), "status": regulation.status},
        )


def ensure_rules_editable(regulation: Any) -> None:
    """Rules are locked from approval on (``approved`` keeps the structure editable, ``active`` freezes everything)."""
    if regulation.status != "draft":
        raise APIError(
            409,
            ErrorCode.RECORD_LOCKED,
            f"Regulation {regulation.code} is {regulation.status}: rules are locked after approval",
            {"regulation_id": str(regulation.id), "status": regulation.status},
        )


class AcademicServiceBase:
    audit_module = "programs"

    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = tenant_id(principal, request)

    async def _audit(
        self,
        action: str,
        record_type: str,
        record_id: uuid.UUID,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
        module: str | None = None,
    ) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module=module or self.audit_module,
            action=action,
            record_type=record_type,
            record_id=record_id,
            old=old,
            new=new,
            request=self.request,
        )

    async def _emit(
        self, event_type: str, payload: dict[str, Any], aggregate_type: str, aggregate_id: uuid.UUID
    ) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=event_type,
            payload=payload,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor_user_id=getattr(self.principal, "id", None),
        )
