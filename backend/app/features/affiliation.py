"""Feature keys registered by Phase 34 (docs/Feature_Flags.md affiliation group): the university ↔ affiliated-college
relationship — registry / applications / programme approvals (``affiliation.core``), scrutiny → inspection → compliance
(``affiliation.inspections``), term / session data submissions with the result-gating lock
(``affiliation.data_submissions``), fee schedules and college dues (``affiliation.fees``) and exam centres per central
session (``affiliation.exam_centres``, moved here from the Phase 14 registration — same key, same defaults). All are off
and university tier: standalone / autonomous college tenants never enable them.
"""

from app.core.features import FEATURE_REGISTRY, register_feature

_U = "university"
_KEYS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("affiliation.core", "Affiliation", "college affiliation records", ("institution.multi_college",)),
    ("affiliation.inspections", "Inspections", "inspection workflow", ("affiliation.core",)),
    ("affiliation.data_submissions", "College data submissions", "term submissions", ("affiliation.core",)),
    ("affiliation.exam_centres", "Exam centres", "centres per session", ("exams.sessions",)),
    ("affiliation.fees", "Affiliation fees", "fee schedules", ("fees.core",)),
)

for _key, _name, _desc, _deps in _KEYS:
    if _key in FEATURE_REGISTRY:
        continue
    register_feature(
        key=_key,
        group="affiliation",
        name=_name,
        description=_desc,
        default_enabled=False,
        min_plan_tier=_U,
        depends_on=_deps,
    )
