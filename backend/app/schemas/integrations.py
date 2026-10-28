"""Integrations hub, API keys, webhooks, dead letters, imports and exports — Prompts/41 §41.4."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---- connections ----------------------------------------------------------------------------------------------------
class ConnectionIn(BaseModel):
    capability: str = Field(max_length=40)
    provider: str = Field(max_length=40)
    label: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict, description="secret + public fields; '***' keeps a stored secret")
    public_config: dict[str, Any] = Field(default_factory=dict)
    is_sandbox: bool = True
    college_id: uuid.UUID | None = None


class ConnectionOut(BaseModel):
    id: uuid.UUID
    capability: str
    provider: str
    label: str | None = None
    config_redacted: dict[str, Any] = Field(default_factory=dict)
    public_config: dict[str, Any] = Field(default_factory=dict)
    is_sandbox: bool
    is_default: bool = False
    status: str
    last_health_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    health_history: list[dict[str, Any]] = Field(default_factory=list)


class ConnectionTestRequest(BaseModel):
    action: Literal["ping", "send_test", "create_order", "lookup"] = "ping"
    params: dict[str, Any] = Field(default_factory=dict)


class ConnectionTestOut(BaseModel):
    ok: bool
    latency_ms: int
    detail: str
    sample: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class CapabilityStatusOut(BaseModel):
    capability: str
    name: str
    provider: str | None = None
    status: str
    connection_id: uuid.UUID | None = None
    feature: str | None = None
    feature_enabled: bool = True
    used_by_features: list[str] = Field(default_factory=list)
    last_error: str | None = None


# ---- api keys -------------------------------------------------------------------------------------------------------
class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=60)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100_000)
    expires_at: datetime | None = None
    ip_allowlist: list[str] = Field(default_factory=list, max_length=50)


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    rate_limit_per_minute: int
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    is_active: bool
    created_at: datetime
    revoked_at: datetime | None = None
    ip_allowlist: list[str] = Field(default_factory=list)
    usage_today: int = 0


class ApiKeyCreatedOut(ApiKeyOut):
    secret: str = Field(description="shown once")


# ---- webhooks -------------------------------------------------------------------------------------------------------
class WebhookIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    url: str = Field(max_length=2000, pattern=r"^https://")
    events: list[str] = Field(min_length=1, max_length=200)
    is_active: bool = True
    headers: dict[str, str] = Field(default_factory=dict)


class WebhookOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    events: list[str]
    is_active: bool
    headers: dict[str, str] = Field(default_factory=dict)
    secret_hint: str
    stats: dict[str, int] = Field(default_factory=dict)
    auto_disabled: bool = False
    created_at: datetime | None = None


class WebhookCreatedOut(WebhookOut):
    secret: str


class WebhookTestRequest(BaseModel):
    event_type: str = Field(default="ping", max_length=80)


class DeliveryOut(BaseModel):
    id: uuid.UUID
    webhook_id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    response_code: int | None = None
    response_body: str | None = None
    next_retry_at: datetime | None = None
    delivered_at: datetime | None = None
    created_at: datetime
    payload: dict[str, Any] | None = None


class DeliveryRetryRequest(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    all_dead: bool = False
    webhook_id: uuid.UUID | None = None


class EventCatalogueItem(BaseModel):
    event_type: str
    description: str
    payload_schema: dict[str, Any]
    since: str = "41"


# ---- dead letters / inbound -----------------------------------------------------------------------------------------
class DeadLetterOut(BaseModel):
    kind: Literal["outbox", "webhook", "notification"]
    id: uuid.UUID
    type: str
    error: str | None = None
    attempts: int | None = None
    created_at: datetime | None = None


class DeadLetterAction(BaseModel):
    kind: Literal["outbox", "webhook", "notification"]
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


class InboundEventOut(BaseModel):
    id: str
    provider: str
    connection_id: str | None = None
    event_type: str | None = None
    event_id: str | None = None
    processed: bool
    duplicate: bool = False
    error: str | None = None
    received_at: datetime


# ---- imports --------------------------------------------------------------------------------------------------------
class ImportColumn(BaseModel):
    key: str
    label: str
    type: str = "str"
    required: bool = False
    lookup: str | None = None
    unique_in: str | None = None
    example: str | None = None


class ImportTemplateOut(BaseModel):
    entity: str
    label: str
    module: str
    permission: str
    columns: list[ImportColumn]
    notes: str | None = None


class ImportCreate(BaseModel):
    entity: str = Field(max_length=60)
    file_url: str = Field(max_length=2000)
    mapping: dict[str, str] | None = None
    profile_name: str | None = Field(default=None, max_length=80)
    college_id: uuid.UUID | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ImportOut(BaseModel):
    id: uuid.UUID
    entity: str
    status: str
    mode: str
    file_url: str
    total_rows: int | None = None
    valid_rows: int | None = None
    error_rows: int | None = None
    report: dict[str, Any] | None = None
    mapping: dict[str, Any] | None = None
    job_id: uuid.UUID | None = None
    applied_at: datetime | None = None
    rolled_back_at: datetime | None = None
    created_at: datetime | None = None
    can_rollback: bool = False


class ImportRowOut(BaseModel):
    row_no: int
    raw: dict[str, Any]
    normalized: dict[str, Any] | None = None
    errors: list[dict[str, Any]] | None = None
    status: str
    created_entity_id: uuid.UUID | None = None


class ImportMappingIn(BaseModel):
    mapping: dict[str, str]
    profile_name: str | None = Field(default=None, max_length=80)


class ImportApplyRequest(BaseModel):
    confirm_valid_rows: int = Field(ge=0)
    on_conflict: Literal["skip", "update", "error"] = "skip"


class ImportRollbackRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class WorkbookStepOut(BaseModel):
    order: int
    entity: str
    label: str
    status: str
    import_id: uuid.UUID | None = None
    depends_on: list[int] = Field(default_factory=list)


class WorkbookOut(BaseModel):
    started_at: datetime | None = None
    progress_pct: int
    steps: list[WorkbookStepOut]


class ExportRequest(BaseModel):
    include: list[str] = Field(default_factory=list, max_length=50)


class ExportOut(BaseModel):
    job_id: uuid.UUID
    status: str
    url: str | None = None
    expires_at: datetime | None = None
