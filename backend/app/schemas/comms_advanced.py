"""Communication-advanced schemas — Prompts/24 §24.4 (OpenAPI names prefixed ``Comms`` / ``Campaign`` / ``Bot`` /
``Assistant`` to stay unique)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


ChannelLit = Literal["sms", "whatsapp", "email", "push", "in_app"]


class SegmentCondition(_Strict):
    field: str = Field(min_length=2, max_length=40)
    op: Literal["eq", "in", "between", "gte", "lte", "is_null"]
    value: Any = None


class DuesRule(_Strict):
    min_paise: int = Field(0, ge=0)
    overdue_only: bool = False


class AttendanceRule(_Strict):
    below_pct: float = Field(ge=0, le=100)
    term_id: uuid.UUID | None = None


class SegmentRules(_Strict):
    all: list[SegmentCondition] = []
    any: list[SegmentCondition] = []
    roles: list[str] = []
    person_types: list[Literal["student", "guardian", "staff"]] = ["student"]
    college_id: uuid.UUID | None = None
    program_ids: list[uuid.UUID] = []
    batch_ids: list[uuid.UUID] = []
    department_ids: list[uuid.UUID] = []
    hostel_ids: list[uuid.UUID] = []
    route_ids: list[uuid.UUID] = []
    dues: DuesRule | None = None
    attendance: AttendanceRule | None = None
    custom_user_ids: list[uuid.UUID] = []
    notify_guardians: bool = False


class SegmentPreview(BaseModel):
    count: int
    by_channel_reachable: dict[str, int]
    sample: list[dict[str, Any]]


class SavedSegmentIn(_Strict):
    name: str = Field(min_length=2, max_length=120)
    rules: SegmentRules
    shared: bool = False


class SavedSegmentOut(BaseModel):
    id: uuid.UUID
    name: str
    rules: dict[str, Any]
    shared: bool
    owner_user_id: uuid.UUID | None = None
    updated_at: datetime | None = None


class CampaignBody(_Strict):
    sms: str | None = Field(None, max_length=1000)
    sms_dlt_template_id: uuid.UUID | None = None
    whatsapp_template: str | None = Field(None, max_length=120)
    whatsapp_text: str | None = Field(None, max_length=4000)
    email_subject: str | None = Field(None, max_length=200)
    email_html: str | None = Field(None, max_length=200_000)
    push_title: str | None = Field(None, max_length=65)
    push_body: str | None = Field(None, max_length=240)
    in_app: str | None = Field(None, max_length=4000)


class CampaignCreate(_Strict):
    name: str = Field(min_length=2, max_length=160)
    channels: list[ChannelLit] = Field(min_length=1)
    audience_rules: SegmentRules | None = None
    segment_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    body_override: CampaignBody | None = None
    variables: dict[str, Any] = {}
    scheduled_at: datetime | None = None
    respect_quiet_hours: bool = True
    category: Literal["transactional", "marketing", "academic", "emergency"] = "academic"


class CampaignUpdate(_Strict):
    name: str | None = Field(None, min_length=2, max_length=160)
    channels: list[ChannelLit] | None = None
    audience_rules: SegmentRules | None = None
    template_id: uuid.UUID | None = None
    body_override: CampaignBody | None = None
    variables: dict[str, Any] | None = None
    scheduled_at: datetime | None = None
    respect_quiet_hours: bool | None = None


class ComplianceResult(BaseModel):
    ok: bool
    errors: list[str]
    warnings: list[str] = []


class CampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    channels: list[str]
    audience_rules: dict[str, Any]
    template_id: uuid.UUID | None = None
    body: dict[str, Any] = {}
    scheduled_at: datetime | None = None
    status: str
    is_emergency: bool
    total_recipients: int | None = None
    sent_count: int
    failed_count: int
    job_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    cost_estimate_paise: int = 0
    compliance: ComplianceResult | None = None
    approval: dict[str, Any] = {}


class CampaignAction(_Strict):
    action: Literal["submit", "approve", "reject", "schedule", "send_now", "cancel", "pause", "resume", "retry_failed"]
    scheduled_at: datetime | None = None
    remarks: str | None = Field(None, max_length=500)


class CampaignReport(BaseModel):
    campaign_id: uuid.UUID
    sent: int
    delivered: int
    failed: int
    read: int
    queued: int
    deferred: int
    cost_paise: int
    by_channel: dict[str, dict[str, int]]
    failures_by_reason: dict[str, int]
    timeline: list[dict[str, Any]]


class AnnouncementAnalytics(BaseModel):
    announcement_id: uuid.UUID
    audience: int
    read: int
    acknowledged: int
    requires_ack: bool
    funnel: list[dict[str, Any]]
    pending: list[dict[str, Any]] = []


class AckReminderRequest(_Strict):
    channels: list[ChannelLit] = ["in_app", "push"]


class EmergencyBroadcast(_Strict):
    alert_type: Literal["sos", "fire", "medical", "security", "weather", "other"] = "security"
    message: str = Field(min_length=5, max_length=1000)
    audience: Literal["all", "college", "hostel", "custom"] = "all"
    college_id: uuid.UUID | None = None
    hostel_id: uuid.UUID | None = None
    custom_user_ids: list[uuid.UUID] = []
    channels: list[ChannelLit] | None = None
    incident_ref: str | None = Field(None, max_length=80)
    emergency_alert_id: uuid.UUID | None = None
    drill: bool = False
    confirm: str = Field(description="type BROADCAST to confirm")


class AllClear(_Strict):
    message: str = Field("All clear — normal activities resume.", min_length=3, max_length=500)


class EmergencyLog(BaseModel):
    campaign_id: uuid.UUID
    alert_type: str | None = None
    message: str
    raised_by: uuid.UUID | None = None
    at: datetime
    recipients: int | None = None
    sent: int
    drill: bool
    all_clear_at: datetime | None = None
    incident_ref: str | None = None


class BotFlowDefinition(_Strict):
    key: str = Field(min_length=2, max_length=40)
    label: str = Field(min_length=2, max_length=60)
    trigger_words: list[str] = []
    requires_auth: bool = True
    roles: list[str] = []
    enabled: bool = True


class BotFlowsPut(_Strict):
    flows: list[BotFlowDefinition]
    greeting: str | None = Field(None, max_length=500)


class BotTestRequest(_Strict):
    message: str = Field(min_length=1, max_length=500)
    as_user_id: uuid.UUID | None = None


class BotSessionOut(BaseModel):
    id: uuid.UUID
    channel: str
    phone: str | None = None
    user_id: uuid.UUID | None = None
    flow_key: str | None = None
    state: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = []
    last_activity_at: datetime
    handoff: bool = False


class AssistantChatRequest(_Strict):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = {}


class AssistantChatResponse(BaseModel):
    conversation_id: uuid.UUID
    reply: str
    citations: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    links: list[dict[str, str]] = []


class AssistantOptIn(_Strict):
    accepted: bool


class AssistantMe(BaseModel):
    enabled: bool
    opted_in: bool
    allowed: bool
    provider: str


class AssistantConfig(_Strict):
    provider: Literal["mock", "groq", "openai", "azure", "ollama"] = "mock"
    opt_in_required: bool = True
    allowed_roles: list[str] = []
    allow_pii_to_provider: bool = False
    max_tokens: int = Field(800, ge=64, le=8000)


class SimulatorInboxOut(BaseModel):
    id: str
    channel: str
    recipient: str
    subject: str | None = None
    body: str | None = None
    status: str
    at: datetime


class SimInbound(_Strict):
    phone: str = Field(min_length=6, max_length=20)
    text: str = Field(min_length=1, max_length=1000)
    wa_message_id: str | None = Field(None, max_length=120)


class SimProviderEvent(_Strict):
    message_log_id: uuid.UUID
    status: Literal["delivered", "read", "failed", "bounced"]
    error: str | None = None


class DeliveryAnalyticsOut(BaseModel):
    period_from: datetime
    period_to: datetime
    totals: dict[str, int]
    by_channel: dict[str, dict[str, int]]
    by_day: list[dict[str, Any]]
    failures_by_reason: dict[str, int]
    cost_paise: int


class ProviderHealthOut(BaseModel):
    channel: str
    provider: str
    ok: bool
    detail: str
    last_errors: list[str] = []


class CommsJobAccepted(BaseModel):
    job_id: uuid.UUID


class MyMessageOut(BaseModel):
    id: uuid.UUID
    channel: str
    subject: str | None = None
    body_preview: str | None = None
    status: str
    event_type: str | None = None
    created_at: datetime
