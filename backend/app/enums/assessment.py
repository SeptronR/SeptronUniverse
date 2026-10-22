"""Internal assessment, OBE, LMS, projects and question-bank enums — Prompts/13 §13.3 (values from the section 14
column comments of Database_Schema.sql)."""

from enum import StrEnum


class AssessmentStatus(StrEnum):
    PLANNED = "planned"
    CONDUCTED = "conducted"
    MARKS_ENTRY = "marks_entry"
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    LOCKED = "locked"


EDITABLE = frozenset({AssessmentStatus.PLANNED, AssessmentStatus.CONDUCTED, AssessmentStatus.MARKS_ENTRY})


# components of the Phase 05 scheme that live in internal marks (ESE theory / practical / viva are Phase 14)
from app.enums.academics import ComponentCategory  # noqa: E402

INTERNAL_CATEGORIES = frozenset({ComponentCategory.CIA, ComponentCategory.PROJECT_REVIEW})


class CiaStatus(StrEnum):
    COMPUTED = "computed"
    HOD_APPROVED = "hod_approved"
    LOCKED = "locked"
    SUBMITTED_TO_UNIVERSITY = "submitted_to_university"


class ChangeRequestStatus(StrEnum):
    REQUESTED = "requested"
    HOD_APPROVED = "hod_approved"
    COE_APPROVED = "coe_approved"
    APPLIED = "applied"
    REJECTED = "rejected"


class OutcomeType(StrEnum):
    PEO = "PEO"
    PO = "PO"
    PSO = "PSO"


class BloomLevel(StrEnum):
    REMEMBER = "remember"
    UNDERSTAND = "understand"
    APPLY = "apply"
    ANALYZE = "analyze"
    EVALUATE = "evaluate"
    CREATE = "create"


class ContentType(StrEnum):
    FILE = "file"
    VIDEO = "video"
    LINK = "link"
    TEXT = "text"
    SCORM = "scorm"
    EMBED = "embed"


class AssignmentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


class SubmissionStatus(StrEnum):
    SUBMITTED = "submitted"
    GRADED = "graded"
    RETURNED = "returned"
    RESUBMIT = "resubmit"


QuizStatus = AssignmentStatus


class AttemptStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    AUTO_SUBMITTED = "auto_submitted"
    GRADED = "graded"


class ShowResult(StrEnum):
    IMMEDIATE = "immediate"
    AFTER_CLOSE = "after_close"
    NEVER = "never"


class ProjectType(StrEnum):
    MINI = "mini"
    MAJOR = "major"
    DISSERTATION = "dissertation"
    INTERNSHIP_PROJECT = "internship_project"


class ProjectStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    EVALUATED = "evaluated"


class QuestionType(StrEnum):
    MCQ = "mcq"
    MSQ = "msq"
    TRUE_FALSE = "true_false"
    SHORT = "short"
    LONG = "long"
    NUMERIC = "numeric"
    FILL_BLANK = "fill_blank"
    MATCH = "match"


AUTO_SCORED = frozenset(
    {QuestionType.MCQ, QuestionType.MSQ, QuestionType.TRUE_FALSE, QuestionType.NUMERIC, QuestionType.FILL_BLANK}
)


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class PaperPurpose(StrEnum):
    INTERNAL = "internal"
    QUIZ = "quiz"
    ESE = "ese"
    PRACTICE = "practice"


class PaperStatus(StrEnum):
    DRAFT = "draft"
    FROZEN = "frozen"
    USED = "used"


class LessonStatus(StrEnum):
    PLANNED = "planned"
    DELIVERED = "delivered"
    DEFERRED = "deferred"


COURSE_FILE_ITEMS = (
    ("syllabus", "Syllabus"),
    ("timetable", "Timetable"),
    ("lesson_plan", "Lesson plan"),
    ("question_papers", "Question papers"),
    ("marks", "Internal marks"),
    ("attainment", "CO attainment"),
    ("feedback", "Course feedback"),
)
