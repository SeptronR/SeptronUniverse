"""Communication schemas — Prompts/04 §04.4 (templates, DLT/WhatsApp registries, preferences, notifications,
message logs, ad-hoc sends, announcements, devices)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.authz.masking import MaskedStr
from app.schemas.common import ORMModel

ChannelName = Literal["in_app", "sms", "whatsapp", "email", "push"]
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


# ---- templates --------------------------------------------------------------------------------------------------
class TemplateCreate(BaseModel):
    event_trigger: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    channels: list[ChannelName] = Field(default_factory=lambda: list[ChannelName](["in_app"]), min_length=1)
    subject_template: str | None = None
    body_template: str = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)
    language: str = Field(default="en", max_length=10)
    dlt_template_id: str | None = Field(default=None, max_length=40)
    whatsapp_template_name: str | None = Field(default=None, max_length=120)
    activate: bool = True


class TemplateUpdate(BaseModel):
    """Editing creates a new version (the previous one stays for audit); ``activate`` switches the resolver to it."""

    name: str | None = Field(default=None, min_length=2, max_length=120)
    channels: list[ChannelName] | None = None
    subject_template: str | None = None
    body_template: str | None = None
    variables: list[str] | None = None
    dlt_template_id: str | None = Field(default=None, max_length=40)
    whatsapp_template_name: str | None = Field(default=None, max_length=120)
    activate: bool = True


class TemplateResponse(ORMModel):
    id: uuid.UUID
    institution_id: uuid.UUID | None = None
    event_trigger: str
    name: str
    channels: list[str]
    subject_template: str | None = None
    body_template: str
    variables: list[str] | None = None
    language: str
    version: int
    is_active: bool
    dlt_template_id: str | None = None
    whatsapp_template_name: str | None = None
    updated_at: datetime
    is_platform: bool = False
    category: str | None = None


class TemplatePreviewRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


class TemplatePreview(BaseModel):
    subject: str | None = None
    body: str
    missing_variables: list[str] = Field(default_factory=list)


class DltTemplateCreate(BaseModel):
    sender_id: str = Field(min_length=3, max_length=10)
    entity_id: str | None = Field(default=None, max_length=30)
    template_id: str = Field(min_length=3, max_length=40)
    template_text: str = Field(min_length=1)
    category: Literal["transactional", "service_implicit", "service_explicit", "promotional"] = "transactional"
    status: Literal["approved", "pending", "rejected"] = "approved"


class DltTemplateResponse(ORMModel):
    id: uuid.UUID
    sender_id: str
    entity_id: str | None = None
    template_id: str
    template_text: str
    category: str
    status: str
    created_at: datetime


class WhatsappTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9_]+$")
    language: str = Field(default="en", max_length=10)
    category: Literal["utility", "marketing", "authentication"] = "utility"
    body: str = Field(min_length=1)
    components: dict[str, Any] | list[Any] | None = None


class WhatsappTemplateResponse(ORMModel):
    id: uuid.UUID
    name: str
    language: str
    category: str
    body: str
    components: dict[str, Any] | list[Any] | None = None
    status: str
    meta_template_id: str | None = None
    updated_at: datetime


# ---- preferences ------------------------------------------------------------------------------------------------
class QuietHours(BaseModel):
    from_: str = Field(alias="from", pattern=HHMM)
    to: str = Field(pattern=HHMM)

    model_config = {"populate_by_name": True}


class PreferenceItem(BaseModel):
    category: str = Field(max_length=40)
    channels: list[ChannelName]
    quiet_hours: QuietHours | None = None
    digest: Literal["none", "daily", "weekly"] = "none"
    mandatory: bool = False


class PreferenceUpdate(BaseModel):
    items: list[PreferenceItem] = Field(min_length=1, max_length=40)


class PreferenceResponse(BaseModel):
    items: list[PreferenceItem]
    available_channels: list[str]


# ---- notifications / logs ---------------------------------------------------------------------------------------
class NotificationResponse(ORMModel):
    id: uuid.UUID
    title: str
    body: str | None = None
    category: str | None = None
    event_type: str | None = None
    link: dict[str, Any] | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime
    route: str | None = None


class UnreadCount(BaseModel):
    unread: int


class MessageLogResponse(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    recipient: MaskedStr  # masked unless communication:view_pii
    channel: str
    event_type: str | None = None
    template_id: uuid.UUID | None = None
    subject: str | None = None
    body_preview: str | None = None
    provider: str | None = None
    provider_message_id: str | None = None
    status: str
    error: str | None = None
    cost_paise: int | None = None
    event_id: uuid.UUID | None = None
    created_at: datetime
    sent_at: datetime | None = None
    delivered_at: datetime | None = None


class Audience(BaseModel):
    user_ids: list[uuid.UUID] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    direct_contacts: list[dict[str, str]] = Field(default_factory=list)
    include_guardians: bool = False

    @model_validator(mode="after")
    def _not_empty(self) -> "Audience":
        if not (
            self.user_ids
            or self.roles
            or self.college_id
            or self.department_id
            or self.program_id
            or self.batch_id
            or self.direct_contacts
        ):
            raise ValueError("the audience is empty")
        return self


class SendMessageRequest(BaseModel):
    event_type: str | None = Field(default=None, max_length=80)
    template_id: uuid.UUID | None = None
    audience: Audience
    context: dict[str, Any] = Field(default_factory=dict)
    channels: list[ChannelName] | None = None

    @model_validator(mode="after")
    def _one(self) -> "SendMessageRequest":
        if not (self.event_type or self.template_id):
            raise ValueError("event_type or template_id is required")
        return self


class SendMessageResponse(BaseModel):
    event_id: uuid.UUID | None
    event_type: str
    queued: bool = True


class WebhookCallback(BaseModel):
    message_id: str = Field(max_length=120, description="provider message id (or our message_logs id)")
    status: Literal["sent", "delivered", "failed", "bounced", "read"]
    error: str | None = Field(default=None, max_length=500)
    cost_paise: int | None = None


# ---- announcements ----------------------------------------------------------------------------------------------
class AudienceRules(BaseModel):
    roles: list[str] = Field(default_factory=list)
    college_ids: list[uuid.UUID] = Field(default_factory=list)
    department_ids: list[uuid.UUID] = Field(default_factory=list)
    program_ids: list[uuid.UUID] = Field(default_factory=list)
    batch_ids: list[uuid.UUID] = Field(default_factory=list)
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class AnnouncementCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1)
    category: str | None = Field(default=None, max_length=30)
    college_id: uuid.UUID | None = None
    audience_rules: AudienceRules = Field(default_factory=AudienceRules)
    attachments: list[dict[str, Any]] | None = None
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    requires_ack: bool = False
    is_pinned: bool = False
    channels: list[ChannelName] = Field(default_factory=lambda: list[ChannelName](["in_app", "push"]))


class AnnouncementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    body: str | None = None
    category: str | None = Field(default=None, max_length=30)
    audience_rules: AudienceRules | None = None
    attachments: list[dict[str, Any]] | None = None
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    requires_ack: bool | None = None
    is_pinned: bool | None = None


class AckStats(BaseModel):
    total: int
    read: int
    acknowledged: int


class AnnouncementResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    title: str
    body: str
    category: str | None = None
    audience_rules: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] | None = None
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    requires_ack: bool
    is_pinned: bool
    is_active: bool
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    status: str = "draft"  # draft | scheduled | published | expired
    my_read_at: datetime | None = None
    my_acknowledged_at: datetime | None = None
    ack_stats: AckStats | None = None


class AnnouncementPublish(BaseModel):
    channels: list[ChannelName] = Field(default_factory=lambda: list[ChannelName](["in_app", "push"]))


class AcknowledgeRequest(BaseModel):
    acknowledge: bool = True


# ---- devices ----------------------------------------------------------------------------------------------------
class DeviceRegister(BaseModel):
    provider: Literal["fcm", "webpush", "expo"]
    platform: Literal["android", "ios", "web"]
    token: str = Field(min_length=2, max_length=4096)
    topics: list[str] = Field(default_factory=list)

    @field_validator("topics")
    @classmethod
    def _topics(cls, v: list[str]) -> list[str]:
        return sorted({t[:80] for t in v})


class DeviceResponse(ORMModel):
    id: uuid.UUID
    provider: str
    platform: str
    topics: list[str] | None = None
    is_active: bool
    created_at: datetime
