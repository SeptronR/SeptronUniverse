"""Affiliation management — Prompts/34 §34.3.

Status vocabularies of section 31 (``affiliation_applications`` … ``exam_centres``), the per-type document checklists,
the Phase 34 settings defaults (``affiliation.*``) and the fee schedule template rows seeded by ``0034`` for the current
academic year.
"""

from enum import StrEnum
from typing import Any


class ApplicationType(StrEnum):
    NEW = "new"
    RENEWAL = "renewal"
    EXTENSION = "extension"
    INTAKE_INCREASE = "intake_increase"
    PROGRAM_ADDITION = "program_addition"
    PROGRAM_CLOSURE = "program_closure"
    AUTONOMY = "autonomy"


class ApplicationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    FEE_PAID = "fee_paid"
    SCRUTINY = "scrutiny"
    INSPECTION_SCHEDULED = "inspection_scheduled"
    INSPECTED = "inspected"
    COMPLIANCE_PENDING = "compliance_pending"
    APPROVED = "approved"
    CONDITIONAL = "conditional"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ApprovalStatus(StrEnum):
    PROVISIONAL = "provisional"
    PERMANENT = "permanent"
    CONDITIONAL = "conditional"
    WITHDRAWN = "withdrawn"


class FeeType(StrEnum):
    AFFILIATION = "affiliation"
    CONTINUATION = "continuation"
    INSPECTION = "inspection"
    INTAKE_INCREASE = "intake_increase"
    EXAM_PROCESSING_PER_STUDENT = "exam_processing_per_student"
    RECOGNITION = "recognition"


class PerUnit(StrEnum):
    FLAT = "flat"
    PER_PROGRAM = "per_program"
    PER_STUDENT = "per_student"


class SubmissionType(StrEnum):
    STUDENT_REGISTRATIONS = "student_registrations"
    COURSE_REGISTRATIONS = "course_registrations"
    CIA_MARKS = "cia_marks"
    ATTENDANCE_ELIGIBILITY = "attendance_eligibility"
    PRACTICAL_MARKS = "practical_marks"
    EXAM_REGISTRATIONS = "exam_registrations"
    INTERNAL_FACULTY_LIST = "internal_faculty_list"


class SubmissionStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    RETURNED = "returned"
    ACCEPTED = "accepted"
    LOCKED = "locked"


OPEN_STATUSES: frozenset[str] = frozenset(
    {"draft", "submitted", "fee_paid", "scrutiny", "inspection_scheduled", "inspected", "compliance_pending"}
)
DECIDED_STATUSES: frozenset[str] = frozenset({"approved", "conditional", "rejected"})
# Types whose decision needs an inspection; renewal / extension only when the last inspection is older than
# ``affiliation.inspection_required_years``
INSPECTION_TYPES: frozenset[str] = frozenset({"new", "program_addition", "intake_increase", "autonomy"})
# Types whose decision cites an Academic / Executive Council resolution when ``governance.minutes`` is on
COUNCIL_TYPES: frozenset[str] = frozenset({"new", "autonomy", "program_addition", "program_closure"})
# Submission types the exam office (COE, ``exams:configure``) accepts / locks; the registrar accepts the rest
EXAM_SUBMISSIONS: frozenset[str] = frozenset(
    {"cia_marks", "attendance_eligibility", "practical_marks", "exam_registrations"}
)
# Types an autonomous college still submits (its examinations are local)
AUTONOMOUS_SUBMISSIONS: frozenset[str] = frozenset(
    {"student_registrations", "course_registrations", "internal_faculty_list"}
)

CHECKLIST_ITEMS: dict[str, str] = {
    "land_building": "Land & building documents",
    "faculty_roster": "Faculty roster with qualifications",
    "labs_library": "Laboratories & library inventory",
    "finance": "Audited financial statements",
    "noc_state": "NOC from the State Government",
    "aicte_approval": "AICTE / statutory council approval",
    "fee_regulatory": "Fee regulatory committee approval",
    "anti_ragging": "Anti-ragging affidavit",
    "migration_plan": "Student migration / teach-out plan",
    "autonomy_report": "Self-study report for autonomy (UGC)",
    "naac_certificate": "NAAC accreditation certificate",
}

DEFAULT_CHECKLISTS: dict[str, list[str]] = {
    "new": [
        "land_building",
        "faculty_roster",
        "labs_library",
        "finance",
        "noc_state",
        "aicte_approval",
        "fee_regulatory",
        "anti_ragging",
    ],
    "renewal": ["faculty_roster", "finance", "anti_ragging"],
    "extension": ["faculty_roster", "finance"],
    "intake_increase": ["faculty_roster", "labs_library", "aicte_approval", "noc_state"],
    "program_addition": ["faculty_roster", "labs_library", "aicte_approval", "noc_state", "finance"],
    "program_closure": ["migration_plan"],
    "autonomy": ["autonomy_report", "naac_certificate", "faculty_roster", "finance"],
}

DEFAULT_SUBMISSION_WINDOWS: dict[str, str] = {
    "student_registrations": "term_start+30d",
    "course_registrations": "term_start+30d",
    "internal_faculty_list": "term_start+30d",
    "attendance_eligibility": "last_instruction_date+3d",
    "cia_marks": "last_instruction_date+7d",
    "practical_marks": "last_instruction_date+10d",
    "exam_registrations": "session_registration_end+2d",
}

DEFAULT_VALIDATION_RULES: dict[str, Any] = {
    "cia_complete": True,
    "marks_within_max": True,
    "eligibility_decided": True,
    "faculty_matches_offerings": True,
}

DEFAULT_AFFILIATION_SETTINGS: dict[str, Any] = {
    "affiliation.document_checklists": DEFAULT_CHECKLISTS,
    "affiliation.inspection_required_years": 3,
    "affiliation.deficiency_compliance_days": 30,
    "affiliation.order_validity_years": {"provisional": 1, "permanent": 5},
    "affiliation.submission_windows": DEFAULT_SUBMISSION_WINDOWS,
    "affiliation.submission_validation_rules": DEFAULT_VALIDATION_RULES,
    "affiliation.results_require_accepted": [
        "cia_marks",
        "attendance_eligibility",
        "practical_marks",
        "exam_registrations",
    ],
    "affiliation.centre_capacity_buffer_pct": 10,
    "affiliation.expiry_reminder_days": 90,
    "affiliation.appeal_as_extension": True,
}

# (fee_type, amount_paise, per_unit) — ``affiliation_fee_schedules`` template rows for the current academic year
FEE_SCHEDULE_TEMPLATE: tuple[tuple[str, int, str], ...] = (
    ("affiliation", 50_000_00, "per_program"),
    ("continuation", 25_000_00, "per_program"),
    ("inspection", 30_000_00, "flat"),
    ("intake_increase", 500_00, "per_student"),
    ("exam_processing_per_student", 150_00, "per_student"),
    ("recognition", 10_000_00, "flat"),
)

# Fee lines charged per application type (inspection is added when the type / age needs one)
FEES_BY_TYPE: dict[str, tuple[str, ...]] = {
    "new": ("affiliation", "recognition"),
    "renewal": ("continuation",),
    "extension": ("continuation",),
    "intake_increase": ("intake_increase",),
    "program_addition": ("affiliation",),
    "program_closure": (),
    "autonomy": ("recognition",),
}
