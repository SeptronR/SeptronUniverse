"""Domain events (transactional outbox) — Prompts/00_PREREQUISITE_Project_Setup.md §3.14 (ADR 0005).

Services call ``await events.emit(db, ...)`` inside the business transaction; the row is committed together with the
change and ``tasks/outbox.py:relay`` dispatches it after commit (at-least-once; consumers dedupe on
``event_consumptions``).
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import DomainEvent


async def emit(
    db: AsyncSession,
    *,
    institution_id: uuid.UUID | None,
    event_type: str,
    payload: dict[str, Any],
    aggregate_type: str | None = None,
    aggregate_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Write the event in the SAME transaction as the business change. The relay dispatches it after commit."""
    ev = DomainEvent(
        institution_id=institution_id,
        event_type=event_type,
        payload=payload,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        actor_user_id=actor_user_id,
    )
    db.add(ev)
    await db.flush()
    return ev.id
