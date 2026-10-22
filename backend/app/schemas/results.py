"""Result schemas — Prompts/15 §15.4 (runs, rows, term results, publication, queries, grade cards, legacy import)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunScope(_Strict):
    college_ids: list[uuid.UUID] = []
    program_ids: list[uuid.UUID] = []
    batch_ids: list[uuid.UUID] = []
    enrollment_ids: list[uuid.UUID] = Field(default=[], description="correction / revaluation runs: affected students")
    course_ids: list[uuid.UUID] = []
    marks_delta: dict[str, Decimal] = Field(
        default={}, description="correction runs: {'<enrolment>:<course>': delta ESE marks}"
    )
    ignore_holds: bool = Field(default=False, description="withheld release (Phase 16): holds do not withhold")


class RunCreateRequest(_Strict):
    exam_session_id: uuid.UUID
    scope: RunScope = Field(default_factory=RunScope)
    run_type: Literal["provisional", "final", "revaluation", "supplementary_merge", "correction"] = "provisional"


class RunResponse(BaseModel):
    id: uuid.UUID
    exam_session_id: uuid.UUID | None = None
    session_name: str | None = None
    scope: dict[str, Any] | None = None
    run_type: str
    status: str
    triggered_by: uuid.UUID | None = None
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    approval_resolution_id: uuid.UUID | None = None
    published_at: datetime | None = None
    stats: dict[str, Any] | None = None
    config_snapshot: dict[str, Any] | None = None
    checksum: str | None = None
    anomalies_count: int = 0
    job_id: uuid.UUID | None = None
    created_at: datetime


class AnomalyRow(BaseModel):
    student: str | None = None
    registration_number: str | None = None
    enrollment_id: uuid.UUID | None = None
    course: str | None = None
    course_id: uuid.UUID | None = None
    code: str
    detail: str
    row_id: uuid.UUID | None = None


class RunAction(_Strict):
    decision: Literal["verify", "approve", "rollback"] | None = None
    comment: str | None = Field(default=None, max_length=2000)
    resolution_id: uuid.UUID | None = None
    acknowledge_anomalies: bool = Field(default=False, description="checklist ack (verify)")


class PublishRequest(_Strict):
    audience: Literal["student", "college", "public"] = "student"
    notify: bool = True
    withhold_ids: list[uuid.UUID] = Field(default=[], description="enrolment ids to withhold")


class CourseResultResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    term_id: uuid.UUID
    course_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    offering_id: uuid.UUID | None = None
    attempt_number: int
    attempt_type: str
    credits: Decimal
    cia_marks: Decimal | None = None
    cia_max: Decimal | None = None
    ese_marks: Decimal | None = None
    ese_max: Decimal | None = None
    grace_marks: Decimal
    grace_reason: str | None = None
    moderation_delta: Decimal | None = None
    total_marks: Decimal | None = None
    total_max: Decimal | None = None
    percentage: Decimal | None = None
    letter_grade: str | None = None
    grade_point: Decimal | None = None
    result_status: str
    counts_toward_cgpa: bool
    is_current: bool
    version: int
    status: str
    published_at: datetime | None = None
    hash: str | None = None
    revised: bool = False


class TermResultResponse(BaseModel):
    id: uuid.UUID
    student_term_record_id: uuid.UUID
    term_id: uuid.UUID | None = None
    term_number: int | None = None
    term_name: str | None = None
    run_id: uuid.UUID
    credits_registered: Decimal
    credits_earned: Decimal
    sgpa: Decimal | None = None
    cgpa: Decimal | None = None
    cumulative_credits: Decimal | None = None
    backlog_count: int
    result_class: str | None = None
    status: str
    version: int
    is_current: bool
    published_at: datetime | None = None
    grade_card_id: uuid.UUID | None = None


class MyTerm(BaseModel):
    term: TermResultResponse
    courses: list[CourseResultResponse]


class MyResultsResponse(BaseModel):
    student_id: uuid.UUID | None = None
    enrollment_id: uuid.UUID | None = None
    terms: list[MyTerm]
    cgpa: Decimal | None = None
    credits_earned: Decimal | None = None
    standing: str | None = None


class PublicLookupRequest(_Strict):
    reg_no: str = Field(min_length=2, max_length=40)
    dob: date
    institution: str | None = Field(default=None, max_length=80, description="institution slug")


class PublicLookupResponse(BaseModel):
    name: str
    registration_number: str
    terms: list[dict[str, Any]]


class GradeCardResponse(BaseModel):
    id: uuid.UUID
    student_term_result_id: uuid.UUID
    document_number: str
    qr_token: str
    version: int
    generated_at: datetime
    superseded: bool = False
    term_number: int | None = None
    sgpa: Decimal | None = None


class TabulationRow(BaseModel):
    enrollment_id: uuid.UUID
    registration_number: str | None = None
    student_name: str | None = None
    courses: dict[str, str]
    sgpa: Decimal | None = None
    cgpa: Decimal | None = None
    credits_earned: Decimal | None = None
    backlogs: int = 0
    result_class: str | None = None


class ResultAnalysis(BaseModel):
    pass_pct_by_course: list[dict[str, Any]]
    grade_distribution: dict[str, int]
    toppers: list[dict[str, Any]]
    students: int
    pass_pct: float | None = None


class LegacyImportCreate(_Strict):
    batch_id: uuid.UUID
    term_number: int = Field(ge=1, le=20)
    file_url: str | None = Field(default=None, max_length=2000, description="stored key (or upload the file)")
    mapping: dict[str, str] = Field(
        default={},
        description="column → field (reg_no, course_code, course_title, credits, cia, ese, total, grade, gp, attempt)",
    )


class LegacyValidationReport(BaseModel):
    rows: int
    valid: int
    errors: list[dict[str, Any]]
    students: int
    courses_to_create: list[str] = []


class LegacyImportResponse(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    term_number: int
    status: str
    validation_report: dict[str, Any] | None = None
    run_id: uuid.UUID | None = None
    created_at: datetime


class ResultVerifyResponse(BaseModel):
    valid: bool
    document_type: str = "grade_card"
    document_number: str | None = None
    holder_name: str | None = None
    registration_number: str | None = None
    term_number: int | None = None
    sgpa: Decimal | None = None
    cgpa: Decimal | None = None
    hash: str | None = None
    superseded: bool = False
    institution: str | None = None
    message: str | None = None
