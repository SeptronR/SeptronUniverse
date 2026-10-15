"""Feature keys registered by Phase 08 (docs/Feature_Flags.md §2 admissions and ``website.enquiry``).

Several dependencies name keys of later phases (``documents.templates`` — Phase 26, ``fees.refunds`` — Phase 12,
``comms.sms`` — Phase 04, ``academics.value_added_courses`` — Phase 05): until those modules register them the
documented defaults apply (the registry only checks that a dependency is documented).
"""

from app.core.features import register_feature

_ADMISSIONS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("admissions.cycles", "Admission cycles", "cycles, cycle programmes", True, "starter", ()),
    (
        "admissions.online_application",
        "Online application",
        "public apply portal",
        True,
        "starter",
        ("admissions.cycles",),
    ),
    (
        "admissions.entrance_import",
        "Entrance/counselling import",
        "CSV import of ranks/allotments",
        True,
        "standard",
        ("admissions.cycles",),
    ),
    ("admissions.merit_lists", "Merit lists", "merit computation & publish", True, "starter", ("admissions.cycles",)),
    ("admissions.seat_matrix", "Seat matrix", "quota × category seats", True, "starter", ("admissions.cycles",)),
    (
        "admissions.counselling_allotment",
        "Counselling & allotment",
        "rounds, choice filling, allotment",
        True,
        "standard",
        ("admissions.seat_matrix", "admissions.merit_lists"),
    ),
    (
        "admissions.document_verification",
        "Document verification",
        "verification queue",
        True,
        "starter",
        ("admissions.cycles",),
    ),
    ("admissions.offers", "Admission offers", "offer letters", True, "starter", ("documents.templates",)),
    ("admissions.lateral_entry", "Lateral entry", "lateral intake handling", True, "standard", ("admissions.cycles",)),
    ("admissions.enquiry_crm", "Enquiry CRM", "enquiries pipeline", True, "standard", ("comms.sms",)),
    (
        "admissions.open_enrolment",
        "Open enrolment",
        "non-degree learner admission",
        False,
        "standard",
        ("academics.value_added_courses",),
    ),
    ("admissions.refunds", "Admission refunds", "withdrawal refund rules", True, "standard", ("fees.refunds",)),
)
_WEBSITE: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("website.enquiry", "Website enquiry", "enquiry forms", True, "starter", ("admissions.enquiry_crm",)),
)

for _group, _rows in (("admissions", _ADMISSIONS), ("website", _WEBSITE)):
    for _key, _name, _desc, _on, _tier, _deps in _rows:
        register_feature(
            key=_key,
            group=_group,
            name=_name,
            description=_desc,
            default_enabled=_on,
            min_plan_tier=_tier,
            depends_on=_deps,
        )
