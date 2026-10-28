"""Ops console, status page and internal ops reports — Prompts/44 §44.5 / §44.6.

State lives in ``platform_settings`` (platform session only):

* ring buffers (newest first, capped): ``ops.deploys`` (200), ``ops.backups_log`` (500), ``ops.restore_drills`` (50),
  ``ops.alert_events`` (1 000), ``ops.incidents`` (200), ``ops.capacity`` (400), ``ops.script_runs`` (200),
  ``ops.releases`` (100);
* summaries: ``ops.backups`` (``last_success_at`` per kind + status — read by the Phase 43 posture ``backups``
  control), ``ops.status_components`` (manual overrides), ``ops`` (configuration seeded by ``0044``).

Worker liveness: ``POST /internal/ops/heartbeat/{queue}`` and the in-process Celery signal set Redis
``worker:{queue}:heartbeat`` (TTL 120 s). Component states for ``/public/status`` are derived (probes, heartbeats,
Phase 38 provider outages, active alerts) unless a super admin overrides them; tenant names never appear.
Ops scripts (``rollover`` … ``reindex_search``) run as audited ``background_jobs``; ``tenant_restore``,
``key_rotation`` and ``archive_year`` need a second super admin's approval (four-eyes).
"""

from __future__ import annotations

import builtins
import os
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.audit import log_audit
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client
from app.services.hardening.common import HardeningBase

ROOT = Path(__file__).resolve().parents[4]
QUEUES = ("notifications", "emails", "documents", "reports", "integrations", "scheduled")
COMPONENTS = ("api", "web", "workers", "database", "redis", "storage", "payments", "sms", "whatsapp", "email", "push")
PROVIDER_COMPONENT = {"payments": "payments", "sms": "sms", "whatsapp": "whatsapp", "email": "email", "push": "push"}
STATES = ("operational", "degraded", "outage", "maintenance")
FOUR_EYES = ("tenant_restore", "key_rotation", "archive_year")
SCRIPTS = (
    "rollover",
    "close_term",
    "archive_year",
    "tenant_export",
    "tenant_restore",
    "key_rotation",
    "partitions",
    "cache_warm",
    "reindex_search",
)
RING = {
    "ops.deploys": 200,
    "ops.backups_log": 500,
    "ops.restore_drills": 50,
    "ops.alert_events": 1000,
    "ops.incidents": 200,
    "ops.capacity": 400,
    "ops.script_runs": 200,
    "ops.releases": 100,
}
PARTITIONED = (
    "domain_events",
    "webhook_deliveries",
    "audit_logs",
    "message_logs",
    "student_class_attendance",
    "vehicle_gps_logs",
)


def now() -> str:
    return datetime.now(UTC).isoformat()


class OpsService(HardeningBase):
    """Platform session; ``principal`` is a super admin / support agent (route dependencies decide)."""

    # ---- storage helpers --------------------------------------------------------------------------------------------
    async def ring(self, key: str) -> builtins.list[dict[str, Any]]:
        return list(await self.platform_value(key, None) or [])

    async def push(self, key: str, item: dict[str, Any]) -> dict[str, Any]:
        items = [item, *await self.ring(key)][: RING.get(key, 200)]
        await self.put_platform_value(key, items)
        return item

    async def replace(self, key: str, item_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        items = await self.ring(key)
        for it in items:
            if it.get("id") == item_id:
                it.update(patch)
                await self.put_platform_value(key, items)
                return it
        raise APIError(404, ErrorCode.NOT_FOUND, "Not found")

    async def _audit(self, action: str, new: dict[str, Any]) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="platform",
            action=f"ops_{action}",
            record_type="ops",
            record_id=None,
            new=new,
            request=self.request,
        )

    def writer(self) -> None:
        if not getattr(self.principal, "is_super_admin", False):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Super admin only (support agents read)")

    # ---- overview ---------------------------------------------------------------------------------------------------
    async def _scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return (await self.db.execute(text(sql), params or {})).scalar()
        except Exception:  # noqa: BLE001 - a missing table / permission degrades one card, never the page
            await self.db.rollback()
            return None

    async def queues(self) -> builtins.list[dict[str, Any]]:
        out = []
        for q in QUEUES:
            try:
                depth = int(await redis_client.llen(q))  # type: ignore[misc]
                beat = await redis_client.get(f"worker:{q}:heartbeat")
            except Exception:  # noqa: BLE001
                depth, beat = -1, None
            out.append({"name": q, "depth": depth, "worker_alive": beat is not None, "last_heartbeat": beat})
        return out

    async def outbox(self) -> dict[str, Any]:
        pending = await self._scalar("SELECT count(*) FROM domain_events WHERE status = 'pending'")
        oldest = await self._scalar(
            "SELECT EXTRACT(EPOCH FROM NOW() - min(created_at)) FROM domain_events WHERE status = 'pending'"
        )
        dead = await self._scalar("SELECT count(*) FROM domain_events WHERE status = 'dead'")
        return {"pending": pending or 0, "lag_s": round(float(oldest), 1) if oldest else 0.0, "dead": dead or 0}

    async def dlq(self) -> dict[str, Any]:
        return {
            "outbox": await self._scalar("SELECT count(*) FROM domain_events WHERE status = 'dead'") or 0,
            "webhooks": await self._scalar("SELECT count(*) FROM webhook_deliveries WHERE status = 'dead'") or 0,
            "notifications": await self._scalar("SELECT count(*) FROM message_logs WHERE status IN ('failed', 'dead')")
            or 0,
        }

    async def overview(self) -> dict[str, Any]:
        head = await self._scalar("SELECT version_num FROM alembic_version")
        conns = await self._scalar("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
        size = await self._scalar("SELECT pg_database_size(current_database())")
        try:
            info = await redis_client.info("memory")
            redis = {
                "used_mb": round(int(info.get("used_memory", 0)) / 1048576, 1),
                "maxmemory_mb": round(int(info.get("maxmemory", 0)) / 1048576, 1),
            }
        except Exception:  # noqa: BLE001
            redis = {"used_mb": None}  # type: ignore[dict-item]
        backups = dict(await self.platform_value("ops.backups", None) or {})
        last = backups.get("last_success_at")
        age = round((datetime.now(UTC) - datetime.fromisoformat(last)).total_seconds() / 60) if last else None
        drills = await self.ring("ops.restore_drills")
        deploys = await self.ring("ops.deploys")
        alerts = [a for a in await self.ring("ops.alert_events") if a.get("status") == "firing"]
        ro = (
            (
                await self.db.execute(
                    text(
                        "SELECT institution_id, reason, starts_at, ends_at FROM read_only_modes WHERE is_active AND (ends_at IS NULL OR ends_at > NOW()) "
                        "ORDER BY starts_at LIMIT 20"
                    )
                )
            )
            .mappings()
            .all()
        )
        return {
            "env": settings.APP_ENV,
            "version": os.environ.get("APP_VERSION", "dev"),
            "image_tags": {
                "api": os.environ.get("UNIVERSE_IMAGE", "local"),
                "web": os.environ.get("UNIVERSE_WEB_IMAGE", "local"),
            },
            "uptime_s": round(time.monotonic()),
            "last_deploy": deploys[0] if deploys else None,
            "migrations": {"head": head},
            "queues": await self.queues(),
            "outbox": await self.outbox(),
            "dlq": await self.dlq(),
            "db": {"connections": conns, "size_gb": round(int(size) / 1073741824, 2) if size else None},
            "redis": redis,
            "backups": {**backups, "age_min": age},
            "restore_drill": drills[0] if drills else None,
            "alerts_active": alerts[:50],
            "read_only": [dict(r) for r in ro],
        }

    # ---- deploys / backups / drills ---------------------------------------------------------------------------------
    async def deploy_report(self, body: dict[str, Any]) -> dict[str, Any]:
        rec = {
            "id": body.get("id") or uuid.uuid4().hex[:12],
            "env": body.get("env"),
            "image_tags": body.get("image_tags") or {},
            "sha": body.get("sha"),
            "started_at": body.get("started_at") or now(),
            "finished_at": body.get("finished_at"),
            "status": body.get("status", "succeeded"),
            "migrated_to": body.get("migrated_to"),
            "by": body.get("by"),
            "notes": body.get("notes") or [],
            "rollback_to": body.get("rollback_to"),
        }
        await self.push("ops.deploys", rec)
        from app.core import events

        kind = {"succeeded": "finished", "failed": "failed", "rolled_back": "rolled_back"}.get(
            str(rec["status"]), "started"
        )
        await events.emit(
            self.db,
            institution_id=None,
            event_type=f"ops.deploy_{kind}",
            payload=rec,
            aggregate_type="ops",
            aggregate_id=None,
        )
        return rec

    async def deploy_note(self, deploy_id: str, note: str) -> dict[str, Any]:
        self.writer()
        items = await self.ring("ops.deploys")
        for it in items:
            if it.get("id") == deploy_id:
                it.setdefault("notes", []).append({"at": now(), "by": str(self.principal.id), "note": note})
                await self.put_platform_value("ops.deploys", items)
                await self._audit("deploy_note", {"deploy": deploy_id})
                return it
        raise APIError(404, ErrorCode.NOT_FOUND, "Deploy not found")

    async def backup_report(self, body: dict[str, Any]) -> dict[str, Any]:
        rec = {
            "id": uuid.uuid4().hex[:12],
            "kind": body.get("kind", "full"),
            "started_at": body.get("started_at"),
            "finished_at": body.get("finished_at") or now(),
            "size_bytes": body.get("size_bytes"),
            "location": body.get("location"),
            "checksum": body.get("checksum"),
            "status": body.get("status", "succeeded"),
            "verify": body.get("verify"),
        }
        await self.push("ops.backups_log", rec)
        summary = dict(await self.platform_value("ops.backups", None) or {})
        if rec["status"] == "succeeded":
            summary["last_success_at"] = rec["finished_at"]
            summary[f"last_{rec['kind']}"] = rec["finished_at"]
            summary["status"] = "ok"
        else:
            summary["status"] = "failed"
            summary["last_failure_at"] = rec["finished_at"]
            from app.core.notifications.notify import notify_event

            await notify_event(
                self.db,
                None,
                "ops.backup_failed",
                audience={"user_ids": await self._oncall()},
                context={"kind": rec["kind"], "at": rec["finished_at"]},
            )
        await self.put_platform_value("ops.backups", summary)
        return rec

    async def _oncall(self) -> builtins.list[str]:
        rows = (
            await self.db.execute(
                text("SELECT id FROM users WHERE is_super_admin AND deleted_at IS NULL AND is_active")
            )
        ).all()
        return [str(r[0]) for r in rows]

    async def record_drill(self, body: dict[str, Any]) -> dict[str, Any]:
        targets = ((await self.platform_value("ops", None)) or {}).get("dr_targets") or {
            "rpo_minutes": 15,
            "rto_hours": 4,
        }
        rpo, rto = body.get("rpo_observed_min"), body.get("rto_observed_min")
        ok = (
            rpo is not None
            and rto is not None
            and float(rpo) <= targets["rpo_minutes"]
            and float(rto) <= targets["rto_hours"] * 60
        )
        rec = {
            "id": uuid.uuid4().hex[:12],
            "date": body.get("date") or now(),
            "source_backup": body.get("source_backup"),
            "target_env": body.get("target_env", "scratch"),
            "rpo_observed_min": rpo,
            "rto_observed_min": rto,
            "verified_checks": body.get("verified_checks") or [],
            "status": body.get("status") or ("passed" if ok else "failed"),
            "report_url": body.get("report_url"),
        }
        await self.push("ops.restore_drills", rec)
        from app.core.notifications.notify import notify_event

        await notify_event(
            self.db,
            None,
            "ops.restore_drill_result",
            audience={"user_ids": await self._oncall()},
            context={"status": rec["status"], "rpo": rpo, "rto": rto},
        )
        return rec

    # ---- alerts -----------------------------------------------------------------------------------------------------
    def rules(self) -> builtins.list[dict[str, Any]]:
        import yaml  # type: ignore[import-untyped]

        out: list[dict[str, Any]] = []
        for f in sorted((ROOT / "ops" / "alerts").glob("*.yml")):
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            for g in doc.get("groups", []):
                for r in g.get("rules", []):
                    out.append(
                        {
                            "group": g.get("name"),
                            "alert": r.get("alert"),
                            "expr": r.get("expr"),
                            "for": r.get("for"),
                            "severity": (r.get("labels") or {}).get("severity"),
                            "summary": (r.get("annotations") or {}).get("summary"),
                            "file": f.name,
                        }
                    )
        return out

    async def alert_events(self, payload: dict[str, Any]) -> int:
        """Alertmanager webhook (v4 payload) → ring; ``component`` label degrades the status page while firing."""
        n = 0
        for a in payload.get("alerts", []):
            labels = a.get("labels") or {}
            await self.push(
                "ops.alert_events",
                {
                    "id": a.get("fingerprint") or uuid.uuid4().hex[:12],
                    "rule": labels.get("alertname"),
                    "severity": labels.get("severity"),
                    "labels": labels,
                    "status": a.get("status", "firing"),
                    "fired_at": a.get("startsAt") or now(),
                    "resolved_at": a.get("endsAt") if a.get("status") == "resolved" else None,
                    "summary": (a.get("annotations") or {}).get("summary"),
                },
            )
            comp = labels.get("component")
            if comp in COMPONENTS:
                auto = dict(await self.platform_value("ops.status_auto", None) or {})
                auto[comp] = {
                    "state": "degraded" if a.get("status", "firing") == "firing" else "operational",
                    "since": now(),
                    "message": (a.get("annotations") or {}).get("summary"),
                }
                await self.put_platform_value("ops.status_auto", auto)
            n += 1
        return n

    async def alerts(self, active: bool | None = None) -> builtins.list[dict[str, Any]]:
        items = await self.ring("ops.alert_events")
        return [a for a in items if active is None or (a.get("status") == "firing") == active]

    async def test_alert(self, rule: str) -> dict[str, Any]:
        self.writer()
        known = {r["alert"] for r in self.rules()}
        if rule not in known:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown rule", {"rule": rule})
        await self.alert_events(
            {
                "alerts": [
                    {
                        "labels": {"alertname": rule, "severity": "test"},
                        "status": "resolved",
                        "annotations": {"summary": f"test fire of {rule}"},
                        "startsAt": now(),
                        "endsAt": now(),
                    }
                ]
            }
        )
        await self._audit("alert_test", {"rule": rule})
        return {"rule": rule, "recorded": True}

    # ---- status page ------------------------------------------------------------------------------------------------
    async def _probe(self) -> dict[str, dict[str, Any]]:
        comps: dict[str, dict[str, Any]] = {
            c: {"state": "operational", "since": None, "message": None} for c in COMPONENTS
        }
        try:
            await self.db.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            comps["database"]["state"] = "outage"
        try:
            await redis_client.ping()  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            comps["redis"]["state"] = "outage"
        try:
            alive = [await redis_client.get(f"worker:{q}:heartbeat") for q in QUEUES]
            if settings.is_production and not all(alive):
                comps["workers"]["state"] = "degraded"
        except Exception:  # noqa: BLE001
            pass
        rows = (await self.db.execute(text("SELECT key FROM platform_settings WHERE key LIKE 'outage:%'"))).all()
        for (key,) in rows:
            cap = key.split(":")[1] if key.count(":") >= 2 else ""
            if cap in PROVIDER_COMPONENT:
                comps[PROVIDER_COMPONENT[cap]] = {
                    "state": "degraded",
                    "since": None,
                    "message": "Provider outage detected",
                }
        for k, v in (await self.platform_value("ops.status_auto", None) or {}).items():
            if k in comps and v.get("state") != "operational":
                comps[k] = v
        for k, v in (await self.platform_value("ops.status_components", None) or {}).items():
            if k in comps and v.get("state"):
                comps[k] = v
        return comps

    async def public_status(self) -> dict[str, Any]:
        comps = await self._probe()
        incidents = [
            {k: i.get(k) for k in ("id", "title", "components", "state", "updates", "started_at", "resolved_at")}
            for i in await self.ring("ops.incidents")
            if i.get("state") != "resolved"
            or (i.get("resolved_at") and i["resolved_at"] > (datetime.now(UTC) - timedelta(days=14)).isoformat())
        ]
        maint = (
            (
                await self.db.execute(
                    text(
                        "SELECT reason, starts_at, ends_at FROM read_only_modes WHERE institution_id IS NULL AND is_active "
                        "AND (ends_at IS NULL OR ends_at > NOW()) ORDER BY starts_at LIMIT 10"
                    )
                )
            )
            .mappings()
            .all()
        )
        overall = (
            "outage"
            if any(c["state"] == "outage" for c in comps.values())
            else (
                "degraded" if any(c["state"] in ("degraded", "maintenance") for c in comps.values()) else "operational"
            )
        )
        await self._record_uptime(comps)
        return {
            "overall": overall,
            "components": [{"key": k, **v} for k, v in comps.items()],
            "incidents": incidents,
            "maintenance": [
                {"reason": m["reason"], "starts_at": m["starts_at"], "ends_at": m["ends_at"]} for m in maint
            ],
            "generated_at": now(),
        }

    async def _record_uptime(self, comps: dict[str, dict[str, Any]]) -> None:
        day = datetime.now(UTC).strftime("%Y%m%d")
        try:
            for k, v in comps.items():
                await redis_client.hincrby(f"uptime:{k}:{day}", "total", 1)  # type: ignore[misc]
                if v["state"] == "operational":
                    await redis_client.hincrby(f"uptime:{k}:{day}", "ok", 1)  # type: ignore[misc]
                await redis_client.expire(f"uptime:{k}:{day}", 100 * 86400)
        except Exception:  # noqa: BLE001
            pass

    async def history(self, component: str, days: int = 90) -> builtins.list[dict[str, Any]]:
        out = []
        for n in range(days):
            day = (datetime.now(UTC) - timedelta(days=n)).strftime("%Y%m%d")
            try:
                h = await redis_client.hgetall(f"uptime:{component}:{day}")  # type: ignore[misc]
            except Exception:  # noqa: BLE001
                h = {}
            total, ok = int(h.get("total", 0) or 0), int(h.get("ok", 0) or 0)
            out.append({"date": day, "uptime_pct": round(100 * ok / total, 2) if total else None})
        return out

    async def incident_open(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writer()
        comps = [c for c in body.get("components") or [] if c in COMPONENTS]
        inc = {
            "id": uuid.uuid4().hex[:12],
            "title": body["title"],
            "components": comps,
            "state": body.get("state", "investigating"),
            "updates": [{"at": now(), "state": body.get("state", "investigating"), "message": body.get("message", "")}],
            "started_at": now(),
            "resolved_at": None,
        }
        await self.push("ops.incidents", inc)
        await self._announce(f"Incident: {inc['title']}", body.get("message") or "We are investigating.", "incident")
        await self._audit("incident_open", {"id": inc["id"], "title": inc["title"]})
        return inc

    async def incident_update(
        self, incident_id: str, state: str, message: str, resolve: bool = False
    ) -> dict[str, Any]:
        self.writer()
        items = await self.ring("ops.incidents")
        for it in items:
            if it.get("id") == incident_id:
                st = "resolved" if resolve else state
                it["state"] = st
                it.setdefault("updates", []).append({"at": now(), "state": st, "message": message})
                if resolve:
                    it["resolved_at"] = now()
                await self.put_platform_value("ops.incidents", items)
                await self._audit(
                    "incident_resolve" if resolve else "incident_update", {"id": incident_id, "state": st}
                )
                if resolve:
                    await self._announce(f"Resolved: {it['title']}", message or "The incident is resolved.", "incident")
                return it
        raise APIError(404, ErrorCode.NOT_FOUND, "Incident not found")

    async def incidents(self) -> builtins.list[dict[str, Any]]:
        return await self.ring("ops.incidents")

    async def set_component(self, key: str, state: str | None, message: str | None) -> dict[str, Any]:
        self.writer()
        if key not in COMPONENTS or (state is not None and state not in STATES):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Unknown component or state",
                {"components": list(COMPONENTS), "states": list(STATES)},
            )
        overrides = dict(await self.platform_value("ops.status_components", None) or {})
        if state is None:
            overrides.pop(key, None)
        else:
            overrides[key] = {"state": state, "since": now(), "message": message}
        await self.put_platform_value("ops.status_components", overrides)
        await self._audit("status_component", {"key": key, "state": state})
        return {"key": key, **(overrides.get(key) or {"state": "auto"})}

    async def _announce(self, title: str, body: str, kind: str, audience_type: str = "roles") -> None:
        cfg = (await self.platform_value("ops", None)) or {}
        if kind == "incident" and not cfg.get("status_page", {}).get("announce_incidents", True):
            return
        from app.schemas.saas import AnnouncementAudience, AnnouncementIn
        from app.services.saas.announcement_service import AnnouncementService

        await AnnouncementService(self.db, self.principal, self.request).create(
            AnnouncementIn(
                title=title[:200],
                body=body or title,
                kind=kind,  # type: ignore[arg-type]
                audience=AnnouncementAudience(type="roles", values=["institution_admin"]),
                channels=["banner", "inapp"],
            ),
            system=True,
        )

    # ---- capacity / partitions --------------------------------------------------------------------------------------
    async def capacity_snapshot(self) -> dict[str, Any]:
        snap = {
            "date": datetime.now(UTC).date().isoformat(),
            "tenants": await self._scalar("SELECT count(*) FROM institutions WHERE deleted_at IS NULL") or 0,
            "students": await self._scalar("SELECT count(*) FROM students WHERE deleted_at IS NULL") or 0,
            "staff": await self._scalar("SELECT count(*) FROM staff") or 0,
            "db_size_gb": round(
                int(await self._scalar("SELECT pg_database_size(current_database())") or 0) / 1073741824, 3
            ),
            "queue_depth_peak": max([q["depth"] for q in await self.queues()] or [0]),
            "storage_gb": None,
        }
        await self.push("ops.capacity", snap)
        return snap

    async def capacity(self) -> dict[str, Any]:
        snaps = list(reversed(await self.ring("ops.capacity")))
        proj: dict[str, Any] = {}
        if len(snaps) >= 2:
            first, last = snaps[0], snaps[-1]
            days = max(1, (datetime.fromisoformat(last["date"]) - datetime.fromisoformat(first["date"])).days)
            for k in ("students", "db_size_gb"):
                rate = (float(last.get(k) or 0) - float(first.get(k) or 0)) / days
                proj[f"{k}_12m"] = round(float(last.get(k) or 0) + rate * 365, 2)
        recs: list[str] = []
        cfg = ((await self.platform_value("ops", None)) or {}).get("capacity") or {}
        if snaps and snaps[-1].get("queue_depth_peak", 0) > 1000:
            recs.append("Queue depth peaked above 1 000 — add a worker for the busiest queue or raise its concurrency")
        if snaps and (snaps[-1].get("db_size_gb") or 0) > 80:
            recs.append("Database above 80 GB — plan storage growth and review partition retention")
        conns = await self._scalar("SELECT count(*) FROM pg_stat_activity")
        if conns and cfg.get("pgbouncer_pool") and conns > 0.85 * int(cfg["pgbouncer_pool"]):
            recs.append("Connections above 85 % of the pgbouncer pool — increase pool size or add a replica")
        return {"snapshots": snaps[-120:], "projections": proj, "recommendations": recs}

    async def partitions(self) -> builtins.list[dict[str, Any]]:
        out = []
        nxt = (datetime.now(UTC).replace(day=1) + timedelta(days=32)).strftime("%Y_%m")
        for t in PARTITIONED:
            parts = [
                r[0]
                for r in (
                    await self.db.execute(
                        text(
                            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid JOIN pg_class p ON p.oid = i.inhparent "
                            "WHERE p.relname = :t ORDER BY c.relname"
                        ),
                        {"t": t},
                    )
                ).all()
            ]
            out.append(
                {
                    "table": t,
                    "partitions": parts,
                    "next_month_exists": any(nxt in p for p in parts),
                    "oldest": next((p for p in parts if re.search(r"\d{4}_\d{2}", p)), None),
                }
            )
        return out

    # ---- scripts (four-eyes) ----------------------------------------------------------------------------------------
    async def request_script(self, script: str, params: dict[str, Any]) -> dict[str, Any]:
        self.writer()
        if script not in SCRIPTS:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown script", {"allowed": list(SCRIPTS)})
        rec = {
            "id": uuid.uuid4().hex[:12],
            "script": script,
            "params": params,
            "requested_by": str(self.principal.id),
            "requested_at": now(),
            "status": "pending_approval" if script in FOUR_EYES else "queued",
            "job_id": None,
        }
        if rec["status"] == "queued":
            rec["job_id"] = await self._enqueue(rec)
        await self.push("ops.script_runs", rec)
        await self._audit("script_request", {"script": script, "status": rec["status"]})
        return rec

    async def approve_script(self, run_id: str) -> dict[str, Any]:
        self.writer()
        items = await self.ring("ops.script_runs")
        rec = next((r for r in items if r.get("id") == run_id), None)
        if rec is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Run not found")
        if rec["status"] != "pending_approval":
            raise APIError(409, ErrorCode.CONFLICT, f"Run is {rec['status']}")
        if rec["requested_by"] == str(self.principal.id):
            raise APIError(409, ErrorCode.CONFLICT, "A second super admin must approve", {"code": "FOUR_EYES"})
        rec.update({"status": "queued", "approved_by": str(self.principal.id), "approved_at": now()})
        rec["job_id"] = await self._enqueue(rec)
        await self.put_platform_value("ops.script_runs", items)
        await self._audit("script_approve", {"id": run_id, "script": rec["script"]})
        return rec

    async def _enqueue(self, rec: dict[str, Any]) -> str:
        from app.core.jobs import enqueue

        job = await enqueue(
            self.db,
            self.principal,
            "ops.script_run",
            {"run_id": rec["id"], "script": rec["script"], **rec["params"]},
            queue="scheduled",
        )
        return str(job.id)

    async def script_runs(self) -> builtins.list[dict[str, Any]]:
        return await self.ring("ops.script_runs")

    # ---- config / releases ------------------------------------------------------------------------------------------
    async def config(self) -> dict[str, Any]:
        safe = {
            k: getattr(settings, k)
            for k in (
                "APP_ENV",
                "DB_POOL_SIZE",
                "DB_MAX_OVERFLOW",
                "STORAGE_BACKEND",
                "MAX_UPLOAD_MB",
                "ACCESS_TOKEN_EXPIRE_MINUTES",
                "REFRESH_TOKEN_EXPIRE_DAYS",
                "ALLOWED_ORIGINS",
                "PLATFORM_HOSTS",
                "CSP_ENFORCE",
                "JWT_KID",
            )
            if hasattr(settings, k)
        }
        return {
            "settings": safe,
            "ops": await self.platform_value("ops", None),
            "features_env_defaults": await self.platform_value("features.env_defaults", None),
            "image_tags": {"api": os.environ.get("UNIVERSE_IMAGE"), "web": os.environ.get("UNIVERSE_WEB_IMAGE")},
            "migration_head": await self._scalar("SELECT version_num FROM alembic_version"),
        }

    async def releases(self) -> builtins.list[dict[str, Any]]:
        return await self.ring("ops.releases")

    async def add_release(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writer()
        rec = {
            "version": body["version"],
            "date": body.get("date") or now(),
            "notes_md": body.get("notes_md", ""),
            "sbom_url": body.get("sbom_url"),
            "images": body.get("images") or {},
            "deprecations": body.get("deprecations") or [],
            "announced_at": None,
        }
        await self.push("ops.releases", rec)
        await self._audit("release_add", {"version": rec["version"]})
        return rec

    async def release_from_ci(self, body: dict[str, Any]) -> dict[str, Any]:
        """``release.yml`` (X-Ops-Token): record the tagged release and announce it when the policy says so."""
        version = str(body["version"])
        items = await self.ring("ops.releases")
        if not any(r.get("version") == version for r in items):
            await self.push(
                "ops.releases",
                {
                    "version": version,
                    "date": now(),
                    "notes_md": body.get("notes_md", ""),
                    "sbom_url": body.get("sbom_url"),
                    "images": body.get("images") or {},
                    "deprecations": body.get("deprecations") or [],
                    "announced_at": None,
                },
            )
        policy = (((await self.platform_value("ops", None)) or {}).get("release") or {}).get(
            "announce_to_institutions", True
        )
        return (
            await self._announce_release(version)
            if policy and body.get("announce", True)
            else {"version": version, "announced_at": None}
        )

    async def announce_release(self, version: str) -> dict[str, Any]:
        self.writer()
        rec = await self._announce_release(version)
        await self._audit("release_announce", {"version": version})
        return rec

    async def _announce_release(self, version: str) -> dict[str, Any]:
        items = await self.ring("ops.releases")
        rec = next((r for r in items if r.get("version") == version), None)
        if rec is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Release not found")
        body = rec.get("notes_md") or f"SeptronUniverse {version} is live."
        if rec.get("deprecations"):
            days = (((await self.platform_value("ops", None)) or {}).get("release") or {}).get(
                "deprecation_notice_days", 90
            )
            body += (
                "\n\nDeprecations (sunset in " + str(days) + " days): " + ", ".join(str(d) for d in rec["deprecations"])
            )
        await self._announce(f"Release {version}", body, "release")
        rec["announced_at"] = now()
        await self.put_platform_value("ops.releases", items)
        return rec


def internal_token_ok(token: str | None) -> bool:
    import hmac

    return bool(settings.INTERNAL_OPS_TOKEN and token and hmac.compare_digest(token, settings.INTERNAL_OPS_TOKEN))
