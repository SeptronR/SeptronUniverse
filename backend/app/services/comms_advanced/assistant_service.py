"""AI assistant — Prompts/24 §24.6 ``assistant_service`` (``comms.ai_assistant``).

Opt-in per user (``consent_records`` purpose ``ai_assistant``) and ``comms.assistant.allowed_roles``; the provider is a
``LlmProvider`` adapter — ``mock`` (deterministic: keyword intents → tools → templated answer) ships here, live
providers plug in through ``integration_connections`` (Phase 41). Tools are the read-only helpers in ``tools.py`` run
under the caller's principal; every tool call is audited (``assistant.tool``) and cited; write intents (approve,
cancel, pay, delete …) answer with a deep link only. PII never leaves the tenant unless
``comms.assistant.allow_pii_to_provider`` (the mock provider never sends anything). Conversations are
``conversation_sessions(channel='web'|'mobile', flow_key='assistant')`` kept 30 days; usage counts per month in
``comms_meta``. The feature flag is the kill switch.
"""

import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.tenancy import today_for
from app.models.communication import ConversationSession
from app.models.platform import ConsentRecord
from app.schemas.comms_advanced import AssistantChatRequest, AssistantChatResponse, AssistantConfig, AssistantMe
from app.services.comms_advanced import tools
from app.services.comms_advanced.common import CommsBase, now_utc

RETENTION_DAYS = 30
WRITE_INTENTS = {
    "approve": "/approvals",
    "reject": "/approvals",
    "cancel": "/me",
    "delete": "/me",
    "pay": "/student/fees",
    "apply": "/me",
    "submit": "/me",
}
DEFAULT_CONFIG = {
    "provider": "mock",
    "opt_in_required": True,
    "allowed_roles": [],
    "allow_pii_to_provider": False,
    "max_tokens": 800,
}


class AssistantService(CommsBase):
    async def config(self) -> dict[str, Any]:
        v = await self.setting("comms", "assistant")
        return {**DEFAULT_CONFIG, **(v if isinstance(v, dict) else {})}

    async def put_config(self, body: AssistantConfig) -> dict[str, Any]:
        from app.models.platform import InstitutionSetting

        self.require("template_manage")
        row = (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == self.inst,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == "comms",
                    InstitutionSetting.key == "assistant",
                )
            )
        ).scalar_one_or_none()
        value = body.model_dump()
        if row is None:
            self.db.add(
                InstitutionSetting(
                    institution_id=self.inst,
                    college_id=None,
                    category="comms",
                    key="assistant",
                    value=value,
                    value_type="json",
                    updated_by=self.actor_id,
                )
            )
        else:
            row.value, row.updated_by = value, self.actor_id
        await self.db.flush()
        await self._audit("assistant_config", "assistant", None, None, value)
        return value

    async def opted_in(self) -> bool:
        row = (
            await self.db.execute(
                select(ConsentRecord)
                .where(
                    ConsentRecord.user_id == self.actor_id,
                    ConsentRecord.purpose == "ai_assistant",
                    ConsentRecord.withdrawn_at.is_(None),
                )
                .order_by(ConsentRecord.recorded_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return bool(row and row.granted)

    async def allowed(self) -> bool:
        roles = (await self.config()).get("allowed_roles") or []
        return not roles or bool(set(roles) & set(getattr(self.principal, "roles", []) or []))

    async def me(self) -> AssistantMe:
        return AssistantMe(
            enabled=await self.feature("comms.ai_assistant"),
            opted_in=await self.opted_in(),
            allowed=await self.allowed(),
            provider=str((await self.config())["provider"]),
        )

    async def opt_in(self, accepted: bool) -> AssistantMe:
        if accepted:
            self.db.add(
                ConsentRecord(
                    institution_id=self.inst,
                    user_id=self.actor_id,
                    purpose="ai_assistant",
                    granted=True,
                    text_version="2026-10",
                    granted_by_user_id=self.actor_id,
                )
            )
        else:
            for r in (
                await self.db.execute(
                    select(ConsentRecord).where(
                        ConsentRecord.user_id == self.actor_id,
                        ConsentRecord.purpose == "ai_assistant",
                        ConsentRecord.withdrawn_at.is_(None),
                    )
                )
            ).scalars():
                r.withdrawn_at = now_utc()
        await self.db.flush()
        await self._emit(
            "assistant.opted_in" if accepted else "assistant.opted_out",
            {"user_id": str(self.actor_id)},
            "assistant",
            self.actor_id,
        )
        return await self.me()

    async def _guard(self) -> None:
        await self.require_feature("comms.ai_assistant")
        if not await self.allowed():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "The assistant is not available for your role")
        if (await self.config()).get("opt_in_required", True) and not await self.opted_in():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Opt in to use the assistant", {"code": "OPT_IN_REQUIRED"})

    async def _conversation(self, cid: uuid.UUID | None, channel: str) -> ConversationSession:
        if cid:
            s = (
                await self.db.execute(
                    select(ConversationSession).where(
                        ConversationSession.id == cid,
                        ConversationSession.user_id == self.actor_id,
                        ConversationSession.flow_key == "assistant",
                    )
                )
            ).scalar_one_or_none()
            if s is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Conversation not found")
            return s
        s = ConversationSession(
            institution_id=self.inst,
            channel=channel,
            user_id=self.actor_id,
            flow_key="assistant",
            state={},
            messages=[],
        )
        self.db.add(s)
        await self.db.flush()
        return s

    async def _tool(self, name: str, coro: Any) -> tuple[str, dict[str, Any]]:
        text_out, data = await coro
        await self._audit(
            "assistant.tool", "assistant", None, None, {"tool": name, **{k: v for k, v in data.items() if k != "tool"}}
        )
        return text_out, data

    async def chat(self, body: AssistantChatRequest, channel: str = "web") -> AssistantChatResponse:
        await self._guard()
        s = await self._conversation(body.conversation_id, "mobile" if channel == "mobile" else "web")
        msg = body.message.strip()
        low = msg.lower()
        p = self.principal
        citations: list[str] = []
        calls: list[dict[str, Any]] = []
        links: list[dict[str, str]] = []
        replies: list[str] = []
        write = next((w for w in WRITE_INTENTS if re.search(rf"\b{w}\b", low)), None)
        students = await tools.students_of(self.db, p)
        target = students[0] if students else None
        # someone else's data? (a name in the question that is not the caller / a ward)
        other = re.search(r"\b(?:of|for)\s+([a-z]+(?:\s[a-z]+)?)\b", low)
        if (
            other
            and students
            and not any(other.group(1).split()[0] in st.full_name.lower() for st in students)
            and other.group(1).split()[0] not in ("me", "my", "today", "tomorrow", "this", "the", "dbms", "course")
        ):
            target = None
            replies.append("I can only answer about your own records (or your wards').")
        today = today_for(await self.institution())
        if write:
            links.append({"label": "Open the page", "href": f"{settings.frontend_url}{WRITE_INTENTS[write]}"})
            replies.append(
                f"I can't {write} things for you, but you can do it here: {settings.frontend_url}{WRITE_INTENTS[write]}"
            )
        elif "department" in low and "attendance" in low:
            below = float(m.group(1)) if (m := re.search(r"(\d{2})\s*%?", low)) else 75.0
            t, d = await self._tool("department_attendance", tools.department_attendance(self.db, p, below))
            replies.append(t)
            calls.append(d)
        elif "collection" in low or ("fee" in low and "today" in low and p.has("fees", "view_all")):
            t, d = await self._tool("fee_collection_today", tools.fee_collection_today(self.db, p, today))
            replies.append(t)
            calls.append(d)
        elif target is not None and "attendance" in low:
            course = m.group(1) if (m := re.search(r"\bin\s+([a-z0-9]{2,12})\b", low)) else None
            t, d = await self._tool("my_attendance", tools.attendance(self.db, p, target, course))
            replies.append(t)
            calls.append(d)
        elif target is not None and any(w in low for w in ("due", "fee", "fees", "pending payment")):
            t, d = await self._tool("my_dues", tools.dues(self.db, p, target))
            replies.append(t)
            calls.append(d)
        elif target is not None and any(w in low for w in ("timetable", "class", "classes", "schedule")):
            day = today + timedelta(days=1) if "tomorrow" in low else today
            t, d = await self._tool("my_timetable", tools.timetable(self.db, p, target, day))
            replies.append(t)
            calls.append(d)
        elif target is not None and any(w in low for w in ("result", "sgpa", "cgpa", "grade")):
            t, d = await self._tool("my_results", tools.results(self.db, p, target))
            replies.append(t)
            calls.append(d)
        elif target is not None and any(w in low for w in ("outpass", "out-pass", "leave")):
            t, d = await self._tool("outpass_status", tools.outpass(self.db, p, target))
            replies.append(t)
            calls.append(d)
        elif not replies:
            t, d = await self._tool("faq", tools.faq(self.db, msg))
            if t:
                replies.append(t)
                calls.append(d)
            else:
                replies.append(
                    'I can help with your attendance, dues, timetable, results and out-pass status, or look up help articles. Try: "what is my attendance in DBMS?"'
                )
        citations = [f"tool:{c['tool']}" for c in calls if c.get("tool")]
        reply = "\n\n".join(replies)
        s.messages = [
            *(s.messages or []),
            {"role": "user", "text": msg, "at": now_utc().isoformat()},
            {"role": "assistant", "text": reply, "citations": citations, "at": now_utc().isoformat()},
        ][-100:]
        s.last_activity_at = now_utc()
        month = today.strftime("%Y-%m")
        usage = await self.meta("assistant_usage", month)
        usage["messages"] = int(usage.get("messages", 0)) + 1
        usage["tool_calls"] = int(usage.get("tool_calls", 0)) + len(calls)
        intents = dict(usage.get("intents") or {})
        for c in calls:
            intents[c["tool"]] = int(intents.get(c["tool"], 0)) + 1
        usage["intents"] = intents
        await self.put_meta("assistant_usage", month, usage)
        await self._emit(
            "assistant.answered", {"conversation_id": str(s.id), "tools": [c["tool"] for c in calls]}, "assistant", s.id
        )
        await self.db.flush()
        return AssistantChatResponse(
            conversation_id=s.id, reply=reply, citations=citations, tool_calls=calls, links=links
        )

    async def conversations(self) -> list[dict[str, Any]]:
        await self._guard()
        rows = (
            await self.db.execute(
                select(ConversationSession)
                .where(ConversationSession.user_id == self.actor_id, ConversationSession.flow_key == "assistant")
                .order_by(ConversationSession.last_activity_at.desc())
                .limit(50)
            )
        ).scalars()
        return [
            {
                "id": str(s.id),
                "channel": s.channel,
                "last_activity_at": s.last_activity_at.isoformat(),
                "messages": s.messages or [],
            }
            for s in rows
        ]

    async def delete_conversation(self, cid: uuid.UUID) -> None:
        s = (
            await self.db.execute(
                select(ConversationSession).where(
                    ConversationSession.id == cid,
                    ConversationSession.user_id == self.actor_id,
                    ConversationSession.flow_key == "assistant",
                )
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Conversation not found")
        await self.db.delete(s)

    async def usage(self) -> dict[str, Any]:
        self.require("template_manage", "view_all")
        return {"by_month": await self.metas("assistant_usage"), "config": await self.config()}

    async def retention(self) -> int:
        cutoff = now_utc() - timedelta(days=RETENTION_DAYS)
        rows = list(
            (
                await self.db.execute(
                    select(ConversationSession).where(
                        ConversationSession.institution_id == self.inst,
                        ConversationSession.flow_key == "assistant",
                        ConversationSession.last_activity_at < cutoff,
                    )
                )
            ).scalars()
        )
        for s in rows:
            await self.db.delete(s)
        await self.db.flush()
        return len(rows)
