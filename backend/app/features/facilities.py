"""Feature keys registered by Phase 25 (docs/Feature_Flags.md §2.13 events / facilities and the calendar keys).

Dependencies on keys of other phases (``documents.templates``, ``mentoring.counselling``, ``mobile.app``,
``integrations.payments``) are listed as documented.
"""

from app.core.features import register_feature

_KEYS: tuple[tuple[str, str, str, str, bool, str, tuple[str, ...]], ...] = (
    ("calendar", "calendar.core", "Calendar", "academic calendar, events", True, "starter", ()),
    ("calendar", "calendar.ical", "iCal export", "institution feeds", True, "starter", ("calendar.core",)),
    (
        "calendar",
        "calendar.personal_feed",
        "Personal iCal feed",
        "per-user token feeds",
        True,
        "standard",
        ("calendar.core",),
    ),
    ("campus", "events.core", "Events", "events, registrations", True, "standard", ()),
    (
        "campus",
        "events.certificates",
        "Event certificates",
        "participation certificates",
        True,
        "standard",
        ("documents.templates",),
    ),
    ("campus", "facilities.room_booking", "Room booking", "venue booking", True, "standard", ("timetable.rooms",)),
    (
        "campus",
        "facilities.equipment_booking",
        "Equipment booking",
        "asset booking",
        False,
        "standard",
        ("inventory.assets",),
    ),
    ("campus", "facilities.service_desk", "Service desk", "maintenance/IT tickets", True, "standard", ()),
    (
        "campus",
        "facilities.lost_found",
        "Lost & found",
        "register",
        False,
        "standard",
        ("facilities.service_desk",),
    ),
    ("campus", "facilities.amc", "AMC contracts", "AMC register", False, "standard", ("inventory.assets",)),
    ("campus", "facilities.visitor_gate", "Visitor & gate", "campus passes", False, "standard", ()),
    (
        "campus",
        "facilities.emergency_sos",
        "Emergency / SOS",
        "SOS alerts, broadcast",
        False,
        "standard",
        ("mobile.app", "comms.push"),
    ),
    ("campus", "facilities.health_centre", "Health centre", "visits, insurance", False, "standard", ()),
    (
        "campus",
        "facilities.counselling_appointments",
        "Counselling appointments",
        "slots & bookings",
        False,
        "standard",
        ("mentoring.counselling",),
    ),
    ("campus", "facilities.sports", "Sports", "teams, events, participation", False, "standard", ()),
    (
        "campus",
        "facilities.canteen_wallet",
        "Canteen & wallet",
        "prepaid wallet",
        False,
        "professional",
        ("integrations.payments",),
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
