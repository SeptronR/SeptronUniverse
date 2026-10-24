"""Library enums — Prompts/19 §19.3 (values from the section 18 column comments)."""

from enum import StrEnum
from typing import Any


class ResourceType(StrEnum):
    BOOK = "book"
    JOURNAL = "journal"
    THESIS = "thesis"
    EBOOK = "ebook"
    EJOURNAL = "ejournal"
    CD = "cd"
    REFERENCE = "reference"
    ILL = "ill"


class CopyStatus(StrEnum):
    AVAILABLE = "available"
    ISSUED = "issued"
    RESERVED = "reserved"
    LOST = "lost"
    DAMAGED = "damaged"
    WITHDRAWN = "withdrawn"
    REFERENCE_ONLY = "reference_only"


class MemberType(StrEnum):
    STUDENT = "student"
    FACULTY = "faculty"
    STAFF = "staff"
    SCHOLAR = "scholar"
    ALUMNI = "alumni"
    EXTERNAL = "external"


class IssueStatus(StrEnum):
    ISSUED = "issued"
    RETURNED = "returned"
    OVERDUE = "overdue"
    LOST = "lost"


class ReservationStatus(StrEnum):
    WAITING = "waiting"
    AVAILABLE = "available"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class IllStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    RECEIVED = "received"
    RETURNED = "returned"
    CANCELLED = "cancelled"


ACTIVE_ISSUE = ("issued", "overdue")
# status changes a librarian may make by hand (issued / reserved / lost move only through circulation)
MANUAL_COPY_STATUS = ("available", "damaged", "withdrawn", "reference_only")

# defaults copied into ``institution_settings['library.member_rules']`` (migration 0019)
MEMBER_RULES: dict[str, dict[str, Any]] = {
    "student": {"max_books": 3, "loan_days": 14, "max_renewals": 1},
    "faculty": {"max_books": 10, "loan_days": 30, "max_renewals": 2},
    "scholar": {"max_books": 6, "loan_days": 30, "max_renewals": 2},
    "staff": {"max_books": 3, "loan_days": 14, "max_renewals": 1},
    "alumni": {"max_books": 2, "loan_days": 14, "max_renewals": 0, "deposit_paise": 200000},
    "external": {"max_books": 1, "loan_days": 7, "max_renewals": 0, "deposit_paise": 100000},
}

# Dewey Decimal top classes (default categories)
DDC_CLASSES: tuple[tuple[str, str], ...] = (
    ("000", "Computer science, information & general works"),
    ("100", "Philosophy & psychology"),
    ("200", "Religion"),
    ("300", "Social sciences"),
    ("400", "Language"),
    ("500", "Science"),
    ("600", "Technology"),
    ("700", "Arts & recreation"),
    ("800", "Literature"),
    ("900", "History & geography"),
)
