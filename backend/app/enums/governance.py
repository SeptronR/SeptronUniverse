"""Governance: committees, meetings, legal, RTI, audit paras, e-File and policies — Prompts/33 §33.3.

Status vocabularies of section 30 (``committees`` … ``policies``), the statutory committee templates per institution
type seeded by ``0033`` and the Phase 33 settings defaults. ``meetings.status`` gains ``cancelled`` (VARCHAR(20), the DDL
comment lists the four happy-path states only).
"""

from enum import StrEnum
from typing import Any


class CommitteeType(StrEnum):
    BOS = "bos"
    ACADEMIC_COUNCIL = "academic_council"
    EXECUTIVE_COUNCIL = "executive_council"
    SENATE = "senate"
    GOVERNING_BODY = "governing_body"
    ACADEMIC_COMMITTEE = "academic_committee"
    FINANCE = "finance"
    IQAC = "iqac"
    ANTI_RAGGING = "anti_ragging"
    ICC = "icc"
    GRIEVANCE = "grievance"
    RESEARCH_BOARD = "research_board"
    PURCHASE = "purchase"
    DISCIPLINE = "discipline"
    ETHICS = "ethics"
    CUSTOM = "custom"


class MemberType(StrEnum):
    STAFF = "staff"
    EXTERNAL = "external"
    STUDENT = "student"


class MemberRole(StrEnum):
    CHAIR = "chair"
    SECRETARY = "secretary"
    MEMBER = "member"
    CONVENOR = "convenor"
    SPECIAL_INVITEE = "special_invitee"


class MeetingStatus(StrEnum):
    SCHEDULED = "scheduled"
    HELD = "held"
    MINUTES_DRAFT = "minutes_draft"
    MINUTES_APPROVED = "minutes_approved"
    CANCELLED = "cancelled"


class ResolutionStatus(StrEnum):
    PASSED = "passed"
    DEFERRED = "deferred"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"


class AtrStatus(StrEnum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    RETURNED = "returned"


class LegalStatus(StrEnum):
    OPEN = "open"
    HEARING = "hearing"
    JUDGEMENT = "judgement"
    APPEAL = "appeal"
    CLOSED = "closed"


class RtiStatus(StrEnum):
    RECEIVED = "received"
    ASSIGNED = "assigned"
    RESPONDED = "responded"
    APPEALED = "appealed"
    CLOSED = "closed"


class ParaStatus(StrEnum):
    OPEN = "open"
    REPLIED = "replied"
    SETTLED = "settled"
    DROPPED = "dropped"


class EfileStatus(StrEnum):
    OPEN = "open"
    IN_MOVEMENT = "in_movement"
    CLOSED = "closed"


class EfileAction(StrEnum):
    FORWARD = "forward"
    RETURN = "return"
    APPROVE = "approve"
    REJECT = "reject"


class PolicyStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


POLICY_CATEGORIES: tuple[str, ...] = (
    "academic",
    "examination",
    "it",
    "posh",
    "anti_ragging",
    "research_ethics",
    "data_protection",
    "hr",
    "finance",
    "hostel",
    "conduct",
)

# Audit registers (Phase 32) whose paras this phase tracks
PARA_AUDIT_TYPES: tuple[str, ...] = ("financial_statutory", "ag")

# Committees every pack expects (coverage check → Phase 32 evidence 7.1.x)
MANDATORY_COMMITTEES: tuple[str, ...] = ("anti_ragging", "icc", "grievance")

HALF: dict[str, Any] = {"type": "fraction", "value": "1/2"}
THIRD: dict[str, Any] = {"type": "fraction", "value": "1/3"}

# (template_key, name, committee_type, code (resolution numbering), quorum_rule, per_department)
_T = tuple[str, str, str, str, dict[str, Any], bool]
UNIVERSITY_TEMPLATES: tuple[_T, ...] = (
    ("academic_council", "Academic Council", "academic_council", "AC", HALF, False),
    ("executive_council", "Executive Council", "executive_council", "EC", HALF, False),
    ("senate", "Senate / Court", "senate", "SEN", THIRD, False),
    ("finance", "Finance Committee", "finance", "FC", HALF, False),
    ("bos", "Board of Studies", "bos", "BOS", HALF, True),
    ("research_board", "Research Board", "research_board", "RB", HALF, False),
    ("iqac", "Internal Quality Assurance Cell", "iqac", "IQAC", HALF, False),
    ("anti_ragging", "Anti-Ragging Committee", "anti_ragging", "ARC", HALF, False),
    ("icc", "Internal Complaints Committee", "icc", "ICC", HALF, False),
    ("grievance", "Grievance Redressal Committee", "grievance", "GRC", HALF, False),
    ("purchase", "Purchase Committee", "purchase", "PC", HALF, False),
    ("discipline", "Discipline Committee", "discipline", "DSC", HALF, False),
)
COLLEGE_TEMPLATES: tuple[_T, ...] = (
    ("governing_body", "Governing Body", "governing_body", "GB", HALF, False),
    ("academic_committee", "Academic Committee", "academic_committee", "ACM", HALF, False),
    ("bos", "Board of Studies (autonomous)", "bos", "BOS", HALF, True),
    ("iqac", "Internal Quality Assurance Cell", "iqac", "IQAC", HALF, False),
    ("anti_ragging", "Anti-Ragging Committee", "anti_ragging", "ARC", HALF, False),
    ("icc", "Internal Complaints Committee", "icc", "ICC", HALF, False),
    ("grievance", "Grievance Redressal Committee", "grievance", "GRC", HALF, False),
    ("purchase", "Purchase Committee", "purchase", "PC", HALF, False),
    ("discipline", "Discipline Committee", "discipline", "DSC", HALF, False),
)
TYPE_CODES: dict[str, str] = {t[2]: t[3] for t in UNIVERSITY_TEMPLATES + COLLEGE_TEMPLATES} | {
    "ethics": "ETH",
    "custom": "CMT",
}


def committee_templates(institution_type: str | None) -> tuple[_T, ...]:
    """University-type institutions get the university set; colleges / schools the college set."""
    return UNIVERSITY_TEMPLATES if (institution_type or "").startswith("univ") else COLLEGE_TEMPLATES


DEFAULT_GOVERNANCE_SETTINGS: dict[str, Any] = {
    "governance.minutes_approval": "chair",
    "governance.notice_days": 7,
    "governance.atr_due_days": 30,
    "governance.quorum_block": True,
    "rti.response_days": 30,
    "rti.fee_paise": 1000,
    "rti.appeal_days": 30,
    "efile.pendency_sla_days": 7,
    "legal.hearing_reminder_days": [7, 1],
    "policies.ack_required_categories": ["conduct", "it", "posh"],
}
