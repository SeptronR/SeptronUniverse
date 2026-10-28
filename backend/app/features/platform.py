"""Feature keys registered by Phase 01 (docs/Feature_Flags.md §2.15 — platform & search).

The ``core.*`` keys of this phase (``core.auth``, ``core.rbac``, ``core.institution``, ``core.settings``,
``core.audit_logs``, ``core.dashboard``, ``core.notifications_inapp``, ``core.background_jobs``) are registered in
``app/core/features.py`` because they are non-toggleable; these five are ordinary toggles (default on, starter tier).
"""

from app.core.features import register_feature

register_feature(
    key="platform.read_only_mode",
    group="platform",
    name="Read-only mode",
    description="maintenance toggle (platform or tenant read-only windows)",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="search.global",
    group="search",
    name="Global search",
    description="tsvector search over students, staff, courses and applicants (Ctrl+K)",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="platform.help_center",
    group="platform",
    name="Help centre",
    description="in-app help articles",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="platform.in_app_feedback",
    group="platform",
    name="In-app feedback",
    description="feedback widget",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="platform.guided_tours",
    group="platform",
    name="Guided tours",
    description="onboarding tours",
    default_enabled=True,
    min_plan_tier="starter",
)
# Phase 38: tenant data export (the institution admin's ``POST /billing/export``; user exports are Phase 43 DSR)
register_feature(
    key="data.export_portability",
    group="data",
    name="Data export",
    description="tenant/user exports",
    default_enabled=True,
    min_plan_tier="standard",
    depends_on=("core.background_jobs",),
)
