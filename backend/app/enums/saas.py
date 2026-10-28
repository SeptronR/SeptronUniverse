"""Super admin & SaaS operations — Prompts/38 §38.2 / §38.3 (statuses, platform defaults, onboarding templates).

``PLATFORM_DEFAULTS`` is what revision ``0038`` writes into ``platform_settings`` (one row per dotted key);
``PLATFORM_KEYS`` is the typed catalogue the platform settings page renders (``scope=platform`` like the Phase 37
settings catalogue; ``secret`` keys are never returned — ``***``). ``PLAN_DEFAULTS`` fills the prices / limits of the
four §36.3 plans (``enabled_features`` come from the feature registry tiers, ``install_service.plan_enabled_features``).
"""

from enum import StrEnum
from typing import Any


class SubscriptionStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    GRACE = "grace"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class BillingCycle(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class InvoiceStatus(StrEnum):
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    RESOLVED = "resolved"
    CLOSED = "closed"


class TicketPriority(StrEnum):
    URGENT = "urgent"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class RegistrationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    PAID = "paid"
    PROVISIONED = "provisioned"
    FAILED = "failed"
    EXPIRED = "expired"


class DemoRequestStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    CONVERTED = "converted"
    DROPPED = "dropped"


class FeedbackStatus(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    PLANNED = "planned"
    DONE = "done"
    DECLINED = "declined"


class AnnouncementAudienceType(StrEnum):
    ALL = "all"
    PLAN = "plan"
    INSTITUTION_TYPE = "institution_type"
    INSTITUTION_IDS = "institution_ids"
    ROLES = "roles"


class OnboardingTemplate(StrEnum):
    UNIVERSITY = "university"
    AUTONOMOUS = "autonomous"
    AFFILIATED = "affiliated"
    STANDALONE = "standalone"


# ---- side stores ------------------------------------------------------------------------------------------------------
# institution_settings category holding tenant-readable SaaS facts: ``invoice:<number>`` (invoice ledger),
# ``caps`` (usage caps), ``usage:<yyyy-mm>`` (ai tokens, cost, overage flags), ``export:<id>`` (tenant export manifests),
# ``erase_request`` (four-eyes approval), ``status_log`` (lifecycle history)
SAAS_META = "saas_meta"
# platform_settings key prefixes (no tenant column — platform session only): registration extras, demo-request notes,
# feedback triage notes, platform alerts, invoice number sequences
REG_PREFIX = "reg:"
DEMO_PREFIX = "demo_req:"
FEEDBACK_PREFIX = "feedback:"
ALERT_PREFIX = "alert:"
SEQ_PREFIX = "seq:"

TIER_ORDER = ("starter", "standard", "professional", "university")
TICKET_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("in_progress", "waiting", "resolved", "closed"),
    "in_progress": ("waiting", "resolved", "closed"),
    "waiting": ("in_progress", "resolved", "closed"),
    "resolved": ("closed", "in_progress"),
    "closed": ("in_progress",),
}
TICKET_REOPEN_DAYS = 14
TICKET_AUTO_CLOSE_DAYS = 5
IMPERSONATION_MAX_MINUTES = 60
EXPORT_TTL_DAYS = 7
FEEDBACK_SCREENSHOT_DAYS = 90
OUTAGE_FAILING_SHARE = 0.5
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "app",
        "www",
        "mail",
        "platform",
        "super-admin",
        "superadmin",
        "support",
        "help",
        "status",
        "billing",
        "public",
        "static",
        "assets",
        "demo",
        "login",
        "signup",
        "register",
        "septron",
        "universe",
    }
)
USAGE_METRICS = (
    "active_students",
    "active_staff",
    "storage_bytes",
    "sms_sent",
    "whatsapp_sent",
    "emails_sent",
    "api_calls",
)
CAP_KEYS = (
    "api_calls_per_day",
    "sms_per_month",
    "whatsapp_per_month",
    "emails_per_month",
    "ai_tokens_per_month",
    "storage_gb",
)

# code → (monthly paise, yearly paise); limits stay the §36.3 values (student / staff / storage / sms credits)
PLAN_DEFAULTS: dict[str, dict[str, Any]] = {
    "starter": {"price_paise_monthly": 1_500_000, "price_paise_yearly": 15_000_000, "reports.max_rows": 50_000},
    "standard": {"price_paise_monthly": 5_000_000, "price_paise_yearly": 50_000_000, "reports.max_rows": 200_000},
    "professional": {"price_paise_monthly": 15_000_000, "price_paise_yearly": 150_000_000, "reports.max_rows": 500_000},
    "university": {"price_paise_monthly": 40_000_000, "price_paise_yearly": 400_000_000, "reports.max_rows": 1_000_000},
}

PLATFORM_DEFAULTS: dict[str, Any] = {
    "billing": {
        "gstin": "29AAACS0000A1Z5",
        "legal_name": "Septron Technologies Pvt Ltd",
        "address": "Bengaluru, Karnataka, India",
        "invoice_prefix": "INV",
        "gst_pct": 18,
        "currency": "INR",
        "due_days": 15,
        "grace_days": 15,
        "trial_days": 30,
        "proration": True,
    },
    "usage.rates": {
        "sms_paise": 25,
        "whatsapp_paise": 60,
        "email_paise": 2,
        "ai_token_paise_per_1k": 40,
        "storage_gb_paise": 500,
    },
    "usage.caps_default": {"api_calls_per_day": 200_000},
    "usage.overage_alert_pct": 80,
    "support.sla_hours": {"urgent": 4, "high": 12, "normal": 48, "low": 120},
    "support.categories": ["login", "billing", "data", "integration", "exams", "mobile", "other"],
    "support.oncall": [],
    "demo.reset_cron": "0 2 * * *",
    "demo.institution_slugs": ["demo-uni", "demo-college"],
    "registration.expiry_hours": 72,
    "announcements.default_channels": ["banner", "inapp"],
    "mobile.min_versions": {"android": "1.0.0", "ios": "1.0.0", "force_update": False},
    "platform.status_page_url": "https://status.universe.septronr.com",
    "captcha": {"provider": "none", "site_key": "", "secret": ""},
    "sales.email": "sales@septronr.com",
    "saas.notify_impersonation": True,
    "danger.allow_prod_reset": False,
    "danger.four_eyes": True,
}

# typed platform catalogue (Phase 37 ``scope=platform``): key → (type, group, label, secret sub-keys)
PLATFORM_KEYS: dict[str, dict[str, Any]] = {
    "billing": {
        "type": "json",
        "group": "billing",
        "label": "Billing profile (GSTIN, prefix, GST %, due / grace / trial days, proration)",
    },
    "usage.rates": {"type": "json", "group": "usage", "label": "Usage rates (paise)"},
    "usage.caps_default": {"type": "json", "group": "usage", "label": "Default per-tenant caps"},
    "usage.overage_alert_pct": {
        "type": "int",
        "group": "usage",
        "label": "Overage alert threshold (%)",
        "min": 1,
        "max": 100,
    },
    "support.sla_hours": {"type": "json", "group": "support", "label": "SLA hours per priority"},
    "support.categories": {"type": "list", "group": "support", "label": "Ticket categories"},
    "support.oncall": {"type": "list", "group": "support", "label": "On-call support users (ids, round-robin)"},
    "demo.reset_cron": {"type": "string", "group": "demo", "label": "Demo reset schedule (cron, UTC)"},
    "demo.institution_slugs": {"type": "list", "group": "demo", "label": "Demo tenants reset nightly"},
    "registration.expiry_hours": {
        "type": "int",
        "group": "registration",
        "label": "Unverified registrations expire after (h)",
        "min": 1,
        "max": 720,
    },
    "announcements.default_channels": {
        "type": "list",
        "group": "announcements",
        "label": "Default announcement channels",
    },
    "mobile.min_versions": {"type": "json", "group": "mobile", "label": "Minimum app versions / force update"},
    "platform.status_page_url": {"type": "string", "group": "platform", "label": "Status page URL"},
    "captcha": {"type": "json", "group": "security", "label": "Captcha provider", "secret": ["secret"]},
    "sales.email": {"type": "string", "group": "sales", "label": "Sales inbox (demo requests)"},
    "saas.notify_impersonation": {
        "type": "bool",
        "group": "support",
        "label": "Notify tenant admins when impersonation starts",
    },
    "danger.allow_prod_reset": {"type": "bool", "group": "danger", "label": "Allow reset of non-demo tenants"},
    "danger.four_eyes": {"type": "bool", "group": "danger", "label": "Erasure needs a second super admin"},
}
SECRET_MASK = "***"

# onboarding templates (§38.6 institution_admin_service rule 2): institution type, features forced on / off on top of
# the plan defaults (as plan-sourced flags, so later plan changes re-evaluate them), main college
TEMPLATES: dict[str, dict[str, Any]] = {
    "university": {
        "institution_type": "university",
        "main_college": False,
        "on": ["institution.multi_college", "affiliation.core"],
        "off": [],
        "exam_authority": "university",
    },
    "autonomous": {
        "institution_type": "autonomous_college",
        "main_college": True,
        "on": [],
        "off": [
            "institution.multi_college",
            "affiliation.core",
            "affiliation.inspections",
            "affiliation.data_submissions",
        ],
        "exam_authority": "autonomous",
    },
    "affiliated": {
        "institution_type": "affiliated_college",
        "main_college": True,
        "on": [],
        "off": [
            "institution.multi_college",
            "affiliation.core",
            "affiliation.inspections",
            "affiliation.data_submissions",
        ],
        "exam_authority": "university",
    },
    "standalone": {
        "institution_type": "standalone_college",
        "main_college": True,
        "on": [],
        "off": [
            "institution.multi_college",
            "affiliation.core",
            "affiliation.inspections",
            "affiliation.data_submissions",
        ],
        "exam_authority": "autonomous",
    },
}
TYPE_TEMPLATE: dict[str, str] = {
    "university": "university",
    "deemed_university": "university",
    "multi_campus": "university",
    "autonomous_college": "autonomous",
    "affiliated_college": "affiliated",
    "standalone_college": "standalone",
}
# tables never dumped / dropped by tenant export / reset / erasure (append-only evidence or platform rows)
TENANT_KEEP_TABLES = frozenset({"audit_logs", "domain_events", "event_consumptions", "background_jobs"})
