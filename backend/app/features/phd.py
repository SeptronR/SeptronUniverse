"""Feature keys registered by Phase 31 (docs/Feature_Flags.md §2 phd / portals / integrations): the PhD lifecycle keys
(all off, professional), the ``portals.scholar`` shell key (Phase 39 builds the shell on these endpoints) and the
``integrations.koha_dspace_shodhganga`` adapter key the ETD upload depends on (mocks until Phase 41).
"""

from app.core.features import FEATURE_REGISTRY, register_feature

_P = "professional"
_CORE = ("phd.core",)
_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("phd", "phd.core", "PhD scholars", "scholar records, guides", False, _P, ("academics.programs",)),
    ("phd", "phd.coursework", "PhD coursework", "coursework registration/results", False, _P, _CORE),
    ("phd", "phd.dc_meetings", "Doctoral committee", "DC constitution & meetings", False, _P, _CORE),
    ("phd", "phd.progress_reports", "Progress reports", "half-yearly reports", False, _P, _CORE),
    ("phd", "phd.fellowships", "Fellowships", "fellowship disbursement", False, _P, ("phd.core", "hr.payroll")),
    (
        "phd",
        "phd.extensions_guide_change",
        "Scholar requests",
        "extension, guide change",
        False,
        _P,
        ("workflow.engine",),
    ),
    (
        "phd",
        "phd.thesis_plagiarism",
        "Thesis & plagiarism",
        "submissions, similarity",
        False,
        _P,
        ("integrations.plagiarism",),
    ),
    ("phd", "phd.external_examiners", "Thesis examiners", "examiner panel", False, _P, ("phd.thesis_plagiarism",)),
    ("phd", "phd.viva", "Viva-voce", "viva scheduling", False, _P, ("phd.external_examiners",)),
    (
        "phd",
        "phd.etd_upload",
        "ETD upload",
        "Shodhganga/institutional",
        False,
        _P,
        ("integrations.koha_dspace_shodhganga",),
    ),
    ("phd", "phd.scholar_portal", "Scholar portal", "scholar self-service", False, _P, _CORE),
    ("platform", "portals.scholar", "Scholar portal", "PhD scholar", False, _P, _CORE),
    (
        "integrations",
        "integrations.koha_dspace_shodhganga",
        "Koha / DSpace / Shodhganga",
        "library & repositories",
        False,
        _P,
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
