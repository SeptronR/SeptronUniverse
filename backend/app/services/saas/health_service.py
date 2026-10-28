"""Integration health across tenants — Prompts/38 §38.6 ``health_service`` (platform view).

Business rules
1. Latest ``integration_health_checks`` row per connection across tenants (Phase 01 Beat + Phase 24 probes write
   them); ``failing_since`` = the start of the current run of failed checks.
2. **Outages**: grouped by capability × provider, a provider whose connections fail on ≥ 50 % of ≥ 2 tenants is an
   outage → ``integration.outage_detected`` (once; state in ``platform_settings['outage:<capability>:<provider>']``),
   an ``incident`` platform announcement to the affected tenants and Redis ``outage:{institution}`` read by the
   ``/auth/me`` banner; recovery → ``integration.outage_cleared`` and the banner is removed (Beat
   ``platform.health_rollup`` every 5 minutes; Phase 44 status page reads the same state).
3. ``retry`` enqueues a probe of the chosen connections (``saas.health_probe``); ``disable`` sets the connection
   ``disabled`` (tenant integration admins notified; Phase 41 shows it) — super admin; both audited.
4. Dead letters: outbox events with failed consumers / exhausted attempts and webhook deliveries in ``failed`` per
   tenant (Phase 41 retry UI links).
"""

import contextlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from app.enums.saas import OUTAGE_FAILING_SHARE
from app.models.platform import IntegrationConnection
from app.schemas.saas import (
    AnnouncementAudience,
    AnnouncementIn,
    ConnectionDisable,
    HealthRetryRequest,
    HealthRow,
    OutageOut,
)
from app.services.saas.common import PlatformBase, conflict, not_found, now_utc


class HealthService(PlatformBase):
    async def overview(
        self, capability: str | None = None, provider: str | None = None, status: str | None = None
    ) -> list[HealthRow]:
        self.require_platform("platform", "view")
        where, binds = ["TRUE"], {}
        if capability:
            where.append("c.capability = :cap")
            binds["cap"] = capability
        if provider:
            where.append("c.provider = :prov")
            binds["prov"] = provider
        if status:
            where.append("c.status = :st")
            binds["st"] = status
        rows = (
            (
                await self.db.execute(
                    text(
                        f"""
                    SELECT c.id, c.institution_id, c.capability, c.provider, c.label, c.status, c.last_health_at, c.last_error,
                           h.latency_ms,
                           (SELECT min(x.checked_at) FROM integration_health_checks x WHERE x.connection_id = c.id AND NOT x.ok
                              AND x.checked_at > COALESCE((SELECT max(y.checked_at) FROM integration_health_checks y
                                                            WHERE y.connection_id = c.id AND y.ok), 'epoch')) AS failing_since
                    FROM integration_connections c
                    LEFT JOIN LATERAL (SELECT latency_ms FROM integration_health_checks h WHERE h.connection_id = c.id
                                       ORDER BY h.checked_at DESC LIMIT 1) h ON TRUE
                    WHERE {" AND ".join(where)}
                    ORDER BY c.capability, c.provider
                    """  # noqa: S608 - static fragments; values are bound
                    ),
                    binds,
                )
            )
            .mappings()
            .all()
        )
        insts = await self.institution_refs([r["institution_id"] for r in rows])
        return [
            HealthRow(
                connection_id=r["id"],
                institution=insts.get(r["institution_id"], {"id": str(r["institution_id"])}),
                capability=r["capability"],
                provider=r["provider"],
                label=r["label"],
                status=r["status"],
                last_health_at=r["last_health_at"],
                last_error=r["last_error"],
                failing_since=r["failing_since"],
                latency_ms=r["latency_ms"],
            )
            for r in rows
        ]

    async def history(self, connection_id: uuid.UUID, limit: int = 200) -> list[dict[str, Any]]:
        self.require_platform("platform", "view")
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT checked_at, ok, latency_ms, detail FROM integration_health_checks WHERE connection_id = :c ORDER BY checked_at DESC LIMIT :n"
                    ),
                    {"c": connection_id, "n": limit},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def compute_outages(self) -> list[OutageOut]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT capability, provider, institution_id, bool_or(status = 'failed') AS failing, min(last_health_at) AS since "
                    "FROM integration_connections WHERE status <> 'disabled' GROUP BY capability, provider, institution_id"
                )
            )
        ).all()
        groups: dict[tuple[str, str], list[tuple[uuid.UUID, bool, datetime | None]]] = {}
        for cap, prov, inst, failing, since in rows:
            groups.setdefault((cap, prov), []).append((inst, bool(failing), since))
        out: list[OutageOut] = []
        for (cap, prov), members in groups.items():
            failing = [m for m in members if m[1]]
            share = len(failing) / len(members) if members else 0
            if len(members) >= 2 and len(failing) >= 2 and share >= OUTAGE_FAILING_SHARE:
                insts = await self.institution_refs([m[0] for m in failing])
                out.append(
                    OutageOut(
                        capability=cap,
                        provider=prov,
                        failing=len(failing),
                        total=len(members),
                        share=round(share, 2),
                        institutions=[insts.get(m[0], {"id": str(m[0])}) for m in failing],
                        since=min((m[2] for m in failing if m[2]), default=None),
                    )
                )
        return out

    async def outages(self) -> list[OutageOut]:
        self.require_platform("platform", "view")
        return await self.compute_outages()

    async def rollup(self) -> dict[str, int]:
        """Beat ``platform.health_rollup``: detect / clear provider-wide outages and refresh the tenant banners."""
        from app.db.session import redis_client

        current = {f"{o.capability}:{o.provider}": o for o in await self.compute_outages()}
        known = await self.plist("outage:")
        detected = cleared = 0
        affected: dict[str, list[dict[str, Any]]] = {}
        for key, o in current.items():
            for inst in o.institutions:
                affected.setdefault(inst["id"], []).append(
                    {"capability": o.capability, "provider": o.provider, "since": o.since}
                )
            if key not in known or not (known[key] or {}).get("active"):
                detected += 1
                await self.pput(
                    f"outage:{key}",
                    {"active": True, "since": now_utc().isoformat(), "failing": o.failing, "total": o.total},
                )
                await self.emit(
                    "integration.outage_detected",
                    {"capability": o.capability, "provider": o.provider, "failing": o.failing, "total": o.total},
                    aggregate_type="integration_outage",
                )
                from app.services.saas.announcement_service import AnnouncementService

                await AnnouncementService(self.db, self.principal).create(
                    AnnouncementIn(
                        title=f"{o.provider} {o.capability} outage",
                        body=f"{o.provider} ({o.capability}) is failing for several institutions. Messages / requests through it may be delayed; we are monitoring.",
                        audience=AnnouncementAudience(type="institution_ids", values=[i["id"] for i in o.institutions]),
                        channels=["banner"],
                        kind="incident",
                    ),
                    system=True,
                )
                await self.notify_platform(
                    "platform.outage_detected",
                    {"provider": o.provider, "capability": o.capability, "failing": o.failing, "total": o.total},
                )
        for key, state in known.items():
            if (state or {}).get("active") and key not in current:
                cleared += 1
                await self.pput(
                    f"outage:{key}", {**(state or {}), "active": False, "cleared_at": now_utc().isoformat()}
                )
                cap, _, prov = key.partition(":")
                await self.emit(
                    "integration.outage_cleared",
                    {"capability": cap, "provider": prov},
                    aggregate_type="integration_outage",
                )
        with contextlib.suppress(Exception):
            for k in await redis_client.keys("outage:*"):
                if k.split(":", 1)[1] not in affected:
                    await redis_client.delete(k)
            for inst_id, items in affected.items():
                await redis_client.set(f"outage:{inst_id}", json.dumps(items, default=str), ex=900)
        return {"outages": len(current), "detected": detected, "cleared": cleared}

    async def retry(self, body: HealthRetryRequest) -> dict[str, Any]:
        self.require_platform("platform", "view")
        from app.core.jobs import send_after_commit

        ids = [str(i) for i in body.connection_ids]
        send_after_commit(self.db, "saas.health_probe", [ids], "integrations", str(uuid.uuid4()))
        rows = (
            await self.db.execute(
                select(IntegrationConnection.id, IntegrationConnection.institution_id).where(
                    IntegrationConnection.id.in_(body.connection_ids)
                )
            )
        ).all()
        for cid, inst in rows:
            await self.audit("health_retry", "integration_connection", cid, {"queued": True}, institution_id=inst)
        return {"queued": len(rows)}

    async def disable(self, connection_id: uuid.UUID, body: ConnectionDisable) -> HealthRow:
        self.require_super("Disabling a tenant connection")
        conn = (
            await self.db.execute(
                select(IntegrationConnection).where(IntegrationConnection.id == connection_id).with_for_update()
            )
        ).scalar_one_or_none()
        if conn is None:
            raise not_found("Connection")
        if conn.status == "disabled":
            raise conflict("The connection is already disabled")
        old = conn.status
        conn.status = "disabled"
        conn.last_error = f"Disabled by the platform: {body.reason}"
        await self.db.flush()
        await self.audit(
            "connection_disable",
            "integration_connection",
            conn.id,
            {"reason": body.reason, "capability": conn.capability, "provider": conn.provider},
            old={"status": old},
            institution_id=conn.institution_id,
        )
        await self.emit(
            "integrations.connection_disabled",
            {"connection_id": str(conn.id), "reason": body.reason},
            institution_id=conn.institution_id,
            aggregate_type="integration_connection",
            aggregate_id=conn.id,
        )
        await self.notify(
            "platform.connection_disabled",
            conn.institution_id,
            {"roles": ["integration_admin", "institution_admin"]},
            {"capability": conn.capability, "provider": conn.provider, "reason": body.reason},
            ["in_app", "email"],
        )
        rows = await self.overview(capability=conn.capability, provider=conn.provider)
        return next(r for r in rows if r.connection_id == conn.id)

    async def dead_letters(self) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT institution_id, count(*) FROM domain_events WHERE status IN ('failed','dead') "
                    "AND created_at > NOW() - INTERVAL '30 days' GROUP BY institution_id"
                )
            )
        ).all()
        hooks = (
            await self.db.execute(
                text(
                    "SELECT institution_id, count(*) FROM webhook_deliveries WHERE status IN ('failed','dead') "
                    "AND created_at > NOW() - INTERVAL '30 days' GROUP BY institution_id"
                )
            )
        ).all()
        insts = await self.institution_refs([r[0] for r in rows] + [r[0] for r in hooks])
        per: dict[str, dict[str, Any]] = {}
        for iid, n in rows:
            per.setdefault(str(iid), {"institution": insts.get(iid), "outbox": 0, "webhooks": 0})["outbox"] = int(n)
        for iid, n in hooks:
            per.setdefault(str(iid), {"institution": insts.get(iid), "outbox": 0, "webhooks": 0})["webhooks"] = int(n)
        return {"total": sum(v["outbox"] + v["webhooks"] for v in per.values()), "tenants": list(per.values())}
