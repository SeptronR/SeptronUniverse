"""Feature keys registered by Phase 28 (docs/Feature_Flags.md §2 placement): placement core, recruiter portal,
internships, training programmes and the resume builder. ``portals.recruiter`` (Phase 39 shell) reuses these endpoints.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("placement", "placement.core", "Placement", "companies, drives, offers", True, "standard", ()),
    (
        "placement",
        "placement.recruiter_portal",
        "Recruiter portal",
        "company users",
        False,
        "professional",
        ("placement.core",),
    ),
    (
        "placement",
        "placement.internships",
        "Internships",
        "internship records, NOC",
        True,
        "standard",
        ("placement.core",),
    ),
    (
        "placement",
        "placement.training",
        "Training programmes",
        "training & attendance",
        True,
        "standard",
        ("placement.core",),
    ),
    (
        "placement",
        "placement.resume_builder",
        "Resume builder",
        "structured resumes",
        True,
        "standard",
        ("placement.core",),
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
