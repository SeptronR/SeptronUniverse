"""Meetings and minutes — Prompts/33 §33.6 ``meeting_service`` ({governance.minutes}).

1. **Schedule**: meeting number auto per committee / year (``<n>/<yyyy>``), agenda items with documents and linked
   entities, the "ATR on previous minutes" item added automatically (pending action-taken reports of the committee),
   agenda edits until the freeze; **notice** through the Phase 26 ``meeting_notice`` template and the communication
   core to every current member (short notice flagged when fewer than ``governance.notice_days`` remain), Phase 25
   calendar entries, daily reminders.
2. **Held**: attendance (members + invitees), quorum against ``quorum_rule``; when it is not met and
   ``governance.quorum_block`` is on, minutes are refused (409 ``QUORUM_NOT_MET``). Minutes drafting (text or upload)
   with per-item resolution drafts → ``minutes_draft`` → submit starts ``governance.minutes_approval`` (secretary →
   chair) → approve → ``minutes_approved``: resolutions numbered ``<CODE>/<yyyy>/<n>`` under a committee row lock,
   linked entities applied (``regulations`` / ``result_processing_runs`` / ``degrees_awarded`` /
   ``policies``), the Phase 26 ``minutes`` document, ``governance.minutes_approved`` (Phase 32 evidence 6.5.1) and
   owner notifications. Approved minutes are immutable (409 ``MINUTES_APPROVED``); a **corrigendum** keeps the old
   text as a version with its approval record.
3. **Agenda suggestions** per committee type: BoS / Academic Council — draft regulations, verified result runs awaiting
   approval, recommended degrees, BoS resolutions (AC), submitted policies; Finance — open audit paras and submitted
   budgets; IQAC — the Phase 32 dashboard's top improvement gaps and consistency alerts; plus the event inbox
   ``suggestions:<committee_type>`` and the committee's pending ATRs.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select

from app.core.workflow import engine as workflow_engine
from app.models.governance import ActionTakenReport, Committee, CommitteeMember, Meeting, Resolution
from app.models.platform import WorkflowInstance
from app.schemas.governance import (
    AgendaSuggestion,
    AgendaUpdate,
    AttendanceMark,
    Corrigendum,
    LinkedEntity,
    MeetingCancel,
    MeetingCreate,
    MeetingOut,
    MeetingUpdate,
    MinutesApprove,
    MinutesDraft,
    NoticeSend,
    QuorumOut,
)
from app.services.documents.render_service import register_resolver
from app.services.governance.common import (
    GovernanceBase,
    committee_code,
    forbidden,
    not_found,
    now_utc,
    quorum_required,
    rule,
)

ENTITY = "meeting"
WF_KEY = "governance.minutes_approval"
OPEN = ("scheduled", "held", "minutes_draft")


class MeetingService(GovernanceBase):
    # ---- read ---------------------------------------------------------------------------------------------------------
    async def meeting(self, mid: uuid.UUID, *, lock: bool = False) -> Meeting:
        stmt = select(Meeting).where(Meeting.id == mid, Meeting.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        m = (await self.db.execute(stmt)).scalar_one_or_none()
        if m is None:
            raise not_found("Meeting")
        return m

    async def visible_meeting(self, mid: uuid.UUID, *, lock: bool = False) -> tuple[Meeting, Committee]:
        m = await self.meeting(mid, lock=lock)
        c = await self.committee(m.committee_id)
        await self.committee_visible(c)
        return m, c

    async def committee_members(self, c: Committee) -> list[CommitteeMember]:
        today = await self.today()
        return [
            r
            for r in (
                await self.db.execute(select(CommitteeMember).where(CommitteeMember.committee_id == c.id))
            ).scalars()
            if (r.from_on is None or r.from_on <= today) and (r.to_on is None or r.to_on >= today)
        ]

    def quorum(self, c: Committee, m: Meeting, total: int) -> QuorumOut:
        present = len((m.attendance or {}).get("present_member_ids") or [])
        required = quorum_required(c.quorum_rule, total)
        return QuorumOut(met=present >= required, present=present, required=required, total=total)

    async def outs(self, rows: list[Meeting], *, full: bool = False) -> list[MeetingOut]:
        from app.services.governance.resolution_service import ResolutionService

        if not rows:
            return []
        cids = list({r.committee_id for r in rows})
        cmap = {c.id: c for c in (await self.db.execute(select(Committee).where(Committee.id.in_(cids)))).scalars()}
        metas = await self.metas("meeting", [str(r.id) for r in rows])
        owned = await self.owned_committee_ids()
        admin = self.admin()
        res_svc = ResolutionService(self.db, self.principal, self.request, self.inst)
        out: list[MeetingOut] = []
        for r in rows:
            c = cmap[r.committee_id]
            meta = metas.get(str(r.id), {})
            manager = admin or c.id in owned
            draft_hidden = r.status != "minutes_approved" and not manager and not self.reader_all()
            total = len(await self.committee_members(c)) if full else int((r.attendance or {}).get("total") or 0)
            res = await res_svc.for_meeting(r.id) if full else []
            out.append(
                MeetingOut(
                    id=r.id,
                    committee_id=c.id,
                    committee_name=c.name,
                    committee_type=c.committee_type,
                    meeting_no=r.meeting_no,
                    held_on=r.held_on,
                    venue_or_link=r.venue_or_link,
                    agenda=list(r.agenda or []),
                    agenda_frozen=bool(meta.get("agenda_frozen")),
                    status=r.status,
                    notice_sent_at=datetime.fromisoformat(meta["notice_sent_at"])
                    if meta.get("notice_sent_at")
                    else None,
                    short_notice=bool(meta.get("short_notice")),
                    quorum_met=r.quorum_met,
                    quorum=self.quorum(c, r, total) if full and r.attendance else None,
                    attendance=r.attendance if (manager or self.reader_all()) else None,
                    minutes_text=None if draft_hidden else r.minutes_text,
                    minutes_url=None if draft_hidden else r.minutes_url,
                    minutes_version=int(meta.get("minutes_version") or (1 if r.minutes_text else 0)),
                    minutes_pdf_document_id=uuid.UUID(meta["minutes_document_id"])
                    if meta.get("minutes_document_id")
                    else None,
                    approval=list(meta.get("approval") or []),
                    workflow_instance_id=uuid.UUID(meta["workflow_instance_id"])
                    if meta.get("workflow_instance_id")
                    else None,
                    resolutions=res,
                    can_edit=manager and r.status in OPEN,
                )
            )
        return out

    async def list_meetings(
        self,
        *,
        committee_id: uuid.UUID | None = None,
        status: str | None = None,
        scope: str | None = None,
        year: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MeetingOut]:
        stmt = select(Meeting).where(Meeting.institution_id == self.inst)
        if scope == "mine" or not self.reader_all() or scope == "committee":
            if scope == "mine":
                ids: list[uuid.UUID] | None = list(
                    set(await self.my_committee_ids()) | await self.owned_committee_ids()
                )
            elif scope == "committee":
                ids = list(await self.owned_committee_ids())
            else:
                ids = await self.visible_committee_ids()
            if ids is not None:
                stmt = stmt.where(Meeting.committee_id.in_(ids or [uuid.uuid4()]))
        if committee_id:
            stmt = stmt.where(Meeting.committee_id == committee_id)
        if status:
            stmt = stmt.where(Meeting.status == status)
        if year:
            stmt = stmt.where(func.extract("year", Meeting.held_on) == year)
        rows = (await self.db.execute(stmt.order_by(Meeting.held_on.desc()).limit(limit).offset(offset))).scalars()
        return await self.outs(list(rows))

    async def get(self, mid: uuid.UUID) -> MeetingOut:
        m, _ = await self.visible_meeting(mid)
        return (await self.outs([m], full=True))[0]

    # ---- schedule -----------------------------------------------------------------------------------------------------
    async def _next_no(self, c: Committee, when: datetime) -> str:
        n = (
            await self.db.execute(
                select(func.count()).where(
                    Meeting.committee_id == c.id,
                    func.extract("year", Meeting.held_on) == when.year,
                )
            )
        ).scalar_one()
        return f"{int(n) + 1}/{when.year}"[:20]

    async def pending_atr_item(self, c: Committee) -> dict[str, Any] | None:
        pending = (
            await self.db.execute(
                select(func.count())
                .select_from(Resolution)
                .join(Meeting, Meeting.id == Resolution.meeting_id)
                .where(
                    Meeting.committee_id == c.id,
                    Resolution.status == "passed",
                    Resolution.action_owner_staff_id.is_not(None),
                )
            )
        ).scalar_one()
        if not pending:
            return None
        return {
            "item": f"Action taken report on previous minutes ({int(pending)} pending)",
            "source": "atr",
            "linked_entity": {"entity_type": "committee_atr", "entity_id": str(c.id)},
        }

    async def create(self, body: MeetingCreate) -> MeetingOut:
        c = await self.committee(body.committee_id, lock=True)
        await self.require_committee_manager(c)
        if not c.is_active:
            raise rule("The committee is not active", "COMMITTEE_INACTIVE")
        agenda = [a.model_dump(mode="json") for a in body.agenda]
        if body.include_atr:
            atr = await self.pending_atr_item(c)
            if atr:
                agenda.insert(0, atr)
        m = Meeting(
            institution_id=self.inst,
            committee_id=c.id,
            meeting_no=body.meeting_no or await self._next_no(c, body.held_on),
            held_on=body.held_on,
            venue_or_link=body.venue_or_link,
            agenda=agenda,
            status="scheduled",
            created_by=self.actor_id,
        )
        self.db.add(m)
        await self.db.flush()
        await self._calendar(c, m)
        await self._audit("schedule", ENTITY, m.id, None, {"committee": c.name, "held_on": str(m.held_on)})
        await self._emit(
            "governance.meeting_scheduled",
            {"meeting_id": str(m.id), "committee_id": str(c.id), "held_on": m.held_on.isoformat()},
            ENTITY,
            m.id,
        )
        return await self.get(m.id)

    async def _calendar(self, c: Committee, m: Meeting) -> None:
        try:
            from app.models.exams import CalendarEvent

            async with self.db.begin_nested():
                old = (
                    await self.db.execute(
                        select(CalendarEvent).where(
                            CalendarEvent.institution_id == self.inst,
                            CalendarEvent.source_type == ENTITY,
                            CalendarEvent.source_id == m.id,
                        )
                    )
                ).scalar_one_or_none()
                if old is None:
                    self.db.add(
                        CalendarEvent(
                            institution_id=self.inst,
                            college_id=c.college_id,
                            title=f"{c.name} meeting {m.meeting_no or ''}"[:200],
                            description="; ".join(str(a.get("item")) for a in (m.agenda or []))[:2000] or None,
                            event_type="meeting",
                            starts_at=m.held_on,
                            ends_at=m.held_on + timedelta(hours=2),
                            location=(m.venue_or_link or "")[:200] or None,
                            audience_rules={"committee_id": str(c.id)},
                            source_type=ENTITY,
                            source_id=m.id,
                            created_by=self.actor_id,
                        )
                    )
                else:
                    old.starts_at, old.ends_at = m.held_on, m.held_on + timedelta(hours=2)
                    old.deleted_at = now_utc() if m.status == "cancelled" else None
                await self.db.flush()
        except Exception:  # noqa: BLE001 - the calendar entry is a convenience, never blocks scheduling
            return

    async def _editable(self, mid: uuid.UUID) -> tuple[Meeting, Committee]:
        m, c = await self.visible_meeting(mid, lock=True)
        await self.require_committee_manager(c)
        if m.status == "minutes_approved":
            raise rule("Approved minutes are immutable — record a corrigendum", "MINUTES_APPROVED")
        if m.status == "cancelled":
            raise rule("The meeting is cancelled", "MEETING_CANCELLED")
        return m, c

    async def update(self, mid: uuid.UUID, body: MeetingUpdate) -> MeetingOut:
        m, c = await self._editable(mid)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(m, k, v)
        await self.db.flush()
        await self._calendar(c, m)
        return await self.get(m.id)

    async def set_agenda(self, mid: uuid.UUID, body: AgendaUpdate) -> MeetingOut:
        m, _ = await self._editable(mid)
        meta = await self.meta("meeting", m.id)
        if meta.get("agenda_frozen"):
            raise rule("The agenda is frozen", "AGENDA_FROZEN")
        m.agenda = [a.model_dump(mode="json") for a in body.agenda]
        if body.freeze:
            meta["agenda_frozen"] = True
            await self.put_meta("meeting", m.id, meta)
        await self.db.flush()
        return await self.get(m.id)

    async def send_notice(self, mid: uuid.UUID, body: NoticeSend) -> MeetingOut:
        m, c = await self._editable(mid)
        notice_days = await self.gov_int("governance.notice_days")
        short = (m.held_on - now_utc()) < timedelta(days=notice_days)
        members = await self.committee_members(c)
        users = [u.user_id for u in members if u.user_id] + [
            await self.staff_user(u.staff_id) for u in members if u.staff_id and not u.user_id
        ]
        items = "; ".join(str(a.get("item")) for a in (m.agenda or []))[:900]
        await self._notify(
            "governance.meeting_notice",
            users,
            {
                "committee": c.name,
                "held_on": m.held_on.strftime("%d-%m-%Y %H:%M"),
                "venue": m.venue_or_link or "",
                "items": items,
                "short_notice": short,
            },
        )
        doc = await self.render_doc("meeting_notice", ENTITY, m.id, {"meeting.short_notice": short})
        meta = await self.meta("meeting", m.id)
        meta.update(
            {
                "notice_sent_at": now_utc().isoformat(),
                "short_notice": short,
                "notice_channels": list(body.channels),
                "notice_recipients": len([u for u in users if u]),
                "notice_document_id": str(doc.issued_document_id) if doc is not None else None,
                "external_members": [
                    (x.external or {}).get("email") for x in members if x.member_type == "external" and x.external
                ],
            }
        )
        await self.put_meta("meeting", m.id, meta)
        await self._emit(
            "governance.notice_sent",
            {"meeting_id": str(m.id), "short_notice": short, "recipients": len(users)},
            ENTITY,
            m.id,
        )
        return await self.get(m.id)

    # ---- held -------------------------------------------------------------------------------------------------------------
    async def attendance(self, mid: uuid.UUID, body: AttendanceMark) -> QuorumOut:
        m, c = await self.visible_meeting(mid, lock=True)
        members = await self.committee_members(c)
        ids = {x.id for x in members}
        if body.self_check_in:
            sid = await self.my_staff_id()
            mine = [x.id for x in members if x.user_id == self.actor_id or (sid and x.staff_id == sid)]
            if not mine:
                raise forbidden("Not a member of this committee")
            present = set((m.attendance or {}).get("present_member_ids") or []) | {str(i) for i in mine}
            invitees = list((m.attendance or {}).get("invitees") or [])
        else:
            await self.require_committee_manager(c)
            unknown = [i for i in body.present_member_ids if i not in ids]
            if unknown:
                raise rule("Some ids are not current members", "UNKNOWN_MEMBER", 422, ids=[str(i) for i in unknown])
            present = {str(i) for i in body.present_member_ids}
            invitees = list(body.invitees)
        if m.status in ("minutes_approved", "cancelled"):
            raise rule(f"The meeting is {m.status}", "INVALID_TRANSITION")
        total = len(members)
        m.attendance = {
            "present_member_ids": sorted(present),
            "invitees": invitees,
            "total": total,
            "marked_at": now_utc().isoformat(),
            "marked_by": str(self.actor_id) if self.actor_id else None,
        }
        q = self.quorum(c, m, total)
        m.quorum_met = q.met
        if m.status == "scheduled":
            m.status = "held"
        await self.db.flush()
        await self._emit(
            "governance.meeting_held",
            {"meeting_id": str(m.id), "quorum_met": q.met, "present": q.present, "required": q.required},
            ENTITY,
            m.id,
        )
        return q

    async def draft_minutes(self, mid: uuid.UUID, body: MinutesDraft) -> MeetingOut:
        m, c = await self._editable(mid)
        if m.status == "scheduled" or m.attendance is None:
            raise rule("Mark attendance first", "ATTENDANCE_REQUIRED")
        if m.quorum_met is False and await self.gov_setting("governance.quorum_block"):
            raise rule("The quorum was not met", "QUORUM_NOT_MET")
        meta = await self.meta("meeting", m.id)
        if meta.get("submitted"):
            raise rule("The minutes are awaiting approval", "MINUTES_SUBMITTED")
        atr_days = await self.gov_int("governance.atr_due_days")
        today = await self.today()
        drafts = []
        for r in body.resolutions:
            d = r.model_dump(mode="json")
            if r.action_owner_staff_id and not r.due_on and r.status == "passed":
                d["due_on"] = (today + timedelta(days=atr_days)).isoformat()
            drafts.append(d)
        m.minutes_text, m.minutes_url, m.status = body.minutes_text, body.minutes_url, "minutes_draft"
        meta["draft_resolutions"] = drafts
        meta["minutes_version"] = int(meta.get("minutes_version") or 0) or 1
        await self.put_meta("meeting", m.id, meta)
        await self.db.flush()
        await self._emit(
            "governance.minutes_drafted", {"meeting_id": str(m.id), "resolutions": len(drafts)}, ENTITY, m.id
        )
        return await self.get(m.id)

    async def submit_minutes(self, mid: uuid.UUID) -> MeetingOut:
        m, c = await self._editable(mid)
        if m.status != "minutes_draft" or not m.minutes_text:
            raise rule("Draft the minutes first", "NO_DRAFT")
        meta = await self.meta("meeting", m.id)
        if meta.get("submitted"):
            raise rule("The minutes are already submitted", "MINUTES_SUBMITTED")
        if (await self.gov_setting("governance.minutes_approval")) == "none":
            await self.finalise(m, c, via="direct")
            return await self.get(m.id)
        chair_user = await self.staff_user(c.chair_staff_id) if c.chair_staff_id else None
        wf = (
            await self.start_workflow(
                WF_KEY,
                ENTITY,
                m.id,
                f"Minutes · {c.name} {m.meeting_no or ''}",
                {"chair_user_id": str(chair_user) if chair_user else None, "committee_id": str(c.id)},
            )
            if chair_user
            else None
        )
        meta = await self.meta("meeting", m.id)
        meta["submitted"] = True
        meta["workflow_instance_id"] = str(wf) if wf else None
        meta.setdefault("approval", []).append(
            {"action": "submitted", "by": str(self.actor_id) if self.actor_id else None, "at": now_utc().isoformat()}
        )
        await self.put_meta("meeting", m.id, meta)
        await self._notify(
            "governance.minutes_draft",
            [chair_user] if chair_user else await self.role_users("registrar"),
            {"committee": c.name, "meeting_no": m.meeting_no or "", "held_on": m.held_on.strftime("%d-%m-%Y")},
        )
        return await self.get(m.id)

    async def approve_minutes(self, mid: uuid.UUID, body: MinutesApprove) -> MeetingOut:
        self.require_writer()
        m, c = await self.visible_meeting(mid, lock=True)
        if m.status != "minutes_draft":
            raise rule(f"The meeting is {m.status}", "INVALID_TRANSITION")
        meta = await self.meta("meeting", m.id)
        if not meta.get("submitted"):
            raise rule("Submit the minutes first", "NOT_SUBMITTED")
        if await self.acted_on_workflow(meta.get("workflow_instance_id"), body.approve, body.comment):
            return await self.get(m.id)
        if not (self.admin() or c.id in await self.chair_committee_ids() or self.has_any("governance", "approve")):
            raise forbidden("Only the chair (or a governance administrator) approves minutes")
        if body.approve:
            await self.finalise(m, c, via="direct", comment=body.comment)
        else:
            await self.return_minutes(m, body.comment)
        return await self.get(m.id)

    async def return_minutes(self, m: Meeting, comment: str | None) -> None:
        meta = await self.meta("meeting", m.id)
        meta["submitted"] = False
        meta["workflow_instance_id"] = None
        meta.setdefault("approval", []).append(
            {
                "action": "returned",
                "by": str(self.actor_id) if self.actor_id else None,
                "at": now_utc().isoformat(),
                "comment": comment,
            }
        )
        await self.put_meta("meeting", m.id, meta)

    async def finalise(self, m: Meeting, c: Committee, *, via: str, comment: str | None = None) -> None:
        """Number the drafted resolutions under the committee lock, apply links, render the minutes, emit."""
        from app.services.governance.resolution_service import ResolutionService

        await self.committee(c.id, lock=True)
        meta = await self.meta("meeting", m.id)
        drafts = list(meta.get("draft_resolutions") or [])
        rsvc = ResolutionService(self.db, self.principal, self.request, self.inst)
        created = []
        for d in drafts:
            number = await rsvc.next_number(c, m.held_on.year)
            r = Resolution(
                institution_id=self.inst,
                meeting_id=m.id,
                number=number,
                subject=str(d["subject"])[:300],
                text=str(d["text"]),
                action_owner_staff_id=uuid.UUID(d["action_owner_staff_id"]) if d.get("action_owner_staff_id") else None,
                due_on=datetime.fromisoformat(d["due_on"]).date() if d.get("due_on") else None,
                status=d.get("status") or "passed",
                linked_entity=(
                    {**d["linked_entity"], "agenda_item": d.get("agenda_item")} if d.get("linked_entity") else None
                ),
            )
            self.db.add(r)
            await self.db.flush()
            created.append(r)
        m.status = "minutes_approved"
        await self.db.flush()
        for r in created:
            if r.linked_entity and r.status == "passed":
                await rsvc.apply_link(
                    r,
                    LinkedEntity(
                        **{k: v for k, v in r.linked_entity.items() if k in ("entity_type", "entity_id", "label")}
                    ),
                )
            await self._emit(
                "governance.resolution_passed" if r.status == "passed" else f"governance.resolution_{r.status}",
                {"resolution_id": str(r.id), "number": r.number, "committee_type": c.committee_type},
                "resolution",
                r.id,
            )
            if r.action_owner_staff_id and r.status == "passed":
                await self._notify(
                    "governance.resolution_assigned",
                    [await self.staff_user(r.action_owner_staff_id)],
                    {"number": r.number, "subject": r.subject, "due_on": str(r.due_on or "")},
                )
        doc = await self.render_doc("minutes", ENTITY, m.id, allow_multiple=True)
        meta = await self.meta("meeting", m.id)
        meta.update(
            {
                "draft_resolutions": [],
                "minutes_version": int(meta.get("minutes_version") or 1),
                "minutes_document_id": str(doc.issued_document_id)
                if doc is not None
                else meta.get("minutes_document_id"),
                "approved_at": now_utc().isoformat(),
            }
        )
        meta.setdefault("approval", []).append(
            {
                "action": "approved",
                "via": via,
                "by": str(self.actor_id) if self.actor_id else None,
                "at": now_utc().isoformat(),
                "comment": comment,
            }
        )
        await self.put_meta("meeting", m.id, meta)
        await self._audit("minutes_approve", ENTITY, m.id, None, {"resolutions": len(created), "via": via})
        await self._emit(
            "governance.minutes_approved",
            {
                "meeting_id": str(m.id),
                "committee_id": str(c.id),
                "committee_type": c.committee_type,
                "meeting_no": m.meeting_no,
                "resolutions": [str(r.id) for r in created],
            },
            ENTITY,
            m.id,
        )
        users = [x.user_id or await self.staff_user(x.staff_id) for x in await self.committee_members(c)]
        await self._notify(
            "governance.minutes_approved", users, {"committee": c.name, "meeting_no": m.meeting_no or ""}
        )

    async def corrigendum(self, mid: uuid.UUID, body: Corrigendum) -> MeetingOut:
        self.require_writer()
        m, c = await self.visible_meeting(mid, lock=True)
        if m.status != "minutes_approved":
            raise rule("Corrigenda apply to approved minutes", "NOT_APPROVED")
        if not (self.admin() or c.id in await self.chair_committee_ids() or c.id in await self.owned_committee_ids()):
            raise forbidden("Only the secretary / chair or a governance administrator records a corrigendum")
        meta = await self.meta("meeting", m.id)
        version = int(meta.get("minutes_version") or 1)
        meta.setdefault("versions", []).append(
            {"version": version, "minutes_text": m.minutes_text, "replaced_at": now_utc().isoformat()}
        )
        meta["minutes_version"] = version + 1
        meta.setdefault("approval", []).append(
            {
                "action": "corrigendum",
                "version": version + 1,
                "by": str(self.actor_id) if self.actor_id else None,
                "at": now_utc().isoformat(),
                "reason": body.reason,
            }
        )
        m.minutes_text = body.minutes_text
        doc = await self.render_doc("minutes", ENTITY, m.id, allow_multiple=True)
        if doc is not None:
            meta["minutes_document_id"] = str(doc.issued_document_id)
        await self.put_meta("meeting", m.id, meta)
        await self.db.flush()
        await self._emit(
            "governance.minutes_corrigendum", {"meeting_id": str(m.id), "version": version + 1}, ENTITY, m.id
        )
        return await self.get(m.id)

    async def cancel(self, mid: uuid.UUID, body: MeetingCancel) -> MeetingOut:
        m, c = await self._editable(mid)
        m.status = "cancelled"
        await self.timeline("meeting", m.id, "cancelled", reason=body.reason)
        await self.db.flush()
        await self._calendar(c, m)
        await self._emit("governance.meeting_cancelled", {"meeting_id": str(m.id), "reason": body.reason}, ENTITY, m.id)
        return await self.get(m.id)

    async def minutes_lines(self, mid: uuid.UUID) -> tuple[str, list[str]]:
        m, c = await self.visible_meeting(mid)
        if m.status != "minutes_approved" and not (self.admin() or c.id in await self.owned_committee_ids()):
            raise not_found("Approved minutes")
        out = (await self.outs([m], full=True))[0]
        lines = [
            f"{c.name} — meeting {m.meeting_no or ''}",
            f"Held on {m.held_on.strftime('%d-%m-%Y %H:%M')} at {m.venue_or_link or '—'}",
            f"Status: {m.status}  ·  minutes version {out.minutes_version}",
            "",
            "Agenda:",
            *[f"  {i + 1}. {a.get('item')}" for i, a in enumerate(m.agenda or [])],
            "",
            "Minutes:",
            *((m.minutes_text or "").splitlines() or ["—"]),
            "",
            "Resolutions:",
            *[f"  {r.number} [{r.status}] {r.subject}" for r in out.resolutions],
        ]
        return f"minutes-{committee_code(c)}-{(m.meeting_no or '').replace('/', '-')}", lines

    # ---- suggestions ------------------------------------------------------------------------------------------------------
    async def suggestions(self, mid: uuid.UUID) -> list[AgendaSuggestion]:
        m, c = await self.visible_meeting(mid)
        return await self.suggestions_for(c)

    async def suggestions_for(self, c: Committee) -> list[AgendaSuggestion]:
        from sqlalchemy import text

        out: list[AgendaSuggestion] = []
        atr = await self.pending_atr_item(c)
        if atr:
            out.append(
                AgendaSuggestion(source="atr", item=atr["item"], linked_entity=LinkedEntity(**atr["linked_entity"]))
            )
        t = c.committee_type
        if t in ("bos", "academic_council", "academic_committee"):
            where = "institution_id = :i AND status = 'draft'"
            params: dict[str, Any] = {"i": self.inst}
            for rid, code, name in (
                await self.db.execute(
                    text(f"SELECT id, code, name FROM regulations WHERE {where} ORDER BY created_at DESC LIMIT 20"),  # noqa: S608
                    params,
                )
            ).all():
                out.append(
                    AgendaSuggestion(
                        source="regulation",
                        item=f"Approval of regulation {code} — {name}",
                        linked_entity=LinkedEntity(entity_type="regulation", entity_id=rid, label=str(code)),
                    )
                )
        if t in ("academic_council", "executive_council", "senate", "governing_body", "academic_committee"):
            for rid, status in (
                await self.db.execute(
                    text(
                        "SELECT id, status FROM result_processing_runs WHERE institution_id = :i AND status = 'verified' "
                        "AND approval_resolution_id IS NULL ORDER BY created_at DESC LIMIT 20"
                    ),
                    {"i": self.inst},
                )
            ).all():
                out.append(
                    AgendaSuggestion(
                        source="result_run",
                        item="Approval of results (verified run)",
                        linked_entity=LinkedEntity(entity_type="result_run", entity_id=rid),
                        detail=status,
                    )
                )
            n = (
                await self.db.execute(
                    text("SELECT COUNT(*) FROM degrees_awarded WHERE institution_id = :i AND status = 'recommended'"),
                    {"i": self.inst},
                )
            ).scalar_one()
            if n:
                out.append(AgendaSuggestion(source="degrees", item=f"Award of degrees ({int(n)} recommended)"))
            for bid, number, subject in (
                await self.db.execute(
                    select(Resolution.id, Resolution.number, Resolution.subject)
                    .join(Meeting, Meeting.id == Resolution.meeting_id)
                    .join(Committee, Committee.id == Meeting.committee_id)
                    .where(
                        Committee.institution_id == self.inst,
                        Committee.committee_type == "bos",
                        Resolution.status == "passed",
                        Resolution.created_at >= now_utc() - timedelta(days=120),
                    )
                    .limit(20)
                )
            ).all():
                out.append(
                    AgendaSuggestion(
                        source="bos_resolution",
                        item=f"Ratification of BoS resolution {number}: {subject}"[:500],
                        linked_entity=LinkedEntity(entity_type="resolution", entity_id=bid, label=number),
                    )
                )
            from app.services.governance.policy_service import PolicyService

            for p in await PolicyService(self.db, self.principal, self.request, self.inst).submitted():
                out.append(
                    AgendaSuggestion(
                        source="policy",
                        item=f"Approval of policy {p.title} v{p.version}",
                        linked_entity=LinkedEntity(entity_type="policy", entity_id=p.id, label=p.title),
                    )
                )
        if t == "finance":
            from app.services.governance.audit_para_service import AuditParaService

            for para in await AuditParaService(self.db, self.principal, self.request, self.inst).open_paras(limit=20):
                out.append(
                    AgendaSuggestion(
                        source="audit_para",
                        item=f"Audit para {para.para_no} ({para.audit_type} {para.period_label}) — compliance",
                        linked_entity=LinkedEntity(entity_type="audit_para", entity_id=para.id, label=para.para_no),
                    )
                )
        if t == "iqac":
            out += await self.iqac_suggestions()
        inbox = await self.meta("suggestions", t)
        for s in list(inbox.get("items") or [])[-20:]:
            le = s.get("linked_entity")
            out.append(
                AgendaSuggestion(
                    source=str(s.get("source") or "event"),
                    item=str(s.get("item")),
                    linked_entity=LinkedEntity(**le) if le and le.get("entity_id") else None,
                    detail=s.get("detail"),
                )
            )
        return out

    async def iqac_suggestions(self) -> list[AgendaSuggestion]:
        """Phase 32 IQAC dashboard top gaps → IQAC meeting agenda items."""
        out: list[AgendaSuggestion] = []
        if not await self.feature("accreditation.aishe"):
            return out
        try:
            from app.services.accreditation.dashboard_service import DashboardService

            async with self.db.begin_nested():
                dash = await DashboardService(self.db, None, institution_id=self.inst).dashboard()
        except Exception:  # noqa: BLE001 - the dashboard needs the Phase 32 catalogue; suggestions are optional
            return out
        for g in (getattr(dash, "top_gaps", None) or [])[:10]:
            out.append(
                AgendaSuggestion(
                    source="iqac_gap",
                    item=f"Improvement plan for NAAC {g.get('code')} {g.get('title')} (gap {g.get('gap')})"[:500],
                    detail=g.get("metric_key"),
                )
            )
        if getattr(dash, "consistency_alerts", 0):
            out.append(
                AgendaSuggestion(
                    source="consistency_alert",
                    item=f"Review of {dash.consistency_alerts} data consistency alert(s)",
                )
            )
        return out

    async def add_suggestion(self, committee_type: str, item: dict[str, Any]) -> None:
        inbox = await self.meta("suggestions", committee_type)
        items = [
            x
            for x in list(inbox.get("items") or [])
            if not (
                item.get("linked_entity")
                and x.get("linked_entity")
                and x["linked_entity"].get("entity_id") == item["linked_entity"].get("entity_id")
            )
        ]
        items.append({**item, "at": now_utc().isoformat()})
        inbox["items"] = items[-50:]
        await self.put_meta("suggestions", committee_type, inbox)

    # ---- Beat ---------------------------------------------------------------------------------------------------------
    async def reminders(self) -> int:
        """Daily: members of meetings held tomorrow are reminded."""
        start = now_utc() + timedelta(hours=12)
        rows = (
            await self.db.execute(
                select(Meeting).where(
                    Meeting.institution_id == self.inst,
                    Meeting.status == "scheduled",
                    Meeting.held_on >= start,
                    Meeting.held_on < start + timedelta(days=1),
                )
            )
        ).scalars()
        n = 0
        for m in rows:
            c = await self.committee(m.committee_id)
            users = [x.user_id or await self.staff_user(x.staff_id) for x in await self.committee_members(c)]
            await self._notify(
                "governance.meeting_reminder",
                users,
                {"committee": c.name, "held_on": m.held_on.strftime("%d-%m-%Y %H:%M"), "venue": m.venue_or_link or ""},
            )
            n += 1
        return n

    async def my_meetings(self) -> list[MeetingOut]:
        ids = list(set(await self.my_committee_ids()) | await self.owned_committee_ids())
        if not ids:
            return []
        rows = (
            await self.db.execute(
                select(Meeting)
                .where(
                    Meeting.committee_id.in_(ids),
                    or_(Meeting.held_on >= now_utc() - timedelta(days=90), Meeting.status.in_(OPEN)),
                )
                .order_by(Meeting.held_on.desc())
                .limit(50)
            )
        ).scalars()
        return await self.outs(list(rows))

    async def pending_atrs(self) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count()).where(
                        ActionTakenReport.institution_id == self.inst, ActionTakenReport.status == "submitted"
                    )
                )
            ).scalar_one()
        )


# ---- workflow hooks ------------------------------------------------------------------------------------------------------
class _Actor:
    def __init__(self, institution_id: uuid.UUID, user_id: uuid.UUID | None):
        self.institution_id, self.id = institution_id, user_id
        self.is_super_admin, self.impersonator_id = False, None
        self.scopes: list[tuple[str, uuid.UUID | None]] = [("institution", None)]
        self.roles: list[str] = []

    def has(self, module: str, action: str) -> bool:
        return True


@workflow_engine.on(WF_KEY, "approved")
async def _minutes_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = MeetingService(db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id)
    m = await svc.meeting(instance.entity_id, lock=True)
    if m.status == "minutes_draft":
        await svc.finalise(m, await svc.committee(m.committee_id), via="workflow")


@workflow_engine.on(WF_KEY, "rejected")
async def _minutes_returned(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = MeetingService(db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id)
    m = await svc.meeting(instance.entity_id, lock=True)
    if m.status == "minutes_draft":
        await svc.return_minutes(m, "returned by the chair")


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(Meeting, Committee)
            .join(Committee, Committee.id == Meeting.committee_id)
            .where(Meeting.id == entity_id)
        )
    ).first()
    if row is None:
        return None, None
    m, c = row
    return f"Minutes of {c.name} {m.meeting_no or ''} ({m.held_on:%d-%m-%Y})", "secretary → chair"


# ---- Phase 26 resolvers ------------------------------------------------------------------------------------------------
@register_resolver(ENTITY)
async def _meeting_ctx(svc: Any, mid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    m = (await svc.db.execute(select(Meeting).where(Meeting.id == mid))).scalar_one()
    c = (await svc.db.execute(select(Committee).where(Committee.id == m.committee_id))).scalar_one()
    res = (
        await svc.db.execute(select(Resolution).where(Resolution.meeting_id == m.id).order_by(Resolution.number))
    ).scalars()
    att = m.attendance or {}
    return (
        {
            "committee": {"name": c.name, "type": c.committee_type, "code": committee_code(c)},
            "meeting": {
                "number": m.meeting_no or "",
                "held_on": m.held_on.strftime("%d-%m-%Y %H:%M"),
                "venue": m.venue_or_link or "",
                "agenda": "<br>".join(f"{i + 1}. {a.get('item')}" for i, a in enumerate(m.agenda or [])),
                "minutes": (m.minutes_text or "").replace("\n", "<br>"),
                "present": len(att.get("present_member_ids") or []),
                "quorum": "met" if m.quorum_met else "not met",
                "resolutions": "<br>".join(f"{r.number}: {r.subject} ({r.status})" for r in res),
                "short_notice": False,
            },
            "title": f"{c.name} — {m.meeting_no or ''}",
            "body": "",
        },
        None,
        None,
    )
