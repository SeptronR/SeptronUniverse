"""Institution structure / academic session enums — Prompts/03 §03.3 (values copied from Database_Schema.sql §2, §7)."""

from enum import StrEnum


class InstitutionType(StrEnum):
    UNIVERSITY = "university"
    DEEMED_UNIVERSITY = "deemed_university"
    AUTONOMOUS_COLLEGE = "autonomous_college"
    AFFILIATED_COLLEGE = "affiliated_college"
    STANDALONE_COLLEGE = "standalone_college"
    MULTI_CAMPUS = "multi_campus"


class InstitutionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class CollegeType(StrEnum):
    CONSTITUENT = "constituent"
    AFFILIATED = "affiliated"
    AUTONOMOUS = "autonomous"
    CAMPUS = "campus"
    DEEMED_UNIT = "deemed_unit"
    STUDY_CENTRE = "study_centre"
    MAIN = "main"


class DepartmentType(StrEnum):
    ACADEMIC = "academic"
    ADMINISTRATIVE = "administrative"
    RESEARCH_CENTRE = "research_centre"


class TermType(StrEnum):
    ODD = "odd"
    EVEN = "even"
    SUMMER = "summer"
    TRIMESTER = "trimester"
    ANNUAL = "annual"


class TermStatus(StrEnum):
    PLANNED = "planned"
    REGISTRATION = "registration"
    IN_PROGRESS = "in_progress"
    EXAM = "exam"
    RESULT_PROCESSING = "result_processing"
    CLOSED = "closed"


# forward-only order of the term status machine (Prompts/03 §03.6 academic_session_service rule 3)
TERM_STATUS_ORDER: tuple[TermStatus, ...] = (
    TermStatus.PLANNED,
    TermStatus.REGISTRATION,
    TermStatus.IN_PROGRESS,
    TermStatus.EXAM,
    TermStatus.RESULT_PROCESSING,
    TermStatus.CLOSED,
)


class HolidayType(StrEnum):
    PUBLIC = "public"
    INSTITUTION = "institution"
    RESTRICTED = "restricted"
    EXAM_BREAK = "exam_break"


class HolidayAppliesTo(StrEnum):
    ALL = "all"
    STUDENTS = "students"
    STAFF = "staff"


class ResetPolicy(StrEnum):
    NEVER = "never"
    YEARLY = "yearly"
    PER_TERM = "per_term"
