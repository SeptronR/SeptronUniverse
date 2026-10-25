"""Accounting & budget enums — Prompts/23 §23.3 (values from the section 22 column comments)."""

from enum import StrEnum


class AccountType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"


class ExpenseStatus(StrEnum):
    RECORDED = "recorded"
    SUBMITTED = "submitted"  # in the accounting.expense workflow
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"


class BudgetStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    FROZEN = "frozen"
    CLOSED = "closed"


class GrantStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    SUSPENDED = "suspended"


class ReconStatus(StrEnum):
    OPEN = "open"
    RECONCILED = "reconciled"


class ExportTarget(StrEnum):
    TALLY = "tally"
    ZOHO = "zoho"
    CSV = "csv"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


# IN pack chart of accounts: (code, name, type, parent code). Phase 12 codes (1100/1200/1300/2100/2200/4000/5100 and the
# 40x0 fee-head children) are kept.
IN_CHART: tuple[tuple[str, str, str, str | None], ...] = (
    ("1000", "Assets", "asset", None),
    ("1100", "Fees receivable", "asset", "1000"),
    ("1200", "Cash", "asset", "1000"),
    ("1300", "Bank", "asset", "1000"),
    ("1310", "Bank — current account", "asset", "1300"),
    ("1320", "Bank — savings account", "asset", "1300"),
    ("1400", "Fixed assets", "asset", "1000"),
    ("1410", "Furniture & fixtures", "asset", "1400"),
    ("1420", "IT equipment", "asset", "1400"),
    ("1430", "Lab equipment", "asset", "1400"),
    ("1440", "Vehicles", "asset", "1400"),
    ("1500", "Deposits & advances", "asset", "1000"),
    ("2000", "Liabilities", "liability", None),
    ("2100", "Refunds payable", "liability", "2000"),
    ("2200", "Caution deposits", "liability", "2000"),
    ("2300", "Fees received in advance", "liability", "2000"),
    ("2400", "TDS payable", "liability", "2000"),
    ("2500", "GST payable", "liability", "2000"),
    ("2600", "PF / ESI payable", "liability", "2000"),
    ("2700", "Vendor payables", "liability", "2000"),
    ("2800", "Unspent grants", "liability", "2000"),
    ("3000", "Equity", "equity", None),
    ("3100", "General fund", "equity", "3000"),
    ("3200", "Restricted funds", "equity", "3000"),
    ("4000", "Fee income", "income", None),
    ("4500", "Other income", "income", None),
    ("4510", "Grants received", "income", "4500"),
    ("4520", "Donations", "income", "4500"),
    ("4530", "Interest", "income", "4500"),
    ("4540", "Library fines", "income", "4500"),
    ("4550", "Rent & hire charges", "income", "4500"),
    ("4560", "Asset sale proceeds", "income", "4500"),
    ("4590", "Miscellaneous income", "income", "4500"),
    ("5000", "Expenses", "expense", None),
    ("5100", "Scholarship credits", "expense", "5000"),
    ("5200", "Salaries", "expense", "5000"),
    ("5210", "PF / ESI — employer", "expense", "5000"),
    ("5300", "Consumables", "expense", "5000"),
    ("5310", "Lab consumables & chemicals", "expense", "5300"),
    ("5320", "Stationery", "expense", "5300"),
    ("5400", "Library books & journals", "expense", "5000"),
    ("5500", "Repairs & maintenance", "expense", "5000"),
    ("5600", "Utilities", "expense", "5000"),
    ("5700", "Travel", "expense", "5000"),
    ("5800", "Events & seminars", "expense", "5000"),
    ("5850", "Fee refunds", "expense", "5000"),
    ("5900", "Depreciation", "expense", "5000"),
    ("5910", "Audit fees", "expense", "5000"),
    ("5920", "Bank charges", "expense", "5000"),
    ("5990", "Miscellaneous expenses", "expense", "5000"),
)
DEFAULT_MAPPINGS = {
    "bank": "1310",
    "cash": "1200",
    "caution_deposit": "2200",
    "advance": "2300",
    "tds_payable": "2400",
    "gst_payable": "2500",
    "pf_payable": "2600",
    "salaries": "5200",
    "employer_contrib": "5210",
    "refunds": "5850",
    "depreciation": "5900",
    "asset_sale": "4560",
    "donations": "4520",
    "grants": "4510",
    "bank_charges": "5920",
    "interest": "4530",
    "inventory_default": "5300",
    "inventory_categories": {
        "Lab consumables": "5310",
        "Chemicals": "5310",
        "Stationery": "5320",
        "Library": "5400",
        "IT hardware": "1420",
        "Furniture": "1410",
    },
}
GRANT_HEADS = ("manpower", "equipment", "consumables", "travel", "contingency", "overheads")
