"""Inventory, procurement & bills schemas — Prompts/22 §22.4 (OpenAPI names prefixed ``Inv`` / ``Po`` / ``Asset`` where
a generic name could collide with another module)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- masters -------------------------------------------------------------------------------------------------------------
class BankDetailsIn(_Strict):
    account_no: str = Field(min_length=6, max_length=20)
    ifsc: str = Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    bank: str | None = Field(None, max_length=80)


class SupplierIn(_Strict):
    name: str = Field(min_length=2, max_length=200)
    code: str | None = Field(None, max_length=20)
    gstin: str | None = Field(None, pattern=r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
    pan: str | None = Field(None, pattern=r"^[A-Z]{5}\d{4}[A-Z]$")
    contact: dict[str, Any] | None = None
    address: dict[str, Any] | None = None
    categories: list[str] | None = None
    bank_details: BankDetailsIn | None = None
    supplier_type: Literal["individual", "company", "firm", "government"] | None = None


class SupplierUpdate(_Strict):
    contact: dict[str, Any] | None = None
    address: dict[str, Any] | None = None
    categories: list[str] | None = None
    bank_details: BankDetailsIn | None = None
    rating: float | None = Field(None, ge=0, le=5)
    gstin: str | None = Field(None, pattern=r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
    pan: str | None = Field(None, pattern=r"^[A-Z]{5}\d{4}[A-Z]$")


class SupplierOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str | None = None
    gstin: str | None = None
    pan: str | None = None
    contact: dict[str, Any] | None = None
    address: dict[str, Any] | None = None
    categories: list[Any] | None = None
    bank_details: dict[str, Any] | None = None  # masked unless inventory:view_pii
    rating: float | None = None
    status: str
    portal_user_id: uuid.UUID | None = None
    is_active: bool


class SupplierRegister(_Strict):
    institution: str = Field(min_length=2, max_length=80, description="institution slug")
    name: str = Field(min_length=2, max_length=200)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str | None = Field(None, max_length=20)
    gstin: str | None = Field(None, pattern=r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
    pan: str | None = Field(None, pattern=r"^[A-Z]{5}\d{4}[A-Z]$")
    categories: list[str] = []
    captcha_token: str | None = None


class SupplierAction(_Strict):
    reason: str | None = Field(None, max_length=1000)


class StoreIn(_Strict):
    name: str = Field(min_length=2, max_length=120)
    store_type: Literal["central", "department", "lab", "hostel"] = "central"
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    keeper_staff_id: uuid.UUID | None = None
    is_active: bool = True


class StoreOut(BaseModel):
    id: uuid.UUID
    name: str
    store_type: str
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    keeper_staff_id: uuid.UUID | None = None
    keeper_name: str | None = None
    is_active: bool
    items: int = 0
    below_min: int = 0
    value_paise: int = 0


class InvCategoryIn(_Strict):
    name: str = Field(min_length=2, max_length=100)
    parent_id: uuid.UUID | None = None
    is_consumable: bool = True


class InvCategoryOut(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    is_consumable: bool
    is_active: bool


class SafetyData(_Strict):
    hazard_class: str = Field(min_length=1, max_length=60)
    storage: str = Field(min_length=1, max_length=500)
    msds_url: str | None = Field(None, max_length=500)
    disposal: str | None = Field(None, max_length=500)
    expiry: date | None = None


class ItemIn(_Strict):
    category_id: uuid.UUID | None = None
    item_code: str | None = Field(None, max_length=30)
    name: str = Field(min_length=2, max_length=200)
    unit: str = Field("nos", min_length=1, max_length=20)
    description: str | None = None
    is_consumable: bool = True
    is_hazardous: bool = False
    safety_data: SafetyData | None = None
    min_stock_level: float | None = Field(None, ge=0)
    reorder_qty: float | None = Field(None, ge=0)
    unit_cost_paise: int | None = Field(None, ge=0)
    gst_rate: float | None = Field(None, ge=0, le=28)


class ItemUpdate(_Strict):
    category_id: uuid.UUID | None = None
    name: str | None = Field(None, min_length=2, max_length=200)
    unit: str | None = Field(None, max_length=20)
    description: str | None = None
    is_hazardous: bool | None = None
    safety_data: SafetyData | None = None
    min_stock_level: float | None = Field(None, ge=0)
    reorder_qty: float | None = Field(None, ge=0)
    gst_rate: float | None = Field(None, ge=0, le=28)
    is_active: bool | None = None
    version: int | None = None


class ItemOut(BaseModel):
    id: uuid.UUID
    category_id: uuid.UUID | None = None
    category: str | None = None
    item_code: str
    name: str
    unit: str
    description: str | None = None
    is_consumable: bool
    is_hazardous: bool
    safety_data: dict[str, Any] | None = None
    min_stock_level: float | None = None
    reorder_qty: float | None = None
    unit_cost_paise: int | None = None  # hidden without inventory:view_all|manage
    gst_rate: float | None = None
    is_active: bool
    version: int
    on_hand: float = 0


class ItemImport(_Strict):
    csv: str = Field(min_length=10, max_length=2_000_000)


class StockLevelOut(BaseModel):
    store_id: uuid.UUID
    item_id: uuid.UUID
    item_code: str
    item_name: str
    unit: str
    quantity: float
    min_stock_level: float | None = None
    reorder_qty: float | None = None
    below_min: bool = False
    is_hazardous: bool = False
    unit_cost_paise: int | None = None


class StockLine(_Strict):
    item_id: uuid.UUID
    quantity: float = Field(gt=0)
    remarks: str | None = Field(None, max_length=500)


class StockIssueRequest(_Strict):
    store_id: uuid.UUID
    items: list[StockLine] = Field(min_length=1, max_length=200)
    issued_to_type: Literal["department", "lab", "staff", "student", "event"]
    issued_to_id: uuid.UUID | None = None
    reference_type: str | None = Field(None, max_length=30)
    reference_id: uuid.UUID | None = None
    safety_ack: bool = False


class ReturnRequest(_Strict):
    store_id: uuid.UUID
    items: list[StockLine] = Field(min_length=1, max_length=200)
    returned_by_type: Literal["department", "lab", "staff", "student", "event"] = "department"
    returned_by_id: uuid.UUID | None = None
    reference_type: str | None = Field(None, max_length=30)
    reference_id: uuid.UUID | None = None


class StockTransfer(_Strict):
    from_store_id: uuid.UUID
    to_store_id: uuid.UUID
    items: list[StockLine] = Field(min_length=1, max_length=200)


class StockAdjust(_Strict):
    store_id: uuid.UUID
    item_id: uuid.UUID
    quantity: float = Field(description="signed change")
    reason: str = Field(min_length=3, max_length=500)


class WriteOffRequest(_Strict):
    store_id: uuid.UUID
    items: list[StockLine] = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=3, max_length=500)
    approval_ref: str | None = Field(None, max_length=100)


class StockTxnOut(BaseModel):
    id: uuid.UUID
    store_id: uuid.UUID
    item_id: uuid.UUID
    item_name: str | None = None
    txn_type: str
    quantity: float
    unit_cost_paise: int | None = None
    reference_type: str | None = None
    reference_id: uuid.UUID | None = None
    issued_to_type: str | None = None
    issued_to_id: uuid.UUID | None = None
    remarks: str | None = None
    performed_by: uuid.UUID | None = None
    occurred_at: datetime


class StockResult(BaseModel):
    transactions: list[StockTxnOut]


# ---- indents --------------------------------------------------------------------------------------------------------------------
class IndentLine(_Strict):
    item_id: uuid.UUID | None = None
    free_text: str | None = Field(None, max_length=200)
    qty: float = Field(gt=0)
    unit: str | None = Field(None, max_length=20)
    est_unit_cost_paise: int = Field(0, ge=0)


class IndentCreate(_Strict):
    department_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None
    purpose: str = Field(min_length=3, max_length=2000)
    priority: Literal["low", "normal", "high", "emergency"] = "normal"
    items: list[IndentLine] = Field(min_length=1, max_length=100)
    budget_head_id: uuid.UUID | None = None
    emergency_approval_ref: str | None = Field(None, max_length=100)


class IndentUpdate(_Strict):
    purpose: str | None = Field(None, min_length=3, max_length=2000)
    priority: Literal["low", "normal", "high", "emergency"] | None = None
    items: list[IndentLine] | None = Field(None, min_length=1, max_length=100)
    budget_head_id: uuid.UUID | None = None
    store_id: uuid.UUID | None = None
    emergency_approval_ref: str | None = Field(None, max_length=100)


class IndentResponse(BaseModel):
    id: uuid.UUID
    indent_number: str
    department_id: uuid.UUID | None = None
    department_code: str | None = None
    store_id: uuid.UUID | None = None
    requested_by: uuid.UUID
    requester_name: str | None = None
    purpose: str | None = None
    priority: str
    items: list[dict[str, Any]]
    estimated_paise: int | None = None
    budget_head_id: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    workflow_step: str | None = None
    status: str
    fulfilment_pct: int = 0
    quotations: int = 0
    po_ids: list[uuid.UUID] = []
    created_at: datetime


class IndentFulfilLine(_Strict):
    line: int = Field(ge=0)
    qty_from_stock: float = Field(gt=0)


class IndentFulfil(_Strict):
    store_id: uuid.UUID | None = None
    items: list[IndentFulfilLine] = Field(min_length=1)
    safety_ack: bool = False


# ---- quotations / POs / GRN ---------------------------------------------------------------------------------------------------------
class QuotationLine(_Strict):
    line: int = Field(ge=0)
    item_id: uuid.UUID | None = None
    unit_price_paise: int = Field(ge=0)
    qty: float = Field(gt=0)
    tax_rate: float = Field(0, ge=0, le=28)


class QuotationIn(_Strict):
    supplier_id: uuid.UUID | None = None
    reference: str | None = Field(None, max_length=60)
    tender_ref: str | None = Field(None, max_length=60)
    gem_ref: str | None = Field(None, max_length=60)
    items: list[QuotationLine] = Field(min_length=1)
    valid_until: date | None = None
    file_url: str | None = None
    comparison_notes: str | None = None


class QuotationOut(BaseModel):
    id: uuid.UUID
    indent_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    reference: str | None = None
    tender_ref: str | None = None
    gem_ref: str | None = None
    items: list[dict[str, Any]]
    total_paise: int
    valid_until: date | None = None
    file_url: str | None = None
    is_selected: bool
    comparison_notes: str | None = None


class ComparativeStatement(BaseModel):
    indent_id: uuid.UUID
    suppliers: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    lowest_by_item: dict[str, str]
    lowest_total_supplier_id: uuid.UUID | None = None


class PoLine(_Strict):
    item_id: uuid.UUID
    qty: float = Field(gt=0)
    unit_price_paise: int = Field(ge=0)
    tax_rate: float = Field(0, ge=0, le=28)


class PoCreate(_Strict):
    supplier_id: uuid.UUID
    indent_id: uuid.UUID | None = None
    quotation_id: uuid.UUID | None = None
    items: list[PoLine] | None = None
    terms: str | None = Field(None, max_length=4000)
    expected_date: date | None = None


class PoUpdate(_Strict):
    items: list[PoLine] | None = None
    terms: str | None = Field(None, max_length=4000)
    expected_date: date | None = None


class PoAction(_Strict):
    reason: str | None = Field(None, max_length=1000)
    email: str | None = Field(None, max_length=200)


class PoItemOut(BaseModel):
    id: uuid.UUID
    item_id: uuid.UUID
    item_name: str | None = None
    quantity: float
    unit_price_paise: int
    tax_rate: float | None = None
    received_qty: float


class PoResponse(BaseModel):
    id: uuid.UUID
    po_number: str
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    indent_id: uuid.UUID | None = None
    quotation_id: uuid.UUID | None = None
    order_date: date
    expected_date: date | None = None
    terms: str | None = None
    subtotal_paise: int
    tax_paise: int
    total_paise: int
    status: str
    version: int = 1
    workflow_instance_id: uuid.UUID | None = None
    items: list[PoItemOut] = []
    receipts: list[dict[str, Any]] = []
    acknowledged_at: datetime | None = None


class GrnLine(_Strict):
    po_item_id: uuid.UUID
    qty_received: float = Field(ge=0)
    qty_rejected: float = Field(0, ge=0)
    remarks: str | None = Field(None, max_length=500)


class GrnCreate(_Strict):
    po_id: uuid.UUID
    store_id: uuid.UUID
    received_on: date
    invoice_no: str | None = Field(None, max_length=60)
    items: list[GrnLine] = Field(min_length=1)
    remarks: str | None = None


class GrnResponse(BaseModel):
    id: uuid.UUID
    grn_number: str
    po_id: uuid.UUID
    po_number: str | None = None
    store_id: uuid.UUID
    received_on: date
    received_by: uuid.UUID | None = None
    invoice_no: str | None = None
    items: list[dict[str, Any]]
    remarks: str | None = None
    asset_lines: list[dict[str, Any]] = []


# ---- assets ----------------------------------------------------------------------------------------------------------------------
class AssetIn(_Strict):
    name: str = Field(min_length=2, max_length=200)
    category: str | None = Field(None, max_length=60)
    item_id: uuid.UUID | None = None
    serial_no: str | None = Field(None, max_length=80)
    college_id: uuid.UUID | None = None
    location_room_id: uuid.UUID | None = None
    custodian_staff_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    purchase_date: date | None = None
    cost_paise: int | None = Field(None, ge=0)
    warranty_until: date | None = None
    depreciation_method: Literal["slm", "wdv", "none"] | None = None
    depreciation_rate: float | None = Field(None, ge=0, le=100)
    is_bookable: bool = False


class AssetUpdate(_Strict):
    name: str | None = Field(None, min_length=2, max_length=200)
    serial_no: str | None = Field(None, max_length=80)
    warranty_until: date | None = None
    depreciation_method: Literal["slm", "wdv", "none"] | None = None
    depreciation_rate: float | None = Field(None, ge=0, le=100)
    is_bookable: bool | None = None
    version: int | None = None


class AssetOut(BaseModel):
    id: uuid.UUID
    asset_tag: str
    name: str
    category: str | None = None
    item_id: uuid.UUID | None = None
    serial_no: str | None = None
    college_id: uuid.UUID | None = None
    location_room_id: uuid.UUID | None = None
    location: str | None = None
    custodian_staff_id: uuid.UUID | None = None
    custodian_name: str | None = None
    department_id: uuid.UUID | None = None
    department_code: str | None = None
    purchase_date: date | None = None
    cost_paise: int | None = None
    po_id: uuid.UUID | None = None
    warranty_until: date | None = None
    depreciation_method: str | None = None
    depreciation_rate: float | None = None
    current_value_paise: int | None = None
    is_bookable: bool
    status: str
    version: int
    pending_custodian_staff_id: uuid.UUID | None = None


class AssetBulkFromGrn(_Strict):
    grn_id: uuid.UUID
    item_ids: list[uuid.UUID] = Field(min_length=1)
    category: str | None = Field(None, max_length=60)
    location_room_id: uuid.UUID | None = None
    custodian_staff_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


class AssetTransfer(_Strict):
    custodian_staff_id: uuid.UUID | None = None
    location_room_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


class AssetStatusChange(_Strict):
    status: Literal["in_use", "idle", "under_repair", "condemned", "disposed"]
    reason: str = Field(min_length=3, max_length=1000)
    approval_ref: str | None = Field(None, max_length=100)
    sale_value_paise: int | None = Field(None, ge=0)
    service_request_id: uuid.UUID | None = None


class AssetQrLabelsRequest(_Strict):
    asset_ids: list[uuid.UUID] | None = None
    department_id: uuid.UUID | None = None
    category: str | None = None


class AssetLookup(BaseModel):
    asset: AssetOut


class AssetAuditStart(_Strict):
    department_id: uuid.UUID | None = None
    location_room_id: uuid.UUID | None = None
    category: str | None = None
    name: str | None = Field(None, max_length=120)


class AssetAuditScanLine(_Strict):
    asset_tag: str | None = Field(None, max_length=40)
    qr: str | None = Field(None, max_length=200)
    condition: Literal["good", "fair", "poor", "damaged"] = "good"
    remarks: str | None = Field(None, max_length=500)


class AssetAuditScan(_Strict):
    scans: list[AssetAuditScanLine] = Field(min_length=1, max_length=1000)


class AuditCycleOut(BaseModel):
    id: uuid.UUID
    name: str
    scope: dict[str, Any]
    started_on: date
    status: str
    expected: int
    scanned: int
    completed_on: date | None = None


class AuditReport(BaseModel):
    audit_id: uuid.UUID
    expected: int
    found: int
    missing: int
    unexpected: int
    conditions: dict[str, int]
    missing_assets: list[dict[str, Any]] = []
    unexpected_assets: list[dict[str, Any]] = []
    flagged: list[str] = []


class DepreciationRunRequest(_Strict):
    financial_year: str = Field(pattern=r"^\d{4}-\d{2}$", description="e.g. 2026-27")
    preview: bool = False


class DepreciationSummary(BaseModel):
    financial_year: str
    assets: int
    depreciation_paise: int
    rows: list[dict[str, Any]] = []
    preview: bool = False


# ---- bills ------------------------------------------------------------------------------------------------------------------------
class VendorBillIn(_Strict):
    supplier_id: uuid.UUID
    po_id: uuid.UUID | None = None
    grn_id: uuid.UUID | None = None
    bill_number: str = Field(min_length=1, max_length=60)
    bill_date: date
    due_date: date | None = None
    subtotal_paise: int = Field(ge=0)
    tax_paise: int | None = Field(None, ge=0)
    lines: list[dict[str, Any]] | None = None
    file_url: str | None = None


class VendorBillOut(BaseModel):
    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    po_id: uuid.UUID | None = None
    po_number: str | None = None
    grn_id: uuid.UUID | None = None
    bill_number: str
    bill_date: date
    due_date: date | None = None
    subtotal_paise: int
    tax_paise: int
    tds_paise: int
    total_paise: int
    net_payable_paise: int
    file_url: str | None = None
    status: str
    workflow_instance_id: uuid.UUID | None = None
    paid_at: datetime | None = None
    payment_ref: str | None = None
    match: dict[str, Any] = {}
    hold_reason: str | None = None


class BillDecision(_Strict):
    action: Literal["approve", "reject", "hold", "release"]
    remarks: str | None = Field(None, max_length=2000)
    hold_reason: str | None = Field(None, max_length=500)


class BillPay(_Strict):
    payment_ref: str = Field(min_length=2, max_length=60)
    paid_at: datetime | None = None
    mode: Literal["neft", "rtgs", "cheque", "upi", "cash"] = "neft"


class VendorStoreSale(_Strict):
    store_id: uuid.UUID
    items: list[StockLine] = Field(min_length=1, max_length=50)
    buyer_type: Literal["student", "staff"] = "student"
    buyer_id: uuid.UUID
    bill_to_fees: bool = True


class InvJobAccepted(BaseModel):
    job_id: uuid.UUID


class InvReport(BaseModel):
    kind: str
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
