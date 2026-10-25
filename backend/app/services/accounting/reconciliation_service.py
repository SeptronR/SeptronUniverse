"""Bank reconciliation — Prompts/23 §23.6 ``reconciliation_service``.

A statement (rows: date, description, reference, signed amount — + money in) per bank account and date. Auto-match:
credits against ``fee_payments`` (UTR / reference / gateway id, else amount within ± 2 days) and income records,
debits against paid expenses (reference or amount ± 2 days). Unmatched rows are matched by hand, turned into new
records (bank charges → expense, interest → income) or marked *unexplained* with a remark. ``ledger_balance`` = Σ bank
postings up to the statement date (shown beside the statement balance); ``difference`` = Σ unmatched rows; ``close`` needs every row matched
or explained (409 ``UNRECONCILED``). Monthly Beat reminds the accountant about open reconciliations.
"""

import csv
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.accounting import BankReconciliation, ExpenseRecord, IncomeRecord
from app.models.fees import FeePayment
from app.schemas.accounting import (
    ReconAddRecord,
    ReconciliationCreate,
    ReconciliationOut,
    ReconItem,
    ReconMatch,
    StatementRow,
)
from app.services.accounting.common import AccountingBase, rule

WINDOW = timedelta(days=2)


class ReconciliationService(AccountingBase):
    def out(self, r: BankReconciliation) -> ReconciliationOut:
        items = [ReconItem(**i) for i in (r.items or [])]
        return ReconciliationOut(
            id=r.id,
            bank_account=r.bank_account,
            statement_date=r.statement_date,
            statement_balance_paise=int(r.statement_balance_paise),
            ledger_balance_paise=int(r.ledger_balance_paise),
            difference_paise=int(r.difference_paise),
            items=items,
            status=r.status,
            matched=sum(1 for i in items if i.status in ("matched", "explained")),
            unmatched=sum(1 for i in items if i.status == "unmatched"),
        )

    async def list_recons(self) -> list[ReconciliationOut]:
        self.require("reconcile", "view_all")
        rows = (
            await self.db.execute(
                select(BankReconciliation)
                .where(BankReconciliation.institution_id == self.inst)
                .order_by(BankReconciliation.statement_date.desc())
            )
        ).scalars()
        return [self.out(r) for r in rows]

    async def row(self, rid: uuid.UUID, *, for_update: bool = False) -> BankReconciliation:
        self.require("reconcile", "view_all")
        q = select(BankReconciliation).where(
            BankReconciliation.id == rid, BankReconciliation.institution_id == self.inst
        )
        if for_update:
            q = q.with_for_update()
        r = (await self.db.execute(q)).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Reconciliation not found")
        return r

    async def ledger_balance(self, upto: date) -> int:
        bank_ids = select(func.coalesce(func.sum(IncomeRecord.amount_paise), 0)).where(
            IncomeRecord.institution_id == self.inst,
            IncomeRecord.received_on <= upto,
            or_(IncomeRecord.payment_mode.is_(None), IncomeRecord.payment_mode != "cash"),
        )
        inc = int((await self.db.execute(bank_ids)).scalar_one())
        exp = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(ExpenseRecord.amount_paise), 0)).where(
                        ExpenseRecord.institution_id == self.inst,
                        ExpenseRecord.status == "paid",
                        ExpenseRecord.spent_on <= upto,
                    )
                )
            ).scalar_one()
        )
        return inc - exp

    def _recompute(self, r: BankReconciliation) -> None:
        unmatched = sum(int(i["row"]["amount_paise"]) for i in (r.items or []) if i["status"] == "unmatched")
        r.difference_paise = unmatched

    async def create(self, body: ReconciliationCreate) -> ReconciliationOut:
        self.require("reconcile")
        ledger = await self.ledger_balance(body.statement_date)
        r = BankReconciliation(
            institution_id=self.inst,
            bank_account=body.bank_account,
            statement_date=body.statement_date,
            statement_balance_paise=body.statement_balance_paise,
            ledger_balance_paise=ledger,
            difference_paise=0,
            items=[],
        )
        self.db.add(r)
        await self.db.flush()
        if body.statement_rows:
            await self._add_rows(r, body.statement_rows)
        await self._audit(
            "create",
            "bank_reconciliation",
            r.id,
            None,
            {"bank": r.bank_account, "date": r.statement_date.isoformat(), "rows": len(body.statement_rows)},
        )
        await self._emit(
            "accounting.reconciliation_opened", {"reconciliation_id": str(r.id)}, "bank_reconciliation", r.id
        )
        return self.out(r)

    async def _add_rows(self, r: BankReconciliation, rows: list[StatementRow]) -> None:
        items = list(r.items or [])
        used: set[str] = {str(i.get("matched_id")) for i in items if i.get("matched_id")}
        for row in rows:
            item: dict[str, Any] = {
                "id": uuid.uuid4().hex[:12],
                "row": row.model_dump(mode="json"),
                "status": "unmatched",
                "matched_type": None,
                "matched_id": None,
                "remark": None,
            }
            hit = await self._auto(row, used)
            if hit:
                item.update(status="matched", matched_type=hit[0], matched_id=str(hit[1]))
                used.add(str(hit[1]))
            items.append(item)
        r.items = items
        self._recompute(r)
        await self.db.flush()

    async def _auto(self, row: StatementRow, used: set[str]) -> tuple[str, uuid.UUID] | None:
        lo, hi = row.date - WINDOW, row.date + WINDOW
        ref = (row.reference or "").strip()
        if row.amount_paise > 0:
            q = select(FeePayment.id).where(FeePayment.institution_id == self.inst, FeePayment.status == "success")
            if ref:
                hit = (
                    (
                        await self.db.execute(
                            q.where(
                                or_(
                                    FeePayment.utr == ref,
                                    FeePayment.reference_no == ref,
                                    FeePayment.gateway_payment_id == ref,
                                )
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if hit and str(hit) not in used:
                    return "fee_payment", hit
            for pid in (
                await self.db.execute(
                    q.where(FeePayment.amount_paise == row.amount_paise, FeePayment.payment_date.between(lo, hi))
                )
            ).scalars():
                if str(pid) not in used:
                    return "fee_payment", pid
            for iid in (
                await self.db.execute(
                    select(IncomeRecord.id).where(
                        IncomeRecord.institution_id == self.inst,
                        IncomeRecord.amount_paise == row.amount_paise,
                        IncomeRecord.received_on.between(lo, hi),
                        IncomeRecord.source_type != "fee_payment",
                    )
                )
            ).scalars():
                if str(iid) not in used:
                    return "income", iid
        else:
            amt = -row.amount_paise
            q = select(ExpenseRecord.id).where(
                ExpenseRecord.institution_id == self.inst,
                ExpenseRecord.status == "paid",
                ExpenseRecord.amount_paise == amt,
            )
            if ref:
                hit = (await self.db.execute(q.where(ExpenseRecord.reference_no == ref))).scalars().first()
                if hit and str(hit) not in used:
                    return "expense", hit
            for eid in (await self.db.execute(q.where(ExpenseRecord.spent_on.between(lo, hi)))).scalars():
                if str(eid) not in used:
                    return "expense", eid
        return None

    async def import_csv(self, rid: uuid.UUID, csv_text: str) -> ReconciliationOut:
        r = await self.row(rid, for_update=True)
        if r.status != "open":
            raise rule("The reconciliation is closed", "RECON_CLOSED")
        rows = []
        for n, rec in enumerate(csv.DictReader(io.StringIO(csv_text)), start=2):
            try:
                rows.append(
                    StatementRow(
                        date=date.fromisoformat((rec.get("date") or "").strip()),
                        description=(rec.get("description") or "")[:255],
                        reference=(rec.get("reference") or "").strip() or None,
                        amount_paise=int(Decimal((rec.get("amount") or "0").replace(",", "")) * 100),
                    )
                )
            except (ValueError, ArithmeticError) as exc:
                raise APIError(422, ErrorCode.VALIDATION, f"Row {n}: {exc}") from exc
        await self._add_rows(r, rows)
        return self.out(r)

    async def match(self, rid: uuid.UUID, body: ReconMatch, *, unmatch: bool = False) -> ReconciliationOut:
        r = await self.row(rid, for_update=True)
        if r.status != "open":
            raise rule("The reconciliation is closed", "RECON_CLOSED")
        items = [dict(i) for i in (r.items or [])]
        it = next((i for i in items if i["id"] == body.item_id), None)
        if it is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Statement row not found")
        if unmatch:
            it.update(status="unmatched", matched_type=None, matched_id=None, remark=None)
        elif body.unexplained_remark:
            it.update(status="explained", remark=body.unexplained_remark)
        else:
            if not body.matched_type or not body.matched_id:
                raise APIError(422, ErrorCode.VALIDATION, "matched_type and matched_id are required")
            it.update(status="matched", matched_type=body.matched_type, matched_id=str(body.matched_id))
        r.items = items
        self._recompute(r)
        await self.db.flush()
        return self.out(r)

    async def add_record(self, rid: uuid.UUID, body: ReconAddRecord) -> ReconciliationOut:
        r = await self.row(rid, for_update=True)
        items = [dict(i) for i in (r.items or [])]
        it = next((i for i in items if i["id"] == body.item_id), None)
        if it is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Statement row not found")
        row = it["row"]
        on = date.fromisoformat(row["date"])
        if body.kind == "bank_charge":
            acct = (
                await self.account_by_id(body.ledger_account_id)
                if body.ledger_account_id
                else await self.account("bank_charges")
            )
            rec: Any = ExpenseRecord(
                institution_id=self.inst,
                ledger_account_id=acct.id,
                amount_paise=abs(int(row["amount_paise"])),
                spent_on=on,
                payee="Bank",
                description=f"Bank charges · {row['description']}"[:255],
                reference_no=row.get("reference"),
                status="paid",
                recorded_by=self.actor_id,
            )
            kind = "expense"
        else:
            acct = (
                await self.account_by_id(body.ledger_account_id)
                if body.ledger_account_id
                else await self.account("interest")
            )
            rec = IncomeRecord(
                institution_id=self.inst,
                ledger_account_id=acct.id,
                amount_paise=abs(int(row["amount_paise"])),
                received_on=on,
                source_type="bank_interest",
                description=f"Bank interest · {row['description']}"[:255],
                reference_no=row.get("reference"),
                payment_mode="bank",
                recorded_by=self.actor_id,
            )
            kind = "income"
        self.db.add(rec)
        await self.db.flush()
        it.update(status="matched", matched_type=kind, matched_id=str(rec.id))
        r.items = items
        self._recompute(r)
        await self.db.flush()
        return self.out(r)

    async def close(self, rid: uuid.UUID) -> ReconciliationOut:
        r = await self.row(rid, for_update=True)
        if any(i["status"] == "unmatched" for i in (r.items or [])):
            raise rule(
                "Match or explain every statement row before closing",
                "UNRECONCILED",
                difference_paise=int(r.difference_paise),
            )
        r.status, r.reconciled_by = "reconciled", self.actor_id
        await self.db.flush()
        await self._audit("close", "bank_reconciliation", r.id, None, {"difference_paise": int(r.difference_paise)})
        await self._emit(
            "accounting.reconciliation_reconciled", {"reconciliation_id": str(r.id)}, "bank_reconciliation", r.id
        )
        return self.out(r)

    async def reminder(self) -> int:
        n = (
            await self.db.execute(
                select(func.count())
                .select_from(BankReconciliation)
                .where(BankReconciliation.institution_id == self.inst, BankReconciliation.status == "open")
            )
        ).scalar_one()
        if n:
            await self._notify(
                "accounting.reconciliation_pending", [], {"count": int(n)}, audience={"roles": ["accountant"]}
            )
        return int(n)
