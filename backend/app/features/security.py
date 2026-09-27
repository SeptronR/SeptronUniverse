"""Feature keys registered by Phase 02 (docs/Feature_Flags.md §2.1 — security & privacy).

``core.auth`` / ``core.rbac`` (non-toggleable) live in ``app/core/features.py``; these six are ordinary toggles.
"""

from app.core.features import register_feature

register_feature(
    key="security.mfa",
    group="core",
    name="Multi-factor auth",
    description="TOTP for privileged roles",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="security.sso",
    group="core",
    name="Single sign-on",
    description="OIDC/SAML login",
    default_enabled=False,
    min_plan_tier="professional",
    depends_on=("integrations.sso",),
)
register_feature(
    key="security.ip_allowlist_exam_ops",
    group="core",
    name="IP allow-list for exam ops",
    description="restrict decode/publish to IPs",
    default_enabled=False,
    min_plan_tier="professional",
)
register_feature(
    key="security.session_management",
    group="core",
    name="Session management",
    description="active sessions, revoke, login history",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="privacy.dpdp_consent",
    group="core",
    name="DPDP consent",
    description="consent records & banners",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="privacy.data_subject_requests",
    group="core",
    name="Data-subject requests",
    description="export/erasure requests",
    default_enabled=True,
    min_plan_tier="standard",
    depends_on=("privacy.dpdp_consent",),
)
