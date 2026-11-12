"""Campaigns, announcement analytics and emergency broadcast — Prompts/24 §24.6 ``campaign_service`` /
``announcement_analytics_service`` / ``emergency_service``.

1. **Compliance**: SMS needs a DLT-registered template (``body_override.sms_dlt_template_id`` or the template's
   ``dlt_template_id``) whose text matches; WhatsApp needs an ``approved`` ``whatsapp_templates`` name; e-mail HTML is
   sanitised (scripts / handlers stripped); push title ≤ 65 / body ≤ 240.
2. **Cost** = Σ reachable recipients × ``platform_settings['comms.rates']`` per channel; credits = the
   ``comms.credits`` setting (``{sms, whatsapp}``; absent = unmetered) → 409 ``CREDITS_INSUFFICIENT`` on send;
   above ``comms.campaign_approval_threshold_recipients`` → ``pending_approval`` (``communication:approve``).
3. **Sending** (job ``campaign.send``): one ``message_logs`` row per recipient × channel (``campaign_id`` set, body
   parked in Redis like the Phase 04 dispatcher); the first ``comms.throttle_per_minute[channel]`` rows go to
   ``notifications.deliver`` at once, the rest stay ``deferred`` and the Beat flush releases the next minute-batch
   (also releases quiet-hours deferrals once the window ends; emergency campaigns ignore quiet hours and preferences);
   ``pause`` stops the flush, ``resume`` restarts it, ``retry_failed`` re-queues failed rows; the campaign is ``sent``
   when nothing is queued / deferred. In-app rows become ``notifications``.
4. **Department campaigns**: non-officers target only their unit (segment compiler) and only in-app / e-mail / push
   (403 for SMS / WhatsApp without ``communication:bulk``).
5. **Emergency**: typed ``BROADCAST`` confirmation, every channel, every recipient of the scope, ``[DRILL]`` prefix in
   drill mode, incident log (``comms_meta``), all-clear follow-up.
"""

import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, literal_column, select, update

from app.core.errors import APIError, ErrorCode
from app.enums.comms_advanced import DEFAULT_RATES_PAISE, DEFAULT_THROTTLE, EMERGENCY_CONFIRM
from app.models.comms_advanced import BulkCampaign
from app.models.communication import (
    Announcement,
    AnnouncementAcknowledgement,
    DltTemplate,
    MessageLog,
    Notification,
    NotificationPreference,
    NotificationTemplate,
    WhatsappTemplate,
)
from app.schemas.comms_advanced import (
    AnnouncementAnalytics,
    CampaignAction,
    CampaignCreate,
    CampaignReport,
    CampaignResponse,
    CampaignUpdate,
    ComplianceResult,
    EmergencyBroadcast,
    EmergencyLog,
    SegmentRules,
)
from app.services.comms_advanced.common import COMM, CommsBase, all_access, now_utc, officer, rule
from app.services.comms_advanced.segment_service import Audience, SegmentService

OPEN = ("queued", "deferred")


def sanitise_html(html: str) -> str:
    html = re.sub(r"<\s*(script|iframe|object|embed)[^>]*>.*?<\s*/\s*\1\s*>", "", html, flags=re.I | re.S)
    html = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)
    return re.sub(r"javascript:", "", html, flags=re.I)


class CampaignService(CommsBase):
    # ---- read ----------------------------------------------------------------------------------------------------------------
    def _body(self, c: BulkCampaign) -> dict[str, Any]:
        try:
            return json.loads(c.body_override) if c.body_override else {}
        except ValueError:
            return {"in_app": c.body_override}

    async def out(self, c: BulkCampaign, *, with_compliance: bool = False) -> CampaignResponse:
        m = await self.meta("campaign", c.id)
        o = CampaignResponse(
            id=c.id,
            name=c.name,
            channels=list(c.channels or []),
            audience_rules=c.audience_rules or {},
            template_id=c.template_id,
            body=self._body(c),
            scheduled_at=c.scheduled_at,
            status=c.status,
            is_emergency=c.is_emergency,
            total_recipients=c.total_recipients,
            sent_count=c.sent_count,
            failed_count=c.failed_count,
            job_id=c.job_id,
            created_by=c.created_by,
            created_at=c.created_at,
            cost_estimate_paise=int(m.get("cost_paise", 0)),
            approval={k: m[k] for k in ("approved_by", "approved_at", "rejected_by", "remarks") if k in m},
        )
        if with_compliance:
            o.compliance = await self.compliance(c)
        return o

    def _predicate(self) -> Any:
        if all_access(self.principal):
            return BulkCampaign.institution_id == self.inst
        return BulkCampaign.created_by == self.actor_id

    async def list_campaigns(self, status: str | None = None, scope: str | None = None) -> list[CampaignResponse]:
        self.require("bulk", "send", "approve", "view_all")
        q = select(BulkCampaign).where(BulkCampaign.institution_id == self.inst)
        if scope == "self" or not (all_access(self.principal) or self.can(COMM, "view_all")):
            q = q.where(BulkCampaign.created_by == self.actor_id)
        if status:
            q = q.where(BulkCampaign.status == status)
        rows = list((await self.db.execute(q.order_by(BulkCampaign.created_at.desc()).limit(500))).scalars())
        return [await self.out(c) for c in rows]

    async def row(self, cid: uuid.UUID, *, for_update: bool = False) -> BulkCampaign:
        q = select(BulkCampaign).where(BulkCampaign.id == cid, BulkCampaign.institution_id == self.inst)
        if not (all_access(self.principal) or self.can(COMM, "view_all") or self.can(COMM, "approve")):
            q = q.where(BulkCampaign.created_by == self.actor_id)
        if for_update:
            q = q.with_for_update()
        c = (await self.db.execute(q)).scalar_one_or_none()
        if c is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Campaign not found")
        return c

    async def get(self, cid: uuid.UUID) -> CampaignResponse:
        return await self.out(await self.row(cid), with_compliance=True)

    # ---- authoring ---------------------------------------------------------------------------------------------------------
    async def _rules(self, body: CampaignCreate | CampaignUpdate) -> dict[str, Any] | None:
        if getattr(body, "segment_id", None):
            seg = await SegmentService(self.db, self.principal, self.request, self.inst).get_saved(body.segment_id)  # type: ignore[arg-type,union-attr]
            return dict(seg["rules"])
        return body.audience_rules.model_dump(mode="json") if body.audience_rules else None

    def _channel_gate(self, channels: Any) -> None:
        if not officer(self.principal) and set(channels) & {"sms", "whatsapp"}:
            raise APIError(
                403,
                ErrorCode.PERMISSION_DENIED,
                "SMS / WhatsApp campaigns need communication:bulk",
                {"channels": sorted(set(channels) & {"sms", "whatsapp"})},
            )

    async def create(self, body: CampaignCreate) -> CampaignResponse:
        self.require("bulk", "send")
        await self.require_feature("comms.bulk_campaigns")
        self._channel_gate(body.channels)
        rules = await self._rules(body)
        if rules is None:
            raise APIError(422, ErrorCode.VALIDATION, "Pick an audience (rules or a saved segment)")
        if body.scheduled_at and not await self.feature("comms.scheduled_sends"):
            raise APIError(
                403,
                ErrorCode.FEATURE_DISABLED,
                "Feature 'comms.scheduled_sends' is not enabled",
                {"feature": "comms.scheduled_sends"},
            )
        c = BulkCampaign(
            institution_id=self.inst,
            name=body.name,
            channels=list(dict.fromkeys(body.channels)),
            audience_rules=rules,
            template_id=body.template_id,
            body_override=json.dumps(body.body_override.model_dump(mode="json", exclude_none=True))
            if body.body_override
            else None,
            scheduled_at=body.scheduled_at,
            status="draft",
            created_by=self.actor_id,
        )
        self.db.add(c)
        await self.db.flush()
        await self.put_meta(
            "campaign",
            c.id,
            {"variables": body.variables, "respect_quiet_hours": body.respect_quiet_hours, "category": body.category},
        )
        await self._estimate(c)
        await self._audit("create", "bulk_campaign", c.id, None, {"name": c.name, "channels": c.channels})
        await self._emit("campaign.created", {"campaign_id": str(c.id)}, "bulk_campaign", c.id)
        return await self.out(c, with_compliance=True)

    async def update(self, cid: uuid.UUID, body: CampaignUpdate) -> CampaignResponse:
        c = await self.row(cid, for_update=True)
        if c.status not in ("draft", "pending_approval"):
            raise rule("Only a draft campaign can be edited", "NOT_DRAFT")
        data = body.model_dump(exclude_unset=True)
        if "channels" in data:
            self._channel_gate(data["channels"])
            c.channels = list(dict.fromkeys(data["channels"]))
        if body.audience_rules is not None:
            c.audience_rules = body.audience_rules.model_dump(mode="json")
        if "template_id" in data:
            c.template_id = data["template_id"]
        if body.body_override is not None:
            c.body_override = json.dumps(body.body_override.model_dump(mode="json", exclude_none=True))
        if "scheduled_at" in data:
            c.scheduled_at = data["scheduled_at"]
        if "name" in data:
            c.name = data["name"]
        m = await self.meta("campaign", c.id)
        if body.variables is not None:
            m["variables"] = body.variables
        if body.respect_quiet_hours is not None:
            m["respect_quiet_hours"] = body.respect_quiet_hours
        await self.put_meta("campaign", c.id, m)
        c.status = "draft"
        await self._estimate(c)
        return await self.out(c, with_compliance=True)

    async def audience(self, c: BulkCampaign) -> Audience:
        rules = SegmentRules(**(c.audience_rules or {}))
        if c.is_emergency:  # emergency broadcasts reach the whole scope regardless of the caller's unit
            return await SegmentService(self.db, None, self.request, self.inst).compile(rules)
        return await SegmentService(self.db, self.principal, self.request, self.inst).compile(rules)

    async def rates(self) -> dict[str, int]:
        from sqlalchemy import text

        row = (
            await self.db.execute(text("SELECT value FROM platform_settings WHERE key = 'comms.rates'"))
        ).scalar_one_or_none()
        return {**DEFAULT_RATES_PAISE, **(row if isinstance(row, dict) else {})}

    async def _estimate(self, c: BulkCampaign) -> int:
        aud = await self.audience(c)
        reach = aud.reach()
        rates = await self.rates()
        cost = sum(reach.get(ch, 0) * int(rates.get(ch, 0)) for ch in c.channels)
        c.total_recipients = len(aud.users)
        m = await self.meta("campaign", c.id)
        m["cost_paise"] = cost
        m["reach"] = {ch: reach.get(ch, 0) for ch in c.channels}
        await self.put_meta("campaign", c.id, m)
        await self.db.flush()
        return cost

    async def compliance(self, c: BulkCampaign) -> ComplianceResult:
        body = self._body(c)
        errors: list[str] = []
        warnings: list[str] = []
        tmpl = (
            (
                await self.db.execute(select(NotificationTemplate).where(NotificationTemplate.id == c.template_id))
            ).scalar_one_or_none()
            if c.template_id
            else None
        )
        if "sms" in c.channels:
            dlt_ref = body.get("sms_dlt_template_id")
            ok = False
            if dlt_ref:
                d = (
                    await self.db.execute(
                        select(DltTemplate).where(
                            DltTemplate.id == uuid.UUID(str(dlt_ref)), DltTemplate.institution_id == self.inst
                        )
                    )
                ).scalar_one_or_none()
                if d is not None and d.status == "approved":
                    pattern = re.escape(d.template_text).replace(r"\{\#var\#\}", ".{0,30}")
                    ok = not body.get("sms") or bool(re.fullmatch(pattern, body["sms"]))
                    if not ok:
                        errors.append("DLT_TEMPLATE_MISMATCH")
            elif tmpl is not None and tmpl.dlt_template_id:
                ok = True
            if not ok and "DLT_TEMPLATE_MISMATCH" not in errors:
                errors.append("DLT_TEMPLATE_REQUIRED")
        if "whatsapp" in c.channels:
            name = body.get("whatsapp_template") or (tmpl.whatsapp_template_name if tmpl else None)
            wa = (
                (
                    await self.db.execute(
                        select(WhatsappTemplate).where(
                            WhatsappTemplate.institution_id == self.inst, WhatsappTemplate.name == name
                        )
                    )
                )
                .scalars()
                .first()
                if name
                else None
            )
            if wa is None or wa.status != "approved":
                errors.append("WA_TEMPLATE_NOT_APPROVED")
        if "email" in c.channels:
            if not (body.get("email_subject") or tmpl):
                errors.append("EMAIL_SUBJECT_REQUIRED")
            if body.get("email_html") and sanitise_html(body["email_html"]) != body["email_html"]:
                warnings.append("EMAIL_HTML_SANITISED")
        if "push" in c.channels and not (body.get("push_title") or tmpl):
            errors.append("PUSH_TITLE_REQUIRED")
        if not (body or tmpl):
            errors.append("CONTENT_REQUIRED")
        return ComplianceResult(ok=not errors, errors=errors, warnings=warnings)

    # ---- actions ---------------------------------------------------------------------------------------------------------
    async def action(self, cid: uuid.UUID, body: CampaignAction) -> CampaignResponse:
        c = await self.row(cid, for_update=True)
        m = await self.meta("campaign", c.id)
        a = body.action
        if a == "submit":
            if c.status != "draft":
                raise rule("Only a draft can be submitted", "NOT_DRAFT")
            comp = await self.compliance(c)
            if not comp.ok:
                raise rule("The campaign fails the compliance check", "COMPLIANCE_FAILED", errors=comp.errors)
            await self._estimate(c)
            threshold = int(await self.setting("comms", "campaign_approval_threshold_recipients") or 2000)
            c.status = "pending_approval" if (c.total_recipients or 0) > threshold else "approved"
            await self._emit(
                "campaign.submitted", {"campaign_id": str(c.id), "status": c.status}, "bulk_campaign", c.id
            )
        elif a in ("approve", "reject"):
            self.require("approve")
            if c.status != "pending_approval":
                raise rule("The campaign is not awaiting approval", "NOT_PENDING")
            c.status = "approved" if a == "approve" else "draft"
            m.update(
                {
                    "approved_by" if a == "approve" else "rejected_by": str(self.actor_id),
                    "approved_at": now_utc().isoformat(),
                    "remarks": body.remarks,
                }
            )
            await self._emit(
                f"campaign.{'approved' if a == 'approve' else 'rejected'}",
                {"campaign_id": str(c.id)},
                "bulk_campaign",
                c.id,
            )
        elif a == "schedule":
            await self.require_feature("comms.scheduled_sends")
            if c.status not in ("approved", "draft"):
                raise rule("Approve the campaign before scheduling it", "NOT_APPROVED")
            if c.status == "draft":
                raise rule("Submit the campaign first", "NOT_SUBMITTED")
            when = body.scheduled_at or c.scheduled_at
            if when is None or when <= now_utc():
                raise APIError(
                    422, ErrorCode.VALIDATION, "scheduled_at must be in the future", {"field": "scheduled_at"}
                )
            c.scheduled_at, c.status = when, "scheduled"
            await self._emit(
                "campaign.scheduled", {"campaign_id": str(c.id), "at": when.isoformat()}, "bulk_campaign", c.id
            )
        elif a == "send_now":
            if c.status not in ("approved", "scheduled"):
                raise rule("The campaign is not approved", "NOT_APPROVED", status_=c.status)
            await self._check_credits(c)
            await self._start(c)
        elif a == "cancel":
            if c.status in ("sent", "cancelled"):
                raise rule("The campaign is finished", "FINISHED")
            c.status = "cancelled"
            await self.db.execute(
                update(MessageLog)
                .where(MessageLog.campaign_id == c.id, MessageLog.status.in_(OPEN))
                .values(status="suppressed", error="CAMPAIGN_CANCELLED")
            )
            await self._emit("campaign.cancelled", {"campaign_id": str(c.id)}, "bulk_campaign", c.id)
        elif a == "pause":
            if c.status != "sending":
                raise rule("Only a sending campaign can be paused", "NOT_SENDING")
            c.status = "paused"
            await self._emit("campaign.paused", {"campaign_id": str(c.id)}, "bulk_campaign", c.id)
        elif a == "resume":
            if c.status != "paused":
                raise rule("The campaign is not paused", "NOT_PAUSED")
            c.status = "sending"
            await self._emit("campaign.resumed", {"campaign_id": str(c.id)}, "bulk_campaign", c.id)
            await self.flush_campaign(c)
        elif a == "retry_failed":
            if c.status not in ("sent", "sending", "failed"):
                raise rule("Nothing to retry yet", "NOT_STARTED")
            n = (
                await self.db.execute(
                    update(MessageLog)
                    .where(MessageLog.campaign_id == c.id, MessageLog.status == "failed")
                    .values(status="deferred", error=None)
                )
            ).rowcount or 0  # type: ignore[attr-defined]
            if n:
                c.status = "sending"
                await self.flush_campaign(c)
        await self.put_meta("campaign", c.id, m)
        await self.db.flush()
        await self._audit(a, "bulk_campaign", c.id, None, {"status": c.status})
        return await self.out(c)

    async def _check_credits(self, c: BulkCampaign) -> None:
        if c.is_emergency:
            return
        credits = await self.setting("comms", "credits")
        if not isinstance(credits, dict):
            return
        reach = (await self.meta("campaign", c.id)).get("reach", {})
        for ch in ("sms", "whatsapp"):
            if ch in c.channels and ch in credits and int(credits[ch]) < int(reach.get(ch, 0)):
                raise rule(
                    f"Not enough {ch.upper()} credits",
                    "CREDITS_INSUFFICIENT",
                    channel=ch,
                    needed=int(reach.get(ch, 0)),
                    available=int(credits[ch]),
                )

    async def _start(self, c: BulkCampaign) -> None:
        from app.core.jobs import enqueue

        c.status = "sending"
        j = (
            await enqueue(self.db, self.principal, "campaign.send", {"campaign_id": str(c.id)})
            if self.principal is not None
            else None
        )
        c.job_id = j.id if j else None
        await self.db.flush()
        await self._emit("campaign.started", {"campaign_id": str(c.id)}, "bulk_campaign", c.id)
        if j is None:  # system-started (scheduler / emergency): materialise inline
            await self.materialise(c)

    # ---- sending ----------------------------------------------------------------------------------------------------------
    def _content(
        self, c: BulkCampaign, tmpl: NotificationTemplate | None, channel: str, name: str, variables: dict[str, Any]
    ) -> tuple[str, str]:
        from app.core.notifications.templating import render

        body = self._body(c)
        ctx = {**variables, "name": name}
        prefix = "[DRILL] " if (c.is_emergency and (body.get("drill") or False)) else ""
        if channel == "email" and body.get("email_html"):
            return prefix + (body.get("email_subject") or c.name), sanitise_html(body["email_html"])
        mapping = {
            "sms": body.get("sms"),
            "whatsapp": body.get("whatsapp_text") or body.get("sms"),
            "push": body.get("push_body"),
            "in_app": body.get("in_app") or body.get("push_body") or body.get("sms"),
        }
        text_body = mapping.get(channel) or body.get("in_app") or body.get("sms")
        subject = body.get("email_subject") or body.get("push_title") or c.name
        if text_body is None and tmpl is not None:
            try:
                subject, text_body = render(tmpl.subject_template, ctx) or tmpl.name, render(tmpl.body_template, ctx)
            except Exception:  # noqa: BLE001 - broken template: fall back to the campaign name
                text_body = c.name
        text_body = text_body or c.name
        for k, v in ctx.items():
            text_body = text_body.replace("{{ " + k + " }}", str(v)).replace("{{" + k + "}}", str(v))
        return prefix + str(subject), prefix + str(text_body)

    async def materialise(self, c: BulkCampaign) -> dict[str, int]:
        """Create the message rows (queued / deferred) for every recipient × channel, then release the first batch."""
        from app.core.jobs import send_after_commit
        from app.db.session import redis_client
        from app.repositories.message_log_repository import MessageLogRepository
        from app.services.notifications.dispatcher import BODY_TTL, body_key, in_quiet_hours

        if (await self.db.execute(select(MessageLog.id).where(MessageLog.campaign_id == c.id).limit(1))).first():
            return await self.flush_campaign(c)  # resumed job: rows already exist
        aud = await self.audience(c)
        m = await self.meta("campaign", c.id)
        variables, respect = m.get("variables") or {}, bool(m.get("respect_quiet_hours", True)) and not c.is_emergency
        tmpl = (
            (
                await self.db.execute(select(NotificationTemplate).where(NotificationTemplate.id == c.template_id))
            ).scalar_one_or_none()
            if c.template_id
            else None
        )
        prefs = {
            p.user_id: p
            for p in (
                await self.db.execute(
                    select(NotificationPreference).where(
                        NotificationPreference.user_id.in_(list(aud.users) or [uuid.uuid4()])
                    )
                )
            ).scalars()
        }
        tz = (await self.institution()).timezone or "Asia/Kolkata"
        logs = MessageLogRepository(self.db)
        counts = {"rows": 0, "in_app": 0, "deferred": 0}
        devices: dict[uuid.UUID, list[str]] = {}
        if "push" in c.channels:
            from app.models.platform import DeviceToken

            for d in (
                await self.db.execute(
                    select(DeviceToken).where(
                        DeviceToken.user_id.in_(list(aud.users) or [uuid.uuid4()]), DeviceToken.is_active.is_(True)
                    )
                )
            ).scalars():
                devices.setdefault(d.user_id, []).append(f"{d.provider}:{d.token}")
        for uid, u in aud.users.items():
            pref = prefs.get(uid)
            quiet = respect and pref is not None and in_quiet_hours(pref.quiet_hours, tz)
            for ch in c.channels:
                subject, body = self._content(c, tmpl, ch, u.get("name") or "", variables)
                if ch == "in_app":
                    self.db.add(
                        Notification(
                            institution_id=self.inst,
                            user_id=uid,
                            title=subject[:200],
                            body=body,
                            category="emergency" if c.is_emergency else "announcements",
                            event_type="campaign.message",
                            link={"campaign_id": str(c.id)},
                        )
                    )
                    await logs.add(
                        institution_id=self.inst,
                        user_id=uid,
                        recipient=str(uid),
                        channel="in_app",
                        event_type="campaign.message",
                        campaign_id=c.id,
                        subject=subject[:255],
                        body_preview=body[:255],
                        provider="in_app",
                        status="sent",
                        sent_at=now_utc(),
                    )
                    counts["in_app"] += 1
                    continue
                targets: list[Any] = {
                    "sms": [u.get("phone")],
                    "whatsapp": [u.get("phone")],
                    "email": [u.get("email")],
                    "push": devices.get(uid, []),
                }.get(ch, [])  # type: ignore[assignment]
                for to in [t for t in targets if t]:
                    row = await logs.add(
                        institution_id=self.inst,
                        user_id=uid,
                        recipient=str(to)[:200],
                        channel=ch,
                        event_type="campaign.message",
                        campaign_id=c.id,
                        template_id=c.template_id,
                        subject=subject[:255],
                        body_preview=body[:255],
                        status="deferred",
                        error="QUIET_HOURS" if quiet else None,
                    )
                    await redis_client.set(
                        body_key(row.id), json.dumps({"subject": subject, "body": body}), ex=BODY_TTL
                    )
                    counts["rows"] += 1
                    counts["deferred"] += int(quiet)
        c.total_recipients = len(aud.users)
        await self.db.flush()
        _ = send_after_commit
        released = await self.flush_campaign(c)
        return counts | released

    async def flush_campaign(self, c: BulkCampaign) -> dict[str, int]:
        """Release up to one minute of throttle per channel; finish the campaign when nothing is pending."""
        from app.core.jobs import send_after_commit
        from app.services.notifications.dispatcher import in_quiet_hours

        if c.status not in ("sending",):
            return {"released": 0}
        throttle = {**DEFAULT_THROTTLE, **(await self.setting("comms", "throttle_per_minute") or {})}
        m = await self.meta("campaign", c.id)
        respect = bool(m.get("respect_quiet_hours", True)) and not c.is_emergency
        tz = (await self.institution()).timezone or "Asia/Kolkata"
        released = 0
        for ch in c.channels:
            if ch == "in_app":
                continue
            rows = list(
                (
                    await self.db.execute(
                        select(MessageLog)
                        .where(
                            MessageLog.campaign_id == c.id, MessageLog.channel == ch, MessageLog.status == "deferred"
                        )
                        .limit(int(throttle.get(ch, 600)))
                    )
                ).scalars()
            )
            prefs = (
                {
                    p.user_id: p
                    for p in (
                        await self.db.execute(
                            select(NotificationPreference).where(
                                NotificationPreference.user_id.in_(
                                    [r.user_id for r in rows if r.user_id] or [uuid.uuid4()]
                                )
                            )
                        )
                    ).scalars()
                }
                if respect
                else {}
            )
            for r in rows:
                p = prefs.get(r.user_id) if r.user_id else None
                if respect and p is not None and in_quiet_hours(p.quiet_hours, tz):
                    continue
                r.status, r.error = "queued", None
                send_after_commit(
                    self.db,
                    "notifications.deliver",
                    [str(r.id)],
                    "emails" if ch == "email" else "notifications",
                    str(uuid.uuid4()),
                )
                released += 1
        await self.db.flush()
        await self.refresh_counts(c)
        return {"released": released}

    async def refresh_counts(self, c: BulkCampaign) -> None:
        rows: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(MessageLog.status, func.count())
                    .where(MessageLog.campaign_id == c.id)
                    .group_by(MessageLog.status)
                )
            ).all()  # type: ignore[arg-type]
        )
        c.sent_count = int(sum(v for k, v in rows.items() if k in ("sent", "delivered", "read")))
        c.failed_count = int(sum(v for k, v in rows.items() if k in ("failed", "bounced")))
        pending = int(sum(v for k, v in rows.items() if k in OPEN))
        if c.status == "sending" and pending == 0:
            c.status = "sent"
            await self._emit(
                "campaign.completed",
                {"campaign_id": str(c.id), "sent": c.sent_count, "failed": c.failed_count},
                "bulk_campaign",
                c.id,
            )
            if c.created_by:
                await self._notify(
                    "campaign.completed",
                    [c.created_by],
                    {"campaign": c.name, "sent": c.sent_count, "failed": c.failed_count},
                )
        await self.db.flush()

    async def report(self, cid: uuid.UUID) -> CampaignReport:
        c = await self.row(cid)
        by: dict[str, dict[str, int]] = {}
        totals: dict[str, int] = {}
        reasons: dict[str, int] = {}
        cost = 0
        for ch, st, n, cst in (
            await self.db.execute(
                select(
                    MessageLog.channel,
                    MessageLog.status,
                    func.count(),
                    func.coalesce(func.sum(MessageLog.cost_paise), 0),
                )
                .where(MessageLog.campaign_id == c.id)
                .group_by(MessageLog.channel, MessageLog.status)
            )
        ).all():
            by.setdefault(ch, {})[st] = int(n)
            totals[st] = totals.get(st, 0) + int(n)
            cost += int(cst)
        for err, n in (
            await self.db.execute(
                select(MessageLog.error, func.count())
                .where(MessageLog.campaign_id == c.id, MessageLog.status.in_(("failed", "bounced")))
                .group_by(MessageLog.error)
            )
        ).all():
            reasons[err or "unknown"] = int(n)
        timeline = [
            {"hour": h.isoformat() if h else None, "count": int(n)}
            for h, n in (
                await self.db.execute(
                    select(func.date_trunc(literal_column("'hour'"), MessageLog.sent_at), func.count())
                    .where(MessageLog.campaign_id == c.id, MessageLog.sent_at.is_not(None))
                    .group_by(func.date_trunc(literal_column("'hour'"), MessageLog.sent_at))
                    .order_by(func.date_trunc(literal_column("'hour'"), MessageLog.sent_at))
                )
            ).all()
        ]
        return CampaignReport(
            campaign_id=c.id,
            sent=totals.get("sent", 0) + totals.get("delivered", 0) + totals.get("read", 0),
            delivered=totals.get("delivered", 0) + totals.get("read", 0),
            failed=totals.get("failed", 0) + totals.get("bounced", 0),
            read=totals.get("read", 0),
            queued=totals.get("queued", 0),
            deferred=totals.get("deferred", 0),
            cost_paise=cost,
            by_channel=by,
            failures_by_reason=reasons,
            timeline=timeline,
        )

    async def recipients(self, cid: uuid.UUID, status: str | None = None) -> list[dict[str, Any]]:
        c = await self.row(cid)
        q = select(MessageLog).where(MessageLog.campaign_id == c.id)
        if status:
            q = q.where(MessageLog.status == status)
        rows = (await self.db.execute(q.order_by(MessageLog.created_at.desc()).limit(1000))).scalars()
        return [
            {
                "id": str(r.id),
                "channel": r.channel,
                "recipient": ("•••" + r.recipient[-4:]) if r.channel in ("sms", "whatsapp") else r.recipient,
                "status": r.status,
                "error": r.error,
            }
            for r in rows
        ]

    # ---- Beat ------------------------------------------------------------------------------------------------------------
    async def scheduler_tick(self) -> int:
        due = list(
            (
                await self.db.execute(
                    select(BulkCampaign)
                    .where(
                        BulkCampaign.institution_id == self.inst,
                        BulkCampaign.status == "scheduled",
                        BulkCampaign.scheduled_at <= now_utc(),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for c in due:
            try:
                await self._check_credits(c)
            except APIError:
                c.status = "failed"
                await self._emit(
                    "campaign.failed",
                    {"campaign_id": str(c.id), "reason": "CREDITS_INSUFFICIENT"},
                    "bulk_campaign",
                    c.id,
                )
                continue
            c.status = "sending"
            await self.db.flush()
            await self._emit("campaign.started", {"campaign_id": str(c.id), "scheduled": True}, "bulk_campaign", c.id)
            await self.materialise(c)
        return len(due)

    async def flush_tick(self) -> int:
        n = 0
        for c in (
            await self.db.execute(
                select(BulkCampaign).where(BulkCampaign.institution_id == self.inst, BulkCampaign.status == "sending")
            )
        ).scalars():
            n += (await self.flush_campaign(c))["released"]
        return n

    # ---- announcement analytics ---------------------------------------------------------------------------------------------
    async def announcement(self, aid: uuid.UUID) -> Announcement:
        a = (
            await self.db.execute(
                select(Announcement).where(
                    Announcement.id == aid, Announcement.institution_id == self.inst, Announcement.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Announcement not found")
        if not (
            all_access(self.principal)
            or self.can(COMM, "view_all")
            or a.created_by == self.actor_id
            or officer(self.principal)
        ):
            raise APIError(404, ErrorCode.NOT_FOUND, "Announcement not found")
        return a

    async def _announcement_audience(self, a: Announcement) -> Audience:
        rules = a.audience_rules or {}
        seg = (
            SegmentRules(**{k: v for k, v in rules.items() if k in SegmentRules.model_fields})
            if rules
            else SegmentRules(person_types=["student", "staff"])
        )
        return await SegmentService(self.db, self.principal, self.request, self.inst).compile(seg)

    async def analytics(self, aid: uuid.UUID, *, with_pending: bool = True) -> AnnouncementAnalytics:
        await self.require_feature("comms.announcement_ack")
        a = await self.announcement(aid)
        aud = await self._announcement_audience(a)
        acks = list(
            (
                await self.db.execute(
                    select(AnnouncementAcknowledgement).where(AnnouncementAcknowledgement.announcement_id == a.id)
                )
            ).scalars()
        )
        read = {x.user_id for x in acks}
        acked = {x.user_id for x in acks if x.acknowledged_at}
        by_day: dict[str, dict[str, int]] = {}
        for x in acks:
            d = x.read_at.date().isoformat()
            by_day.setdefault(d, {"read": 0, "acknowledged": 0})["read"] += 1
            if x.acknowledged_at:
                by_day.setdefault(x.acknowledged_at.date().isoformat(), {"read": 0, "acknowledged": 0})[
                    "acknowledged"
                ] += 1
        pending_ids = [u for u in aud.users if (u not in acked if a.requires_ack else u not in read)]
        return AnnouncementAnalytics(
            announcement_id=a.id,
            audience=len(aud.users),
            read=len(read & set(aud.users)) if aud.users else len(read),
            acknowledged=len(acked),
            requires_ack=a.requires_ack,
            funnel=[{"day": k, **v} for k, v in sorted(by_day.items())],
            pending=[{"user_id": str(u), "name": aud.users[u]["name"]} for u in pending_ids[:500]]
            if with_pending
            else [],
        )

    async def remind(self, aid: uuid.UUID, channels: list[str]) -> CampaignResponse:
        a = await self.announcement(aid)
        stats = await self.analytics(aid)
        ids = [uuid.UUID(p["user_id"]) for p in stats.pending]
        if not ids:
            raise rule("Everybody has already responded", "NOTHING_PENDING")
        body = CampaignCreate(
            name=f"Reminder: {a.title}"[:160],
            channels=[c for c in channels if c in ("in_app", "push", "email") or officer(self.principal)] or ["in_app"],  # type: ignore[misc]
            audience_rules=SegmentRules(person_types=[], custom_user_ids=ids),
            body_override={
                "in_app": f"Please {'acknowledge' if a.requires_ack else 'read'}: {a.title}",
                "push_title": "Reminder",
                "push_body": a.title[:200],
                "email_subject": f"Reminder: {a.title}"[:200],
            },  # type: ignore[arg-type]
        )
        c = await self.create(body)
        row = await self.row(c.id, for_update=True)
        row.status = "approved"
        await self._start(row)
        await self._emit(
            "announcement.ack_reminder_sent",
            {"announcement_id": str(a.id), "recipients": len(ids)},
            "announcement",
            a.id,
        )
        return await self.out(row)

    # ---- emergency -------------------------------------------------------------------------------------------------------
    async def emergency(self, body: EmergencyBroadcast) -> CampaignResponse:
        self.require("emergency")
        await self.require_feature("comms.emergency_broadcast")
        if body.confirm.strip().upper() != EMERGENCY_CONFIRM:
            raise APIError(
                422, ErrorCode.VALIDATION, f"Type {EMERGENCY_CONFIRM} to confirm the broadcast", {"field": "confirm"}
            )
        rules: dict[str, Any] = {"person_types": ["student", "guardian", "staff"]}
        if body.audience == "college" and body.college_id:
            rules["college_id"] = str(body.college_id)
        elif body.audience == "hostel" and body.hostel_id:
            rules["hostel_ids"] = [str(body.hostel_id)]
            rules["person_types"] = ["student", "guardian"]
        elif body.audience == "custom":
            rules = {"person_types": [], "custom_user_ids": [str(u) for u in body.custom_user_ids]}
        channels = body.channels or ["in_app", "push", "sms", "whatsapp", "email"]
        enabled = [
            ch
            for ch in channels
            if ch == "in_app"
            or await self.feature(
                {"sms": "comms.sms", "whatsapp": "comms.whatsapp", "email": "comms.email", "push": "comms.push"}[ch]
            )
        ]
        prefix = "[DRILL] " if body.drill else ""
        c = BulkCampaign(
            institution_id=self.inst,
            name=f"{prefix}EMERGENCY · {body.alert_type.upper()}"[:160],
            channels=enabled,
            audience_rules=rules,
            body_override=json.dumps(
                {
                    "sms": prefix + body.message,
                    "whatsapp_text": prefix + body.message,
                    "push_title": f"{prefix}Emergency alert",
                    "push_body": (prefix + body.message)[:240],
                    "email_subject": f"{prefix}Emergency: {body.alert_type}",
                    "in_app": prefix + body.message,
                }
            ),
            status="approved",
            is_emergency=True,
            created_by=self.actor_id,
        )
        self.db.add(c)
        await self.db.flush()
        await self.put_meta(
            "emergency",
            c.id,
            {
                "alert_type": body.alert_type,
                "message": body.message,
                "raised_by": str(self.actor_id),
                "at": now_utc().isoformat(),
                "drill": body.drill,
                "incident_ref": body.incident_ref,
                "emergency_alert_id": str(body.emergency_alert_id) if body.emergency_alert_id else None,
            },
        )
        await self.put_meta("campaign", c.id, {"respect_quiet_hours": False, "category": "emergency"})
        c.status = "sending"
        await self.db.flush()
        await self.materialise(c)
        await self._audit(
            "emergency_broadcast",
            "bulk_campaign",
            c.id,
            None,
            {"alert_type": body.alert_type, "drill": body.drill, "recipients": c.total_recipients},
        )
        await self._emit(
            "emergency.broadcast_sent",
            {
                "campaign_id": str(c.id),
                "alert_type": body.alert_type,
                "drill": body.drill,
                "recipients": c.total_recipients,
            },
            "bulk_campaign",
            c.id,
        )
        return await self.out(c)

    async def all_clear(self, cid: uuid.UUID, message: str) -> CampaignResponse:
        self.require("emergency")
        src = await self.row(cid)
        if not src.is_emergency:
            raise rule("Not an emergency broadcast", "NOT_EMERGENCY")
        em = await self.meta("emergency", src.id)
        if em.get("all_clear_at"):
            raise rule("All-clear was already sent", "ALREADY_CLEARED")
        c = BulkCampaign(
            institution_id=self.inst,
            name=f"ALL CLEAR · {src.name}"[:160],
            channels=list(src.channels),
            audience_rules=src.audience_rules,
            body_override=json.dumps(
                {
                    "sms": message,
                    "whatsapp_text": message,
                    "push_title": "All clear",
                    "push_body": message[:240],
                    "email_subject": "All clear",
                    "in_app": message,
                }
            ),
            status="sending",
            is_emergency=True,
            created_by=self.actor_id,
        )
        self.db.add(c)
        await self.db.flush()
        await self.put_meta("campaign", c.id, {"respect_quiet_hours": False})
        await self.materialise(c)
        em["all_clear_at"] = now_utc().isoformat()
        em["all_clear_campaign_id"] = str(c.id)
        await self.put_meta("emergency", src.id, em)
        await self._emit(
            "emergency.all_clear",
            {"campaign_id": str(src.id), "all_clear_campaign_id": str(c.id)},
            "bulk_campaign",
            src.id,
        )
        return await self.out(c)

    async def emergency_log(self) -> list[EmergencyLog]:
        self.require("emergency", "view_all")
        metas = await self.metas("emergency")
        rows = (
            await self.db.execute(
                select(BulkCampaign)
                .where(
                    BulkCampaign.institution_id == self.inst,
                    BulkCampaign.id.in_([uuid.UUID(k) for k in metas] or [uuid.uuid4()]),
                )
                .order_by(BulkCampaign.created_at.desc())
            )
        ).scalars()
        out = []
        for c in rows:
            m = metas.get(str(c.id), {})
            out.append(
                EmergencyLog(
                    campaign_id=c.id,
                    alert_type=m.get("alert_type"),
                    message=m.get("message", ""),
                    raised_by=uuid.UUID(m["raised_by"]) if m.get("raised_by") and m["raised_by"] != "None" else None,
                    at=c.created_at,
                    recipients=c.total_recipients,
                    sent=c.sent_count,
                    drill=bool(m.get("drill")),
                    all_clear_at=m.get("all_clear_at"),
                    incident_ref=m.get("incident_ref"),
                )
            )
        return out

    async def due_window(self) -> datetime:
        return now_utc() + timedelta(minutes=1)
