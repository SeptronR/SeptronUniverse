"""Internal assessment schemas — Prompts/13 §13.4 (marks grid, chain, CIA consolidation, change requests)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class OfferingAssessmentResponse(ORMModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    component_id: uuid.UUID
    component_code: str | None = None
    course_code: str | None = None
    course_title: str | None = None
    section_code: str | None = None
    category: str | None = None
    name: str
    max_marks: float
    scaled_to: float | None = None
    scheduled_on: date | None = None
    marks_entry_deadline: date | None = None
    status: str
    question_count: int = 0
    marks_entered: int = 0
    roster: int = 0
    submitted_at: datetime | None = None
    verified_at: datetime | None = None
    locked_at: datetime | None = None
    version: int


class InstantiateRequest(BaseModel):
    scheme_override_id: uuid.UUID | None = None


class InstantiateResult(BaseModel):
    created: int = 0
    existing: int = 0
    assessments: list[OfferingAssessmentResponse] = Field(default_factory=list)


class AssessmentQuestionIn(BaseModel):
    question_no: str = Field(min_length=1, max_length=10)
    max_marks: float = Field(gt=0)
    co_id: uuid.UUID | None = None
    bloom_level: str | None = None
    part: str | None = Field(None, max_length=5)


class AssessmentQuestionOut(ORMModel):
    id: uuid.UUID
    question_no: str
    max_marks: float
    co_id: uuid.UUID | None = None
    co_code: str | None = None
    bloom_level: str | None = None
    part: str | None = None


class QuestionMapReplace(BaseModel):
    questions: list[AssessmentQuestionIn]


class MarkRowIn(BaseModel):
    student_program_enrollment_id: uuid.UUID
    marks: float | None = None
    is_absent: bool = False
    is_exempt: bool = False
    question_wise: dict[str, float] | None = None


class MarksBulkUpsert(BaseModel):
    rows: list[MarkRowIn] = Field(min_length=1)
    source: str | None = None


class MarksResult(BaseModel):
    saved: int = 0
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    status: str


class MarksGridRow(BaseModel):
    student_program_enrollment_id: uuid.UUID
    mark_id: uuid.UUID | None = None
    registration_number: str | None = None
    roll_number: str | None = None
    name: str | None = None
    marks: float | None = None
    is_absent: bool = False
    is_exempt: bool = False
    question_wise: dict[str, Any] | None = None
    version: int | None = None


class MarksGridResponse(BaseModel):
    assessment: OfferingAssessmentResponse
    questions: list[AssessmentQuestionOut] = Field(default_factory=list)
    rows: list[MarksGridRow] = Field(default_factory=list)
    co_summary: dict[str, float] = Field(default_factory=dict)
    read_only: bool = False


class VerifyRequest(BaseModel):
    decision: Literal["approve", "reject"] = "approve"
    comment: str | None = Field(None, max_length=1000)


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class CiaRow(BaseModel):
    student_program_enrollment_id: uuid.UUID
    registration_number: str | None = None
    name: str | None = None
    component_breakdown: dict[str, Any] = Field(default_factory=dict)
    cia_total: float
    cia_scaled: float
    status: str


class ConsolidateResponse(BaseModel):
    offering_id: uuid.UUID
    cia_max: float
    rows: list[CiaRow] = Field(default_factory=list)
    status: str | None = None
    missing_components: list[str] = Field(default_factory=list)


class ChangeRequestCreate(BaseModel):
    target_type: Literal["internal_mark"] = "internal_mark"
    target_id: uuid.UUID
    new_value: dict[str, Any]
    reason: str = Field(min_length=3, max_length=2000)
    evidence_url: str | None = None


class ChangeRequestDecision(BaseModel):
    comment: str | None = Field(None, max_length=1000)


class ChangeRequestOut(ORMModel):
    id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any]
    reason: str
    evidence_url: str | None = None
    requested_by: uuid.UUID
    status: str
    workflow_instance_id: uuid.UUID | None = None
    applied_at: datetime | None = None
    created_at: datetime
    student_name: str | None = None
    assessment_name: str | None = None
    can_act: bool = False


class MyMarksRow(BaseModel):
    offering_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    components: list[dict[str, Any]] = Field(default_factory=list)
    cia_scaled: float | None = None
    cia_max: float | None = None
