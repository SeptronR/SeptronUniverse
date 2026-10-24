"""Feature keys registered by Phase 17 (docs/Feature_Flags.md obe group, attainment half).

``obe.definitions`` ships with Phase 13. ``surveys.core`` belongs to Phase 27 — the dependency is listed as documented.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    (
        "obe",
        "obe.attainment",
        "OBE attainment",
        "CO / PO / PSO attainment runs",
        False,
        "professional",
        ("obe.definitions", "assessment.question_wise_co"),
    ),
    (
        "obe",
        "obe.indirect_surveys",
        "Indirect attainment",
        "course-exit / programme-exit / alumni / employer surveys",
        False,
        "professional",
        ("surveys.core",),
    ),
    (
        "obe",
        "obe.cqi",
        "CQI register",
        "continuous quality improvement actions",
        False,
        "professional",
        ("obe.attainment",),
    ),
    ("obe", "obe.nba_export", "NBA SAR export", "Criterion 3 tables", False, "professional", ("obe.attainment",)),
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
