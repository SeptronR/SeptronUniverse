"""Evaluation & results enums — Prompts/15 §15.3 (values from the section 15 / 16 column comments)."""

from enum import StrEnum


class BundleStatus(StrEnum):
    CREATED = "created"
    CODED = "coded"
    DISPATCHED = "dispatched"
    RECEIVED = "received"
    IN_VALUATION = "in_valuation"
    VALUATED = "valuated"
    DECODED = "decoded"
    ARCHIVED = "archived"


class ScriptStatus(StrEnum):
    RECEIVED = "received"
    CODED = "coded"
    IN_VALUATION = "in_valuation"
    VALUATED = "valuated"
    DISCREPANCY = "discrepancy"
    THIRD_VALUATION = "third_valuation"
    FINALIZED = "finalized"
    MODERATED = "moderated"
    DECODED = "decoded"
    REVALUATION = "revaluation"
    ARCHIVED = "archived"
    DESTROYED = "destroyed"


class CustodyAction(StrEnum):
    CREATED = "created"
    DISPATCHED = "dispatched"
    RECEIVED = "received"
    HANDED_OVER = "handed_over"
    RETURNED = "returned"
    ARCHIVED = "archived"
    DESTROYED = "destroyed"


class EvaluatorType(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class AssignmentStatus(StrEnum):
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    VERIFIED = "verified"


class FinalMarksStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    NEEDS_THIRD = "needs_third"
    MODERATED = "moderated"
    FINAL = "final"


class ModerationType(StrEnum):
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    ADD_FLAT = "add_flat"
    GRACE = "grace"
    NORMALIZE = "normalize"
    CAP = "cap"


class ModerationStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    APPLIED = "applied"
    REVERTED = "reverted"


class RunType(StrEnum):
    PROVISIONAL = "provisional"
    FINAL = "final"
    REVALUATION = "revaluation"
    SUPPLEMENTARY_MERGE = "supplementary_merge"
    CORRECTION = "correction"
    LEGACY_IMPORT = "legacy_import"


class RunStatus(StrEnum):
    QUEUED = "queued"
    COMPUTING = "computing"
    COMPUTED = "computed"
    VERIFIED = "verified"
    APPROVED = "approved"
    PUBLISHED = "published"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ResultAttemptType(StrEnum):
    REGULAR = "regular"
    ARREAR = "arrear"
    IMPROVEMENT = "improvement"
    CREDIT_TRANSFER = "credit_transfer"
    AUDIT = "audit"
    RE_REGISTRATION = "re_registration"
    LEGACY = "legacy"


class ResultStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ABSENT = "absent"
    WITHHELD = "withheld"
    MALPRACTICE = "malpractice"
    DETAINED = "detained"
    INCOMPLETE = "incomplete"
    WITHDRAWN = "withdrawn"
    EXEMPTED = "exempted"
    AUDIT_PASS = "audit_pass"
    AUDIT_FAIL = "audit_fail"


class RowStatus(StrEnum):
    DRAFT = "draft"
    COMPUTED = "computed"
    VERIFIED = "verified"
    APPROVED = "approved"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class TermResultStatus(StrEnum):
    COMPUTED = "computed"
    APPROVED = "approved"
    PUBLISHED = "published"
    WITHHELD = "withheld"
    SUPERSEDED = "superseded"


class Audience(StrEnum):
    STUDENT = "student"
    COLLEGE = "college"
    PUBLIC = "public"


class LegacyImportStatus(StrEnum):
    UPLOADED = "uploaded"
    VALIDATED = "validated"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


ANOMALY_CODES = (
    "MISSING_CIA",
    "ABSENT_WITH_MARKS",
    "ESE_MISSING",
    "GRACE_APPLIED",
    "GRADE_BOUNDARY",
    "WITHHELD_HOLD",
    "MALPRACTICE_PENDING",
)
# grade letters printed for non-graded outcomes
SPECIAL_GRADE = {
    "absent": "AB",
    "withheld": "WH",
    "malpractice": "MP",
    "withdrawn": "W",
    "incomplete": "I",
    "detained": "DT",
}
PASSING = frozenset({"pass", "audit_pass", "exempted"})
