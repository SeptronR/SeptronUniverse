"""Feature keys registered by Phase 03 (docs/Feature_Flags.md §2.2 — institution).

``core.institution`` / ``core.settings`` (non-toggleable) live in ``app/core/features.py`` and gate the base routes.
"""

from app.core.features import register_feature

register_feature(
    key="institution.multi_college",
    group="institution",
    name="Multiple colleges/campuses",
    description="college switcher, college scopes",
    default_enabled=False,
    min_plan_tier="university",
)
register_feature(
    key="institution.faculties",
    group="institution",
    name="Faculties/schools",
    description="faculty layer between college and department",
    default_enabled=False,
    min_plan_tier="standard",
)
register_feature(
    key="institution.holidays",
    group="institution",
    name="Holiday calendar",
    description="holidays master",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="institution.themes",
    group="institution",
    name="Themes & branding",
    description="colour themes, table styles, logos",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="institution.number_sequences_custom",
    group="institution",
    name="Custom number formats",
    description="editable patterns for reg/hall-ticket/certificate numbers",
    default_enabled=True,
    min_plan_tier="standard",
)
