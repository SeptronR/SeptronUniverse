"""Feature keys registered by Phase 36 (docs/Feature_Flags.md reports group). ``reports.core`` gates the registry,
catalogue, runs, registers and the ad-hoc builder; ``reports.scheduled`` the schedules / deliveries; ``reports.statutory``
the statutory renderers, review and sign-off (Phase 32 submission files are rendered through them when it is on).
"""

from app.core.features import FEATURE_REGISTRY, register_feature

_KEYS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("reports.core", "Reports", "report registry", True, "starter", ()),
    ("reports.scheduled", "Scheduled reports", "schedules", True, "standard", ("reports.core",)),
    ("reports.statutory", "Statutory reports", "AISHE/NIRF/AICTE/UGC/NSP", False, "professional", ("reports.core",)),
)

for _key, _name, _desc, _default, _tier, _deps in _KEYS:
    if _key in FEATURE_REGISTRY:
        continue
    register_feature(
        key=_key,
        group="reports",
        name=_name,
        description=_desc,
        default_enabled=_default,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
