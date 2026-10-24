"""Feature keys registered by Phase 19 (docs/Feature_Flags.md library group).

``integrations.koha_dspace_shodhganga`` belongs to Phase 41 — the dependency is listed as documented.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("library", "library.core", "Library", "catalogue, members, circulation", True, "starter", ()),
    ("library", "library.opac", "OPAC", "public catalogue search", True, "starter", ("library.core",)),
    ("library", "library.fines", "Library fines", "fine rules & invoices", True, "starter", ("fees.core",)),
    (
        "library",
        "library.eresources",
        "E-resources",
        "subscriptions, remote access, usage",
        True,
        "standard",
        ("library.core",),
    ),
    ("library", "library.rfid_barcode", "RFID / barcode", "scan circulation", True, "standard", ("library.core",)),
    (
        "library",
        "library.inter_library_loan",
        "Inter-library loan",
        "ILL requests",
        False,
        "professional",
        ("library.core",),
    ),
    (
        "library",
        "library.koha_sync",
        "Koha / DSpace sync",
        "catalogue & ETD sync",
        False,
        "professional",
        ("integrations.koha_dspace_shodhganga",),
    ),
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
