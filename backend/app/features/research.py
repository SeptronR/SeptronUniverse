"""Feature keys registered by Phase 30 (docs/Feature_Flags.md §2 research / integrations): publications, patents,
funded projects (on the Phase 23 grants ledger), consultancy, FDP, MoUs (standard, on), the professional ethics
committee / seed grants & incentives / incubation / API score keys (off), and the bibliographic + plagiarism adapters.
"""

from app.core.features import FEATURE_REGISTRY, register_feature

_FP = ("hr.faculty_profiles",)
_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("research", "research.publications", "Publications", "publication records", True, "standard", _FP),
    ("research", "research.patents", "Patents", "patent records", True, "standard", _FP),
    (
        "research",
        "research.projects_grants",
        "Projects & grants",
        "funded projects, utilisation",
        True,
        "standard",
        ("accounting.grants_ledger",),
    ),
    ("research", "research.consultancy", "Consultancy", "consultancy records", True, "standard", _FP),
    (
        "research",
        "research.ethics_committee",
        "Ethics committees",
        "IEC/IAEC approvals",
        False,
        "professional",
        ("governance.committees",),
    ),
    (
        "research",
        "research.seed_grants_incentives",
        "Seed grants & incentives",
        "incentive workflows",
        False,
        "professional",
        ("workflow.engine",),
    ),
    ("research", "research.fdp", "FDP & development", "FDP records", True, "standard", _FP),
    ("research", "research.mous_collaborations", "MoUs & collaborations", "MoU register", True, "standard", ()),
    ("research", "research.incubation", "Incubation & start-ups", "incubation register", False, "professional", ()),
    (
        "research",
        "research.api_score",
        "API score",
        "API/CAS computation",
        False,
        "professional",
        ("research.publications",),
    ),
    (
        "integrations",
        "integrations.scopus_crossref_orcid",
        "Scopus / Crossref / ORCID",
        "publication lookup",
        False,
        "professional",
        (),
    ),
    (
        "integrations",
        "integrations.plagiarism",
        "Plagiarism checkers",
        "DrillBit/Urkund/Turnitin",
        False,
        "professional",
        (),
    ),
)

for _group, _key, _name, _desc, _on, _tier, _deps in _KEYS:
    if _key in FEATURE_REGISTRY:  # an earlier phase may have registered an integration key already
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
