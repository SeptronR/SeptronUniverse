"""Audit explorer, chain integrity, exam audit, security console and retention schemas — Prompts/37 §37.4."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ExportFormat = Literal["csv", "xlsx", "json", "pdf"]


# ---- explorer -------------------------------------------------------------------------------------------------------
class AuditUser(BaseModel):
    id: uuid.UUID | None = None
    name: str | None = None


class AuditRowOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    module: str
    action: str
    record_type: str | None = None
    record_id: uuid.UUID | None = None
    record_label: str | None = None
    user: AuditUser | None = None
    impersonator: AuditUser | None = None
    ip_masked: str | None = None
    request_id: str | None = None
    summary: str
    has_diff: bool = False


class AuditListOut(BaseModel):
    items: list[AuditRowOut]
    total: int
    page: int
    page_size: int
    date_from: datetime
    date_to: datetime


class DiffEntry(BaseModel):
    field: str
    old: Any = None
    new: Any = None
    masked: bool = False


class AuditDetailOut(AuditRowOut):
    old_values: dict[str, Any] | None = None
    new_values: dict[str, Any] | None = None
    diff: list[DiffEntry] = Field(default_factory=list)
    masked_fields: list[str] = Field(default_factory=list)
    user_agent: str | None = None
    prev_hash: str | None = None
    hash: str | None = None
    related: list[AuditRowOut] = Field(default_factory=list)


class RecordTimelineOut(BaseModel):
    at: datetime
    source: Literal["audit", "event", "workflow"]
    action: str
    actor: AuditUser | None = None
    summary: str | None = None
    audit_id: uuid.UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class WhoViewedOut(BaseModel):
    audit_id: uuid.UUID
    user: AuditUser
    at: datetime
    action: str
    fields_unmasked: list[str] = Field(default_factory=list)
    ip_masked: str | None = None


class AuditSummaryOut(BaseModel):
    """IQAC / dashboards: counts per module (and per action) — no rows."""

    date_from: datetime
    date_to: datetime
    total: int
    by_module: list[dict[str, Any]]
    by_action: list[dict[str, Any]]
    impersonated: int


class AuditExportRequest(BaseModel):
    query: dict[str, Any] = Field(
        default_factory=dict, description="the explorer filters (module, action, from, to, …)"
    )
    format: ExportFormat = "csv"


class JobQueuedOut(BaseModel):
    job_id: uuid.UUID
    job_type: str
    status: str = "queued"
    report_key: str | None = None


# ---- chain integrity ------------------------------------------------------------------------------------------------
class ChainVerifyRequest(BaseModel):
    from_: datetime | None = Field(default=None, alias="from")
    to: datetime | None = None
    compare_digests: bool = True

    model_config = {"populate_by_name": True}


class BrokenLink(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    reason: str


class ChainVerifyOut(BaseModel):
    ok: bool
    rows: int
    first_broken: BrokenLink | None = None
    digest: str
    duration_ms: int
    date_from: datetime
    date_to: datetime
    digest_mismatches: list[str] = Field(default_factory=list)
    verification_id: str | None = None


class ChainDigestOut(BaseModel):
    date: date
    rows: int
    last_hash: str | None = None
    digest: str
    signed: bool
    key_id: str | None = None
    archived_url: str | None = None
    verified: bool | None = None


# ---- exam audit -----------------------------------------------------------------------------------------------------
ExamSection = Literal[
    "marks", "qp_print", "custody", "valuation", "moderation", "decode", "runs", "publication", "post_result"
]


class ExamAuditEntry(BaseModel):
    at: datetime | None = None
    actor: AuditUser | None = None
    action: str
    subject: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    ip_masked: str | None = None
    gap: bool = False


class ExamAuditOut(BaseModel):
    exam_session_id: uuid.UUID
    section: str
    entries: list[ExamAuditEntry]
    summary: dict[str, Any] = Field(default_factory=dict)


class ExamAuditSummaryOut(BaseModel):
    exam_session_id: uuid.UUID
    session_name: str
    sections: dict[str, int]
    open_gaps: int
    days_to_publication: int | None = None
    decode_visible: bool


class ExamAuditExportRequest(BaseModel):
    sections: list[ExamSection] | None = None
    format: ExportFormat = "pdf"


# ---- security -------------------------------------------------------------------------------------------------------
class SecurityEventOut(BaseModel):
    id: str
    type: str
    at: datetime
    user: AuditUser | None = None
    identifier: str | None = None
    ip_masked: str | None = None
    severity: Literal["info", "low", "medium", "high"]
    details: dict[str, Any] = Field(default_factory=dict)


class AnomalyAlertOut(BaseModel):
    id: str
    rule: str
    count: int
    window: int | None = None
    users: list[AuditUser] = Field(default_factory=list)
    ips: list[str] = Field(default_factory=list)
    first_seen: datetime
    last_seen: datetime | None = None
    acknowledged: bool = False
    acknowledged_by: uuid.UUID | None = None
    note: str | None = None
    recommended_actions: list[dict[str, Any]] = Field(default_factory=list)


class AnomalyAck(BaseModel):
    note: str = Field(min_length=2, max_length=1000)


class AdminSessionOut(BaseModel):
    id: uuid.UUID
    user: AuditUser
    device_label: str | None = None
    platform: str | None = None
    ip_masked: str | None = None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_reason: str | None = None


class SessionRevokeRequest(BaseModel):
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    all: bool = False
    force_mfa_reenrol: bool = False
    reason: str | None = Field(default=None, max_length=300)


class SessionRevokeOut(BaseModel):
    revoked: int
    user_id: uuid.UUID | None = None
    mfa_reset: bool = False


class LoginHistoryAdminOut(BaseModel):
    id: uuid.UUID
    user: AuditUser | None = None
    identifier: str | None = None
    outcome: str
    ip_masked: str | None = None
    user_agent: str | None = None
    occurred_at: datetime


# ---- feature changes / platform actions -----------------------------------------------------------------------------
class FeatureChangeLogOut(BaseModel):
    id: uuid.UUID
    feature_key: str
    old_value: Any = None
    new_value: Any = None
    changed_by: AuditUser | None = None
    changed_at: datetime
    reason: str | None = None
    platform_actor: bool = False


# ---- retention ------------------------------------------------------------------------------------------------------
class RetentionPolicyOut(BaseModel):
    values: dict[str, Any]
    maximums: dict[str, int]
    minimums: dict[str, int]
    defaults: dict[str, Any]


class RetentionPolicyIn(BaseModel):
    values: dict[str, int] = Field(description="policy key → days / years (legal holds have their own endpoints)")
    reason: str | None = Field(default=None, max_length=500)


class RetentionPreviewOut(BaseModel):
    data_class: str
    policy_key: str | None = None
    keep: int | None = None
    cutoff: datetime | None = None
    eligible: int
    held: int
    partitions: list[dict[str, Any]] = Field(default_factory=list)


class LegalHoldScope(BaseModel):
    batch_id: uuid.UUID | None = None
    enrollment_ids: list[uuid.UUID] | None = None
    exam_session_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None


class LegalHoldIn(BaseModel):
    data_class: str = Field(max_length=40)
    scope: LegalHoldScope
    reason: str = Field(min_length=3, max_length=1000)
    until: date | None = None


class LegalHoldOut(BaseModel):
    id: str
    data_class: str
    scope: dict[str, Any]
    reason: str
    until: date | None = None
    set_by: uuid.UUID | None = None
    set_at: datetime
    active: bool = True


class RetentionRunRequest(BaseModel):
    data_class: str = Field(max_length=40)
    period: str | None = Field(default=None, max_length=20, description="archive: academic year '2022-23' or 'YYYY-MM'")
    dry_run: bool = False


class ArchiveManifestOut(BaseModel):
    id: str
    kind: Literal["purge", "archive", "restore", "erase"]
    data_class: str
    period: str | None = None
    rows: int
    file_url: str | None = None
    storage_key: str | None = None
    sha256: str | None = None
    status: str
    created_at: datetime
    created_by: uuid.UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RestoreRequest(BaseModel):
    manifest_id: str = Field(max_length=60)
