"""Tasks of Phase 44 — Prompts/44 §44.7 (operations).

Job ``ops.script_run`` runs one of the ops scripts (``rollover`` · ``close_term`` · ``archive_year`` · ``tenant_export`` ·
``tenant_restore`` · ``key_rotation`` · ``partitions`` · ``cache_warm`` · ``reindex_search``) — four-eyes runs are only
enqueued after approval (``OpsService.approve_script``); the run record in ``ops.script_runs`` gets the result.
Beat (UTC): ``ops.capacity_snapshot_daily`` (23:30 = 05:00 IST), ``ops.backup_age_check`` (every 30 min — alert when
the last successful backup is older than 6 h), ``ops.status_probe`` (every minute — uptime samples),
``ops.worker_heartbeat_check`` (every minute — alert event when a production queue lost its worker),
``ops.cert_expiry_check`` (daily — custom-domain certificates < 14 days, from Phase 40 ``institution_domains``).
"""

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import text

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.integrations import _platform

log = structlog.get_logger()
BACKEND = Path(__file__).resolve().parents[2]
SCRIPT_CMDS = {
    "rollover": ["scripts/ops/rollover_academic_year.py"],
    "close_term": ["scripts/ops/close_term.py"],
    "archive_year": ["scripts/ops/archive_year.py"],
    "tenant_export": ["scripts/ops/tenant_export.py"],
    "tenant_restore": ["scripts/ops/tenant_restore.py"],
    "key_rotation": ["scripts/ops/key_rotation.py"],
    "reindex_search": ["scripts/ops/reindex_search.py"],
}


class _Platform:
    is_super_admin = True
    roles = ["super_admin"]
    scopes: list[Any] = []
    institution_id = None
    id = None

    def has(self, module: str, action: str) -> bool:
        return True


async def _update_run(db: Any, run_id: str, patch: dict[str, Any]) -> None:
    from app.services.ops.ops_service import OpsService

    svc = OpsService(db, _Platform())
    items = await svc.ring("ops.script_runs")
    for it in items:
        if it.get("id") == run_id:
            it.update(patch)
    await svc.put_platform_value("ops.script_runs", items)


@celery.task(name="jobs.ops.script_run", queue="scheduled")
@job("ops.script_run", queue="scheduled")
async def script_run(ctx: JobContext, db: Any, run_id: str, script: str, **params: Any) -> dict[str, Any]:
    started = datetime.now(UTC)
    if script == "partitions":
        from app.tasks.platform import ensure_next_month

        out: dict[str, Any] = {"created": await ensure_next_month()}
        ok = True
    elif script == "cache_warm":
        from app.db.session import redis_client

        keys = 0
        async for k in redis_client.scan_iter(match="site_ver:*"):
            keys += 1
            await redis_client.incr(k)  # bump the SSR page-cache version → pages re-render on next hit
        out, ok = {"site_versions_bumped": keys}, True
    else:
        args = [
            sys.executable,
            *SCRIPT_CMDS[script],
            *(f"--{k.replace('_', '-')}={v}" for k, v in params.items() if v is not None),
        ]
        p = subprocess.run(args, cwd=BACKEND, capture_output=True, text=True, timeout=3600, check=False)  # noqa: S603
        out, ok = {"exit": p.returncode, "tail": (p.stdout + p.stderr)[-3000:]}, p.returncode == 0
    patch = {
        "status": "succeeded" if ok else "failed",
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_s": round((datetime.now(UTC) - started).total_seconds(), 1),
        "result": out,
    }
    await _update_run(db, run_id, patch)
    from app.core import events

    await events.emit(
        db,
        institution_id=None,
        event_type="ops.script_run",
        payload={"run_id": run_id, "script": script, "ok": ok},
        aggregate_type="ops",
        aggregate_id=None,
        actor_user_id=ctx.requested_by,
    )
    return patch


@celery.task(name="beat.ops.capacity_snapshot_daily", queue="scheduled")
def capacity_snapshot_daily() -> dict[str, Any]:
    async def fn(db: Any) -> dict[str, Any]:
        from app.services.ops.ops_service import OpsService

        return await OpsService(db, _Platform()).capacity_snapshot()

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.ops.backup_age_check", queue="scheduled")
def backup_age_check() -> dict[str, Any]:
    async def fn(db: Any) -> dict[str, Any]:
        from app.services.ops.ops_service import OpsService

        svc = OpsService(db, _Platform())
        summary = dict(await svc.platform_value("ops.backups", None) or {})
        last = summary.get("last_success_at")
        age = (datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds() / 60 if last else None
        stale = age is None or age > 360
        from app.core.config import settings

        if stale and settings.is_production:
            await svc.alert_events(
                {
                    "alerts": [
                        {
                            "labels": {"alertname": "BackupTooOld", "severity": "critical", "component": "database"},
                            "status": "firing",
                            "annotations": {"summary": f"Last successful backup {last or 'never'}"},
                        }
                    ]
                }
            )
        return {"age_min": age, "stale": stale}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.ops.status_probe", queue="scheduled")
def status_probe() -> dict[str, Any]:
    async def fn(db: Any) -> dict[str, Any]:
        from app.services.ops.ops_service import OpsService

        s = await OpsService(db, None).public_status()
        return {"overall": s["overall"]}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.ops.worker_heartbeat_check", queue="scheduled")
def worker_heartbeat_check() -> dict[str, Any]:
    async def fn(db: Any) -> dict[str, Any]:
        from app.core.config import settings
        from app.db.session import redis_client
        from app.services.ops.ops_service import QUEUES, OpsService

        missing = [q for q in QUEUES if not await redis_client.get(f"worker:{q}:heartbeat")]
        if missing and settings.is_production:
            await OpsService(db, _Platform()).alert_events(
                {
                    "alerts": [
                        {
                            "labels": {
                                "alertname": "WorkerHeartbeatMissing",
                                "severity": "critical",
                                "component": "workers",
                                "queues": ",".join(missing),
                            },
                            "status": "firing",
                            "annotations": {"summary": f"No worker heartbeat for {', '.join(missing)}"},
                        }
                    ]
                }
            )
        return {"missing": missing}

    return run_async(_platform(fn))  # type: ignore[no-any-return]


@celery.task(name="beat.ops.cert_expiry_check", queue="scheduled")
def cert_expiry_check() -> dict[str, Any]:
    """Custom-domain certificates reported by the edge (Phase 40 ``ssl-status`` callback, ``website_meta domain:<id>``)."""

    async def fn(db: Any) -> dict[str, Any]:
        rows = (
            await db.execute(
                text(
                    "SELECT key, value FROM institution_settings WHERE category = 'website_meta' AND key LIKE 'domain:%'"
                )
            )
        ).all()
        soon = []
        limit = datetime.now(UTC) + timedelta(days=14)
        for key, value in rows:
            exp = (value or {}).get("ssl_expires_at") if isinstance(value, dict) else None
            if exp and datetime.fromisoformat(str(exp)) < limit:
                soon.append({"domain": key.split(":", 1)[1], "expires": exp})
        if soon:
            from app.services.ops.ops_service import OpsService

            await OpsService(db, _Platform()).alert_events(
                {
                    "alerts": [
                        {
                            "labels": {
                                "alertname": "CertificateExpiringSoon",
                                "severity": "warning",
                                "component": "web",
                            },
                            "status": "firing",
                            "annotations": {"summary": f"{len(soon)} certificate(s) expire within 14 days"},
                        }
                    ]
                }
            )
        return {"expiring": soon}

    return run_async(_platform(fn))  # type: ignore[no-any-return]
