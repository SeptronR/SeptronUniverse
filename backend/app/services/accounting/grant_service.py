"""Grant ledgers — Prompts/23 §23.6 ``grant_service`` (``accounting.grants_ledger``).

A ledger per funded project (manual, or from Phase 30's ``research.project_sanctioned``) with agency heads
(``budget_heads`` JSONB ``[{name, allocated_paise, utilised_paise}]``); receipts (instalments → ``income_records`` on
``grants`` with ``source_type='grant_receipt'``), head-wise expenses (``expense_records`` on the head's account,
``payee='[grant:<id>]'``) blocked beyond the head's available (409 ``GRANT_HEAD_EXCEEDED``), reallocation between heads
when the agency allows it, utilisation certificate (GFR 12-A style PDF) and statement of expenditure per period,
closure with the unspent balance moved to ``Unspent grants`` (refund record). PI ownership = ``pi_staff_id`` in the
ledger's ``accounting_meta`` (falls back to the Phase 30 ``ResearchProject.pi_staff_id``; ``from_project`` back-links
``research_projects.grant_ledger_id``).
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.accounting import ExpenseRecord, GrantLedger, IncomeRecord
from app.schemas.accounting import (
    GrantClose,
    GrantExpense,
    GrantLedgerIn,
    GrantLedgerOut,
    GrantReallocate,
    GrantReceipt,
)
from app.services.accounting.common import AccountingBase, all_access, institution_scope, now_utc, rule

HEAD_ACCOUNTS = {
    "manpower": "5200",
    "equipment": "1430",
    "consumables": "5310",
    "travel": "5700",
    "contingency": "5990",
    "overheads": "5990",
}


class GrantService(AccountingBase):
    async def _pi(self, g: GrantLedger, meta: dict[str, Any] | None = None) -> uuid.UUID | None:
        m = meta if meta is not None else await self.meta("grant", g.id)
        if m.get("pi_staff_id"):
            return uuid.UUID(m["pi_staff_id"])
        if g.research_project_id:
            from app.models.research import ResearchProject

            v = (
                await self.db.execute(
                    select(ResearchProject.pi_staff_id).where(ResearchProject.id == g.research_project_id)
                )
            ).scalar_one_or_none()
            return v
        return None

    async def visible(self, g: GrantLedger, meta: dict[str, Any] | None = None) -> bool:
        p = self.principal
        # research readers only at institution level (research_cell): faculty reach view_all through research:manage and
        # HODs hold it at department scope, and both may see only the grants they are PI of (Prompts/23 visibility)
        if all_access(p) or self.can("accounting", "manage") or (self.can("research", "view_all") and institution_scope(p)):
            return True
        mine = await self.my_staff_id()
        return mine is not None and mine == await self._pi(g, meta)

    async def outs(self, rows: list[GrantLedger]) -> list[GrantLedgerOut]:
        from app.models.hr import Staff

        metas = await self.metas("grant") if rows else {}
        out = []
        for g in rows:
            m = metas.get(str(g.id), {})
            pi = await self._pi(g, m)
            pi_name = None
            if pi:
                s = (await self.db.execute(select(Staff).where(Staff.id == pi))).scalar_one_or_none()
                pi_name = s.full_name if s else None
            heads = [
                {**h, "available_paise": int(h.get("allocated_paise", 0)) - int(h.get("utilised_paise", 0))}
                for h in (g.budget_heads or [])
            ]
            out.append(
                GrantLedgerOut(
                    id=g.id,
                    research_project_id=g.research_project_id,
                    pi_staff_id=pi,
                    pi_name=pi_name,
                    name=g.name,
                    funding_agency=g.funding_agency,
                    sanctioned_paise=int(g.sanctioned_paise),
                    received_paise=int(g.received_paise),
                    utilised_paise=int(g.utilised_paise),
                    balance_paise=int(g.received_paise) - int(g.utilised_paise),
                    budget_heads=heads,
                    status=g.status,
                )
            )
        return out

    async def list_grants(self) -> list[GrantLedgerOut]:
        rows = list(
            (
                await self.db.execute(
                    select(GrantLedger)
                    .where(GrantLedger.institution_id == self.inst)
                    .order_by(GrantLedger.created_at.desc())
                )
            ).scalars()
        )
        metas = await self.metas("grant")
        rows = [g for g in rows if await self.visible(g, metas.get(str(g.id), {}))]
        return await self.outs(rows)

    async def row(self, gid: uuid.UUID, *, for_update: bool = False) -> GrantLedger:
        q = select(GrantLedger).where(GrantLedger.id == gid, GrantLedger.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        g = (await self.db.execute(q)).scalar_one_or_none()
        if g is None or not await self.visible(g):
            raise APIError(404, ErrorCode.NOT_FOUND, "Grant ledger not found")
        return g

    async def get(self, gid: uuid.UUID) -> GrantLedgerOut:
        return (await self.outs([await self.row(gid)]))[0]

    async def create(self, body: GrantLedgerIn) -> GrantLedgerOut:
        self.require("manage")
        if sum(h.allocated_paise for h in body.budget_heads) > body.sanctioned_paise:
            raise APIError(422, ErrorCode.VALIDATION, "Head allocations exceed the sanctioned amount")
        g = GrantLedger(
            institution_id=self.inst,
            research_project_id=body.research_project_id,
            name=body.name,
            funding_agency=body.funding_agency,
            sanctioned_paise=body.sanctioned_paise,
            budget_heads=[
                {"name": h.name, "allocated_paise": h.allocated_paise, "utilised_paise": 0} for h in body.budget_heads
            ],
        )
        self.db.add(g)
        await self.db.flush()
        await self.put_meta(
            "grant",
            g.id,
            {
                "pi_staff_id": str(body.pi_staff_id) if body.pi_staff_id else None,
                "reallocation_allowed": body.reallocation_allowed,
                "created_by": str(self.actor_id),
            },
        )
        await self._audit(
            "create", "grant_ledger", g.id, None, {"name": g.name, "sanctioned_paise": g.sanctioned_paise}
        )
        return (await self.outs([g]))[0]

    async def update(self, gid: uuid.UUID, name: str | None, agency: str | None) -> GrantLedgerOut:
        self.require("manage")
        g = await self.row(gid, for_update=True)
        if name:
            g.name = name
        if agency is not None:
            g.funding_agency = agency
        await self.db.flush()
        return (await self.outs([g]))[0]

    async def receipt(self, gid: uuid.UUID, body: GrantReceipt) -> GrantLedgerOut:
        self.require("manage", "post")
        g = await self.row(gid, for_update=True)
        if g.status != "active":
            raise rule("The grant is not active", "GRANT_CLOSED")
        if int(g.received_paise) + body.amount_paise > int(g.sanctioned_paise):
            raise rule("Receipts would exceed the sanctioned amount", "OVER_SANCTION")
        await self.check_open(body.received_on)
        g.received_paise = int(g.received_paise) + body.amount_paise
        self.db.add(
            IncomeRecord(
                institution_id=self.inst,
                ledger_account_id=(await self.account("grants")).id,
                amount_paise=body.amount_paise,
                received_on=body.received_on,
                source_type="grant_receipt",
                source_id=g.id,
                description=f"Grant instalment · {g.name}"[:255],
                reference_no=body.reference,
                payment_mode="bank",
                recorded_by=self.actor_id,
            )
        )
        await self.db.flush()
        await self._emit(
            "accounting.grant_received",
            {"grant_id": str(g.id), "amount_paise": body.amount_paise},
            "grant_ledger",
            g.id,
        )
        return (await self.outs([g]))[0]

    async def expense(self, gid: uuid.UUID, body: GrantExpense) -> GrantLedgerOut:
        g = await self.row(gid, for_update=True)
        if g.status != "active":
            raise rule("The grant is not active", "GRANT_CLOSED")
        await self.check_open(body.spent_on)
        heads = [dict(h) for h in (g.budget_heads or [])]
        head = next((h for h in heads if h["name"].lower() == body.head.lower()), None)
        if head is None:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown grant head", {"field": "head"})
        available = int(head["allocated_paise"]) - int(head.get("utilised_paise", 0))
        if body.amount_paise > available:
            raise rule(
                "Not enough available in this grant head — reallocate first", "GRANT_HEAD_EXCEEDED", available=available
            )
        head["utilised_paise"] = int(head.get("utilised_paise", 0)) + body.amount_paise
        g.budget_heads, g.utilised_paise = heads, int(g.utilised_paise) + body.amount_paise
        acct = await self.account(HEAD_ACCOUNTS.get(head["name"].lower(), "5990"))
        self.db.add(
            ExpenseRecord(
                institution_id=self.inst,
                ledger_account_id=acct.id,
                amount_paise=body.amount_paise,
                spent_on=body.spent_on,
                payee=f"[grant:{g.id}]",
                description=f"{head['name']} · {body.description}"[:255],
                reference_no=(body.payee or "")[:80] or None,
                document_url=body.document_url,
                status="paid",
                recorded_by=self.actor_id,
            )
        )
        await self.db.flush()
        await self._audit(
            "expense", "grant_ledger", g.id, None, {"head": head["name"], "amount_paise": body.amount_paise}
        )
        await self._emit(
            "accounting.grant_expensed",
            {"grant_id": str(g.id), "head": head["name"], "amount_paise": body.amount_paise},
            "grant_ledger",
            g.id,
        )
        return (await self.outs([g]))[0]

    async def reallocate(self, gid: uuid.UUID, body: GrantReallocate) -> GrantLedgerOut:
        self.require("manage")
        g = await self.row(gid, for_update=True)
        if not (await self.meta("grant", g.id)).get("reallocation_allowed", True):
            raise rule("The funding agency does not allow reallocation for this grant", "REALLOCATION_NOT_ALLOWED")
        heads = [dict(h) for h in (g.budget_heads or [])]
        src = next((h for h in heads if h["name"].lower() == body.from_head.lower()), None)
        dst = next((h for h in heads if h["name"].lower() == body.to_head.lower()), None)
        if src is None or dst is None:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown grant head")
        if body.amount_paise > int(src["allocated_paise"]) - int(src.get("utilised_paise", 0)):
            raise rule("Not enough available in the source head", "GRANT_HEAD_EXCEEDED")
        src["allocated_paise"] = int(src["allocated_paise"]) - body.amount_paise
        dst["allocated_paise"] = int(dst["allocated_paise"]) + body.amount_paise
        g.budget_heads = heads
        m = await self.meta("grant", g.id)
        m.setdefault("reallocations", []).append(
            {
                "from": src["name"],
                "to": dst["name"],
                "amount_paise": body.amount_paise,
                "remark": body.remark,
                "at": now_utc().isoformat(),
            }
        )
        await self.put_meta("grant", g.id, m)
        await self.db.flush()
        await self._audit(
            "reallocate",
            "grant_ledger",
            g.id,
            None,
            {"from": src["name"], "to": dst["name"], "amount_paise": body.amount_paise, "remark": body.remark},
        )
        return (await self.outs([g]))[0]

    async def close(self, gid: uuid.UUID, body: GrantClose) -> GrantLedgerOut:
        self.require("manage")
        g = await self.row(gid, for_update=True)
        unspent = int(g.received_paise) - int(g.utilised_paise)
        if unspent > 0:
            self.db.add(
                IncomeRecord(
                    institution_id=self.inst,
                    ledger_account_id=(await self.account("2800")).id,
                    amount_paise=unspent,
                    received_on=await self.today(),
                    source_type="grant_unspent",
                    source_id=g.id,
                    description=f"Unspent balance to refund · {g.name}"[:255],
                    recorded_by=self.actor_id,
                )
            )
        g.status = "closed"
        await self.db.flush()
        await self._audit("close", "grant_ledger", g.id, None, {"unspent_paise": unspent, "remark": body.remark})
        await self._emit(
            "accounting.grant_closed", {"grant_id": str(g.id), "unspent_paise": unspent}, "grant_ledger", g.id
        )
        return (await self.outs([g]))[0]

    async def soe(self, gid: uuid.UUID, date_from: date | None = None, date_to: date | None = None) -> dict[str, Any]:
        g = await self.row(gid)
        q = select(ExpenseRecord).where(ExpenseRecord.payee == f"[grant:{g.id}]")
        if date_from:
            q = q.where(ExpenseRecord.spent_on >= date_from)
        if date_to:
            q = q.where(ExpenseRecord.spent_on <= date_to)
        rows = list((await self.db.execute(q.order_by(ExpenseRecord.spent_on))).scalars())
        by_head: dict[str, int] = {}
        for r in rows:
            head = (r.description or "").split(" · ", 1)[0]
            by_head[head] = by_head.get(head, 0) + int(r.amount_paise)
        receipts = (
            (
                await self.db.execute(
                    select(IncomeRecord).where(
                        IncomeRecord.source_type == "grant_receipt", IncomeRecord.source_id == g.id
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            "grant": (await self.outs([g]))[0].model_dump(mode="json"),
            "period_from": date_from.isoformat() if date_from else None,
            "period_to": date_to.isoformat() if date_to else None,
            "receipts_paise": sum(int(r.amount_paise) for r in receipts),
            "expenditure_by_head": by_head,
            "expenditure_paise": sum(by_head.values()),
            "rows": [
                {"on": r.spent_on.isoformat(), "description": r.description, "amount_paise": int(r.amount_paise)}
                for r in rows
            ],
        }

    async def uc_lines(self, gid: uuid.UUID, date_from: date | None, date_to: date | None) -> tuple[str, list[str]]:
        s = await self.soe(gid, date_from, date_to)
        g = s["grant"]
        inst = await self.institution()
        lines = [
            "UTILISATION CERTIFICATE (GFR 12-A)",
            f"Institution: {inst.name}",
            f"Grant: {g['name']}   Agency: {g['funding_agency'] or '-'}   PI: {g['pi_name'] or '-'}",
            f"Period: {s['period_from'] or 'start'} to {s['period_to'] or 'date'}",
            "",
            f"Sanctioned: Rs {g['sanctioned_paise'] / 100:,.2f}",
            f"Received:   Rs {s['receipts_paise'] / 100:,.2f}",
            f"Utilised:   Rs {s['expenditure_paise'] / 100:,.2f}",
            f"Unspent:    Rs {(s['receipts_paise'] - s['expenditure_paise']) / 100:,.2f}",
            "",
            "Head-wise expenditure:",
        ]
        lines += [f"  {h:<20} Rs {v / 100:>14,.2f}" for h, v in s["expenditure_by_head"].items()]
        lines += [
            "",
            "Certified that the grant has been utilised for the purpose for which it was sanctioned and that the conditions",
            "on which it was sanctioned have been fulfilled.",
            "",
            "Principal Investigator                 Finance Officer                 Head of the Institution",
        ]
        return f"UC {g['name']}", lines

    async def from_project(
        self,
        project_id: uuid.UUID,
        name: str,
        agency: str | None,
        sanctioned: int,
        pi_staff_id: uuid.UUID | None,
        heads: list[dict[str, Any]] | None,
    ) -> uuid.UUID | None:
        if (await self.db.execute(select(GrantLedger.id).where(GrantLedger.research_project_id == project_id))).first():
            return None
        g = GrantLedger(
            institution_id=self.inst,
            research_project_id=project_id,
            name=name[:160],
            funding_agency=agency,
            sanctioned_paise=sanctioned,
            budget_heads=[
                {"name": h.get("name"), "allocated_paise": int(h.get("allocated_paise", 0)), "utilised_paise": 0}
                for h in (heads or [])
            ]
            or [{"name": "contingency", "allocated_paise": sanctioned, "utilised_paise": 0}],
        )
        self.db.add(g)
        await self.db.flush()
        await self.put_meta(
            "grant", g.id, {"pi_staff_id": str(pi_staff_id) if pi_staff_id else None, "reallocation_allowed": True}
        )
        from app.models.research import ResearchProject

        project = (
            await self.db.execute(select(ResearchProject).where(ResearchProject.id == project_id).with_for_update())
        ).scalar_one_or_none()
        if project is not None:  # back-link (Prompts/30 §30.6 projects 1)
            project.grant_ledger_id = g.id
            await self.db.flush()
        return g.id
