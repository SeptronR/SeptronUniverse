"""Feature keys registered by Phase 32 (docs/Feature_Flags.md §2 accreditation): AISHE data is on (standard); NAAC,
NIRF, AICTE / UGC returns, the evidence repository and audit registers are off (professional); NBA depends on
``obe.attainment`` and IQAC cycles on ``accreditation.naac``.
"""

from app.core.features import FEATURE_REGISTRY, register_feature

_P, _S = "professional", "standard"
_KEYS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("accreditation.naac", "NAAC", "NAAC framework & metrics", False, _P, ()),
    ("accreditation.nba", "NBA", "NBA framework", False, _P, ("obe.attainment",)),
    ("accreditation.nirf", "NIRF", "NIRF data", False, _P, ()),
    ("accreditation.aishe", "AISHE", "AISHE data", True, _S, ()),
    ("accreditation.aicte_ugc", "AICTE / UGC returns", "approval data packs", False, _P, ()),
    ("accreditation.evidence_repo", "Evidence repository", "evidence files", False, _P, ()),
    ("accreditation.iqac_cycles", "IQAC cycles", "cycles & narratives", False, _P, ("accreditation.naac",)),
    ("accreditation.audit_registers", "Audit registers", "academic/green/gender audits", False, _P, ()),
)

for _key, _name, _desc, _on, _tier, _deps in _KEYS:
    if _key in FEATURE_REGISTRY:
        continue
    register_feature(
        key=_key,
        group="accreditation",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
