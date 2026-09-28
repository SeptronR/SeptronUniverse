"""``notify_event`` — the single entry point modules use to notify people (Prompts/04 §04.6).

It never raises and never sends anything itself: it writes a ``notification.requested`` domain event in the caller's
transaction, so the notification exists exactly when the business change commits and delivery is at-least-once
through the outbox (consumer ``notifications.dispatch`` → ``services/notifications/dispatcher.py``).

``audience`` keys: ``user_ids``, ``roles``, ``college_id``, ``department_id``, ``program_id``, ``batch_id``,
``direct_contacts`` (``[{"channel": "sms", "to": "+91…"}]`` for people without an account, e.g. applicants),
``include_guardians`` (students' guardians when the student consented to the guardian portal).
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events

log = structlog.get_logger()


async def notify_event(
    db: AsyncSession,
    institution_id: uuid.UUID | str | None,
    event_type: str,
    *,
    audience: dict[str, Any],
    context: dict[str, Any] | None = None,
    channels: list[str] | None = None,
    priority: str = "normal",
    template_id: uuid.UUID | str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    try:
        iid = uuid.UUID(str(institution_id)) if institution_id else None
        return await events.emit(
            db,
            institution_id=iid,
            event_type="notification.requested",
            payload={
                "event_type": event_type,
                "audience": audience,
                "context": context or {},
                "channels": channels,
                "priority": priority,
                "template_id": str(template_id) if template_id else None,
            },
            aggregate_type="notification",
            actor_user_id=actor_user_id,
        )
    except Exception as exc:  # noqa: BLE001 - notifying must never break the business transaction
        log.warning("notify_event_failed", event_type=event_type, error=str(exc)[:300])
        return None
