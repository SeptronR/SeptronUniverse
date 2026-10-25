"""Emergency / SOS — Prompts/25 §25.6 ``emergency_service`` ({facilities.emergency_sos}).

The mobile SOS button raises ``emergency_alerts(raised_by, alert_type, location{lat, lng, accuracy, text}, message)``;
responders come from ``facilities.sos_responders`` (alert type → role slugs / user ids) and are notified (push / SMS
with a map link); the escalation Beat repeats the alert every ``sos_escalate_minutes`` while ``raised`` and adds the
principal (``vice_chancellor``) from the second round. Responders ``acknowledge`` (who / when) and ``resolve`` with
notes; ``false-alarm`` marks the alert (event for Phase 27 discipline); ``escalate-broadcast`` hands ``fire`` /
``security`` alerts to the Phase 24 emergency broadcast when {comms.emergency_broadcast} is on. Rate limit: more than
``sos_rate_limit.count`` alerts in ``minutes`` → 429 and security is told about the abuse. The timeline, drill and
false-alarm flags live in ``responders`` (``{roles, users, timeline, drill, false_alarm, escalations}``).
Visibility: raiser (self); responders / ``facilities:manage`` / ``view_all`` see all.
"""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.facilities import SOS_RESPONDERS_DEFAULT
from app.models.facilities import EmergencyAlert
from app.schemas.facilities import SosBroadcast, SosNotes, SosOut, SosRaise
from app.services.facilities.common import FacilitiesBase, forbidden, not_found, now_utc, rule


class EmergencyService(FacilitiesBase):
    audit_module = "facilities"

    def responder(self) -> bool:
        return self.can("facilities", "manage") or self.can("facilities", "view_all")

    def _visible(self) -> Any:
        if self.responder():
            return EmergencyAlert.institution_id == self.inst
        return EmergencyAlert.raised_by_user_id == self.actor_id

    async def outs(self, rows: Sequence[EmergencyAlert]) -> list[SosOut]:
        names = await self.user_names([r.raised_by_user_id for r in rows])
        out = []
        for r in rows:
            o = SosOut.model_validate(r)
            o.raised_by_name = names.get(r.raised_by_user_id)
            loc = r.location or {}
            if loc.get("lat") is not None and loc.get("lng") is not None:
                o.map_url = f"https://maps.google.com/?q={loc['lat']},{loc['lng']}"
            resp = r.responders or {}
            o.timeline = resp.get("timeline") or []
            o.false_alarm = bool(resp.get("false_alarm"))
            o.drill = bool(resp.get("drill"))
            if not self.responder():
                o.responders = {"acknowledged": r.acknowledged_at is not None}
            out.append(o)
        return out

    async def row(self, aid: uuid.UUID, *, for_update: bool = False) -> EmergencyAlert:
        stmt = select(EmergencyAlert).where(
            EmergencyAlert.id == aid, EmergencyAlert.institution_id == self.inst, self._visible()
        )
        if for_update:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Alert")
        return r

    async def _targets(self, alert_type: str) -> tuple[list[str], list[str]]:
        table = await self.setting("facilities", "sos_responders")
        cfg = {**SOS_RESPONDERS_DEFAULT, **(table if isinstance(table, dict) else {})}
        roles, users = [], []
        for x in cfg.get(alert_type) or cfg.get("sos") or []:
            try:
                users.append(str(uuid.UUID(str(x))))
            except ValueError:
                roles.append(str(x))
        return roles, users

    def _stamp(self, r: EmergencyAlert, action: str, **extra: Any) -> None:
        resp = dict(r.responders or {})
        tl = list(resp.get("timeline") or [])
        tl.append(
            {
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
                "action": action,
                **extra,
            }
        )
        resp["timeline"] = tl
        r.responders = resp

    async def raise_alert(self, body: SosRaise) -> SosOut:
        if self.actor_id is None:
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Sign in first")
        self.require("facilities:view", "facilities:book", "facilities:manage")
        lim = await self.setting("facilities", "sos_rate_limit")
        count = int((lim or {}).get("count", 3)) if isinstance(lim, dict) else 3
        minutes = int((lim or {}).get("minutes", 10)) if isinstance(lim, dict) else 10
        recent = (
            await self.db.execute(
                select(func.count())
                .select_from(EmergencyAlert)
                .where(
                    EmergencyAlert.raised_by_user_id == self.actor_id,
                    EmergencyAlert.created_at >= now_utc() - timedelta(minutes=minutes),
                )
            )
        ).scalar_one()
        if recent >= count:
            await self._notify(
                "emergency.sos_raised",
                [],
                {
                    "alert_type": "repeated SOS (possible abuse)",
                    "who": str(self.actor_id),
                    "location": "-",
                    "map_url": "",
                },
                audience={"roles": ["security_officer"]},
            )
            raise APIError(
                429, ErrorCode.RATE_LIMITED, "Too many alerts — security has been informed", {"code": "SOS_RATE_LIMIT"}
            )
        roles, users = await self._targets(body.alert_type)
        r = EmergencyAlert(
            institution_id=self.inst,
            raised_by_user_id=self.actor_id,
            alert_type=body.alert_type,
            location=body.location.model_dump(),
            message=body.message,
            status="raised",
            responders={"roles": roles, "users": users, "drill": body.drill, "escalations": 0, "timeline": []},
        )
        self.db.add(r)
        await self.db.flush()
        self._stamp(r, "raised")
        await self.db.flush()
        out = (await self.outs([r]))[0]
        who = (await self.user_names([self.actor_id])).get(self.actor_id, "Someone")
        await self._notify(
            "emergency.sos_raised",
            [],
            {
                "alert_type": ("[DRILL] " if body.drill else "") + body.alert_type.upper(),
                "who": who,
                "location": body.location.text
                or (f"{body.location.lat},{body.location.lng}" if body.location.lat is not None else "unknown"),
                "map_url": out.map_url or "",
            },
            audience={"roles": roles, "user_ids": users},
        )
        await self._audit("raise", "emergency_alert", r.id, None, {"alert_type": r.alert_type, "drill": body.drill})
        await self._emit(
            "emergency.sos_raised", {"alert_id": str(r.id), "alert_type": r.alert_type}, "emergency_alert", r.id
        )
        return out

    async def list_alerts(self, status: str | None = None) -> list[SosOut]:
        if not self.responder():
            raise forbidden("Responders only")
        stmt = select(EmergencyAlert).where(EmergencyAlert.institution_id == self.inst)
        if status:
            stmt = stmt.where(EmergencyAlert.status == status)
        rows = (await self.db.execute(stmt.order_by(EmergencyAlert.created_at.desc()).limit(300))).scalars().all()
        return await self.outs(rows)

    async def mine(self) -> list[SosOut]:
        rows = (
            (
                await self.db.execute(
                    select(EmergencyAlert)
                    .where(
                        EmergencyAlert.institution_id == self.inst, EmergencyAlert.raised_by_user_id == self.actor_id
                    )
                    .order_by(EmergencyAlert.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def get(self, aid: uuid.UUID) -> SosOut:
        return (await self.outs([await self.row(aid)]))[0]

    def _require_responder(self) -> None:
        if not self.can("facilities", "manage"):
            raise forbidden("Responders only")

    async def acknowledge(self, aid: uuid.UUID, body: SosNotes) -> SosOut:
        self._require_responder()
        r = await self.row(aid, for_update=True)
        if r.status != "raised":
            raise rule("The alert was already acknowledged", "ALREADY_ACKNOWLEDGED")
        r.status, r.acknowledged_by, r.acknowledged_at = "acknowledged", self.actor_id, now_utc()
        self._stamp(r, "acknowledged", notes=body.notes)
        await self.db.flush()
        name = (
            (await self.user_names([self.actor_id])).get(self.actor_id, "A responder")
            if self.actor_id
            else "A responder"
        )
        await self._notify(
            "emergency.acknowledged", [r.raised_by_user_id], {"responder": name, "at": r.acknowledged_at.isoformat()}
        )
        await self._audit("acknowledge", "emergency_alert", r.id, None, {"notes": body.notes})
        await self._emit("emergency.acknowledged", {"alert_id": str(r.id)}, "emergency_alert", r.id)
        return (await self.outs([r]))[0]

    async def resolve(self, aid: uuid.UUID, body: SosNotes, *, false_alarm: bool = False) -> SosOut:
        self._require_responder()
        r = await self.row(aid, for_update=True)
        if r.status == "resolved":
            raise rule("The alert is already resolved", "ALREADY_RESOLVED")
        now = now_utc()
        if r.acknowledged_at is None:
            r.acknowledged_by, r.acknowledged_at = self.actor_id, now
        r.status, r.resolved_at = "resolved", now
        resp = dict(r.responders or {})
        if false_alarm:
            resp["false_alarm"] = True
        r.responders = resp
        self._stamp(r, "false_alarm" if false_alarm else "resolved", notes=body.notes)
        await self.db.flush()
        await self._notify(
            "emergency.resolved", [r.raised_by_user_id], {"alert_type": r.alert_type, "notes": body.notes or ""}
        )
        await self._audit(
            "false_alarm" if false_alarm else "resolve", "emergency_alert", r.id, None, {"notes": body.notes}
        )
        await self._emit(
            "emergency.resolved", {"alert_id": str(r.id), "false_alarm": false_alarm}, "emergency_alert", r.id
        )
        if false_alarm:
            await self._emit(
                "emergency.false_alarm",
                {"alert_id": str(r.id), "raised_by_user_id": str(r.raised_by_user_id)},
                "emergency_alert",
                r.id,
            )
        return (await self.outs([r]))[0]

    async def escalate_broadcast(self, aid: uuid.UUID, body: SosBroadcast) -> dict[str, Any]:
        self._require_responder()
        r = await self.row(aid, for_update=True)
        if r.alert_type not in ("fire", "security"):
            raise rule("Only fire / security alerts are broadcast", "NOT_BROADCASTABLE")
        await self.require_feature("comms.emergency_broadcast")
        from app.schemas.comms_advanced import EmergencyBroadcast
        from app.services.comms_advanced.campaign_service import CampaignService

        loc = (r.location or {}).get("text") or "campus"
        drill = bool((r.responders or {}).get("drill"))
        campaign = await CampaignService(self.db, self.principal, self.request).emergency(
            EmergencyBroadcast(
                alert_type=r.alert_type,  # type: ignore[arg-type]
                message=body.message
                or f"{r.alert_type.upper()} alert at {loc}. Follow the instructions of the security staff.",
                audience="all",
                emergency_alert_id=r.id,
                drill=drill,
                confirm=body.confirm,
            )
        )
        self._stamp(r, "broadcast", campaign_id=str(getattr(campaign, "id", "")))
        await self.db.flush()
        return {
            "alert_id": str(r.id),
            "campaign": campaign.model_dump(mode="json") if hasattr(campaign, "model_dump") else campaign,
        }

    async def escalation(self) -> int:
        minutes = await self.int_setting("facilities", "sos_escalate_minutes", 3)
        now = now_utc()
        rows = (
            (
                await self.db.execute(
                    select(EmergencyAlert)
                    .where(EmergencyAlert.institution_id == self.inst, EmergencyAlert.status == "raised")
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for r in rows:
            resp = dict(r.responders or {})
            rounds = int(resp.get("escalations") or 0)
            if now < r.created_at + timedelta(minutes=minutes * (rounds + 1)):
                continue
            resp["escalations"] = rounds + 1
            r.responders = resp
            self._stamp(r, "escalated", round=rounds + 1)
            roles = list(resp.get("roles") or []) + (["vice_chancellor"] if rounds >= 1 else [])
            await self._notify(
                "emergency.sos_raised",
                [],
                {
                    "alert_type": f"ESCALATED {r.alert_type.upper()}",
                    "who": "unacknowledged alert",
                    "location": (r.location or {}).get("text") or "-",
                    "map_url": "",
                },
                audience={"roles": roles, "user_ids": list(resp.get("users") or [])},
            )
            await self._emit(
                "emergency.escalated", {"alert_id": str(r.id), "round": rounds + 1}, "emergency_alert", r.id
            )
            n += 1
        await self.db.flush()
        return n

    async def register(self) -> list[dict[str, Any]]:
        if not self.responder():
            raise forbidden("Responders only")
        return [
            {
                "id": str(o.id),
                "at": o.created_at.isoformat(),
                "type": o.alert_type,
                "raised_by": o.raised_by_name,
                "status": o.status,
                "acknowledged_at": o.acknowledged_at.isoformat() if o.acknowledged_at else None,
                "resolved_at": o.resolved_at.isoformat() if o.resolved_at else None,
                "false_alarm": o.false_alarm,
                "drill": o.drill,
            }
            for o in await self.list_alerts()
        ]
