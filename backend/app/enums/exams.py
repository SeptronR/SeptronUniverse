"""Exam administration enums — Prompts/14 §14.3 (values from the section 15 column comments)."""

from enum import StrEnum


class ExamKind(StrEnum):
    REGULAR = "regular"
    SUPPLEMENTARY = "supplementary"
    ARREAR = "arrear"
    IMPROVEMENT = "improvement"
    SPECIAL = "special"
    SUMMER = "summer"
    PRACTICAL = "practical"


class ExamSessionStatus(StrEnum):
    DRAFT = "draft"
    REGISTRATION_OPEN = "registration_open"
    REGISTRATION_CLOSED = "registration_closed"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    VALUATION = "valuation"
    RESULT_PROCESSING = "result_processing"
    RESULTS_PUBLISHED = "results_published"
    CLOSED = "closed"


SESSION_FLOW = [s.value for s in ExamSessionStatus]


class PaperType(StrEnum):
    THEORY = "theory"
    PRACTICAL = "practical"
    PROJECT_VIVA = "project_viva"
    DISSERTATION = "dissertation"
    ONLINE = "online"


class SessionSlot(StrEnum):
    FN = "FN"
    AN = "AN"
    EVE = "EVE"


class PaperStatus(StrEnum):
    PLANNED = "planned"
    QP_READY = "qp_ready"
    CONDUCTED = "conducted"
    SCRIPTS_RECEIVED = "scripts_received"
    VALUATION = "valuation"
    FINALIZED = "finalized"


class ExamRegistrationStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    FEE_PENDING = "fee_pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    DEBARRED = "debarred"


class AttemptType(StrEnum):
    REGULAR = "regular"
    ARREAR = "arrear"
    IMPROVEMENT = "improvement"
    GRADE_IMPROVEMENT = "grade_improvement"


class ItemEligibility(StrEnum):
    ELIGIBLE = "eligible"
    CONDONED = "condoned"
    DETAINED = "detained"
    DEBARRED = "debarred"
    PENDING = "pending"


SEATABLE = frozenset({ItemEligibility.ELIGIBLE, ItemEligibility.CONDONED})


class ItemStatus(StrEnum):
    REGISTERED = "registered"
    CANCELLED = "cancelled"
    ABSENT = "absent"
    APPEARED = "appeared"
    MALPRACTICE = "malpractice"
    WITHHELD = "withheld"


class InvigilationRole(StrEnum):
    CHIEF_SUPERINTENDENT = "chief_superintendent"
    HALL_SUPERINTENDENT = "hall_superintendent"
    INVIGILATOR = "invigilator"
    RELIEVER = "reliever"
    FLYING_SQUAD = "flying_squad"
    OBSERVER = "observer"


class DutyStatus(StrEnum):
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    SWAP_REQUESTED = "swap_requested"
    SWAPPED = "swapped"
    ABSENT = "absent"
    COMPLETED = "completed"


class HallAttendanceStatus(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    MALPRACTICE = "malpractice"


class QpAssignmentStatus(StrEnum):
    INVITED = "invited"
    ACCEPTED = "accepted"
    SUBMITTED = "submitted"
    SCRUTINISED = "scrutinised"
    APPROVED = "approved"
    SELECTED = "selected"
    PRINTED = "printed"
    REJECTED = "rejected"


class MalpracticeCategory(StrEnum):
    COPYING = "copying"
    IMPERSONATION = "impersonation"
    DEVICE = "device"
    MATERIAL = "material"
    MISCONDUCT = "misconduct"
    TAMPERING = "tampering"
    OTHER = "other"
