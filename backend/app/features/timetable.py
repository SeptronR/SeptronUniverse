"""Feature keys registered by Phase 10 (docs/Feature_Flags.md §2.6 timetable).

``timetable.substitutions`` depends on ``hr.leaves`` (Phase 06 — approved leaves feed the auto-substitution requests);
``timetable.auto_generate`` is off by default (professional tier) and ships as a greedy placer
(``services/timetable/auto_generate_service.py``).
"""

from app.core.features import register_feature

_TIMETABLE: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("timetable.core", "Timetable", "timetables, entries, sessions", True, "starter", ()),
    ("timetable.rooms", "Rooms & buildings", "room master", True, "starter", ()),
    (
        "timetable.substitutions",
        "Substitutions",
        "substitution requests, auto-flag",
        True,
        "standard",
        ("hr.leaves",),
    ),
    ("timetable.auto_generate", "Auto timetable", "constraint solver", False, "professional", ("timetable.core",)),
    ("timetable.ical", "iCal export", "personal/section iCal", True, "starter", ("timetable.core",)),
)

for _key, _name, _desc, _on, _tier, _deps in _TIMETABLE:
    register_feature(
        key=_key,
        group="timetable",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
