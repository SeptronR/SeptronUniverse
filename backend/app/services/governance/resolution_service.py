"""Resolutions and action-taken reports — Prompts/33 §33.6 ``meeting_service`` 3–4 ({governance.minutes}).

Numbering ``<CODE>/<yyyy>/<n>`` (e.g. ``AC/2026/14``) per committee code and year, taken under the committee row lock
(``FOR UPDATE`` by ``MeetingService.finalise``) as max + 1 of the numbers already issued — ``UNIQUE (institution_id,
number)`` is the backstop. **Linkage API** (``link`` / ``apply_link`` / ``lookup``) used by Phase 05 (regulations),
Phase 15 (result approvals), Phase 18 (degree awards), Phase 33 policies, Phase 22 purchase decisions and Phase 27
discipline: ``regulation`` / ``result_run`` / ``degree_award`` / ``policy`` write the entity's
``approval_resolution_id`` / ``approved_resolution_id``; other types are recorded in ``linked_entity`` only.
Certified extracts through the Phase 26 ``resolution_extract`` template. ATR cycle: the action owner submits (one open
report at a time), the secretary accepts (→ resolution ``implemented``) or returns (resubmission); weekly reminders for
overdue reports; the next meeting's agenda gets "ATR on previous minutes".
"""

import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, text

from app.models.governance import ActionTakenReport, Committee, Meeting, Resolution
from app.schemas.governance import (
    AtrDecision,
    AtrOut,
    AtrSubmit,
    DocumentRef,
    LinkedEntity,
    ResolutionLink,
    ResolutionOut,
    ResolutionStatusChange,
)
from app.services.documents.render_service import register_resolver
from app.services.governance.common import GovernanceBase, committee_code, forbidden, not_found, now_utc, rule

ENTITY = "resolution"
# entity_type → (table, column) written by the linkage API
LINK_TARGETS: dict[str, tuple[str, str]] = {
    "regulation": ("regulations", "approval_resolution_id"),
    "result_run": ("result_processing_runs", "approval_resolution_id"),
    "degree_award": ("degrees_awarded", "approval_resolution_id"),
    "policy": ("policies", "approved_resolution_id"),
}


class ResolutionService(GovernanceBase):
    async def next_number(self, c: Committee, year: int) -> str:
        code = committee_code(c)
        prefix = f"{code}/{year}/"
        rows = (
            await self.db.execute(
                select(Resolution.number).where(
                    Resolution.institution_id == self.inst, Resolution.number.like(f"{prefix}%")
                )
            )
        ).scalars()
        nums = [int(m.group(1)) for n in rows if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", n))]
        return f"{prefix}{max(nums, default=0) + 1}"[:40]

    async def row(self, rid: uuid.UUID, *, lock: bool = False) -> tuple[Resolution, Meeting, Committee]:
        stmt = select(Resolution).where(Resolution.id == rid, Resolution.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Resolution")
        m = (await self.db.execute(select(Meeting).where(Meeting.id == r.meeting_id))).scalar_one()
        c = await self.committee(m.committee_id)
        return r, m, c

    async def visible(self, rid: uuid.UUID, *, lock: bool = False) -> tuple[Resolution, Meeting, Committee]:
        r, m, c = await self.row(rid, lock=lock)
        sid = await self.my_staff_id()
        if sid is not None and r.action_owner_staff_id == sid:
            return r, m, c
        await self.committee_visible(c)
        return r, m, c

    async def outs(self, rows: list[Resolution]) -> list[ResolutionOut]:
        if not rows:
            return []
        mids = list({r.meeting_id for r in rows})
        meetings = {m.id: m for m in (await self.db.execute(select(Meeting).where(Meeting.id.in_(mids)))).scalars()}
        cmap = {
            c.id: c
            for c in (
                await self.db.execute(
                    select(Committee).where(Committee.id.in_({m.committee_id for m in meetings.values()}))
                )
            ).scalars()
        }
        atrs: dict[uuid.UUID, ActionTakenReport] = {}
        for a in (
            await self.db.execute(
                select(ActionTakenReport)
                .where(ActionTakenReport.resolution_id.in_([r.id for r in rows]))
                .order_by(ActionTakenReport.submitted_at)
            )
        ).scalars():
            atrs[a.resolution_id] = a
        names = await self.staff_names([r.action_owner_staff_id for r in rows])
        submitters = await self.user_display([a.submitted_by for a in atrs.values()])
        ameta = await self.metas("atr", [str(a.id) for a in atrs.values()])
        today = await self.today()
        out = []
        for r in rows:
            m = meetings[r.meeting_id]
            c = cmap[m.committee_id]
            atr = atrs.get(r.id)
            out.append(
                ResolutionOut(
                    id=r.id,
                    meeting_id=r.meeting_id,
                    committee_id=c.id,
                    committee_name=c.name,
                    number=r.number,
                    subject=r.subject,
                    text=r.text,
                    status=r.status,
                    action_owner_staff_id=r.action_owner_staff_id,
                    owner_name=names.get(r.action_owner_staff_id) if r.action_owner_staff_id else None,
                    due_on=r.due_on,
                    overdue=bool(r.due_on and r.due_on < today and r.status == "passed"),
                    linked_entity=r.linked_entity,
                    created_at=r.created_at,
                    atr=AtrOut(
                        id=atr.id,
                        resolution_id=atr.resolution_id,
                        report_text=atr.report_text,
                        attachments=list(atr.attachments or []),
                        submitted_by=atr.submitted_by,
                        submitted_by_name=submitters.get(atr.submitted_by) if atr.submitted_by else None,
                        submitted_at=atr.submitted_at,
                        status=atr.status,
                        decision_remarks=ameta.get(str(atr.id), {}).get("remarks"),
                    )
                    if atr
                    else None,
                )
            )
        return out

    async def for_meeting(self, mid: uuid.UUID) -> list[ResolutionOut]:
        rows = (
            await self.db.execute(
                select(Resolution).where(Resolution.meeting_id == mid).order_by(Resolution.created_at)
            )
        ).scalars()
        return await self.outs(list(rows))

    async def list_resolutions(
        self,
        *,
        committee_id: uuid.UUID | None = None,
        status: str | None = None,
        owner_id: uuid.UUID | None = None,
        year: int | None = None,
        scope: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ResolutionOut], int]:
        stmt = (
            select(Resolution)
            .join(Meeting, Meeting.id == Resolution.meeting_id)
            .where(Resolution.institution_id == self.inst)
        )
        sid = await self.my_staff_id()
        if scope == "mine":
            stmt = stmt.where(Resolution.action_owner_staff_id == (sid or uuid.uuid4()))
        elif scope == "committee":
            stmt = stmt.where(Meeting.committee_id.in_(list(await self.owned_committee_ids()) or [uuid.uuid4()]))
        elif not self.reader_all():
            conds: list[Any] = [Meeting.committee_id.in_((await self.visible_committee_ids()) or [uuid.uuid4()])]
            if sid is not None:
                conds.append(Resolution.action_owner_staff_id == sid)
            stmt = stmt.where(or_(*conds))
        if committee_id:
            stmt = stmt.where(Meeting.committee_id == committee_id)
        if status:
            stmt = stmt.where(Resolution.status == status)
        if owner_id:
            stmt = stmt.where(Resolution.action_owner_staff_id == owner_id)
        if year:
            stmt = stmt.where(func.extract("year", Meeting.held_on) == year)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (
            await self.db.execute(stmt.order_by(Resolution.created_at.desc()).limit(limit).offset(offset))
        ).scalars()
        return await self.outs(list(rows)), int(total)

    async def get(self, rid: uuid.UUID) -> ResolutionOut:
        r, _, _ = await self.visible(rid)
        return (await self.outs([r]))[0]

    # ---- linkage ------------------------------------------------------------------------------------------------------
    async def apply_link(self, r: Resolution, link: LinkedEntity | ResolutionLink) -> None:
        target = LINK_TARGETS.get(link.entity_type)
        if target is not None:
            table, column = target
            res = await self.db.execute(
                text(f"UPDATE {table} SET {column} = :r WHERE id = :e AND institution_id = :i"),  # noqa: S608 - literals
                {"r": r.id, "e": link.entity_id, "i": self.inst},
            )
            if not res.rowcount:  # type: ignore[attr-defined]
                raise rule(f"{link.entity_type} {link.entity_id} not found", "LINK_TARGET_MISSING", 422)
        r.linked_entity = {
            "entity_type": link.entity_type,
            "entity_id": str(link.entity_id),
            "label": link.label,
        }
        await self.db.flush()
        await self.timeline("resolution", r.id, "linked", entity_type=link.entity_type, entity_id=str(link.entity_id))
        await self._emit(
            "governance.resolution_linked",
            {"resolution_id": str(r.id), "entity_type": link.entity_type, "entity_id": str(link.entity_id)},
            ENTITY,
            r.id,
        )

    async def link(self, rid: uuid.UUID, body: ResolutionLink) -> ResolutionOut:
        r, m, c = await self.visible(rid, lock=True)
        await self.require_committee_manager(c)
        if r.status not in ("passed", "implemented"):
            raise rule("Only passed resolutions can be linked", "NOT_PASSED")
        await self.apply_link(r, body)
        return (await self.outs([r]))[0]

    async def lookup(self, entity_type: str, entity_id: uuid.UUID) -> list[ResolutionOut]:
        rows = list(
            (
                await self.db.execute(
                    select(Resolution).where(
                        Resolution.institution_id == self.inst,
                        Resolution.linked_entity["entity_type"].astext == entity_type,
                        Resolution.linked_entity["entity_id"].astext == str(entity_id),
                    )
                )
            ).scalars()
        )
        target = LINK_TARGETS.get(entity_type)
        if target is not None:
            table, column = target
            rid = (
                await self.db.execute(
                    text(f"SELECT {column} FROM {table} WHERE id = :e AND institution_id = :i"),  # noqa: S608
                    {"e": entity_id, "i": self.inst},
                )
            ).scalar_one_or_none()
            if rid and rid not in {r.id for r in rows}:
                extra = (await self.db.execute(select(Resolution).where(Resolution.id == rid))).scalar_one_or_none()
                if extra is not None:
                    rows.append(extra)
        return await self.outs(rows)

    async def set_status(self, rid: uuid.UUID, body: ResolutionStatusChange) -> ResolutionOut:
        r, m, c = await self.visible(rid, lock=True)
        await self.require_committee_manager(c)
        if r.status == "implemented" and body.status != "implemented":
            raise rule("Implemented resolutions are closed", "INVALID_TRANSITION")
        old = r.status
        r.status = body.status
        await self.db.flush()
        await self.timeline("resolution", r.id, f"status:{body.status}", remarks=body.remarks)
        await self._audit("status", ENTITY, r.id, {"status": old}, {"status": r.status})
        if r.status == "implemented":
            await self._emit("governance.resolution_implemented", {"resolution_id": str(r.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def extract(self, rid: uuid.UUID) -> DocumentRef:
        r, m, c = await self.visible(rid)
        if m.status != "minutes_approved":
            raise rule("Extracts are issued from approved minutes", "NOT_APPROVED")
        doc = await self.render_doc("resolution_extract", ENTITY, r.id, allow_multiple=True)
        if doc is None:
            return DocumentRef()
        return DocumentRef(issued_document_id=doc.issued_document_id, url=getattr(doc, "pdf_url", None))

    # ---- ATR ----------------------------------------------------------------------------------------------------------
    async def submit_atr(self, rid: uuid.UUID, body: AtrSubmit) -> ResolutionOut:
        self.require_writer()
        r, m, c = await self.row(rid, lock=True)
        sid = await self.my_staff_id()
        if not (sid is not None and r.action_owner_staff_id == sid) and not await self.can_manage_committee(c):
            raise forbidden("Only the action owner submits the action-taken report")
        if r.status != "passed":
            raise rule(f"The resolution is {r.status}", "INVALID_TRANSITION")
        open_ = (
            await self.db.execute(
                select(ActionTakenReport.id).where(
                    ActionTakenReport.resolution_id == r.id, ActionTakenReport.status == "submitted"
                )
            )
        ).first()
        if open_ is not None:
            raise rule("An action-taken report is awaiting a decision", "ATR_PENDING")
        a = ActionTakenReport(
            institution_id=self.inst,
            resolution_id=r.id,
            report_text=body.report_text,
            attachments=list(body.attachments),
            submitted_by=self.actor_id,
            status="submitted",
        )
        self.db.add(a)
        await self.db.flush()
        await self._emit("governance.atr_submitted", {"resolution_id": str(r.id), "atr_id": str(a.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]

    async def decide_atr(self, atr_id: uuid.UUID, body: AtrDecision) -> ResolutionOut:
        self.require_writer()
        a = (
            await self.db.execute(
                select(ActionTakenReport)
                .where(ActionTakenReport.id == atr_id, ActionTakenReport.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Action-taken report")
        r, m, c = await self.row(a.resolution_id, lock=True)
        await self.require_committee_manager(c)
        if a.status != "submitted":
            raise rule(f"The report is {a.status}", "INVALID_TRANSITION")
        a.status = body.decision
        await self.put_meta(
            "atr", a.id, {"remarks": body.remarks, "by": str(self.actor_id), "at": now_utc().isoformat()}
        )
        if body.decision == "accepted":
            r.status = "implemented"
            await self._emit("governance.resolution_implemented", {"resolution_id": str(r.id)}, ENTITY, r.id)
        await self.db.flush()
        await self._emit(
            f"governance.atr_{body.decision}", {"resolution_id": str(r.id), "atr_id": str(a.id)}, ENTITY, r.id
        )
        return (await self.outs([r]))[0]

    async def atr_due_reminders(self) -> int:
        """Weekly: passed resolutions with an owner, due within 7 days or overdue, without an accepted ATR."""
        today = await self.today()
        rows = (
            await self.db.execute(
                select(Resolution).where(
                    Resolution.institution_id == self.inst,
                    Resolution.status == "passed",
                    Resolution.action_owner_staff_id.is_not(None),
                    Resolution.due_on.is_not(None),
                    Resolution.due_on <= today + timedelta(days=7),
                )
            )
        ).scalars()
        n = 0
        for r in rows:
            await self._notify(
                "governance.atr_due",
                [await self.staff_user(r.action_owner_staff_id)],
                {"number": r.number, "subject": r.subject, "due_on": str(r.due_on)},
            )
            n += 1
        return n


@register_resolver(ENTITY)
async def _resolution_ctx(svc: Any, rid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    r = (await svc.db.execute(select(Resolution).where(Resolution.id == rid))).scalar_one()
    m = (await svc.db.execute(select(Meeting).where(Meeting.id == r.meeting_id))).scalar_one()
    c = (await svc.db.execute(select(Committee).where(Committee.id == m.committee_id))).scalar_one()
    return (
        {
            "committee": {"name": c.name, "code": committee_code(c)},
            "meeting": {"number": m.meeting_no or "", "held_on": m.held_on.strftime("%d-%m-%Y")},
            "resolution": {
                "number": r.number,
                "subject": r.subject,
                "text": r.text.replace("\n", "<br>"),
                "status": r.status,
            },
            "title": f"Extract of resolution {r.number}",
            "body": "",
        },
        None,
        None,
    )
