"""Platform dashboard, platform alerts and the platform audit — Prompts/38 §38.6 ``platform_dashboard_service``.

Business rules
1. Dashboard (``platform:view``; cached 5 minutes in Redis ``platform:dashboard``): tenants by status / plan / type,
   MRR / ARR (running subscriptions normalised monthly), trials ending in 7 days, overdue invoices, top usage /
   overage tenants, failing connections and provider outages, open tickets by priority with SLA breaches, chain
   breaks and anomalies (platform alerts), dead letters, active read-only windows, recent platform actions and the
   platform charts (Phase 35 registry keys ``saas.*`` computed on the platform session).
2. **Platform alerts**: the consumers of Phase 37 ``audit.chain_broken`` / ``audit.anomaly_detected`` record
   ``platform_settings['alert:<id>']`` (tenant, kind, detail, first / last seen — deduplicated per tenant + kind +
   rule) and notify the super admins (``platform.alert``); ``resolve`` closes one (super admin, audited).
3. **Platform audit** (``/platform/audit``): the Phase 37 ``audit_logs`` rows written by platform users (super admins,
   support agents) or under impersonation, plus every ``platform`` / ``support`` / ``institutions`` module row —
   filtered by tenant, actor and dates (≤ 366 days); support agents see their own actions only.
"""

import contextlib
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, text

from app.models.audit import AuditLog
from app.models.platform import User
from app.schemas.saas import PlatformAuditRow, PlatformDashboardOut
from app.services.saas.common import PlatformBase, not_found, now_utc, today_utc, unprocessable

CACHE_KEY = "platform:dashboard"
CACHE_TTL = 300


class PlatformDashboardService(PlatformBase):
    async def dashboard(self, refresh: bool = False) -> PlatformDashboardOut:
        self.require_platform("platform", "view")
        from app.db.session import redis_client

        if not refresh:
            with contextlib.suppress(Exception):
                cached = await redis_client.get(CACHE_KEY)
                if cached:
                    data = PlatformDashboardOut.model_validate_json(cached)
                    data.cached = True
                    return data
        data = await self.compute()
        with contextlib.suppress(Exception):
            await redis_client.set(CACHE_KEY, data.model_dump_json(), ex=CACHE_TTL)
        return data

    async def compute(self) -> PlatformDashboardOut:
        from app.services.saas.health_service import HealthService
        from app.services.saas.institution_admin_service import InstitutionAdminService
        from app.services.saas.read_only_schedule_service import ReadOnlyScheduleService
        from app.services.saas.registrations import platform_charts
        from app.services.saas.subscription_service import SubscriptionService
        from app.services.saas.support_service import SupportService
        from app.services.saas.usage_service import UsageService

        counts = await InstitutionAdminService(self.db, self.principal).counts()
        subs = SubscriptionService(self.db, self.principal)
        mrr, by_plan = await subs.mrr()
        today = today_utc()
        trials = (
            (
                await self.db.execute(
                    text(
                        "SELECT DISTINCT ON (s.institution_id) s.institution_id, i.name, i.slug, s.ends_on, s.status FROM institution_subscriptions s "
                        "JOIN institutions i ON i.id = s.institution_id WHERE i.deleted_at IS NULL "
                        "ORDER BY s.institution_id, s.starts_on DESC, s.created_at DESC"
                    )
                )
            )
            .mappings()
            .all()
        )
        trials_ending = [
            {
                "institution": {"id": str(t["institution_id"]), "name": t["name"], "slug": t["slug"]},
                "ends_on": t["ends_on"],
            }
            for t in trials
            if t["status"] == "trial" and t["ends_on"] and today <= t["ends_on"] <= today + timedelta(days=7)
        ]
        overdue = [
            d for _, _, d in await self.tlist("invoice:") if isinstance(d, dict) and d.get("status") == "overdue"
        ]
        health = HealthService(self.db, self.principal)
        failing = [r.model_dump() for r in await health.overview(status="failed")][:50]
        outages = [o.model_dump() for o in await health.compute_outages()]
        tickets, breaches = await SupportService(self.db, self.principal).open_by_priority()
        alerts = await self.alerts()
        ro = [w.model_dump() for w in await ReadOnlyScheduleService(self.db, self.principal).active_now()]
        recent = [r.model_dump() for r in await self.audit_rows(None, None, today - timedelta(days=7), None, limit=15)]
        return PlatformDashboardOut(
            tenants={**counts, "by_plan": by_plan},
            tenants_total=sum(counts["by_status"].values()),
            mrr_paise=mrr,
            arr_paise=mrr * 12,
            trials_ending=trials_ending,
            invoices_overdue={
                "count": len(overdue),
                "total_paise": sum(int(d.get("total_paise") or 0) for d in overdue),
            },
            usage_top=await UsageService(self.db, self.principal).top(10),
            health_failing=failing,
            outages=outages,
            tickets_open_by_priority=tickets,
            sla_breaches=breaches,
            chain_breaks=[a for a in alerts if a.get("kind") == "chain_broken" and not a.get("resolved")],
            alerts=[a for a in alerts if not a.get("resolved")][:50],
            jobs_dead_letters=await health.dead_letters(),
            read_only_active=ro,
            recent_actions=recent,
            charts=await platform_charts(self.db),
            generated_at=now_utc(),
        )

    # ---- alerts (rule 2) --------------------------------------------------------------------------------------------
    async def record_alert(self, kind: str, institution_id: uuid.UUID | None, detail: dict[str, Any]) -> str:
        key = f"{institution_id}:{kind}:{detail.get('rule') or ''}"
        aid = uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:16]
        existing = await self.pget(f"alert:{aid}") or {}
        inst = (await self.institution_refs([institution_id])).get(institution_id) if institution_id else None
        doc = {
            "id": aid,
            "kind": kind,
            "institution_id": str(institution_id) if institution_id else None,
            "institution": inst,
            "detail": detail,
            "count": int(existing.get("count") or 0) + 1,
            "first_seen": existing.get("first_seen") or now_utc().isoformat(),
            "last_seen": now_utc().isoformat(),
            "resolved": False,
        }
        await self.pput(f"alert:{aid}", doc)
        if not existing or existing.get("resolved"):
            await self.notify_platform(
                "platform.alert",
                {
                    "kind": kind.replace("_", " "),
                    "institution": (inst or {}).get("name") or "platform",
                    "detail": json.dumps(detail, default=str)[:300],
                },
                ["in_app", "email"],
            )
        with contextlib.suppress(Exception):
            from app.db.session import redis_client

            await redis_client.delete(CACHE_KEY)
        return aid

    async def alerts(self) -> list[dict[str, Any]]:
        rows = [v for v in (await self.plist("alert:")).values() if isinstance(v, dict)]
        return sorted(rows, key=lambda v: str(v.get("last_seen") or ""), reverse=True)

    async def list_alerts(self, open_only: bool = True) -> list[dict[str, Any]]:
        self.require_platform("platform", "view")
        rows = await self.alerts()
        return [r for r in rows if not (open_only and r.get("resolved"))]

    async def resolve_alert(self, alert_id: str, note: str | None) -> dict[str, Any]:
        self.require_super("Resolving platform alerts")
        doc = await self.pget(f"alert:{alert_id}")
        if not isinstance(doc, dict):
            raise not_found("Alert")
        doc.update(resolved=True, resolved_at=now_utc().isoformat(), resolved_by=str(self.actor_id), note=note)
        await self.pput(f"alert:{alert_id}", doc)
        inst = uuid.UUID(doc["institution_id"]) if doc.get("institution_id") else None
        await self.audit(
            "alert_resolve",
            "platform_alert",
            None,
            {"alert_id": alert_id, "kind": doc.get("kind"), "note": note},
            institution_id=inst,
        )
        return doc

    # ---- platform audit (rule 3) ------------------------------------------------------------------------------------
    async def audit_rows(
        self,
        institution_id: uuid.UUID | None,
        actor: uuid.UUID | None,
        date_from: date | datetime | None,
        date_to: date | datetime | None,
        limit: int = 500,
        module: str | None = None,
    ) -> list[PlatformAuditRow]:
        self.require_platform("platform", "view")
        hi = _dt(date_to, end=True) or now_utc()
        lo = _dt(date_from) or hi - timedelta(days=30)
        if (hi - lo).days > 366:
            raise unprocessable("A query may span at most 366 days", field="from")
        platform_users = select(User.id).where(
            or_(User.is_super_admin.is_(True), and_(User.institution_id.is_(None), User.deleted_at.is_(None)))
        )
        q = (
            select(AuditLog)
            .where(
                AuditLog.occurred_at >= lo,
                AuditLog.occurred_at <= hi,
                or_(
                    AuditLog.user_id.in_(platform_users),
                    AuditLog.impersonator_id.is_not(None),
                    AuditLog.module.in_(("platform", "support", "institutions")),
                ),
            )
            .order_by(AuditLog.occurred_at.desc())
            .limit(min(limit, 2000))
        )
        if institution_id:
            q = q.where(AuditLog.institution_id == institution_id)
        if actor:
            q = q.where(AuditLog.user_id == actor)
        if module:
            q = q.where(AuditLog.module == module)
        if self.is_support:
            q = q.where(AuditLog.user_id == self.actor_id)
        rows = list((await self.db.execute(q)).scalars())
        from app.services.audit.common import AuditBase

        users = await self.user_refs([r.user_id for r in rows] + [r.impersonator_id for r in rows])
        insts = await self.institution_refs([r.institution_id for r in rows])
        return [
            PlatformAuditRow(
                id=r.id,
                occurred_at=r.occurred_at,
                institution=insts.get(r.institution_id) if r.institution_id else None,
                actor=users.get(r.user_id) if r.user_id else None,
                impersonator=users.get(r.impersonator_id) if r.impersonator_id else None,
                module=r.module,
                action=r.action,
                record_type=r.record_type,
                record_id=r.record_id,
                summary=AuditBase.summary_line(r),
                new_values=r.new_values if not self.is_support else None,
            )
            for r in rows
        ]


def _dt(v: date | datetime | None, *, end: bool = False) -> datetime | None:
    from datetime import UTC, time

    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return datetime.combine(v, time.max if end else time.min, tzinfo=UTC)
