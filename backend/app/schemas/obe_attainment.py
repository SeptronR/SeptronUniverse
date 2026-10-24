"""OBE attainment schemas — Prompts/17 §17.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.obe_attainment import LevelBand


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- configs ---------------------------------------------------------------------------------------------------------
class SurveyThreshold(BaseModel):
    level: int = Field(ge=1, le=3)
    min_mean: float


class AttainmentConfigIn(_Strict):
    scope_type: Literal["regulation", "program"]
    scope_id: uuid.UUID
    target_student_pct: float = Field(60, ge=0, le=100)
    target_marks_pct: float = Field(60, ge=0, le=100)
    levels: list[LevelBand] = Field(min_length=1, max_length=5)
    direct_weight: int = Field(80, ge=0, le=100)
    indirect_weight: int = Field(20, ge=0, le=100)
    cia_weight_in_direct: int = Field(30, ge=0, le=100)
    ese_weight_in_direct: int = Field(70, ge=0, le=100)
    co_target_level: float = Field(2.0, ge=0, le=3)
    po_target_level: float = Field(2.0, ge=0, le=3)
    ese_apportion_strategy: Literal["question_wise", "qp_pattern", "uniform"] = "question_wise"
    credit_weighted_po: bool = False
    survey_thresholds: list[SurveyThreshold] | None = None


class AttainmentConfigOut(BaseModel):
    id: uuid.UUID | None = None
    scope_type: str
    scope_id: uuid.UUID | None = None
    source: str  # program | regulation | platform
    target_student_pct: float
    target_marks_pct: float
    levels: list[LevelBand]
    direct_weight: int
    indirect_weight: int
    cia_weight_in_direct: int
    ese_weight_in_direct: int
    co_target_level: float
    po_target_level: float
    ese_apportion_strategy: str
    credit_weighted_po: bool
    survey_thresholds: list[SurveyThreshold]
    updated_at: datetime | None = None
    history: list[dict[str, Any]] = []


# ---- runs ------------------------------------------------------------------------------------------------------------
class CoRunRequest(_Strict):
    offering_id: uuid.UUID | None = None  # taken from the path when omitted
    include_indirect: bool = True
    survey_id: uuid.UUID | None = None


class PoRunRequest(_Strict):
    program_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    include_indirect: bool = True
    term_upto: int | None = Field(None, ge=1, le=20)


class RunResponse(BaseModel):
    run_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    scope_type: str
    scope_id: uuid.UUID
    status: str
    config_snapshot: dict[str, Any] | None = None
    computed_at: datetime | None = None
    warnings: list[str] = []


class RunSummary(BaseModel):
    id: uuid.UUID
    status: str
    run_at: datetime
    run_by: uuid.UUID | None = None
    warnings: list[str] = []
    config_snapshot: dict[str, Any] | None = None


class CoRow(BaseModel):
    co_id: uuid.UUID
    co: str
    statement: str | None = None
    students_assessed: int
    students_above_target: int
    direct_pct: float | None = None
    cia_level: float | None = None
    ese_level: float | None = None
    direct_level: float | None = None
    indirect_level: float | None = None
    final_level: float | None = None
    target: float | None = None
    gap: float | None = None
    breakdown: list[dict[str, Any]] = []


class OfferingRef(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    section_code: str | None = None
    term_id: uuid.UUID | None = None


class Prerequisites(BaseModel):
    cia_locked: bool
    cia_pending: list[str] = []
    has_ese: bool
    results_published: bool
    survey_present: bool


class CoAttainmentResponse(BaseModel):
    offering: OfferingRef
    run: RunSummary | None = None
    prerequisites: Prerequisites | None = None
    cos: list[CoRow] = []


class PoRow(BaseModel):
    outcome_id: uuid.UUID
    outcome: str
    outcome_type: str
    statement: str | None = None
    direct: float | None = None
    indirect: float | None = None
    final: float | None = None
    target: float | None = None
    gap: float | None = None
    contributing_courses: int
    breakdown: list[dict[str, Any]] = []


class PeoRow(BaseModel):
    outcome_id: uuid.UUID
    outcome: str
    level: float | None = None
    via: list[str] = []


class ProgramRef(BaseModel):
    id: uuid.UUID
    code: str | None = None
    name: str | None = None


class BatchRef(BaseModel):
    id: uuid.UUID
    code: str | None = None
    admission_year: int | None = None


class PoAttainmentResponse(BaseModel):
    program: ProgramRef
    batch: BatchRef
    run: RunSummary | None = None
    coverage_pct: float | None = None
    outcomes: list[PoRow] = []
    peos: list[PeoRow] = []


class TrendBatch(BaseModel):
    batch: BatchRef
    run_at: datetime | None = None
    outcomes: dict[str, float | None]


class ProgramAttainmentTrend(BaseModel):
    program: ProgramRef
    outcomes: list[str]
    batches: list[TrendBatch]


class CoPoHeatmap(BaseModel):
    rows: list[str]  # courses (programme) or COs (offering)
    columns: list[str]  # POs / PSOs or assessments
    cells: list[list[float | None]]
    row_ids: list[str] = []


class GapListRow(BaseModel):
    scope: str  # offering | program
    scope_id: uuid.UUID
    label: str
    outcome: str
    outcome_id: uuid.UUID | None = None
    co_id: uuid.UUID | None = None
    final: float | None = None
    target: float | None = None
    gap: float
    suggested_action: str
    open_actions: int = 0


class DashboardResponse(BaseModel):
    program: ProgramRef
    batch: BatchRef
    radar: list[dict[str, Any]]
    heatmap: CoPoHeatmap
    gaps: list[GapListRow]
    coverage_pct: float | None = None
    direct_vs_indirect: list[dict[str, Any]]
    cqi: dict[str, int] = {}
    run: RunSummary | None = None


class StudentCoItem(BaseModel):
    co: str
    statement: str | None = None
    marks_pct: float | None = None
    above_target: bool | None = None


class StudentCoAchievement(BaseModel):
    offering: OfferingRef
    student_program_enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    cos: list[StudentCoItem]


class IndirectSurveySummary(BaseModel):
    survey: dict[str, Any]
    responses: int
    mean_by_co: dict[str, float] = {}
    mean_by_outcome: dict[str, float] = {}
    levels: dict[str, int] = {}


# ---- CQI -------------------------------------------------------------------------------------------------------------
class CqiActionIn(_Strict):
    scope_type: Literal["offering", "course", "program"]
    scope_id: uuid.UUID
    outcome_id: uuid.UUID | None = None
    gap: float | None = Field(None, ge=-3, le=3)
    action_text: str = Field(min_length=3, max_length=4000)
    owner_staff_id: uuid.UUID | None = None
    due_on: date | None = None


class CqiActionUpdate(_Strict):
    action_text: str | None = Field(None, min_length=3, max_length=4000)
    owner_staff_id: uuid.UUID | None = None
    due_on: date | None = None
    evidence_url: str | None = None


class CqiStatusChange(_Strict):
    status: Literal["planned", "in_progress", "done"]
    evidence_url: str | None = None
    comment: str | None = Field(None, max_length=2000)


class CqiVerify(_Strict):
    approve: bool = True
    comment: str | None = Field(None, max_length=2000)


class CqiActionOut(BaseModel):
    id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID
    scope_label: str | None = None
    outcome_id: uuid.UUID | None = None
    outcome: str | None = None
    gap: float | None = None
    gap_after: float | None = None
    action_text: str
    owner_staff_id: uuid.UUID | None = None
    owner_name: str | None = None
    due_on: date | None = None
    overdue: bool = False
    status: str
    evidence_url: str | None = None
    reviewed_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


# ---- NBA export ------------------------------------------------------------------------------------------------------
class NbaExportRequest(_Strict):
    program_id: uuid.UUID
    batch_id: uuid.UUID
    format: Literal["xlsx", "docx"] = "xlsx"


class ExportJob(BaseModel):
    job_id: uuid.UUID
    status: str
    progress: int | None = None
    file_url: str | None = None
    result: dict[str, Any] | None = None
