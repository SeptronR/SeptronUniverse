"""Degrees, convocation & digital credentials schemas — Prompts/18 §18.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrollmentRef(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    program_code: str | None = None
    batch_code: str | None = None
    status: str | None = None


# ---- eligibility ---------------------------------------------------------------------------------------------------------
class EligibilityRunRequest(_Strict):
    batch_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    enrollment_ids: list[uuid.UUID] | None = Field(None, max_length=5000)
    include_exits: bool = False
    notify: bool = False


class DegreeEligibilityRunSummary(BaseModel):
    run_id: uuid.UUID
    job_id: uuid.UUID | None = None
    checked: int = 0
    eligible: int = 0
    ineligible: int = 0
    by_reason: dict[str, int] = {}
    exit_awards: int = 0


class BucketRow(BaseModel):
    bucket: str
    required: float
    earned: float
    ok: bool


class EligibilityCheckResponse(BaseModel):
    id: uuid.UUID
    enrollment: EnrollmentRef
    checked_at: datetime
    credits_earned: float | None = None
    credits_required: float | None = None
    bucket_breakdown: list[BucketRow] = []
    backlog_count: int | None = None
    cgpa: float | None = None
    min_cgpa_ok: bool | None = None
    duration_ok: bool | None = None
    dues_cleared: bool | None = None
    holds_clear: bool | None = None
    mandatory_noncredit_ok: bool | None = None
    is_eligible: bool
    reasons: list[str] = []
    overridden: bool = False
    override_reason: str | None = None
    run_id: uuid.UUID | None = None


class EligibilityOverride(_Strict):
    decision: Literal["eligible", "ineligible"]
    reason: str = Field(min_length=5, max_length=2000)


# ---- convocation -----------------------------------------------------------------------------------------------------------
class ConvocationIn(_Strict):
    name: str = Field(min_length=3, max_length=160)
    held_on: date | None = None
    venue: str | None = Field(None, max_length=200)
    registration_deadline: date | None = None
    fee_paise: int = Field(0, ge=0, le=10_000_000)


class ConvocationUpdate(_Strict):
    name: str | None = Field(None, min_length=3, max_length=160)
    held_on: date | None = None
    venue: str | None = Field(None, max_length=200)
    registration_deadline: date | None = None
    fee_paise: int | None = Field(None, ge=0, le=10_000_000)


class ConvocationStatusChange(_Strict):
    status: Literal["registration_open", "closed", "completed"]


class ConvocationOut(BaseModel):
    id: uuid.UUID
    name: str
    held_on: date | None = None
    venue: str | None = None
    registration_deadline: date | None = None
    fee_paise: int
    status: str
    counts: dict[str, int] = {}
    created_at: datetime


class ConvocationRegister(_Strict):
    mode: Literal["in_person", "absentia"] = "in_person"
    gown_size: Literal["XS", "S", "M", "L", "XL", "XXL"] | None = None
    guests: int | None = Field(None, ge=0, le=4)
    enrollment_id: uuid.UUID | None = None  # alumni / staff on behalf; defaults to the caller's enrolment


class ConvocationRegistrationResponse(BaseModel):
    id: uuid.UUID
    convocation_id: uuid.UUID
    convocation: str | None = None
    enrollment: EnrollmentRef
    mode: str
    gown_size: str | None = None
    guests: int | None = None
    status: str
    fee_invoice_id: uuid.UUID | None = None
    fee_status: str | None = None
    attendance_token: str | None = None
    created_at: datetime


class AttendanceMark(_Strict):
    token: str | None = None
    registration_id: uuid.UUID | None = None


# ---- awards ------------------------------------------------------------------------------------------------------------------
class AwardBatchRequest(_Strict):
    convocation_id: uuid.UUID | None = None
    enrollment_ids: list[uuid.UUID] | None = Field(None, max_length=5000)
    batch_id: uuid.UUID | None = None
    award_type: Literal["degree", "honours", "pg_diploma", "phd", "diploma", "certificate"] = "degree"
    date_of_award: date | None = None
    resolution_id: uuid.UUID | None = None


class AwardPreviewRow(BaseModel):
    enrollment: EnrollmentRef
    degree_name: str
    result_class: str | None = None
    cgpa: float | None = None
    skip_reason: str | None = None


class AwardBatchPreview(BaseModel):
    dry_run: bool
    eligible: int
    skipped: int
    created: int = 0
    rows: list[AwardPreviewRow] = []


class DegreeAwardedResponse(BaseModel):
    id: uuid.UUID
    enrollment: EnrollmentRef
    award_type: str
    degree_name: str
    specialization: str | None = None
    result_class: str | None = None
    cgpa: float | None = None
    date_of_award: date | None = None
    certificate_number: str | None = None
    serial_no: str | None = None
    convocation_id: uuid.UUID | None = None
    pdf_url: str | None = None
    esign_ref: str | None = None
    status: str
    approval_resolution_id: uuid.UUID | None = None
    verification_token: str | None = None
    credential_status: str | None = None
    reissued_as: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ApproveRequest(_Strict):
    resolution_id: uuid.UUID | None = None
    comment: str | None = Field(None, max_length=2000)


class IssueRequest(_Strict):
    esign: bool = False


class IssueBatchRequest(_Strict):
    award_ids: list[uuid.UUID] | None = Field(None, max_length=5000)
    convocation_id: uuid.UUID | None = None
    esign: bool = False


class RevokeRequest(_Strict):
    reason: str = Field(min_length=5, max_length=2000)


class ReissueRequest(_Strict):
    reason: str = Field(min_length=5, max_length=2000)
    corrections: dict[str, Any] | None = None  # degree_name / specialization / result_class / holder_name


class ProvisionalRequest(_Strict):
    enrollment_id: uuid.UUID


class ProvisionalResponse(BaseModel):
    enrollment: EnrollmentRef
    document_number: str
    pdf_url: str | None = None
    verification_token: str
    issued_at: datetime
    superseded: bool = False


# ---- credentials / ABC ------------------------------------------------------------------------------------------------------
class CredentialPushRequest(_Strict):
    entity_type: Literal["grade_card", "transcript", "degree", "provisional_certificate"] = "degree"
    entity_ids: list[uuid.UUID] | None = Field(None, max_length=5000)
    batch_id: uuid.UUID | None = None
    channel: Literal["digilocker", "nad", "internal"] = "digilocker"


class PushSummary(BaseModel):
    job_id: uuid.UUID | None = None
    queued: int = 0
    pushed: int = 0
    acknowledged: int = 0
    failed: int = 0
    skipped: dict[str, int] = {}


class CredentialStatusResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    channel: str
    status: str
    ack_ref: str | None = None
    attempts: int
    pushed_at: datetime | None = None
    payload_hash: str
    response: dict[str, Any] | None = None
    holder: str | None = None
    updated_at: datetime


class AbcPushRequest(_Strict):
    student_ids: list[uuid.UUID] | None = Field(None, max_length=5000)
    term_id: uuid.UUID | None = None


class AbcPushSummary(BaseModel):
    job_id: uuid.UUID | None = None
    batches: int = 0
    pushed: int = 0
    acknowledged: int = 0
    failed: int = 0
    skipped_no_apaar: int = 0


class AbcLedgerRow(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    apaar_id: str | None = None
    course_code: str
    course_title: str
    credits: float
    letter_grade: str | None = None
    grade_point: float | None = None
    academic_year: str | None = None
    status: str
    push_batch_id: uuid.UUID | None = None
    attempts: int
    updated_at: datetime


# ---- verification / stats ---------------------------------------------------------------------------------------------------
class DegreeVerifyResponse(BaseModel):
    valid: bool
    entity_type: str
    institution: str | None = None
    holder_masked: str | None = None
    award: dict[str, Any] | None = None
    issued_at: datetime | None = None
    revoked: bool = False
    superseded: bool = False
    hash: str | None = None
    version_note: str | None = None
    message: str | None = None


class BulkVerifyRequest(_Strict):
    tokens: list[str] = Field(min_length=1, max_length=50)
    captcha_token: str | None = None
    institution: str | None = None


class GraduationStatsResponse(BaseModel):
    gph: float | None = None
    gphd: int = 0
    on_time_pct: float | None = None
    admitted: int = 0
    graduated: int = 0
    graduated_on_time: int = 0
    median_cgpa: float | None = None
    by_program: list[dict[str, Any]] = []
