"""Privacy schemas — Prompts/02 §02.4 (DPDP consents, data-subject requests)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

ConsentPurposeName = Literal["academic", "communication", "marketing", "health", "photo", "third_party"]
DsrTypeName = Literal["access", "export", "correction", "erasure"]


class ConsentRequest(BaseModel):
    purpose: ConsentPurposeName
    granted: bool
    text_version: str | None = Field(default=None, max_length=20)


class ConsentResponse(ORMModel):
    id: uuid.UUID
    purpose: str
    granted: bool
    text_version: str | None = None
    recorded_at: datetime
    withdrawn_at: datetime | None = None


class DataSubjectRequestCreate(BaseModel):
    request_type: DsrTypeName
    details: str | None = Field(default=None, max_length=4000)


class DataSubjectRequestResponse(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    request_type: str
    status: str
    details: str | None = None
    due_at: datetime | None = None
    result_url: str | None = None
    created_at: datetime
    closed_at: datetime | None = None
