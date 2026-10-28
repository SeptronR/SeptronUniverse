"""Portal, PWA, notification-centre, tour, help-context and locale schemas — Prompts/39 §39.4.

Value objects of the unified pages (``UnifiedRequestItem`` …) are read models built by the aggregators in
``services/portals/aggregators.py``; ``ManifestOut`` is a Web App Manifest (served as ``application/manifest+json``).
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.communication import QuietHours

DigestLit = Literal["none", "daily", "weekly"]
ChannelLit = Literal["in_app", "sms", "whatsapp", "email", "push"]


# ---- shell ----------------------------------------------------------------------------------------------------------
class PortalNavEntry(BaseModel):
    key: str
    label_key: str
    route: str
    icon: str
    feature: str | None = None
    permission: str | None = None


class BrandingOut(BaseModel):
    app_name: str
    short_name: str
    theme_color: str = "#4f46e5"
    background_color: str = "#f8fafc"
    logo_url: str | None = None
    icons: list[dict[str, str]] = Field(default_factory=list)
    splash: str | None = None


class TermChip(BaseModel):
    id: uuid.UUID
    name: str


class PortalConfigOut(BaseModel):
    persona: str | None = None
    personas: list[str] = Field(default_factory=list, description="every persona the user holds (role switch)")
    home: str | None = None
    branding: BrandingOut
    tabs: list[PortalNavEntry] = Field(default_factory=list)
    more: list[PortalNavEntry] = Field(default_factory=list)
    home_widgets: list[str] = Field(default_factory=list)
    unified: list[str] = Field(default_factory=list)
    language: str = "en"
    locales: list[str] = Field(default_factory=lambda: ["en"])
    features_missing: list[str] = Field(default_factory=list)
    admin_switch: bool = False
    term: TermChip | None = None
    ward_id: uuid.UUID | None = None
    tours_enabled: bool = False
    push_enabled: bool = False


class WardOut(BaseModel):
    student_id: uuid.UUID
    name: str
    registration_number: str | None = None
    program: str | None = None
    consent: bool
    active: bool = False


class WardSwitchIn(BaseModel):
    student_id: uuid.UUID


# ---- unified pages --------------------------------------------------------------------------------------------------
class UnifiedRequestItem(BaseModel):
    source_module: str
    type: str
    id: uuid.UUID
    number: str | None = None
    title: str
    status: str
    raw_status: str | None = None
    created_at: datetime | None = None
    route: str
    student_id: uuid.UUID | None = None


class MyRequestsOut(BaseModel):
    items: list[UnifiedRequestItem]
    by_status: dict[str, int] = Field(default_factory=dict)
    by_module: dict[str, int] = Field(default_factory=dict)
    launchers: list[PortalNavEntry] = Field(default_factory=list, description="'raise new' entries")


class UnifiedDocumentItem(BaseModel):
    id: uuid.UUID
    template_type: str | None = None
    document_number: str | None = None
    title: str
    person_type: str | None = None
    person_id: uuid.UUID | None = None
    issued_at: datetime | None = None
    verification_token: str | None = None
    verify_url: str | None = None
    download_route: str


class UnifiedPaymentItem(BaseModel):
    kind: Literal["invoice", "payment", "refund"]
    id: uuid.UUID
    number: str | None = None
    source_type: str | None = None
    description: str | None = None
    amount_paise: int
    balance_paise: int | None = None
    status: str
    at: date | datetime | None = None
    due_date: date | None = None
    payable: bool = False
    student_id: uuid.UUID | None = None
    receipt_url: str | None = None


class PaymentTotals(BaseModel):
    invoiced_paise: int = 0
    paid_paise: int = 0
    balance_paise: int = 0
    refunded_paise: int = 0


class MyPaymentsOut(BaseModel):
    invoices: list[UnifiedPaymentItem]
    payments: list[UnifiedPaymentItem]
    refunds: list[UnifiedPaymentItem]
    totals: PaymentTotals


class ApprovalItem(BaseModel):
    step_id: uuid.UUID
    instance_id: uuid.UUID
    workflow: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    title: str
    step_order: int
    sla_due_at: datetime | None = None
    created_at: datetime | None = None
    route: str


class CalendarItem(BaseModel):
    id: str
    title: str
    start: datetime | date
    end: datetime | date | None = None
    kind: str
    route: str | None = None


class MyCalendarOut(BaseModel):
    items: list[CalendarItem]
    subscribe_url: str | None = None


class TimelineItem(BaseModel):
    at: datetime
    kind: str
    title: str
    module: str | None = None
    route: str | None = None


# ---- notification centre --------------------------------------------------------------------------------------------
class NotificationCounts(BaseModel):
    unread: int
    unread_by_category: dict[str, int]
    snoozed: dict[str, datetime] = Field(default_factory=dict)
    pending_ack: int = 0


class NotificationDetail(BaseModel):
    id: uuid.UUID
    title: str
    body: str | None = None
    category: str | None = None
    event_type: str | None = None
    route: str | None = None
    priority: str = "normal"
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


class MarkReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    all: bool = False
    category: str | None = Field(default=None, max_length=40)


class MarkReadOut(BaseModel):
    marked: int
    unread: int


class SnoozeIn(BaseModel):
    category: str = Field(max_length=40)
    hours: int = Field(ge=0, le=168, description="0 clears the snooze")


class CategoryChannels(BaseModel):
    category: str
    channels: list[ChannelLit]
    locked: list[ChannelLit] = Field(default_factory=list, description="cells the policy keeps on")
    available: list[ChannelLit] = Field(default_factory=list)


class PreferencesOut(BaseModel):
    categories: list[CategoryChannels]
    quiet_hours: QuietHours | None = None
    digest: DigestLit = "none"
    push_subscribed: bool = False
    available_channels: list[str]


class PreferencesIn(BaseModel):
    categories: list[CategoryChannels] = Field(default_factory=list, max_length=40)
    quiet_hours: QuietHours | None = None
    clear_quiet_hours: bool = False
    digest: DigestLit | None = None


class NotificationTestIn(BaseModel):
    category: str = Field(default="system", max_length=40)
    channels: list[ChannelLit] = Field(default_factory=lambda: list[ChannelLit](["in_app", "push"]))


# ---- push / PWA -----------------------------------------------------------------------------------------------------
class PushKeys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class PushSubscribeIn(BaseModel):
    endpoint: str = Field(max_length=1000, pattern=r"^https://")
    keys: PushKeys
    topics: list[str] = Field(default_factory=list, max_length=30)
    platform: str = Field(default="web", max_length=20)


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(max_length=1000)


class PushSubscribeOut(BaseModel):
    id: uuid.UUID
    endpoint: str
    topics: list[str]
    is_active: bool
    created: bool = False


class PushTestRequest(BaseModel):
    title: str = Field(default="Test notification", max_length=120)
    body: str = Field(default="Push notifications are working.", max_length=400)
    route: str | None = Field(default=None, max_length=200)


class PushTestOut(BaseModel):
    devices: int
    log_ids: list[uuid.UUID]
    payload: dict[str, Any]


class VapidKeyOut(BaseModel):
    public_key: str
    configured: bool


class PwaConfigOut(BaseModel):
    version: str
    cache_ttl: dict[str, int]
    swr_routes: dict[str, str]
    precache: list[str]
    offline_route: str = "/offline"
    background_sync: list[str]
    push_enabled: bool


class InstallPing(BaseModel):
    platform: str = Field(default="web", max_length=20)
    outcome: Literal["accepted", "dismissed", "installed"] = "installed"


# ---- tours / help / feedback / locale ------------------------------------------------------------------------------
class TourStep(BaseModel):
    target: str
    title: str
    body: str
    placement: str = "bottom"


class TourDef(BaseModel):
    key: str
    route: str
    roles: list[str]
    version: int
    title: str | None = None
    steps: list[TourStep]


class TourStateOut(BaseModel):
    completed: dict[str, int] = Field(default_factory=dict)
    dismissed: list[str] = Field(default_factory=list)
    disabled_routes: list[str] = Field(default_factory=list)


class TourStateIn(BaseModel):
    key: str = Field(max_length=80)
    version: int = Field(ge=1, le=1000)
    completed: bool = False
    dismissed: bool = False
    reset: bool = False


class HelpContextOut(BaseModel):
    route: str
    article: dict[str, Any] | None = None
    related: list[dict[str, Any]] = Field(default_factory=list)
    tours: list[str] = Field(default_factory=list)


class HelpfulIn(BaseModel):
    helpful: bool = True


class HelpfulOut(BaseModel):
    slug: str
    helpful: int
    not_helpful: int


class LocalePackOut(BaseModel):
    locale: str
    strings: dict[str, Any]
    overrides: dict[str, str] = Field(default_factory=dict)


class MeUpdateIn(BaseModel):
    locale: str | None = Field(default=None, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    timezone: str | None = Field(default=None, max_length=60)
    theme: Literal["light", "dark", "system"] | None = None


class MeUpdateOut(BaseModel):
    locale: str | None = None
    timezone: str | None = None
    theme: str | None = None
