"""Programmes, regulations & curriculum enums — Prompts/05 §05.3 (values copied from Database_Schema.sql §7 comments
and docs/Academic_Core_Design.md §1a)."""

from enum import StrEnum


class ProgramLevel(StrEnum):
    CERTIFICATE = "certificate"
    DIPLOMA = "diploma"
    UG = "ug"
    PG = "pg"
    PG_DIPLOMA = "pg_diploma"
    INTEGRATED = "integrated"
    MPHIL = "mphil"
    PHD = "phd"


class ProgramMode(StrEnum):
    REGULAR = "regular"
    PART_TIME = "part_time"
    DISTANCE = "distance"
    ONLINE = "online"


class ProgramStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class TermPattern(StrEnum):
    SEMESTER = "semester"
    YEAR = "year"
    TRIMESTER = "trimester"


class ExamAuthority(StrEnum):
    UNIVERSITY = "university"
    AUTONOMOUS_COLLEGE = "autonomous_college"


class RegulationStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class ProgramRegulationStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class CourseType(StrEnum):
    CORE = "core"
    PROGRAM_ELECTIVE = "program_elective"
    OPEN_ELECTIVE = "open_elective"
    LAB = "lab"
    INTEGRATED_LAB = "integrated_lab"
    PROJECT = "project"
    INTERNSHIP = "internship"
    SEMINAR = "seminar"
    MOOC = "mooc"
    AUDIT = "audit"
    MANDATORY_NON_CREDIT = "mandatory_non_credit"
    ABILITY_ENHANCEMENT = "ability_enhancement"
    SKILL_ENHANCEMENT = "skill_enhancement"
    VALUE_ADDED = "value_added"
    MINOR = "minor"
    HONOURS = "honours"


NON_CREDIT_COURSE_TYPES = frozenset({CourseType.AUDIT, CourseType.MANDATORY_NON_CREDIT})


class CourseStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    ACTIVE = "active"
    RETIRED = "retired"


# draft → approved → active → retired (one step forward; retire from any live state)
COURSE_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"approved"}),
    "approved": frozenset({"active", "draft", "retired"}),
    "active": frozenset({"retired"}),
    "retired": frozenset(),
}


class PrereqRelation(StrEnum):
    PREREQUISITE = "prerequisite"
    COREQUISITE = "corequisite"
    ANTIREQUISITE = "antirequisite"


class BasketType(StrEnum):
    PROGRAM_ELECTIVE = "program_elective"
    OPEN_ELECTIVE = "open_elective"
    MINOR = "minor"
    HONOURS = "honours"
    MOOC = "mooc"
    VERTICAL = "vertical"


class AllocationMode(StrEnum):
    PRIORITY_CGPA = "priority_cgpa"
    FCFS = "fcfs"
    LOTTERY = "lottery"
    MANUAL = "manual"


class BatchStatus(StrEnum):
    ACTIVE = "active"
    GRADUATING = "graduating"
    GRADUATED = "graduated"
    CLOSED = "closed"


class EntryType(StrEnum):
    REGULAR = "regular"
    LATERAL = "lateral"


class ScaleType(StrEnum):
    ABSOLUTE = "absolute"
    RELATIVE = "relative"


class ComponentCategory(StrEnum):
    CIA = "cia"
    ESE_THEORY = "ese_theory"
    ESE_PRACTICAL = "ese_practical"
    VIVA = "viva"
    PROJECT_REVIEW = "project_review"


CREDIT_BUCKETS = ("HS", "BS", "ES", "PC", "PE", "OE", "EEC", "MC", "VAC", "AEC", "SEC")
