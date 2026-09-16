"""Transactional-outbox relay and the consumer contract — Prompts/00 §3.14, Prompts/01 §01.6 (ADR 0005).

Beat runs ``outbox.relay`` every 5 s. Pending ``domain_events`` (``next_attempt_at`` due) are locked with
``FOR UPDATE SKIP LOCKED`` on the **platform session** (BYPASSRLS — the relay is cross-tenant by nature), sent to every
subscribed consumer task (at-least-once) and marked ``dispatched``. Delivery problems feed back into the event row:

* a broker failure while sending, or a consumer raising, increments ``attempts``, stores ``last_error`` and re-arms the
  event with exponential backoff ``next_attempt_at = now + 2^attempts min`` (capped at 2^8);
* after ``MAX_ATTEMPTS`` (10) the event is ``dead`` (dead-letter — visible in Phase 37/38 ops screens).

Consumers are declared with ``@consumer("search.reindex", events=["student.*", …])`` — an ``async def fn(db, event)``
that receives a tenant session (RLS context from ``event["institution_id"]``) or the platform session for platform
events. The wrapper is idempotent: it records ``event_consumptions(consumer, event_id)`` and skips duplicates, so a
retry triggered by one failing consumer never re-runs the others. ``"*"`` subscribes to every event, ``"student.*"``
to a prefix.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import or_, select, text

from app.tasks.celery_app import celery

log = structlog.get_logger()

CONSUMERS: dict[str, list[str]] = {}  # event_type (or prefix.* / *) → [celery task names]
MAX_ATTEMPTS = 10

ConsumerFn = Callable[[Any, dict[str, Any]], Awaitable[None]]


def subscribe(event_type: str, task_name: str) -> None:
    """Register a Celery task as a consumer of an event type (``"*"`` receives every event, ``"x.*"`` a prefix)."""
    tasks = CONSUMERS.setdefault(event_type, [])
    if task_name not in tasks:
        tasks.append(task_name)


def consumers_for(event_type: str) -> list[str]:
    tasks = list(CONSUMERS.get(event_type, []))
    prefix = event_type.split(".")[0]
    tasks += CONSUMERS.get(f"{prefix}.*", [])
    tasks += CONSUMERS.get("*", [])
    return sorted(set(tasks))


# ---- relay ---------------------------------------------------------------------------------------------------------


@celery.task(name="outbox.relay", queue="scheduled")
def relay(batch: int = 500) -> dict[str, int]:
    """Dispatch pending events to their consumers; returns counters for Flower / logs."""
    return asyncio.run(_relay(batch))


async def _relay(batch: int) -> dict[str, int]:
    from app.db.session import PlatformSessionLocal
    from app.models.platform import DomainEvent

    celery.loader.import_default_modules()  # every ``include``d task module registers its consumers before routing
    dispatched = failed = 0
    now = datetime.now(UTC)
    async with PlatformSessionLocal() as db:
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
            try:
                for task_name in consumers_for(ev.event_type):
                    celery.send_task(task_name, kwargs=_event_kwargs(ev))
                ev.status, ev.dispatched_at, ev.last_error = "dispatched", now, None
                dispatched += 1
            except Exception as exc:  # noqa: BLE001 - broker failures are retried with backoff
                _arm_retry(ev, str(exc))
                failed += 1
        await db.commit()
    if dispatched or failed:
        log.info("outbox_relay", dispatched=dispatched, failed=failed)
    return {"dispatched": dispatched, "failed": failed}


def _event_kwargs(ev: Any) -> dict[str, Any]:
    return {
        "institution_id": str(ev.institution_id) if ev.institution_id else None,
        "event_id": str(ev.id),
        "event_type": ev.event_type,
        "payload": ev.payload,
        "aggregate_type": ev.aggregate_type,
        "aggregate_id": str(ev.aggregate_id) if ev.aggregate_id else None,
        "actor_user_id": str(ev.actor_user_id) if ev.actor_user_id else None,
    }


def backoff(attempts: int) -> timedelta:
    return timedelta(minutes=2 ** min(max(attempts, 1), 8))


def _arm_retry(ev: Any, error: str) -> None:
    ev.attempts += 1
    ev.last_error = error[:2000]
    if ev.attempts >= MAX_ATTEMPTS:
        ev.status = "dead"
    else:
        ev.status = "pending"
        ev.next_attempt_at = datetime.now(UTC) + backoff(ev.attempts)


async def record_consumer_failure(event_id: str, consumer_name: str, error: str) -> None:
    """A consumer raised: re-arm the event with backoff (or dead-letter it) on the platform session."""
    from app.db.session import PlatformSessionLocal
    from app.models.platform import DomainEvent

    async with PlatformSessionLocal() as db:
        ev = (
            await db.execute(select(DomainEvent).where(DomainEvent.id == event_id).with_for_update())
        ).scalar_one_or_none()
        if ev is None:
            return
        _arm_retry(ev, f"{consumer_name}: {error}")
        await db.commit()
        log.warning(
            "outbox_consumer_failed",
            consumer=consumer_name,
            event_id=event_id,
            attempts=ev.attempts,
            status=ev.status,
            error=error[:200],
        )


# ---- consumer contract -----------------------------------------------------------------------------------------------


async def mark_consumed(db: Any, consumer_name: str, event_id: str) -> bool:
    """Idempotency guard: returns False when this consumer already handled the event."""
    res = await db.execute(
        text(
            "INSERT INTO event_consumptions (consumer, event_id) VALUES (:c, :e) "
            "ON CONFLICT (consumer, event_id) DO NOTHING RETURNING consumer"
        ),
        {"c": consumer_name, "e": event_id},
    )
    return res.first() is not None


async def already_consumed(db: Any, consumer_name: str, event_id: str) -> bool:
    row = await db.execute(
        text("SELECT 1 FROM event_consumptions WHERE consumer = :c AND event_id = :e"),
        {"c": consumer_name, "e": event_id},
    )
    return row.first() is not None


def consumer(name: str, events: list[str], queue: str = "scheduled") -> Callable[[ConsumerFn], Any]:
    """Declare an outbox consumer: ``@consumer("search.reindex", events=["student.*"]) async def fn(db, event)``."""

    def deco(fn: ConsumerFn) -> Any:
        @celery.task(name=name, queue=queue)
        def task(**event: Any) -> None:
            asyncio.run(_consume(name, fn, event))

        for e in events:
            subscribe(e, name)
        task.__consumer_events__ = list(events)  # type: ignore[attr-defined]
        task.__consumer_fn__ = fn  # type: ignore[attr-defined]  # in-process verification drives the body directly
        return task

    return deco


async def _consume(name: str, fn: ConsumerFn, event: dict[str, Any]) -> None:
    from app.db.session import PlatformSessionLocal, tenant_session

    event_id = event.get("event_id")
    structlog.contextvars.bind_contextvars(consumer=name, event_id=event_id, event_type=event.get("event_type"))
    try:
        async with PlatformSessionLocal() as pdb:
            if event_id and await already_consumed(pdb, name, event_id):
                log.info("outbox_consumer_skip_duplicate")
                return
        inst = event.get("institution_id")
        db = await tenant_session(inst) if inst else PlatformSessionLocal()
        try:
            await fn(db, event)
            if event_id:
                await mark_consumed(db, name, event_id)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - recorded on the event row, never re-raised into Celery retries
            await db.rollback()
            if event_id:
                await record_consumer_failure(event_id, name, str(exc))
            return
        finally:
            await db.close()
    finally:
        structlog.contextvars.unbind_contextvars("consumer", "event_id", "event_type")


# ---- built-in consumers used by the Phase 01 verification (step 5) ---------------------------------------------------


@consumer("outbox.test_ping", events=["test.ping"])
async def test_ping(db: Any, event: dict[str, Any]) -> None:
    """Consumer for ``test.ping`` events: logs the payload (one ``event_consumptions`` row per event)."""
    log.info("test_ping", payload=event.get("payload"))


@consumer("outbox.test_fail", events=["test.fail"])
async def test_fail(db: Any, event: dict[str, Any]) -> None:
    """Always-failing consumer: proves ``attempts`` increments and ``next_attempt_at`` is set (verification step 5)."""
    raise RuntimeError("test.fail consumer failed on purpose")
