"""Survey schemas — Prompts/27 §27.4 (OpenAPI names prefixed ``Svy``)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


SurveyTypeLit = Literal[
    "course", "faculty", "institution", "course_exit", "program_exit", "alumni", "employer", "hostel", "parent", "sss"
]


class SvyQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=2, max_length=500)
    type: Literal["likert5", "likert4", "text", "choice", "yesno"] = "likert5"
    scale: int | None = Field(None, ge=2, le=10)
    options: list[str] | None = None
    co_id: str | None = None
    po_id: str | None = None
    outcome_id: str | None = None
    required: bool = True


class SvyTargets(BaseModel):
    type: Literal["offering", "staff", "institution", "program", "hostel"] | None = None
    ids: list[uuid.UUID] | None = None
    auto: bool = True


class SvyCreate(_Strict):
    survey_type: SurveyTypeLit
    term_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    title: str = Field(min_length=3, max_length=200)
    questions: list[SvyQuestion] | None = None
    use_template: bool = True
    audience_rules: dict[str, Any] = {}
    targets: SvyTargets = Field(default_factory=SvyTargets)
    is_anonymous: bool = True
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    reminder_days: list[int] = []
    min_responses: int | None = Field(None, ge=1, le=100)

    @model_validator(mode="after")
    def _window(self) -> "SvyCreate":
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise ValueError("closes_at must be after opens_at")
        return self


class SvyUpdate(_Strict):
    title: str | None = Field(None, min_length=3, max_length=200)
    questions: list[SvyQuestion] | None = None
    audience_rules: dict[str, Any] | None = None
    targets: SvyTargets | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    reminder_days: list[int] | None = None
    min_responses: int | None = Field(None, ge=1, le=100)


class SvyOut(BaseModel):
    id: uuid.UUID
    survey_type: str
    term_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    title: str
    questions: list[dict[str, Any]] = []
    audience_rules: dict[str, Any] = {}
    targets: dict[str, Any] = {}
    is_anonymous: bool
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    status: str
    reminder_days: list[int] = []
    min_responses: int = 5
    responses: int = 0
    expected: int | None = None
    completion_pct: float | None = None
    created_at: datetime | None = None


class SvyTarget(BaseModel):
    target_type: str
    target_id: uuid.UUID | None = None
    label: str | None = None
    responded: bool = False


class SvyPending(BaseModel):
    survey_id: uuid.UUID
    survey_type: str
    title: str
    closes_at: datetime | None = None
    targets: list[SvyTarget]


class SvyForm(BaseModel):
    survey_id: uuid.UUID
    title: str
    survey_type: str
    is_anonymous: bool
    questions: list[dict[str, Any]]
    target: SvyTarget | None = None


class SvyRespond(_Strict):
    target_id: uuid.UUID | None = None
    answers: dict[str, Any]


class SvyRespondResult(BaseModel):
    survey_id: uuid.UUID
    target_id: uuid.UUID | None = None
    submitted_at: datetime


class SvyCompletion(BaseModel):
    survey_id: uuid.UUID
    expected: int | None = None
    responses: int
    respondents: int
    completion_pct: float | None = None
    by_target: list[dict[str, Any]] = []


class SvyQuestionStats(BaseModel):
    id: str
    text: str
    type: str
    n: int
    mean: float | None = None
    distribution: dict[str, int] = {}


class SvyAnalytics(BaseModel):
    survey_id: uuid.UUID
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    target_label: str | None = None
    n: int
    per_question: list[SvyQuestionStats]
    overall: float | None = None
    comments_masked: list[str] = []
    co_scores: dict[str, float] | None = None
    po_scores: dict[str, float] | None = None
    previous_overall: float | None = None


class SvyCompareRow(BaseModel):
    key: str
    label: str | None = None
    n: int
    overall: float | None = None


class SvyCompare(BaseModel):
    survey_id: uuid.UUID
    institution_overall: float | None = None
    rows: list[SvyCompareRow]


class SvySssScore(BaseModel):
    survey_id: uuid.UUID | None = None
    period: str | None = None
    respondents: int
    score: float | None = None
    max_score: float = 4.0
    per_item: dict[str, float] = {}
    metric_recorded: bool = False


class SvyExternalLinks(_Strict):
    count: int = Field(1, ge=1, le=500)
    target_id: uuid.UUID | None = None


class SvyExternalLinksOut(BaseModel):
    survey_id: uuid.UUID
    tokens: list[str]
