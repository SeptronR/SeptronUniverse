"""Mentoring, grievances, discipline, surveys & clubs enums and shipped defaults — Prompts/27 §27.3 / §27.2."""

from enum import StrEnum
from typing import Any


class AssignmentStatus(StrEnum):
    ACTIVE = "active"
    REASSIGNED = "reassigned"
    ENDED = "ended"


class BookingStatus(StrEnum):
    BOOKED = "booked"
    ATTENDED = "attended"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class SessionMode(StrEnum):
    IN_PERSON = "in_person"
    ONLINE = "online"
    PHONE = "phone"
    GROUP = "group"


class ReferralStatus(StrEnum):
    REFERRED = "referred"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GrievanceCategory(StrEnum):
    ACADEMIC = "academic"
    EXAM = "exam"
    FEE = "fee"
    HOSTEL = "hostel"
    HARASSMENT = "harassment"
    RAGGING = "ragging"
    DISCRIMINATION = "discrimination"
    INFRASTRUCTURE = "infrastructure"
    OTHER = "other"


class GrievanceCommittee(StrEnum):
    GRIEVANCE_CELL = "grievance_cell"
    ICC = "icc"
    ANTI_RAGGING = "anti_ragging"
    SC_ST_CELL = "sc_st_cell"
    OBC_CELL = "obc_cell"


class GrievanceStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ESCALATED = "escalated"
    REOPENED = "reopened"


class CaseStatus(StrEnum):
    REPORTED = "reported"
    INQUIRY = "inquiry"
    HEARING = "hearing"
    DECIDED = "decided"
    APPEALED = "appealed"
    CLOSED = "closed"


class SanctionType(StrEnum):
    WARNING = "warning"
    FINE = "fine"
    SUSPENSION = "suspension"
    EXPULSION = "expulsion"
    COMMUNITY_SERVICE = "community_service"
    HOSTEL_EVICTION = "hostel_eviction"
    DEBAR_PLACEMENT = "debar_placement"


class SurveyType(StrEnum):
    COURSE = "course"
    FACULTY = "faculty"
    INSTITUTION = "institution"
    COURSE_EXIT = "course_exit"
    PROGRAM_EXIT = "program_exit"
    ALUMNI = "alumni"
    EMPLOYER = "employer"
    HOSTEL = "hostel"
    PARENT = "parent"
    SSS = "sss"


class SurveyStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    ANALYSED = "analysed"


class ClubType(StrEnum):
    TECHNICAL = "technical"
    CULTURAL = "cultural"
    SPORTS = "sports"
    SOCIAL = "social"
    PROFESSIONAL_CHAPTER = "professional_chapter"
    NSS = "nss"
    NCC = "ncc"
    EXTENSION = "extension"


class ClubRole(StrEnum):
    PENDING = "pending"
    MEMBER = "member"
    PRESIDENT = "president"
    VICE_PRESIDENT = "vice_president"
    SECRETARY = "secretary"
    TREASURER = "treasurer"
    COORDINATOR = "coordinator"


class ActivityType(StrEnum):
    NSS = "nss"
    NCC = "ncc"
    COMMUNITY_SERVICE = "community_service"
    CLUB = "club"
    SPORTS = "sports"


class AchievementCategory(StrEnum):
    SPORTS = "sports"
    CULTURAL = "cultural"
    TECHNICAL = "technical"
    RESEARCH = "research"
    HACKATHON = "hackathon"
    OTHER = "other"


CONCERNS: tuple[str, ...] = ("academic", "personal", "financial", "health", "career")
CONFIDENTIAL_CATEGORIES: frozenset[str] = frozenset({"harassment", "ragging", "discrimination"})
COMMITTEE_TYPES: tuple[str, ...] = ("grievance", "icc", "anti_ragging", "sc_st_cell", "obc_cell", "discipline")
# grievance committee code → committees.committee_type
COMMITTEE_TYPE_OF: dict[str, str] = {
    "grievance_cell": "grievance",
    "icc": "icc",
    "anti_ragging": "anti_ragging",
    "sc_st_cell": "sc_st_cell",
    "obc_cell": "obc_cell",
}
SEVERE_SANCTIONS: frozenset[str] = frozenset({"suspension", "expulsion"})
# who verifies which hours: NSS / NCC officers (``clubs:verify_hours``) verify everything; a club advisor only the
# ``club`` hours of their own club; the sports officer ``sports``
ADVISOR_ACTIVITY_TYPES: frozenset[str] = frozenset({"club"})

DEFAULT_RISK_WEIGHTS: dict[str, int] = {
    "attendance": 35,
    "cia": 25,
    "dues": 10,
    "standing": 15,
    "hostel": 5,
    "engagement": 10,
}
DEFAULT_RISK_THRESHOLDS: dict[str, int] = {"medium": 40, "high": 65}
DEFAULT_SLA_HOURS: dict[str, int] = {
    "harassment": 24,
    "ragging": 24,
    "discrimination": 48,
    "exam": 72,
    "fee": 72,
    "academic": 120,
    "hostel": 72,
    "infrastructure": 120,
    "other": 120,
}
DEFAULT_COMMITTEE_ROUTING: dict[str, str] = {
    "harassment": "icc",
    "ragging": "anti_ragging",
    "discrimination": "sc_st_cell|obc_cell",
    "default": "grievance_cell",
}
DEFAULT_SANCTION_SCALE: dict[str, Any] = {
    "minor": ["warning", "community_service"],
    "moderate": ["fine", "community_service", "hostel_eviction"],
    "major": ["suspension", "debar_placement"],
    "gross": ["expulsion"],
    "max_fine_paise": 2500000,
    "appeal_window_days": 15,
}

_LIKERT = {"type": "likert5", "scale": 5, "required": True}
# NAAC SSS (Student Satisfaction Survey) — 20 quantitative items on a 0–4 scale + 1 open comment
SSS_QUESTIONS: list[dict[str, Any]] = [
    {"id": f"q{i}", "text": t, "type": "likert5", "scale": 4, "required": True}
    for i, t in enumerate(
        (
            "How much of the syllabus was covered in the class?",
            "How well did the teachers prepare for the classes?",
            "How well were the teachers able to communicate?",
            "The teacher's approach to teaching can best be described as",
            "Fairness of the internal evaluation process by the teachers",
            "Was your performance in assignments discussed with you?",
            "The institute takes active interest in promoting internship, student exchange, field visit opportunities",
            "The teaching and mentoring process in your institution facilitates you in cognitive, social and "
            "emotional growth",
            "The institution provides multiple opportunities to learn and grow",
            "Teachers inform you about your expected competencies, course outcomes and programme outcomes",
            "Your mentor does a necessary follow-up with an assigned task to you",
            "The teachers illustrate the concepts through examples and applications",
            "The teachers identify your strengths and encourage you with providing right level of challenges",
            "Teachers are able to identify your weaknesses and help you to overcome them",
            "The institution makes effort to engage students in the monitoring, review and continuous quality "
            "improvement of the teaching learning process",
            "The institute/ teachers use student centric methods for enhancing learning experiences",
            "Teachers encourage you to participate in extracurricular activities",
            "Efforts are made by the institute/ teachers to inculcate soft skills, life skills and employability "
            "skills to make you ready for the world of work",
            "What percentage of teachers use ICT tools such as LCD projector, Multimedia, etc. while teaching",
            "The overall quality of teaching-learning process in your institute is very good",
        ),
        start=1,
    )
] + [{"id": "q21", "text": "Give three observation / suggestions to improve the overall teaching", "type": "text"}]

COURSE_FEEDBACK_QUESTIONS: list[dict[str, Any]] = [
    {"id": "c1", "text": "The course objectives and outcomes were made clear", **_LIKERT},
    {"id": "c2", "text": "The teacher covered the syllabus in time", **_LIKERT},
    {"id": "c3", "text": "The teacher explained concepts with examples", **_LIKERT},
    {"id": "c4", "text": "Assessments were fair and returned with feedback", **_LIKERT},
    {"id": "c5", "text": "The teacher was available for doubts outside class", **_LIKERT},
    {"id": "c6", "text": "Overall rating of the course", **_LIKERT},
    {"id": "c7", "text": "Comments", "type": "text", "required": False},
]
HOSTEL_QUESTIONS: list[dict[str, Any]] = [
    {"id": "h1", "text": "Cleanliness of rooms and washrooms", **_LIKERT},
    {"id": "h2", "text": "Quality of mess food", **_LIKERT},
    {"id": "h3", "text": "Safety and security", **_LIKERT},
    {"id": "h4", "text": "Responsiveness of the warden", **_LIKERT},
    {"id": "h5", "text": "Comments", "type": "text", "required": False},
]
PARENT_QUESTIONS: list[dict[str, Any]] = [
    {"id": "p1", "text": "Communication from the institution about my ward", **_LIKERT},
    {"id": "p2", "text": "Academic progress of my ward", **_LIKERT},
    {"id": "p3", "text": "Mentoring support", **_LIKERT},
    {"id": "p4", "text": "Campus safety", **_LIKERT},
    {"id": "p5", "text": "Suggestions", "type": "text", "required": False},
]
SURVEY_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "sss": SSS_QUESTIONS,
    "course": COURSE_FEEDBACK_QUESTIONS,
    "faculty": COURSE_FEEDBACK_QUESTIONS[1:6],
    "hostel": HOSTEL_QUESTIONS,
    "parent": PARENT_QUESTIONS,
}
# survey type → target type of its responses (auto targets)
SURVEY_TARGET_TYPE: dict[str, str] = {
    "course": "offering",
    "course_exit": "offering",
    "faculty": "staff",
    "institution": "institution",
    "sss": "institution",
    "program_exit": "program",
    "alumni": "program",
    "employer": "program",
    "hostel": "hostel",
    "parent": "institution",
}
EXTERNAL_SURVEYS: frozenset[str] = frozenset({"alumni", "employer"})
