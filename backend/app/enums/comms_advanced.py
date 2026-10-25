"""Communication-advanced enums and defaults — Prompts/24 §24.3."""

from enum import StrEnum


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    PAUSED = "paused"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Channel(StrEnum):
    SMS = "sms"
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    PUSH = "push"
    IN_APP = "in_app"


class BotFlowState(StrEnum):
    MENU = "menu"
    AWAIT_CHOICE = "await_choice"
    AWAIT_WARD = "await_ward"
    AWAIT_TEXT = "await_text"
    HANDOFF = "handoff"
    CLOSED = "closed"


class AssistantRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


CHANNELS = ("sms", "whatsapp", "email", "push", "in_app")
DEFAULT_THROTTLE = {"sms": 600, "whatsapp": 300, "email": 1200, "push": 5000, "in_app": 100000}
DEFAULT_RATES_PAISE = {"sms": 20, "whatsapp": 60, "email": 2, "push": 0, "in_app": 0}
EMERGENCY_CONFIRM = "BROADCAST"
SEGMENT_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # field, type, ops
    ("college", "uuid", ("eq", "in")),
    ("department", "uuid", ("eq", "in")),
    ("program", "uuid", ("eq", "in")),
    ("batch", "uuid", ("eq", "in")),
    ("hostel", "uuid", ("eq", "in")),
    ("route", "uuid", ("eq", "in")),
    ("role", "str", ("eq", "in")),
    ("gender", "str", ("eq", "in")),
    ("category", "str", ("eq", "in")),
    ("status", "str", ("eq", "in")),
    ("term_number", "int", ("eq", "in", "between", "gte", "lte")),
    ("dues_paise", "int", ("gte", "lte", "between")),
    ("attendance_pct", "num", ("lte", "gte", "between")),
)
BOT_FLOWS: list[dict[str, object]] = [
    {
        "key": "attendance",
        "label": "Attendance",
        "trigger_words": ["attendance", "1"],
        "requires_auth": True,
        "roles": ["student", "parent"],
    },
    {
        "key": "dues",
        "label": "Fee dues",
        "trigger_words": ["dues", "fee", "fees", "2"],
        "requires_auth": True,
        "roles": ["student", "parent"],
    },
    {
        "key": "timetable",
        "label": "Today's timetable",
        "trigger_words": ["timetable", "classes", "3"],
        "requires_auth": True,
        "roles": ["student", "parent"],
    },
    {
        "key": "results",
        "label": "Latest results",
        "trigger_words": ["result", "results", "4"],
        "requires_auth": True,
        "roles": ["student", "parent"],
    },
    {
        "key": "hall_ticket",
        "label": "Hall ticket",
        "trigger_words": ["hall ticket", "hallticket", "5"],
        "requires_auth": True,
        "roles": ["student"],
    },
    {
        "key": "outpass_status",
        "label": "Out-pass status",
        "trigger_words": ["outpass", "out-pass", "leave", "6"],
        "requires_auth": True,
        "roles": ["student", "parent"],
    },
    {
        "key": "receipt",
        "label": "Last fee receipt",
        "trigger_words": ["receipt", "7"],
        "requires_auth": True,
        "roles": ["student", "parent"],
    },
    {
        "key": "complaint",
        "label": "Raise a complaint",
        "trigger_words": ["complaint", "8"],
        "requires_auth": True,
        "roles": ["student", "parent", "staff"],
    },
    {
        "key": "talk_to_human",
        "label": "Talk to the office",
        "trigger_words": ["human", "office", "help", "9"],
        "requires_auth": False,
        "roles": [],
    },
]
