"""Platform tasks — Prompts/01 §01.6/§01.7: Beat jobs, outbox consumers and the dev sleep job.

Beat (``app/tasks/beat.py``): ``jobs.cleanup`` (daily 03:00) · ``read_only.expire`` (1 min) · ``integrations.health``
(15 min) · ``partitions.ensure_next_month`` (monthly, 25th 02:00 — idempotent, also safe to run by hand).
Consumers: ``search.reindex`` ← ``student.*|staff.*|course.*|applicant.*`` (throttled matview refresh),
``webhooks.deliver`` ← ``*`` (records ``webhook_deliveries`` rows for tenants with matching active webhooks; Phase 41
delivers them). Every cross-tenant task runs on the platform session (BYPASSRLS) — see ``tasks/outbox.py``.
"""

import asyncio
import contextlib
import re
import time
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import select, text

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.outbox import consumer

log = structlog.get_logger()

# partitioned parents → range column (Database_Schema.sql §6, §12, §20, §23)
PARTITIONED_TABLES: dict[str, str] = {
    "domain_events": "created_at",
    "webhook_deliveries": "created_at",
    "audit_logs": "occurred_at",
    "message_logs": "created_at",
    "student_class_attendance": "session_date",
    "vehicle_gps_logs": "recorded_at",
}
SEARCH_REINDEX_LOCK = "search:reindex:lock"
SEARCH_REINDEX_PENDING = "search:reindex:pending"
SEARCH_REINDEX_INTERVAL = 60


# ---- Beat jobs -----------------------------------------------------------------------------------------------------


@celery.task(name="beat.jobs.cleanup", queue="scheduled")
def jobs_cleanup() -> dict[str, int]:
    return run_async(_jobs_cleanup())


async def _jobs_cleanup() -> dict[str, int]:
    from app.db.session import PlatformSessionLocal
    from app.services.job_service import JobService

    async with PlatformSessionLocal() as db:
        result = await JobService(db).cleanup()
        await db.commit()
    return result


@celery.task(name="beat.read_only.expire", queue="scheduled")
def read_only_expire() -> int:
    return run_async(_read_only_expire())


async def _read_only_expire() -> int:
    from app.db.session import PlatformSessionLocal
    from app.services.read_only_service import ReadOnlyService

    async with PlatformSessionLocal() as db:
        n = await ReadOnlyService(db).expire()
        await db.commit()
    return n


@celery.task(name="beat.integrations.health", queue="scheduled")
def integrations_health() -> dict[str, int]:
    return run_async(_integrations_health())


async def _integrations_health() -> dict[str, int]:
    """Health-check every configured integration connection (mock adapters until Phase 41 wires providers)."""
    from app.db.session import PlatformSessionLocal
    from app.integrations.registry import get_adapter
    from app.models.platform import IntegrationConnection, IntegrationHealthCheck

    checked = healthy = 0
    async with PlatformSessionLocal() as db:
        rows = (
            (await db.execute(select(IntegrationConnection).where(IntegrationConnection.status != "disabled")))
            .scalars()
            .all()
        )
        for conn in rows:
            t0 = time.perf_counter()
            try:
                adapter = get_adapter(conn.capability, conn.provider, **(conn.public_config or {}))
                ok, detail = await adapter.health()
            except Exception as exc:  # noqa: BLE001 - an adapter error is a failed check, not a task failure
                ok, detail = False, str(exc)[:500]
            latency = int((time.perf_counter() - t0) * 1000)
            db.add(
                IntegrationHealthCheck(
                    institution_id=conn.institution_id, connection_id=conn.id, ok=ok, latency_ms=latency, detail=detail
                )
            )
            conn.last_health_at = datetime.now(UTC)
            conn.last_error = None if ok else detail
            conn.status = "healthy" if ok else ("degraded" if conn.status == "healthy" else "failed")
            checked += 1
            healthy += int(ok)
        await db.commit()
    if checked:
        log.info("integrations_health", checked=checked, healthy=healthy)
    return {"checked": checked, "healthy": healthy}


@celery.task(name="beat.partitions.ensure_next_month", queue="scheduled")
def partitions_ensure_next_month() -> dict[str, list[str]]:
    return run_async(ensure_next_month())


def month_bounds(day: date) -> tuple[date, date]:
    lo = day.replace(day=1)
    hi = (lo.replace(year=lo.year + 1, month=1) if lo.month == 12 else lo.replace(month=lo.month + 1)).replace(day=1)
    return lo, hi


def partition_name(table: str, lo: date) -> str:
    return f"{table}_y{lo.year:04d}m{lo.month:02d}"


_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _ident(value: str) -> str:
    """Identifiers come from ``PARTITIONED_TABLES`` / ``partition_name`` only; refuse anything else defensively."""
    if not _IDENT.match(value):
        raise ValueError(f"unsafe identifier {value!r}")
    return value


def partition_statements(table: str, column: str, name: str, lo: date, hi: date) -> list[str]:
    """DDL/DML for one monthly partition. DDL cannot take bind parameters, so identifiers are validated by ``_ident``
    and the bounds are ISO dates rendered from ``date`` objects (never user input)."""
    table, column, name = _ident(table), _ident(column), _ident(name)
    default, tmp = _ident(f"{table}_default"), _ident(f"tmp_{name}")
    lo_s, hi_s = lo.isoformat(), hi.isoformat()
    window = f"{column} >= '{lo_s}' AND {column} < '{hi_s}'"
    # nosec markers: identifiers validated above, bounds are generated dates (see docstring)
    return [
        f"CREATE TEMP TABLE {tmp} ON COMMIT DROP AS SELECT * FROM {default} WHERE {window}",  # nosec B608
        f"DELETE FROM {default} WHERE {window}",  # nosec B608
        f"CREATE TABLE {name} PARTITION OF {table} FOR VALUES FROM ('{lo_s}') TO ('{hi_s}')",
        # moved rows keep their values verbatim: row triggers (e.g. the audit hash chain, which would recompute
        # prev_hash/hash) stay off for the copy — DISABLE TRIGGER on the parent recurses to the partitions
        f"ALTER TABLE {table} DISABLE TRIGGER USER",
        f"INSERT INTO {table} SELECT * FROM {tmp}",  # nosec B608
        f"ALTER TABLE {table} ENABLE TRIGGER USER",
    ]


async def ensure_next_month(today: date | None = None) -> dict[str, list[str]]:
    """Create the current and next month's partitions for every partitioned table (idempotent).

    Rows that already sit in the default partition for that month are moved into the new partition inside the same
    transaction (PostgreSQL refuses to attach a range that the default partition still holds rows for).
    """
    from app.db.session import PlatformSessionLocal

    today = today or datetime.now(UTC).date()
    this_lo, this_hi = month_bounds(today)
    next_lo, next_hi = month_bounds(this_hi)
    created: list[str] = []
    skipped: list[str] = []
    async with PlatformSessionLocal() as db:
        for table, column in PARTITIONED_TABLES.items():
            exists = (await db.execute(text("SELECT to_regclass(:t)"), {"t": table})).scalar_one()
            if exists is None:
                skipped.append(f"{table} (missing)")
                continue
            for lo, hi in ((this_lo, this_hi), (next_lo, next_hi)):
                name = partition_name(table, lo)
                if (await db.execute(text("SELECT to_regclass(:t)"), {"t": name})).scalar_one() is not None:
                    skipped.append(name)
                    continue
                try:
                    async with db.begin_nested():  # one failing table must not block the others
                        for stmt in partition_statements(table, column, name, lo, hi):
                            await db.execute(text(stmt))
                    created.append(name)
                except Exception as exc:  # noqa: BLE001
                    skipped.append(f"{name} (error: {str(exc)[:120]})")
                    log.warning("partition_create_failed", partition=name, error=str(exc)[:500])
        await db.commit()
    log.info("partitions_ensure_next_month", created=created, skipped=len(skipped))
    return {"created": created, "skipped": skipped}


# ---- outbox consumers ----------------------------------------------------------------------------------------------


@consumer("search.reindex", events=["student.*", "staff.*", "course.*", "applicant.*", "department.*"])
async def search_reindex(db: Any, event: dict[str, Any]) -> None:
    """Refresh ``search_documents`` at most once per minute; a burst of events collapses into one delayed refresh."""
    await schedule_search_refresh()


async def schedule_search_refresh(force: bool = False) -> bool:
    from app.db.session import redis_client

    acquired = force
    if not force:
        with contextlib.suppress(Exception):
            acquired = bool(await redis_client.set(SEARCH_REINDEX_LOCK, "1", nx=True, ex=SEARCH_REINDEX_INTERVAL))
    if not acquired:
        with contextlib.suppress(Exception):
            if await redis_client.set(SEARCH_REINDEX_PENDING, "1", nx=True, ex=SEARCH_REINDEX_INTERVAL * 2):
                celery.send_task("search.refresh", countdown=SEARCH_REINDEX_INTERVAL, queue="scheduled")
        return False
    await refresh_search_documents()
    return True


@celery.task(name="search.refresh", queue="scheduled")
def search_refresh() -> None:
    """Delayed refresh scheduled by a throttled ``search.reindex``."""
    run_async(_search_refresh_pending())


async def _search_refresh_pending() -> None:
    from app.db.session import redis_client

    with contextlib.suppress(Exception):
        await redis_client.delete(SEARCH_REINDEX_PENDING)
        await redis_client.set(SEARCH_REINDEX_LOCK, "1", ex=SEARCH_REINDEX_INTERVAL)
    await refresh_search_documents()


async def refresh_search_documents() -> None:
    """``REFRESH MATERIALIZED VIEW CONCURRENTLY`` on the platform session (the matview owner, BYPASSRLS)."""
    from app.db.session import PlatformSessionLocal
    from app.repositories.platform_repository import SearchRepository

    async with PlatformSessionLocal() as db:
        await SearchRepository(db).refresh()
        await db.commit()
    log.info("search_documents_refreshed")


@consumer("webhooks.deliver", events=["*"], queue="integrations")
async def webhooks_deliver(db: Any, event: dict[str, Any]) -> None:
    """Record a ``webhook_deliveries`` row for every active webhook of the tenant subscribed to the event type."""
    from app.models.platform import Webhook, WebhookDelivery

    inst = event.get("institution_id")
    if not inst:
        return  # platform events are not delivered to tenant webhooks
    hooks = (
        (await db.execute(select(Webhook).where(Webhook.institution_id == inst, Webhook.is_active.is_(True))))
        .scalars()
        .all()
    )
    event_type = str(event.get("event_type"))
    prefix = event_type.split(".")[0] + ".*"
    for hook in hooks:
        wanted = set(hook.events or [])
        if wanted and event_type not in wanted and prefix not in wanted and "*" not in wanted:
            continue
        db.add(
            WebhookDelivery(
                institution_id=hook.institution_id,
                webhook_id=hook.id,
                event_id=event["event_id"],
                event_type=event_type,
                status="pending",
            )
        )


# ---- dev-only sleep job (Prompts/01 §01.11 step 7) -------------------------------------------------------------------


@celery.task(name="jobs.sleep", queue="reports")
@job("sleep", queue="reports")
async def sleep_job(ctx: JobContext, db: Any, seconds: int = 5, **_: Any) -> dict[str, Any]:
    """Progress every second for ``seconds`` seconds; honours cancellation between ticks."""
    seconds = max(1, min(int(seconds), 300))
    for i in range(seconds):
        await asyncio.sleep(1)
        await ctx.progress(db, int((i + 1) * 100 / seconds), f"slept {i + 1}/{seconds}s")
    return {"slept": seconds}
