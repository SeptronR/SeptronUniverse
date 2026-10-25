"""Placement, internships & training enums and shipped defaults (Prompts/28 §28.3)."""

from enum import StrEnum
from typing import Any


class CompanyTier(StrEnum):
    DREAM = "dream"
    SUPER_DREAM = "super_dream"
    CORE = "core"
    MASS = "mass"


class JobType(StrEnum):
    FULL_TIME = "full_time"
    INTERNSHIP = "internship"
    INTERN_PPO = "intern_ppo"
    PART_TIME = "part_time"


class DriveMode(StrEnum):
    ON_CAMPUS = "on_campus"
    OFF_CAMPUS = "off_campus"
    VIRTUAL = "virtual"
    POOLED = "pooled"


class DriveStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RoundType(StrEnum):
    PRE_PLACEMENT_TALK = "pre_placement_talk"
    APTITUDE = "aptitude"
    CODING = "coding"
    GD = "gd"
    TECHNICAL = "technical"
    HR = "hr"
    FINAL = "final"


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    INELIGIBLE = "ineligible"
    SHORTLISTED = "shortlisted"
    IN_PROCESS = "in_process"
    REJECTED = "rejected"
    SELECTED = "selected"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_DECLINED = "offer_declined"
    WITHDRAWN = "withdrawn"
    ABSENT = "absent"


class RoundResultStatus(StrEnum):
    CLEARED = "cleared"
    NOT_CLEARED = "not_cleared"
    ABSENT = "absent"
    PENDING = "pending"


class OfferStatus(StrEnum):
    OFFERED = "offered"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    JOINED = "joined"
    NOT_JOINED = "not_joined"


class PlacementStatus(StrEnum):
    UNPLACED = "unplaced"
    PLACED = "placed"
    MULTIPLE = "multiple"
    OPTED_OUT = "opted_out"


class OptOutReason(StrEnum):
    HIGHER_STUDIES = "higher_studies"
    ENTREPRENEURSHIP = "entrepreneurship"
    FAMILY_BUSINESS = "family_business"
    GOVT_EXAMS = "govt_exams"
    OTHER = "other"


class InternshipStatus(StrEnum):
    PLANNED = "planned"
    ONGOING = "ongoing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TrainingType(StrEnum):
    APTITUDE = "aptitude"
    SOFT_SKILLS = "soft_skills"
    TECHNICAL = "technical"
    MOCK_INTERVIEW = "mock_interview"


DRIVE_TRANSITIONS: dict[str, dict[str, str]] = {
    "publish": {"draft": "open"},
    "close": {"open": "closed"},
    "start": {"open": "in_progress", "closed": "in_progress"},
    "complete": {"in_progress": "completed", "closed": "completed"},
    "cancel": {"draft": "cancelled", "open": "cancelled", "closed": "cancelled", "in_progress": "cancelled"},
}
# offers that hold a seat against the policy (max_offers)
HOLDING_OFFER = ("accepted", "joined")
DREAM_TIERS = ("dream", "super_dream")

ELIGIBILITY_DEFAULTS: dict[str, Any] = {
    "min_cgpa": 6.0,
    "max_active_backlogs": 0,
    "max_history_backlogs": 2,
    "min_10th_pct": 60,
    "min_12th_pct": 60,
    "max_gap_years": 1,
    "allowed_if_already_placed": False,
}
POLICY_DEFAULTS: dict[str, Any] = {
    "max_offers": 1,
    "dream_ctc_threshold_paise": 100000000,
    "allow_upgrade_if_dream": True,
    "opt_out_allowed": True,
}
CONSENTED_FIELDS: list[str] = [
    "name",
    "program",
    "cgpa",
    "backlogs",
    "resume",
    "skills",
    "achievements",
    "email",
    "phone",
]
BLACKLIST_RULES: dict[str, int] = {"no_show_after_shortlist": 2, "offer_decline_after_accept": 1}
RESUME_TEMPLATES: list[dict[str, str]] = [
    {"key": "resume_classic", "name": "Classic (single column)"},
    {"key": "resume_modern", "name": "Modern (two column)"},
    {"key": "resume_compact", "name": "Compact (one page)"},
]
RESUME_SECTIONS = ("summary", "education", "projects", "internships", "skills", "certifications", "achievements")

# reason codes returned by the eligibility engine
REASONS = {
    "CGPA": "CGPA below the drive minimum",
    "ACTIVE_BACKLOGS": "Active backlogs above the limit",
    "HISTORY_BACKLOGS": "History of backlogs above the limit",
    "PCT_10": "10th percentage below the minimum",
    "PCT_12": "12th percentage below the minimum",
    "GAP_YEARS": "Gap years above the limit",
    "PROGRAM": "Programme not in the drive",
    "BATCH": "Batch not in the drive",
    "ATTENDANCE": "Attendance below the minimum",
    "SKILLS": "None of the required skills",
    "ALREADY_PLACED": "Already placed (only dream upgrades allowed)",
    "MAX_OFFERS": "Maximum offers already accepted",
    "OPTED_OUT": "Opted out of placements",
    "BLACKLISTED": "Blacklisted from placements",
    "DEBARRED": "Debarred from placements (discipline)",
    "HOLD": "An active hold blocks placements",
    "INACTIVE": "Enrolment not active",
}
