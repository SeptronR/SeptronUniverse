"""Fees, scholarships & no-dues enums — Prompts/12 §12.3 (values copied from the section 13 column comments of
Database_Schema.sql)."""

from enum import StrEnum


class HeadType(StrEnum):
    TUITION = "tuition"
    ADMISSION = "admission"
    EXAM = "exam"
    HOSTEL = "hostel"
    MESS = "mess"
    TRANSPORT = "transport"
    LIBRARY = "library"
    LAB = "lab"
    CAUTION_DEPOSIT = "caution_deposit"
    FINE = "fine"
    CERTIFICATE = "certificate"
    REVAL = "reval"
    CONDONATION = "condonation"
    CONVOCATION = "convocation"
    AFFILIATION = "affiliation"
    OTHER = "other"


class PayerType(StrEnum):
    STUDENT = "student"
    APPLICANT = "applicant"
    COLLEGE = "college"
    ALUMNI = "alumni"
    STAFF = "staff"
    COMPANY = "company"


class InvoiceStatus(StrEnum):
    PENDING = "pending"
    PARTIAL = "partial"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentMode(StrEnum):
    CASH = "cash"
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    CHEQUE = "cheque"
    DD = "dd"
    NEFT = "neft"
    CHALLAN = "challan"
    GATEWAY = "gateway"
    ADJUSTMENT = "adjustment"
    SCHOLARSHIP_CREDIT = "scholarship_credit"
    WALLET = "wallet"


class PaymentStatus(StrEnum):
    INITIATED = "initiated"
    SUCCESS = "success"
    FAILED = "failed"
    BOUNCED = "bounced"
    CANCELLED = "cancelled"
    RECONCILED = "reconciled"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    PROCESSED = "processed"
    REJECTED = "rejected"


class ScholarshipProvider(StrEnum):
    CENTRAL_GOVT = "central_govt"
    STATE_GOVT = "state_govt"
    INSTITUTION = "institution"
    PRIVATE = "private"
    ALUMNI = "alumni"


class AmountType(StrEnum):
    FIXED = "fixed"
    FEE_PCT = "fee_pct"
    FEE_FULL = "fee_full"


class ScholarshipStatus(StrEnum):
    APPLIED = "applied"
    VERIFIED = "verified"
    RECOMMENDED = "recommended"
    SANCTIONED = "sanctioned"
    DISBURSED = "disbursed"
    REJECTED = "rejected"


class DisbursementMode(StrEnum):
    FEE_CREDIT = "fee_credit"
    BANK_TRANSFER = "bank_transfer"
    EXTERNAL_PORTAL = "external_portal"


class NoDuesPurpose(StrEnum):
    GRADUATION = "graduation"
    TRANSFER = "transfer"
    HOSTEL_VACATE = "hostel_vacate"
    EXIT = "exit"
    TRANSCRIPT = "transcript"


class NoDuesStatus(StrEnum):
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    CLEARED = "cleared"
    BLOCKED = "blocked"


class SignoffStatus(StrEnum):
    PENDING = "pending"
    CLEARED = "cleared"
    DUES_PENDING = "dues_pending"


class DepartmentKey(StrEnum):
    ACCOUNTS = "accounts"
    LIBRARY = "library"
    HOSTEL = "hostel"
    LAB = "lab"
    DEPARTMENT = "department"
    SPORTS = "sports"
    TRANSPORT = "transport"
    PLACEMENT = "placement"


class DiscountType(StrEnum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"


class FineAppliesTo(StrEnum):
    LATE_FEE = "late_fee"
    LIBRARY_OVERDUE = "library_overdue"
    HOSTEL = "hostel"
    DISCIPLINE = "discipline"


class FineCalcType(StrEnum):
    PER_DAY = "per_day"
    FLAT = "flat"
    SLAB = "slab"


class ReconcileStatus(StrEnum):
    UNMATCHED = "unmatched"
    MATCHED = "matched"
    IGNORED = "ignored"


class DayBookStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    DEPOSITED = "deposited"


# modes that land in the day-book columns
CASH_MODES = frozenset({PaymentMode.CASH})
CHEQUE_MODES = frozenset({PaymentMode.CHEQUE, PaymentMode.DD})
OFFLINE_MODES = frozenset({PaymentMode.NEFT, PaymentMode.CHALLAN, PaymentMode.DD, PaymentMode.CHEQUE})
OPEN_INVOICE = frozenset({InvoiceStatus.PENDING, InvoiceStatus.PARTIAL, InvoiceStatus.OVERDUE})
SETTLED_PAYMENT = frozenset({PaymentStatus.SUCCESS, PaymentStatus.RECONCILED})
