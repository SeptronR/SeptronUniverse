"""Feature keys registered by Phase 12 (docs/Feature_Flags.md fees group + ``integrations.payments``).

Dependencies on keys of later phases (``accounting.gst_reports`` / ``accounting.tally_export`` — Phase 23,
``integrations.nsp`` — Phase 41) are listed as documented; the registry tolerates not-yet-registered dependencies.
"""

from app.core.features import register_feature

_FEES: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("fees.core", "Fee management", "heads, structures, invoices, payments", True, "starter", ()),
    ("fees.structures_by_quota", "Quota/category structures", "structure dimensions", True, "starter", ("fees.core",)),
    ("fees.instalments", "Instalments", "instalment schedules", True, "starter", ("fees.core",)),
    ("fees.auto_late_fee", "Automatic late fee", "Beat late-fee posting", True, "standard", ("fees.instalments",)),
    ("fees.online_payment", "Online payment", "gateway checkout", True, "starter", ("integrations.payments",)),
    ("fees.upi_qr", "UPI QR", "static/dynamic UPI QR receipts", True, "standard", ("fees.online_payment",)),
    (
        "fees.offline_challan_reconciliation",
        "Offline payments",
        "challan/NEFT/DD with UTR reconciliation",
        True,
        "standard",
        ("fees.core",),
    ),
    ("fees.discounts", "Discounts & concessions", "discount rules", True, "starter", ("fees.core",)),
    (
        "fees.staff_ward_concession",
        "Staff-ward concession",
        "automatic concession for staff wards",
        False,
        "standard",
        ("fees.discounts", "hr.staff"),
    ),
    ("fees.fines", "Fines", "fine configuration", True, "starter", ("fees.core",)),
    (
        "fees.scholarships",
        "Scholarships",
        "scholarship applications & disbursement",
        True,
        "standard",
        ("fees.core", "workflow.engine"),
    ),
    ("fees.nsp_integration", "NSP integration", "NSP references/exports", False, "professional", ("integrations.nsp",)),
    ("fees.no_dues", "No-dues clearance", "multi-department sign-off", True, "standard", ("workflow.engine",)),
    ("fees.refunds", "Refunds", "refund workflow", True, "standard", ("fees.core",)),
    (
        "fees.receipt_cancellation_approval",
        "Receipt cancellation approval",
        "cancellation via workflow",
        True,
        "standard",
        ("workflow.engine",),
    ),
    ("fees.gst_invoicing", "GST invoicing", "GST fields/reports", False, "standard", ("accounting.gst_reports",)),
    ("fees.thermal_receipts", "Thermal receipts", "mobile ESC/POS printing", True, "standard", ("mobile.app",)),
    (
        "fees.accounting_export",
        "Accounting export",
        "Tally/Zoho export",
        False,
        "standard",
        ("accounting.tally_export",),
    ),
)

for _key, _name, _desc, _on, _tier, _deps in _FEES:
    register_feature(
        key=_key,
        group="fees",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )

register_feature(
    key="integrations.payments",
    group="integrations",
    name="Payment gateways",
    description="Razorpay/PayU/Cashfree/Stripe",
    default_enabled=True,
    min_plan_tier="starter",
    depends_on=(),
)
