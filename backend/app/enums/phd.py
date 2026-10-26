"""PhD & research-scholar management enums and the shipped ``phd.rules`` defaults (Prompts/31 §31.2 / §31.3)."""

from enum import StrEnum
from typing import Any


class ScholarMode(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"


class FellowshipType(StrEnum):
    JRF = "jrf"
    SRF = "srf"
    INSTITUTION = "institution"
    PROJECT = "project"
    NONE = "none"


class CourseworkStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXEMPTED = "exempted"


class ScholarStatus(StrEnum):
    ADMITTED = "admitted"
    COURSEWORK = "coursework"
    REGISTERED = "registered"
    SYNOPSIS_SUBMITTED = "synopsis_submitted"
    THESIS_SUBMITTED = "thesis_submitted"
    UNDER_EVALUATION = "under_evaluation"
    VIVA_SCHEDULED = "viva_scheduled"
    AWARDED = "awarded"
    DISCONTINUED = "discontinued"


# forward order of the lifecycle; ``discontinued`` is reachable from any pre-award state
STATUS_ORDER: tuple[str, ...] = tuple(s.value for s in ScholarStatus if s is not ScholarStatus.DISCONTINUED)
PRE_AWARD: frozenset[str] = frozenset(STATUS_ORDER[:-1])


class DcMeetingStatus(StrEnum):
    SCHEDULED = "scheduled"
    HELD = "held"
    APPROVED = "approved"


class ProgressStatus(StrEnum):
    SUBMITTED = "submitted"
    GUIDE_REVIEWED = "guide_reviewed"
    DC_REVIEWED = "dc_reviewed"


class DcRating(StrEnum):
    SATISFACTORY = "satisfactory"
    UNSATISFACTORY = "unsatisfactory"


class FellowshipStatus(StrEnum):
    ACTIVE = "active"
    HELD = "held"
    CLOSED = "closed"


class DisbursementStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    HELD = "held"


class RequestType(StrEnum):
    EXTENSION = "extension"
    CHANGE_OF_GUIDE = "change_of_guide"
    MODE_CHANGE = "mode_change"
    LEAVE = "leave"
    COURSEWORK_EXEMPTION = "coursework_exemption"
    CANCELLATION_REVIEW = "cancellation_review"


class RequestStatus(StrEnum):
    REQUESTED = "requested"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ThesisStage(StrEnum):
    PRE_SYNOPSIS = "pre_synopsis"
    SYNOPSIS = "synopsis"
    THESIS = "thesis"
    REVISED_THESIS = "revised_thesis"


class ThesisStatus(StrEnum):
    SUBMITTED = "submitted"
    PLAGIARISM_CHECKED = "plagiarism_checked"
    DC_APPROVED = "dc_approved"
    REJECTED = "rejected"


class ExaminerStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    INVITED = "invited"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REPORT_RECEIVED = "report_received"


class Recommendation(StrEnum):
    ACCEPT = "accept"
    MINOR = "minor"
    MAJOR = "major"
    REJECT = "reject"


class VivaResult(StrEnum):
    RECOMMENDED = "recommended"
    RE_VIVA = "re_viva"
    NOT_RECOMMENDED = "not_recommended"


class EtdStatus(StrEnum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"


class EtdRepository(StrEnum):
    SHODHGANGA = "shodhganga"
    INSTITUTIONAL = "institutional"


class DcRole(StrEnum):
    CONVENOR = "convenor"
    MEMBER = "member"
    EXTERNAL = "external"


# UGC (Minimum Standards and Procedures for Award of PhD Degree) Regulations 2022 defaults from the IN pack
DEFAULT_PHD_RULES: dict[str, Any] = {
    "guide_load_by_cadre": {"professor": 8, "associate": 6, "assistant": 4},
    "coursework_min_credits": 12,
    "methodology_course_codes": ["RM", "RESEARCH METHODOLOGY"],
    "coursework_deadline_months": 12,
    "progress_report_months": 6,
    "progress_grace_days": 30,
    "unsatisfactory_limit": 2,
    "min_duration_months": 24,
    "max_duration_months": 72,
    "extension_max_months": 24,
    "relaxation_months": {"women": 24, "pwd": 24},
    "duration_warning_months": 6,
    "similarity_max_pct": 10,
    "ai_declaration_required": True,
    "examiners_min_external": 2,
    "examiners_outside_state": 1,
    "coi_coauthor_years": 3,
    "viva_after": ["accept", "minor"],
    "re_viva_max": 1,
    "thesis_within_months_of_synopsis": 6,
    "pre_submission_requirements": {"journal_papers": 1, "conference_presentations": 2},
    "dc_min_external": 1,
    "etd_deadline_days": 30,
    "hide_examiners_from_scholar": True,
    "examiner_report_due_days": 60,
    "fellowship_defaults": {
        "jrf": {"monthly_paise": 3700000, "hra_pct": 24},
        "srf": {"monthly_paise": 4200000, "hra_pct": 24},
        "institution": {"monthly_paise": 2500000, "hra_pct": 0},
        "project": {"monthly_paise": 3100000, "hra_pct": 0},
    },
    "contingency_yearly_paise": {"jrf": 2000000, "srf": 2500000, "institution": 1000000, "project": 0},
    "jrf_to_srf_months": 24,
    "leave_fellowship_hold": {"maternity": False, "medical": False, "other": True},
    "thesis_fee_paise": 0,
    "examiner_remuneration_paise": 500000,
}
