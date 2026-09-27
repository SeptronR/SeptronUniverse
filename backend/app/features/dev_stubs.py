"""Feature keys behind the development-only stub routes of Phase 02 (``app/api/v1/endpoints/dev.py``).

``GET /hostels`` {hostel.core} and ``POST /students`` {students.core} exist only while ``APP_ENV=development`` so the
Phase 02 verification (§02.11 steps 9 and 14) can prove the feature gate and the seat-limit entitlement before the real
modules ship. **Phase 07 (students) and Phase 20 (hostel) move these registrations into their own
``app/features/<module>.py`` and delete the stub routes.**
"""

from app.core.features import register_feature

register_feature(
    key="students.core",
    group="students",
    name="Student records",
    description="student master, enrolments, term records",
    default_enabled=True,
    min_plan_tier="starter",
)
register_feature(
    key="hostel.core",
    group="campus",
    name="Hostel",
    description="hostels, rooms, allocations",
    default_enabled=False,
    min_plan_tier="standard",
)
