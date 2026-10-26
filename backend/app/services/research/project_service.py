"""Funded research projects — Prompts/30 §30.6 ``project_service`` ({research.projects_grants}).

1. Lifecycle ``applied`` → ``sanctioned`` → ``ongoing`` → ``completed`` → ``closed``. The research cell's ``sanction``
   action (letter, sanctioned amount, budget heads) starts ``research.project_sanction`` and records the cell's own
   step-1 verification; the principal's acknowledgement (inbox or this API) fires the ``approved`` hook: status
   ``sanctioned``, sanction letter archived through Phase 26 ``documents.render('custom', 'research_project', id)``
   and ``research.project_sanctioned`` {project_id, title, funding_agency, sanctioned_paise, pi_staff_id,
   budget_heads} emitted — the Phase 23 consumer creates the ``grant_ledgers`` row and back-links
   ``research_projects.grant_ledger_id``. ``start`` refuses projects whose ethics category is listed in
   ``research.ethics_required_for_categories`` without a valid approval (409 ``ETHICS_REQUIRED``); ``close`` needs the
   utilisation certificate (the Phase 23 ledger closed — 409 ``UC_REQUIRED``).
2. Expenses: the PI raises a request; ``via=direct`` books a Phase 23 grant expense on the head (head-wise availability
   from the ledger, 409 ``GRANT_HEAD_EXCEEDED``); ``via=indent`` raises a Phase 22 indent (procurement rules apply) and
   books the grant expense when ``inventory.indent_fulfilled`` arrives. Receipts / expenses booked on the ledger are
   mirrored into ``received_paise`` / ``utilisation``. Project staff (JRF / SRF / RA) and their monthly pay live in
   the side store (Phase 06 payroll reads them when ``source_type='research_project'`` is configured).
3. Reports: periodic progress reports per ``report_periodicity_months`` (reports-due schedule, weekly reminder Beat),
   SoE / UC through Phase 23, closure checklist.

Visibility: the PI and co-PIs (``co_pi[].staff_id``) own a project; HODs read their department's projects; the research
cell, principal-level readers, IQAC and auditors read all; accountants read money (``accounting:view_all``).
"""

import contextlib
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, true

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.enums.research import PROJECT_ACTIONS
from app.models.accounting import GrantLedger
from app.models.platform import WorkflowInstance
from app.models.research import EthicsApproval, ResearchProject
from app.schemas.research import (
    ProjectAction,
    ProjectExpenseRequest,
    ProjectLedgerOut,
    ProjectReport,
    ProjectStaffIn,
    RschProjectIn,
    RschProjectOut,
    RschProjectUpdate,
)
from app.services.research.common import ResearchBase, forbidden, not_found, now_utc, rule, rupees, staff_name

WF_KEY = "research.project_sanction"


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


class ProjectService(ResearchBase):
    # ---- visibility -----------------------------------------------------------------------------------------------------
    async def predicate(self, scope: str | None = None) -> Any:
        if scope in (None, "all") and self.money_reader():
            return true()
        return await self.owned_predicate(ResearchProject.pi_staff_id, scope=scope, json_col=ResearchProject.co_pi)

    async def row(self, pid: uuid.UUID, *, lock: bool = False, visible: bool = True) -> ResearchProject:
        stmt = select(ResearchProject).where(ResearchProject.id == pid, ResearchProject.institution_id == self.inst)
        if visible:
            stmt = stmt.where(await self.predicate())
        p = (await self.db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
        if p is None:
            raise not_found("Research project")
        return p

    async def _owns(self, p: ResearchProject) -> bool:
        return await self.is_mine(p.pi_staff_id, p.co_pi)

    async def _require_pi(self, p: ResearchProject) -> None:
        self.require_writer()
        if not self.cell() and not await self._owns(p):
            raise forbidden("Only the PI / co-PI or the research cell acts on this project")

    # ---- outputs --------------------------------------------------------------------------------------------------------
    def _due(self, p: ResearchProject, m: dict[str, Any], today: date) -> list[dict[str, Any]]:
        if p.status not in ("sanctioned", "ongoing") or not p.start_on:
            return []
        every = int(m.get("report_periodicity_months") or 6)
        submitted = {r.get("period") for r in m.get("reports") or []}
        out, d, i = [], _add_months(p.start_on, every), 1
        end = p.end_on or _add_months(p.start_on, 36)
        while d <= end and i <= 24:
            period = f"P{i}"
            if period not in submitted:
                out.append({"period": period, "due_on": d.isoformat(), "overdue": d < today})
            d, i = _add_months(d, every), i + 1
        return out[:4]

    async def outs(self, rows: list[ResearchProject]) -> list[RschProjectOut]:
        staff = await self.staff_map([r.pi_staff_id for r in rows])
        metas = await self.metas("project", [r.id for r in rows]) if rows else {}
        gids = [r.grant_ledger_id for r in rows if r.grant_ledger_id]
        ledgers = (
            {g.id: g for g in (await self.db.execute(select(GrantLedger).where(GrantLedger.id.in_(gids)))).scalars()}
            if gids
            else {}
        )
        mine = await self.my_staff_id()
        today = await self.today()
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            g = ledgers.get(r.grant_ledger_id) if r.grant_ledger_id else None
            heads = [dict(h) for h in (g.budget_heads if g is not None else r.budget_heads) or []]
            for h in heads:
                h["available_paise"] = int(h.get("allocated_paise", 0)) - int(h.get("utilised_paise", 0))
            utilised = int(g.utilised_paise) if g is not None else int((r.utilisation or {}).get("utilised_paise", 0))
            received = int(g.received_paise) if g is not None else int(r.received_paise or 0)
            s = staff.get(r.pi_staff_id)
            out.append(
                RschProjectOut(
                    id=r.id,
                    title=r.title,
                    pi_staff_id=r.pi_staff_id,
                    pi_name=staff_name(s),
                    department_id=s.department_id if s else None,
                    co_pi=list(r.co_pi or []),
                    funding_agency=r.funding_agency,
                    scheme=r.scheme,
                    sanctioned_paise=r.sanctioned_paise,
                    received_paise=received,
                    utilised_paise=utilised,
                    utilisation_pct=round(100 * utilised / received, 1) if received else 0.0,
                    start_on=r.start_on,
                    end_on=r.end_on,
                    status=r.status,
                    budget_heads=heads,
                    ethics_approval_id=r.ethics_approval_id,
                    grant_ledger_id=r.grant_ledger_id,
                    sanction_letter_url=r.sanction_letter_url,
                    sanction_document_id=uuid.UUID(m["sanction_document_id"])
                    if m.get("sanction_document_id")
                    else None,
                    workflow_instance_id=uuid.UUID(m["workflow_instance_id"])
                    if m.get("workflow_instance_id")
                    else None,
                    reports=list(m.get("reports") or []),
                    reports_due=self._due(r, m, today),
                    staff=list(m.get("staff") or []),
                    expense_requests=list(m.get("expense_requests") or []),
                    is_pi=mine is not None
                    and (r.pi_staff_id == mine or any(str(c.get("staff_id")) == str(mine) for c in (r.co_pi or []))),
                )
            )
        return out

    # ---- reads ------------------------------------------------------------------------------------------------------------
    async def query(
        self,
        *,
        status: str | None = None,
        agency: str | None = None,
        department_id: uuid.UUID | None = None,
        scope: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RschProjectOut], int]:
        from app.models.hr import Staff

        stmt = select(ResearchProject).where(ResearchProject.institution_id == self.inst, await self.predicate(scope))
        if status:
            stmt = stmt.where(ResearchProject.status == status)
        if agency:
            stmt = stmt.where(ResearchProject.funding_agency.ilike(f"%{agency}%"))
        if department_id:
            stmt = stmt.where(
                ResearchProject.pi_staff_id.in_(select(Staff.id).where(Staff.department_id == department_id))
            )
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(stmt.order_by(ResearchProject.created_at.desc()).limit(limit).offset(offset))
            ).scalars()
        )
        return await self.outs(rows), total

    async def mine(self) -> list[RschProjectOut]:
        me = await self.require_my_staff()
        rows = list(
            (
                await self.db.execute(
                    select(ResearchProject)
                    .where(
                        ResearchProject.institution_id == self.inst,
                        (ResearchProject.pi_staff_id == me.id)
                        | ResearchProject.co_pi.contains([{"staff_id": str(me.id)}]),
                    )
                    .order_by(ResearchProject.created_at.desc())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def get(self, pid: uuid.UUID) -> RschProjectOut:
        return (await self.outs([await self.row(pid)]))[0]

    # ---- writes ----------------------------------------------------------------------------------------------------------
    async def create(self, body: RschProjectIn, *, internal: bool = False) -> RschProjectOut:
        if not internal:
            self.require_writer()
        if body.pi_staff_id is not None and (internal or self.cell()):
            pi = (await self.staff_row(body.pi_staff_id)).id
        else:
            pi = (await self.require_my_staff()).id
        if body.start_on and body.end_on and body.end_on < body.start_on:
            raise rule("end_on precedes start_on", "BAD_DATES", 422)
        if body.ethics_approval_id:
            await self._ethics(body.ethics_approval_id)
        heads = [h.model_dump() | {"utilised_paise": 0} for h in body.budget_heads]
        if body.sanctioned_paise and heads and sum(h["allocated_paise"] for h in heads) > body.sanctioned_paise:
            raise rule("Budget heads exceed the project amount", "HEADS_EXCEED", 422)
        p = ResearchProject(
            institution_id=self.inst,
            pi_staff_id=pi,
            co_pi=[c.model_dump(mode="json") for c in body.co_pi],
            title=body.title,
            funding_agency=body.funding_agency,
            scheme=body.scheme,
            sanctioned_paise=body.sanctioned_paise,
            start_on=body.start_on,
            end_on=body.end_on,
            status="applied",
            budget_heads=heads,
            ethics_approval_id=body.ethics_approval_id,
            sanction_letter_url=body.sanction_letter_url,
            utilisation={"utilised_paise": 0},
        )
        self.db.add(p)
        await self.db.flush()
        await self.put_meta(
            "project",
            p.id,
            {
                "ethics_category": body.ethics_category,
                "report_periodicity_months": body.report_periodicity_months,
                "timeline": [{"at": now_utc().isoformat(), "action": "applied", "by": str(self.actor_id)}],
            },
        )
        await self._audit("create", "research_project", p.id, None, {"title": p.title, "agency": p.funding_agency})
        await self._emit(
            "research.project_applied",
            {"project_id": str(p.id), "pi_staff_id": str(pi), "funding_agency": p.funding_agency},
            "research_project",
            p.id,
        )
        return (await self.outs([p]))[0]

    async def update(self, pid: uuid.UUID, body: RschProjectUpdate) -> RschProjectOut:
        p = await self.row(pid, lock=True)
        await self._require_pi(p)
        data = body.model_dump(exclude_unset=True, mode="json")
        if p.status in ("closed",):
            raise rule("A closed project cannot be edited", "PROJECT_CLOSED")
        if "budget_heads" in data:
            if p.status != "applied" and not self.cell():
                raise rule("Budget heads are fixed at sanction — reallocate on the grant ledger", "HEADS_FIXED")
            data["budget_heads"] = [h | {"utilised_paise": 0} for h in data["budget_heads"] or []]
        if "ethics_approval_id" in data and data["ethics_approval_id"]:
            await self._ethics(uuid.UUID(data["ethics_approval_id"]))
        m = await self.meta("project", p.id)
        if "ethics_category" in data:
            m["ethics_category"] = data.pop("ethics_category")
            await self.put_meta("project", p.id, m)
        for k, v in data.items():
            if k.endswith("_on") and isinstance(v, str):
                v = date.fromisoformat(v)
            if k == "ethics_approval_id" and v:
                v = uuid.UUID(v)
            setattr(p, k, v)
        await self.db.flush()
        await self._audit("update", "research_project", p.id, None, body.model_dump(exclude_unset=True, mode="json"))
        return (await self.outs([p]))[0]

    async def _ethics(self, aid: uuid.UUID) -> EthicsApproval:
        a = (
            await self.db.execute(
                select(EthicsApproval).where(EthicsApproval.id == aid, EthicsApproval.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Ethics approval")
        return a

    # ---- lifecycle -------------------------------------------------------------------------------------------------------
    async def action(self, pid: uuid.UUID, body: ProjectAction) -> RschProjectOut:
        p = await self.row(pid, lock=True)
        allowed, target = PROJECT_ACTIONS[body.action]
        if p.status not in allowed:
            raise rule(f"Cannot {body.action} a project that is {p.status}", "INVALID_TRANSITION")
        m = await self.meta("project", p.id)
        today = await self.today()
        if body.action == "submit":
            await self._require_pi(p)
            m["submitted_on"] = today.isoformat()
        elif body.action == "sanction":
            self.require_cell()
            amount = body.sanctioned_paise or p.sanctioned_paise
            if not amount:
                raise rule("sanctioned_paise is required", "AMOUNT_REQUIRED", 422)
            heads = [h.model_dump() | {"utilised_paise": 0} for h in body.budget_heads] if body.budget_heads else None
            heads = heads or [dict(h) for h in (p.budget_heads or [])]
            if heads and sum(int(h.get("allocated_paise", 0)) for h in heads) > amount:
                raise rule("Budget heads exceed the sanctioned amount", "HEADS_EXCEED", 422)
            if m.get("workflow_instance_id"):
                wf = (
                    await self.db.execute(
                        select(WorkflowInstance).where(WorkflowInstance.id == uuid.UUID(m["workflow_instance_id"]))
                    )
                ).scalar_one_or_none()
                if wf is not None and wf.status in ("pending", "escalated"):
                    raise rule("The sanction is already awaiting the principal", "SANCTION_PENDING")
            m["pending_sanction"] = {
                "sanctioned_paise": amount,
                "budget_heads": heads,
                "sanction_letter_url": body.sanction_letter_url,
                "start_on": (body.start_on or p.start_on or today).isoformat(),
                "end_on": end.isoformat() if (end := body.end_on or p.end_on) else None,
                "remarks": body.remarks,
            }
            s = await self.staff_row(p.pi_staff_id)
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_KEY,
                entity_type="research_project",
                entity_id=p.id,
                started_by=self.actor_id,
                context={
                    "department_id": str(s.department_id) if s.department_id else None,
                    "amount_paise": amount,
                    "funding_agency": p.funding_agency,
                },
                title=f"Sanction · {p.title[:80]} · ₹{amount / 100:,.0f}",
            )
            m["workflow_instance_id"] = str(wf.id)
            await self.put_meta("project", p.id, m)
            if self.principal is not None:
                with contextlib.suppress(APIError):  # the research cell's own verification is step 1
                    await workflow_engine.act(
                        self.db, instance_id=wf.id, actor=self.principal, decision="approve", comment="Verified"
                    )
            await self.db.refresh(p)
            return (await self.outs([p]))[0]
        elif body.action == "start":
            await self._require_pi(p)
            await self._ethics_gate(p, m, today)
            p.start_on = body.start_on or p.start_on or today
        elif body.action == "complete":
            await self._require_pi(p)
            m["final_report_url"] = body.final_report_url
            m["completed_on"] = today.isoformat()
        elif body.action == "close":
            self.require_cell()
            if p.grant_ledger_id:
                g = (await self.db.execute(select(GrantLedger).where(GrantLedger.id == p.grant_ledger_id))).scalar_one()
                if g.status != "closed":
                    raise rule("Submit the utilisation certificate (close the grant ledger) first", "UC_REQUIRED")
            m["closure"] = {
                "closed_on": today.isoformat(),
                "assets_transferred": True,
                "remarks": body.remarks,
            }
        p.status = target
        tl = list(m.get("timeline") or [])
        tl.append({"at": now_utc().isoformat(), "action": body.action, "by": str(self.actor_id)})
        m["timeline"] = tl
        await self.put_meta("project", p.id, m)
        await self.db.flush()
        await self._audit(body.action, "research_project", p.id, None, body.model_dump(mode="json"))
        if body.action != "submit":
            event = {"start": "started", "complete": "completed", "close": "closed"}[body.action]
            await self._emit(
                f"research.project_{event}", {"project_id": str(p.id), "status": p.status}, "research_project", p.id
            )
        return (await self.outs([p]))[0]

    async def _ethics_gate(self, p: ResearchProject, m: dict[str, Any], today: date) -> None:
        required = await self.json_setting("ethics_required_for_categories", ["clinical", "animal", "biosafety"])
        cat = m.get("ethics_category")
        if not cat or cat not in required:
            return
        if p.ethics_approval_id:
            a = await self._ethics(p.ethics_approval_id)
            if a.decision == "approved" and (a.valid_to is None or a.valid_to >= today):
                return
        raise rule(f"An ethics approval is required before starting a {cat} project", "ETHICS_REQUIRED")

    async def apply_sanction(self, pid: uuid.UUID) -> None:
        """``research.project_sanction`` approved: the principal acknowledged."""
        p = await self.row(pid, lock=True, visible=False)
        if p.status != "applied":
            return
        m = await self.meta("project", p.id)
        ps = m.pop("pending_sanction", None) or {}
        p.sanctioned_paise = int(ps.get("sanctioned_paise") or p.sanctioned_paise or 0)
        p.budget_heads = ps.get("budget_heads") or p.budget_heads
        p.sanction_letter_url = ps.get("sanction_letter_url") or p.sanction_letter_url
        if ps.get("start_on"):
            p.start_on = date.fromisoformat(ps["start_on"])
        if ps.get("end_on"):
            p.end_on = date.fromisoformat(ps["end_on"])
        p.status = "sanctioned"
        m["sanctioned_on"] = (await self.today()).isoformat()
        tl = list(m.get("timeline") or [])
        tl.append({"at": now_utc().isoformat(), "action": "sanctioned", "by": str(self.actor_id)})
        m["timeline"] = tl
        await self.db.flush()
        doc = await self._letter(p)
        if doc:
            m["sanction_document_id"] = str(doc)
        await self.put_meta("project", p.id, m)
        await self._emit(
            "research.project_sanctioned",
            {
                "project_id": str(p.id),
                "title": p.title,
                "funding_agency": p.funding_agency,
                "sanctioned_paise": int(p.sanctioned_paise or 0),
                "pi_staff_id": str(p.pi_staff_id),
                "budget_heads": [
                    {"name": h.get("name"), "allocated_paise": int(h.get("allocated_paise", 0))}
                    for h in (p.budget_heads or [])
                ],
            },
            "research_project",
            p.id,
        )
        await self._notify(
            "research.project_sanctioned",
            [await self.staff_user(p.pi_staff_id)],
            {"title": p.title[:120], "amount": rupees(p.sanctioned_paise), "agency": p.funding_agency or ""},
        )

    async def _letter(self, p: ResearchProject) -> uuid.UUID | None:
        if not await self.feature("documents.templates"):
            return None
        from app.services.documents.render_service import RenderService

        s = await self.staff_row(p.pi_staff_id)
        heads = "; ".join(f"{h.get('name')}: Rs {rupees(h.get('allocated_paise'))}" for h in p.budget_heads or [])
        try:
            res = await RenderService(self.db, self.principal, self.request, self.inst).render(
                "custom",
                "research_project",
                p.id,
                allow_multiple=True,
                variables_override={
                    "title": "Project sanction letter",
                    "body": f"The project “{p.title}” of {staff_name(s)} (Principal Investigator) funded by "
                    f"{p.funding_agency or 'the institution'}{f' under {p.scheme}' if p.scheme else ''} is sanctioned "
                    f"for Rs {rupees(p.sanctioned_paise)} from {p.start_on or '—'} to {p.end_on or '—'}. "
                    f"Budget heads: {heads or '—'}.",
                },
            )
        except APIError:
            return None
        return res.issued_document_id

    async def withdraw_sanction(self, pid: uuid.UUID) -> None:
        m = await self.meta("project", pid)
        m.pop("pending_sanction", None)
        m["sanction_rejected_on"] = (await self.today()).isoformat()
        await self.put_meta("project", pid, m)

    # ---- ledger / expenses -------------------------------------------------------------------------------------------------
    async def ledger(self, pid: uuid.UUID) -> ProjectLedgerOut:
        p = await self.row(pid)
        out = (await self.outs([p]))[0]
        return ProjectLedgerOut(
            project_id=p.id,
            grant_ledger_id=p.grant_ledger_id,
            sanctioned_paise=int(p.sanctioned_paise or 0),
            received_paise=out.received_paise,
            utilised_paise=out.utilised_paise,
            balance_paise=out.received_paise - out.utilised_paise,
            heads=out.budget_heads,
        )

    async def expense(self, pid: uuid.UUID, body: ProjectExpenseRequest) -> RschProjectOut:
        p = await self.row(pid, lock=True)
        await self._require_pi(p)
        if p.status not in ("sanctioned", "ongoing"):
            raise rule("Expenses are booked on sanctioned / ongoing projects", "PROJECT_NOT_ACTIVE")
        if p.grant_ledger_id is None:
            raise rule("The grant ledger is not linked yet", "LEDGER_PENDING")
        g = (
            await self.db.execute(select(GrantLedger).where(GrantLedger.id == p.grant_ledger_id).with_for_update())
        ).scalar_one()
        head = next((h for h in g.budget_heads or [] if str(h.get("name", "")).lower() == body.head.lower()), None)
        if head is None:
            raise rule("Unknown budget head", "UNKNOWN_HEAD", 422)
        m = await self.meta("project", p.id)
        reqs = list(m.get("expense_requests") or [])
        reserved = sum(
            int(r["amount_paise"])
            for r in reqs
            if r.get("via") == "indent"
            and r.get("status") == "raised"
            and str(r.get("head")).lower() == body.head.lower()
        )
        available = int(head.get("allocated_paise", 0)) - int(head.get("utilised_paise", 0)) - reserved
        if body.amount_paise > available:
            raise rule("Not enough available in this budget head", "GRANT_HEAD_EXCEEDED", available=available)
        today = await self.today()
        entry: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "head": head["name"],
            "amount_paise": body.amount_paise,
            "description": body.description,
            "via": body.via,
            "attachments": body.attachments,
            "at": now_utc().isoformat(),
            "by": str(self.actor_id),
        }
        if body.via == "direct":
            from app.schemas.accounting import GrantExpense
            from app.services.accounting.grant_service import GrantService

            await GrantService(self.db, None, self.request, self.inst).expense(
                g.id,
                GrantExpense(
                    head=head["name"],
                    amount_paise=body.amount_paise,
                    spent_on=body.spent_on or today,
                    description=body.description,
                    payee=body.payee,
                    document_url=body.attachments[0] if body.attachments else None,
                ),
            )
            entry["status"] = "booked"
            await self.sync_ledger(p.id)
        else:
            from app.schemas.inventory import IndentCreate, IndentLine
            from app.services.inventory.indent_service import IndentService

            s = await self.staff_row(p.pi_staff_id)
            svc = IndentService(self.db, self.principal, self.request, self.inst)
            ind = await svc.create(
                IndentCreate(
                    department_id=s.department_id,
                    purpose=f"[project:{p.id}] {body.description}"[:2000],
                    items=[
                        IndentLine(
                            free_text=body.description[:200],
                            qty=body.qty,
                            est_unit_cost_paise=int(body.amount_paise / body.qty),
                        )
                    ],
                )
            )
            await svc.put_meta(
                "indent",
                ind.id,
                {"research_project_id": str(p.id), "grant_ledger_id": str(g.id), "grant_head": head["name"]},
            )
            with contextlib.suppress(APIError):
                await svc.submit(ind.id)
            entry.update(status="raised", indent_id=str(ind.id))
        reqs.append(entry)
        m["expense_requests"] = reqs
        await self.put_meta("project", p.id, m)
        await self._emit(
            "research.project_expense_requested",
            {"project_id": str(p.id), "head": head["name"], "amount_paise": body.amount_paise, "via": body.via},
            "research_project",
            p.id,
        )
        return (await self.outs([p]))[0]

    async def on_indent_fulfilled(self, indent_id: uuid.UUID, amount_paise: int | None) -> bool:
        """Phase 22 ``inventory.indent_fulfilled`` for a project indent → the grant expense on its head."""
        from app.schemas.accounting import GrantExpense
        from app.services.accounting.grant_service import GrantService
        from app.services.inventory.indent_service import IndentService

        im = await IndentService(self.db, None, institution_id=self.inst).meta("indent", indent_id)
        if not im.get("research_project_id"):
            return False
        pid = uuid.UUID(im["research_project_id"])
        m = await self.meta("project", pid)
        reqs = list(m.get("expense_requests") or [])
        entry = next((r for r in reqs if r.get("indent_id") == str(indent_id)), None)
        if entry is None or entry.get("status") == "booked":
            return False
        amount = int(amount_paise or entry["amount_paise"])
        await GrantService(self.db, None, institution_id=self.inst).expense(
            uuid.UUID(im["grant_ledger_id"]),
            GrantExpense(
                head=im["grant_head"],
                amount_paise=amount,
                spent_on=await self.today(),
                description=f"Indent {indent_id} · {entry['description']}"[:255],
            ),
        )
        entry.update(status="booked", booked_paise=amount)
        m["expense_requests"] = reqs
        await self.put_meta("project", pid, m)
        await self.sync_ledger(pid)
        return True

    async def sync_ledger(self, pid: uuid.UUID) -> None:
        """Mirror the Phase 23 ledger (receipts / utilisation) onto the project row."""
        p = (await self.db.execute(select(ResearchProject).where(ResearchProject.id == pid))).scalar_one_or_none()
        if p is None or p.grant_ledger_id is None:
            return
        g = (await self.db.execute(select(GrantLedger).where(GrantLedger.id == p.grant_ledger_id))).scalar_one_or_none()
        if g is None:
            return
        p.received_paise = int(g.received_paise)
        p.utilisation = {
            "utilised_paise": int(g.utilised_paise),
            "by_head": {h.get("name"): int(h.get("utilised_paise", 0)) for h in g.budget_heads or []},
            "synced_at": now_utc().isoformat(),
        }
        await self.db.flush()

    async def on_grant_event(self, grant_id: uuid.UUID) -> None:
        pid = (
            await self.db.execute(select(GrantLedger.research_project_id).where(GrantLedger.id == grant_id))
        ).scalar_one_or_none()
        if pid:
            await self.sync_ledger(pid)

    # ---- reports / staff ------------------------------------------------------------------------------------------------
    async def reports(self, pid: uuid.UUID) -> list[dict[str, Any]]:
        await self.row(pid)
        return list((await self.meta("project", pid)).get("reports") or [])

    async def add_report(self, pid: uuid.UUID, body: ProjectReport) -> list[dict[str, Any]]:
        p = await self.row(pid, lock=True)
        await self._require_pi(p)
        m = await self.meta("project", p.id)
        reps = [r for r in m.get("reports") or [] if r.get("period") != body.period]
        reps.append(body.model_dump() | {"submitted_at": now_utc().isoformat(), "by": str(self.actor_id)})
        m["reports"] = reps
        await self.put_meta("project", p.id, m)
        await self._emit(
            "research.project_report_uploaded",
            {"project_id": str(p.id), "period": body.period},
            "research_project",
            p.id,
        )
        return reps

    async def add_staff(self, pid: uuid.UUID, body: ProjectStaffIn) -> list[dict[str, Any]]:
        p = await self.row(pid, lock=True)
        await self._require_pi(p)
        m = await self.meta("project", p.id)
        st = list(m.get("staff") or [])
        st.append(body.model_dump(mode="json") | {"id": uuid.uuid4().hex[:12]})
        m["staff"] = st
        await self.put_meta("project", p.id, m)
        await self._audit("add_staff", "research_project", p.id, None, body.model_dump(mode="json"))
        return st

    async def report_reminders(self) -> int:
        today = await self.today()
        n = 0
        rows = (
            await self.db.execute(
                select(ResearchProject).where(
                    ResearchProject.institution_id == self.inst, ResearchProject.status.in_(("sanctioned", "ongoing"))
                )
            )
        ).scalars()
        metas = await self.metas("project")
        for p in rows:
            m = metas.get(str(p.id), {})
            for due in self._due(p, m, today):
                d = date.fromisoformat(due["due_on"])
                if today <= d <= today + timedelta(days=14) or due["overdue"]:
                    await self._notify(
                        "research.project_report_due",
                        [await self.staff_user(p.pi_staff_id)],
                        {"title": p.title[:120], "period": due["period"], "due_on": due["due_on"]},
                    )
                    await self._emit(
                        "research.project_report_due",
                        {"project_id": str(p.id), "period": due["period"], "due_on": due["due_on"]},
                        "research_project",
                        p.id,
                    )
                    n += 1
                    break
            if p.end_on and today <= p.end_on <= today + timedelta(days=60) and today.weekday() == 0:
                await self._notify(
                    "research.project_closing",
                    [await self.staff_user(p.pi_staff_id)],
                    {"title": p.title[:120], "end_on": p.end_on.isoformat()},
                )
        return n


@workflow_engine.on(WF_KEY, "approved")
async def _sanction_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await ProjectService(db, actor, institution_id=instance.institution_id).apply_sanction(instance.entity_id)


@workflow_engine.on(WF_KEY, "rejected")
async def _sanction_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await ProjectService(db, actor, institution_id=instance.institution_id).withdraw_sanction(instance.entity_id)
