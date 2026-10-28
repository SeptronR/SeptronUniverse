"""Feature keys registered by Phase 39 (docs/Feature_Flags.md §2.15 portals + ``i18n.web`` of §2.1).

``portals.student`` / ``portals.parent`` (Phase 07), ``portals.alumni`` (Phase 29), ``portals.warden`` (Phase 20),
``portals.scholar`` (Phase 31) and ``platform.guided_tours`` / ``platform.help_center`` / ``platform.in_app_feedback``
(Phase 01) already exist; this module adds the remaining portal shells, PWA / web push and web localisation.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("platform", "portals.faculty", "Faculty portal", "faculty portal", True, "starter", ()),
    (
        "platform",
        "portals.evaluator",
        "Evaluator portal",
        "external evaluator",
        True,
        "standard",
        ("exams.external_examiners",),
    ),
    (
        "platform",
        "portals.recruiter",
        "Recruiter portal",
        "company users",
        False,
        "professional",
        ("placement.recruiter_portal",),
    ),
    ("platform", "portals.pwa_push", "PWA & web push", "manifest, push", True, "starter", ()),
    ("core", "i18n.web", "Web localisation", "language switch on web", False, "standard", ()),
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
