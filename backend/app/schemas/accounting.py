"""Accounting & budget schemas — Prompts/23 §23.4 (OpenAPI names prefixed ``Acct`` / ``Budget`` / ``Grant`` where a
generic name could collide)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


AccountTypeLit = Literal["income", "expense", "asset", "liability", "equity"]


class AcctAccountIn(_Strict):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    account_type: AccountTypeLit | None = None
    parent_id: uuid.UUID | None = None
    external_ref: str | None = Field(None, max_length=60)


class AcctAccountUpdate(_Strict):
    name: str | None = Field(None, min_length=2, max_length=120)
    external_ref: str | None = Field(None, max_length=60)
    is_active: bool | None = None
    parent_id: uuid.UUID | None = None


class AcctAccountOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    account_type: str
    parent_id: uuid.UUID | None = None
    external_ref: str | None = None
    is_active: bool
    debit_paise: int = 0
    credit_paise: int = 0
    balance_paise: int = 0
    children: list["AcctAccountOut"] = []


class ChartImport(_Strict):
    template: Literal["IN"] | None = "IN"
    csv: str | None = Field(None, max_length=500_000, description="code,name,type,parent_code")


class AcctMappings(_Strict):
    mappings: dict[str, Any]


class LedgerLine(BaseModel):
    id: uuid.UUID
    kind: Literal["income", "expense"]
    on: date
    amount_paise: int
    debit_paise: int
    credit_paise: int
    balance_paise: int = 0
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    description: str | None = None
    reference_no: str | None = None


class TrialBalanceRow(BaseModel):
    account_id: uuid.UUID | None = None
    code: str
    name: str
    account_type: str
    debit_paise: int
    credit_paise: int


class TrialBalanceOut(BaseModel):
    period_from: date
    period_to: date
    rows: list[TrialBalanceRow]
    total_debit_paise: int
    total_credit_paise: int
    balanced: bool


# ---- records ---------------------------------------------------------------------------------------------------------------
class IncomeRecordIn(_Strict):
    ledger_account_id: uuid.UUID
    college_id: uuid.UUID | None = None
    amount_paise: int = Field(gt=0)
    received_on: date
    source_type: str | None = Field(None, max_length=40)
    source_id: uuid.UUID | None = None
    description: str = Field(min_length=2, max_length=255)
    reference_no: str | None = Field(None, max_length=80)
    payment_mode: Literal["cash", "bank", "cheque", "upi", "neft", "in_kind"] | None = "bank"


class IncomeRecordUpdate(_Strict):
    description: str | None = Field(None, min_length=2, max_length=255)
    reference_no: str | None = Field(None, max_length=80)


class IncomeRecordOut(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    ledger_account_id: uuid.UUID
    account: str | None = None
    amount_paise: int
    received_on: date
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    description: str | None = None
    reference_no: str | None = None
    payment_mode: str | None = None
    recorded_by: uuid.UUID | None = None
    reversed: bool = False


class AcctReverse(_Strict):
    reason: str = Field(min_length=3, max_length=500)


class ExpenseRecordIn(_Strict):
    ledger_account_id: uuid.UUID
    budget_head_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    amount_paise: int = Field(gt=0)
    spent_on: date
    payee: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=2, max_length=255)
    reference_no: str | None = Field(None, max_length=80)
    vendor_bill_id: uuid.UUID | None = None
    document_url: str | None = None
    gst_input_paise: int | None = Field(None, ge=0)


class ExpenseRecordUpdate(_Strict):
    payee: str | None = Field(None, min_length=2, max_length=200)
    description: str | None = Field(None, min_length=2, max_length=255)
    reference_no: str | None = Field(None, max_length=80)
    document_url: str | None = None
    budget_head_id: uuid.UUID | None = None


class ExpenseRecordOut(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    department_code: str | None = None
    ledger_account_id: uuid.UUID
    account: str | None = None
    budget_head_id: uuid.UUID | None = None
    budget_head: str | None = None
    amount_paise: int
    spent_on: date
    payee: str | None = None
    description: str | None = None
    reference_no: str | None = None
    vendor_bill_id: uuid.UUID | None = None
    document_url: str | None = None
    status: str
    workflow_instance_id: uuid.UUID | None = None
    source_type: str | None = None
    warning: str | None = None


class ExpenseDecision(_Strict):
    action: Literal["approve", "reject"]
    remarks: str | None = Field(None, max_length=1000)


class ExpensePay(_Strict):
    paid_on: date
    mode: Literal["cash", "bank", "cheque", "upi", "neft"] = "neft"
    reference: str = Field(min_length=2, max_length=80)


# ---- budgets ---------------------------------------------------------------------------------------------------------------
class BudgetHeadIn(_Strict):
    academic_year_id: uuid.UUID
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=120)
    ledger_account_id: uuid.UUID | None = None
    allocated_paise: int = Field(ge=0)


class BudgetHeadUpdate(_Strict):
    name: str | None = Field(None, min_length=2, max_length=120)
    ledger_account_id: uuid.UUID | None = None


class BudgetHeadOut(BaseModel):
    id: uuid.UUID
    academic_year_id: uuid.UUID
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    department_code: str | None = None
    name: str
    ledger_account_id: uuid.UUID | None = None
    allocated_paise: int
    utilised_paise: int
    committed_paise: int
    available_paise: int
    pct: float
    status: str


class BudgetBulkAllocate(_Strict):
    academic_year_id: uuid.UUID
    rows: list[BudgetHeadIn] = Field(min_length=1, max_length=500)


class BudgetRevise(_Strict):
    allocated_paise: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)


class BudgetTransfer(_Strict):
    from_head_id: uuid.UUID
    to_head_id: uuid.UUID
    amount_paise: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=500)


class BudgetCommit(_Strict):
    budget_head_id: uuid.UUID
    amount_paise: int
    source_type: str
    source_id: uuid.UUID


# ---- grants -----------------------------------------------------------------------------------------------------------------
class GrantHeadIn(_Strict):
    name: str = Field(min_length=2, max_length=60)
    allocated_paise: int = Field(ge=0)


class GrantLedgerIn(_Strict):
    research_project_id: uuid.UUID | None = None
    pi_staff_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=160)
    funding_agency: str | None = Field(None, max_length=160)
    sanctioned_paise: int = Field(gt=0)
    budget_heads: list[GrantHeadIn] = Field(min_length=1, max_length=20)
    reallocation_allowed: bool = True


class GrantLedgerOut(BaseModel):
    id: uuid.UUID
    research_project_id: uuid.UUID | None = None
    pi_staff_id: uuid.UUID | None = None
    pi_name: str | None = None
    name: str
    funding_agency: str | None = None
    sanctioned_paise: int
    received_paise: int
    utilised_paise: int
    balance_paise: int
    budget_heads: list[dict[str, Any]]
    status: str


class GrantReceipt(_Strict):
    amount_paise: int = Field(gt=0)
    received_on: date
    reference: str | None = Field(None, max_length=80)


class GrantExpense(_Strict):
    head: str = Field(min_length=2, max_length=60)
    amount_paise: int = Field(gt=0)
    spent_on: date
    description: str = Field(min_length=2, max_length=255)
    payee: str | None = Field(None, max_length=200)
    document_url: str | None = None


class GrantReallocate(_Strict):
    from_head: str
    to_head: str
    amount_paise: int = Field(gt=0)
    remark: str = Field(min_length=3, max_length=500)


class GrantClose(_Strict):
    remark: str | None = Field(None, max_length=500)


# ---- reconciliation ---------------------------------------------------------------------------------------------------------
class StatementRow(_Strict):
    date: date
    description: str = Field(max_length=255)
    reference: str | None = Field(None, max_length=80)
    amount_paise: int = Field(description="+ credit (money in), − debit (money out)")


class ReconciliationCreate(_Strict):
    bank_account: str = Field(min_length=2, max_length=60)
    statement_date: date
    statement_balance_paise: int
    statement_rows: list[StatementRow] = []


class ReconItem(BaseModel):
    id: str
    row: dict[str, Any]
    status: str
    matched_type: str | None = None
    matched_id: uuid.UUID | None = None
    remark: str | None = None


class ReconciliationOut(BaseModel):
    id: uuid.UUID
    bank_account: str
    statement_date: date
    statement_balance_paise: int
    ledger_balance_paise: int
    difference_paise: int
    items: list[ReconItem]
    status: str
    matched: int = 0
    unmatched: int = 0


class ReconImport(_Strict):
    csv: str = Field(
        min_length=5, max_length=2_000_000, description="date,description,reference,amount (rupees; negative = debit)"
    )


class ReconMatch(_Strict):
    item_id: str
    matched_type: Literal["fee_payment", "income", "expense"] | None = None
    matched_id: uuid.UUID | None = None
    unexplained_remark: str | None = Field(None, max_length=500)


class ReconAddRecord(_Strict):
    item_id: str
    kind: Literal["bank_charge", "interest"]
    ledger_account_id: uuid.UUID | None = None


# ---- GST / exports / statements --------------------------------------------------------------------------------------------
class GstReportOut(BaseModel):
    period: str
    output_tax: list[dict[str, Any]]
    input_tax: list[dict[str, Any]]
    output_total_paise: int
    input_total_paise: int
    net_paise: int


class ExportRequest(_Strict):
    target: Literal["tally", "zoho", "csv"] = "tally"
    period_from: date
    period_to: date
    voucher_types: list[Literal["receipt", "payment", "journal"]] = ["receipt", "payment"]
    include_exported: bool = False


class ExportOut(BaseModel):
    id: uuid.UUID
    target: str
    period_from: date
    period_to: date
    status: str
    job_id: uuid.UUID | None = None
    file_url: str | None = None
    created_at: datetime


class StatementOut(BaseModel):
    kind: str
    period_from: date
    period_to: date
    college_id: uuid.UUID | None = None
    sections: list[dict[str, Any]]
    totals: dict[str, int]


class PeriodClose(_Strict):
    upto_date: date


class YearClose(_Strict):
    academic_year_id: uuid.UUID
    carry_forward: Literal["none", "unspent"] = "none"


class AcctJobAccepted(BaseModel):
    job_id: uuid.UUID


class AcctDashboard(BaseModel):
    cash_paise: int
    bank_paise: int
    receivables_paise: int
    income_month_paise: int
    expense_month_paise: int
    pending_expenses: int
    budget_alerts: list[dict[str, Any]]
    open_reconciliations: int
    posting_gaps: int
