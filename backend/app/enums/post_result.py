"""Post-result enums — Prompts/16 §16.3 (values from the section 16 column comments)."""

from enum import StrEnum


class RevalType(StrEnum):
    RETOTALING = "retotaling"
    PHOTOCOPY = "photocopy"
    REVALUATION = "revaluation"
    CHALLENGE = "challenge"


class RevalStatus(StrEnum):
    SUBMITTED = "submitted"
    FEE_PAID = "fee_paid"
    ASSIGNED = "assigned"
    EVALUATED = "evaluated"
    MARKS_CHANGED = "marks_changed"
    NO_CHANGE = "no_change"
    REJECTED = "rejected"
    CLOSED = "closed"


class MalpracticeCategory(StrEnum):
    COPYING = "copying"
    IMPERSONATION = "impersonation"
    DEVICE = "device"
    MATERIAL = "material"
    MISCONDUCT = "misconduct"
    TAMPERING = "tampering"
    OTHER = "other"


class Punishment(StrEnum):
    NONE = "none"
    WARNING = "warning"
    CANCEL_PAPER = "cancel_paper"
    CANCEL_SESSION = "cancel_session"
    DEBAR_TERMS = "debar_terms"
    EXPEL = "expel"


class MalpracticeStatus(StrEnum):
    REPORTED = "reported"
    UNDER_INQUIRY = "under_inquiry"
    HEARING_SCHEDULED = "hearing_scheduled"
    DECIDED = "decided"
    APPEALED = "appealed"
    APPEAL_DECIDED = "appeal_decided"
    CLOSED = "closed"


class TranscriptType(StrEnum):
    PROVISIONAL = "provisional"
    CONSOLIDATED = "consolidated"
    FINAL = "final"
    DUPLICATE = "duplicate"
    MIGRATION = "migration"


class TranscriptStatus(StrEnum):
    REQUESTED = "requested"
    FEE_PENDING = "fee_pending"
    GENERATED = "generated"
    ISSUED = "issued"
    CANCELLED = "cancelled"


REVAL_OPEN = ("submitted", "fee_paid", "assigned", "evaluated")
MALPRACTICE_PENDING = ("reported", "under_inquiry", "hearing_scheduled", "appealed")
CANCELLING = ("cancel_paper", "cancel_session", "debar_terms", "expel")
# IN pack default punishment scale (platform_settings['malpractice_scale'])
MALPRACTICE_SCALE: list[dict[str, object]] = [
    {"punishment": "warning", "label": "Written warning", "severity": 1},
    {"punishment": "cancel_paper", "label": "Cancel the paper", "severity": 2},
    {"punishment": "cancel_session", "label": "Cancel every paper of the session", "severity": 3},
    {"punishment": "debar_terms", "label": "Debar for 1–4 terms", "severity": 4, "min_terms": 1, "max_terms": 4},
    {"punishment": "expel", "label": "Expel from the institution", "severity": 5},
]
# transcript fees (paise) per type when the institution has no ``results.transcript_fees`` setting
TRANSCRIPT_FEES = {"provisional": 30000, "consolidated": 50000, "final": 50000, "duplicate": 100000, "migration": 50000}
