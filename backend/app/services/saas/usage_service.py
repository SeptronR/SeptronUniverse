"""Usage metering, caps and overage — Prompts/38 §38.6 ``usage_service`` (replaces the Phase 02 ``usage.meter``).

Business rules
1. **Meter** (``usage.meter_month`` on the 1st for the previous month, ``usage.meter_incremental`` daily for the
   current one; ``POST /platform/usage/meter`` as a job): per tenant, ``usage_meters`` upsert of active students /
   staff (Phase 02 seat counts), storage bytes (file service counter per tenant prefix), SMS / WhatsApp / e-mails sent
   in the month (Phase 24 ``message_logs`` by channel, status not failed), API calls (request counters
   ``api:{institution}:{yyyymmdd}`` in Redis, summed over the month's days); AI tokens (Phase 24 assistant usage, an
   estimate of 800 tokens per message when the provider reports none), cost and overage go to
   ``saas_meta usage:<yyyy-mm>`` (no columns for them). Cost = rates (``usage.rates``, paise) × SMS / WhatsApp /
   e-mail counts + AI tokens per 1k + storage above the plan allowance per GB.
2. **Caps** (``saas_meta caps``, defaults ``usage.caps_default``): ``api_calls_per_day`` is enforced by the request
   middleware (``apicap:{inst}`` cached in Redis → 429 ``RATE_LIMITED`` + ``/auth/me`` banner); SMS / WhatsApp caps
   tighten the Phase 24 credits (``comms.credits`` → 409 ``CREDITS_INSUFFICIENT`` on send).
3. **Overage alerts** at ``usage.overage_alert_pct`` and at 100 % of a plan limit or cap → ``usage.overage`` event,
   ``saas.usage_overage`` to the tenant's institution admins and the super admins; once per metric per month.
4. Platform list / totals / CSV export (Phase 36 ``render_service.render_csv``); tenants read their own months.
"""

import contextlib
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, text

from app.enums.saas import CAP_KEYS
from app.models.platform import Institution
from app.models.saas import UsageMeter
from app.schemas.saas import UsageCapsIn, UsageMonth, UsageOut
from app.services.saas.common import PlatformBase, forbidden, today_utc, unprocessable

AI_TOKENS_PER_MESSAGE = 800
LIMIT_FIELDS = {"active_students": "student_limit", "active_staff": "staff_limit", "sms_sent": "sms_credits"}


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def parse_month(v: str | None, default: date) -> date:
    if not v:
        return default
    try:
        return date.fromisoformat(f"{v}-01" if len(v) == 7 else v).replace(day=1)
    except ValueError as exc:
        raise unprocessable("Months are YYYY-MM", field="month") from exc


async def api_counter_incr(institution_id: str, day: str) -> int:
    from app.db.session import redis_client

    key = f"api:{institution_id}:{day}"
    n = int(await redis_client.incr(key))
    if n == 1:
        await redis_client.expire(key, 40 * 86400)
    return n


class UsageService(PlatformBase):
    # ---- metering (rule 1) ------------------------------------------------------------------------------------------
    async def meter_all(self, period: date | None = None) -> dict[str, Any]:
        period = month_start(period or today_utc())
        ids = [
            r[0]
            for r in (
                await self.db.execute(
                    select(Institution.id).where(
                        Institution.deleted_at.is_(None), Institution.status.in_(("active", "pending", "suspended"))
                    )
                )
            ).all()
        ]
        done = 0
        for iid in ids:
            await self.meter(iid, period)
            done += 1
        await self.emit("usage.metered", {"period": str(period), "institutions": done}, aggregate_type="usage_meter")
        return {"period": str(period), "institutions": done}

    async def meter(self, institution_id: uuid.UUID, period: date) -> dict[str, Any]:
        from app.repositories.subscription_repository import SubscriptionRepository
        from app.services.entitlement_service import EntitlementService
        from app.services.file_service import FileService

        ent = EntitlementService(self.db, None)
        lo, hi = period, next_month(period)
        values: dict[str, int] = {
            "active_students": await ent.seats_in_use(institution_id, "student"),
            "active_staff": await ent.seats_in_use(institution_id, "staff"),
        }
        storage = 0
        with contextlib.suppress(Exception):  # file store / Redis unavailable → keep the last value
            storage = int(await FileService(self.db).usage_bytes(institution_id))
        values["storage_bytes"] = storage
        rows = (
            await self.db.execute(
                text(
                    "SELECT channel, count(*) FROM message_logs WHERE institution_id = :i AND created_at >= :lo "
                    "AND created_at < :hi AND status NOT IN ('failed', 'suppressed') GROUP BY channel"
                ),
                {"i": institution_id, "lo": lo, "hi": hi},
            )
        ).all()
        by_channel = {c: int(n) for c, n in rows}
        values["sms_sent"] = by_channel.get("sms", 0)
        values["whatsapp_sent"] = by_channel.get("whatsapp", 0)
        values["emails_sent"] = by_channel.get("email", 0)
        values["api_calls"] = await self.api_calls(institution_id, lo, hi)
        await SubscriptionRepository(self.db).upsert_meter(institution_id, period, **values)
        ai_tokens = await self.ai_tokens(institution_id, period)
        sub, plan = await self._plan_of(institution_id)
        caps = await self.caps(institution_id)
        cost = await self.cost(values, ai_tokens, plan)
        extra = await self.tget(institution_id, f"usage:{period:%Y-%m}", {}) or {}
        extra.update(ai_tokens=ai_tokens, cost_paise=cost, computed_at=str(datetime.now().astimezone()))
        overage = self.overage(values, ai_tokens, plan, caps)
        alerted = set(extra.get("alerted") or [])
        await self._alert_overage(institution_id, period, overage, alerted)
        extra["overage"] = overage
        extra["alerted"] = sorted(alerted)
        await self.tput(institution_id, f"usage:{period:%Y-%m}", extra)
        return {**values, "ai_tokens": ai_tokens, "cost_paise": cost}

    async def api_calls(self, institution_id: uuid.UUID, lo: date, hi: date) -> int:
        from app.db.session import redis_client

        total = 0
        d = lo
        with contextlib.suppress(Exception):
            keys = []
            while d < hi:
                keys.append(f"api:{institution_id}:{d:%Y%m%d}")
                d += timedelta(days=1)
            for v in await redis_client.mget(keys):
                total += int(v or 0)
        if total == 0:  # Redis counters expire after 40 days: keep the stored value for older months
            row = (
                await self.db.execute(
                    select(UsageMeter.api_calls).where(
                        UsageMeter.institution_id == institution_id, UsageMeter.period_month == lo
                    )
                )
            ).first()
            total = int(row[0]) if row else 0
        return total

    async def ai_tokens(self, institution_id: uuid.UUID, period: date) -> int:
        row = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                    "AND category = 'comms_meta' AND key = :k"
                ),
                {"i": institution_id, "k": f"assistant_usage:{period:%Y-%m}"},
            )
        ).first()
        usage = row[0] if row and isinstance(row[0], dict) else {}
        return int(usage.get("tokens") or int(usage.get("messages") or 0) * AI_TOKENS_PER_MESSAGE)

    async def _plan_of(self, institution_id: uuid.UUID) -> tuple[Any, Any]:
        from app.services.saas.subscription_service import SubscriptionService

        svc = SubscriptionService(self.db, self.principal)
        sub = await svc.current(institution_id)
        plan = await svc._plan(sub.plan_id) if sub else None
        return sub, plan

    async def cost(self, values: dict[str, int], ai_tokens: int, plan: Any) -> int:
        rates = await self.setting("usage.rates") or {}
        cost = (
            values.get("sms_sent", 0) * int(rates.get("sms_paise") or 0)
            + values.get("whatsapp_sent", 0) * int(rates.get("whatsapp_paise") or 0)
            + values.get("emails_sent", 0) * int(rates.get("email_paise") or 0)
            + round(ai_tokens / 1000 * int(rates.get("ai_token_paise_per_1k") or 0))
        )
        allowance = (plan.storage_gb or 0) if plan else 0
        over_gb = max(values.get("storage_bytes", 0) / 1024**3 - allowance, 0)
        return int(cost + round(over_gb * int(rates.get("storage_gb_paise") or 0)))

    def overage(self, values: dict[str, int], ai_tokens: int, plan: Any, caps: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def check(metric: str, used: float, limit: float | None, source: str) -> None:
            if not limit:
                return
            pct = round(used * 100 / limit, 1)
            out.append({"metric": metric, "used": used, "limit": limit, "pct": pct, "source": source})

        if plan is not None:
            for metric, col in LIMIT_FIELDS.items():
                check(metric, values.get(metric, 0), getattr(plan, col), "plan")
            check("storage_gb", round(values.get("storage_bytes", 0) / 1024**3, 2), plan.storage_gb, "plan")
        check("sms_sent", values.get("sms_sent", 0), caps.get("sms_per_month"), "cap")
        check("whatsapp_sent", values.get("whatsapp_sent", 0), caps.get("whatsapp_per_month"), "cap")
        check("emails_sent", values.get("emails_sent", 0), caps.get("emails_per_month"), "cap")
        check("ai_tokens", ai_tokens, caps.get("ai_tokens_per_month"), "cap")
        return out

    async def _alert_overage(
        self, institution_id: uuid.UUID, period: date, overage: list[dict[str, Any]], alerted: set[str]
    ) -> None:
        threshold = int(await self.setting("usage.overage_alert_pct") or 80)
        inst = await self.institution(institution_id)
        for o in overage:
            for level in (threshold, 100):
                tag = f"{o['metric']}:{o['source']}:{level}"
                if o["pct"] < level or tag in alerted:
                    continue
                alerted.add(tag)
                context = {
                    "institution": inst.name,
                    "metric": o["metric"].replace("_", " "),
                    "pct": o["pct"],
                    "used": o["used"],
                    "limit": o["limit"],
                    "month": f"{period:%Y-%m}",
                }
                await self.emit(
                    "usage.overage",
                    {**context, "level": level},
                    institution_id=institution_id,
                    aggregate_type="usage_meter",
                )
                await self.notify_tenant_admins(institution_id, "saas.usage_overage", context, ["in_app", "email"])
                await self.notify_platform("saas.usage_overage", context, ["in_app"])

    # ---- caps (rule 2) ----------------------------------------------------------------------------------------------
    async def caps(self, institution_id: uuid.UUID) -> dict[str, Any]:
        default = await self.setting("usage.caps_default") or {}
        own = await self.tget(institution_id, "caps", {}) or {}
        return {**default, **{k: v for k, v in own.items() if v is not None}}

    async def set_caps(self, institution_id: uuid.UUID, body: UsageCapsIn) -> dict[str, Any]:
        self.require_platform("platform", "billing")
        if self.is_support:
            raise forbidden("Support agents cannot change caps")
        inst = await self.institution(institution_id)
        bad = sorted(k for k in body.caps if k not in CAP_KEYS)
        if bad:
            raise unprocessable(f"Unknown caps: {', '.join(bad)}", field="caps", allowed=list(CAP_KEYS))
        old = await self.tget(inst.id, "caps", {}) or {}
        new = {**old, **body.caps}
        new = {k: v for k, v in new.items() if v is not None}
        await self.tput(inst.id, "caps", new)
        await cache_api_cap(inst.id, (await self.caps(inst.id)).get("api_calls_per_day"))
        await self._tighten_credits(inst.id, new)
        await self.audit("usage_caps", "institution", inst.id, {"caps": new}, old={"caps": old}, institution_id=inst.id)
        return await self.caps(inst.id)

    async def _tighten_credits(self, institution_id: uuid.UUID, caps: dict[str, Any]) -> None:
        """SMS / WhatsApp caps lower the Phase 24 ``comms.credits`` (never raise them above the plan)."""
        if not any(k in caps for k in ("sms_per_month", "whatsapp_per_month")):
            return
        current = await self.tenant_setting(institution_id, "comms", "credits")
        credits = dict(current) if isinstance(current, dict) else {}
        for ch, cap_key in (("sms", "sms_per_month"), ("whatsapp", "whatsapp_per_month")):
            cap = caps.get(cap_key)
            if cap is not None:
                credits[ch] = min(int(credits.get(ch, cap)), int(cap))
        from app.services.saas.subscription_service import SubscriptionService

        await SubscriptionService(self.db, self.principal).write_setting(institution_id, "comms", "credits", credits)

    # ---- reads (rule 4) ---------------------------------------------------------------------------------------------
    async def months(self, institution_id: uuid.UUID | None, from_month: str | None, to_month: str | None) -> UsageOut:
        today = today_utc()
        hi = parse_month(to_month, month_start(today))
        lo = parse_month(from_month, month_start(hi - timedelta(days=330)))
        if self.is_platform:
            self.require_platform("platform", "view")
            inst = institution_id
            if inst is not None:
                await self.audit_read(inst, "usage")
        else:
            if not self.can("settings", "view"):
                raise forbidden("settings:view required")
            inst = self.institution_scope(institution_id)
        q = select(UsageMeter).where(UsageMeter.period_month >= lo, UsageMeter.period_month <= hi)
        if inst is not None:
            q = q.where(UsageMeter.institution_id == inst)
        meters = list((await self.db.execute(q.order_by(UsageMeter.period_month, UsageMeter.institution_id))).scalars())
        names = await self.institution_refs([m.institution_id for m in meters])
        extras: dict[tuple[uuid.UUID, str], Any] = {(i, k): v for i, k, v in await self.tlist("usage:", inst)}
        caps_cache: dict[uuid.UUID, dict[str, Any]] = {}
        out: list[UsageMonth] = []
        totals: dict[str, int] = {}
        for m in meters:
            ex = extras.get((m.institution_id, f"{m.period_month:%Y-%m}")) or {}
            if m.institution_id not in caps_cache:
                caps_cache[m.institution_id] = await self.caps(m.institution_id)
            row = UsageMonth(
                institution_id=m.institution_id,
                institution_name=names.get(m.institution_id, {}).get("name"),
                period_month=m.period_month,
                active_students=m.active_students,
                active_staff=m.active_staff,
                storage_bytes=m.storage_bytes,
                sms_sent=m.sms_sent,
                whatsapp_sent=m.whatsapp_sent,
                emails_sent=m.emails_sent,
                api_calls=m.api_calls,
                ai_tokens=int(ex.get("ai_tokens") or 0),
                cost_paise=int(ex.get("cost_paise") or 0),
                caps=caps_cache[m.institution_id],
                overage=[o for o in ex.get("overage") or [] if o.get("pct", 0) >= 80],
            )
            out.append(row)
            for k in ("sms_sent", "whatsapp_sent", "emails_sent", "api_calls", "ai_tokens", "cost_paise"):
                totals[k] = totals.get(k, 0) + int(getattr(row, k))
        return UsageOut(months=out, totals=totals)

    async def export_csv(self, from_month: str | None, to_month: str | None) -> bytes:
        from app.core.reports import ReportColumn as C
        from app.services.reports.render_service import render_csv

        data = await self.months(None, from_month, to_month)
        cols = [
            C("institution_name", "Institution"),
            C("period_month", "Month", "date"),
            C("active_students", "Students", "int"),
            C("active_staff", "Staff", "int"),
            C("storage_bytes", "Storage (bytes)", "int"),
            C("sms_sent", "SMS", "int"),
            C("whatsapp_sent", "WhatsApp", "int"),
            C("emails_sent", "E-mails", "int"),
            C("api_calls", "API calls", "int"),
            C("ai_tokens", "AI tokens", "int"),
            C("cost_paise", "Usage cost", "money"),
        ]
        return render_csv(cols, [m.model_dump() for m in data.months])

    async def top(self, limit: int = 10) -> list[dict[str, Any]]:
        period = month_start(today_utc())
        rows = list(
            (
                await self.db.execute(
                    select(UsageMeter)
                    .where(UsageMeter.period_month == period)
                    .order_by(UsageMeter.api_calls.desc())
                    .limit(limit)
                )
            ).scalars()
        )
        names = await self.institution_refs([r.institution_id for r in rows])
        extras = {i: v for i, k, v in await self.tlist(f"usage:{period:%Y-%m}") if k == ""}
        return [
            {
                "institution": names.get(r.institution_id),
                "api_calls": r.api_calls,
                "sms_sent": r.sms_sent,
                "storage_gb": round(r.storage_bytes / 1024**3, 2),
                "active_students": r.active_students,
                "overage": [
                    o for o in (extras.get(r.institution_id) or {}).get("overage") or [] if o.get("pct", 0) >= 80
                ],
            }
            for r in rows
        ]


async def cache_api_cap(institution_id: uuid.UUID, cap: Any) -> None:
    from app.db.session import redis_client

    with contextlib.suppress(Exception):
        if cap:
            await redis_client.set(f"apicap:{institution_id}", int(cap))
        else:
            await redis_client.delete(f"apicap:{institution_id}")
