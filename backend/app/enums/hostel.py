"""Hostel enums — Prompts/20 §20.3 (values from the section 19 column comments)."""

from enum import StrEnum
from typing import Any


class HostelType(StrEnum):
    BOYS = "boys"
    GIRLS = "girls"
    COED = "coed"
    PG = "pg"
    INTERNATIONAL = "international"
    STAFF = "staff"


class RoomType(StrEnum):
    SINGLE = "single"
    DOUBLE = "double"
    TRIPLE = "triple"
    DORM = "dorm"


class RoomStatus(StrEnum):
    AVAILABLE = "available"
    FULL = "full"
    MAINTENANCE = "maintenance"
    BLOCKED = "blocked"


class BedStatus(StrEnum):
    VACANT = "vacant"
    ALLOCATED = "allocated"
    BLOCKED = "blocked"


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    WAITLISTED = "waitlisted"
    ALLOTTED = "allotted"
    DECLINED = "declined"
    CANCELLED = "cancelled"


class AllocationStatus(StrEnum):
    ALLOTTED = "allotted"
    CHECKED_IN = "checked_in"
    VACATED = "vacated"
    TRANSFERRED = "transferred"
    EVICTED = "evicted"


class RoomChangeStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class RollCallStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    ON_LEAVE = "on_leave"


class Diet(StrEnum):
    VEG = "veg"
    NONVEG = "nonveg"
    JAIN = "jain"
    SPECIAL = "special"


class Meal(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    SNACKS = "snacks"
    DINNER = "dinner"


class MealStatus(StrEnum):
    TAKEN = "taken"
    SKIPPED = "skipped"
    REBATE = "rebate"


class LeaveType(StrEnum):
    OUT_PASS = "out_pass"
    DAY_LEAVE = "day_leave"
    HOME_LEAVE = "home_leave"
    MEDICAL = "medical"


class GuardianConsent(StrEnum):
    PENDING = "pending"
    OTP_VERIFIED = "otp_verified"
    NOT_REQUIRED = "not_required"


class LeaveStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    OUT = "out"
    RETURNED = "returned"
    LATE_RETURN = "late_return"
    ABSCONDING = "absconding"


class ComplaintStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class DisciplineAction(StrEnum):
    WARNING = "warning"
    FINE = "fine"
    SUSPENSION = "suspension"
    EVICTION = "eviction"


class QuarterStatus(StrEnum):
    VACANT = "vacant"
    ALLOCATED = "allocated"
    MAINTENANCE = "maintenance"


ACTIVE_ALLOCATION = ("allotted", "checked_in")
ACTIVE_LEAVE = ("requested", "approved", "out")
BED_LABELS = "ABCDEFGHIJKL"
# max duration (hours) per leave type
LEAVE_MAX_HOURS: dict[str, int] = {"out_pass": 24, "day_leave": 24, "home_leave": 24 * 30, "medical": 24 * 60}
ROOM_CAPACITY: dict[str, int] = {"single": 1, "double": 2, "triple": 3, "dorm": 6}
GENDER_HOSTELS: dict[str, tuple[str, ...]] = {
    "male": ("boys", "coed", "pg", "international"),
    "female": ("girls", "coed", "pg", "international"),
}
COMPLAINT_FLOW: dict[str, tuple[str, ...]] = {
    "open": ("assigned", "in_progress", "resolved", "closed"),
    "assigned": ("in_progress", "resolved", "closed"),
    "in_progress": ("resolved", "closed"),
    "resolved": ("closed", "in_progress"),
    "closed": (),
}

# priority weights (``hostel.priority_weights`` overrides)
PRIORITY_WEIGHTS: dict[str, Any] = {
    "distance_bands": [
        {"min_km": 300, "points": 50},
        {"min_km": 100, "points": 40},
        {"min_km": 50, "points": 25},
        {"min_km": 20, "points": 10},
    ],
    "category": {"SC": 15, "ST": 15, "EWS": 10, "OBC": 5},
    "pwd": 100,
    "cgpa_factor": 2.0,
}
