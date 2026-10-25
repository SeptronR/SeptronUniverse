"""Feature keys registered by Phase 22 (docs/Feature_Flags.md inventory group)."""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("campus", "inventory.core", "Inventory", "stores, items, issues", False, "standard", ()),
    (
        "campus",
        "inventory.procurement",
        "Procurement",
        "indents, quotations, POs, GRN",
        False,
        "standard",
        ("workflow.engine",),
    ),
    (
        "campus",
        "inventory.vendor_portal",
        "Vendor portal",
        "supplier registration/quotes",
        False,
        "professional",
        ("inventory.procurement",),
    ),
    (
        "campus",
        "inventory.lab_consumables",
        "Lab consumables",
        "chemicals, safety data",
        False,
        "standard",
        ("inventory.core",),
    ),
    ("campus", "inventory.assets", "Assets", "asset register, depreciation", False, "standard", ("inventory.core",)),
    ("campus", "inventory.asset_qr", "Asset QR tags", "QR labels & audits", False, "standard", ("inventory.assets",)),
    ("campus", "inventory.bills", "Vendor bills", "bill tracking", False, "standard", ("inventory.procurement",)),
    (
        "campus",
        "inventory.vendor_store",
        "Vendor store",
        "campus store (Orbit vendor inventory)",
        False,
        "standard",
        ("inventory.core",),
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
