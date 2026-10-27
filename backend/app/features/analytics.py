"""Feature keys registered by Phase 35 (docs/Feature_Flags.md analytics group). ``core.dashboard`` (role dashboards) is a
core key registered in Phase 01; ``analytics.core`` gates the chart registry, Insights tabs, drill-down, read models and
digests; ``analytics.early_warning`` gates the cohort analytics / interventions / alerts on top of the Phase 27 risk flags
(Phase 27's ``mentoring.early_warning`` depends on it — the scoring job stays in Phase 27).
"""

from app.core.features import FEATURE_REGISTRY, register_feature

_KEYS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("analytics.core", "Analytics", "chart registry, insights tabs", True, "standard", ()),
    (
        "analytics.early_warning",
        "Early-warning analytics",
        "risk scoring job",
        False,
        "professional",
        ("analytics.core",),
    ),
)

for _key, _name, _desc, _default, _tier, _deps in _KEYS:
    if _key in FEATURE_REGISTRY:
        continue
    register_feature(
        key=_key,
        group="analytics",
        name=_name,
        description=_desc,
        default_enabled=_default,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
