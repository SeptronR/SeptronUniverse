"""Timetable & rooms enums — Prompts/10 §10.3 (values copied from the section 12 column comments of
Database_Schema.sql)."""

from enum import StrEnum


class RoomType(StrEnum):
    CLASSROOM = "classroom"
    LAB = "lab"
    SEMINAR = "seminar"
    AUDITORIUM = "auditorium"
    EXAM_HALL = "exam_hall"
    SMART_CLASS = "smart_class"
    SPORTS = "sports"
    OTHER = "other"


class SlotType(StrEnum):
    LECTURE = "lecture"
    LAB = "lab"
    BREAK = "break"
    LUNCH = "lunch"


class TimetableScope(StrEnum):
    SECTION = "section"
    BATCH = "batch"
    DEPARTMENT = "department"


class TimetableStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SessionType(StrEnum):
    LECTURE = "lecture"
    TUTORIAL = "tutorial"
    LAB = "lab"
    PROJECT = "project"


class WeekPattern(StrEnum):
    ALL = "all"
    ODD = "odd"
    EVEN = "even"


class SubstitutionStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    # not in the DDL comment: a leave-auto request whose leave was cancelled (Prompts/10 §10.6 "withdrawn")
    WITHDRAWN = "withdrawn"


class SubstitutionSource(StrEnum):
    MANUAL = "manual"
    LEAVE_AUTO = "leave_auto"


class SessionStatus(StrEnum):
    SCHEDULED = "scheduled"
    CONDUCTED = "conducted"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


class AttendanceStatus(StrEnum):
    NOT_TAKEN = "not_taken"
    TAKEN = "taken"
    FINALIZED = "finalized"


# only these offerings can be scheduled (Phase 09 status machine)
SCHEDULABLE_OFFERING_STATUSES: frozenset[str] = frozenset({"open", "closed", "in_progress"})
# weekday numbering of ``timetable_entries.day_of_week``: ISO 1 = Monday … 7 = Sunday
DAY_NAMES: dict[int, str] = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
