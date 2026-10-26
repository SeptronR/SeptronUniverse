"""Feature keys registered by Phase 33 (docs/Feature_Flags.md §2 governance): committees, minutes / resolutions and the
policy repository are on (standard); legal cases, RTI and e-File are off (professional); audit paras are off
(professional) and depend on Phase 32's ``accreditation.audit_registers``. ``governance.committees`` moved here from the
Phase 27 stub registration (same key, same defaults).
"""

from app.core.features import FEATURE_REGISTRY, register_feature

_P, _S = "professional", "standard"
_KEYS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("governance.committees", "Committees", "committees & members", True, _S, ()),
    (
        "governance.minutes",
        "Meetings & minutes",
        "meetings, minutes, resolutions, ATRs",
        True,
        _S,
        ("governance.committees",),
    ),
    ("governance.policies", "Policies", "policy repository & acknowledgements", True, _S, ()),
    ("governance.legal", "Legal cases", "case register & hearings", False, _P, ()),
    ("governance.rti", "RTI", "RTI requests, appeals & returns", False, _P, ()),
    ("governance.efile", "e-File", "file movement & notings", False, _P, ()),
    (
        "governance.audit_paras",
        "Audit paras",
        "statutory / AG audit paras",
        False,
        _P,
        ("accreditation.audit_registers",),
    ),
)

for _key, _name, _desc, _on, _tier, _deps in _KEYS:
    if _key in FEATURE_REGISTRY:
        continue
    register_feature(
        key=_key,
        group="governance",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
