"""Offering & registration enums — Prompts/09 §09.3 (values copied from the section 11 column comments of
Database_Schema.sql)."""

from enum import StrEnum


class OfferingStatus(StrEnum):
    PLANNED = "planned"
    OPEN = "open"
    CLOSED = "closed"
    IN_PROGRESS = "in_progress"
    MARKS_ENTRY = "marks_entry"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# planned → open (registration) → closed (add-drop end) → in_progress → marks_entry (Phase 13) → completed (Phase 15);
# cancelled only with zero confirmed items (rule 4)
OFFERING_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"open", "cancelled"},
    "open": {"closed", "planned", "cancelled"},
    "closed": {"open", "in_progress", "cancelled"},
    "in_progress": {"marks_entry", "cancelled"},
    "marks_entry": {"completed", "in_progress"},
    "completed": set(),
    "cancelled": set(),
}
OFFERING_FINAL = frozenset({"completed", "cancelled"})


class DeliveryMode(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"
    HYBRID = "hybrid"


class FacultyRole(StrEnum):
    COORDINATOR = "coordinator"
    INSTRUCTOR = "instructor"
    LAB_INSTRUCTOR = "lab_instructor"
    TEACHING_ASSISTANT = "teaching_assistant"


class WindowType(StrEnum):
    REGULAR = "regular"
    ADD_DROP = "add_drop"
    LATE = "late"
    ARREAR = "arrear"
    SUMMER = "summer"
    AUDIT = "audit"
    MINOR_HONOURS = "minor_honours"


class WindowStatus(StrEnum):
    SCHEDULED = "scheduled"
    OPEN = "open"
    CLOSED = "closed"


class RegistrationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ADVISOR_PENDING = "advisor_pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"
    LOCKED = "locked"


# statuses in which the student edits the cart
EDITABLE_REGISTRATION = frozenset({"draft", "changes_requested", "rejected"})
# statuses that count as "pending" for the term-close check
PENDING_REGISTRATION = frozenset({"draft", "submitted", "advisor_pending", "changes_requested"})


class ItemStatus(StrEnum):
    SELECTED = "selected"
    WAITLISTED = "waitlisted"
    CONFIRMED = "confirmed"
    DROPPED = "dropped"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"
    SUBSTITUTED = "substituted"


# items that hold a seat / count towards the credits
SEATED_ITEMS = frozenset({"selected", "confirmed"})
LIVE_ITEMS = frozenset({"selected", "confirmed", "waitlisted"})


class RegistrationType(StrEnum):
    REGULAR = "regular"
    ARREAR = "arrear"
    IMPROVEMENT = "improvement"
    AUDIT = "audit"
    MINOR = "minor"
    HONOURS = "honours"
    RE_REGISTRATION = "re_registration"
    MOOC = "mooc"


class WaitlistStatus(StrEnum):
    WAITING = "waiting"
    OFFERED = "offered"
    PROMOTED = "promoted"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ArrearStatus(StrEnum):
    OPEN = "open"
    REGISTERED = "registered"
    CLEARED = "cleared"
    WAIVED = "waived"


class ChoiceFormStatus(StrEnum):
    SUBMITTED = "submitted"
    ALLOCATED = "allocated"
    UNALLOCATED = "unallocated"
    MANUAL = "manual"


class AllocationMode(StrEnum):
    PRIORITY_CGPA = "priority_cgpa"
    FCFS = "fcfs"
    LOTTERY = "lottery"
    MANUAL = "manual"


class AdvisorDecisionKind(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
