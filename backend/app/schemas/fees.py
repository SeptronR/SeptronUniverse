"""Fee schemas — Prompts/12 §12.4. Money is always integer paise. Names carry a ``Fee`` prefix where a generic name
would collide with an existing OpenAPI schema (``StructureResponse`` / ``PaymentResult`` already exist)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.enums.fees import DiscountType, FineAppliesTo, FineCalcType, HeadType, PaymentMode
from app.schemas.common import ORMModel


# ---- heads ------------------------------------------------------------------------------------------------------------
class FeeHeadIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    head_type: HeadType = HeadType.TUITION
    is_refundable: bool = False
    is_taxable: bool = False
    gst_rate: float | None = Field(None, ge=0, le=28)
    ledger_account_id: uuid.UUID | None = None
    is_active: bool = True


class FeeHeadOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    head_type: str
    is_refundable: bool
    is_taxable: bool
    gst_rate: float | None = None
    ledger_account_id: uuid.UUID | None = None
    is_active: bool


class LedgerAccountOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    account_type: str
    parent_id: uuid.UUID | None = None


# ---- structures -------------------------------------------------------------------------------------------------------
class FeeStructureItemIn(BaseModel):
    fee_head_id: uuid.UUID
    amount_paise: int = Field(ge=0)
    instalment_no: int = Field(1, ge=1, le=12)
    due_date: date | None = None
    due_offset_days: int | None = Field(None, ge=0, le=365)
    is_optional: bool = False


class FeeStructureItemOut(ORMModel):
    id: uuid.UUID
    fee_head_id: uuid.UUID
    head_code: str | None = None
    head_name: str | None = None
    amount_paise: int
    instalment_no: int
    due_date: date | None = None
    due_offset_days: int | None = None
    is_optional: bool


class FeeStructureCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    college_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    program_regulation_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    term_number: int | None = Field(None, ge=1, le=20)
    category: str | None = Field(None, max_length=20)
    quota: str | None = Field(None, max_length=30)
    effective_from: date
    effective_to: date | None = None
    per_credit_paise: int | None = Field(None, ge=0)
    items: list[FeeStructureItemIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dates(self) -> "FeeStructureCreate":
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to precedes effective_from")
        return self


class FeeStructureUpdate(BaseModel):
    name: str | None = Field(None, max_length=160)
    effective_to: date | None = None
    per_credit_paise: int | None = Field(None, ge=0)
    status: Literal["active", "draft", "archived"] | None = None
    items: list[FeeStructureItemIn] | None = None
    version: int | None = None


class FeeStructureResponse(ORMModel):
    id: uuid.UUID
    name: str
    college_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    program_regulation_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    term_number: int | None = None
    category: str | None = None
    quota: str | None = None
    effective_from: date
    effective_to: date | None = None
    total_paise: int
    per_credit_paise: int | None = None
    status: str
    version: int
    items: list[FeeStructureItemOut] = Field(default_factory=list)
    assigned_count: int = 0


class StructureCloneRequest(BaseModel):
    effective_from: date
    effective_to: date | None = None
    academic_year_id: uuid.UUID | None = None
    name: str | None = None
    increase_pct: float = Field(0, ge=-50, le=100)


class ApplicableStructureResponse(BaseModel):
    structure: FeeStructureResponse | None = None
    matched_on: list[str] = Field(default_factory=list)
    candidates: int = 0


class FeeAssignRequest(BaseModel):
    enrollment_ids: list[uuid.UUID] | None = None
    batch_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    generate_invoices: bool = True
    dry_run: bool = False


class FeeAssignResult(BaseModel):
    assigned: int = 0
    already: int = 0
    invoices_created: int = 0
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    dry_run: bool = False


class BulkInvoiceRequest(BaseModel):
    batch_id: uuid.UUID
    term_id: uuid.UUID | None = None
    dry_run: bool = False


# ---- discounts / fines ------------------------------------------------------------------------------------------------
class DiscountIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    discount_type: DiscountType
    value: float = Field(gt=0)
    applies_to_heads: list[str] | None = None
    eligibility_rules: dict[str, Any] | None = None
    requires_approval: bool = True
    max_per_year: int | None = Field(None, ge=1)
    is_active: bool = True


class DiscountOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    discount_type: str
    value: float
    applies_to_heads: list[str] | None = None
    eligibility_rules: dict[str, Any] | None = None
    requires_approval: bool
    max_per_year: int | None = None
    is_active: bool


class DiscountAssign(BaseModel):
    enrollment_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=1000)
    academic_year_id: uuid.UUID | None = None


class DiscountAssignmentOut(ORMModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    discount_id: uuid.UUID
    discount_code: str | None = None
    discount_name: str | None = None
    academic_year_id: uuid.UUID | None = None
    reason: str | None = None
    status: str
    approved_by: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    created_at: datetime


class FineConfigIn(BaseModel):
    id: uuid.UUID | None = None
    applies_to: FineAppliesTo
    calc_type: FineCalcType
    amount_paise: int | None = Field(None, ge=0)
    grace_days: int = Field(0, ge=0, le=365)
    max_paise: int | None = Field(None, ge=0)
    slabs: list[dict[str, Any]] | None = None
    is_active: bool = True


class FineConfigOut(ORMModel):
    id: uuid.UUID
    applies_to: str
    calc_type: str
    amount_paise: int | None = None
    grace_days: int
    max_paise: int | None = None
    slabs: list[dict[str, Any]] | None = None
    is_active: bool


# ---- invoices ---------------------------------------------------------------------------------------------------------
class InvoiceItemIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)
    amount_paise: int
    fee_head_id: uuid.UUID | None = None
    head_code: str | None = None
    instalment_no: int | None = None
    due_date: date | None = None


class InvoiceCreate(BaseModel):
    """Internal linkage API (``invoice_service.create_invoice``) — also the ``/_dev/fees/link`` body."""

    payer_type: str = "student"
    payer_id: uuid.UUID | None = None
    enrollment_id: uuid.UUID | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    description: str | None = None
    items: list[InvoiceItemIn] = Field(default_factory=list)
    due_date: date | None = None
    term_id: uuid.UUID | None = None
    allow_multiple: bool = False


class FeeLinkRequest(BaseModel):
    source_type: str
    source_id: uuid.UUID
    amount_paise: int = Field(gt=0)
    enrollment_id: uuid.UUID | None = None
    description: str | None = None


class InvoiceItemOut(ORMModel):
    id: uuid.UUID
    fee_head_id: uuid.UUID | None = None
    description: str
    amount_paise: int
    tax_paise: int
    instalment_no: int | None = None
    due_date: date | None = None


class FeePaymentOut(ORMModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_number: str | None = None
    receipt_number: str
    amount_paise: int
    payment_date: date
    payment_mode: str
    gateway: str | None = None
    gateway_order_id: str | None = None
    reference_no: str | None = None
    utr: str | None = None
    bank_name: str | None = None
    status: str
    counter: str | None = None
    collected_by: uuid.UUID | None = None
    receipt_url: str | None = None
    cancel_reason: str | None = None
    cancel_workflow_instance_id: uuid.UUID | None = None
    payer_name: str | None = None
    created_at: datetime


class InvoiceResponse(ORMModel):
    id: uuid.UUID
    invoice_number: str
    payer_type: str
    payer_id: uuid.UUID
    payer_name: str | None = None
    registration_number: str | None = None
    student_program_enrollment_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    source_link: str | None = None
    description: str | None = None
    total_paise: int
    discount_paise: int
    tax_paise: int
    fine_paise: int
    paid_paise: int
    balance_paise: int
    due_date: date | None = None
    status: str
    gst_number: str | None = None
    created_at: datetime
    cancelled_reason: str | None = None
    items: list[InvoiceItemOut] = Field(default_factory=list)
    payments: list[FeePaymentOut] = Field(default_factory=list)


class DuesResponse(BaseModel):
    invoices: list[InvoiceResponse] = Field(default_factory=list)
    total_due: int = 0
    overdue: int = 0
    next_due: date | None = None
    student_name: str | None = None
    enrollment_id: uuid.UUID | None = None


class InvoiceCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


# ---- collection -------------------------------------------------------------------------------------------------------
class AllocationIn(BaseModel):
    invoice_id: uuid.UUID
    amount_paise: int = Field(gt=0)


class ChequeIn(BaseModel):
    no: str = Field(min_length=1, max_length=40)
    date: date
    bank: str = Field(min_length=1, max_length=100)


class CollectRequest(BaseModel):
    invoice_id: uuid.UUID | None = None
    allocation: list[AllocationIn] | None = None
    amount_paise: int = Field(gt=0)
    mode: PaymentMode
    reference: str | None = Field(None, max_length=80)
    utr: str | None = Field(None, max_length=40)
    bank: str | None = Field(None, max_length=100)
    cheque: ChequeIn | None = None
    counter: str | None = Field(None, max_length=40)
    allow_advance: bool = False

    @model_validator(mode="after")
    def _target(self) -> "CollectRequest":
        if not self.invoice_id and not self.allocation:
            raise ValueError("invoice_id or allocation is required")
        if self.mode in (PaymentMode.CHEQUE, PaymentMode.DD) and not (self.cheque or self.reference):
            raise ValueError("cheque / DD details are required")
        return self


class ReceiptResponse(BaseModel):
    receipt_numbers: list[str] = Field(default_factory=list)
    payments: list[FeePaymentOut] = Field(default_factory=list)
    invoices: list[InvoiceResponse] = Field(default_factory=list)
    amount_paise: int = 0


class ThermalReceipt(BaseModel):
    receipt_number: str
    width: int = 32
    commands: list[dict[str, Any]] = Field(default_factory=list)
    text: str = ""


class OnlineInitiateRequest(BaseModel):
    invoice_ids: list[uuid.UUID] = Field(min_length=1)
    amount_paise: int | None = Field(None, gt=0)
    gateway: str | None = None


class OnlineInitiateResponse(BaseModel):
    order_id: str
    gateway: str
    key: str | None = None
    amount: int
    checkout: dict[str, Any] = Field(default_factory=dict)
    payment_ids: list[uuid.UUID] = Field(default_factory=list)


class OnlineVerifyRequest(BaseModel):
    order_id: str
    payment_id: str
    signature: str


class OrderStatusResponse(BaseModel):
    order_id: str
    status: str
    amount_paise: int
    receipt_numbers: list[str] = Field(default_factory=list)


class UpiQrRequest(BaseModel):
    invoice_id: uuid.UUID
    amount_paise: int | None = Field(None, gt=0)


class UpiQrResponse(BaseModel):
    qr_png: str | None = None
    upi_uri: str
    vpa: str
    amount: int
    ref: str
    status: str = "pending"


class OfflineDeclare(BaseModel):
    invoice_id: uuid.UUID
    amount_paise: int = Field(gt=0)
    mode: Literal["neft", "challan", "dd", "cheque"]
    utr: str = Field(min_length=3, max_length=40)
    bank: str | None = Field(None, max_length=100)
    paid_on: date | None = None


class CancelReceiptRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class BounceRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    bank_charges_paise: int = Field(0, ge=0)


class ReconcileRowIn(BaseModel):
    utr: str | None = None
    amount_paise: int
    statement_date: date | None = None
    payer_hint: str | None = None
    bank_account: str | None = None


class ReconcileUpload(BaseModel):
    file_url: str | None = None
    rows: list[ReconcileRowIn] | None = None
    dry_run: bool = False


class ReconcileRowOut(ORMModel):
    id: uuid.UUID
    statement_date: date | None = None
    utr: str | None = None
    amount_paise: int | None = None
    payer_hint: str | None = None
    bank_account: str | None = None
    status: str
    matched_payment_id: uuid.UUID | None = None
    proposed_payment_id: uuid.UUID | None = None
    proposed_receipt: str | None = None
    created_at: datetime


class ReconcileMatch(BaseModel):
    payment_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None


class ReconcileSummary(BaseModel):
    rows: int = 0
    auto_matched: int = 0
    unmatched: int = 0
    dry_run: bool = False


# ---- refunds / day-book -----------------------------------------------------------------------------------------------
class RefundCreate(BaseModel):
    invoice_id: uuid.UUID | None = None
    payment_id: uuid.UUID | None = None
    amount_paise: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=2000)


class RefundDecision(BaseModel):
    comment: str | None = Field(None, max_length=1000)


class RefundProcess(BaseModel):
    refund_mode: Literal["neft", "cheque", "cash", "upi", "gateway", "adjustment"]
    reference_no: str = Field(min_length=1, max_length=80)


class RefundResponse(ORMModel):
    id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    invoice_number: str | None = None
    payment_id: uuid.UUID | None = None
    payer_type: str
    payer_id: uuid.UUID
    payer_name: str | None = None
    amount_paise: int
    reason: str
    refund_mode: str | None = None
    reference_no: str | None = None
    status: str
    workflow_instance_id: uuid.UUID | None = None
    processed_at: datetime | None = None
    created_at: datetime
    can_act: bool = False


class DayBookRow(BaseModel):
    id: uuid.UUID | None = None
    entry_date: date
    counter: str | None = None
    collected_by: uuid.UUID | None = None
    collector_name: str | None = None
    cash_paise: int = 0
    digital_paise: int = 0
    cheque_paise: int = 0
    deposited_paise: int = 0
    status: str = "open"
    receipts: int = 0


class DayBookResponse(BaseModel):
    date: date
    rows: list[DayBookRow] = Field(default_factory=list)
    by_mode: dict[str, int] = Field(default_factory=dict)
    total_paise: int = 0


class DayBookClose(BaseModel):
    date: date
    counter: str | None = None
    deposited_paise: int | None = Field(None, ge=0)
    remarks: str | None = None


# ---- reports ----------------------------------------------------------------------------------------------------------
class FeeReportRow(BaseModel):
    key: str
    label: str | None = None
    count: int = 0
    amount_paise: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


class FeeReport(BaseModel):
    report: str
    rows: list[FeeReportRow] = Field(default_factory=list)
    total_paise: int = 0


class AccountingExportRequest(BaseModel):
    date_from: date
    date_to: date
    format: Literal["tally_xml", "csv"] = "tally_xml"


class FeeDashboard(BaseModel):
    today_by_mode: dict[str, int] = Field(default_factory=dict)
    today_total: int = 0
    dues_total: int = 0
    overdue_total: int = 0
    overdue_count: int = 0
    reconcile_pending: int = 0
    refunds_pending: int = 0
    cancel_pending: int = 0
    online_initiated: int = 0
