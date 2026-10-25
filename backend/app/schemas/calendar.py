"""Calendar schemas — Prompts/25 §25.4 (OpenAPI names prefixed ``Calendar`` to stay unique)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


CalendarTypeLit = Literal["general", "academic", "exam", "holiday", "registration", "deadline", "meeting"]


class CalendarAudience(_Strict):
    """Who sees a manual entry: empty = everyone in the institution (or the college when ``college_id`` is set)."""

    person_types: list[Literal["student", "staff", "guardian"]] = []
    roles: list[str] = []
    department_ids: list[uuid.UUID] = []
    program_ids: list[uuid.UUID] = []


class CalendarEventIn(_Strict):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(None, max_length=4000)
    event_type: CalendarTypeLit = "general"
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    location: str | None = Field(None, max_length=200)
    college_id: uuid.UUID | None = None
    audience_rules: CalendarAudience | None = None
    color: str | None = Field(None, max_length=10)


class CalendarEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    college_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    event_type: str
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool
    location: str | None = None
    audience_rules: dict[str, Any] | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    color: str | None = None
    created_by: uuid.UUID | None = None


class CalendarItem(BaseModel):
    """One merged entry of ``GET /calendar`` (manual rows and every registered source)."""

    key: str
    title: str
    event_type: str
    source_type: str
    source_id: uuid.UUID | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    location: str | None = None
    color: str | None = None
    college_id: uuid.UUID | None = None
    editable: bool = False
    link: str | None = None


class CalendarOut(BaseModel):
    from_at: datetime
    to_at: datetime
    scope: str
    items: list[CalendarItem]
    sources: list[str]
    conflicts: list[dict[str, Any]] = []


class CalendarFeedTokenOut(BaseModel):
    url: str | None = None
    webcal_url: str | None = None
    created_at: datetime | None = None
    revoked: bool = False


class CalendarDeadline(BaseModel):
    title: str
    due_at: datetime
    source_type: str
    days_left: int


class CalendarJobAccepted(BaseModel):
    job_id: uuid.UUID
