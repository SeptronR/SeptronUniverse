"""Calendar, events & facilities enums and shipped defaults — Prompts/25 §25.3 / §25.2."""

from enum import StrEnum
from typing import Any


class CalendarEventType(StrEnum):
    GENERAL = "general"
    ACADEMIC = "academic"
    EXAM = "exam"
    HOLIDAY = "holiday"
    REGISTRATION = "registration"
    DEADLINE = "deadline"
    MEETING = "meeting"


class EventType(StrEnum):
    CONFERENCE = "conference"
    SEMINAR = "seminar"
    WORKSHOP = "workshop"
    FDP = "fdp"
    GUEST_LECTURE = "guest_lecture"
    CULTURAL = "cultural"
    SPORTS = "sports"
    OUTREACH = "outreach"
    EXHIBITION = "exhibition"
    ALUMNI = "alumni"
    CONVOCATION = "convocation"
    OTHER = "other"


class EventStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BookingStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    HANDED_OVER = "handed_over"  # equipment only
    RETURNED = "returned"  # equipment only


class ServiceCategory(StrEnum):
    ELECTRICAL = "electrical"
    PLUMBING = "plumbing"
    IT = "it"
    NETWORK = "network"
    FURNITURE = "furniture"
    CLEANING = "cleaning"
    CIVIL = "civil"
    SECURITY = "security"
    ASSET = "asset"
    OTHER = "other"


class ServicePriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ServiceStatus(StrEnum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


class VisitorStatus(StrEnum):
    ISSUED = "issued"
    INSIDE = "inside"
    EXITED = "exited"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AlertType(StrEnum):
    SOS = "sos"
    FIRE = "fire"
    MEDICAL = "medical"
    SECURITY = "security"


class AlertStatus(StrEnum):
    RAISED = "raised"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AppointmentStatus(StrEnum):
    AVAILABLE = "available"
    BOOKED = "booked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class SportsLevel(StrEnum):
    INSTITUTION = "institution"
    INTER_COLLEGE = "inter_college"
    UNIVERSITY = "university"
    STATE = "state"
    NATIONAL = "national"
    INTERNATIONAL = "international"


class LostFoundStatus(StrEnum):
    REPORTED = "reported"
    CLAIMED = "claimed"
    DISPOSED = "disposed"


class WalletTxnType(StrEnum):
    TOPUP = "topup"
    DEBIT = "debit"
    REFUND = "refund"


OPEN_SERVICE = ("open", "assigned", "in_progress", "reopened")
LIVE_BOOKING = ("requested", "approved", "handed_over")

# §25.2 settings defaults
SLA_HOURS: dict[str, int] = {
    "electrical": 24,
    "plumbing": 24,
    "it": 8,
    "network": 4,
    "furniture": 72,
    "cleaning": 12,
    "civil": 168,
    "security": 2,
    "asset": 48,
    "other": 48,
}
# priority multipliers on the category SLA (high halves, urgent quarters)
PRIORITY_FACTOR: dict[str, float] = {"low": 1.5, "normal": 1.0, "high": 0.5, "urgent": 0.25}
# event type → default NAAC criterion
NAAC_DEFAULTS: dict[str, str] = {
    "fdp": "6.3.3",
    "conference": "3.3",
    "seminar": "3.3",
    "workshop": "3.3",
    "outreach": "3.6",
    "cultural": "5.3",
    "sports": "5.3",
}
EVENT_TYPE_COLORS: dict[str, str] = {
    "holiday": "#ef4444",
    "exam": "#f59e0b",
    "academic": "#3b82f6",
    "registration": "#8b5cf6",
    "deadline": "#ec4899",
    "event": "#10b981",
    "booking": "#64748b",
    "class": "#0ea5e9",
    "general": "#6b7280",
    "meeting": "#14b8a6",
}
# category → default routing (role slug of the queue owner; ``facilities.routing`` overrides)
DEFAULT_ROUTING: dict[str, str] = {
    "it": "it_cell",
    "network": "it_cell",
    "security": "security_officer",
}
SOS_RESPONDERS_DEFAULT: dict[str, Any] = {
    "security": ["security_officer"],
    "medical": ["medical_officer", "security_officer"],
    "fire": ["security_officer", "estate_officer"],
    "sos": ["security_officer"],
}
EVENT_CERTIFICATE_HTML = (
    "<div style='text-align:center;font-family:serif;padding:48px;border:6px double #1e3a8a'>"
    "<h1>Certificate of Participation</h1><p>This is to certify that</p><h2>{{ name }}</h2>"
    "<p>participated in <b>{{ event }}</b> ({{ event_type }}) held from {{ from_on }} to {{ to_on }}.</p>"
    "<p style='margin-top:48px'>{{ institution }}</p><p style='font-size:10px'>Verify: {{ verify_url }}</p></div>"
)
