"""Feature keys registered by Phase 27 (docs/Feature_Flags.md §2.14 mentoring / grievances / discipline / surveys /
clubs). ``governance.committees`` (registered here by the Phase 27 stub) now lives in ``app/features/governance.py``.

Dependencies on keys of later phases (``analytics.early_warning`` — Phase 35) are listed as documented.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("student_support", "mentoring.core", "Mentoring", "assignments, sessions", True, "standard", ()),
    (
        "student_support",
        "mentoring.appointment_slots",
        "Mentor slots",
        "bookable slots",
        True,
        "standard",
        ("mentoring.core",),
    ),
    (
        "student_support",
        "mentoring.early_warning",
        "Early warning",
        "risk flags",
        False,
        "professional",
        ("analytics.early_warning",),
    ),
    ("student_support", "mentoring.counselling", "Counselling", "referrals", True, "standard", ("mentoring.core",)),
    ("student_support", "grievances.core", "Grievances", "tickets, SLA", True, "standard", ("workflow.engine",)),
    (
        "student_support",
        "grievances.anonymous",
        "Anonymous grievances",
        "public form",
        True,
        "standard",
        ("grievances.core",),
    ),
    (
        "student_support",
        "grievances.committees",
        "Grievance committees",
        "ICC/anti-ragging routing",
        True,
        "standard",
        ("governance.committees",),
    ),
    (
        "student_support",
        "discipline.core",
        "Discipline",
        "cases, sanctions",
        True,
        "standard",
        ("governance.committees",),
    ),
    ("student_support", "surveys.core", "Surveys", "surveys & responses", True, "standard", ()),
    (
        "student_support",
        "surveys.sss",
        "Student satisfaction survey",
        "SSS template",
        True,
        "standard",
        ("surveys.core",),
    ),
    ("student_support", "clubs.core", "Clubs & activities", "clubs, events", True, "standard", ()),
    (
        "student_support",
        "clubs.activity_hours_credits",
        "Activity hours → credits",
        "NSS/NCC hours ledger",
        False,
        "standard",
        ("clubs.core",),
    ),
    (
        "student_support",
        "clubs.achievements",
        "Achievements",
        "verified achievements",
        True,
        "standard",
        ("clubs.core",),
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
