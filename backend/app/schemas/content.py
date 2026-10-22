"""Question bank, blueprint, paper and study-material schemas (carried from Orbit) — Prompts/13 §13.4."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel


class SyllabusTopicIn(BaseModel):
    unit_no: int | None = None
    title: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    sequence: int = 1
    hours: float | None = None


class SyllabusTopicOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID
    unit_no: int | None = None
    title: str
    parent_id: uuid.UUID | None = None
    sequence: int
    hours: float | None = None


class OptionIn(BaseModel):
    label: str | None = Field(None, max_length=5)
    body_primary: str = Field(min_length=1)
    body_secondary: str | None = None
    is_correct: bool = False


class QuestionIn(BaseModel):
    course_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    co_id: uuid.UUID | None = None
    question_type: Literal["mcq", "msq", "true_false", "short", "long", "numeric", "fill_blank", "match"]
    body_primary: str = Field(min_length=1)
    body_secondary: str | None = None
    marks: float = Field(1, gt=0)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    bloom_level: str | None = None
    answer_key: Any | None = None
    explanation: str | None = None
    tags: list[str] | None = None
    media: list[dict[str, Any]] | None = None
    options: list[OptionIn] | None = None

    @model_validator(mode="after")
    def _options(self) -> "QuestionIn":
        if self.question_type in ("mcq", "msq"):
            opts = self.options or []
            correct = sum(1 for o in opts if o.is_correct)
            if len(opts) < 2:
                raise ValueError("MCQ / MSQ need at least two options")
            if self.question_type == "mcq" and correct != 1:
                raise ValueError("An MCQ needs exactly one correct option")
            if self.question_type == "msq" and correct < 1:
                raise ValueError("An MSQ needs at least one correct option")
        return self


class OptionOut(ORMModel):
    id: uuid.UUID
    label: str | None = None
    body_primary: str
    body_secondary: str | None = None
    is_correct: bool
    sequence: int


class QuestionOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    co_id: uuid.UUID | None = None
    question_type: str
    body_primary: str
    body_secondary: str | None = None
    marks: float
    difficulty: str
    bloom_level: str | None = None
    answer_key: Any | None = None
    explanation: str | None = None
    tags: list[str] | None = None
    usage_count: int
    created_by: uuid.UUID | None = None
    created_at: datetime
    options: list[OptionOut] = Field(default_factory=list)


class QuestionImportReport(BaseModel):
    created: int = 0
    failed: list[dict[str, Any]] = Field(default_factory=list)


class BlueprintIn(BaseModel):
    course_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=160)
    total_marks: float = Field(gt=0)
    duration_minutes: int | None = None
    pattern: dict[str, Any] = Field(
        description="{parts:[{title, count, marks, question_types?, co_ids?, bloom?, difficulty?}]}"
    )


class BlueprintOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID | None = None
    name: str
    total_marks: float
    duration_minutes: int | None = None
    pattern: dict[str, Any]
    created_at: datetime


class PaperGenerateRequest(BaseModel):
    blueprint_id: uuid.UUID
    title: str | None = None
    purpose: Literal["internal", "quiz", "ese", "practice"] = "internal"
    strategy: Literal["random", "least_used"] = "random"
    seed: int | None = None


class PaperOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID | None = None
    blueprint_id: uuid.UUID | None = None
    title: str
    purpose: str
    total_marks: float | None = None
    duration_minutes: int | None = None
    sections: list[dict[str, Any]]
    status: str
    is_bilingual: bool
    frozen_at: datetime | None = None
    shortfall: list[dict[str, Any]] = Field(default_factory=list)


class PaperUpdate(BaseModel):
    title: str | None = None
    sections: list[dict[str, Any]] | None = None
    duration_minutes: int | None = None
    is_bilingual: bool | None = None


class StudyMaterialIn(BaseModel):
    course_id: uuid.UUID | None = None
    offering_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    material_type: str = "notes"
    body_primary: str | None = None
    body_secondary: str | None = None
    file_url: str | None = None


class StudyMaterialOut(ORMModel):
    id: uuid.UUID
    course_id: uuid.UUID | None = None
    offering_id: uuid.UUID | None = None
    title: str
    material_type: str
    body_primary: str | None = None
    body_secondary: str | None = None
    file_url: str | None = None
    is_published: bool
    published_at: datetime | None = None
    created_at: datetime
