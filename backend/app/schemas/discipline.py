"""Discipline schemas — Prompts/27 §27.4 (OpenAPI names prefixed ``Disc``)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


SanctionLit = Literal[
    "warning", "fine", "suspension", "expulsion", "community_service", "hostel_eviction", "debar_placement"
]


class DiscSource(BaseModel):
    type: Literal["manual", "hostel", "malpractice", "false_sos", "placement", "grievance"] = "manual"
    id: uuid.UUID | None = None


class DiscEvidence(BaseModel):
    name: str = Field(max_length=200)
    url: str | None = Field(None, max_length=1000)
    note: str | None = Field(None, max_length=1000)


class DiscCaseCreate(_Strict):
    subject_type: Literal["student", "staff"]
    subject_id: uuid.UUID
    category: str = Field(min_length=2, max_length=40)
    description: str = Field(min_length=5, max_length=10000)
    evidence: list[DiscEvidence] = []
    source: DiscSource | None = None


class DiscInquiry(_Strict):
    committee_id: uuid.UUID
    hearing_at: datetime | None = None
    notice_text: str | None = Field(None, max_length=5000)


class DiscNotice(_Strict):
    notice_text: str = Field(min_length=5, max_length=5000)
    respond_by: date | None = None


class DiscHearing(_Strict):
    hearing_at: datetime
    venue: str | None = Field(None, max_length=200)
    attendees: list[str] = []
    minutes: str | None = Field(None, max_length=10000)


class DiscStatement(_Strict):
    text: str = Field(min_length=5, max_length=10000)
    attachments: list[DiscEvidence] = []


class DiscSanction(BaseModel):
    type: SanctionLit
    amount_paise: int | None = Field(None, ge=0)
    from_on: date | None = None
    to_on: date | None = None
    hours: float | None = Field(None, ge=0, le=500)
    details: str | None = Field(None, max_length=1000)


class DiscDecision(_Strict):
    sanctions: list[DiscSanction] = Field(min_length=1, max_length=10)
    decision_text: str = Field(min_length=5, max_length=10000)


class DiscAppealCreate(_Strict):
    grounds: str = Field(min_length=10, max_length=10000)
    attachments: list[DiscEvidence] = []


class DiscAppealDecision(_Strict):
    outcome: Literal["uphold", "modify", "revoke"]
    sanctions: list[DiscSanction] | None = None
    remarks: str = Field(min_length=3, max_length=5000)


class DiscCaseOut(BaseModel):
    id: uuid.UUID
    case_number: str
    subject_type: str
    subject_id: uuid.UUID
    subject_name: str | None = None
    department_id: uuid.UUID | None = None
    category: str
    description: str | None = None
    status: str
    committee_id: uuid.UUID | None = None
    committee_name: str | None = None
    hearing_at: datetime | None = None
    sanctions: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    fee_invoice_id: uuid.UUID | None = None
    appeal_status: str | None = None
    appeal: dict[str, Any] | None = None
    decided_at: datetime | None = None
    decision_text: str | None = None
    decision_document_id: uuid.UUID | None = None
    evidence: list[dict[str, Any]] = []
    notices: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    hearings: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    source: dict[str, Any] | None = None
    workflow_instance_id: uuid.UUID | None = None
    created_at: datetime | None = None
    can_appeal: bool = False
    is_subject: bool = False


class DiscRegisterRow(BaseModel):
    case_number: str
    subject_type: str
    subject: str | None = None
    category: str
    reported_on: datetime | None = None
    status: str
    sanctions: str | None = None
    decided_on: datetime | None = None
    appeal_status: str | None = None
