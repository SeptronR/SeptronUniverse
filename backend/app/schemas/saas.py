"""SaaS schemas — Prompts/02 §02.4 (entitlements), the one-time ``/install`` bootstrap and Prompts/38 §38.4 (super
admin & SaaS operations)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field


class EntitlementLimits(BaseModel):
    students: int | None = None
    staff: int | None = None
    storage_gb: int | None = None
    sms_credits: int | None = None


class EntitlementUsage(BaseModel):
    students: int = 0
    staff: int = 0
    storage_bytes: int = 0
    sms_sent: int = 0
    period_month: date | None = None


class EntitlementsResponse(BaseModel):
    institution_id: uuid.UUID
    plan: str | None = Field(default=None, description="plan code")
    plan_name: str | None = None
    tier: str | None = None
    status: str = Field(description="trial | active | grace | expired | cancelled | none")
    starts_on: date | None = None
    ends_on: date | None = None
    grace_until: date | None = None
    limits: EntitlementLimits
    usage: EntitlementUsage
    writable: bool = Field(default=True, description="false once expired / cancelled")
    locked_settings: dict[str, Any] = Field(default_factory=dict, description="plan-locked settings (Phase 38)")


class InstallRequest(BaseModel):
    install_key: str = Field(min_length=1, max_length=200)
    super_admin_email: EmailStr
    super_admin_password: str = Field(min_length=1, max_length=200)
    super_admin_username: str = Field(default="superadmin", min_length=3, max_length=80)


class InstallResponse(BaseModel):
    installed_at: datetime
    permissions: int
    role_templates: int
    features: int
    plans: int
    super_admin_id: uuid.UUID


# ======================================================================================================================
# Phase 38 — super admin & SaaS operations (Prompts/38 §38.4)
# ======================================================================================================================

PlanTier = Literal["starter", "standard", "professional", "university"]
TemplateName = Literal["university", "autonomous", "affiliated", "standalone"]


class JobAccepted(BaseModel):
    job_id: uuid.UUID | None = None
    job_type: str
    status: str = "queued"
    detail: dict[str, Any] = Field(default_factory=dict)


# ---- institutions ----------------------------------------------------------------------------------------------------
class InstitutionAdminOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    type: str
    status: str
    plan: str | None = None
    tier: str | None = None
    subscription_status: str | None = None
    ends_on: date | None = None
    students_active: int = 0
    staff_active: int = 0
    storage_gb: float = 0
    health: str = "ok"  # ok | degraded | failing | none
    last_login_at: datetime | None = None
    created_at: datetime
    is_demo: bool = False


class InstitutionDetailOut(InstitutionAdminOut):
    profile: dict[str, Any] = Field(default_factory=dict)
    subscription: dict[str, Any] | None = None
    invoices: list[dict[str, Any]] = Field(default_factory=list)
    usage: list[dict[str, Any]] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    connections: list[dict[str, Any]] = Field(default_factory=list)
    open_tickets: list[dict[str, Any]] = Field(default_factory=list)
    impersonations: list[dict[str, Any]] = Field(default_factory=list)
    chain: dict[str, Any] = Field(default_factory=dict)
    last_logins: list[dict[str, Any]] = Field(default_factory=list)
    status_log: list[dict[str, Any]] = Field(default_factory=list)
    caps: dict[str, Any] = Field(default_factory=dict)
    exports: list[dict[str, Any]] = Field(default_factory=list)
    erase_request: dict[str, Any] | None = None


class WizardAdmin(BaseModel):
    username: str = Field(default="admin", min_length=3, max_length=80)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    display_name: str = Field(min_length=2, max_length=200)


class WizardInstitution(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    short_name: str | None = Field(default=None, max_length=60)
    slug: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$")
    code: str | None = Field(default=None, max_length=20)
    parent_university_name: str | None = Field(default=None, max_length=200)
    timezone: str = "Asia/Kolkata"
    locale: str = "en-IN"
    currency: str = "INR"
    gstin: str | None = Field(default=None, max_length=20)
    contact: dict[str, Any] | None = None
    address: dict[str, Any] | None = None


class OnboardingWizardRequest(BaseModel):
    """Phase 03 ``OnboardingRequest`` extended with the template, trial, demo data and custom domain (§38.4)."""

    template: TemplateName = "standalone"
    institution: WizardInstitution
    admin: WizardAdmin
    plan_code: str = Field(default="standard", max_length=30)
    pack: str = Field(default="IN", max_length=10)
    trial: bool = True
    billing_cycle: Literal["monthly", "yearly"] = "yearly"
    seed_demo: bool = False
    custom_domain: str | None = Field(default=None, max_length=255)
    activate: bool = True


class FeaturePreviewOut(BaseModel):
    plan: str
    template: str
    enabled: list[str]
    forced_on: list[str]
    forced_off: list[str]
    not_in_plan: list[str]


class InstitutionStatusChange(BaseModel):
    action: Literal["activate", "suspend", "archive", "unarchive"]
    reason: str = Field(min_length=3, max_length=500)


class TenantExportRequest(BaseModel):
    include: list[Literal["db", "files"]] = Field(default=["db", "files"])
    format: Literal["json", "csv"] = "json"
    encrypt_to_email: EmailStr | None = None


class TenantExportOut(BaseModel):
    export_id: str
    manifest: dict[str, Any]
    url: str | None = None
    expires_at: datetime | None = None


class TenantResetRequest(BaseModel):
    confirm_slug: str = Field(min_length=1, max_length=60)


class TenantErasureRequest(BaseModel):
    confirm_slug: str = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=3, max_length=500)


# ---- plans / subscriptions / invoices -------------------------------------------------------------------------------
class PlanIn(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=80)
    tier: PlanTier
    price_paise_monthly: int | None = Field(default=None, ge=0)
    price_paise_yearly: int | None = Field(default=None, ge=0)
    student_limit: int | None = Field(default=None, ge=0)
    staff_limit: int | None = Field(default=None, ge=0)
    storage_gb: int | None = Field(default=None, ge=0)
    sms_credits: int | None = Field(default=None, ge=0)
    enabled_features: list[str] = Field(default_factory=list)
    locked_settings: dict[str, Any] = Field(
        default_factory=dict, description="plan-locked settings, e.g. reports.max_rows"
    )
    is_active: bool = True
    allow_above_tier: bool = False


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    price_paise_monthly: int | None = Field(default=None, ge=0)
    price_paise_yearly: int | None = Field(default=None, ge=0)
    student_limit: int | None = Field(default=None, ge=0)
    staff_limit: int | None = Field(default=None, ge=0)
    storage_gb: int | None = Field(default=None, ge=0)
    sms_credits: int | None = Field(default=None, ge=0)
    enabled_features: list[str] | None = None
    locked_settings: dict[str, Any] | None = None
    allow_above_tier: bool = False


class PlanOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    tier: str
    prices: dict[str, int | None]
    limits: dict[str, int | None]
    enabled_features: list[str]
    locked_settings: dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    subscribers: int = 0


class ChangePreviewOut(BaseModel):
    institution_id: uuid.UUID
    from_plan: str | None
    to_plan: str
    features_disabled: list[dict[str, Any]]
    features_enabled: list[str]
    overrides_kept: list[str]
    limit_violations: list[dict[str, Any]]
    proration: dict[str, Any]
    allowed: bool


class SubscriptionAssign(BaseModel):
    plan_id: uuid.UUID
    starts_on: date | None = None
    billing_cycle: Literal["monthly", "yearly"] = "yearly"
    trial_days: int | None = Field(default=None, ge=0, le=365)
    amount_paise: int | None = Field(default=None, ge=0)
    payment_ref: str | None = Field(default=None, max_length=80)


class SubscriptionChange(BaseModel):
    plan_id: uuid.UUID
    effective: Literal["now", "next_cycle"] = "now"


class SubscriptionRenew(BaseModel):
    billing_cycle: Literal["monthly", "yearly"] | None = None
    payment_ref: str | None = Field(default=None, max_length=80)


class SubscriptionCancel(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    at_period_end: bool = True


class InvoiceOut(BaseModel):
    number: str
    institution_id: uuid.UUID
    institution_name: str | None = None
    period: str
    kind: str = "subscription"  # subscription | proration | overage | registration
    plan: str | None = None
    lines: list[dict[str, Any]] = Field(default_factory=list)
    amount_paise: int
    gst_paise: int
    total_paise: int
    status: str
    issued_on: date
    due_on: date
    paid_on: date | None = None
    payment_ref: str | None = None
    pdf_url: str | None = None
    dunning: list[dict[str, Any]] = Field(default_factory=list)


class SubscriptionOut(BaseModel):
    id: uuid.UUID | None = None
    institution_id: uuid.UUID
    plan: PlanOut | None = None
    status: str
    billing_cycle: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    grace_until: date | None = None
    amount_paise: int | None = None
    payment_ref: str | None = None
    scheduled_change: dict[str, Any] | None = None
    cancel_at_period_end: bool = False
    invoices: list[InvoiceOut] = Field(default_factory=list)
    usage_vs_limits: dict[str, Any] = Field(default_factory=dict)
    locked_settings: dict[str, Any] = Field(default_factory=dict)


class GeneratePeriodRequest(BaseModel):
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM; default current month")


class ManualPayment(BaseModel):
    payment_ref: str = Field(min_length=3, max_length=80)
    paid_on: date | None = None


class InvoicePayRequest(BaseModel):
    mode: Literal["gateway", "manual"] = "gateway"
    manual: ManualPayment | None = None


class InvoicePayOut(BaseModel):
    number: str
    status: str
    order: dict[str, Any] | None = None


class GatewayWebhook(BaseModel):
    order_id: str = Field(max_length=80)
    invoice_number: str | None = Field(default=None, max_length=40)
    registration_id: uuid.UUID | None = None
    payment_ref: str = Field(max_length=80)
    status: Literal["paid", "failed"] = "paid"
    signature: str | None = Field(
        default=None, max_length=200, description="prefer the X-Signature header (HMAC of the raw body)"
    )


# ---- usage ----------------------------------------------------------------------------------------------------------
class UsageMonth(BaseModel):
    institution_id: uuid.UUID
    institution_name: str | None = None
    period_month: date
    active_students: int = 0
    active_staff: int = 0
    storage_bytes: int = 0
    sms_sent: int = 0
    whatsapp_sent: int = 0
    emails_sent: int = 0
    api_calls: int = 0
    ai_tokens: int = 0
    cost_paise: int = 0
    caps: dict[str, Any] = Field(default_factory=dict)
    overage: list[dict[str, Any]] = Field(default_factory=list)


class UsageOut(BaseModel):
    months: list[UsageMonth]
    totals: dict[str, int] = Field(default_factory=dict)


class UsageCapsIn(BaseModel):
    caps: dict[str, int | None]


# ---- impersonation --------------------------------------------------------------------------------------------------
class ImpersonationOut(BaseModel):
    id: uuid.UUID
    impersonator: dict[str, Any]
    target: dict[str, Any]
    institution: dict[str, Any] | None = None
    reason: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    active: bool
    read_only: bool = False
    writes_count: int = 0
    ended_by: str | None = None


class ImpersonationForceStop(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# ---- support --------------------------------------------------------------------------------------------------------
class TicketCreate(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=10_000)
    priority: Literal["urgent", "high", "normal", "low"] = "normal"
    module: str | None = Field(default=None, max_length=60)
    category: str = Field(default="other", max_length=30)
    attachments: list[str] = Field(default_factory=list, max_length=10)
    institution_id: uuid.UUID | None = Field(default=None, description="platform side: raise on behalf of a tenant")


class TicketMessage(BaseModel):
    id: str
    by: dict[str, Any]
    at: datetime
    text: str
    attachments: list[str] = Field(default_factory=list)
    internal: bool = False
    side: str = "tenant"  # tenant | platform | system


class TicketOut(BaseModel):
    id: uuid.UUID
    ticket_number: str
    institution: dict[str, Any] | None = None
    subject: str
    description: str | None = None
    priority: str
    module: str | None = None
    category: str | None = None
    status: str
    raised_by: dict[str, Any] | None = None
    assigned_to: dict[str, Any] | None = None
    messages: list[TicketMessage] = Field(default_factory=list)
    sla_due_at: datetime | None = None
    breached: bool = False
    csat: int | None = None
    related_feedback: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None
    can_reopen: bool = False


class TicketReply(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    attachments: list[str] = Field(default_factory=list, max_length=10)
    internal: bool = False


class TicketAssign(BaseModel):
    user_id: uuid.UUID


class TicketStatusChange(BaseModel):
    status: Literal["open", "in_progress", "waiting", "resolved", "closed"]
    resolution: str | None = Field(default=None, max_length=2000)


class TicketRate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class DiagnosticsOut(BaseModel):
    ticket_number: str
    institution: dict[str, Any] | None = None
    versions: dict[str, Any]
    flags_diff: dict[str, Any]
    failing_connections: list[dict[str, Any]]
    last_errors: list[dict[str, Any]]
    subscription: dict[str, Any] | None = None
    sentry_url: str | None = None
    generated_at: datetime


# ---- help / feedback ------------------------------------------------------------------------------------------------
class HelpAudience(BaseModel):
    roles: list[str] = Field(default_factory=list)
    portals: list[str] = Field(default_factory=list)
    public: bool = False


class HelpArticleIn(BaseModel):
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9:/_.-]+$")
    title: str = Field(min_length=2, max_length=200)
    body: str = Field(min_length=1, max_length=100_000)
    module: str | None = Field(default=None, max_length=60)
    audience: HelpAudience = Field(default_factory=HelpAudience)
    is_published: bool = True


class HelpArticleAdminOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    body: str
    module: str | None = None
    audience: dict[str, Any] | None = None
    is_published: bool
    is_platform: bool
    institution_id: uuid.UUID | None = None
    helpful: dict[str, int] = Field(default_factory=dict)
    updated_at: datetime


class HelpImport(BaseModel):
    articles: list[HelpArticleIn] = Field(max_length=1000)


class FeedbackAdminOut(BaseModel):
    id: uuid.UUID
    institution: dict[str, Any] | None = None
    user: dict[str, Any] | None = None
    page: str | None = None
    category: str | None = None
    rating: int | None = None
    message: str | None = None
    screenshot_url: str | None = None
    client: str | None = None
    status: str
    note: str | None = None
    responded: bool = False
    ticket_number: str | None = None
    created_at: datetime


class FeedbackTriage(BaseModel):
    status: Literal["new", "triaged", "planned", "done", "declined"]
    note: str | None = Field(default=None, max_length=2000)
    respond_text: str | None = Field(default=None, max_length=4000)


# ---- announcements --------------------------------------------------------------------------------------------------
class AnnouncementAudience(BaseModel):
    type: Literal["all", "plan", "institution_type", "institution_ids", "roles"] = "all"
    values: list[str] = Field(default_factory=list)


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)
    audience: AnnouncementAudience = Field(default_factory=AnnouncementAudience)
    channels: list[Literal["banner", "inapp", "email"]] = Field(default=["banner", "inapp"])
    kind: Literal["info", "release", "maintenance", "incident"] = "info"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool = True


class AnnouncementOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    audience: dict[str, Any]
    channels: list[str]
    kind: str = "info"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    is_active: bool
    live: bool = False
    delivered: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# ---- health ---------------------------------------------------------------------------------------------------------
class HealthRow(BaseModel):
    connection_id: uuid.UUID
    institution: dict[str, Any]
    capability: str
    provider: str
    label: str | None = None
    status: str
    last_health_at: datetime | None = None
    last_error: str | None = None
    failing_since: datetime | None = None
    latency_ms: int | None = None


class HealthRetryRequest(BaseModel):
    connection_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class ConnectionDisable(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OutageOut(BaseModel):
    capability: str
    provider: str
    failing: int
    total: int
    share: float
    institutions: list[dict[str, Any]]
    since: datetime | None = None
    active: bool = True


# ---- read-only windows ----------------------------------------------------------------------------------------------
class ReadOnlyScheduleIn(BaseModel):
    institution_id: uuid.UUID | None = Field(default=None, description="platform window when omitted (super admin)")
    scope: Literal["platform", "institution"] = "institution"
    reason: str = Field(min_length=3, max_length=200)
    starts_at: datetime
    ends_at: datetime
    notice_hours: int = Field(default=24, ge=0, le=720)


class ReadOnlyWindowOut(BaseModel):
    id: uuid.UUID
    institution: dict[str, Any] | None = None
    scope: str
    reason: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    is_active: bool
    state: str  # upcoming | active | ended | cancelled
    set_by: uuid.UUID | None = None


# ---- platform settings ----------------------------------------------------------------------------------------------
class PlatformSettingOut(BaseModel):
    key: str
    group: str
    label: str
    type: str
    value: Any = None
    default: Any = None
    secret_keys: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    updated_by: uuid.UUID | None = None


class PlatformSettingsIn(BaseModel):
    values: dict[str, Any]
    reason: str | None = Field(default=None, max_length=500)


# ---- registrations / demo requests ----------------------------------------------------------------------------------
class PublicRegistrationAdmin(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)


class PublicRegistrationIn(BaseModel):
    institution_name: str = Field(min_length=3, max_length=200)
    institution_type: Literal[
        "university",
        "deemed_university",
        "autonomous_college",
        "affiliated_college",
        "standalone_college",
        "multi_campus",
    ]
    slug: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$")
    admin: PublicRegistrationAdmin
    plan_code: str = Field(default="standard", max_length=30)
    trial: bool = True
    captcha_token: str | None = Field(default=None, max_length=4000)


class PublicRegistrationOut(BaseModel):
    id: uuid.UUID
    status: str
    next: str  # verify_email | pay | provisioning | done | expired | failed
    login_url: str | None = None


class RegistrationOut(BaseModel):
    id: uuid.UUID
    institution_name: str
    institution_type: str
    slug: str
    admin_name: str | None = None
    admin_email: str
    admin_phone: str | None = None
    plan: str | None = None
    trial: bool = True
    status: str
    payment_ref: str | None = None
    institution_id: uuid.UUID | None = None
    error: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RegistrationAction(BaseModel):
    action: Literal["verify", "provision", "expire", "retry"]
    note: str | None = Field(default=None, max_length=500)


class DemoRequestIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    institution_name: str | None = Field(default=None, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    institution_type: str | None = Field(default=None, max_length=30)
    message: str | None = Field(default=None, max_length=4000)
    captcha_token: str | None = Field(default=None, max_length=4000)


class DemoRequestOut(BaseModel):
    id: uuid.UUID
    name: str
    institution_name: str | None = None
    email: str | None = None
    phone: str | None = None
    institution_type: str | None = None
    message: str | None = None
    status: str
    notes: list[dict[str, Any]] = Field(default_factory=list)
    owner: str | None = None
    created_at: datetime


class DemoRequestUpdate(BaseModel):
    status: Literal["new", "contacted", "converted", "dropped"]
    notes: str | None = Field(default=None, max_length=4000)


# ---- dashboard / audit ----------------------------------------------------------------------------------------------
class PlatformDashboardOut(BaseModel):
    tenants: dict[str, dict[str, int]]
    tenants_total: int
    mrr_paise: int
    arr_paise: int
    trials_ending: list[dict[str, Any]]
    invoices_overdue: dict[str, Any]
    usage_top: list[dict[str, Any]]
    health_failing: list[dict[str, Any]]
    outages: list[dict[str, Any]]
    tickets_open_by_priority: dict[str, int]
    sla_breaches: int
    chain_breaks: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    jobs_dead_letters: dict[str, Any]
    read_only_active: list[dict[str, Any]]
    recent_actions: list[dict[str, Any]]
    charts: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime
    cached: bool = False


class PlatformAuditRow(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    institution: dict[str, Any] | None = None
    actor: dict[str, Any] | None = None
    impersonator: dict[str, Any] | None = None
    module: str
    action: str
    record_type: str | None = None
    record_id: uuid.UUID | None = None
    summary: str
    new_values: dict[str, Any] | None = None


class BannerState(BaseModel):
    """Banners for every shell (``/auth/me``): subscription state, provider outage, API cap, active impersonation."""

    subscription: dict[str, Any] | None = None
    outage: list[dict[str, Any]] = Field(default_factory=list)
    api_cap: dict[str, Any] | None = None
    impersonation_active: bool = False
    announcements: int = 0
