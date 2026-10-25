"""Manual income & expense records — Prompts/23 §23.6 ``records_service``.

Income (donations in kind, interest, rentals, misc) is recorded directly by ``accounting:post`` holders and reversed with a
negated row. Expenses: ``recorded`` → ``submit`` → up to ``accounting.expense_approval_threshold_paise`` an
``accounting:approve`` holder decides directly; above it the ``accounting.expense`` workflow runs (accountant →
vice-chancellor / principal) → ``approved`` (budget utilisation applied, threshold alerts) → ``paid`` with a reference.
Rules: open period only (``PERIOD_CLOSED``), an attachment above ``accounting.document_required_paise``, budget heads
must be ``approved`` and have room (409 ``BUDGET_EXCEEDED`` with ``accounting.budget_hard_stop``, else a warning).
Automatic postings (``payee='[<source>]'``) are read-only here.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.accounting import BudgetHead, ExpenseRecord, IncomeRecord
from app.models.fees import LedgerAccount
from app.models.platform import Department, WorkflowInstance
from app.schemas.accounting import (
    AcctReverse,
    ExpenseDecision,
    ExpensePay,
    ExpenseRecordIn,
    ExpenseRecordOut,
    ExpenseRecordUpdate,
    IncomeRecordIn,
    IncomeRecordOut,
    IncomeRecordUpdate,
)
from app.services.accounting.common import ACC, AccountingBase, pairs, rule, unit_predicate
from app.services.students.common import snap

EKEYS = ("amount_paise", "status", "budget_head_id", "ledger_account_id", "department_id")


def expense_predicate(p: Any) -> Any:
    return unit_predicate(p, ExpenseRecord.department_id, ExpenseRecord.college_id, ExpenseRecord.recorded_by)


class RecordsService(AccountingBase):
    # ---- income ---------------------------------------------------------------------------------------------------------
    async def income_outs(self, rows: list[IncomeRecord]) -> list[IncomeRecordOut]:
        names = pairs(
            (
                await self.db.execute(
                    select(LedgerAccount.id, LedgerAccount.name).where(
                        LedgerAccount.id.in_({r.ledger_account_id for r in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        reversed_ids = {
            r.source_id
            for r in (
                await self.db.execute(
                    select(IncomeRecord).where(
                        IncomeRecord.source_type == "income_reversal",
                        IncomeRecord.source_id.in_([r.id for r in rows] or [uuid.uuid4()]),
                    )
                )
            ).scalars()
        }
        out = []
        for r in rows:
            o = IncomeRecordOut.model_validate(r, from_attributes=True)
            o.account = names.get(r.ledger_account_id)
            o.reversed = r.id in reversed_ids
            out.append(o)
        return out

    async def incomes(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        source_type: str | None = None,
        account_id: uuid.UUID | None = None,
    ) -> list[IncomeRecordOut]:
        self.require("view_all", "post")
        q = select(IncomeRecord).where(
            IncomeRecord.institution_id == self.inst,
            unit_predicate(self.principal, None, IncomeRecord.college_id, IncomeRecord.recorded_by),
        )
        if date_from:
            q = q.where(IncomeRecord.received_on >= date_from)
        if date_to:
            q = q.where(IncomeRecord.received_on <= date_to)
        if source_type:
            q = q.where(IncomeRecord.source_type == source_type)
        if account_id:
            q = q.where(IncomeRecord.ledger_account_id == account_id)
        return await self.income_outs(
            list((await self.db.execute(q.order_by(IncomeRecord.received_on.desc()).limit(3000))).scalars())
        )

    async def income_row(self, rid: uuid.UUID) -> IncomeRecord:
        r = (
            await self.db.execute(
                select(IncomeRecord).where(IncomeRecord.id == rid, IncomeRecord.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Income record not found")
        return r

    async def create_income(self, body: IncomeRecordIn) -> IncomeRecordOut:
        self.require("post")
        await self.check_open(body.received_on)
        await self.account_by_id(body.ledger_account_id)
        r = IncomeRecord(institution_id=self.inst, **body.model_dump(), recorded_by=self.actor_id)
        if r.source_type is None:
            r.source_type = "manual"
        self.db.add(r)
        await self.db.flush()
        await self._audit(
            "create", "income_record", r.id, None, snap(r, ("amount_paise", "ledger_account_id", "received_on"))
        )
        await self._emit(
            "accounting.income_recorded",
            {"income_id": str(r.id), "amount_paise": r.amount_paise},
            "income_record",
            r.id,
        )
        return (await self.income_outs([r]))[0]

    async def update_income(self, rid: uuid.UUID, body: IncomeRecordUpdate) -> IncomeRecordOut:
        self.require("post")
        r = await self.income_row(rid)
        if r.source_type not in (None, "manual"):
            raise rule("Automatic postings cannot be edited — reverse the source document", "AUTO_POSTING")
        await self.check_open(r.received_on)
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(r, k, v)
        await self.db.flush()
        return (await self.income_outs([r]))[0]

    async def reverse_income(self, rid: uuid.UUID, body: AcctReverse) -> IncomeRecordOut:
        self.require("post")
        r = await self.income_row(rid)
        if (
            await self.db.execute(
                select(IncomeRecord.id).where(
                    IncomeRecord.source_type == "income_reversal", IncomeRecord.source_id == r.id
                )
            )
        ).first():
            raise rule("Already reversed", "ALREADY_REVERSED")
        rev = IncomeRecord(
            institution_id=self.inst,
            college_id=r.college_id,
            ledger_account_id=r.ledger_account_id,
            amount_paise=-int(r.amount_paise),
            received_on=await self.today(),
            source_type="income_reversal",
            source_id=r.id,
            description=f"Reversal: {body.reason}"[:255],
            reference_no=r.reference_no,
            payment_mode=r.payment_mode,
            recorded_by=self.actor_id,
        )
        self.db.add(rev)
        await self.db.flush()
        await self._audit("reverse", "income_record", r.id, None, {"reason": body.reason, "reversal_id": str(rev.id)})
        return (await self.income_outs([rev]))[0]

    # ---- expenses ---------------------------------------------------------------------------------------------------------
    async def expense_outs(self, rows: list[ExpenseRecord]) -> list[ExpenseRecordOut]:
        accts = pairs(
            (
                await self.db.execute(
                    select(LedgerAccount.id, LedgerAccount.name).where(
                        LedgerAccount.id.in_({r.ledger_account_id for r in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        heads = pairs(
            (
                await self.db.execute(
                    select(BudgetHead.id, BudgetHead.name).where(
                        BudgetHead.id.in_({r.budget_head_id for r in rows if r.budget_head_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        depts = pairs(
            (
                await self.db.execute(
                    select(Department.id, Department.code).where(
                        Department.id.in_({r.department_id for r in rows if r.department_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        out = []
        for r in rows:
            o = ExpenseRecordOut.model_validate(r, from_attributes=True)
            o.account = accts.get(r.ledger_account_id)
            o.budget_head = heads.get(r.budget_head_id) if r.budget_head_id else None
            o.department_code = depts.get(r.department_id) if r.department_id else None
            o.source_type = (r.payee or "")[1:-1] if (r.payee or "").startswith("[") else "manual"
            out.append(o)
        return out

    async def expenses(
        self,
        department_id: uuid.UUID | None = None,
        status: str | None = None,
        budget_head_id: uuid.UUID | None = None,
        scope: str | None = None,
        manual_only: bool = False,
    ) -> list[ExpenseRecordOut]:
        q = select(ExpenseRecord).where(ExpenseRecord.institution_id == self.inst)
        if scope == "self":
            q = q.where(ExpenseRecord.recorded_by == self.actor_id)
        elif scope == "department":
            from app.services.accounting.common import dept_ids

            q = q.where(ExpenseRecord.department_id.in_(dept_ids(self.principal)))
        else:
            q = q.where(expense_predicate(self.principal))
        if department_id:
            q = q.where(ExpenseRecord.department_id == department_id)
        if status:
            q = q.where(ExpenseRecord.status == status)
        if budget_head_id:
            q = q.where(ExpenseRecord.budget_head_id == budget_head_id)
        if manual_only:
            q = q.where(~ExpenseRecord.payee.like("[%]"))
        return await self.expense_outs(
            list((await self.db.execute(q.order_by(ExpenseRecord.spent_on.desc()).limit(3000))).scalars())
        )

    async def expense_row(self, rid: uuid.UUID, *, for_update: bool = False) -> ExpenseRecord:
        q = select(ExpenseRecord).where(
            ExpenseRecord.id == rid, ExpenseRecord.institution_id == self.inst, expense_predicate(self.principal)
        )
        if for_update:
            q = q.with_for_update()
        r = (await self.db.execute(q)).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Expense not found")
        return r

    async def get_expense(self, rid: uuid.UUID) -> ExpenseRecordOut:
        return (await self.expense_outs([await self.expense_row(rid)]))[0]

    async def _budget_room(self, head_id: uuid.UUID, amount: int, *, exclude: int = 0) -> tuple[BudgetHead, str | None]:
        from app.services.accounting.budget_service import BudgetService

        return await BudgetService(self.db, self.principal, self.request, self.inst).room(
            head_id, amount, exclude=exclude
        )

    async def create_expense(self, body: ExpenseRecordIn) -> ExpenseRecordOut:
        self.require("post")
        await self.check_open(body.spent_on)
        await self.account_by_id(body.ledger_account_id)
        need_doc = int(await self.setting("accounting", "document_required_paise") or 1000000)
        if body.amount_paise > need_doc and not body.document_url:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Attach the bill / voucher for expenses of this size",
                {"field": "document_url"},
            )
        warning = None
        dept = body.department_id
        college = body.college_id
        if body.budget_head_id:
            head, warning = await self._budget_room(body.budget_head_id, body.amount_paise)
            dept = dept or head.department_id
            college = college or head.college_id
        if dept is None and not self.can(ACC, "view_all"):
            from app.services.accounting.common import _ids

            depts = _ids(self.principal, "department")
            dept = depts[0] if depts else None
        r = ExpenseRecord(
            institution_id=self.inst,
            college_id=college,
            department_id=dept,
            ledger_account_id=body.ledger_account_id,
            budget_head_id=body.budget_head_id,
            amount_paise=body.amount_paise,
            spent_on=body.spent_on,
            payee=body.payee,
            description=body.description,
            reference_no=body.reference_no,
            vendor_bill_id=body.vendor_bill_id,
            document_url=body.document_url,
            status="recorded",
            recorded_by=self.actor_id,
        )
        self.db.add(r)
        await self.db.flush()
        if body.gst_input_paise:
            await self.put_meta("expense_gst", r.id, {"input_paise": body.gst_input_paise})
        await self._audit("create", "expense_record", r.id, None, snap(r, EKEYS))
        await self._emit(
            "accounting.expense_recorded",
            {"expense_id": str(r.id), "amount_paise": r.amount_paise},
            "expense_record",
            r.id,
        )
        out = (await self.expense_outs([r]))[0]
        out.warning = warning
        return out

    async def update_expense(self, rid: uuid.UUID, body: ExpenseRecordUpdate) -> ExpenseRecordOut:
        r = await self.expense_row(rid, for_update=True)
        if r.status != "recorded" or (r.payee or "").startswith("["):
            raise rule("Only a recorded manual expense can be edited", "NOT_EDITABLE")
        if r.recorded_by != self.actor_id and not self.can(ACC, "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the recorder edits an expense")
        data = body.model_dump(exclude_unset=True)
        if data.get("budget_head_id"):
            await self._budget_room(data["budget_head_id"], r.amount_paise)
        for k, v in data.items():
            setattr(r, k, v)
        await self.db.flush()
        return (await self.expense_outs([r]))[0]

    async def submit(self, rid: uuid.UUID) -> ExpenseRecordOut:
        r = await self.expense_row(rid, for_update=True)
        if r.status != "recorded":
            raise rule("Only a recorded expense can be submitted", "NOT_RECORDED")
        if r.budget_head_id:
            await self._budget_room(r.budget_head_id, r.amount_paise)
        r.status = "submitted"
        if r.amount_paise > int(await self.setting("accounting", "expense_approval_threshold_paise") or 5000000):
            inst = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="accounting.expense",
                entity_type="expense_record",
                entity_id=r.id,
                started_by=self.actor_id,
                context={
                    "amount_paise": r.amount_paise,
                    "department_id": str(r.department_id) if r.department_id else None,
                },
                title=f"Expense ₹{r.amount_paise / 100:,.0f} · {r.payee}",
            )
            r.workflow_instance_id = inst.id
        await self.db.flush()
        await self._audit("submit", "expense_record", r.id, None, snap(r, EKEYS))
        return (await self.expense_outs([r]))[0]

    async def decide(self, rid: uuid.UUID, body: ExpenseDecision, *, via_workflow: bool = False) -> ExpenseRecordOut:
        if not via_workflow:
            self.require("approve")
        r = (
            await self.expense_row(rid, for_update=True)
            if not via_workflow
            else (
                await self.db.execute(select(ExpenseRecord).where(ExpenseRecord.id == rid).with_for_update())
            ).scalar_one()
        )
        if r.status != "submitted":
            raise rule("The expense is not awaiting a decision", "NOT_SUBMITTED")
        if r.workflow_instance_id and not via_workflow:
            raise rule("This expense is above the threshold — decide it in the workflow inbox", "WORKFLOW_REQUIRED")
        if body.action == "reject":
            r.status = "rejected"
            event = "accounting.expense_rejected"
        else:
            if r.budget_head_id:
                from app.services.accounting.budget_service import BudgetService

                await BudgetService(self.db, self.principal, self.request, self.inst).utilise(
                    r.budget_head_id, r.amount_paise
                )
            r.status, r.approved_by = "approved", self.actor_id
            event = "accounting.expense_approved"
        await self.db.flush()
        await self._audit(body.action, "expense_record", r.id, None, snap(r, EKEYS) | {"remarks": body.remarks})
        await self._emit(event, {"expense_id": str(r.id), "amount_paise": r.amount_paise}, "expense_record", r.id)
        await self._notify(
            "accounting.expense_status",
            [r.recorded_by],
            {"amount": f"{r.amount_paise / 100:,.2f}", "status": r.status, "payee": r.payee or ""},
        )
        return (await self.expense_outs([r]))[0]

    async def pay(self, rid: uuid.UUID, body: ExpensePay) -> ExpenseRecordOut:
        self.require("post", "approve")
        r = await self.expense_row(rid, for_update=True)
        if r.status != "approved":
            raise rule("Only an approved expense can be paid", "NOT_APPROVED")
        await self.check_open(body.paid_on)
        r.status = "paid"
        r.reference_no = (body.reference or r.reference_no or "")[:80]
        await self.put_meta(
            "expense_payment",
            r.id,
            {"paid_on": body.paid_on.isoformat(), "mode": body.mode, "reference": body.reference},
        )
        await self.db.flush()
        await self._audit(
            "pay",
            "expense_record",
            r.id,
            None,
            {"paid_on": body.paid_on.isoformat(), "mode": body.mode, "reference": body.reference},
        )
        await self._emit(
            "accounting.expense_paid", {"expense_id": str(r.id), "amount_paise": r.amount_paise}, "expense_record", r.id
        )
        await self._notify(
            "accounting.expense_status",
            [r.recorded_by],
            {"amount": f"{r.amount_paise / 100:,.2f}", "status": "paid", "payee": r.payee or ""},
        )
        return (await self.expense_outs([r]))[0]


@workflow_engine.on("accounting.expense", "approved")
async def _expense_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await RecordsService(db, actor, institution_id=instance.institution_id).decide(
        instance.entity_id, ExpenseDecision(action="approve"), via_workflow=True
    )


@workflow_engine.on("accounting.expense", "rejected")
async def _expense_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await RecordsService(db, actor, institution_id=instance.institution_id).decide(
        instance.entity_id, ExpenseDecision(action="reject"), via_workflow=True
    )
