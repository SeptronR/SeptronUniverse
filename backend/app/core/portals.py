"""Portal registry — Prompts/39 §39.6 ``portal_service`` rule 1 / 2 (persona information architecture).

``register_portal(persona, tabs=…, more=…, home_widgets=…)`` declares a persona shell; every entry carries an
optional ``feature`` / ``permission`` so entries whose feature is off (or whose permission the user lacks) vanish
from ``GET /portal/config`` and are listed in ``features_missing``. Routes are the web paths of the existing module
pages (Phases 07–38); the Flutter shell (``/portal/config`` too) maps the same keys onto its screens
(docs/Mobile_App_UI_Structure.md §3). Labels are i18n keys of the ``portal`` namespace (``frontend/public/locales``).
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PortalEntry:
    key: str
    route: str
    icon: str
    feature: str | None = None
    permission: str | None = None  # "module:action"

    @property
    def label_key(self) -> str:
        return f"portal.nav.{self.key}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label_key": self.label_key,
            "route": self.route,
            "icon": self.icon,
            "feature": self.feature,
            "permission": self.permission,
        }


@dataclass(frozen=True)
class PortalDef:
    persona: str
    tabs: tuple[PortalEntry, ...]
    more: tuple[PortalEntry, ...] = ()
    home_widgets: tuple[str, ...] = ()
    unified: tuple[str, ...] = field(default=("requests", "documents", "payments", "calendar", "timeline"))


PORTALS: dict[str, PortalDef] = {}


def register_portal(
    persona: str,
    *,
    tabs: list[PortalEntry],
    more: list[PortalEntry] | None = None,
    home_widgets: list[str] | None = None,
    unified: tuple[str, ...] | None = None,
) -> PortalDef:
    assert persona not in PORTALS, f"duplicate portal {persona}"
    d = PortalDef(
        persona=persona,
        tabs=tuple(tabs),
        more=tuple(more or ()),
        home_widgets=tuple(home_widgets or ()),
        **({"unified": unified} if unified is not None else {}),
    )
    PORTALS[persona] = d
    return d


E = PortalEntry


def _unified(prefix: str, *, payments: bool = True, approvals: bool = False) -> list[PortalEntry]:
    out = [
        E("requests", f"{prefix}/requests", "inbox"),
        E("documents", f"{prefix}/documents", "file-text", "documents.templates"),
    ]
    if payments:
        out.append(E("payments", f"{prefix}/payments", "wallet", "fees.core"))
    if approvals:
        out.append(E("approvals", f"{prefix}/approvals", "check-square", "workflow.engine"))
    return out + [
        E("calendar", f"{prefix}/calendar", "calendar"),
        E("timeline", f"{prefix}/timeline", "history"),
        E("notifications", f"{prefix}/notifications", "bell"),
        E("profile", f"{prefix}/profile", "user"),
    ]


register_portal(
    "student",
    tabs=[
        E("home", "/student", "home"),
        E("academics", "/student/timetable", "book-open", "timetable.core"),
        E("exams", "/student/exams", "clipboard-list", "exams.sessions"),
        E("fees", "/student/fees", "indian-rupee", "fees.core"),
        E("more", "/student/more", "grid"),
    ],
    more=[
        E("attendance", "/student/attendance", "calendar-check", "attendance.core"),
        E("registration", "/student/registration", "list-checks", "registration.core"),
        E("marks", "/student/marks", "bar-chart", "assessment.internal_marks"),
        E("results", "/student/results", "award", "results.publication_portal"),
        E("reval", "/student/exams/reval", "rotate-ccw", "results.revaluation"),
        E("transcripts", "/student/transcripts", "scroll", "results.transcripts"),
        E("degree", "/student/degree", "graduation-cap", "degrees.eligibility"),
        E("hostel", "/student/hostel", "bed", "hostel.core"),
        E("library", "/student/library", "library", "library.core"),
        E("transport", "/student/transport", "bus", "transport.core"),
        E("placement", "/student/placement", "briefcase", "placement.core"),
        E("mentor", "/student/mentor", "users", "mentoring.core"),
        E("surveys", "/student/surveys", "message-square", "surveys.core"),
        E("grievances", "/student/grievances", "alert-circle", "grievances.core"),
        E("clubs", "/student/clubs", "star", "clubs.core"),
        E("id_card", "/student/id-card", "id-card", "students.id_cards"),
        E("credit_transfers", "/student/credit-transfers", "repeat", "academics.credit_transfer_mooc"),
        E("undertakings", "/student/undertakings", "file-signature", "students.undertakings"),
        *_unified("/student"),
    ],
    home_widgets=["timetable_today", "attendance_summary", "dues", "results_latest", "notices", "requests_open"],
)
register_portal(
    "parent",
    tabs=[
        E("home", "/parent", "home"),
        E("academics", "/parent/attendance", "book-open", "attendance.core"),
        E("fees", "/parent/fees", "indian-rupee", "fees.core"),
        E("more", "/parent/more", "grid"),
    ],
    more=[
        E("timetable", "/parent/timetable", "calendar", "timetable.core"),
        E("hostel", "/parent/hostel", "bed", "hostel.core"),
        E("transport", "/parent/transport", "bus", "transport.core"),
        E("support", "/parent/support", "users", "mentoring.core"),
        E("library", "/parent/library", "library", "library.core"),
        E("placement", "/parent/placement", "briefcase", "placement.core"),
        E("notices", "/parent/notifications", "megaphone", "comms.announcements"),
        *_unified("/parent"),
    ],
    home_widgets=["ward_attendance", "ward_dues", "ward_results", "notices"],
)
register_portal(
    "faculty",
    tabs=[
        E("home", "/faculty", "home"),
        E("attendance", "/faculty/attendance", "calendar-check", "attendance.core"),
        E("marks", "/faculty/offerings", "bar-chart", "assessment.internal_marks"),
        E("courses", "/faculty/offerings", "book-open"),
        E("more", "/faculty/more", "grid"),
    ],
    more=[
        E("timetable", "/faculty/timetable", "calendar", "timetable.core"),
        E("mentees", "/faculty/mentees", "users", "mentoring.core"),
        E("duties", "/faculty/duties", "shield", "exams.invigilation"),
        E("qp", "/faculty/qp", "file-question", "exams.qp_management"),
        E("evaluation", "/faculty/evaluation", "check-circle", "exams.coding_dummy"),
        E("projects", "/faculty/projects", "folder", "assessment.projects"),
        E("question_bank", "/faculty/question-bank", "database", "lms.question_bank"),
        E("research", "/faculty/research", "flask", "research.publications"),
        E("scholars", "/faculty/scholars", "graduation-cap", "phd.core"),
        E("surveys", "/faculty/surveys", "message-square", "surveys.core"),
        E("library", "/faculty/library", "library", "library.core"),
        E("accreditation", "/faculty/accreditation", "badge-check", "accreditation.iqac_cycles"),
        E("internships", "/faculty/internships", "briefcase", "placement.internships"),
        *_unified("/faculty", payments=False, approvals=True),
    ],
    home_widgets=["classes_today", "attendance_pending", "marks_pending", "approvals_pending", "notices"],
)
register_portal(
    "alumni",
    tabs=[
        E("home", "/alumni", "home", "alumni.portal"),
        E("directory", "/alumni/directory", "users", "alumni.portal"),
        E("events", "/alumni/events", "calendar", "alumni.core"),
        E("give", "/alumni/give", "heart", "alumni.fundraising"),
        E("profile", "/alumni/profile", "user", "alumni.portal"),
    ],
    more=[E("jobs", "/alumni/jobs", "briefcase", "alumni.jobs_board"), *_unified("/alumni")],
    home_widgets=["events_upcoming", "jobs_latest", "notices"],
)
register_portal(
    "warden",
    tabs=[
        E("home", "/warden", "home"),
        E("outpasses", "/warden/outpasses", "log-out", "hostel.leave_outpass"),
        E("residents", "/warden/residents", "users", "hostel.core"),
        E("mess", "/warden/mess", "utensils", "hostel.mess"),
        E("more", "/warden/more", "grid"),
    ],
    more=[
        E("visitors", "/warden/visitors", "user-check", "hostel.visitors"),
        E("gate", "/warden/gate", "scan", "hostel.gate_qr"),
        *_unified("/warden", payments=False),
    ],
    home_widgets=["outpasses_pending", "occupancy", "complaints_open", "notices"],
)
register_portal(
    "gate",
    tabs=[
        E("gate_scan", "/warden/gate", "scan", "hostel.gate_qr"),
        E("today", "/warden/gate/today", "list"),
        E("settings", "/warden/gate/settings", "settings"),
    ],
    unified=(),
)
register_portal(
    "evaluator",
    tabs=[
        E("bundles", "/evaluator", "package", "exams.external_examiners"),
        E("entry", "/evaluator/entry", "edit", "exams.coding_dummy"),
        E("profile", "/evaluator/profile", "user"),
    ],
    more=[E("documents", "/evaluator/documents", "file-text", "documents.templates")],
    unified=("documents",),
)
register_portal(
    "scholar",
    tabs=[
        E("home", "/scholar", "home", "phd.scholar_portal"),
        E("progress", "/scholar/progress", "trending-up", "phd.progress_reports"),
        E("thesis", "/scholar/thesis", "book", "phd.thesis_plagiarism"),
        E("fellowship", "/scholar/fellowship", "indian-rupee", "phd.fellowships"),
        E("more", "/scholar/more", "grid"),
    ],
    more=[
        E("coursework", "/scholar/coursework", "book-open", "phd.coursework"),
        E("phd_requests", "/scholar/requests", "inbox", "phd.extensions_guide_change"),
        *_unified("/scholar"),
    ],
    home_widgets=["progress_due", "fellowship", "notices"],
)
register_portal(
    "applicant",
    tabs=[
        E("apply", "/apply", "file-plus", "admissions.online_application"),
        E("status", "/apply/status", "activity"),
        E("allotment", "/apply/allotment", "award", "admissions.counselling_allotment"),
        E("payments", "/apply/payments", "wallet", "fees.core"),
        E("profile", "/apply/profile", "user"),
    ],
    unified=("payments",),
)
register_portal(
    "recruiter",
    tabs=[
        E("drives", "/recruiter/drives", "briefcase", "placement.recruiter_portal"),
        E("applicants", "/recruiter/applicants", "users", "placement.recruiter_portal"),
        E("rounds", "/recruiter/rounds", "list-ordered", "placement.recruiter_portal"),
        E("offers", "/recruiter/offers", "award", "placement.recruiter_portal"),
        E("profile", "/recruiter/profile", "user"),
    ],
    unified=("requests",),
)
register_portal(
    "driver",
    tabs=[
        E("home", "/driver", "home", "transport.core"),
        E("route", "/driver/route", "map", "transport.core"),
        E("settings", "/driver/settings", "settings"),
    ],
    unified=(),
)
