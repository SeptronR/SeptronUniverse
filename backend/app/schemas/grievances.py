"""Grievance schemas — Prompts/27 §27.4 (OpenAPI names prefixed ``Grv``)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


GrvCategoryLit = Literal[
    "academic", "exam", "fee", "hostel", "harassment", "ragging", "discrimination", "infrastructure", "other"
]
GrvCommitteeLit = Literal["grievance_cell", "icc", "anti_ragging", "sc_st_cell", "obc_cell"]
GrvPriorityLit = Literal["low", "normal", "high", "urgent"]


class GrvAttachment(BaseModel):
    name: str = Field(max_length=200)
    url: str = Field(max_length=1000)


class GrvCreate(_Strict):
    category: GrvCategoryLit
    description: str = Field(min_length=10, max_length=10000)
    attachments: list[GrvAttachment] = []
    is_anonymous: bool = False
    on_behalf_enrollment_id: uuid.UUID | None = None
    priority: GrvPriorityLit = "normal"
    contact_email: str | None = Field(None, max_length=200)


class GrvAnonymousCreate(_Strict):
    category: GrvCategoryLit
    description: str = Field(min_length=10, max_length=10000)
    attachments: list[GrvAttachment] = []
    captcha_token: str | None = None
    contact_email: str | None = Field(None, max_length=200)


class GrvCreated(BaseModel):
    id: uuid.UUID
    ticket_number: str
    status: str
    committee: str | None = None
    sla_due_at: datetime | None = None
    tracking_secret: str | None = None  # shown once, anonymous tickets only


class GrvTimelineItem(BaseModel):
    at: datetime | None = None
    by: str | None = None
    note: str
    is_internal: bool = False
    attachments: list[Any] = []


class GrvOut(BaseModel):
    id: uuid.UUID
    ticket_number: str
    category: str
    description: str | None = None
    is_anonymous: bool
    raised_by_user_id: uuid.UUID | None = None
    raised_by_name: str | None = None
    student_program_enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    department_id: uuid.UUID | None = None
    priority: str
    committee: str | None = None
    committee_id: uuid.UUID | None = None
    assigned_to: uuid.UUID | None = None
    assignee_name: str | None = None
    sla_due_at: datetime | None = None
    sla_breached: bool = False
    status: str
    resolution: str | None = None
    resolved_at: datetime | None = None
    satisfaction_rating: int | None = None
    confidential: bool = False
    attachments: list[Any] = []
    timeline: list[GrvTimelineItem] = []
    workflow_instance_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    can_reopen: bool = False
    can_rate: bool = False


class GrvUpdateIn(_Strict):
    note: str = Field(min_length=1, max_length=5000)
    is_internal: bool = False
    attachments: list[GrvAttachment] = []


class GrvTriage(_Strict):
    committee: GrvCommitteeLit | None = None
    assigned_to: uuid.UUID | None = None
    priority: GrvPriorityLit | None = None
    sla_due_at: datetime | None = None
    status: Literal["acknowledged", "under_review"] | None = None
    note: str | None = Field(None, max_length=2000)


class GrvResolve(_Strict):
    resolution: str = Field(min_length=3, max_length=5000)


class GrvEscalate(_Strict):
    reason: str = Field(min_length=3, max_length=2000)


class GrvRate(_Strict):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=1000)


class GrvReopen(_Strict):
    reason: str = Field(min_length=3, max_length=2000)


class GrvTrack(BaseModel):
    ticket_number: str
    category: str
    status: str
    committee: str | None = None
    sla_due_at: datetime | None = None
    created_at: datetime | None = None
    resolution: str | None = None
    timeline: list[GrvTimelineItem] = []


class GrvRegisterRow(BaseModel):
    ticket_number: str
    category: str
    committee: str | None = None
    complainant: str
    received_on: datetime | None = None
    status: str
    resolved_on: datetime | None = None
    days_taken: float | None = None
    within_sla: bool | None = None
    action_taken: str | None = None


class GrvRegister(BaseModel):
    kind: str
    period: str | None = None
    rows: list[GrvRegisterRow]
    totals: dict[str, int]
