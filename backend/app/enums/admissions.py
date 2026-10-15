"""Admissions enums — Prompts/08 §08.3 (values copied from the section 10 column comments of Database_Schema.sql and
docs/Academic_Core_Design.md §2b). Quotas and categories are the regulatory pack's codes (``STATE``, ``LATERAL``,
``PWD`` …; ``GEN``, ``OBC-NCL`` …) so ``StudentCreate`` accepts them unchanged on admission."""

from enum import StrEnum


class CycleLevel(StrEnum):
    UG = "ug"
    PG = "pg"
    PHD = "phd"
    DIPLOMA = "diploma"
    LATERAL = "lateral"
    CERTIFICATE = "certificate"


class CycleStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    MERIT_PROCESSING = "merit_processing"
    COUNSELLING = "counselling"
    COMPLETED = "completed"
    ARCHIVED = "archived"


CYCLE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"open"},
    "open": {"closed"},
    "closed": {"open", "merit_processing"},
    "merit_processing": {"counselling", "completed"},
    "counselling": {"completed"},
    "completed": {"archived"},
    "archived": set(),
}


class EntranceSource(StrEnum):
    JEE = "jee"
    NEET = "neet"
    CUET = "cuet"
    STATE_CET = "state_cet"
    GATE = "gate"
    CAT = "cat"
    INSTITUTION_TEST = "institution_test"
    MERIT_ONLY = "merit_only"


class Quota(StrEnum):
    """The IN pack quotas (``core/packs/in_pack.py``); other packs validate against their own list."""

    STATE = "STATE"
    ALL_INDIA = "ALL_INDIA"
    MANAGEMENT = "MANAGEMENT"
    NRI = "NRI"
    LATERAL = "LATERAL"
    SPORTS = "SPORTS"
    PWD = "PWD"
    WOMEN = "WOMEN"
    DEFENCE = "DEFENCE"
    EWS_SUPER = "EWS_SUPER"


GEN = "GEN"


class ApplicantStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    FEE_PAID = "fee_paid"
    UNDER_VERIFICATION = "under_verification"
    VERIFIED = "verified"
    DOC_REJECTED = "doc_rejected"
    WAITLISTED = "waitlisted"
    MERIT_LISTED = "merit_listed"
    ALLOTTED = "allotted"
    ACCEPTED = "accepted"
    PROVISIONALLY_ADMITTED = "provisionally_admitted"
    ADMITTED = "admitted"
    DECLINED = "declined"
    LAPSED = "lapsed"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"


# docs/Academic_Core_Design.md §2b — "any → withdrawn | rejected" is added for every non-terminal state below
APPLICANT_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"submitted"},
    "submitted": {"fee_paid", "under_verification"},
    "fee_paid": {"under_verification"},
    "under_verification": {"verified", "doc_rejected"},
    "doc_rejected": {"under_verification"},
    "verified": {"merit_listed", "waitlisted", "allotted", "admitted"},
    "waitlisted": {"merit_listed", "allotted"},
    "merit_listed": {"allotted", "waitlisted", "merit_listed"},
    "allotted": {"accepted", "declined", "lapsed", "allotted", "merit_listed"},
    "accepted": {"provisionally_admitted", "admitted", "allotted"},
    "provisionally_admitted": {"admitted"},
    "declined": set(),
    "lapsed": set(),
    "admitted": set(),
    "withdrawn": set(),
    "rejected": set(),
}
TERMINAL_APPLICANT = frozenset({"admitted", "withdrawn", "rejected", "declined", "lapsed"})
for _state, _next in APPLICANT_TRANSITIONS.items():
    if _state not in TERMINAL_APPLICANT:
        _next.update({"withdrawn", "rejected"})
# statuses that take part in merit generation / allotment
MERIT_ELIGIBLE = frozenset({"verified", "waitlisted", "merit_listed"})


class ApplicantSource(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    COUNSELLING_IMPORT = "counselling_import"


class ApplicantEntryType(StrEnum):
    REGULAR = "regular"
    LATERAL = "lateral"
    MIGRATION = "migration"


class DocVerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    RESUBMIT = "resubmit"


class MeritListStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class RoundStatus(StrEnum):
    PLANNED = "planned"
    CHOICE_FILLING = "choice_filling"
    ALLOTTED = "allotted"
    REPORTING = "reporting"
    CLOSED = "closed"


ROUND_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"choice_filling", "allotted"},
    "choice_filling": {"planned", "allotted"},
    "allotted": {"reporting", "closed"},
    "reporting": {"closed"},
    "closed": set(),
}


class AllotmentStatus(StrEnum):
    ALLOTTED = "allotted"
    ACCEPTED = "accepted"
    FLOAT = "float"
    FREEZE = "freeze"
    UPGRADED = "upgraded"
    DECLINED = "declined"
    LAPSED = "lapsed"
    ADMITTED = "admitted"


# allotments that hold their seat (``seat_matrix.filled`` counts them)
HOLDING_ALLOTMENTS = frozenset({"allotted", "accepted", "float", "freeze", "admitted"})


class AllotmentAction(StrEnum):
    ACCEPT = "accept"
    FLOAT = "float"
    FREEZE = "freeze"
    DECLINE = "decline"


class OfferType(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"


class OfferStatus(StrEnum):
    ISSUED = "issued"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class EnquirySource(StrEnum):
    WALK_IN = "walk_in"
    WEB = "web"
    PHONE = "phone"
    REFERRAL = "referral"
    EVENT = "event"
    AGENT = "agent"


class EnquiryStage(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    COUNSELLED = "counselled"
    APPLIED = "applied"
    ADMITTED = "admitted"
    LOST = "lost"
