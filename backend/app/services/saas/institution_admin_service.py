"""Tenant lifecycle and detail — Prompts/38 §38.6 ``institution_admin_service`` (super admin).

Business rules
1. **Lifecycle** ``pending → active ⇄ suspended``, ``active|suspended → archived ⇄ (unarchive) active``, then
   ``erase``. ``activate`` needs a subscription row (trial / active / grace); ``suspend`` revokes every session
   (login → 403 ``INSTITUTION_SUSPENDED``), pauses the tenant's webhooks (re-enabled on activate) — Beat jobs already
   skip non-active tenants; ``archive`` needs a finished tenant export (409 ``RULE_VIOLATION`` otherwise) and hides
   the tenant (403 ``INSTITUTION_ARCHIVED``); every change is reason-bearing, audited on the tenant's chain, kept in
   ``saas_meta status_log`` and emits ``institution.<verb>``.
2. **Onboarding wizard by template** (``university | autonomous | affiliated | standalone``): Phase 03 ``onboard``
   (roles, pack defaults, first admin, plan + ``apply_plan_defaults``) then the template's forced features
   (``source='override'`` with the template as reason, so later plan changes keep them), a trial
   (``billing.trial_days``, no invoice) or a first invoice, ``pending`` when not activated, the plan-locked settings,
   the custom domain (``institution_domains``, Phase 40 verifies it). ``feature_preview`` shows the diff vs the plan.
3. **Tenant export** (job ``tenant.export``; super admin, or the tenant's institution admin via ``/billing/export``
   when ``data.export_portability`` is on): every table with an ``institution_id`` (RLS-scoped rows) as JSON lines
   or CSV + the files manifest (keys under the tenant prefix) + the ``Database_Schema.sql`` sha256 + per-table row
   counts and sha256 → a zip encrypted with AES-256-GCM (key derived from a random password, PBKDF2-SHA256) stored at
   ``platform/exports/{institution}/{ts}/export.zip.enc``; the password goes in a separate e-mail; signed URL valid 7
   days; manifest in ``saas_meta export:<id>``.
4. **Reset** (job ``tenant.reset``): demo tenants (``demo.institution_slugs``) only, unless
   ``danger.allow_prod_reset``; typed slug. Deletes the tenant's operational rows (identity / configuration tables
   kept — users, roles, flags, settings, subscription), then re-runs ``seed_demo_institution.py --type <type> --all``
   and the Phase 03 demo job; nightly Beat ``demo.reset_nightly``.
5. **Erasure** (job ``tenant.erase``): typed slug + reason; the tenant must not be active and must have an export;
   with ``danger.four_eyes`` a second super admin approves (first call → 202 ``pending_approval``). Deletes every
   tenant row except the append-only audit chain and domain events, anonymises the ``institutions`` row (soft
   deleted), keeps the erasure manifest in ``platform_settings['erasure:<id>']``. Irreversible.
6. **Detail** aggregates profile, subscription + invoices, usage (3 months), flags summary, connections health, open
   tickets, impersonations, chain integrity (Phase 37 ``audit_meta`` verifications / digests + platform alerts), last
   logins, caps, exports and the pending erasure request. Support-agent reads are audited and masked.
"""

import base64
import hashlib
import io
import json
import os
import secrets
import uuid
import zipfile
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text

from app.core.features import FEATURE_REGISTRY
from app.enums.saas import EXPORT_TTL_DAYS, TEMPLATES, TENANT_KEEP_TABLES, TYPE_TEMPLATE
from app.models.platform import Institution
from app.models.saas import InstitutionSubscription, SubscriptionPlan
from app.schemas.institution import OnboardingRequest, OnboardingResponse
from app.schemas.saas import (
    FeaturePreviewOut,
    InstitutionAdminOut,
    InstitutionDetailOut,
    InstitutionStatusChange,
    JobAccepted,
    TenantErasureRequest,
    TenantExportRequest,
    TenantResetRequest,
)
from app.services.saas.common import (
    PlatformBase,
    conflict,
    forbidden,
    not_found,
    now_utc,
    rule,
    unprocessable,
)

# identity / configuration tables a demo reset keeps (operational data is re-seeded)
RESET_KEEP = TENANT_KEEP_TABLES | {
    "institution_profile",
    "colleges",
    "faculties",
    "departments",
    "institution_settings",
    "institution_feature_flags",
    "feature_flag_changes",
    "roles",
    "user_roles",
    "users",
    "user_sessions",
    "login_history",
    "mfa_secrets",
    "device_tokens",
    "password_reset_tokens",
    "ip_allowlists",
    "credential_sheets",
    "institution_subscriptions",
    "usage_meters",
    "impersonation_logs",
    "number_sequences",
    "notification_templates",
    "notification_preferences",
    "workflow_definitions",
    "integration_connections",
    "integration_health_checks",
    "api_keys",
    "webhooks",
    "institution_domains",
    "institution_website_config",
    "consent_records",
    "support_tickets",
    "feedback_entries",
    "help_articles",
    "read_only_modes",
}
ERASE_KEEP = TENANT_KEEP_TABLES
SEEDER_TYPE = {"university": "university", "autonomous_college": "autonomous", "affiliated_college": "affiliated"}


class InstitutionAdminService(PlatformBase):
    # ---- list / detail ------------------------------------------------------------------------------------------
    async def _rows(self, where: str = "", binds: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        sql = f"""
            SELECT i.id, i.name, i.slug, i.institution_type, i.status, i.created_at,
                   s.status AS sub_status, s.ends_on, p.code AS plan, p.tier,
                   (SELECT count(*) FROM students st WHERE st.institution_id = i.id AND st.deleted_at IS NULL
                      AND st.status IN ('provisional','admitted','active','on_break','detained')) AS students,
                   (SELECT count(*) FROM users u WHERE u.institution_id = i.id AND u.deleted_at IS NULL
                      AND u.is_active AND u.user_type = 'staff') AS staff,
                   (SELECT m.storage_bytes FROM usage_meters m WHERE m.institution_id = i.id
                      ORDER BY m.period_month DESC LIMIT 1) AS storage,
                   (SELECT max(lh.occurred_at) FROM login_history lh WHERE lh.institution_id = i.id
                      AND lh.outcome IN ('success', 'otp', 'sso')) AS last_login,
                   (SELECT CASE WHEN bool_or(c.status = 'failed') THEN 'failing'
                                WHEN bool_or(c.status = 'degraded') THEN 'degraded'
                                WHEN count(*) > 0 THEN 'ok' ELSE 'none' END
                      FROM integration_connections c WHERE c.institution_id = i.id AND c.status <> 'disabled') AS health
            FROM institutions i
            LEFT JOIN LATERAL (
                SELECT * FROM institution_subscriptions x WHERE x.institution_id = i.id
                ORDER BY x.starts_on DESC, x.created_at DESC LIMIT 1
            ) s ON TRUE
            LEFT JOIN subscription_plans p ON p.id = s.plan_id
            WHERE i.deleted_at IS NULL {where}
            ORDER BY i.created_at DESC
        """  # noqa: S608 - static fragments; values are bound
        rows = (await self.db.execute(text(sql), binds or {})).mappings().all()
        return [dict(r) for r in rows]

    async def _demo_slugs(self) -> set[str]:
        return set(await self.setting("demo.institution_slugs") or [])

    def _admin_out(self, r: dict[str, Any], demo: set[str]) -> InstitutionAdminOut:
        return InstitutionAdminOut(
            id=r["id"],
            name=r["name"],
            slug=r["slug"],
            type=r["institution_type"],
            status=r["status"],
            plan=r["plan"],
            tier=r["tier"],
            subscription_status=r["sub_status"],
            ends_on=r["ends_on"],
            students_active=int(r["students"] or 0),
            staff_active=int(r["staff"] or 0),
            storage_gb=round(int(r["storage"] or 0) / 1024**3, 2),
            health=r["health"] or "none",
            last_login_at=r["last_login"],
            created_at=r["created_at"],
            is_demo=r["slug"] in demo,
        )

    async def list_institutions(
        self,
        status: str | None = None,
        plan: str | None = None,
        institution_type: str | None = None,
        q: str | None = None,
        health: str | None = None,
    ) -> list[InstitutionAdminOut]:
        self.require_platform("platform", "view")
        where, binds = [], {}
        if status:
            where.append("i.status = :status")
            binds["status"] = status
        if institution_type:
            where.append("i.institution_type = :itype")
            binds["itype"] = institution_type
        if q:
            where.append("(i.name ILIKE :q OR i.slug ILIKE :q)")
            binds["q"] = f"%{q}%"
        rows = await self._rows("".join(f" AND {w}" for w in where), binds)
        if plan:
            rows = [r for r in rows if r["plan"] == plan or r["tier"] == plan]
        if health:
            rows = [r for r in rows if (r["health"] or "none") == health]
        demo = await self._demo_slugs()
        return [self._admin_out(r, demo) for r in rows]

    async def detail(self, institution_id: uuid.UUID) -> InstitutionDetailOut:
        self.require_platform("platform", "view")
        rows = await self._rows(" AND i.id = :id", {"id": institution_id})
        if not rows:
            raise not_found("Institution")
        base = self._admin_out(rows[0], await self._demo_slugs())
        await self.audit_read(institution_id, "institution_detail", institution_id)
        from app.services.saas.subscription_service import SubscriptionService
        from app.services.saas.usage_service import UsageService

        inst = await self.institution(institution_id)
        subs = SubscriptionService(self.db, self.principal, self.request)
        sub_out = await subs.subscription(institution_id)
        usage = await UsageService(self.db, self.principal, self.request).months(institution_id, None, None)
        flags = (
            await self.db.execute(
                text(
                    "SELECT source, count(*) FILTER (WHERE platform_enabled), count(*) FROM institution_feature_flags "
                    "WHERE institution_id = :i GROUP BY source"
                ),
                {"i": institution_id},
            )
        ).all()
        conns = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, capability, provider, label, status, last_health_at, last_error FROM integration_connections "
                        "WHERE institution_id = :i ORDER BY capability, provider"
                    ),
                    {"i": institution_id},
                )
            )
            .mappings()
            .all()
        )
        tickets = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, ticket_number, subject, priority, status, created_at FROM support_tickets "
                        "WHERE institution_id = :i AND status NOT IN ('resolved','closed') ORDER BY created_at DESC LIMIT 20"
                    ),
                    {"i": institution_id},
                )
            )
            .mappings()
            .all()
        )
        imps = (
            (
                await self.db.execute(
                    text(
                        "SELECT l.id, l.reason, l.started_at, l.ended_at, u.display_name AS impersonator, t.display_name AS target "
                        "FROM impersonation_logs l LEFT JOIN users u ON u.id = l.impersonator_id LEFT JOIN users t ON t.id = l.target_user_id "
                        "WHERE l.institution_id = :i ORDER BY l.started_at DESC LIMIT 20"
                    ),
                    {"i": institution_id},
                )
            )
            .mappings()
            .all()
        )
        logins = (
            (
                await self.db.execute(
                    text(
                        "SELECT identifier, success, created_at FROM login_history WHERE institution_id = :i "
                        "ORDER BY created_at DESC LIMIT 10"
                    ),
                    {"i": institution_id},
                )
            )
            .mappings()
            .all()
        )
        return InstitutionDetailOut(
            **base.model_dump(),
            profile={
                "short_name": inst.short_name,
                "code": inst.code,
                "regulatory_pack": inst.regulatory_pack,
                "timezone": inst.timezone,
                "gstin": inst.gstin,
                "parent_university_name": inst.parent_university_name,
                "contact": inst.contact if not self.is_support else None,
                "website_url": inst.website_url,
            },
            subscription=sub_out.model_dump(exclude={"invoices", "usage_vs_limits"}),
            invoices=[i.model_dump() for i in sub_out.invoices[:24]],
            usage=[m.model_dump() for m in usage.months[-3:]],
            flags={"by_source": {s: {"enabled": int(e), "total": int(t)} for s, e, t in flags}},
            connections=[dict(c) for c in conns],
            open_tickets=[dict(t) for t in tickets],
            impersonations=[dict(i) for i in imps],
            chain=await self.chain_status(institution_id),
            last_logins=[{**dict(lg), "identifier": self.mask(lg["identifier"], "email")} for lg in logins],
            status_log=list(await self.tget(institution_id, "status_log", []) or [])[-20:],
            caps=await UsageService(self.db, self.principal).caps(institution_id),
            exports=[v for _, _, v in await self.tlist("export:", institution_id)],
            erase_request=await self.tget(institution_id, "erase_request"),
        )

    async def chain_status(self, institution_id: uuid.UUID) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT key, value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                    "AND category = 'audit_meta' AND (key LIKE 'verify:%' OR key LIKE 'digest:%')"
                ),
                {"i": institution_id},
            )
        ).all()
        verifies = sorted(
            (v for k, v in rows if k.startswith("verify:") and isinstance(v, dict)),
            key=lambda v: str(v.get("at") or v.get("created_at") or ""),
            reverse=True,
        )
        digests = sorted(k.split(":", 1)[1] for k, _ in rows if k.startswith("digest:"))
        alerts = [
            v
            for k, v in (await self.plist("alert:")).items()
            if isinstance(v, dict) and v.get("institution_id") == str(institution_id) and not v.get("resolved")
        ]
        last = verifies[0] if verifies else None
        return {
            "last_verification": last,
            "ok": bool(last.get("ok")) if last else None,
            "digests": len(digests),
            "last_digest": digests[-1] if digests else None,
            "open_alerts": alerts,
        }

    # ---- onboarding (rule 2) --------------------------------------------------------------------------------------
    async def feature_preview(self, template: str, plan_code: str) -> FeaturePreviewOut:
        self.require_platform("platform", "view")
        tpl = TEMPLATES.get(template)
        if tpl is None:
            raise unprocessable(f"Unknown template {template!r}", field="template")
        plan = (
            await self.db.execute(select(SubscriptionPlan).where(SubscriptionPlan.code == plan_code))
        ).scalar_one_or_none()
        if plan is None:
            raise unprocessable(f"Unknown plan {plan_code!r}", field="plan_code")
        keys = set(plan.enabled_features or [])
        on = [k for k in tpl["on"] if k in FEATURE_REGISTRY]
        off = [k for k in tpl["off"] if k in FEATURE_REGISTRY]
        enabled = sorted((keys | set(on)) - set(off))
        return FeaturePreviewOut(
            plan=plan.code,
            template=template,
            enabled=enabled,
            forced_on=sorted(on),
            forced_off=sorted(off),
            not_in_plan=sorted(k for k in on if k not in keys),
        )

    async def onboard(self, body: OnboardingRequest) -> OnboardingResponse:
        from app.enums.institution import InstitutionType
        from app.services.institution_service import InstitutionService
        from app.services.saas.subscription_service import SubscriptionService, cache_subscription_state

        self.require_super("Onboarding institutions")
        tpl_name = body.template or TYPE_TEMPLATE.get(body.institution.institution_type.value, "standalone")
        tpl = TEMPLATES[tpl_name]
        if body.template:
            body.institution.institution_type = InstitutionType(tpl["institution_type"])
        from app.enums.saas import RESERVED_SLUGS

        if body.institution.slug in RESERVED_SLUGS:
            raise unprocessable(f"Slug {body.institution.slug!r} is reserved", field="institution.slug")
        result = await InstitutionService(self.db, self.principal, self.request).onboard(body)
        inst_id = result.institution.id
        inst = await self.institution(inst_id, lock=True)
        forced = await self.apply_template(inst_id, tpl_name)
        subs = SubscriptionService(self.db, self.principal, self.request)
        sub = await subs.current(inst_id, lock=True)
        plan = await subs._plan(sub.plan_id) if sub else None
        if sub is not None and plan is not None:
            if body.trial:
                days = body.trial_days or int(await self.setting("billing", "trial_days") or 30)
                sub.status, sub.amount_paise, sub.billing_cycle = "trial", 0, body.billing_cycle
                sub.ends_on = sub.starts_on + timedelta(days=days)
                await self.notify_tenant_admins(
                    inst_id,
                    "saas.trial_started",
                    {"institution": inst.name, "plan": plan.name, "ends_on": str(sub.ends_on)},
                )
            else:
                from app.services.saas.subscription_service import cycle_days, plan_price

                sub.billing_cycle = body.billing_cycle
                sub.ends_on = sub.starts_on + timedelta(days=cycle_days(body.billing_cycle))
                sub.amount_paise = plan_price(plan, body.billing_cycle)
                if sub.amount_paise:
                    await subs.issue_invoice(
                        inst, sub, plan, "subscription", [(f"{plan.name} — {body.billing_cycle}", sub.amount_paise)]
                    )
            await self.db.flush()
            await subs.apply_locked_settings(inst_id, plan)
            await cache_subscription_state(inst_id, sub.status)
        if not body.activate:
            inst.status = "pending"
        if body.custom_domain:
            await self.db.execute(
                text(
                    "INSERT INTO institution_domains (institution_id, hostname, is_primary, verification_token) "
                    "VALUES (:i, :h, TRUE, :t) ON CONFLICT (hostname) DO NOTHING"
                ),
                {"i": inst_id, "h": body.custom_domain.lower(), "t": secrets.token_hex(16)},
            )
        await self._log_status(inst_id, "onboarded", None, inst.status, f"template {tpl_name}")
        await self.audit(
            "onboard_template",
            "institution",
            inst_id,
            {
                "template": tpl_name,
                "trial": body.trial,
                "status": inst.status,
                "forced": forced,
                "domain": body.custom_domain,
            },
            institution_id=inst_id,
        )
        if inst.status == "active":
            await self.emit(
                "institution.activated",
                {"institution_id": str(inst_id), "template": tpl_name},
                institution_id=inst_id,
                aggregate_type="institution",
                aggregate_id=inst_id,
            )
        result.template = tpl_name
        result.status = inst.status
        result.subscription_status = sub.status if sub else None
        result.subscription_ends_on = sub.ends_on if sub else None
        result.forced_features = forced
        return result

    async def apply_template(self, institution_id: uuid.UUID, template: str) -> dict[str, list[str]]:
        """Template features as overrides (kept across plan changes), dependencies first."""
        from app.core.features import invalidate_features_cache
        from app.repositories.feature_flag_repository import FeatureFlagRepository

        tpl = TEMPLATES[template]
        repo = FeatureFlagRepository(self.db)
        flags = await repo.flags(institution_id)
        done: dict[str, list[str]] = {"on": [], "off": []}
        for wanted, keys in ((True, tpl["on"]), (False, tpl["off"])):
            for key in keys:
                if key not in FEATURE_REGISTRY:
                    continue
                row = flags.get(key)
                if row is not None and row.platform_enabled == wanted:
                    continue
                await repo.upsert(institution_id, key, platform_enabled=wanted, source="override", set_by=self.actor_id)
                await repo.log_change(
                    institution_id,
                    key,
                    None,
                    {"platform_enabled": wanted, "source": "override"},
                    self.actor_id,
                    f"template {template}",
                )
                done["on" if wanted else "off"].append(key)
        await invalidate_features_cache(institution_id)
        if done["on"] or done["off"]:
            await self.emit(
                "feature_flag.changed",
                {
                    "institution_id": str(institution_id),
                    "keys": done["on"] + done["off"],
                    "reason": f"template {template}",
                },
                institution_id=institution_id,
                aggregate_type="institution",
                aggregate_id=institution_id,
            )
        return done

    # ---- lifecycle (rule 1) ---------------------------------------------------------------------------------------
    async def _log_status(
        self, institution_id: uuid.UUID, action: str, old: str | None, new: str, reason: str | None
    ) -> None:
        log = list(await self.tget(institution_id, "status_log", []) or [])
        log.append(
            {
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
                "action": action,
                "from": old,
                "to": new,
                "reason": reason,
            }
        )
        await self.tput(institution_id, "status_log", log[-100:])

    async def has_export(self, institution_id: uuid.UUID) -> bool:
        return any(
            isinstance(v, dict) and v.get("status") == "done" for _, _, v in await self.tlist("export:", institution_id)
        )

    async def change_status(self, institution_id: uuid.UUID, body: InstitutionStatusChange) -> InstitutionAdminOut:
        from app.repositories.institution_repository import InstitutionRepository

        self.require_super("Changing an institution's status")
        inst = await self.institution(institution_id, lock=True)
        old = inst.status
        allowed = {
            "activate": ("pending", "suspended"),
            "suspend": ("pending", "active"),
            "archive": ("active", "suspended"),
            "unarchive": ("archived",),
        }[body.action]
        if old not in allowed:
            raise rule(f"Cannot {body.action} an institution that is {old}", status=old)
        if body.action == "activate":
            sub = (
                await self.db.execute(
                    select(InstitutionSubscription.id).where(
                        InstitutionSubscription.institution_id == inst.id,
                        InstitutionSubscription.status.in_(("trial", "active", "grace")),
                    )
                )
            ).first()
            if sub is None:
                raise rule("A subscription is required before activation", code="SUBSCRIPTION_REQUIRED")
        if body.action == "archive" and not await self.has_export(inst.id):
            raise rule("Export the tenant before archiving it", code="EXPORT_REQUIRED")
        new = {"activate": "active", "suspend": "suspended", "archive": "archived", "unarchive": "active"}[body.action]
        inst.status = new
        revoked = 0
        if new in ("suspended", "archived"):
            revoked = await InstitutionRepository(self.db).revoke_sessions(inst.id, f"institution_{new}")
        paused = await self._webhooks(inst.id, enable=new == "active")
        await self.db.flush()
        await self._log_status(inst.id, body.action, old, new, body.reason)
        await self.audit(
            body.action,
            "institution",
            inst.id,
            {"status": new, "reason": body.reason, "sessions_revoked": revoked, "webhooks": paused},
            old={"status": old},
            institution_id=inst.id,
            module="institutions",
        )
        verb = {"activate": "activated", "suspend": "suspended", "archive": "archived", "unarchive": "unarchived"}[
            body.action
        ]
        await self.emit(
            f"institution.{verb}",
            {"institution_id": str(inst.id), "from": old, "reason": body.reason},
            institution_id=inst.id,
            aggregate_type="institution",
            aggregate_id=inst.id,
        )
        await self.emit(
            "institution.updated",
            {"institution_id": str(inst.id), "fields": ["status"], "status": new},
            institution_id=inst.id,
            aggregate_type="institution",
            aggregate_id=inst.id,
        )
        rows = await self._rows(" AND i.id = :id", {"id": inst.id})
        return self._admin_out(rows[0], await self._demo_slugs())

    async def _webhooks(self, institution_id: uuid.UUID, *, enable: bool) -> int:
        """Suspension pauses the tenant's active webhooks (remembered in ``saas_meta paused_webhooks``)."""
        if enable:
            ids = list(await self.tget(institution_id, "paused_webhooks", []) or [])
            if ids:
                await self.db.execute(
                    text("UPDATE webhooks SET is_active = TRUE WHERE institution_id = :i AND id = ANY(:ids)"),
                    {"i": institution_id, "ids": [uuid.UUID(x) for x in ids]},
                )
                await self.tdelete(institution_id, "paused_webhooks")
            return len(ids)
        rows = (
            await self.db.execute(
                text("UPDATE webhooks SET is_active = FALSE WHERE institution_id = :i AND is_active RETURNING id"),
                {"i": institution_id},
            )
        ).all()
        if rows:
            prior = list(await self.tget(institution_id, "paused_webhooks", []) or [])
            await self.tput(institution_id, "paused_webhooks", sorted(set(prior) | {str(r[0]) for r in rows}))
        return len(rows)

    # ---- tenant tables ----------------------------------------------------------------------------------------------
    async def tenant_tables(self) -> list[str]:
        rows = (
            await self.db.execute(
                text(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'institution_id' AND NOT a.attisdropped "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND NOT c.relispartition ORDER BY c.relname"
                )
            )
        ).all()
        return [r[0] for r in rows]

    async def _delete_tenant_rows(self, institution_id: uuid.UUID, keep: frozenset[str] | set[str]) -> dict[str, Any]:
        """Delete the tenant's rows table by table; FK-blocked tables are retried on the next pass (children first)."""
        pending = [t for t in await self.tenant_tables() if t not in keep]
        counts: dict[str, int] = {}
        errors: dict[str, str] = {}
        for _ in range(8):
            progressed = False
            for table in list(pending):
                try:
                    async with self.db.begin_nested():
                        res: Any = await self.db.execute(
                            text(f'DELETE FROM "{table}" WHERE institution_id = :i'), {"i": institution_id}
                        )
                    counts[table] = counts.get(table, 0) + int(res.rowcount or 0)
                    pending.remove(table)
                    errors.pop(table, None)
                    progressed = True
                except Exception as exc:  # noqa: BLE001 - FK order: retried on the next pass
                    errors[table] = str(exc).splitlines()[0][:200]
            if not pending or not progressed:
                break
        return {"deleted": counts, "rows": sum(counts.values()), "failed": errors}

    # ---- export (rule 3) --------------------------------------------------------------------------------------------
    async def request_export(
        self, institution_id: uuid.UUID | None, body: TenantExportRequest, *, tenant: bool = False
    ) -> JobAccepted:
        from app.core.jobs import enqueue

        if tenant:
            inst_id = self.institution_scope(institution_id)
            if "institution_admin" not in (getattr(self.principal, "roles", None) or []):
                raise forbidden("Only the institution admin exports the tenant")
        else:
            self.require_super("Exporting a tenant")
            if institution_id is None:
                raise unprocessable("institution_id is required", field="institution_id")
            inst_id = (await self.institution(institution_id)).id
        export_id = uuid.uuid4().hex[:12]
        await self.tput(
            inst_id,
            f"export:{export_id}",
            {
                "id": export_id,
                "status": "queued",
                "requested_at": now_utc().isoformat(),
                "requested_by": str(self.actor_id),
                "include": body.include,
                "format": body.format,
            },
        )
        job = await enqueue(
            self.db,
            self.principal,
            "tenant.export",
            {
                "institution_id": str(inst_id),
                "export_id": export_id,
                "include": body.include,
                "format": body.format,
                "email": body.encrypt_to_email,
            },
            queue="reports",
        )
        await self.audit(
            "export_request",
            "institution",
            inst_id,
            {"export_id": export_id, "job_id": str(job.id), "tenant": tenant},
            institution_id=inst_id,
        )
        return JobAccepted(job_id=job.id, job_type="tenant.export", detail={"export_id": export_id})

    async def export_now(
        self, institution_id: uuid.UUID, export_id: str, include: list[str], fmt: str, email: str | None = None
    ) -> dict[str, Any]:
        import csv

        from app.core.files import get_storage
        from app.db.session import set_tenant

        inst = await self.institution(institution_id)
        await set_tenant(self.db, institution_id)  # RLS context too (the dump stays tenant-scoped on either role)
        buf = io.BytesIO()
        tables: dict[str, Any] = {}
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if "db" in include:
                for table in await self.tenant_tables():
                    res = await self.db.execute(
                        text(f'SELECT * FROM "{table}" WHERE institution_id = :i'), {"i": institution_id}
                    )
                    cols = list(res.keys())
                    rows = res.all()
                    out = io.StringIO()
                    if fmt == "csv":
                        w = csv.writer(out)
                        w.writerow(cols)
                        for r in rows:
                            w.writerow(
                                [
                                    json.dumps(v, default=str)
                                    if isinstance(v, dict | list)
                                    else (
                                        ""
                                        if v is None
                                        else (
                                            base64.b64encode(v).decode()
                                            if isinstance(v, bytes | memoryview)
                                            else str(v)
                                        )
                                    )
                                    for v in r
                                ]
                            )
                    else:
                        for r in rows:
                            out.write(
                                json.dumps(
                                    {
                                        c: (
                                            base64.b64encode(bytes(v)).decode()
                                            if isinstance(v, bytes | memoryview)
                                            else v
                                        )
                                        for c, v in zip(cols, r, strict=False)
                                    },
                                    default=str,
                                )
                                + "\n"
                            )
                    data = out.getvalue().encode()
                    name = f"db/{table}.{'csv' if fmt == 'csv' else 'jsonl'}"
                    zf.writestr(name, data)
                    tables[table] = {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest(), "file": name}
            files: list[dict[str, Any]] = []
            if "files" in include:
                files = await self._files_manifest(institution_id)
                zf.writestr("files/manifest.json", json.dumps(files, indent=1, default=str))
            schema_sha = _schema_sha()
            manifest = {
                "institution": {"id": str(inst.id), "slug": inst.slug, "name": inst.name},
                "export_id": export_id,
                "generated_at": now_utc().isoformat(),
                "format": fmt,
                "tables": tables,
                "table_count": len(tables),
                "row_count": sum(t["rows"] for t in tables.values()),
                "files": {"count": len(files), "bytes": sum(int(f.get("size") or 0) for f in files)},
                "schema_sha256": schema_sha,
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=1, default=str))
        password = secrets.token_urlsafe(18)
        blob = _encrypt(buf.getvalue(), password)
        ts = now_utc().strftime("%Y%m%dT%H%M%S")
        key = f"platform/exports/{institution_id}/{ts}/export.zip.enc"
        storage = get_storage()
        await storage.put(key, blob, "application/octet-stream")
        url = storage.signed_url(key, ttl=EXPORT_TTL_DAYS * 86400)
        expires = now_utc() + timedelta(days=EXPORT_TTL_DAYS)
        doc = {
            "id": export_id,
            "status": "done",
            "key": key,
            "url": url,
            "expires_at": expires.isoformat(),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "size": len(blob),
            "manifest": {k: v for k, v in manifest.items() if k != "tables"}
            | {"tables": {t: {"rows": v["rows"], "sha256": v["sha256"]} for t, v in tables.items()}},
            "encryption": "AES-256-GCM, PBKDF2-SHA256 (200k) key; layout salt(16)|nonce(12)|ciphertext",
        }
        await self.tput(institution_id, f"export:{export_id}", doc)
        to = email or await self._admin_email(institution_id)
        if to:
            await self.notify(
                "saas.export_ready",
                None,
                {"direct_contacts": [{"channel": "email", "to": to, "name": inst.name}]},
                {"institution": inst.name, "url": url, "expires_at": expires.date().isoformat()},
                ["email"],
            )
            await self.notify(
                "saas.export_password",
                None,
                {"direct_contacts": [{"channel": "email", "to": to, "name": inst.name}]},
                {"institution": inst.name, "password": password},
                ["email"],
            )
        await self.audit(
            "export",
            "institution",
            institution_id,
            {"export_id": export_id, "tables": len(tables), "rows": manifest["row_count"], "sha256": doc["sha256"]},
            institution_id=institution_id,
        )
        await self.emit(
            "institution.exported",
            {"institution_id": str(institution_id), "export_id": export_id},
            institution_id=institution_id,
            aggregate_type="institution",
            aggregate_id=institution_id,
        )
        return {"export_id": export_id, "result_url": url, "manifest": doc["manifest"]}

    async def _files_manifest(self, institution_id: uuid.UUID) -> list[dict[str, Any]]:
        """Keys under the tenant prefix (local store walk; S3 lists by prefix) — signed URLs valid for the export."""
        from app.core.config import settings
        from app.core.files import get_storage

        out: list[dict[str, Any]] = []
        root = settings.UPLOAD_DIR if settings.STORAGE_BACKEND != "s3" else None
        storage = get_storage()
        if root:
            base = os.path.join(str(root), str(institution_id))
            for dirpath, _, names in os.walk(base):
                for n in names:
                    full = os.path.join(dirpath, n)
                    key = os.path.relpath(full, str(root)).replace(os.sep, "/")
                    out.append(
                        {
                            "key": key,
                            "size": os.path.getsize(full),
                            "url": storage.signed_url(key, ttl=EXPORT_TTL_DAYS * 86400),
                        }
                    )
                    if len(out) >= 50_000:
                        return out
        return out

    async def _admin_email(self, institution_id: uuid.UUID) -> str | None:
        row = (
            await self.db.execute(
                text(
                    "SELECT u.email FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles r ON r.id = ur.role_id "
                    "WHERE u.institution_id = :i AND r.slug = 'institution_admin' AND u.is_active AND u.deleted_at IS NULL "
                    "AND u.email IS NOT NULL ORDER BY u.created_at LIMIT 1"
                ),
                {"i": institution_id},
            )
        ).first()
        return row[0] if row else None

    # ---- reset (rule 4) ---------------------------------------------------------------------------------------------
    async def request_reset(self, institution_id: uuid.UUID, body: TenantResetRequest) -> JobAccepted:
        from app.core.jobs import enqueue

        self.require_super("Resetting a tenant")
        inst = await self.institution(institution_id)
        if body.confirm_slug != inst.slug:
            raise unprocessable("The typed slug does not match", field="confirm_slug")
        if inst.slug not in await self._demo_slugs() and not await self.setting("danger.allow_prod_reset"):
            raise forbidden("Only demo tenants can be reset (danger.allow_prod_reset is off)")
        job = await enqueue(self.db, self.principal, "tenant.reset", {"institution_id": str(inst.id)}, queue="reports")
        await self.audit("reset_request", "institution", inst.id, {"job_id": str(job.id)}, institution_id=inst.id)
        return JobAccepted(job_id=job.id, job_type="tenant.reset")

    async def reset_now(self, institution_id: uuid.UUID, *, reseed: bool = True) -> dict[str, Any]:
        inst = await self.institution(institution_id)
        result = await self._delete_tenant_rows(inst.id, RESET_KEEP)
        await self.audit(
            "reset",
            "institution",
            inst.id,
            {"rows": result["rows"], "tables": len(result["deleted"]), "failed": result["failed"]},
            institution_id=inst.id,
        )
        await self.emit(
            "institution.reset",
            {"institution_id": str(inst.id), "rows": result["rows"]},
            institution_id=inst.id,
            aggregate_type="institution",
            aggregate_id=inst.id,
        )
        await self.db.commit()
        seeded = None
        kind = SEEDER_TYPE.get(inst.institution_type)
        if reseed and kind:
            seeded = await _run_seeder(kind)
        return {
            "institution_id": str(inst.id),
            "deleted": result["rows"],
            "failed": result["failed"],
            "reseeded": seeded,
        }

    # ---- erasure (rule 5) -------------------------------------------------------------------------------------------
    async def request_erase(self, institution_id: uuid.UUID, body: TenantErasureRequest) -> JobAccepted:
        from app.core.jobs import enqueue

        self.require_super("Erasing a tenant")
        inst = await self.institution(institution_id, lock=True)
        if body.confirm_slug != inst.slug:
            raise unprocessable("The typed slug does not match", field="confirm_slug")
        if inst.status in ("active", "pending"):
            raise rule("Suspend or archive the institution before erasing it", status=inst.status)
        if not await self.has_export(inst.id):
            raise rule("Export the tenant before erasing it", code="EXPORT_REQUIRED")
        pending = await self.tget(inst.id, "erase_request")
        if await self.setting("danger.four_eyes"):
            if not isinstance(pending, dict):
                await self.tput(
                    inst.id,
                    "erase_request",
                    {"requested_by": str(self.actor_id), "reason": body.reason, "at": now_utc().isoformat()},
                )
                await self.audit(
                    "erase_request",
                    "institution",
                    inst.id,
                    {"reason": body.reason, "four_eyes": True},
                    institution_id=inst.id,
                )
                await self.notify_platform("saas.erase_approval", {"institution": inst.name, "reason": body.reason})
                return JobAccepted(
                    job_id=None, job_type="tenant.erase", status="pending_approval", detail={"approver_needed": True}
                )
            if pending.get("requested_by") == str(self.actor_id):
                raise conflict("A second super admin must approve the erasure")
        job = await enqueue(
            self.db,
            self.principal,
            "tenant.erase",
            {
                "institution_id": str(inst.id),
                "reason": body.reason,
                "requested_by": (pending or {}).get("requested_by"),
            },
            queue="reports",
        )
        await self.audit(
            "erase_approve",
            "institution",
            inst.id,
            {"job_id": str(job.id), "reason": body.reason, "requested_by": (pending or {}).get("requested_by")},
            institution_id=inst.id,
        )
        return JobAccepted(job_id=job.id, job_type="tenant.erase", detail={"approved_by": str(self.actor_id)})

    async def erase_now(self, institution_id: uuid.UUID, reason: str) -> dict[str, Any]:
        inst = await self.institution(institution_id, lock=True)
        exports = [v for _, _, v in await self.tlist("export:", inst.id)]
        result = await self._delete_tenant_rows(inst.id, ERASE_KEEP)
        manifest = {
            "institution_id": str(inst.id),
            "slug": inst.slug,
            "erased_at": now_utc().isoformat(),
            "erased_by": str(self.actor_id) if self.actor_id else None,
            "reason": reason,
            "deleted": result["deleted"],
            "rows": result["rows"],
            "failed": result["failed"],
            "kept": sorted(ERASE_KEEP),
            "exports": [{"id": e.get("id"), "sha256": e.get("sha256")} for e in exports if isinstance(e, dict)],
        }
        await self.pput(f"erasure:{inst.id}", manifest)
        inst.name = f"Erased institution {inst.slug}"
        inst.short_name = None
        inst.contact = None
        inst.address = None
        inst.gstin = None
        inst.status = "archived"
        inst.is_active = False
        inst.deleted_at = now_utc()
        await self.db.flush()
        await self.audit(
            "erase",
            "institution",
            inst.id,
            {"rows": result["rows"], "tables": len(result["deleted"]), "reason": reason},
            institution_id=inst.id,
        )
        await self.emit(
            "institution.erased",
            {"institution_id": str(inst.id), "rows": result["rows"]},
            institution_id=inst.id,
            aggregate_type="institution",
            aggregate_id=inst.id,
        )
        return {"institution_id": str(inst.id), "rows": result["rows"], "failed": result["failed"]}

    # ---- tenant counts for the dashboard ------------------------------------------------------------------------------
    async def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for name, col in (("by_status", Institution.status), ("by_type", Institution.institution_type)):
            stmt = select(col, func.count()).where(Institution.deleted_at.is_(None)).group_by(col)
            out[name] = {str(r[0]): int(r[1]) for r in (await self.db.execute(stmt)).all()}
        return out


def _schema_sha() -> str | None:
    from pathlib import Path

    for p in (Path(__file__).resolve().parents[4] / "Database_Schema.sql", Path("/app/Database_Schema.sql")):
        if p.exists():
            return hashlib.sha256(p.read_bytes()).hexdigest()
    return None


def _encrypt(data: bytes, password: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, nonce = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000).derive(password.encode())
    return salt + nonce + AESGCM(key).encrypt(nonce, data, None)


async def _run_seeder(kind: str) -> dict[str, Any]:
    """``seed_demo_institution.py --type <kind> --all`` in a subprocess (the scripts tree ships with the image)."""
    import asyncio
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[3] / "scripts" / "seed_demo_institution.py"
    if not script.exists():
        return {"ok": False, "reason": "seeder not shipped"}
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--type",
        kind,
        "--all",
        cwd=str(script.parent.parent),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=3600)
    except TimeoutError:
        proc.kill()
        return {"ok": False, "reason": "timeout"}
    tail = (out or b"").decode(errors="replace").strip().splitlines()[-3:]
    return {"ok": proc.returncode == 0, "tail": [ln for ln in tail if "password" not in ln.lower()]}
