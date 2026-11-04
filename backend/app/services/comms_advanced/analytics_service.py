"""Simulator, delivery analytics and provider health — Prompts/24 §24.6 ``simulator_service`` / ``analytics_service``.

The simulator inbox is the tenant's recent ``message_logs`` sent through the ``mock`` provider (SMS / WhatsApp / e-mail
/ push) — what a real phone or mailbox would have received; it can inject inbound WhatsApp messages (driving the bot)
and fake provider callbacks (delivered / read / failed). It is blocked when ``APP_ENV=production`` unless
``platform_settings['comms.simulator_enabled']``. Delivery analytics aggregate ``message_logs`` (partition-pruned by
``created_at``); provider health probes each channel's adapter.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, literal_column, select, text

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.models.communication import MessageLog
from app.schemas.comms_advanced import (
    DeliveryAnalyticsOut,
    MyMessageOut,
    ProviderHealthOut,
    SimProviderEvent,
    SimulatorInboxOut,
)
from app.services.comms_advanced.common import CommsBase, now_utc


class CommsAnalyticsService(CommsBase):
    async def simulator_allowed(self) -> None:
        if settings.APP_ENV != "production":
            return
        row = (
            await self.db.execute(text("SELECT value FROM platform_settings WHERE key = 'comms.simulator_enabled'"))
        ).scalar_one_or_none()
        if row is not True:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "The channel simulator is disabled in production")

    async def inbox(self, channel: str | None = None) -> list[SimulatorInboxOut]:
        self.require("bulk")
        await self.simulator_allowed()
        q = select(MessageLog).where(
            MessageLog.institution_id == self.inst,
            MessageLog.channel != "in_app",
            (MessageLog.provider == "mock") | MessageLog.provider.is_(None),
            MessageLog.status != "suppressed",
        )
        if channel:
            q = q.where(MessageLog.channel == channel)
        rows = (
            await self.db.execute(
                q.where(MessageLog.created_at >= now_utc() - timedelta(days=7))
                .order_by(MessageLog.created_at.desc())
                .limit(200)
            )
        ).scalars()
        return [
            SimulatorInboxOut(
                id=str(r.id),
                channel=r.channel,
                recipient=r.recipient,
                subject=r.subject,
                body=r.body_preview,
                status=r.status,
                at=r.created_at,
            )
            for r in rows
        ]

    async def clear_inbox(self) -> int:
        self.require("bulk")
        await self.simulator_allowed()
        res = await self.db.execute(
            delete(MessageLog)
            .where(
                MessageLog.institution_id == self.inst,
                MessageLog.provider == "mock",
                MessageLog.created_at >= now_utc() - timedelta(days=7),
            )
            .execution_options(synchronize_session=False)
        )
        return int(getattr(res, "rowcount", 0) or 0)

    async def inbound(self, phone: str, text_in: str, wa_message_id: str | None) -> dict[str, Any]:
        from app.services.comms_advanced.bot_service import BotService

        self.require("bulk")
        await self.simulator_allowed()
        await self.require_feature("comms.whatsapp_bot")
        return await BotService(self.db, None, self.request, self.inst).handle(
            phone, text_in, wa_message_id or f"sim-{uuid.uuid4().hex}"
        )

    async def provider_event(self, body: SimProviderEvent) -> dict[str, Any]:
        self.require("bulk")
        await self.simulator_allowed()
        row = (
            (
                await self.db.execute(
                    select(MessageLog).where(
                        MessageLog.id == body.message_log_id, MessageLog.institution_id == self.inst
                    )
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Message not found")
        row.status = body.status
        if body.status in ("delivered", "read"):
            row.delivered_at = row.delivered_at or now_utc()
        if body.status in ("failed", "bounced"):
            row.error = body.error or "SIMULATED_FAILURE"
        await self.db.flush()
        if row.campaign_id:
            from app.models.comms_advanced import BulkCampaign
            from app.services.comms_advanced.campaign_service import CampaignService

            c = (
                await self.db.execute(select(BulkCampaign).where(BulkCampaign.id == row.campaign_id))
            ).scalar_one_or_none()
            if c is not None:
                await CampaignService(self.db, self.principal, self.request, self.inst).refresh_counts(c)
        return {"id": str(row.id), "status": row.status}

    # ---- analytics ---------------------------------------------------------------------------------------------------------
    async def delivery(
        self,
        date_from: datetime | None,
        date_to: datetime | None,
        channel: str | None,
        template_id: uuid.UUID | None,
        event_type: str | None,
    ) -> DeliveryAnalyticsOut:
        self.require("view_all", "bulk")
        lo = date_from or now_utc() - timedelta(days=30)
        hi = date_to or now_utc()
        base = [MessageLog.institution_id == self.inst, MessageLog.created_at >= lo, MessageLog.created_at <= hi]
        if channel:
            base.append(MessageLog.channel == channel)
        if template_id:
            base.append(MessageLog.template_id == template_id)
        if event_type:
            base.append(MessageLog.event_type == event_type)
        by_channel: dict[str, dict[str, int]] = {}
        totals: dict[str, int] = {}
        for ch, st, n in (
            await self.db.execute(
                select(MessageLog.channel, MessageLog.status, func.count())
                .where(*base)
                .group_by(MessageLog.channel, MessageLog.status)
            )
        ).all():
            by_channel.setdefault(ch, {})[st] = int(n)
            totals[st] = totals.get(st, 0) + int(n)
        by_day = [
            {"day": d.date().isoformat() if d else None, "count": int(n)}
            for d, n in (
                await self.db.execute(
                    select(func.date_trunc(literal_column("'day'"), MessageLog.created_at), func.count())
                    .where(*base)
                    .group_by(func.date_trunc(literal_column("'day'"), MessageLog.created_at))
                    .order_by(func.date_trunc(literal_column("'day'"), MessageLog.created_at))
                )
            ).all()
        ]
        reasons = {
            str(e or "unknown"): int(n)
            for e, n in (
                await self.db.execute(
                    select(MessageLog.error, func.count())
                    .where(*base, MessageLog.status.in_(("failed", "bounced")))
                    .group_by(MessageLog.error)
                )
            ).all()
        }
        cost = int(
            (await self.db.execute(select(func.coalesce(func.sum(MessageLog.cost_paise), 0)).where(*base))).scalar_one()
            or 0
        )
        return DeliveryAnalyticsOut(
            period_from=lo,
            period_to=hi,
            totals=totals,
            by_channel=by_channel,
            by_day=by_day,
            failures_by_reason=reasons,
            cost_paise=cost,
        )

    async def providers(self) -> list[ProviderHealthOut]:
        from app.integrations.registry import get_adapter
        from app.services.notifications.delivery import provider_for

        self.require("view_all", "bulk")
        out = []
        for ch in ("sms", "whatsapp", "email", "push"):
            prov = await provider_for(self.db, self.inst, ch)
            try:
                ok, detail = await get_adapter(ch, prov).health()
            except Exception as exc:  # noqa: BLE001 - a broken adapter is reported, not raised
                ok, detail = False, str(exc)[:200]
            errs = [
                str(e)
                for e in (
                    await self.db.execute(
                        select(MessageLog.error)
                        .where(
                            MessageLog.institution_id == self.inst,
                            MessageLog.channel == ch,
                            MessageLog.status == "failed",
                            MessageLog.created_at >= now_utc() - timedelta(days=1),
                        )
                        .order_by(MessageLog.created_at.desc())
                        .limit(5)
                    )
                ).scalars()
                if e
            ]
            out.append(ProviderHealthOut(channel=ch, provider=prov, ok=ok, detail=detail, last_errors=errs))
        return out

    async def export(self, date_from: datetime | None, date_to: datetime | None) -> dict[str, Any]:
        import csv
        import io

        from app.core.files import build_key, storage

        rep = await self.delivery(date_from, date_to, None, None, None)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["channel", "status", "count"])
        for ch, sts in rep.by_channel.items():
            for st, n in sts.items():
                w.writerow([ch, st, n])
        key = build_key(self.inst, "comms-analytics", f"delivery-{uuid.uuid4().hex[:8]}.csv")
        await storage.put(key, buf.getvalue().encode(), "text/csv")
        return {"result_url": key}

    async def my_messages(
        self, channel: str | None, date_from: datetime | None, date_to: datetime | None
    ) -> list[MyMessageOut]:
        q = select(MessageLog).where(
            MessageLog.user_id == self.actor_id, MessageLog.created_at >= (date_from or now_utc() - timedelta(days=90))
        )
        if date_to:
            q = q.where(MessageLog.created_at <= date_to)
        if channel:
            q = q.where(MessageLog.channel == channel)
        rows = (await self.db.execute(q.order_by(MessageLog.created_at.desc()).limit(500))).scalars()
        return [
            MyMessageOut(
                id=r.id,
                channel=r.channel,
                subject=r.subject,
                body_preview=r.body_preview,
                status=r.status,
                event_type=r.event_type,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def health_probe(self) -> int:
        bad = [p for p in await self.providers() if not p.ok]
        for p in bad:
            await self._emit(
                "comms.provider_degraded",
                {"channel": p.channel, "provider": p.provider, "detail": p.detail},
                "provider",
                None,
            )
        return len(bad)
