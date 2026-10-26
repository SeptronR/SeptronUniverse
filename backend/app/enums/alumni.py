"""Alumni, endowments & fundraising enums and shipped defaults (Prompts/29 §29.3 / §29.2)."""

from enum import StrEnum
from typing import Any


class AlumniEventType(StrEnum):
    MEET = "meet"
    WEBINAR = "webinar"
    REUNION = "reunion"
    MENTORSHIP = "mentorship"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"
    ARCHIVED = "archived"


class DonorType(StrEnum):
    ALUMNI = "alumni"
    CORPORATE = "corporate"
    INDIVIDUAL = "individual"


class DonationMode(StrEnum):
    ONLINE = "online"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    CASH = "cash"
    UPI = "upi"


class JobStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ClaimStatus(StrEnum):
    UNCLAIMED = "unclaimed"
    CLAIMED = "claimed"
    VERIFIED = "verified"
    REJECTED = "rejected"


# every field an alumnus may expose in the directory (the projection is consent ∩ requester class)
DIRECTORY_FIELDS: tuple[str, ...] = (
    "name",
    "batch",
    "program",
    "city",
    "country",
    "company",
    "designation",
    "linkedin_url",
    "email",
    "phone",
)
CONTACT_FIELDS: frozenset[str] = frozenset({"email", "phone"})
# students never see contact details, even when the alumnus consented (Prompts/29 §29.11 step 4 "reduced fields")
STUDENT_FIELDS: frozenset[str] = frozenset({"name", "batch", "program", "city", "company", "designation"})
DEFAULT_DIRECTORY_FIELDS: list[str] = ["name", "batch", "program", "city", "company", "designation"]
ENGAGEMENT_WEIGHTS: dict[str, int] = {
    "profile_update": 5,
    "event_attended": 10,
    "donation": 20,
    "mentoring": 15,
    "job_post": 10,
    "survey": 5,
}
FUNDRAISING_80G: dict[str, Any] = {"registration_no": None, "valid_from": None, "valid_to": None, "signatory": None}
MILESTONES: tuple[int, ...] = (25, 50, 75, 100)
# PAN is mandatory on an 80G receipt above this amount (cash donations above ₹2,000 do not qualify for 80G at all)
PAN_THRESHOLD_PAISE = 200_000
CASH_80G_LIMIT_PAISE = 200_000
PROFILE_FIELDS: tuple[str, ...] = (
    "current_company",
    "designation",
    "city",
    "country",
    "linkedin_url",
    "email",
    "phone",
)
