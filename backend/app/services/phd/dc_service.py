"""Doctoral committee — Prompts/31 §31.6 ``dc_service`` ({phd.dc_meetings}).

The DC (``doctoral_committees`` — one per scholar) is constituted by the guide or the research cell: the guide is
the convenor, at least ``phd.rules.dc_min_external`` external member, subject experts; optionally bound to a Phase 33
committee (Phase 27 stub until then). Members are ``{staff_id | external{name, affiliation, email}, role}``; a staff
member listed there owns the scholar (``phd:dc`` ownership). Meetings (``meeting_no`` unique per scholar → 409
``DUPLICATE_MEETING``) carry agenda, attendance, minutes and recommendations (action items with due dates) and move
``scheduled → held`` (minutes) ``→ approved`` (convenor). Pre-synopsis presentations are DC meetings of
``kind='pre_synopsis'``. The thesis DC approval runs the ``phd.thesis_dc_approval`` workflow (``thesis_service``).
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.phd import DcMeeting, DoctoralCommittee, ResearchScholar
from app.schemas.phd import DcConstitute, DcMeetingApprove, DcMeetingCreate, DcMeetingMinutes, DcMeetingOut, DcOut
from app.services.phd.common import PhdBase, forbidden, not_found, now_utc, rule, staff_name

ENTITY = "doctoral_committee"


class DcService(PhdBase):
    async def committee_row(self, scholar_id: uuid.UUID) -> DoctoralCommittee | None:
        return (
            await self.db.execute(select(DoctoralCommittee).where(DoctoralCommittee.scholar_id == scholar_id))
        ).scalar_one_or_none()

    async def committee_out(self, s: ResearchScholar) -> DcOut | None:
        dc = await self.committee_row(s.id)
        if dc is None:
            return None
        m = await self.meta("dc", dc.id)
        n = int((await self.db.execute(select(func.count()).where(DcMeeting.scholar_id == s.id))).scalar_one())
        staff = await self.staff_map([uuid.UUID(str(x["staff_id"])) for x in dc.members or [] if x.get("staff_id")])
        members = [
            {
                **x,
                "name": (
                    staff_name(staff.get(uuid.UUID(str(x["staff_id"]))))
                    if x.get("staff_id")
                    else (x.get("external") or {}).get("name")
                ),
            }
            for x in dc.members or []
        ]
        return DcOut(
            id=dc.id,
            scholar_id=s.id,
            members=members,
            constituted_on=dc.constituted_on,
            committee_id=m.get("committee_id"),
            meetings=n,
        )

    async def get(self, sid: uuid.UUID) -> DcOut | None:
        return await self.committee_out(await self.scholar(sid))

    async def _members(self, s: ResearchScholar, body: DcConstitute) -> list[dict[str, Any]]:
        members: list[dict[str, Any]] = []
        seen: set[str] = set()
        for mb in body.members:
            if mb.staff_id is not None:
                await self.staff_row(mb.staff_id)
                key = str(mb.staff_id)
                if key in seen:
                    raise rule("A member is listed twice", "DUPLICATE_MEMBER", 422)
                seen.add(key)
                members.append({"staff_id": key, "role": mb.role.value})
            else:
                assert mb.external is not None
                members.append({"external": mb.external.model_dump(mode="json"), "role": "external"})
        convenors = [x for x in members if x["role"] == "convenor"]
        if not convenors:
            # the guide is the convenor by default
            g = next((x for x in members if x.get("staff_id") == str(s.guide_staff_id)), None)
            if g is None:
                members.insert(0, {"staff_id": str(s.guide_staff_id), "role": "convenor"})
            else:
                g["role"] = "convenor"
        elif len(convenors) > 1:
            raise rule("A committee has one convenor", "ONE_CONVENOR", 422)
        externals = sum(1 for x in members if x["role"] == "external")
        need = await self.rule_int("dc_min_external")
        if externals < need:
            raise rule(f"The committee needs at least {need} external member(s)", "EXTERNAL_REQUIRED", 422)
        return members

    async def constitute(self, sid: uuid.UUID, body: DcConstitute, *, replace: bool = False) -> DcOut:
        s = await self.scholar(sid, lock=True)
        await self.require_relation(s, "guide")
        dc = await self.committee_row(s.id)
        if dc is not None and not replace:
            raise rule("The committee is already constituted — update its members", "DC_EXISTS")
        if dc is None and replace:
            raise not_found("Doctoral committee")
        members = await self._members(s, body)
        if dc is None:
            dc = DoctoralCommittee(
                institution_id=self.inst, scholar_id=s.id, members=members, constituted_on=await self.today()
            )
            self.db.add(dc)
        else:
            dc.members = members
        await self.db.flush()
        if body.committee_id:
            await self.put_meta("dc", dc.id, {"committee_id": str(body.committee_id)})
        sm = await self.meta("scholar", s.id)
        if sm.pop("dc_reconstitution_required", None):
            await self.put_meta("scholar", s.id, sm)
        await self.scholar_timeline(s, "dc_reconstituted" if replace else "dc_constituted", members=len(members))
        await self._emit(
            "phd.dc_constituted", {"scholar_id": str(s.id), "committee_id": str(dc.id), "members": len(members)},
            ENTITY, dc.id,
        )  # fmt: skip
        return await self.committee_out(s)  # type: ignore[return-value]

    # ---- meetings -----------------------------------------------------------------------------------------------------
    async def meeting_outs(self, rows: list[DcMeeting]) -> list[DcMeetingOut]:
        metas = await self.metas("dcm", [r.id for r in rows])
        out = []
        for r in rows:
            m = metas.get(str(r.id)) or {}
            out.append(
                DcMeetingOut(
                    id=r.id,
                    scholar_id=r.scholar_id,
                    meeting_no=r.meeting_no,
                    held_on=r.held_on,
                    status=r.status,
                    kind=m.get("kind") or "regular",
                    agenda=m.get("agenda"),
                    minutes=r.minutes,
                    minutes_url=r.minutes_url,
                    recommendations=list(r.recommendations or []),
                    attendance=list(m.get("attendance") or []),
                )
            )
        return out

    async def meetings(self, sid: uuid.UUID) -> list[DcMeetingOut]:
        s = await self.scholar(sid)
        rows = list(
            (
                await self.db.execute(
                    select(DcMeeting).where(DcMeeting.scholar_id == s.id).order_by(DcMeeting.meeting_no)
                )
            ).scalars()
        )
        return await self.meeting_outs(rows)

    async def schedule(self, sid: uuid.UUID, body: DcMeetingCreate) -> DcMeetingOut:
        s = await self.scholar(sid, lock=True)
        await self.require_relation(s, "guide", "convenor")
        if await self.committee_row(s.id) is None:
            raise rule("Constitute the doctoral committee first", "DC_REQUIRED")
        dup = (
            await self.db.execute(
                select(DcMeeting.id).where(DcMeeting.scholar_id == s.id, DcMeeting.meeting_no == body.meeting_no)
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise rule(f"Meeting {body.meeting_no} exists", "DUPLICATE_MEETING", 409)
        mt = DcMeeting(institution_id=self.inst, scholar_id=s.id, meeting_no=body.meeting_no, held_on=body.held_on)
        self.db.add(mt)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise rule(f"Meeting {body.meeting_no} exists", "DUPLICATE_MEETING", 409) from exc
        await self.put_meta("dcm", mt.id, {"agenda": body.agenda, "kind": body.kind})
        await self._emit(
            "phd.meeting_scheduled",
            {
                "scholar_id": str(s.id),
                "meeting_id": str(mt.id),
                "meeting_no": mt.meeting_no,
                "held_on": str(mt.held_on),
            },
            "dc_meeting",
            mt.id,
        )
        users = [await self.scholar_user(s)]
        for x in await self.dc_members(s.id):
            if x.get("staff_id"):
                users.append(await self.staff_user(uuid.UUID(str(x["staff_id"]))))
        await self._notify(
            "phd.dc_meeting_scheduled",
            users,
            {"scholar": await self.scholar_name(s), "meeting_no": mt.meeting_no, "held_on": str(mt.held_on)},
        )
        return (await self.meeting_outs([mt]))[0]

    async def _meeting(self, mid: uuid.UUID, *, lock: bool = False) -> tuple[DcMeeting, ResearchScholar]:
        stmt = select(DcMeeting).where(DcMeeting.id == mid, DcMeeting.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        mt = (await self.db.execute(stmt)).scalar_one_or_none()
        if mt is None:
            raise not_found("DC meeting")
        return mt, await self.scholar(mt.scholar_id)

    async def minutes(self, mid: uuid.UUID, body: DcMeetingMinutes) -> DcMeetingOut:
        mt, s = await self._meeting(mid, lock=True)
        await self.require_relation(s, "guide", "convenor")
        if mt.status == "approved":
            raise rule("Approved minutes are locked", "MINUTES_LOCKED")
        mt.minutes = body.minutes
        mt.minutes_url = body.minutes_url
        mt.recommendations = [
            {
                "id": uuid.uuid4().hex[:8],
                "text": r.text,
                "due_on": r.due_on.isoformat() if r.due_on else None,
                "done": False,
            }
            for r in body.recommendations
        ]
        mt.status = "held"
        m = await self.meta("dcm", mt.id)
        m["attendance"] = body.attendance
        await self.put_meta("dcm", mt.id, m)
        await self.db.flush()
        return (await self.meeting_outs([mt]))[0]

    async def approve(self, mid: uuid.UUID, body: DcMeetingApprove) -> DcMeetingOut:
        mt, s = await self._meeting(mid, lock=True)
        self.require_writer()
        rel = await self.relation(s)
        if not ("convenor" in rel or "guide" in rel or self.cell()):
            raise forbidden("The DC convenor approves the minutes")
        if mt.status != "held":
            raise rule("Record the minutes before approval", "MINUTES_REQUIRED")
        mt.status = "approved"
        m = await self.meta("dcm", mt.id)
        m["approved"] = {"by": str(self.actor_id), "at": now_utc().isoformat(), "remarks": body.remarks}
        await self.put_meta("dcm", mt.id, m)
        await self.db.flush()
        await self._emit(
            "phd.meeting_approved",
            {"scholar_id": str(s.id), "meeting_id": str(mt.id), "recommendations": len(mt.recommendations or [])},
            "dc_meeting",
            mt.id,
        )
        return (await self.meeting_outs([mt]))[0]

    async def member_user_ids(self, s: ResearchScholar) -> list[uuid.UUID]:
        out: list[uuid.UUID] = []
        for x in await self.dc_members(s.id):
            if x.get("staff_id") and x.get("role") != "convenor":
                u = await self.staff_user(uuid.UUID(str(x["staff_id"])))
                if u:
                    out.append(u)
        return out

    async def convenor_user(self, s: ResearchScholar) -> uuid.UUID | None:
        for x in await self.dc_members(s.id):
            if x.get("role") == "convenor" and x.get("staff_id"):
                return await self.staff_user(uuid.UUID(str(x["staff_id"])))
        return await self.staff_user(s.guide_staff_id)
