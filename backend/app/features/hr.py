"""Feature keys registered by Phase 06 (docs/Feature_Flags.md §2.11 HR and §2.6 staff attendance).

``attendance.staff`` / ``attendance.biometric`` / ``attendance.geo_app`` live in the attendance group of the doc; the
biometric and geo keys register here because staff attendance is their first consumer (student attendance in Phase 11
reuses them). ``hr.workload`` depends on ``registration.core`` (Phase 09): until offerings exist the computation
reports 0 teaching hours against the cadre norm.
"""

from app.core.features import register_feature

_HR: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("hr.staff", "Staff management", "staff master, documents", True, "starter", ()),
    ("hr.faculty_profiles", "Faculty profiles", "academic ids, cadre, guide status", True, "starter", ("hr.staff",)),
    ("hr.guest_faculty", "Guest / visiting faculty", "hourly remuneration", True, "standard", ("hr.payroll",)),
    ("hr.leaves", "Leave management", "types, requests, balances", True, "starter", ("workflow.engine",)),
    (
        "hr.leave_encashment",
        "Leave encashment",
        "encashment rules",
        False,
        "standard",
        ("hr.leaves", "hr.payroll"),
    ),
    ("hr.payroll", "Payroll", "payroll runs, payslips", True, "standard", ("hr.staff",)),
    ("hr.statutory_payroll", "Statutory payroll", "PF/ESI/PT/TDS, Form 16", True, "standard", ("hr.payroll",)),
    ("hr.loans_advances", "Loans & advances", "loan schedules", False, "standard", ("hr.payroll",)),
    ("hr.staff_attendance", "Staff attendance", "check-in, devices", True, "standard", ("hr.staff",)),
    ("hr.service_book", "Service book", "service records", True, "standard", ("hr.staff",)),
    ("hr.recruitment", "Recruitment", "postings → appointment", False, "professional", ("workflow.engine",)),
    ("hr.reservation_roster", "Reservation roster", "roster validation", False, "professional", ("hr.recruitment",)),
    ("hr.appraisal_pbas", "Appraisal (PBAS)", "self-appraisal workflow", False, "professional", ("workflow.engine",)),
    ("hr.cas_promotions", "CAS promotions", "CAS applications", False, "professional", ("hr.appraisal_pbas",)),
    ("hr.workload", "Workload", "workload computation & norms", True, "standard", ("registration.core",)),
)
_ATTENDANCE: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("attendance.staff", "Staff attendance", "staff check-in, devices", True, "standard", ("hr.staff",)),
    (
        "attendance.biometric",
        "Biometric devices",
        "punch ingest",
        False,
        "standard",
        ("integrations.biometric_rfid",),
    ),
    ("attendance.geo_app", "Geo-fenced app attendance", "GPS-verified marking", False, "standard", ("mobile.app",)),
)

for _group, _rows in (("hr", _HR), ("attendance", _ATTENDANCE)):
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
