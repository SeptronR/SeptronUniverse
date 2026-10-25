"""Feature keys registered by Phase 26 (docs/Feature_Flags.md — documents)."""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("documents.templates", "Document templates", "builder, renderer, issued register", True, "starter", ()),
    (
        "documents.bulk_generation",
        "Bulk generation",
        "ID cards, bonafide, letters in bulk",
        True,
        "starter",
        ("core.background_jobs",),
    ),
    (
        "documents.certificate_requests",
        "Certificate requests",
        "self-service requests with fees and approval",
        True,
        "standard",
        ("workflow.engine", "fees.core"),
    ),
    (
        "documents.serial_registers",
        "Serial registers",
        "statutory serial books",
        True,
        "standard",
        ("documents.templates",),
    ),
    (
        "documents.watermark_signed_links",
        "Signed download links",
        "time-limited, watermarked downloads",
        True,
        "standard",
        ("documents.templates",),
    ),
    (
        "documents.bilingual_templates",
        "Bilingual templates",
        "secondary-language layouts",
        False,
        "standard",
        ("documents.templates",),
    ),
)

for _key, _name, _desc, _on, _tier, _deps in _KEYS:
    register_feature(
        key=_key,
        group="documents",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
