"""Ethics committees — Prompts/30 §30.6 ``ethics_service`` ({research.ethics_committee}).

Committees (IEC / IAEC / IBSC) with registration numbers and members, bound to a Phase 33 ``committees`` row (the
Phase 27 stub until Phase 33 replaces it). An application is an ``ethics_approvals`` row with ``decision`` NULL while
under review (category exempt / expedited / full review, protocol document, linked project); it starts
``research.ethics_review`` with the assigned reviewer (a member) and the chair in the context — the member's review
(inbox or ``/review``) and the chair's decision (``/decide``: approved with ``approval_no`` and validity, revise,
rejected; conditions) follow. Amendments, renewals (new validity) and adverse events are appended to the side store.
Committee members own the applications of their committees; another committee's application answers 404. Approvals
link to projects (Phase 30) and PhD work (Phase 31 — ``scholar_id`` in the side store, also set from the scholar
record); ``project_service`` refuses to start a project of a listed ethics
category without a valid approval.
"""

import contextlib
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import false, func, or_, select, true

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.enums.research import EthicsDecision
from app.models.platform import WorkflowInstance
from app.models.research import EthicsApproval, EthicsCommittee, ResearchProject
from app.schemas.research import (
    EthicsAmend,
    EthicsApplication,
    EthicsApplicationOut,
    EthicsCommitteeIn,
    EthicsCommitteeOut,
    EthicsReview,
)
from app.services.research.common import ResearchBase, forbidden, not_found, now_utc, rule, staff_name

WF_KEY = "research.ethics_review"


class EthicsService(ResearchBase):
    def secretariat(self) -> bool:
        return self.cell("ethics")

    async def my_ethics_committee_ids(self) -> list[uuid.UUID]:
        """Ethics committees the caller sits on (bound committee membership or the ``members`` list)."""
        out: set[uuid.UUID] = set()
        bound = await self.my_committee_ids()
        mine = await self.my_staff_id()
        rows = (
            await self.db.execute(select(EthicsCommittee).where(EthicsCommittee.institution_id == self.inst))
        ).scalars()
        for c in rows:
            if (
                c.committee_id
                and c.committee_id in bound
                or any(
                    (mine and str(m.get("staff_id")) == str(mine)) or str(m.get("user_id")) == str(self.actor_id)
                    for m in c.members or []
                )
            ):
                out.add(c.id)
        return list(out)

    async def _member_role(self, c: EthicsCommittee) -> str | None:
        mine = await self.my_staff_id()
        for m in c.members or []:
            if (mine and str(m.get("staff_id")) == str(mine)) or str(m.get("user_id")) == str(self.actor_id):
                return str(m.get("role") or "member")
        if c.committee_id and c.committee_id in await self.my_committee_ids():
            return "member"
        return None

    async def _user_of(self, member: dict[str, Any]) -> uuid.UUID | None:
        if member.get("user_id"):
            return uuid.UUID(str(member["user_id"]))
        if member.get("staff_id"):
            return await self.staff_user(uuid.UUID(str(member["staff_id"])))
        return None

    # ---- committees -------------------------------------------------------------------------------------------------
    async def committee_outs(self, rows: list[EthicsCommittee]) -> list[EthicsCommitteeOut]:
        counts: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(EthicsApproval.ethics_committee_id, func.count())
                    .where(EthicsApproval.institution_id == self.inst)
                    .group_by(EthicsApproval.ethics_committee_id)
                )
            )
            .tuples()
            .all()
        )
        return [
            EthicsCommitteeOut(
                id=c.id,
                committee_type=c.committee_type,
                committee_id=c.committee_id,
                registration_no=c.registration_no,
                members=list(c.members or []),
                is_active=c.is_active,
                applications=int(counts.get(c.id, 0)),
            )
            for c in rows
        ]

    async def committees(self) -> list[EthicsCommitteeOut]:
        rows = list(
            (
                await self.db.execute(
                    select(EthicsCommittee)
                    .where(EthicsCommittee.institution_id == self.inst)
                    .order_by(EthicsCommittee.committee_type, EthicsCommittee.created_at)
                )
            ).scalars()
        )
        return await self.committee_outs(rows)

    async def create_committee(self, body: EthicsCommitteeIn) -> EthicsCommitteeOut:
        self.require_cell("ethics")
        bound = body.committee_id
        if bound is None:
            from app.models.post_result import Committee

            stub = Committee(
                institution_id=self.inst,
                name=(body.name or f"{body.committee_type.value.upper()} — ethics committee")[:160],
                committee_type=f"ethics_{body.committee_type.value}",
                constituted_on=await self.today(),
                is_active=True,
            )
            chair = next((m for m in body.members if m.role == "chair"), None)
            if chair and chair.staff_id:
                stub.chair_staff_id = chair.staff_id
            self.db.add(stub)
            await self.db.flush()
            bound = stub.id
        c = EthicsCommittee(
            institution_id=self.inst,
            committee_type=body.committee_type.value,
            committee_id=bound,
            members=[m.model_dump(mode="json") for m in body.members],
            registration_no=body.registration_no,
            is_active=body.is_active,
        )
        self.db.add(c)
        await self.db.flush()
        await self._audit("create", "ethics_committee", c.id, None, body.model_dump(mode="json"))
        return (await self.committee_outs([c]))[0]

    async def committee(self, cid: uuid.UUID) -> EthicsCommittee:
        c = (
            await self.db.execute(
                select(EthicsCommittee).where(EthicsCommittee.id == cid, EthicsCommittee.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if c is None:
            raise not_found("Ethics committee")
        return c

    # ---- applications ---------------------------------------------------------------------------------------------------
    async def predicate(self) -> Any:
        p = self.principal
        if p is None or getattr(p, "is_super_admin", False) or self.reader_all():
            return true()
        parts: list[Any] = []
        mine = await self.my_staff_id()
        if mine is not None:
            parts.append(EthicsApproval.pi_staff_id == mine)
        comms = await self.my_ethics_committee_ids()
        if comms:
            parts.append(EthicsApproval.ethics_committee_id.in_(comms))
        sub = self.staff_scope_subquery()
        if sub is not None:
            parts.append(EthicsApproval.pi_staff_id.in_(sub))
        return or_(*parts) if parts else false()

    async def row(self, aid: uuid.UUID, *, lock: bool = False) -> EthicsApproval:
        stmt = select(EthicsApproval).where(
            EthicsApproval.id == aid, EthicsApproval.institution_id == self.inst, await self.predicate()
        )
        a = (await self.db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
        if a is None:
            raise not_found("Ethics application")
        return a

    async def outs(self, rows: list[EthicsApproval]) -> list[EthicsApplicationOut]:
        staff = await self.staff_map([r.pi_staff_id for r in rows])
        metas = await self.metas("ethics", [r.id for r in rows]) if rows else {}
        cids = list({r.ethics_committee_id for r in rows})
        types: dict[Any, Any] = (
            dict(
                (
                    await self.db.execute(
                        select(EthicsCommittee.id, EthicsCommittee.committee_type).where(EthicsCommittee.id.in_(cids))
                    )
                )
                .tuples()
                .all()
            )
            if cids
            else {}
        )
        today = await self.today()
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            status = r.decision or ("reviewed" if m.get("reviews") else "under_review")
            out.append(
                EthicsApplicationOut(
                    id=r.id,
                    ethics_committee_id=r.ethics_committee_id,
                    committee_type=types.get(r.ethics_committee_id),
                    project_title=r.project_title,
                    pi_staff_id=r.pi_staff_id,
                    pi_name=staff_name(staff.get(r.pi_staff_id)) if r.pi_staff_id else None,
                    submitted_on=r.submitted_on,
                    category=m.get("category"),
                    scholar_id=uuid.UUID(m["scholar_id"]) if m.get("scholar_id") else None,
                    decision=r.decision,
                    status=status,
                    approval_no=r.approval_no,
                    valid_to=r.valid_to,
                    is_valid=r.decision == "approved" and (r.valid_to is None or r.valid_to >= today),
                    document_url=r.document_url,
                    conditions=m.get("conditions"),
                    reviews=list(m.get("reviews") or []),
                    history=list(m.get("history") or []),
                    workflow_instance_id=uuid.UUID(m["workflow_instance_id"])
                    if m.get("workflow_instance_id")
                    else None,
                )
            )
        return out

    async def applications(
        self, *, committee_id: uuid.UUID | None = None, status: str | None = None
    ) -> list[EthicsApplicationOut]:
        stmt = select(EthicsApproval).where(EthicsApproval.institution_id == self.inst, await self.predicate())
        if committee_id:
            stmt = stmt.where(EthicsApproval.ethics_committee_id == committee_id)
        if status == "pending":
            stmt = stmt.where(EthicsApproval.decision.is_(None))
        elif status:
            stmt = stmt.where(EthicsApproval.decision == status)
        rows = list((await self.db.execute(stmt.order_by(EthicsApproval.created_at.desc()))).scalars())
        return await self.outs(rows)

    async def get(self, aid: uuid.UUID) -> EthicsApplicationOut:
        return (await self.outs([await self.row(aid)]))[0]

    async def apply(self, body: EthicsApplication) -> EthicsApplicationOut:
        self.require_writer()
        c = await self.committee(body.committee_id)
        if not c.is_active:
            raise rule("The committee is not active", "COMMITTEE_INACTIVE")
        pi = (
            (await self.staff_row(body.pi_staff_id)).id
            if body.pi_staff_id and self.secretariat()
            else (await self.require_my_staff()).id
        )
        a = EthicsApproval(
            institution_id=self.inst,
            ethics_committee_id=c.id,
            project_title=body.project_title,
            pi_staff_id=pi,
            submitted_on=await self.today(),
            document_url=body.protocol_url,
        )
        self.db.add(a)
        await self.db.flush()
        members = list(c.members or [])
        chair = next((m for m in members if m.get("role") == "chair"), None)
        reviewer = next(
            (m for m in members if body.reviewer_staff_id and str(m.get("staff_id")) == str(body.reviewer_staff_id)),
            None,
        ) or next((m for m in members if m.get("role") != "chair"), chair)
        m: dict[str, Any] = {
            "category": body.category.value,
            "project_id": str(body.project_id) if body.project_id else None,
            "scholar_id": str(body.scholar_id) if body.scholar_id else None,
        }
        if body.category.value != "exempt" and reviewer and chair:
            try:
                wf = await workflow_engine.start(
                    self.db,
                    institution_id=self.inst,
                    key=WF_KEY,
                    entity_type="ethics_approval",
                    entity_id=a.id,
                    started_by=self.actor_id,
                    context={
                        "reviewer_user_id": str(await self._user_of(reviewer) or ""),
                        "chair_user_id": str(await self._user_of(chair) or ""),
                        "category": body.category.value,
                    },
                    title=f"Ethics review · {body.project_title[:80]}",
                )
                m["workflow_instance_id"] = str(wf.id)
            except APIError:
                m["workflow_error"] = "reviewer / chair without a user account — decide through the secretariat"
        await self.put_meta("ethics", a.id, m)
        if body.project_id:
            p = (
                await self.db.execute(
                    select(ResearchProject).where(
                        ResearchProject.id == body.project_id, ResearchProject.pi_staff_id == pi
                    )
                )
            ).scalar_one_or_none()
            if p is not None and p.ethics_approval_id is None:
                p.ethics_approval_id = a.id
        await self.db.flush()
        await self._emit(
            "research.ethics_applied",
            {"approval_id": str(a.id), "committee_id": str(c.id), "category": body.category.value},
            "ethics_approval",
            a.id,
        )
        return (await self.outs([a]))[0]

    async def _wf(self, m: dict[str, Any]) -> WorkflowInstance | None:
        if not m.get("workflow_instance_id"):
            return None
        return (
            await self.db.execute(
                select(WorkflowInstance).where(WorkflowInstance.id == uuid.UUID(m["workflow_instance_id"]))
            )
        ).scalar_one_or_none()

    async def review(self, aid: uuid.UUID, body: EthicsReview) -> EthicsApplicationOut:
        """A member's review (workflow step 1); the chair decides."""
        self.require_writer()
        a = await self.row(aid, lock=True)
        if a.decision:
            raise rule("The application is already decided", "ALREADY_DECIDED")
        c = await self.committee(a.ethics_committee_id)
        role = await self._member_role(c)
        if role is None and not self.secretariat():
            raise not_found("Ethics application")
        m = await self.meta("ethics", a.id)
        reviews = list(m.get("reviews") or [])
        reviews.append(
            {
                "by": str(self.actor_id),
                "role": role or "secretariat",
                "recommendation": body.decision.value,
                "comments": body.comments or body.conditions,
                "at": now_utc().isoformat(),
            }
        )
        m["reviews"] = reviews
        await self.put_meta("ethics", a.id, m)
        wf = await self._wf(m)
        if wf is not None and wf.status in ("pending", "escalated") and wf.current_step == 1:
            with contextlib.suppress(APIError):
                await workflow_engine.act(
                    self.db, instance_id=wf.id, actor=self.principal, decision="approve", comment=body.comments
                )
        await self.db.flush()
        return (await self.outs([a]))[0]

    async def decide(self, aid: uuid.UUID, body: EthicsReview, *, via_workflow: bool = False) -> EthicsApplicationOut:
        if not via_workflow:
            self.require_writer()
        a = (
            await self.row(aid, lock=True)
            if not via_workflow
            else (
                await self.db.execute(select(EthicsApproval).where(EthicsApproval.id == aid).with_for_update())
            ).scalar_one()
        )
        if a.decision == "approved":
            raise rule("The application is already approved", "ALREADY_DECIDED")
        c = await self.committee(a.ethics_committee_id)
        if not via_workflow and await self._member_role(c) != "chair" and not self.secretariat():
            raise forbidden("Only the committee chair (or the secretariat) decides")
        m = await self.meta("ethics", a.id)
        today = await self.today()
        a.decision = body.decision.value
        if body.decision.value == "approved":
            a.approval_no = body.approval_no or await self.sequence(
                f"ethics:{c.committee_type}", c.committee_type.upper()
            )
            a.valid_to = body.valid_to or today + timedelta(days=365)
        m["conditions"] = body.conditions
        hist = list(m.get("history") or [])
        hist.append(
            {"action": "decided", "decision": a.decision, "at": now_utc().isoformat(), "by": str(self.actor_id)}
        )
        m["history"] = hist
        await self.put_meta("ethics", a.id, m)
        wf = await self._wf(m)
        if not via_workflow and wf is not None and wf.status in ("pending", "escalated"):
            await self.close_workflow(wf.id, "approved" if a.decision == "approved" else "rejected")
        await self.db.flush()
        await self._emit(
            "research.ethics_decided",
            {"approval_id": str(a.id), "decision": a.decision, "approval_no": a.approval_no},
            "ethics_approval",
            a.id,
        )
        await self._notify(
            "research.ethics_decision",
            [await self.staff_user(a.pi_staff_id)],
            {"title": a.project_title[:120], "decision": a.decision, "approval_no": a.approval_no or ""},
        )
        return (await self.outs([a]))[0]

    async def amend(self, aid: uuid.UUID, body: EthicsAmend) -> EthicsApplicationOut:
        self.require_writer()
        a = await self.row(aid, lock=True)
        if a.decision != "approved":
            raise rule("Only an approved protocol is amended / renewed", "NOT_APPROVED")
        if not (self.secretariat() or await self.is_mine(a.pi_staff_id)):
            raise forbidden("Only the PI or the ethics secretariat records this")
        m = await self.meta("ethics", a.id)
        entry: dict[str, Any] = {
            "action": body.kind,
            "description": body.description,
            "document_url": body.document_url,
            "at": now_utc().isoformat(),
            "by": str(self.actor_id),
        }
        if body.kind == "renew":
            if not self.secretariat():
                raise forbidden("Renewals are granted by the ethics secretariat")
            base = max(a.valid_to or date.min, await self.today())
            a.valid_to = body.valid_to or base + timedelta(days=365)
            entry["valid_to"] = a.valid_to.isoformat()
        m.setdefault("history", []).append(entry)
        await self.put_meta("ethics", a.id, m)
        await self.db.flush()
        await self._audit(body.kind, "ethics_approval", a.id, None, entry)
        return (await self.outs([a]))[0]


@workflow_engine.on(WF_KEY, "approved")
async def _review_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    """The chair approved in the inbox without a decision body: record ``approved`` with a generated number."""
    svc = EthicsService(db, actor, institution_id=instance.institution_id)
    a = (await db.execute(select(EthicsApproval).where(EthicsApproval.id == instance.entity_id))).scalar_one_or_none()
    if a is not None and a.decision is None:
        await svc.decide(a.id, EthicsReview(decision=EthicsDecision.APPROVED), via_workflow=True)


@workflow_engine.on(WF_KEY, "rejected")
async def _review_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    svc = EthicsService(db, actor, institution_id=instance.institution_id)
    a = (await db.execute(select(EthicsApproval).where(EthicsApproval.id == instance.entity_id))).scalar_one_or_none()
    if a is not None and a.decision is None:
        await svc.decide(a.id, EthicsReview(decision=EthicsDecision.REVISE), via_workflow=True)
