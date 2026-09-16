"""Transactional-outbox relay — Prompts/00_PREREQUISITE_Project_Setup.md §3.14 (ADR 0005).

Beat runs ``outbox.relay`` every 5 s (Phase 01 adds the LISTEN/NOTIFY wake-up). Pending ``domain_events`` are
locked with ``FOR UPDATE SKIP LOCKED``, sent to every subscribed consumer task (at-least-once) and marked
``dispatched``; failures set ``next_attempt_at`` with exponential backoff and the event is ``dead`` after 10 attempts.
Consumers must be idempotent: they insert into ``event_consumptions(consumer, event_id)`` first and skip duplicates.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select, text

from app.tasks.celery_app import celery

log = structlog.get_logger()

CONSUMERS: dict[str, list[str]] = {}  # event_type → [celery task names]; phases register with subscribe()
MAX_ATTEMPTS = 10


def subscribe(event_type: str, task_name: str) -> None:
    """Register a Celery task as a consumer of an event type (``"*"`` receives every event)."""
    CONSUMERS.setdefault(event_type, []).append(task_name)


def consumers_for(event_type: str) -> list[str]:
    tasks = list(CONSUMERS.get(event_type, []))
    prefix = event_type.split(".")[0]
    tasks += CONSUMERS.get(f"{prefix}.*", [])
    tasks += CONSUMERS.get("*", [])
    return sorted(set(tasks))


@celery.task(name="outbox.relay", queue="scheduled")
def relay(batch: int = 500) -> dict[str, int]:
    """Dispatch pending events to their consumers; returns counters for Flower / logs."""
    return asyncio.run(_relay(batch))


async def _relay(batch: int) -> dict[str, int]:
    from app.db.session import SessionLocal
    from app.models.platform import DomainEvent

    dispatched = failed = 0
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        q = (
            select(DomainEvent)
            .where(
                DomainEvent.status == "pending",
                or_(DomainEvent.next_attempt_at.is_(None), DomainEvent.next_attempt_at <= now),
            )
            .order_by(DomainEvent.created_at)
            .limit(batch)
            .with_for_update(skip_locked=True)
        )
        events = list((await db.execute(q)).scalars().all())
        for ev in events:
            targets = consumers_for(ev.event_type)
            try:
                for task_name in targets:
                    celery.send_task(
                        task_name,
                        kwargs={
                            "institution_id": str(ev.institution_id) if ev.institution_id else None,
                            "event_id": str(ev.id),
                            "event_type": ev.event_type,
                            "payload": ev.payload,
                            "aggregate_type": ev.aggregate_type,
                            "aggregate_id": str(ev.aggregate_id) if ev.aggregate_id else None,
                        },
                    )
                ev.status, ev.dispatched_at, ev.attempts = "dispatched", now, ev.attempts + 1
                dispatched += 1
            except Exception as exc:  # noqa: BLE001 - broker failures are retried with backoff
                ev.attempts += 1
                ev.last_error = str(exc)[:2000]
                if ev.attempts >= MAX_ATTEMPTS:
                    ev.status = "dead"
                else:
                    ev.next_attempt_at = now + timedelta(minutes=2 ** min(ev.attempts, 8))
                failed += 1
        await db.commit()
    if dispatched or failed:
        log.info("outbox_relay", dispatched=dispatched, failed=failed)
    return {"dispatched": dispatched, "failed": failed}


async def mark_consumed(db: Any, consumer: str, event_id: str) -> bool:
    """Idempotency guard for consumers: returns False when this consumer already handled the event."""
    res = await db.execute(
        text(
            "INSERT INTO event_consumptions (consumer, event_id) VALUES (:c, :e) "
            "ON CONFLICT (consumer, event_id) DO NOTHING RETURNING consumer"
        ),
        {"c": consumer, "e": event_id},
    )
    return res.first() is not None


@celery.task(name="outbox.test_ping", queue="scheduled")
def test_ping(**event: Any) -> None:
    """Consumer for ``test.ping`` events (Phase 01 verification step 5)."""
    asyncio.run(_test_ping(event))


async def _test_ping(event: dict[str, Any]) -> None:
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        if await mark_consumed(db, "outbox.test_ping", event["event_id"]):
            log.info("test_ping", event_id=event["event_id"], payload=event.get("payload"))
        await db.commit()


subscribe("test.ping", "outbox.test_ping")
