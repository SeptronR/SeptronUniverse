"""Portals, PWA, notification centre & guided help — Prompts/39 §39.3 enums and defaults.

``Persona`` is the portal a user lands in (resolved from role slugs by priority; the last match wins); the
notification categories are the Phase 04 catalogue's (``app/core/notifications/catalogue.py:CATEGORIES``, extended
by Phase 39 with ``events`` / ``system``); ``POLICY_LOCKED_IN_APP`` categories can never switch the in-app channel off.
"""

from typing import Literal

Persona = Literal[
    "student",
    "parent",
    "faculty",
    "alumni",
    "warden",
    "gate",
    "evaluator",
    "scholar",
    "applicant",
    "recruiter",
    "driver",
]
PERSONAS: tuple[str, ...] = (
    "student",
    "parent",
    "faculty",
    "alumni",
    "warden",
    "gate",
    "evaluator",
    "scholar",
    "applicant",
    "recruiter",
    "driver",
)

# role slug → persona (docs/User_Flows.md; Phase 02 PORTAL_HOME)
ROLE_PERSONA: dict[str, str] = {
    "student": "student",
    "learner": "student",
    "parent": "parent",
    "alumni": "alumni",
    "applicant": "applicant",
    "recruiter": "recruiter",
    "driver": "driver",
    "external_examiner": "evaluator",
    "research_scholar": "scholar",
    "hostel_gate_staff": "gate",
    "hostel_warden": "warden",
    "faculty": "faculty",
    "guest_faculty": "faculty",
}
# §39.6 rule 1: student < parent < alumni < applicant < recruiter < driver < evaluator < scholar < gate < warden < faculty
PERSONA_PRIORITY: tuple[str, ...] = (
    "student",
    "parent",
    "alumni",
    "applicant",
    "recruiter",
    "driver",
    "evaluator",
    "scholar",
    "gate",
    "warden",
    "faculty",
)
PERSONA_FEATURE: dict[str, str] = {
    "student": "portals.student",
    "parent": "portals.parent",
    "faculty": "portals.faculty",
    "alumni": "portals.alumni",
    "warden": "portals.warden",
    "gate": "portals.warden",
    "evaluator": "portals.evaluator",
    "scholar": "portals.scholar",
    "recruiter": "portals.recruiter",
    "applicant": "admissions.online_application",
    "driver": "transport.core",
}
PERSONA_HOME: dict[str, str] = {
    "student": "/student",
    "parent": "/parent",
    "faculty": "/faculty",
    "alumni": "/alumni",
    "warden": "/warden",
    "gate": "/warden/gate",
    "evaluator": "/evaluator",
    "scholar": "/scholar",
    "applicant": "/apply",
    "recruiter": "/recruiter",
    "driver": "/driver",
}

Digest = Literal["none", "daily", "weekly"]
DIGESTS: tuple[str, ...] = ("none", "daily", "weekly")
# §39.6 notification centre: exam / fee / security categories cannot disable in-app
POLICY_LOCKED_IN_APP: frozenset[str] = frozenset({"exams", "fees", "security", "emergency"})
SNOOZE_MAX_HOURS = 168

# §39.6 My requests: status normalisation
REQUEST_STATUSES: tuple[str, ...] = (
    "draft",
    "pending",
    "in_progress",
    "approved",
    "rejected",
    "completed",
    "cancelled",
)
_STATUS_MAP: dict[str, str] = {
    "draft": "draft",
    "submitted": "pending",
    "pending": "pending",
    "requested": "pending",
    "open": "pending",
    "new": "pending",
    "applied": "pending",
    "registered": "pending",
    "waitlisted": "pending",
    "fee_pending": "pending",
    "payment_pending": "pending",
    "under_review": "in_progress",
    "in_progress": "in_progress",
    "processing": "in_progress",
    "assigned": "in_progress",
    "verified": "in_progress",
    "escalated": "in_progress",
    "on_hold": "in_progress",
    "scheduled": "in_progress",
    "ready": "approved",
    "approved": "approved",
    "sanctioned": "approved",
    "accepted": "approved",
    "confirmed": "approved",
    "booked": "approved",
    "out": "approved",
    "rejected": "rejected",
    "declined": "rejected",
    "denied": "rejected",
    "completed": "completed",
    "closed": "completed",
    "resolved": "completed",
    "issued": "completed",
    "disbursed": "completed",
    "cleared": "completed",
    "returned": "completed",
    "received": "completed",
    "fulfilled": "completed",
    "attended": "completed",
    "cancelled": "cancelled",
    "withdrawn": "cancelled",
    "expired": "cancelled",
    "lapsed": "cancelled",
}


def normalise_status(raw: str | None) -> str:
    return _STATUS_MAP.get((raw or "").lower(), "in_progress" if raw else "pending")


# §39.2 mobile app ids for the association files (platform_settings['mobile.app_ids'])
DEFAULT_APP_IDS: dict[str, object] = {
    "android_package": "in.septron.universe",
    "android_sha256": [],
    "ios_team_id": "",
    "ios_bundle_id": "in.septron.universe",
    "paths": ["/verify/*", "/apply/*", "/student/*", "/parent/*", "/faculty/*", "/notifications/*"],
}
DEFAULT_CACHE_TTL: dict[str, int] = {
    "timetable": 86400,
    "attendance": 21600,
    "dues": 3600,
    "results": 86400,
    "notices": 3600,
}
# runtime cache routes of the service worker: API prefix → TTL key
SWR_ROUTES: dict[str, str] = {
    "/api/v1/timetables/me": "timetable",
    "/api/v1/attendance/summary": "attendance",
    "/api/v1/fees/invoices/me": "dues",
    "/api/v1/results/me": "results",
    "/api/v1/announcements": "notices",
    "/api/v1/portal/config": "notices",
    "/api/v1/dashboard": "notices",
}
ICON_SIZES: tuple[int, ...] = (192, 512)
FEEDBACK_RATE = (10, 600)  # 10 submissions per 10 minutes per user
