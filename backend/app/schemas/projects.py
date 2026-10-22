"""Student project schemas — Prompts/13 §13.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProjectIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    project_type: Literal["mini", "major", "dissertation", "internship_project"] = "major"
    guide_staff_id: uuid.UUID | None = None
    co_guide_staff_id: uuid.UUID | None = None
    external_guide: dict[str, Any] | None = None
    abstract: str | None = None
    repository_url: str | None = None
    status: Literal["proposed", "approved", "in_progress", "submitted", "evaluated"] | None = None
    members: list[uuid.UUID] | None = Field(None, description="enrolment ids (1–4); the first is the leader")


class MemberIn(BaseModel):
    members: list[uuid.UUID] = Field(min_length=1, max_length=4)


class ReviewIn(BaseModel):
    review_no: int = Field(ge=1, le=10)
    scheduled_on: date | None = None
    panel: list[dict[str, Any]] | None = Field(None, description="[{user_id, name}]")
    rubric_scores: dict[str, float] | None = None
    marks: float | None = Field(None, ge=0)
    remarks: str | None = None
    offering_assessment_id: uuid.UUID | None = None


class ReviewOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    review_no: int
    scheduled_on: date | None = None
    panel: list[dict[str, Any]] | None = None
    rubric_scores: dict[str, Any] | None = None
    marks: float | None = None
    remarks: str | None = None
    offering_assessment_id: uuid.UUID | None = None
    created_at: datetime


class ProjectOut(ORMModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    title: str
    project_type: str
    guide_staff_id: uuid.UUID | None = None
    co_guide_staff_id: uuid.UUID | None = None
    guide_name: str | None = None
    external_guide: dict[str, Any] | None = None
    abstract: str | None = None
    repository_url: str | None = None
    status: str
    created_at: datetime
    members: list[dict[str, Any]] = Field(default_factory=list)
    reviews: list[ReviewOut] = Field(default_factory=list)
