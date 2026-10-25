"""Feature keys registered by Phase 21 (docs/Feature_Flags.md transport group)."""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("campus", "transport.core", "Transport", "vehicles, routes, allocations", False, "standard", ()),
    ("campus", "transport.gps_live", "Live GPS", "devices, trips, live map", False, "standard", ("transport.core",)),
    ("campus", "transport.staff", "Staff transport", "staff allocations", False, "standard", ("transport.core",)),
    ("campus", "transport.fees", "Transport fees", "route fees", False, "standard", ("fees.core",)),
)

for _group, _key, _name, _desc, _on, _tier, _deps in _KEYS:
    register_feature(
        key=_key,
        group=_group,
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
