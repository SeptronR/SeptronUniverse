"""Student enums — Prompts/07 §07.3 (values copied from the section 8 column comments of Database_Schema.sql)."""

from enum import StrEnum


class Gender(StrEnum):
    MALE = "M"
    FEMALE = "F"
    OTHER = "O"


class StudentStatus(StrEnum):
    PROVISIONAL = "provisional"
    ADMITTED = "admitted"
    ACTIVE = "active"
    ON_BREAK = "on_break"
    DETAINED = "detained"
    DROPPED_OUT = "dropped_out"
    TRANSFERRED = "transferred"
    EXITED = "exited"
    GRADUATED = "graduated"
    ALUMNI = "alumni"
    EXPELLED = "expelled"
    DECEASED = "deceased"


# statuses that end the student's institutional life — the user account is deactivated (graduates/alumni keep theirs)
TERMINAL_STATUSES = frozenset(
    {
        StudentStatus.DROPPED_OUT,
        StudentStatus.TRANSFERRED,
        StudentStatus.EXITED,
        StudentStatus.EXPELLED,
        StudentStatus.DECEASED,
    }
)
# statuses that occupy a seat (plan seat limit, audiences)
SEATED_STATUSES = frozenset(
    {
        StudentStatus.PROVISIONAL,
        StudentStatus.ADMITTED,
        StudentStatus.ACTIVE,
        StudentStatus.ON_BREAK,
        StudentStatus.DETAINED,
    }
)


class EntryType(StrEnum):
    REGULAR = "regular"
    LATERAL = "lateral"
    MIGRATED = "migrated"
    READMISSION = "readmission"
    EXIT_REENTRY = "exit_reentry"


class EnrollmentStatus(StrEnum):
    ACTIVE = "active"
    BREAK = "break"
    DETAINED = "detained"
    COMPLETED = "completed"
    EXITED_EARLY = "exited_early"
    WITHDRAWN = "withdrawn"
    TRANSFERRED = "transferred"
    EXPELLED = "expelled"


# the partial unique index ``one_active_enrollment`` covers exactly these
OPEN_ENROLLMENT = ("active", "break", "detained")


class TermRecordStatus(StrEnum):
    PENDING_REGISTRATION = "pending_registration"
    REGISTERED = "registered"
    IN_PROGRESS = "in_progress"
    EXAM_PENDING = "exam_pending"
    COMPLETED = "completed"
    DETAINED = "detained"
    ON_BREAK = "on_break"
    WITHDRAWN = "withdrawn"


class HoldType(StrEnum):
    REGISTRATION = "registration"
    EXAM = "exam"
    TRANSCRIPT = "transcript"
    GRADUATION = "graduation"
    HOSTEL = "hostel"
    LIBRARY = "library"
    ALL = "all"


class AcademicStanding(StrEnum):
    GOOD = "good"
    WARNING = "warning"
    PROBATION = "probation"
    DISMISSAL = "dismissal"


STANDING_SEVERITY = {"good": 0, "warning": 1, "probation": 2, "dismissal": 3}


class TransferType(StrEnum):
    MIGRATION_IN = "migration_in"
    MIGRATION_OUT = "migration_out"
    INTER_COLLEGE = "inter_college"
    PROGRAM_CHANGE = "program_change"
    INTER_UNIVERSITY = "inter_university"


class TransferStatus(StrEnum):
    REQUESTED = "requested"
    DUES_CHECK = "dues_check"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class CreditTransferSource(StrEnum):
    SWAYAM = "swayam"
    NPTEL = "nptel"
    COURSERA = "coursera"
    OTHER_MOOC = "other_mooc"
    ABC = "abc"
    OTHER_UNIVERSITY = "other_university"
    PRIOR_LEARNING = "prior_learning"
    INTERNAL_PRIOR = "internal_prior"


MOOC_SOURCES = frozenset({"swayam", "nptel", "coursera", "other_mooc"})


class CreditTransferStatus(StrEnum):
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    APPROVED = "approved"
    REJECTED = "rejected"
    CREDITED = "credited"


class UndertakingType(StrEnum):
    ANTI_RAGGING = "anti_ragging"
    CONDUCT = "conduct"
    HOSTEL_RULES = "hostel_rules"
    DATA_CONSENT = "data_consent"
    PHOTO_CONSENT = "photo_consent"
    CUSTOM = "custom"


class GuardianRelation(StrEnum):
    FATHER = "father"
    MOTHER = "mother"
    GUARDIAN = "guardian"
    SPOUSE = "spouse"
    OTHER = "other"


class Gate(StrEnum):
    """Actions a hold (``hold_type`` or ``all``) or a pending undertaking blocks — ``assert_clear(enrollment, gate)``."""

    REGISTRATION = "registration"
    EXAM = "exam"
    TRANSCRIPT = "transcript"
    GRADUATION = "graduation"
    HOSTEL = "hostel"
    LIBRARY = "library"
