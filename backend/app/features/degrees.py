"""Feature keys registered by Phase 18 (docs/Feature_Flags.md degrees group).

``academics.nep_exit_reentry`` ships with Phase 07. Dependencies on keys of later phases (``events.core``,
``documents.templates``, ``integrations.esign``, ``integrations.digilocker_nad``) are listed as documented.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    (
        "degrees",
        "degrees.eligibility",
        "Degree eligibility",
        "eligibility engine",
        True,
        "standard",
        ("results.processing",),
    ),
    ("degrees", "degrees.convocation", "Convocation", "events & registrations", True, "standard", ("events.core",)),
    (
        "degrees",
        "degrees.certificates",
        "Degree certificates",
        "awards, serials, PDFs",
        True,
        "standard",
        ("documents.templates",),
    ),
    (
        "degrees",
        "degrees.provisional",
        "Provisional certificates",
        "provisional issue",
        True,
        "standard",
        ("degrees.certificates",),
    ),
    (
        "degrees",
        "degrees.esign",
        "e-Sign certificates",
        "DSC/eSign adapter",
        False,
        "professional",
        ("integrations.esign",),
    ),
    (
        "degrees",
        "degrees.digilocker_nad",
        "DigiLocker / NAD push",
        "credential push",
        False,
        "professional",
        ("integrations.digilocker_nad",),
    ),
    ("degrees", "degrees.abc_push", "ABC credit push", "ledger push", False, "professional", ("academics.abc_apaar",)),
    (
        "degrees",
        "degrees.verification_portal",
        "Verification portal",
        "public `/verify`",
        True,
        "standard",
        ("degrees.certificates",),
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
