"""Inventory, procurement & bills enums — Prompts/22 §22.3 (values from the section 21 column comments)."""

from enum import StrEnum


class SupplierStatus(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    BLACKLISTED = "blacklisted"


class StoreType(StrEnum):
    CENTRAL = "central"
    DEPARTMENT = "department"
    LAB = "lab"
    HOSTEL = "hostel"


class IndentStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    HOD_APPROVED = "hod_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"
    CLOSED = "closed"


class IndentPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EMERGENCY = "emergency"


class PoStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"  # in the procurement.po workflow (status kept within the 20-char column)
    APPROVED = "approved"
    SENT = "sent"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class TxnType(StrEnum):
    RECEIPT = "receipt"
    ISSUE = "issue"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    WRITE_OFF = "write_off"


class AssetStatus(StrEnum):
    IN_USE = "in_use"
    IDLE = "idle"
    UNDER_REPAIR = "under_repair"
    CONDEMNED = "condemned"
    DISPOSED = "disposed"


class DepreciationMethod(StrEnum):
    SLM = "slm"
    WDV = "wdv"
    NONE = "none"


class BillStatus(StrEnum):
    RECEIVED = "received"
    VERIFIED = "verified"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"


DEFAULT_CATEGORIES: tuple[tuple[str, bool], ...] = (
    ("Stationery", True),
    ("Lab consumables", True),
    ("Chemicals", True),
    ("IT hardware", False),
    ("Furniture", False),
    ("Electrical", True),
    ("Cleaning", True),
    ("Sports", True),
    ("Library", True),
)
ISSUE_TARGETS = ("department", "lab", "staff", "student", "event")
OPEN_INDENT = ("submitted", "hod_approved", "approved")
RECEIVABLE_PO = ("approved", "sent", "partially_received")
