"""Feature keys registered by Phase 05 (docs/Feature_Flags.md §2.3 — academics).

``academics.credit_transfer_mooc``, ``academics.nep_exit_reentry`` and ``academics.abc_apaar`` register here but are
exercised in Phase 07 (credit transfers, NEP exits, APAAR ids).
"""

from app.core.features import register_feature

for _key, _name, _desc, _on, _tier, _deps in (
    ("academics.programs", "Programmes", "programme master", True, "starter", ()),
    ("academics.regulations", "Regulations", "versioned regulations & rules", True, "starter", ("academics.programs",)),
    (
        "academics.curriculum",
        "Curriculum structure",
        "structure terms, curriculum courses",
        True,
        "starter",
        ("academics.regulations",),
    ),
    (
        "academics.elective_baskets",
        "Elective baskets",
        "baskets, choice forms",
        True,
        "starter",
        ("academics.curriculum",),
    ),
    (
        "academics.minors_honours",
        "Minors & honours",
        "minor programmes, honours tracks",
        False,
        "standard",
        ("academics.elective_baskets",),
    ),
    (
        "academics.value_added_courses",
        "Value-added / certificate courses",
        "VAC/CE courses & open enrolment",
        True,
        "standard",
        ("academics.programs",),
    ),
    (
        "academics.credit_transfer_mooc",
        "MOOC / credit transfer",
        "credit_transfers workflow",
        True,
        "standard",
        ("academics.curriculum",),
    ),
    (
        "academics.nep_exit_reentry",
        "NEP multiple entry/exit",
        "exit points, exit awards, re-entry",
        True,
        "standard",
        ("degrees.certificates",),
    ),
    (
        "academics.abc_apaar",
        "ABC / APAAR",
        "APAAR ids, ABC ledger",
        True,
        "standard",
        ("integrations.digilocker_nad",),
    ),
    (
        "academics.bos_approval_workflow",
        "BoS approval workflow",
        "regulation approval via committees",
        False,
        "professional",
        ("workflow.engine", "governance.committees"),
    ),
    (
        "academics.public_catalog",
        "Public course catalogue",
        "`/catalog` pages",
        True,
        "standard",
        ("website.core",),
    ),
):
    register_feature(
        key=_key,
        group="academics",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
