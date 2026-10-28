"""Custom Prometheus gauges and the ``/metrics`` guard — Prompts/44 §44.6 observability 1.

``/metrics`` requires ``Authorization: Bearer <METRICS_TOKEN>`` when the token is configured (always in production;
the scrape network ACL is the second layer). Gauges are refreshed at scrape time (cheap aggregate queries, ≤ every
15 s): ``outbox_pending``, ``outbox_lag_seconds``, ``dlq_size{kind}``, ``jobs_running{type}``,
``webhook_failure_ratio``, ``active_sessions``, ``tenants_read_only``, ``queue_depth{queue}``,
``worker_alive{queue}``, ``backup_age_minutes``, ``restore_drill_last_success_timestamp``. Celery workers publish ``worker:{queue}:heartbeat`` (TTL 120 s)
from a ``heartbeat_sent`` / beat-independent timer started on ``worker_ready``.
"""

import time
from typing import Any

from prometheus_client import Gauge
from sqlalchemy import text

OUTBOX_PENDING = Gauge("outbox_pending", "Domain events waiting for the relay")
OUTBOX_LAG = Gauge("outbox_lag_seconds", "Age of the oldest pending domain event")
DLQ = Gauge("dlq_size", "Dead letters by kind", ["kind"])
JOBS_RUNNING = Gauge("jobs_running", "Background jobs running by type", ["type"])
WEBHOOK_FAIL = Gauge("webhook_failure_ratio", "Failed / total webhook deliveries in the last hour")
SESSIONS = Gauge("active_sessions", "Live user sessions")
READ_ONLY = Gauge("tenants_read_only", "Institutions in an active read-only window")
QUEUE_DEPTH = Gauge("queue_depth", "Celery queue depth", ["queue"])
WORKER_ALIVE = Gauge("worker_alive", "Worker heartbeat present (1) or missing (0)", ["queue"])
BACKUP_AGE = Gauge("backup_age_minutes", "Minutes since the last successful backup")
DRILL_TS = Gauge("restore_drill_last_success_timestamp", "Unix time of the last passed restore drill")
QUEUES = ("notifications", "emails", "documents", "reports", "integrations", "scheduled")
_last = 0.0


async def refresh() -> None:
    global _last  # noqa: PLW0603 - module-level throttle
    if time.monotonic() - _last < 15:
        return
    _last = time.monotonic()
    from datetime import UTC, datetime

    from app.db.session import PlatformSessionLocal, redis_client

    async with PlatformSessionLocal() as db:

        async def one(sql: str) -> Any:
            try:
                return (await db.execute(text(sql))).scalar()
            except Exception:  # noqa: BLE001 - a missing table never breaks the scrape
                await db.rollback()
                return None

        OUTBOX_PENDING.set(await one("SELECT count(*) FROM domain_events WHERE status = 'pending'") or 0)
        OUTBOX_LAG.set(
            await one(
                "SELECT coalesce(EXTRACT(EPOCH FROM NOW() - min(created_at)), 0) FROM domain_events WHERE status = 'pending'"
            )
            or 0
        )
        DLQ.labels("outbox").set(await one("SELECT count(*) FROM domain_events WHERE status = 'dead'") or 0)
        DLQ.labels("webhooks").set(await one("SELECT count(*) FROM webhook_deliveries WHERE status = 'dead'") or 0)
        DLQ.labels("notifications").set(
            await one("SELECT count(*) FROM message_logs WHERE status IN ('failed', 'dead')") or 0
        )
        ratio = await one(
            "SELECT coalesce(avg(CASE WHEN status IN ('failed', 'dead') THEN 1.0 ELSE 0 END), 0) FROM webhook_deliveries "
            "WHERE created_at > NOW() - INTERVAL '1 hour'"
        )
        WEBHOOK_FAIL.set(float(ratio or 0))
        SESSIONS.set(
            await one("SELECT count(*) FROM user_sessions WHERE revoked_at IS NULL AND expires_at > NOW()") or 0
        )
        READ_ONLY.set(
            await one(
                "SELECT count(DISTINCT institution_id) FROM read_only_modes WHERE is_active AND starts_at <= NOW() AND (ends_at IS NULL OR ends_at > NOW())"
            )
            or 0
        )
        try:
            rows = (
                await db.execute(
                    text("SELECT job_type, count(*) FROM background_jobs WHERE status = 'running' GROUP BY 1")
                )
            ).all()
            for jt, n in rows:
                JOBS_RUNNING.labels(jt).set(n)
        except Exception:  # noqa: BLE001
            await db.rollback()
        backups = await one("SELECT value ->> 'last_success_at' FROM platform_settings WHERE key = 'ops.backups'")
        if backups:
            BACKUP_AGE.set((datetime.now(UTC) - datetime.fromisoformat(str(backups))).total_seconds() / 60)
        drill = await one(
            "SELECT d ->> 'date' FROM platform_settings, jsonb_array_elements(value) d WHERE key = 'ops.restore_drills' "
            "AND d ->> 'status' = 'passed' ORDER BY d ->> 'date' DESC LIMIT 1"
        )
        if drill:
            DRILL_TS.set(datetime.fromisoformat(str(drill)).timestamp())
    for q in QUEUES:
        try:
            QUEUE_DEPTH.labels(q).set(int(await redis_client.llen(q)))  # type: ignore[misc]
            WORKER_ALIVE.labels(q).set(1 if await redis_client.get(f"worker:{q}:heartbeat") else 0)
        except Exception:  # noqa: BLE001
            pass
