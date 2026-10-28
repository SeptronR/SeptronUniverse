"""Feature keys registered by Phase 40 (docs/Feature_Flags.md website group). ``website.enquiry`` was registered by
Phase 08 (``app/features/admissions.py``) with the enquiry CRM; the marketing site is platform-level (no tenant key)."""

from app.core.features import register_feature

for _key, _name, _desc, _on, _tier, _deps in (
    ("website.core", "Public website", "institution site", True, "starter", ()),
    ("website.course_catalog", "Catalogue pages", "public catalogue", True, "standard", ("academics.public_catalog",)),
    ("website.custom_domain", "Custom domain", "domain mapping", False, "standard", ("website.core",)),
):
    register_feature(
        key=_key,
        group="website",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
