"""Feature keys registered by Phase 09 (docs/Feature_Flags.md §2 registration).

``registration.arrears`` depends on ``results.processing`` (Phase 15) and ``registration.self_service`` on
``portals.student`` (Phase 39): until those modules register them the documented defaults apply (the registry only
checks that a dependency is documented). ``hr.workload`` (Phase 06) already names ``registration.core``.
"""

from app.core.features import register_feature

_REGISTRATION: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("registration.core", "Course registration", "windows, registrations", True, "starter", ("academics.curriculum",)),
    (
        "registration.self_service",
        "Student self-registration",
        "student cart",
        True,
        "starter",
        ("registration.core", "portals.student"),
    ),
    (
        "registration.advisor_approval",
        "Advisor approval",
        "approval queue",
        True,
        "standard",
        ("registration.core", "workflow.engine"),
    ),
    (
        "registration.elective_allocation",
        "Elective allocation",
        "choice forms, allocation runs",
        True,
        "standard",
        ("academics.elective_baskets",),
    ),
    ("registration.waitlist", "Waitlists", "offering waitlists", True, "standard", ("registration.core",)),
    ("registration.add_drop", "Add/drop", "add-drop windows", True, "starter", ("registration.core",)),
    (
        "registration.arrears",
        "Arrear registration",
        "arrears register & windows",
        True,
        "starter",
        ("results.processing",),
    ),
    ("registration.audit_courses", "Audit courses", "non-credit audit", False, "standard", ("registration.core",)),
    (
        "registration.overrides",
        "Registration overrides",
        "admin overrides with reason",
        True,
        "standard",
        ("registration.core",),
    ),
)

for _key, _name, _desc, _on, _tier, _deps in _REGISTRATION:
    register_feature(
        key=_key,
        group="registration",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
