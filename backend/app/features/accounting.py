"""Feature keys registered by Phase 23 (docs/Feature_Flags.md accounting group)."""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("finance", "accounting.core", "Accounting", "income/expense, ledgers", False, "standard", ()),
    ("finance", "accounting.budgets", "Budgets", "department budgets", False, "standard", ("accounting.core",)),
    (
        "finance",
        "accounting.grants_ledger",
        "Grants ledger",
        "project ledgers",
        False,
        "professional",
        ("accounting.core",),
    ),
    ("finance", "accounting.gst_reports", "GST reports", "GST returns data", False, "standard", ("accounting.core",)),
    (
        "finance",
        "accounting.tally_export",
        "Tally / Zoho export",
        "vouchers export",
        False,
        "standard",
        ("accounting.core",),
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
