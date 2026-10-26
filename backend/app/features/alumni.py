"""Feature keys registered by Phase 29 (docs/Feature_Flags.md §2 alumni): alumni core / portal / jobs board,
fundraising and 80G donations, plus the ``portals.alumni`` shell key (Phase 39 builds the shell on these endpoints).
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("alumni", "alumni.core", "Alumni", "profiles, directory", True, "standard", ()),
    ("alumni", "alumni.portal", "Alumni portal", "self-service", True, "standard", ("alumni.core",)),
    ("alumni", "alumni.jobs_board", "Alumni jobs board", "job posts", False, "standard", ("alumni.portal",)),
    ("alumni", "alumni.fundraising", "Fundraising", "campaigns", False, "professional", ("alumni.core",)),
    (
        "alumni",
        "alumni.donations_80g",
        "Donations & 80G",
        "receipts",
        False,
        "professional",
        ("alumni.fundraising",),
    ),
    ("platform", "portals.alumni", "Alumni portal", "alumni portal", True, "standard", ("alumni.core",)),
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
