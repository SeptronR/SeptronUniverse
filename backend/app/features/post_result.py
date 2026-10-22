"""Feature keys registered by Phase 16 (docs/Feature_Flags.md results group, post-result half)."""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("results", "results.revaluation", "Revaluation", "reval requests", True, "standard", ("results.processing",)),
    (
        "results",
        "results.photocopy",
        "Photocopy / retotaling",
        "photocopy & retotaling requests",
        True,
        "standard",
        ("results.revaluation",),
    ),
    (
        "results",
        "results.challenge_valuation",
        "Challenge valuation",
        "third-party challenge",
        False,
        "professional",
        ("results.revaluation",),
    ),
    (
        "results",
        "results.supplementary",
        "Supplementary / arrear exams",
        "supplementary sessions",
        True,
        "starter",
        ("exams.sessions",),
    ),
    (
        "results",
        "results.malpractice",
        "Malpractice",
        "cases, hearings, punishments",
        True,
        "standard",
        ("governance.committees",),
    ),
    (
        "results",
        "results.transcripts",
        "Transcripts",
        "transcript requests",
        True,
        "standard",
        ("documents.templates",),
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
