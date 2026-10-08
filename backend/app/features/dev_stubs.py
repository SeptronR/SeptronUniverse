"""Feature key behind the development-only stub route of Phase 02 (``app/api/v1/endpoints/module_stubs.py``).

``GET /hostels`` {hostel.core} exists only while ``APP_ENV=development`` so the Phase 02 verification (§02.11 step 9)
can prove the feature gate before the real module ships. **Phase 20 (hostel) moves this registration into
``app/features/hostel.py`` and deletes the stub route.** Phase 07 already moved ``students.core`` into
``app/features/students.py`` and replaced the ``POST /students`` stub with the real student service (the seat-limit
check of §02.11 step 14 now runs inside ``StudentService.create``).
"""

from app.core.features import register_feature

register_feature(
    key="hostel.core",
    group="campus",
    name="Hostel",
    description="hostels, rooms, allocations",
    default_enabled=False,
    min_plan_tier="standard",
)
