"""Feature keys registered by Phase 11 (docs/Feature_Flags.md attendance group).

``attendance.staff``, ``attendance.biometric`` and ``attendance.geo_app`` were registered by Phase 06
(``app/features/hr.py``) — Phase 11 reuses them for student punches and geo check-in.
"""

from app.core.features import register_feature

_ATTENDANCE: tuple[tuple[str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("attendance.core", "Attendance", "session attendance", True, "starter", ("timetable.core",)),
    ("attendance.qr", "QR attendance", "session QR check-in", True, "standard", ("attendance.core", "mobile.app")),
    ("attendance.rfid", "RFID", "RFID punches", False, "standard", ("integrations.biometric_rfid",)),
    ("attendance.on_duty", "On-duty", "OD requests", True, "starter", ("attendance.core",)),
    (
        "attendance.condonation",
        "Condonation",
        "condonation workflow + fee",
        True,
        "standard",
        ("attendance.core", "workflow.engine"),
    ),
    (
        "attendance.eligibility_detention",
        "Eligibility & detention",
        "eligibility snapshots, detention lists",
        True,
        "starter",
        ("attendance.core",),
    ),
    ("attendance.guardian_alerts", "Guardian alerts", "absence notifications", True, "starter", ("comms.sms",)),
    ("attendance.offline_mobile", "Offline attendance", "mobile write queue", True, "standard", ("mobile.offline",)),
)

for _key, _name, _desc, _on, _tier, _deps in _ATTENDANCE:
    register_feature(
        key=_key,
        group="attendance",
        name=_name,
        description=_desc,
        default_enabled=_on,
        min_plan_tier=_tier,
        depends_on=_deps,
    )
