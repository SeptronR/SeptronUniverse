"""Feature keys registered by Phase 20 (docs/Feature_Flags.md hostel group + ``portals.warden``).

``hostel.core`` moved here from ``app/features/dev_stubs.py`` (the Phase 02 stub route is gone). Dependencies on keys of
later phases (``comms.sms``, ``mobile.app``, ``facilities.service_desk``) are listed as documented.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("campus", "hostel.core", "Hostel", "hostels, rooms, allocations", False, "standard", ()),
    ("campus", "hostel.mess", "Mess", "plans, subscriptions, attendance", False, "standard", ("hostel.core",)),
    ("campus", "hostel.mess_billing", "Mess billing", "monthly bills", False, "standard", ("hostel.mess", "fees.core")),
    (
        "campus",
        "hostel.leave_outpass",
        "Out-pass & leave",
        "requests, guardian OTP",
        False,
        "standard",
        ("hostel.core", "comms.sms"),
    ),
    (
        "campus",
        "hostel.gate_qr",
        "Gate QR",
        "mark-out/return scanning",
        False,
        "standard",
        ("hostel.leave_outpass", "mobile.app"),
    ),
    (
        "campus",
        "hostel.night_roll_call",
        "Night roll call",
        "roll-call attendance",
        False,
        "standard",
        ("hostel.core",),
    ),
    ("campus", "hostel.room_change", "Room change", "change requests", False, "standard", ("hostel.core",)),
    ("campus", "hostel.visitors", "Visitors", "visitor log", False, "standard", ("hostel.core",)),
    (
        "campus",
        "hostel.complaints",
        "Complaints",
        "complaints → service desk",
        False,
        "standard",
        ("facilities.service_desk",),
    ),
    (
        "campus",
        "hostel.discipline",
        "Hostel discipline",
        "disciplinary records & fines",
        False,
        "standard",
        ("hostel.core",),
    ),
    ("campus", "hostel.staff_quarters", "Staff quarters", "quarters allocation", False, "standard", ("hr.staff",)),
    ("platform", "portals.warden", "Warden portal", "warden/gate", False, "standard", ("hostel.core",)),
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
