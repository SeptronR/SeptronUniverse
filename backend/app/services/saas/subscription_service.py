"""Plans, subscriptions, invoices and dunning — Prompts/38 §38.6 ``subscription_service``.

Business rules
1. **Plans** (super admin / ``platform:billing``): ``enabled_features`` must be registered keys whose
   ``min_plan_tier`` ≤ the plan tier (422 ``TIER``) unless ``allow_above_tier``; core keys are never listed (always
   on). Deactivating a plan keeps existing subscriptions. Plan-locked settings (Phase 37 ``locked_by=plan`` —
   ``reports.max_rows``, ``comms.credits``) are kept per plan in ``platform_settings['plan:<code>']`` and written to
   the tenant on every assign / change (tenants cannot edit them: 409 ``SETTING_LOCKED``).
2. **Change preview** lists features that would be switched off (plan-sourced flags, with their enabled dependants),
   overrides that survive (``source='override'``), limit violations (students / staff / storage vs the new plan) and
   the proration. A downgrade with violations is refused (409 ``RULE_VIOLATION`` with counts).
3. **Assign / change / renew / cancel** lock the current ``institution_subscriptions`` row (``FOR UPDATE``). A trial
   (``trial_days``) has no invoice until it converts; ``change(now)`` with ``billing.proration`` issues a proration
   invoice for the remaining share of the period (new plan − credit of the old); ``next_cycle`` is stored as the
   ``scheduled_change`` and applied at renewal. Every change re-runs ``feature_service.apply_plan_defaults``
   (overrides preserved), writes the plan-locked settings, emits ``subscription.*`` + Phase 02 ``subscription.changed``
   and refreshes the Redis subscription state read by the write gate.
4. **Invoices** (``saas_meta invoice:<number>`` on the tenant — tenants read their own under RLS): number
   ``<prefix>/FY<yy>/<nnnn>`` from the platform sequence ``seq:inv:FY<yy>`` (Indian FY, April–March); GST
   ``billing.gst_pct`` on the net; PDF rendered by the Phase 36 ``render_service.render_pdf`` with the platform
   letterhead and the tenant GSTIN, stored at ``platform/invoices/{institution}/{period}-{seq}.pdf``. Statuses
   ``issued → paid | overdue``. Payment: platform ``PaymentGateway`` order (``order:<id>`` row maps the order back) →
   webhook → ``paid``; or a manual ``payment_ref`` (platform billing).
5. **Dunning / state machine** (daily): reminders at due − 7, due and due + 7 (``invoice.overdue`` once past due);
   at due + 7 an unpaid invoice moves the subscription to ``grace`` (``grace_until`` = + ``grace_days``; writes still
   allowed, banner); after ``grace_until`` → ``expired`` (reads allowed, writes 403 ``SUBSCRIPTION_EXPIRED``); a trial
   past ``ends_on`` without payment → ``grace``; an active subscription past ``ends_on`` renews (new period +
   invoice) unless cancelled at period end (→ ``cancelled``). Paying reactivates (``active``).
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, text

from app.core.features import FEATURE_REGISTRY
from app.enums.saas import PLAN_DEFAULTS, TIER_ORDER
from app.models.platform import Institution, InstitutionSetting
from app.models.saas import InstitutionSubscription, SubscriptionPlan
from app.schemas.saas import (
    ChangePreviewOut,
    InvoiceOut,
    InvoicePayOut,
    InvoicePayRequest,
    ManualPayment,
    PlanIn,
    PlanOut,
    PlanUpdate,
    SubscriptionAssign,
    SubscriptionCancel,
    SubscriptionChange,
    SubscriptionOut,
    SubscriptionRenew,
)
from app.services.saas.common import (
    PlatformBase,
    conflict,
    forbidden,
    not_found,
    rule,
    today_utc,
    unprocessable,
)

LOCKED_SETTING_KEYS = ("reports.max_rows", "comms.credits")
ACTIVE_STATES = ("trial", "active", "grace")


def fy_label(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"FY{start % 100:02d}"


def cycle_days(cycle: str) -> int:
    return 30 if cycle == "monthly" else 365


def plan_price(plan: SubscriptionPlan, cycle: str) -> int:
    v = plan.price_paise_monthly if cycle == "monthly" else plan.price_paise_yearly
    return int(v or 0)


async def cache_subscription_state(institution_id: uuid.UUID, status: str | None) -> None:
    """``sub:{inst}`` read by the write gate (``SubscriptionGateMiddleware``); a Redis outage never blocks writes."""
    import contextlib

    from app.db.session import redis_client

    with contextlib.suppress(Exception):
        if status in (None, "trial", "active", "none"):
            await redis_client.delete(f"sub:{institution_id}")
        else:
            await redis_client.set(f"sub:{institution_id}", str(status), ex=7 * 86400)


class SubscriptionService(PlatformBase):
    # ---- plans (rule 1) -------------------------------------------------------------------------------------------
    async def _plan(self, plan_id: uuid.UUID, *, lock: bool = False) -> SubscriptionPlan:
        q = select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
        if lock:
            q = q.with_for_update()
        plan = (await self.db.execute(q)).scalar_one_or_none()
        if plan is None:
            raise not_found("Plan")
        return plan

    async def plan_meta(self, code: str) -> dict[str, Any]:
        meta = await self.pget(f"plan:{code}", {})
        locked = dict((meta or {}).get("locked_settings") or {})
        if not locked and code in PLAN_DEFAULTS:
            locked = {"reports.max_rows": PLAN_DEFAULTS[code]["reports.max_rows"]}
        return {"locked_settings": locked}

    async def plan_out(self, plan: SubscriptionPlan, subscribers: int = 0) -> PlanOut:
        meta = await self.plan_meta(plan.code)
        locked = dict(meta["locked_settings"])
        if plan.sms_credits is not None:
            locked.setdefault("comms.credits", {"sms": plan.sms_credits, "whatsapp": plan.sms_credits // 2})
        return PlanOut(
            id=plan.id,
            code=plan.code,
            name=plan.name,
            tier=plan.tier,
            prices={"monthly": plan.price_paise_monthly, "yearly": plan.price_paise_yearly},
            limits={
                "students": plan.student_limit,
                "staff": plan.staff_limit,
                "storage_gb": plan.storage_gb,
                "sms_credits": plan.sms_credits,
            },
            enabled_features=list(plan.enabled_features or []),
            locked_settings=locked,
            is_active=plan.is_active,
            subscribers=subscribers,
        )

    async def plans(self, *, public: bool = False) -> list[PlanOut]:
        if not public:
            self.require_platform("platform", "view")
        q = select(SubscriptionPlan).order_by(SubscriptionPlan.price_paise_monthly.asc().nulls_last())
        if public:
            q = q.where(SubscriptionPlan.is_active.is_(True))
        plans = list((await self.db.execute(q)).scalars())
        counts: dict[uuid.UUID, int] = {}
        if not public:
            counts = {
                r[0]: int(r[1])
                for r in (
                    await self.db.execute(
                        select(
                            InstitutionSubscription.plan_id,
                            func.count(func.distinct(InstitutionSubscription.institution_id)),
                        )
                        .where(InstitutionSubscription.status.in_(ACTIVE_STATES))
                        .group_by(InstitutionSubscription.plan_id)
                    )
                ).all()
            }
        return [await self.plan_out(p, counts.get(p.id, 0)) for p in plans]

    async def plan(self, plan_id: uuid.UUID) -> PlanOut:
        self.require_platform("platform", "view")
        return await self.plan_out(await self._plan(plan_id))

    def _validate_features(self, keys: list[str], tier: str, allow_above: bool) -> list[str]:
        bad = sorted(k for k in keys if k not in FEATURE_REGISTRY)
        if bad:
            raise unprocessable(f"Unknown feature keys: {', '.join(bad)}", field="enabled_features", keys=bad)
        rank = TIER_ORDER.index(tier)
        above = sorted(k for k in keys if TIER_ORDER.index(FEATURE_REGISTRY[k].min_plan_tier) > rank)
        if above and not allow_above:
            raise unprocessable(
                f"{', '.join(above)} need a higher tier than {tier} (pass allow_above_tier to override)",
                field="enabled_features",
                code="TIER",
                keys=above,
            )
        return sorted({k for k in keys if not FEATURE_REGISTRY[k].is_core})

    def _validate_locked(self, locked: dict[str, Any]) -> dict[str, Any]:
        bad = sorted(k for k in locked if k not in LOCKED_SETTING_KEYS)
        if bad:
            raise unprocessable(f"Not a plan-locked setting: {', '.join(bad)}", field="locked_settings")
        out: dict[str, Any] = {}
        for k, v in locked.items():
            if v is None:
                continue
            if k == "comms.credits":
                if not isinstance(v, dict):
                    raise unprocessable("comms.credits is {sms, whatsapp}", field="locked_settings")
                out[k] = {ch: int(n) for ch, n in v.items() if ch in ("sms", "whatsapp")}
            else:
                out[k] = int(v)
        return out

    async def create_plan(self, body: PlanIn) -> PlanOut:
        self.require_super("Creating plans")
        if (await self.db.execute(select(SubscriptionPlan.id).where(SubscriptionPlan.code == body.code))).first():
            raise conflict(f"Plan code {body.code!r} exists", field="code")
        features = self._validate_features(body.enabled_features, body.tier, body.allow_above_tier)
        plan = SubscriptionPlan(
            code=body.code,
            name=body.name,
            tier=body.tier,
            price_paise_monthly=body.price_paise_monthly,
            price_paise_yearly=body.price_paise_yearly,
            student_limit=body.student_limit,
            staff_limit=body.staff_limit,
            storage_gb=body.storage_gb,
            sms_credits=body.sms_credits,
            enabled_features=features,
            is_active=body.is_active,
        )
        self.db.add(plan)
        await self.db.flush()
        await self.pput(f"plan:{plan.code}", {"locked_settings": self._validate_locked(body.locked_settings)})
        await self.audit(
            "plan_create",
            "subscription_plan",
            plan.id,
            {"code": plan.code, "tier": plan.tier, "features": len(features)},
        )
        await self.emit(
            "plan.created",
            {"plan_id": str(plan.id), "code": plan.code},
            aggregate_type="subscription_plan",
            aggregate_id=plan.id,
        )
        return await self.plan_out(plan)

    async def update_plan(self, plan_id: uuid.UUID, body: PlanUpdate) -> PlanOut:
        self.require_super("Changing plans")
        plan = await self._plan(plan_id, lock=True)
        values = body.model_dump(
            exclude_unset=True, exclude={"allow_above_tier", "locked_settings", "enabled_features"}
        )
        old: dict[str, Any] = {}
        for k, v in values.items():
            if getattr(plan, k) != v:
                old[k] = getattr(plan, k)
                setattr(plan, k, v)
        if body.enabled_features is not None:
            features = self._validate_features(body.enabled_features, plan.tier, body.allow_above_tier)
            added = sorted(set(features) - set(plan.enabled_features or []))
            removed = sorted(set(plan.enabled_features or []) - set(features))
            if added or removed:
                old["enabled_features"] = {"added": added, "removed": removed}
                plan.enabled_features = features
        if body.locked_settings is not None:
            await self.pput(f"plan:{plan.code}", {"locked_settings": self._validate_locked(body.locked_settings)})
            old["locked_settings"] = True
        await self.db.flush()
        await self.audit(
            "plan_update",
            "subscription_plan",
            plan.id,
            {"code": plan.code, "changed": sorted(old)},
            old={k: v for k, v in old.items() if k != "locked_settings"},
        )
        await self.emit(
            "plan.updated",
            {"plan_id": str(plan.id), "code": plan.code, "changed": sorted(old)},
            aggregate_type="subscription_plan",
            aggregate_id=plan.id,
        )
        return await self.plan_out(plan)

    async def deactivate_plan(self, plan_id: uuid.UUID) -> PlanOut:
        self.require_super("Deactivating plans")
        plan = await self._plan(plan_id, lock=True)
        if not plan.is_active:
            raise conflict("The plan is already inactive")
        plan.is_active = False
        await self.db.flush()
        await self.audit("plan_deactivate", "subscription_plan", plan.id, {"code": plan.code})
        await self.emit(
            "plan.updated",
            {"plan_id": str(plan.id), "code": plan.code, "is_active": False},
            aggregate_type="subscription_plan",
            aggregate_id=plan.id,
        )
        return await self.plan_out(plan)

    # ---- current subscription ---------------------------------------------------------------------------------------
    async def current(self, institution_id: uuid.UUID, *, lock: bool = False) -> InstitutionSubscription | None:
        q = (
            select(InstitutionSubscription)
            .where(InstitutionSubscription.institution_id == institution_id)
            .order_by(InstitutionSubscription.starts_on.desc(), InstitutionSubscription.created_at.desc())
            .limit(1)
        )
        if lock:
            q = q.with_for_update()
        return (await self.db.execute(q)).scalar_one_or_none()

    async def usage_vs_limits(self, institution_id: uuid.UUID, plan: SubscriptionPlan | None) -> dict[str, Any]:
        from app.services.entitlement_service import EntitlementService

        ent = EntitlementService(self.db, None)
        students = await ent.seats_in_use(institution_id, "student")
        staff = await ent.seats_in_use(institution_id, "staff")
        meter = await ent.repo.latest_meter(institution_id)
        storage = meter.storage_bytes if meter else 0
        sms = meter.sms_sent if meter else 0
        caps = await self.tget(institution_id, "caps", {}) or {}

        def row(used: float, limit: int | None) -> dict[str, Any]:
            pct = round(used * 100 / limit, 1) if limit else None
            return {"used": used, "limit": limit, "pct": pct, "over": bool(limit and used > limit)}

        return {
            "students": row(students, plan.student_limit if plan else None),
            "staff": row(staff, plan.staff_limit if plan else None),
            "storage_gb": row(round(storage / 1024**3, 2), plan.storage_gb if plan else None),
            "sms": row(sms, plan.sms_credits if plan else None),
            "caps": caps,
        }

    async def subscription(self, institution_id: uuid.UUID | None = None) -> SubscriptionOut:
        inst = self.institution_scope(institution_id)
        if self.is_platform:
            self.require_platform("platform", "view")
            await self.audit_read(inst, "subscription")
        elif not self.can("settings", "view"):
            raise forbidden("settings:view required")
        sub = await self.current(inst)
        plan = await self._plan(sub.plan_id) if sub else None
        meta = await self.tget(inst, "subscription", {}) or {}
        return SubscriptionOut(
            id=sub.id if sub else None,
            institution_id=inst,
            plan=await self.plan_out(plan) if plan else None,
            status=sub.status if sub else "none",
            billing_cycle=sub.billing_cycle if sub else None,
            starts_on=sub.starts_on if sub else None,
            ends_on=sub.ends_on if sub else None,
            grace_until=sub.grace_until if sub else None,
            amount_paise=sub.amount_paise if sub else None,
            payment_ref=sub.payment_ref if sub else None,
            scheduled_change=meta.get("scheduled_change"),
            cancel_at_period_end=bool(meta.get("cancel_at_period_end")),
            invoices=await self.invoices(inst, _checked=True),
            usage_vs_limits=await self.usage_vs_limits(inst, plan),
            locked_settings=(await self.plan_out(plan)).locked_settings if plan else {},
        )

    # ---- change preview (rule 2) ------------------------------------------------------------------------------------
    async def change_preview(self, plan_id: uuid.UUID, institution_id: uuid.UUID) -> ChangePreviewOut:
        self.require_platform("platform", "billing")
        from app.repositories.feature_flag_repository import FeatureFlagRepository

        target = await self._plan(plan_id)
        sub = await self.current(institution_id)
        old_plan = await self._plan(sub.plan_id) if sub else None
        flags = await FeatureFlagRepository(self.db).flags(institution_id)
        new_keys = set(target.enabled_features or [])
        disabled: list[dict[str, Any]] = []
        kept: list[str] = []
        enabled_now = {k for k, r in flags.items() if r.platform_enabled}
        for key, row in sorted(flags.items()):
            if row.source == "override":
                kept.append(key)
                continue
            if (
                row.platform_enabled
                and key not in new_keys
                and key in FEATURE_REGISTRY
                and not FEATURE_REGISTRY[key].is_core
            ):
                dependants = sorted(
                    k for k, f in FEATURE_REGISTRY.items() if key in (f.depends_on or ()) and k in enabled_now
                )
                disabled.append({"key": key, "name": FEATURE_REGISTRY[key].name, "dependants": dependants})
        enabled = sorted(k for k in new_keys if k not in enabled_now)
        violations = await self.limit_violations(institution_id, target)
        proration = self.proration(sub, old_plan, target)
        return ChangePreviewOut(
            institution_id=institution_id,
            from_plan=old_plan.code if old_plan else None,
            to_plan=target.code,
            features_disabled=disabled,
            features_enabled=enabled,
            overrides_kept=kept,
            limit_violations=violations,
            proration=proration,
            allowed=not violations,
        )

    async def limit_violations(self, institution_id: uuid.UUID, plan: SubscriptionPlan) -> list[dict[str, Any]]:
        usage = await self.usage_vs_limits(institution_id, plan)
        out = []
        for kind in ("students", "staff", "storage_gb"):
            r = usage[kind]
            if r["limit"] is not None and r["used"] > r["limit"]:
                out.append({"kind": kind, "current": r["used"], "limit": r["limit"]})
        return out

    def proration(
        self, sub: InstitutionSubscription | None, old: SubscriptionPlan | None, new: SubscriptionPlan
    ) -> dict[str, Any]:
        today = today_utc()
        if sub is None or sub.ends_on is None or sub.ends_on <= today or sub.status == "trial":
            return {"remaining_days": 0, "period_days": 0, "credit_paise": 0, "charge_paise": 0, "net_paise": 0}
        period = max((sub.ends_on - sub.starts_on).days, 1)
        remaining = (sub.ends_on - today).days
        cycle = sub.billing_cycle or "yearly"
        credit = round(plan_price(old, cycle) * remaining / period) if old else 0
        charge = round(plan_price(new, cycle) * remaining / period)
        return {
            "remaining_days": remaining,
            "period_days": period,
            "credit_paise": credit,
            "charge_paise": charge,
            "net_paise": charge - credit,
        }

    # ---- assign / change / renew / cancel (rule 3) ------------------------------------------------------------------
    async def assign(self, institution_id: uuid.UUID, body: SubscriptionAssign) -> SubscriptionOut:
        self.require_platform("platform", "billing")
        if self.is_support:
            raise forbidden("Support agents cannot change subscriptions")
        inst = await self.institution(institution_id, lock=True)
        plan = await self._plan(body.plan_id)
        if not plan.is_active:
            raise rule("The plan is inactive")
        current = await self.current(inst.id, lock=True)
        starts = body.starts_on or today_utc()
        trial = bool(body.trial_days)
        ends = starts + timedelta(days=body.trial_days if trial else cycle_days(body.billing_cycle))  # type: ignore[arg-type]
        if current is not None and current.status in ACTIVE_STATES:
            current.status = "cancelled"
            current.ends_on = min(current.ends_on or starts, starts)
        sub = InstitutionSubscription(
            institution_id=inst.id,
            plan_id=plan.id,
            starts_on=starts,
            ends_on=ends,
            billing_cycle=body.billing_cycle,
            status="trial" if trial else "active",
            payment_ref=body.payment_ref,
            amount_paise=0
            if trial
            else (body.amount_paise if body.amount_paise is not None else plan_price(plan, body.billing_cycle)),
        )
        self.db.add(sub)
        await self.db.flush()
        if not trial and (sub.amount_paise or 0) > 0:
            inv = await self.issue_invoice(
                inst, sub, plan, "subscription", [(f"{plan.name} — {body.billing_cycle}", sub.amount_paise or 0)]
            )
            if body.payment_ref:
                await self._mark_paid(inst.id, inv["number"], body.payment_ref, today_utc())
        await self._after_plan_change(inst, plan, "assigned", {"subscription_id": str(sub.id), "trial": trial})
        await self.audit(
            "subscription_assign",
            "institution_subscription",
            sub.id,
            {"plan": plan.code, "status": sub.status, "cycle": sub.billing_cycle, "ends_on": ends},
            institution_id=inst.id,
        )
        return await self.subscription(inst.id)

    async def start_trial(
        self, inst: Institution, plan: SubscriptionPlan, *, days: int | None = None, cycle: str = "yearly"
    ) -> InstitutionSubscription:
        """Onboarding / self-serve registration: a trial without an invoice (``billing.trial_days``)."""
        days = days or int(await self.setting("billing", "trial_days") or 30)
        today = today_utc()
        sub = InstitutionSubscription(
            institution_id=inst.id,
            plan_id=plan.id,
            starts_on=today,
            ends_on=today + timedelta(days=days),
            billing_cycle=cycle,
            status="trial",
            amount_paise=0,
        )
        self.db.add(sub)
        await self.db.flush()
        await self.emit(
            "subscription.assigned",
            {"institution_id": str(inst.id), "plan": plan.code, "status": "trial", "ends_on": sub.ends_on},
            institution_id=inst.id,
            aggregate_type="institution_subscription",
            aggregate_id=sub.id,
        )
        await self.notify_tenant_admins(
            inst.id, "saas.trial_started", {"institution": inst.name, "plan": plan.name, "ends_on": str(sub.ends_on)}
        )
        return sub

    async def change(self, institution_id: uuid.UUID, body: SubscriptionChange) -> SubscriptionOut:
        self.require_platform("platform", "billing")
        if self.is_support:
            raise forbidden("Support agents cannot change subscriptions")
        inst = await self.institution(institution_id, lock=True)
        sub = await self.current(inst.id, lock=True)
        if sub is None or sub.status not in ACTIVE_STATES:
            raise rule("No running subscription to change — assign one first")
        target = await self._plan(body.plan_id)
        if not target.is_active:
            raise rule("The plan is inactive")
        if target.id == sub.plan_id:
            raise conflict("The institution is already on this plan")
        old = await self._plan(sub.plan_id)
        violations = await self.limit_violations(inst.id, target)
        if violations:
            raise rule(
                "The institution exceeds the limits of the new plan",
                code="PLAN_LIMITS",
                violations=violations,
            )
        if body.effective == "next_cycle":
            meta = await self.tget(inst.id, "subscription", {}) or {}
            meta["scheduled_change"] = {
                "plan_id": str(target.id),
                "plan": target.code,
                "effective_on": str(sub.ends_on),
            }
            await self.tput(inst.id, "subscription", meta)
            await self.audit(
                "subscription_schedule_change",
                "institution_subscription",
                sub.id,
                {"from": old.code, "to": target.code, "on": sub.ends_on},
                institution_id=inst.id,
            )
            return await self.subscription(inst.id)
        proration = self.proration(sub, old, target)
        sub.plan_id = target.id
        if sub.status != "trial":
            sub.amount_paise = plan_price(target, sub.billing_cycle)
        await self.db.flush()
        invoice = None
        if proration["net_paise"] > 0 and await self.setting("billing", "proration"):
            invoice = await self.issue_invoice(
                inst,
                sub,
                target,
                "proration",
                [
                    (
                        f"{target.name}: {proration['remaining_days']} of {proration['period_days']} days",
                        proration["charge_paise"],
                    ),
                    (f"Credit {old.name}: unused {proration['remaining_days']} days", -proration["credit_paise"]),
                ],
            )
        elif proration["net_paise"] < 0:
            meta = await self.tget(inst.id, "subscription", {}) or {}
            meta["credit_paise"] = int(meta.get("credit_paise") or 0) - proration["net_paise"]
            await self.tput(inst.id, "subscription", meta)
        await self._after_plan_change(inst, target, "changed", {"from": old.code, "proration": proration})
        await self.audit(
            "subscription_change",
            "institution_subscription",
            sub.id,
            {
                "from": old.code,
                "to": target.code,
                "proration": proration,
                "invoice": invoice["number"] if invoice else None,
            },
            old={"plan": old.code},
            institution_id=inst.id,
        )
        return await self.subscription(inst.id)

    async def _after_plan_change(
        self, inst: Institution, plan: SubscriptionPlan, verb: str, extra: dict[str, Any]
    ) -> None:
        from app.services.feature_service import FeatureService

        await FeatureService(self.db, self.principal).apply_plan_defaults(inst.id, self.request)
        await self.apply_locked_settings(inst.id, plan)
        sub = await self.current(inst.id)
        await cache_subscription_state(inst.id, sub.status if sub else None)
        payload = {"institution_id": str(inst.id), "plan": plan.code, **extra}
        await self.emit(
            f"subscription.{verb}",
            payload,
            institution_id=inst.id,
            aggregate_type="institution_subscription",
            aggregate_id=sub.id if sub else None,
        )
        if verb != "changed":  # Phase 02 consumers (entitlements / flag cache) listen to subscription.changed
            await self.emit(
                "subscription.changed",
                payload,
                institution_id=inst.id,
                aggregate_type="institution_subscription",
                aggregate_id=sub.id if sub else None,
            )

    async def apply_locked_settings(self, institution_id: uuid.UUID, plan: SubscriptionPlan) -> dict[str, Any]:
        """Write the plan-locked settings (Phase 37 ``locked_by=plan``) into the tenant's institution settings."""
        locked = (await self.plan_out(plan)).locked_settings
        caps = await self.tget(institution_id, "caps", {}) or {}
        for full, value in locked.items():
            if value is None:
                continue
            category, _, key = full.partition(".")
            if full == "comms.credits" and isinstance(value, dict):  # tenant SMS / WhatsApp caps tighten the plan
                value = {
                    ch: min(int(n), int(caps[c])) if caps.get(c) is not None else int(n)
                    for ch, n in value.items()
                    for c in [f"{ch}_per_month"]
                }
            await self.write_setting(institution_id, category, key, value)
        return locked

    async def write_setting(self, institution_id: uuid.UUID, category: str, key: str, value: Any) -> None:
        """Institution-wide setting row written by the platform (plan-locked keys bypass the tenant settings API)."""
        row = (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == institution_id,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == category,
                    InstitutionSetting.key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            self.db.add(
                InstitutionSetting(
                    institution_id=institution_id,
                    college_id=None,
                    category=category,
                    key=key,
                    value=value,
                    value_type="json" if isinstance(value, dict | list) else "int",
                    updated_by=self.actor_id,
                )
            )
        else:
            row.value, row.updated_by = value, self.actor_id
        await self.db.flush()

    async def renew(self, institution_id: uuid.UUID, body: SubscriptionRenew) -> SubscriptionOut:
        self.require_platform("platform", "billing")
        if self.is_support:
            raise forbidden("Support agents cannot renew subscriptions")
        inst = await self.institution(institution_id, lock=True)
        await self.renew_now(inst, body.billing_cycle, body.payment_ref)
        return await self.subscription(inst.id)

    async def renew_now(
        self, inst: Institution, cycle: str | None = None, payment_ref: str | None = None
    ) -> InstitutionSubscription:
        sub = await self.current(inst.id, lock=True)
        if sub is None:
            raise rule("No subscription to renew — assign one first")
        meta = await self.tget(inst.id, "subscription", {}) or {}
        plan = (
            await self._plan(uuid.UUID(meta["scheduled_change"]["plan_id"]))
            if meta.get("scheduled_change")
            else await self._plan(sub.plan_id)
        )
        cycle = cycle or sub.billing_cycle or "yearly"
        today = today_utc()
        # renewing ahead of the end keeps the paid period; a lapsed (grace / expired / cancelled) one restarts today
        running = sub.status in ("active", "trial") and sub.ends_on is not None and sub.ends_on >= today
        start = sub.ends_on if running and sub.ends_on else today
        if not running and sub.status in ACTIVE_STATES:
            sub.status, sub.ends_on = "cancelled", today
        new = InstitutionSubscription(
            institution_id=inst.id,
            plan_id=plan.id,
            starts_on=start,
            ends_on=start + timedelta(days=cycle_days(cycle)),
            billing_cycle=cycle,
            status="active",
            amount_paise=plan_price(plan, cycle),
            payment_ref=payment_ref,
        )
        self.db.add(new)
        await self.db.flush()
        meta.pop("scheduled_change", None)
        meta.pop("cancel_at_period_end", None)
        credit = int(meta.pop("credit_paise", 0) or 0)
        await self.tput(inst.id, "subscription", meta)
        lines = [(f"{plan.name} — {cycle} ({new.starts_on} – {new.ends_on})", new.amount_paise or 0)]
        if credit:
            lines.append(("Credit carried forward", -min(credit, new.amount_paise or 0)))
        inv = await self.issue_invoice(inst, new, plan, "subscription", lines)
        if payment_ref:
            await self._mark_paid(inst.id, inv["number"], payment_ref, today)
        await self._after_plan_change(inst, plan, "renewed", {"subscription_id": str(new.id), "invoice": inv["number"]})
        await self.audit(
            "subscription_renew",
            "institution_subscription",
            new.id,
            {"plan": plan.code, "cycle": cycle, "invoice": inv["number"]},
            institution_id=inst.id,
        )
        await self.notify_tenant_admins(
            inst.id, "saas.subscription_renewed", {"plan": plan.name, "ends_on": str(new.ends_on)}
        )
        return new

    async def cancel(self, institution_id: uuid.UUID, body: SubscriptionCancel) -> SubscriptionOut:
        self.require_platform("platform", "billing")
        if self.is_support:
            raise forbidden("Support agents cannot cancel subscriptions")
        inst = await self.institution(institution_id, lock=True)
        sub = await self.current(inst.id, lock=True)
        if sub is None or sub.status not in ACTIVE_STATES:
            raise rule("No running subscription to cancel")
        if body.at_period_end:
            meta = await self.tget(inst.id, "subscription", {}) or {}
            meta["cancel_at_period_end"] = True
            meta["cancel_reason"] = body.reason
            await self.tput(inst.id, "subscription", meta)
        else:
            sub.status = "cancelled"
            sub.ends_on = today_utc()
            await self.db.flush()
            await cache_subscription_state(inst.id, "cancelled")
            await self.emit(
                "subscription.cancelled",
                {"institution_id": str(inst.id), "reason": body.reason},
                institution_id=inst.id,
                aggregate_type="institution_subscription",
                aggregate_id=sub.id,
            )
        await self.audit(
            "subscription_cancel",
            "institution_subscription",
            sub.id,
            {"reason": body.reason, "at_period_end": body.at_period_end},
            institution_id=inst.id,
        )
        return await self.subscription(inst.id)

    # ---- invoices (rule 4) ------------------------------------------------------------------------------------------
    async def issue_invoice(
        self,
        inst: Institution,
        sub: InstitutionSubscription | None,
        plan: SubscriptionPlan | None,
        kind: str,
        lines: list[tuple[str, int]],
        period: str | None = None,
    ) -> dict[str, Any]:
        billing = await self.setting("billing")
        today = today_utc()
        fy = fy_label(today)
        seq = await self.next_sequence(f"inv:{fy}")
        number = f"{billing.get('invoice_prefix') or 'INV'}/{fy}/{seq}"
        net = max(sum(a for _, a in lines), 0)
        gst_pct = float(billing.get("gst_pct") or 0)
        gst = round(net * gst_pct / 100)
        period = period or (f"{sub.starts_on:%Y-%m}" if sub else f"{today:%Y-%m}")
        doc = {
            "number": number,
            "institution_id": str(inst.id),
            "institution_name": inst.name,
            "institution_gstin": inst.gstin,
            "subscription_id": str(sub.id) if sub else None,
            "period": period,
            "kind": kind,
            "plan": plan.code if plan else None,
            "lines": [{"description": d, "amount_paise": a} for d, a in lines],
            "amount_paise": net,
            "gst_pct": gst_pct,
            "gst_paise": gst,
            "total_paise": net + gst,
            "status": "issued",
            "issued_on": str(today),
            "due_on": str(today + timedelta(days=int(billing.get("due_days") or 15))),
            "paid_on": None,
            "payment_ref": None,
            "pdf_key": None,
            "dunning": [],
        }
        doc["pdf_key"] = await self.render_invoice_pdf(doc, billing)
        await self.tput(inst.id, f"invoice:{number}", doc)
        await self.emit(
            "invoice.issued",
            {"number": number, "total_paise": net + gst, "kind": kind},
            institution_id=inst.id,
            aggregate_type="invoice",
        )
        await self.notify_tenant_admins(
            inst.id,
            "saas.invoice_issued",
            {"number": number, "amount": f"{(net + gst) / 100:,.2f}", "due_on": doc["due_on"]},
            ["in_app", "email"],
        )
        return doc

    async def render_invoice_pdf(self, doc: dict[str, Any], billing: dict[str, Any] | None = None) -> str | None:
        """Phase 36 renderer (platform letterhead + tenant GSTIN) → ``platform/invoices/{inst}/{period}-{seq}.pdf``."""
        import contextlib

        from app.core.files import get_storage
        from app.core.reports import ReportColumn
        from app.services.reports.render_service import render_pdf

        billing = billing or await self.setting("billing")
        cols = [
            ReportColumn("description", "Description"),
            ReportColumn("amount_paise", "Amount (₹)", "money", total=True),
        ]
        summary = [
            ("Invoice", doc["number"]),
            ("Billed to", f"{doc['institution_name']} (GSTIN {doc.get('institution_gstin') or '—'})"),
            ("Period", doc["period"]),
            ("Issued / due", f"{doc['issued_on']} / {doc['due_on']}"),
            ("Net", f"₹ {doc['amount_paise'] / 100:,.2f}"),
            (f"GST {doc['gst_pct']:g}%", f"₹ {doc['gst_paise'] / 100:,.2f}"),
            ("Total", f"₹ {doc['total_paise'] / 100:,.2f}"),
            ("Status", doc["status"]),
        ]
        header = {
            "institution": f"{billing.get('legal_name') or 'SeptronUniverse'} · GSTIN {billing.get('gstin') or '—'}",
            "address": billing.get("address"),
            "scope": "Tax invoice",
        }
        pdf = render_pdf("Tax invoice", cols, list(doc["lines"]), header=header, summary=summary)
        key = f"platform/invoices/{doc['institution_id']}/{doc['period']}-{doc['number'].rsplit('/', 1)[-1]}.pdf"
        with contextlib.suppress(Exception):  # storage outage: the PDF is rendered again on download
            await get_storage().put(key, pdf, "application/pdf")
            return key
        return None

    def invoice_out(self, doc: dict[str, Any]) -> InvoiceOut:
        from app.core.files import get_storage

        url = None
        if doc.get("pdf_key"):
            try:
                url = get_storage().signed_url(doc["pdf_key"], ttl=3600)
            except Exception:  # noqa: BLE001 - a URL is a convenience; download re-renders
                url = None
        return InvoiceOut(
            number=doc["number"],
            institution_id=uuid.UUID(str(doc["institution_id"])),
            institution_name=doc.get("institution_name"),
            period=doc.get("period") or "",
            kind=doc.get("kind") or "subscription",
            plan=doc.get("plan"),
            lines=list(doc.get("lines") or []),
            amount_paise=int(doc.get("amount_paise") or 0),
            gst_paise=int(doc.get("gst_paise") or 0),
            total_paise=int(doc.get("total_paise") or 0),
            status=doc.get("status") or "issued",
            issued_on=date.fromisoformat(str(doc["issued_on"])),
            due_on=date.fromisoformat(str(doc["due_on"])),
            paid_on=date.fromisoformat(str(doc["paid_on"])) if doc.get("paid_on") else None,
            payment_ref=doc.get("payment_ref"),
            pdf_url=url,
            dunning=list(doc.get("dunning") or []),
        )

    async def invoices(self, institution_id: uuid.UUID | None = None, *, _checked: bool = False) -> list[InvoiceOut]:
        inst = self.institution_scope(institution_id)
        if not _checked:
            if self.is_platform:
                self.require_platform("platform", "view")
                await self.audit_read(inst, "invoices")
            elif not self.can("settings", "view"):
                raise forbidden("settings:view required")
        docs = [v for _, _, v in await self.tlist("invoice:", inst) if isinstance(v, dict)]
        docs.sort(key=lambda d: (str(d.get("issued_on")), str(d.get("number"))), reverse=True)
        return [self.invoice_out(d) for d in docs]

    async def all_invoices(
        self, status: str | None = None, institution_id: uuid.UUID | None = None
    ) -> list[InvoiceOut]:
        self.require_platform("platform", "view")
        docs = [v for _, _, v in await self.tlist("invoice:", institution_id) if isinstance(v, dict)]
        if status:
            docs = [d for d in docs if d.get("status") == status]
        docs.sort(key=lambda d: (str(d.get("issued_on")), str(d.get("number"))), reverse=True)
        return [self.invoice_out(d) for d in docs[:2000]]

    async def _invoice(self, institution_id: uuid.UUID, number: str) -> dict[str, Any]:
        doc = await self.tget(institution_id, f"invoice:{number}")
        if not isinstance(doc, dict):
            raise not_found("Invoice")
        return dict(doc)

    async def invoice_pdf(self, number: str, institution_id: uuid.UUID | None = None) -> bytes:
        from app.core.files import get_storage

        inst = self.institution_scope(institution_id)
        if not self.is_platform and not self.can("settings", "view"):
            raise forbidden("settings:view required")
        doc = await self._invoice(inst, number)
        if doc.get("pdf_key"):
            try:
                return await get_storage().get(doc["pdf_key"])
            except Exception:  # noqa: BLE001 - re-render below
                pass
        key = await self.render_invoice_pdf(doc)
        doc["pdf_key"] = key
        await self.tput(inst, f"invoice:{number}", doc)
        if key:
            return await get_storage().get(key)
        from app.services.reports.render_service import render_pdf

        return render_pdf("Tax invoice", [], [], summary=[("Invoice", number)])

    async def generate_period(
        self, period: str | None = None, institution_id: uuid.UUID | None = None
    ) -> dict[str, Any]:
        """Beat ``billing.invoices_monthly`` / ``POST …/invoices/generate``: monthly-cycle subscriptions without an
        invoice for the period get one (yearly ones are invoiced at assign / renewal)."""
        today = today_utc()
        period = period or f"{today:%Y-%m}"
        subs = (
            await self.db.execute(
                select(InstitutionSubscription).where(
                    InstitutionSubscription.status.in_(("active", "grace")),
                    InstitutionSubscription.billing_cycle == "monthly",
                    *([InstitutionSubscription.institution_id == institution_id] if institution_id else []),
                )
            )
        ).scalars()
        issued = 0
        for sub in subs:
            existing = [
                v
                for _, _, v in await self.tlist("invoice:", sub.institution_id)
                if isinstance(v, dict) and v.get("period") == period and v.get("kind") == "subscription"
            ]
            if existing:
                continue
            inst = await self.institution(sub.institution_id)
            plan = await self._plan(sub.plan_id)
            await self.issue_invoice(
                inst,
                sub,
                plan,
                "subscription",
                [(f"{plan.name} — {period}", plan_price(plan, "monthly"))],
                period=period,
            )
            issued += 1
        return {"period": period, "issued": issued}

    # ---- payment ----------------------------------------------------------------------------------------------------
    async def pay(self, number: str, body: InvoicePayRequest, institution_id: uuid.UUID | None = None) -> InvoicePayOut:
        inst = self.institution_scope(institution_id)
        if self.is_platform:
            self.require_platform("platform", "billing")
            if self.is_support:
                raise forbidden("Support agents cannot record payments")
        elif not self.can("settings", "manage") or "institution_admin" not in (
            getattr(self.principal, "roles", None) or []
        ):
            raise forbidden("Only the institution admin pays invoices")
        doc = await self._invoice(inst, number)
        if doc.get("status") == "paid":
            raise conflict("The invoice is already paid")
        if body.mode == "manual":
            if not self.is_platform:
                raise forbidden("Manual payment references are recorded by platform billing")
            manual: ManualPayment = body.manual or ManualPayment(payment_ref="manual")
            doc = await self._mark_paid(inst, number, manual.payment_ref, manual.paid_on or today_utc())
            return InvoicePayOut(number=number, status=doc["status"])
        order = await self.gateway_order(
            int(doc["total_paise"]), number, {"kind": "invoice", "institution_id": str(inst), "number": number}
        )
        doc["gateway_order"] = order["order_id"]
        await self.tput(inst, f"invoice:{number}", doc)
        await self.audit(
            "invoice_pay_start",
            "invoice",
            None,
            {"number": number, "order_id": order["order_id"]},
            institution_id=inst,
            module="settings" if not self.is_platform else None,
        )
        return InvoicePayOut(number=number, status=doc["status"], order=order)

    async def gateway_order(self, amount_paise: int, receipt: str, mapping: dict[str, Any]) -> dict[str, Any]:
        from app.integrations.registry import get_adapter

        provider = str(await self.setting("billing", "gateway") or "mock")
        gw = get_adapter("payment", provider)
        order = await gw.create_order(amount_paise=amount_paise, receipt=receipt[:40])
        await self.pput(f"order:{order['order_id']}", {**mapping, "amount_paise": amount_paise, "provider": provider})
        return dict(order)

    async def gateway_webhook(
        self, order_id: str, payment_ref: str, status: str, body: bytes, signature: str
    ) -> dict[str, Any]:
        """Platform gateway webhook (public route; signature verified with the provider adapter)."""
        from app.integrations.registry import get_adapter

        mapping = await self.pget(f"order:{order_id}")
        if not isinstance(mapping, dict):
            raise not_found("Order")
        gw = get_adapter("payment", str(mapping.get("provider") or "mock"))
        if not gw.verify_webhook(body=body, signature=signature):
            raise forbidden("Invalid webhook signature")
        await self.emit(
            "payment.webhook",
            {"order_id": order_id, "status": status, "kind": mapping.get("kind")},
            aggregate_type="platform_order",
        )
        if status != "paid":
            return {"order_id": order_id, "status": status}
        if mapping.get("kind") == "invoice":
            doc = await self._mark_paid(
                uuid.UUID(mapping["institution_id"]), mapping["number"], payment_ref, today_utc()
            )
            return {"order_id": order_id, "status": doc["status"]}
        if mapping.get("kind") == "registration":
            from app.services.saas.registration_service import RegistrationService

            return await RegistrationService(self.db, None, self.request).paid(
                uuid.UUID(mapping["registration_id"]), payment_ref
            )
        return {"order_id": order_id, "status": status}

    async def _mark_paid(
        self, institution_id: uuid.UUID, number: str, payment_ref: str, paid_on: date
    ) -> dict[str, Any]:
        doc = await self._invoice(institution_id, number)
        if doc.get("status") == "paid":
            return doc
        doc.update(status="paid", paid_on=str(paid_on), payment_ref=payment_ref)
        doc["pdf_key"] = await self.render_invoice_pdf(doc)
        await self.tput(institution_id, f"invoice:{number}", doc)
        sub = await self.current(institution_id, lock=True)
        if sub is not None:
            sub.payment_ref = payment_ref
            if sub.status in ("grace", "expired", "trial"):
                was = sub.status
                if was == "trial":
                    sub.starts_on = today_utc()
                    sub.ends_on = today_utc() + timedelta(days=cycle_days(sub.billing_cycle))
                sub.status, sub.grace_until = "active", None
                await self.emit(
                    "subscription.renewed",
                    {"institution_id": str(institution_id), "from": was},
                    institution_id=institution_id,
                    aggregate_type="institution_subscription",
                    aggregate_id=sub.id,
                )
                await self.emit(
                    "subscription.changed",
                    {"institution_id": str(institution_id), "status": "active"},
                    institution_id=institution_id,
                    aggregate_type="institution_subscription",
                    aggregate_id=sub.id,
                )
            await self.db.flush()
            await cache_subscription_state(institution_id, sub.status)
        await self.audit(
            "invoice_paid",
            "invoice",
            None,
            {"number": number, "payment_ref": payment_ref, "paid_on": paid_on},
            institution_id=institution_id,
        )
        await self.emit(
            "invoice.paid",
            {"number": number, "payment_ref": payment_ref},
            institution_id=institution_id,
            aggregate_type="invoice",
        )
        await self.notify_tenant_admins(
            institution_id, "saas.invoice_paid", {"number": number, "amount": f"{int(doc['total_paise']) / 100:,.2f}"}
        )
        return doc

    # ---- dunning / state machine (rule 5) ---------------------------------------------------------------------------
    async def dunning(self, today: date | None = None) -> dict[str, int]:
        today = today or today_utc()
        counts = {"reminders": 0, "overdue": 0}
        for inst_id, number, doc in await self.tlist("invoice:"):
            if not isinstance(doc, dict) or doc.get("status") not in ("issued", "overdue"):
                continue
            due = date.fromisoformat(str(doc["due_on"]))
            stages = {d.get("stage") for d in doc.get("dunning") or []}
            stage = None
            if today >= due + timedelta(days=7) and "due+7" not in stages:
                stage = "due+7"
            elif today >= due and "due" not in stages:
                stage = "due"
            elif today >= due - timedelta(days=7) and "due-7" not in stages and today < due:
                stage = "due-7"
            changed = False
            if today > due and doc.get("status") == "issued":
                doc["status"] = "overdue"
                changed = True
                counts["overdue"] += 1
                await self.emit(
                    "invoice.overdue",
                    {"number": number, "due_on": str(due)},
                    institution_id=inst_id,
                    aggregate_type="invoice",
                )
            if stage:
                doc.setdefault("dunning", []).append({"stage": stage, "at": str(today)})
                changed = True
                counts["reminders"] += 1
                await self.notify_tenant_admins(
                    inst_id,
                    "saas.invoice_overdue" if stage != "due-7" else "saas.invoice_issued",
                    {"number": number, "amount": f"{int(doc['total_paise']) / 100:,.2f}", "due_on": str(due)},
                    ["in_app", "email"],
                )
            if changed:
                await self.tput(inst_id, f"invoice:{number}", doc)
        return counts

    async def state_machine(self, today: date | None = None) -> dict[str, int]:
        today = today or today_utc()
        grace_days = int(await self.setting("billing", "grace_days") or 15)
        counts = {"grace": 0, "expired": 0, "renewed": 0, "cancelled": 0}
        latest = (
            select(InstitutionSubscription.id)
            .distinct(InstitutionSubscription.institution_id)
            .order_by(
                InstitutionSubscription.institution_id,
                InstitutionSubscription.starts_on.desc(),
                InstitutionSubscription.created_at.desc(),
            )
        )
        subs = list(
            (
                await self.db.execute(
                    select(InstitutionSubscription).where(InstitutionSubscription.id.in_(latest)).with_for_update()
                )
            ).scalars()
        )
        overdue_by_inst: dict[uuid.UUID, date] = {}
        for inst_id, _, doc in await self.tlist("invoice:"):
            if isinstance(doc, dict) and doc.get("status") in ("issued", "overdue"):
                due = date.fromisoformat(str(doc["due_on"]))
                overdue_by_inst[inst_id] = min(overdue_by_inst.get(inst_id, due), due)
        for sub in subs:
            inst = await self.db.get(Institution, sub.institution_id)
            if inst is None or inst.status in ("archived",):
                continue
            meta = await self.tget(sub.institution_id, "subscription", {}) or {}
            oldest_due = overdue_by_inst.get(sub.institution_id)
            if sub.status == "grace" and sub.grace_until and today > sub.grace_until:
                await self._transition(sub, "expired", inst)
                counts["expired"] += 1
            elif (
                sub.status == "active"
                and oldest_due
                and today >= oldest_due + timedelta(days=7)
                or sub.status == "trial"
                and sub.ends_on
                and today > sub.ends_on
            ):
                sub.grace_until = today + timedelta(days=grace_days)
                await self._transition(sub, "grace", inst)
                counts["grace"] += 1
            elif sub.status == "active" and sub.ends_on and today >= sub.ends_on:
                if meta.get("cancel_at_period_end"):
                    await self._transition(sub, "cancelled", inst)
                    counts["cancelled"] += 1
                else:
                    await self.renew_now(inst)
                    counts["renewed"] += 1
            elif sub.status == "trial" and sub.ends_on and (sub.ends_on - today).days in (7, 1):
                await self.notify_tenant_admins(
                    inst.id,
                    "saas.trial_ending",
                    {"institution": inst.name, "ends_on": str(sub.ends_on)},
                    ["in_app", "email"],
                )
        return counts

    async def _transition(self, sub: InstitutionSubscription, status: str, inst: Institution) -> None:
        old = sub.status
        sub.status = status
        await self.db.flush()
        await cache_subscription_state(inst.id, status)
        await self.audit(
            "subscription_state",
            "institution_subscription",
            sub.id,
            {"from": old, "to": status, "grace_until": sub.grace_until},
            institution_id=inst.id,
        )
        await self.emit(
            f"subscription.{status}",
            {"institution_id": str(inst.id), "from": old, "grace_until": sub.grace_until},
            institution_id=inst.id,
            aggregate_type="institution_subscription",
            aggregate_id=sub.id,
        )
        await self.emit(
            "subscription.changed",
            {"institution_id": str(inst.id), "status": status},
            institution_id=inst.id,
            aggregate_type="institution_subscription",
            aggregate_id=sub.id,
        )
        template = {"grace": "saas.subscription_grace", "expired": "saas.subscription_expired"}.get(status)
        if template:
            await self.notify_tenant_admins(
                inst.id,
                template,
                {"institution": inst.name, "grace_until": str(sub.grace_until or "")},
                ["in_app", "email"],
            )

    async def refresh_state_cache(self) -> int:
        rows = (
            await self.db.execute(
                text(
                    "SELECT DISTINCT ON (institution_id) institution_id, status FROM institution_subscriptions "
                    "ORDER BY institution_id, starts_on DESC, created_at DESC"
                )
            )
        ).all()
        for inst_id, status in rows:
            await cache_subscription_state(inst_id, status)
        return len(rows)

    async def mrr(self) -> tuple[int, dict[str, int]]:
        """MRR (paise) of active / grace subscriptions normalised monthly, and the count per plan code."""
        rows = (
            await self.db.execute(
                text(
                    "SELECT DISTINCT ON (s.institution_id) s.status, s.billing_cycle, s.amount_paise, p.code, "
                    "p.price_paise_monthly, p.price_paise_yearly FROM institution_subscriptions s "
                    "JOIN subscription_plans p ON p.id = s.plan_id JOIN institutions i ON i.id = s.institution_id "
                    "WHERE i.deleted_at IS NULL ORDER BY s.institution_id, s.starts_on DESC, s.created_at DESC"
                )
            )
        ).all()
        total = 0
        by_plan: dict[str, int] = {}
        for status, cycle, amount, code, pm, py in rows:
            by_plan[code] = by_plan.get(code, 0) + 1
            if status not in ("active", "grace"):
                continue
            if cycle == "monthly":
                total += int(amount if amount is not None else pm or 0)
            else:
                total += round(int(amount if amount is not None else py or 0) / 12)
        return total, by_plan
