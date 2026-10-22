"""Evaluation schemas — Prompts/15 §15.4 (coding, custody, valuation, reconcile, moderation, decode).

Evaluator-facing models (``EvaluatorBundleResponse``, ``EvaluatorScript``) carry dummy numbers only — never the
registration item, the student or the registration number.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BundleCreateRequest(_Strict):
    room_id: uuid.UUID | None = None
    centre_id: uuid.UUID | None = None
    size: int = Field(default=30, ge=1, le=500, description="scripts per bundle (setting exams.bundle_size)")


class BundleResponse(BaseModel):
    id: uuid.UUID
    exam_paper_id: uuid.UUID
    paper_code: str | None = None
    room_id: uuid.UUID | None = None
    room_code: str | None = None
    exam_centre_id: uuid.UUID | None = None
    bundle_number: str
    script_count: int
    status: str
    coded_at: datetime | None = None
    custody_holder_staff_id: uuid.UUID | None = None
    custody_location: str | None = None
    rounds: list[dict[str, Any]] = []


class DummyScript(BaseModel):
    id: uuid.UUID
    dummy_number: str
    status: str


class CodeBundleResponse(BaseModel):
    bundle: BundleResponse
    scripts: list[DummyScript]


class CustodyLogCreate(_Strict):
    action: Literal["dispatched", "received", "handed_over", "returned"]
    to_staff_id: uuid.UUID | None = None
    location: str | None = Field(default=None, max_length=120)
    remarks: str | None = Field(default=None, max_length=2000)


class CustodyLogResponse(BaseModel):
    id: uuid.UUID
    bundle_id: uuid.UUID
    action: str
    from_staff_id: uuid.UUID | None = None
    to_staff_id: uuid.UUID | None = None
    at: datetime
    location: str | None = None
    remarks: str | None = None


class ExternalEvaluator(_Strict):
    user_id: uuid.UUID | None = Field(default=None, description="time-boxed external_examiner account")
    name: str = Field(min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    institution: str | None = Field(default=None, max_length=200)


class AssignValuationRequest(_Strict):
    bundle_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    evaluator_staff_id: uuid.UUID | None = None
    external_evaluator: ExternalEvaluator | None = None
    evaluator_type: Literal["internal", "external"] = "internal"
    round: int = Field(default=1, ge=1, le=3)
    due_at: datetime | None = None
    remuneration_paise: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _who(self) -> "AssignValuationRequest":
        if self.evaluator_type == "internal" and self.evaluator_staff_id is None:
            raise ValueError("evaluator_staff_id is required for an internal evaluator")
        if self.evaluator_type == "external" and self.external_evaluator is None:
            raise ValueError("external_evaluator is required for an external evaluator")
        return self


class ReassignRequest(_Strict):
    evaluator_staff_id: uuid.UUID | None = None
    external_evaluator: ExternalEvaluator | None = None
    due_at: datetime | None = None


class ValuationAssignmentResponse(BaseModel):
    id: uuid.UUID
    exam_paper_id: uuid.UUID
    bundle_id: uuid.UUID
    bundle_number: str | None = None
    evaluator_staff_id: uuid.UUID | None = None
    evaluator_user_id: uuid.UUID | None = None
    evaluator_name: str | None = None
    evaluator_type: str
    valuation_round: int
    status: str
    assigned_at: datetime
    due_at: datetime | None = None
    submitted_at: datetime | None = None
    remuneration_paise: int | None = None
    scripts: int = 0
    valued: int = 0


class ValuationStatus(BaseModel):
    exam_paper_id: uuid.UUID
    valuation_mode: str
    bundles: int
    scripts: int
    assignments: list[ValuationAssignmentResponse]
    final_marks: dict[str, int]


class EvaluatorScript(BaseModel):
    """Dummy-number projection (``answer_scripts_for_evaluation``) + this round's marks."""

    id: uuid.UUID
    dummy_number: str
    pages: int | None = None
    scan_available: bool = False
    status: str
    marks: Decimal | None = None
    question_wise: dict[str, Any] | None = None
    is_locked: bool = False


class EvaluatorBundleResponse(BaseModel):
    assignment_id: uuid.UUID
    bundle_id: uuid.UUID
    bundle_number: str
    paper_code: str | None = None
    course_title: str | None = None
    max_marks: Decimal
    qp_pattern: dict[str, Any] | None = None
    valuation_round: int
    status: str
    due_at: datetime | None = None
    scripts: int
    valued: int


class ValuationSubmit(_Strict):
    marks: Decimal = Field(ge=0, le=1000)
    question_wise: dict[str, Decimal] | None = Field(default=None, description="{question: marks}")
    annotations_url: str | None = Field(default=None, max_length=2000)


class BulkValuationRow(ValuationSubmit):
    answer_script_id: uuid.UUID


class BulkValuationSubmit(_Strict):
    round: int = Field(ge=1, le=3)
    rows: list[BulkValuationRow] = Field(min_length=1, max_length=500)


class ScriptValuationResponse(BaseModel):
    answer_script_id: uuid.UUID
    valuation_round: int
    marks: Decimal
    question_wise: dict[str, Any] | None = None
    is_locked: bool
    submitted_at: datetime


class ReconcileSummary(BaseModel):
    resolved: int
    needs_third: int
    average_discrepancy: float | None = None
    rule: str
    tolerance: float
    discrepancies: list[dict[str, Any]] = []


class ThirdValuationAssign(_Strict):
    evaluator_staff_id: uuid.UUID | None = None
    external_evaluator: ExternalEvaluator | None = None
    due_at: datetime | None = None
    remuneration_paise: int | None = Field(default=None, ge=0)


class ModerationProposal(_Strict):
    action_type: Literal["scale_up", "scale_down", "add_flat", "grace", "normalize", "cap"]
    rule: dict[str, Any] = Field(description="{factor} | {marks} | {target_mean, target_sd} | {cap} | {below, up_to}")
    justification: str = Field(min_length=5, max_length=4000)


class ModerationDecision(_Strict):
    comment: str | None = Field(default=None, max_length=2000)


class ModerationResponse(BaseModel):
    id: uuid.UUID
    exam_paper_id: uuid.UUID
    action_type: str
    rule: dict[str, Any]
    justification: str
    proposed_by: uuid.UUID
    approved_by: uuid.UUID | None = None
    affected_count: int | None = None
    status: str
    created_at: datetime
    preview: dict[str, Any] | None = None


class DecodeResponse(BaseModel):
    paper: uuid.UUID
    decoded_count: int
    ese_marks_written: int


class OnlineImportResponse(BaseModel):
    paper: uuid.UUID
    items: int


class ScriptRetentionRequest(_Strict):
    action: Literal["archive", "destroy"] = "archive"
    bundle_ids: list[uuid.UUID] | None = None
    approval_note: str | None = Field(default=None, max_length=2000)


class ScriptRegisterRow(BaseModel):
    bundle_id: uuid.UUID
    bundle_number: str
    paper_code: str | None = None
    status: str
    script_count: int
    last_action: str | None = None
    last_action_at: datetime | None = None
