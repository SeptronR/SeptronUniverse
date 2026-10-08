"""Feature keys registered by Phase 07 (docs/Feature_Flags.md §2.4 students and the student / parent portals of §2.15).

``students.core`` moved here from the Phase 02 development stub (``app/features/dev_stubs.py``) together with the real
``POST /students`` route. ``academics.credit_transfer_mooc`` / ``academics.nep_exit_reentry`` / ``academics.abc_apaar``
were registered by Phase 05 (``app/features/academics.py``) and are exercised here. Several dependencies name keys of
later phases (``documents.templates`` — Phase 26, ``results.processing`` — Phase 15): until those modules register
them the documented defaults apply (the registry only checks that a dependency is documented).
"""

from app.core.features import register_feature

_STUDENTS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("students.core", "Student records", "student master, enrolments, term records", True, "starter", ()),
    ("students.guardians_portal", "Guardian portal", "guardian users, consent", True, "starter", ("portals.parent",)),
    ("students.documents", "Student documents", "document uploads/verification", True, "starter", ()),
    (
        "students.undertakings",
        "Undertakings & consents",
        "e-accept of affidavits",
        True,
        "standard",
        ("documents.templates",),
    ),
    ("students.id_cards", "ID cards", "ID card generation", True, "starter", ("documents.templates",)),
    ("students.bulk_import", "Bulk import", "CSV/XLSX student import", True, "starter", ()),
    ("students.holds", "Holds", "student_holds & gates", True, "standard", ()),
    (
        "students.academic_standing",
        "Academic standing",
        "standing rules & flags",
        True,
        "standard",
        ("results.processing",),
    ),
    (
        "students.international_office",
        "International students",
        "passport/visa/FRRO tracking",
        False,
        "standard",
        (),
    ),
    (
        "students.transfers_migration",
        "Transfers & migration",
        "transfer requests, certificates",
        True,
        "standard",
        ("documents.templates",),
    ),
    (
        "students.self_service_profile",
        "Self-service profile",
        "student edits own contact/photo",
        True,
        "starter",
        ("portals.student",),
    ),
)
_PORTALS: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("portals.student", "Student portal", "student portal & PWA", True, "starter", ()),
    ("portals.parent", "Parent portal", "parent portal", True, "starter", ()),
)

for _group, _rows in (("students", _STUDENTS), ("platform", _PORTALS)):
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
