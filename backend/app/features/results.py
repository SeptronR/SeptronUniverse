"""Feature keys registered by Phase 15 (docs/Feature_Flags.md exams group, valuation half, and the results group
used by Prompts/15). ``exams.external_examiners`` / ``exams.remuneration`` were registered by Phase 14."""

from app.core.features import FEATURE_REGISTRY, register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    (
        "exams",
        "exams.coding_dummy",
        "Dummy-number coding",
        "bundles, coding, decode",
        True,
        "standard",
        ("exams.sessions",),
    ),
    (
        "exams",
        "exams.double_valuation",
        "Double valuation",
        "second valuation + discrepancy",
        False,
        "professional",
        ("exams.coding_dummy",),
    ),
    (
        "exams",
        "exams.onscreen_valuation",
        "Onscreen valuation",
        "scanned scripts UI",
        False,
        "professional",
        ("exams.coding_dummy",),
    ),
    ("exams", "exams.moderation", "Moderation", "moderation actions", True, "standard", ("exams.coding_dummy",)),
    ("exams", "exams.grace", "Grace marks", "grace rules", True, "standard", ("results.processing",)),
    (
        "exams",
        "exams.relative_grading",
        "Relative grading",
        "z-score grading",
        False,
        "professional",
        ("results.processing",),
    ),
    (
        "exams",
        "exams.script_custody",
        "Script custody & retention",
        "custody log, destruction register",
        True,
        "standard",
        ("exams.coding_dummy",),
    ),
    (
        "results",
        "results.processing",
        "Result processing",
        "runs, grades, SGPA/CGPA",
        True,
        "starter",
        ("exams.sessions",),
    ),
    (
        "results",
        "results.publication_portal",
        "Result publication",
        "student/public result views",
        True,
        "starter",
        ("results.processing",),
    ),
    ("results", "results.grade_cards", "Grade cards", "grade card PDFs", True, "starter", ("documents.templates",)),
    (
        "results",
        "results.rank_lists",
        "Rank lists & medals",
        "ranks, medals",
        True,
        "standard",
        ("results.processing",),
    ),
    (
        "results",
        "results.legacy_import",
        "Legacy result import",
        "import past results",
        True,
        "standard",
        ("data.migration_toolkit",),
    ),
    (
        "results",
        "results.sms_masked_notify",
        "Masked result SMS",
        "SMS with masked details",
        True,
        "standard",
        ("comms.sms",),
    ),
)

for _group, _key, _name, _desc, _on, _tier, _deps in _KEYS:
    if _key in FEATURE_REGISTRY:
        continue
    register_feature(
        key=_key,
        group=_group,
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
