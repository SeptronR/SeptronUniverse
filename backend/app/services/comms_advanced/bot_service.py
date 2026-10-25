"""WhatsApp bot — Prompts/24 §24.6 ``bot_service`` (``comms.whatsapp_bot``).

Webhook → signature check (``X-Hub-Signature-256`` HMAC with the connection's app secret; the mock / simulator path
skips it) → ``wa_processed_messages`` idempotency (UNIQUE ``wa_message_id``) → session by phone
(``conversation_sessions(channel='whatsapp', external_id=<phone>)``) → identity: the phone's verified user (student,
guardian, staff); unknown numbers get the link-your-number reply. Flow engine: the numbered menu from
``comms.bot_flows`` (``platform_settings['bot_flows']`` default), state in ``conversation_sessions.state``; guardians pick a
ward first. Tools run under the resolved user's principal (``tools.py``). ``complaint`` collects one free-text message
and notifies the office; ``talk_to_human`` flags the session for the hand-off queue. Replies are ``message_logs``
rows (``channel='whatsapp'``, ``event_type='bot.reply'``) delivered through the Phase 04 adapter; outside the 24 h
customer-service window the first reply is the approved ``utility`` template. Transcripts are masked for officers.
"""

import hashlib
import hmac
import json
import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import APIError, ErrorCode
from app.core.tenancy import today_for
from app.enums.comms_advanced import BOT_FLOWS
from app.models.communication import ConversationSession, MessageLog, WaProcessedMessage
from app.models.platform import User
from app.schemas.comms_advanced import BotFlowsPut, BotSessionOut
from app.services.comms_advanced import tools
from app.services.comms_advanced.common import CommsBase, now_utc, rule

WINDOW = timedelta(hours=24)
RETENTION_DAYS = 90


def norm_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p or "")
    return digits[-10:]


def mask_phone(p: str | None) -> str | None:
    return ("•••••" + p[-4:]) if p else None


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, header.split("=", 1)[1])


class BotService(CommsBase):
    async def flows(self) -> dict[str, Any]:
        from sqlalchemy import text

        conf = await self.get_json("comms", "bot_flows", None)
        if isinstance(conf, dict) and conf.get("flows"):
            return conf
        row = (
            await self.db.execute(text("SELECT value FROM platform_settings WHERE key = 'bot_flows'"))
        ).scalar_one_or_none()
        if isinstance(row, dict) and row.get("flows"):
            return row
        return {"flows": BOT_FLOWS, "greeting": "Hello! Reply with a number:"}

    async def put_flows(self, body: BotFlowsPut) -> dict[str, Any]:
        self.require("template_manage", "bulk")
        conf = {
            "flows": [f.model_dump() for f in body.flows],
            "greeting": body.greeting or "Hello! Reply with a number:",
        }
        await self.put_json("comms", "bot_flows", conf)
        await self._audit("bot_flows", "bot", None, None, {"flows": [f.key for f in body.flows]})
        return conf

    def _menu(self, conf: dict[str, Any], roles: list[str]) -> str:
        items = [
            f
            for f in conf["flows"]
            if f.get("enabled", True) and (not f.get("roles") or set(f["roles"]) & set(roles) or not roles)
        ]
        return str(
            conf.get("greeting", "Reply with a number:")
            + "\n"
            + "\n".join(f"{n}. {f['label']}" for n, f in enumerate(items, start=1))
        )

    async def _session(self, phone: str) -> ConversationSession:
        s = (
            await self.db.execute(
                select(ConversationSession)
                .where(
                    ConversationSession.institution_id == self.inst,
                    ConversationSession.channel == "whatsapp",
                    ConversationSession.external_id == phone,
                )
                .order_by(ConversationSession.last_activity_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if s is None or (s.state or {}).get("step") == "closed":
            s = ConversationSession(
                institution_id=self.inst,
                channel="whatsapp",
                external_id=phone,
                flow_key="menu",
                state={"step": "menu"},
                messages=[],
            )
            self.db.add(s)
            await self.db.flush()
            await self._emit("bot.session_started", {"session_id": str(s.id)}, "conversation", s.id)
        return s

    async def _user_for(self, phone: str) -> User | None:
        tail = norm_phone(phone)
        if not tail:
            return None
        rows = list(
            (
                await self.db.execute(
                    select(User).where(
                        User.institution_id == self.inst, User.phone.ilike(f"%{tail}"), User.deleted_at.is_(None)
                    )
                )
            ).scalars()
        )
        verified = [u for u in rows if u.is_verified]
        return (verified or rows)[0] if (verified or rows) else None

    async def _reply(self, s: ConversationSession, text_body: str, user_id: uuid.UUID | None) -> None:
        from app.core.jobs import send_after_commit
        from app.db.session import redis_client
        from app.services.notifications.dispatcher import BODY_TTL, body_key

        log = MessageLog(
            institution_id=self.inst,
            user_id=user_id,
            recipient=str(s.external_id),
            channel="whatsapp",
            event_type="bot.reply",
            body_preview=text_body[:255],
            status="queued",
        )
        self.db.add(log)
        await self.db.flush()
        await redis_client.set(body_key(log.id), json.dumps({"subject": "", "body": text_body}), ex=BODY_TTL)
        send_after_commit(self.db, "notifications.deliver", [str(log.id)], "notifications", str(uuid.uuid4()))
        s.messages = [*(s.messages or []), {"from": "bot", "text": text_body, "at": now_utc().isoformat()}][-200:]

    async def handle(self, phone: str, text_in: str, wa_message_id: str | None = None) -> dict[str, Any]:
        """Process one inbound message; returns ``{duplicate, replies[]}``."""
        from app.services.auth_service import load_principal

        if wa_message_id:
            try:
                async with self.db.begin_nested():
                    self.db.add(WaProcessedMessage(institution_id=self.inst, wa_message_id=wa_message_id))
                    await self.db.flush()
            except IntegrityError:
                return {"duplicate": True, "replies": []}
        phone = norm_phone(phone) or phone
        s = await self._session(phone)
        prev_activity = s.last_activity_at
        s.messages = [*(s.messages or []), {"from": "user", "text": text_in, "at": now_utc().isoformat()}][-200:]
        s.last_activity_at = now_utc()
        conf = await self.flows()
        user = await self._user_for(phone)
        replies: list[str] = []
        if prev_activity and now_utc() - prev_activity > WINDOW and len(s.messages) > 2:  # noqa: PLR2004
            replies.append("[template:utility_session_reopen] Hi, this is your institution's assistant.")
        if user is None:
            s.user_id = None
            replies.append(
                "We could not find this number in our records. Please update your mobile number in the portal profile, or reply 9 to talk to the office."
            )
            if text_in.strip() in ("9", "human", "office"):
                await self._handoff(s, None)
                replies.append("The office has been notified; someone will reach out.")
            for r in replies:
                await self._reply(s, r, None)
            return {"duplicate": False, "replies": replies}
        s.user_id = user.id
        principal = await load_principal(self.db, user.id)
        roles = list(getattr(principal, "roles", []) or [])
        flows = [
            f
            for f in conf["flows"]
            if f.get("enabled", True) and (not f.get("roles") or set(f["roles"]) & set(roles) or not roles)
        ]
        state = dict(s.state or {"step": "menu"})
        msg = text_in.strip().lower()
        students = await tools.students_of(self.db, principal)
        if state.get("step") == "await_text" and state.get("flow") == "complaint":
            await self._notify(
                "communication.bot_handoff",
                [],
                {"phone": mask_phone(phone), "text": text_in[:300], "kind": "complaint"},
                audience={"roles": ["receptionist", "institution_admin"]},
            )
            replies.append("Thank you — your complaint is registered and forwarded to the office.")
            state = {"step": "menu"}
            await self._emit("bot.flow_completed", {"session_id": str(s.id), "flow": "complaint"}, "conversation", s.id)
        elif state.get("step") == "await_ward":
            idx = int(msg) - 1 if msg.isdigit() else -1
            if 0 <= idx < len(students):
                state["ward_id"] = str(students[idx].id)
                replies.append(await self._run(state["flow"], principal, students[idx], text_in))
                state = {"step": "menu", "ward_id": state["ward_id"]}
            else:
                replies.append("Please reply with the ward's number.")
        else:
            flow = None
            if msg.isdigit() and 1 <= int(msg) <= len(flows):
                flow = flows[int(msg) - 1]
            else:
                flow = next(
                    (f for f in flows if any(w in msg for w in f.get("trigger_words", []) if not w.isdigit())), None
                )
            if flow is None:
                replies.append(self._menu(conf, roles))
            elif flow["key"] == "talk_to_human":
                await self._handoff(s, user.id)
                replies.append("The office has been notified; someone will reply here shortly.")
            elif flow["key"] == "complaint":
                state = {"step": "await_text", "flow": "complaint"}
                replies.append("Please describe your complaint in one message.")
            elif not students and flow["key"] != "talk_to_human":
                replies.append("This option is for students and parents. Reply 9 to talk to the office.")
            elif len(students) > 1 and not state.get("ward_id"):
                state = {"step": "await_ward", "flow": flow["key"]}
                replies.append(
                    "Which ward?\n" + "\n".join(f"{n}. {st.full_name}" for n, st in enumerate(students, start=1))
                )
            else:
                st = next((x for x in students if str(x.id) == state.get("ward_id")), students[0])
                replies.append(await self._run(flow["key"], principal, st, text_in))
                await self._emit(
                    "bot.flow_completed", {"session_id": str(s.id), "flow": flow["key"]}, "conversation", s.id
                )
        s.state = state
        for r in replies:
            await self._reply(s, r, user.id)
        await self.db.flush()
        return {"duplicate": False, "replies": replies}

    async def _run(self, key: str, principal: Any, student: Any, text_in: str) -> str:
        today = today_for(await self.institution())
        if key == "attendance":
            return (await tools.attendance(self.db, principal, student))[0]
        if key == "dues":
            return (await tools.dues(self.db, principal, student))[0]
        if key == "timetable":
            day = today + timedelta(days=1) if "tomorrow" in text_in.lower() else today
            return (await tools.timetable(self.db, principal, student, day))[0]
        if key == "results":
            return (await tools.results(self.db, principal, student))[0]
        if key == "hall_ticket":
            from app.core.config import settings

            return f"Download your hall ticket from the portal: {settings.frontend_url}/student/exams"
        if key == "outpass_status":
            return (await tools.outpass(self.db, principal, student))[0]
        if key == "receipt":
            return (await tools.receipt(self.db, principal, student))[0]
        return "Sorry, that option is not available."

    async def _handoff(self, s: ConversationSession, user_id: uuid.UUID | None) -> None:
        st = dict(s.state or {})
        st["handoff"] = True
        st["handoff_at"] = now_utc().isoformat()
        s.state = st
        await self._notify(
            "communication.bot_handoff",
            [],
            {
                "phone": mask_phone(s.external_id),
                "text": (s.messages or [{}])[-1].get("text", "")[:300],
                "kind": "talk_to_human",
            },
            audience={"roles": ["receptionist", "institution_admin"]},
        )
        await self._emit("bot.handoff", {"session_id": str(s.id)}, "conversation", s.id)

    # ---- officer / self views ---------------------------------------------------------------------------------------------
    def out(self, s: ConversationSession, *, masked: bool) -> BotSessionOut:
        msgs = list(s.messages or [])
        if masked:
            msgs = [
                {
                    **m,
                    "text": re.sub(
                        r"\d{4,}", lambda x: "•" * (len(x.group()) - 2) + x.group()[-2:], str(m.get("text", ""))
                    ),
                }
                for m in msgs
            ]
        return BotSessionOut(
            id=s.id,
            channel=s.channel,
            phone=mask_phone(s.external_id) if masked else s.external_id,
            user_id=s.user_id,
            flow_key=s.flow_key,
            state=s.state,
            messages=msgs,
            last_activity_at=s.last_activity_at,
            handoff=bool((s.state or {}).get("handoff")),
        )

    async def sessions(self, status: str | None = None, handoff_only: bool = False) -> list[BotSessionOut]:
        self.require("template_manage", "bulk", "view_all")
        q = (
            select(ConversationSession)
            .where(ConversationSession.institution_id == self.inst, ConversationSession.channel == "whatsapp")
            .order_by(ConversationSession.last_activity_at.desc())
            .limit(500)
        )
        rows = [self.out(s, masked=True) for s in (await self.db.execute(q)).scalars()]
        if handoff_only or status == "handoff":
            rows = [r for r in rows if r.handoff]
        return rows

    async def session(self, sid: uuid.UUID) -> BotSessionOut:
        self.require("template_manage", "bulk", "view_all")
        s = (
            await self.db.execute(
                select(ConversationSession).where(
                    ConversationSession.id == sid, ConversationSession.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Session not found")
        return self.out(s, masked=True)

    async def close_handoff(self, sid: uuid.UUID) -> BotSessionOut:
        self.require("template_manage", "bulk")
        s = (
            await self.db.execute(
                select(ConversationSession).where(
                    ConversationSession.id == sid, ConversationSession.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Session not found")
        st = dict(s.state or {})
        if not st.get("handoff"):
            raise rule("The session is not in the hand-off queue", "NOT_HANDOFF")
        st.update(handoff=False, handoff_closed_at=now_utc().isoformat(), handoff_closed_by=str(self.actor_id))
        s.state = st
        await self.db.flush()
        return self.out(s, masked=True)

    async def my_sessions(self) -> list[BotSessionOut]:
        rows = (
            await self.db.execute(
                select(ConversationSession)
                .where(ConversationSession.user_id == self.actor_id, ConversationSession.channel == "whatsapp")
                .order_by(ConversationSession.last_activity_at.desc())
            )
        ).scalars()
        return [self.out(s, masked=False) for s in rows]

    async def test(self, message: str, as_user_id: uuid.UUID | None) -> dict[str, Any]:
        self.require("template_manage", "bulk")
        phone = "0000000000"
        if as_user_id:
            u = (
                await self.db.execute(select(User).where(User.id == as_user_id, User.institution_id == self.inst))
            ).scalar_one_or_none()
            phone = norm_phone(u.phone) if u and u.phone else phone
        return await self.handle(phone, message, f"test-{uuid.uuid4().hex}")

    async def expire_sessions(self) -> int:
        cutoff = now_utc() - WINDOW
        n = 0
        for s in (
            await self.db.execute(
                select(ConversationSession).where(
                    ConversationSession.institution_id == self.inst,
                    ConversationSession.channel == "whatsapp",
                    ConversationSession.last_activity_at < cutoff,
                )
            )
        ).scalars():
            st = dict(s.state or {})
            if st.get("step") != "closed" and not st.get("handoff"):
                st["step"] = "closed"
                s.state = st
                n += 1
        old = now_utc() - timedelta(days=RETENTION_DAYS)
        for s in (
            await self.db.execute(
                select(ConversationSession).where(
                    ConversationSession.institution_id == self.inst,
                    ConversationSession.channel == "whatsapp",
                    ConversationSession.last_activity_at < old,
                )
            )
        ).scalars():
            await self.db.delete(s)
        await self.db.flush()
        return n
