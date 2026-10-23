"""Post-result schemas — Prompts/16 §16.4."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- revaluation family ------------------------------------------------------------------------------------------------
class RevalEligibleItem(BaseModel):
    exam_registration_item_id: uuid.UUID
    result_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    letter_grade: str | None = None
    result_status: str
    allowed_types: list[str]
    fees: dict[str, int]
    window_ends_at: datetime | None = None
    existing: dict[str, str] = {}


class RevalEligibilityResponse(BaseModel):
    session_id: uuid.UUID
    items: list[RevalEligibleItem]


class RevalCreate(_Strict):
    exam_registration_item_id: uuid.UUID
    request_type: Literal["retotaling", "photocopy", "revaluation", "challenge"]


class RevalResponse(BaseModel):
    id: uuid.UUID
    exam_session_id: uuid.UUID
    exam_registration_item_id: uuid.UUID
    request_type: str
    status: str
    fee_invoice_id: uuid.UUID | None = None
    fee_paise: int = 0
    invoice_status: str | None = None
    original_marks: Decimal | None = None
    revised_marks: Decimal | None = None
    delta: Decimal | None = None
    refund_due: bool
    photocopy_ready: bool = False
    course_code: str | None = None
    student_name: str | None = None
    registration_number: str | None = None
    evaluator_assignment_id: uuid.UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime


class RevalAssignRequest(_Strict):
    evaluator_staff_id: uuid.UUID | None = None
    external_evaluator: dict[str, Any] | None = None
    due_at: datetime | None = None


class RevalMarks(_Strict):
    marks: Decimal = Field(ge=0, le=1000)
    question_wise: dict[str, Decimal] | None = None


class RetotalRequest(_Strict):
    revised_marks: Decimal = Field(ge=0, le=1000)
    remarks: str | None = Field(default=None, max_length=2000)


class RevalDecision(_Strict):
    revised_marks: Decimal | None = Field(default=None, ge=0, le=1000)
    decision: Literal["marks_changed", "no_change", "rejected"] | None = Field(
        default=None, description="omit to apply the min-delta rule"
    )
    remarks: str | None = Field(default=None, max_length=2000)


class RevalScript(BaseModel):
    reval_request_id: uuid.UUID
    answer_script_id: uuid.UUID
    dummy_number: str
    pages: int | None = None
    scan_available: bool = False
    max_marks: Decimal
    request_type: str
    status: str
    due_at: datetime | None = None
    marks: Decimal | None = None


class ChallengePanelRequest(_Strict):
    request_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    evaluator_staff_ids: list[uuid.UUID] = Field(min_length=2, max_length=2)
    due_at: datetime | None = None


class RevalApplyResponse(BaseModel):
    requests: int
    run_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None


# ---- supplementary --------------------------------------------------------------------------------------------------------
class SupplementaryCreateRequest(_Strict):
    term_id: uuid.UUID
    exam_kind: Literal["supplementary", "arrear"] = "supplementary"
    from_session_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=120)
    fee_rules: dict[str, int] | None = None


class SupplementaryPreview(BaseModel):
    students: int
    papers: list[dict[str, Any]]


# ---- malpractice ------------------------------------------------------------------------------------------------------------
class MalpracticeCaseCreate(_Strict):
    exam_registration_item_id: uuid.UUID
    category: Literal["copying", "impersonation", "device", "material", "misconduct", "tampering", "other"]
    invigilator_report: str = Field(min_length=3, max_length=4000)
    evidence: list[dict[str, Any]] | None = None


class InquiryUpdate(_Strict):
    committee_id: uuid.UUID | None = None
    hearing_at: datetime | None = None
    invalidate_paper: bool = False


class StudentStatementSubmit(_Strict):
    text: str = Field(min_length=3, max_length=8000)
    attachments: list[str] = []


class MalpracticeDecision(_Strict):
    punishment: Literal["none", "warning", "cancel_paper", "cancel_session", "debar_terms", "expel"]
    debar_terms: int | None = Field(default=None, ge=1, le=8)
    decision_text: str = Field(min_length=3, max_length=8000)


class AppealCreate(_Strict):
    grounds: str = Field(min_length=10, max_length=8000)
    attachments: list[str] = []


class AppealDecision(_Strict):
    outcome: Literal["uphold", "modify"]
    punishment: Literal["none", "warning", "cancel_paper", "cancel_session", "debar_terms", "expel"] | None = None
    debar_terms: int | None = Field(default=None, ge=1, le=8)
    decision_text: str = Field(min_length=3, max_length=8000)


class MalpracticeCaseResponse(BaseModel):
    id: uuid.UUID
    case_number: str
    exam_session_id: uuid.UUID
    exam_registration_item_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    course_code: str | None = None
    category: str
    evidence: list[dict[str, Any]] | None = None
    invigilator_report: str | None = None
    student_statement: str | None = None
    committee_id: uuid.UUID | None = None
    hearing_at: datetime | None = None
    punishment: str | None = None
    debar_until_term_id: uuid.UUID | None = None
    decision_text: str | None = None
    decided_at: datetime | None = None
    status: str
    reported_at: datetime
    timeline: list[dict[str, Any]] = []
    run_id: uuid.UUID | None = None


# ---- withheld / detention ----------------------------------------------------------------------------------------------------
class WithheldRow(BaseModel):
    result_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    registration_number: str | None = None
    student_name: str | None = None
    course_code: str | None = None
    reasons: list[str]
    releasable: bool


class WithheldReleaseRequest(_Strict):
    result_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=3, max_length=2000)


class DetentionRow(BaseModel):
    student_program_enrollment_id: uuid.UUID
    student_term_record_id: uuid.UUID
    registration_number: str | None = None
    student_name: str | None = None
    term_number: int
    attendance_pct: Decimal | None = None
    detained_courses: list[str] = []
    readmission: dict[str, Any] | None = None


class ReadmissionRequest(_Strict):
    enrollment_id: uuid.UUID
    term_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=2000)


class ReadmissionResponse(BaseModel):
    id: uuid.UUID
    enrollment_id: uuid.UUID
    term_id: uuid.UUID | None = None
    status: str
    reason: str | None = None
    started_at: datetime
    new_term_record_id: uuid.UUID | None = None


class WorkflowDecisionBody(_Strict):
    comment: str | None = Field(default=None, max_length=2000)


# ---- transcripts ----------------------------------------------------------------------------------------------------------------
class TranscriptTypeOut(BaseModel):
    transcript_type: str
    fee_paise: int
    requires_no_dues: bool


class TranscriptRequestCreate(_Strict):
    transcript_type: Literal["provisional", "consolidated", "final", "duplicate", "migration"] = "consolidated"
    copies: int = Field(default=1, ge=1, le=20)
    delivery: Literal["digital", "pickup", "post"] = "digital"
    purpose: str | None = Field(default=None, max_length=200)
    enrollment_id: uuid.UUID | None = Field(default=None, description="staff requests on behalf of a student")


class TranscriptResponse(BaseModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    transcript_type: str
    document_number: str | None = None
    verification_token: str | None = None
    fee_invoice_id: uuid.UUID | None = None
    invoice_status: str | None = None
    workflow_instance_id: uuid.UUID | None = None
    requested_at: datetime
    issued_at: datetime | None = None
    copies: int
    status: str
    superseded: bool = False


class TranscriptIssueRequest(_Strict):
    delivery: Literal["digital", "pickup", "post"] = "digital"
    remarks: str | None = Field(default=None, max_length=2000)


class TranscriptVerifyResponse(BaseModel):
    valid: bool
    document_type: str = "transcript"
    document_number: str | None = None
    transcript_type: str | None = None
    holder_name: str | None = None
    registration_number: str | None = None
    cgpa: Decimal | None = None
    credits_earned: Decimal | None = None
    hash: str | None = None
    superseded: bool = False
    issued_at: datetime | None = None
    institution: str | None = None
    message: str | None = None


# ---- rank lists, medals, corrections -------------------------------------------------------------------------------------------
class RankListEntry(BaseModel):
    rank: int
    student_program_enrollment_id: uuid.UUID | None = None
    student_masked: str
    registration_number: str | None = None
    sgpa: Decimal | None = None
    cgpa: Decimal | None = None
    credits: Decimal | None = None
    tie_break: str | None = None


class RankListResponse(BaseModel):
    batch_id: uuid.UUID
    term_id: uuid.UUID | None = None
    cumulative: bool
    program_id: uuid.UUID | None = None
    entries: list[RankListEntry]
    published_at: datetime | None = None
    key: str | None = None


class RankListPublish(_Strict):
    batch_id: uuid.UUID
    term_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    top_n: int = Field(default=10, ge=1, le=500)
    public: bool = False


class MedalAwardCreate(_Strict):
    batch_id: uuid.UUID
    medal: Literal["gold", "silver", "bronze"]
    student_program_enrollment_id: uuid.UUID
    citation: str | None = Field(default=None, max_length=200)


class MedalResponse(BaseModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    title: str
    position: str | None = None
    level: str | None = None
    held_on: date | None = None
    student_name: str | None = None
    registration_number: str | None = None


class CorrectionRequestCreate(_Strict):
    result_id: uuid.UUID
    reason: str = Field(min_length=5, max_length=2000)
    evidence: str | None = Field(default=None, max_length=2000)
    ese_delta: Decimal = Field(default=Decimal(0), ge=-1000, le=1000, description="ESE marks change to apply")


class CorrectionResponse(BaseModel):
    id: uuid.UUID
    result_id: uuid.UUID | None = None
    status: str
    reason: str | None = None
    ese_delta: Decimal | None = None
    started_at: datetime
    run_id: uuid.UUID | None = None
