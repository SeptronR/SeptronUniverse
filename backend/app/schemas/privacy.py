"""Privacy schemas — Prompts/02 §02.4 (DPDP consents, data-subject requests)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

# Phase 02 names kept for older clients; Phase 43 adds the registry of ``app/core/privacy_registry.py``
ConsentPurposeName = Literal[
    "academic",
    "communication",
    "marketing",
    "health",
    "photo",
    "third_party",
    "communication_transactional",
    "communication_marketing",
    "photo_media",
    "third_party_placement",
    "analytics_external",
    "biometric",
    "location",
    "guardian_access",
]
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
    on_behalf_student_id: uuid.UUID | None = None  # Phase 43: guardian filing for a minor ward


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


# ---- Phase 43 (Prompts/43 §43.4) -------------------------------------------------------------------------------------
class ConsentPurposeOut(BaseModel):
    key: str
    mandatory: bool
    legal_basis: str
    text_version: str
    texts: dict[str, str]


class ConsentBannerOut(BaseModel):
    purposes: list[ConsentPurposeOut]
    notice_version: str
    requires_update: bool
    current: dict[str, bool] = Field(default_factory=dict)
    is_minor: bool = False


class ConsentBulkIn(BaseModel):
    grants: dict[str, bool] = Field(min_length=1)
    notice_version: str | None = Field(default=None, max_length=20)
    on_behalf_student_id: uuid.UUID | None = None


class ConsentReportOut(BaseModel):
    counts: dict[str, dict[str, int]]
    rows: list[dict[str, object]]


class NoticeIn(BaseModel):
    key: str = Field(max_length=40)
    texts: dict[str, str] = Field(min_length=1)
    effective_from: datetime | None = None


class NoticeOut(BaseModel):
    key: str
    version: str
    texts: dict[str, str]
    effective_from: datetime | None = None
    draft: dict[str, object] | None = None


class DsrIdentityVerify(BaseModel):
    method: Literal["otp", "document"]
    otp: str | None = Field(default=None, max_length=10)
    document_url: str | None = Field(default=None, max_length=2000)


class DsrCorrection(BaseModel):
    table: str = Field(max_length=60)
    record_id: uuid.UUID | None = None
    field: str = Field(max_length=60)
    new_value: str = Field(max_length=500)


class DsrAction(BaseModel):
    action: Literal["verify_identity", "start", "extend", "complete", "reject"]
    reason: str | None = Field(default=None, max_length=1000)
    corrections: list[DsrCorrection] = Field(default_factory=list, max_length=50)


class DsrOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    request_type: str
    status: str
    details: str | None = None
    due_at: datetime | None = None
    result_url: str | None = None
    created_at: datetime
    closed_at: datetime | None = None
    identity_verified: bool = False
    extensions: int = 0
    filed_by: uuid.UUID | None = None
    timeline: list[dict[str, object]] = Field(default_factory=list)
    work_items: list[dict[str, object]] = Field(default_factory=list)
    manifest_id: str | None = None
