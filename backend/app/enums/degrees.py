"""Degrees enums — Prompts/18 §18.3 (values from the section 16 column comments)."""

from enum import StrEnum


class AwardType(StrEnum):
    CERTIFICATE = "certificate"
    DIPLOMA = "diploma"
    DEGREE = "degree"
    HONOURS = "honours"
    PG_DIPLOMA = "pg_diploma"
    PHD = "phd"


class AwardStatus(StrEnum):
    RECOMMENDED = "recommended"
    COUNCIL_APPROVED = "council_approved"
    ISSUED = "issued"
    CANCELLED = "cancelled"
    REISSUED = "reissued"


class ConvocationStatus(StrEnum):
    PLANNED = "planned"
    REGISTRATION_OPEN = "registration_open"
    CLOSED = "closed"
    COMPLETED = "completed"


class RegistrationMode(StrEnum):
    IN_PERSON = "in_person"
    ABSENTIA = "absentia"


class CredentialEntityType(StrEnum):
    GRADE_CARD = "grade_card"
    TRANSCRIPT = "transcript"
    DEGREE = "degree"
    PROVISIONAL_CERTIFICATE = "provisional_certificate"


class CredentialChannel(StrEnum):
    DIGILOCKER = "digilocker"
    NAD = "nad"
    ABC = "abc"
    INTERNAL = "internal"


class CredentialStatus(StrEnum):
    PENDING = "pending"
    PUSHED = "pushed"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    REVOKED = "revoked"


LedgerStatus = CredentialStatus

CONVOCATION_FLOW: dict[str, tuple[str, ...]] = {
    "planned": ("registration_open",),
    "registration_open": ("closed",),
    "closed": ("registration_open", "completed"),
    "completed": (),
}

REASONS = (
    "CREDITS_SHORT",
    "BACKLOGS",
    "CGPA_BELOW_MIN",
    "DURATION_EXCEEDED",
    "MANDATORY_NONCREDIT",
    "HOLD_GRADUATION",
    "DUES_PENDING",
)

GOWN_SIZES = ("XS", "S", "M", "L", "XL", "XXL")
