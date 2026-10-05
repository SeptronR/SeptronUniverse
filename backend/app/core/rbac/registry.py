"""Permission catalogue, role templates and scope rules — Prompts/02 §02.2, §02.6; docs/Roles_and_Permissions.md.

* ``PERMISSIONS`` mirrors ``Database_Schema.sql`` §36.1 exactly (modules × standard actions + bespoke actions); the
  Phase 02 seed revision and ``seed_platform.py`` upsert it (``ON CONFLICT DO NOTHING``) and the in-process
  verification asserts the two sets are identical.
* ``ROLE_META`` mirrors §36.2 (name, slug, is_system, default scope, portal) for the 51 platform role templates.
* ``ROLE_TEMPLATES`` encodes docs/Roles_and_Permissions.md §3 as flat ``module:action`` grants per slug; every string
  is validated against the catalogue at import time. ``module:manage`` is the wildcard ``Principal.has()`` honours —
  except ``view_pii``, which must always be granted explicitly (docs/Authorization_and_Visibility.md §1).
  ``institution_admin`` therefore receives every ``exams:*`` action individually (no ``exams:manage``) so
  ``exams:decode`` stays a deliberate, separate grant.
* ``allowed_scope_types(role_slug)`` implements docs/Roles_and_Permissions.md §4 for assignment validation.
"""

from dataclasses import dataclass

# ---- §36.1 catalogue ---------------------------------------------------------------------------------------------
MODULES: tuple[str, ...] = (
    "dashboard",
    "institutions",
    "colleges",
    "faculties",
    "departments",
    "users",
    "roles",
    "features",
    "sessions",
    "programs",
    "regulations",
    "curriculum",
    "courses",
    "batches",
    "offerings",
    "registration",
    "timetable",
    "attendance",
    "marks",
    "projects",
    "exams",
    "results",
    "degrees",
    "obe",
    "lms",
    "admissions",
    "students",
    "credit_transfers",
    "faculty",
    "hr",
    "recruitment",
    "leaves",
    "payroll",
    "research",
    "phd",
    "fees",
    "scholarships",
    "no_dues",
    "hostel",
    "library",
    "transport",
    "inventory",
    "procurement",
    "accounting",
    "events",
    "facilities",
    "health",
    "sports",
    "placement",
    "alumni",
    "fundraising",
    "mentoring",
    "grievances",
    "discipline",
    "surveys",
    "clubs",
    "accreditation",
    "governance",
    "legal",
    "rti",
    "efile",
    "affiliation",
    "communication",
    "calendar",
    "templates",
    "certificates",
    "reports",
    "analytics",
    "audit_logs",
    "settings",
    "integrations",
    "jobs",
    "website",
)

STANDARD_ACTIONS: tuple[str, ...] = (
    "view",
    "view_all",
    "create",
    "update",
    "delete",
    "approve",
    "publish",
    "export",
    "manage",
    "view_pii",
)

# (module, action, description) — copied from Database_Schema.sql §36.1 (never retyped from memory)
BESPOKE_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("users", "reset_password", "Reset user passwords"),
    ("users", "impersonate", "Impersonate users (platform)"),
    ("roles", "assign", "Assign roles"),
    ("roles", "clone", "Clone roles"),
    ("features", "institution_toggle", "Institution-level feature switch"),
    ("sessions", "rollover", "Academic year rollover"),
    ("sessions", "close", "Close term"),
    ("sessions", "lock", "Lock term"),
    ("regulations", "clone", "Clone regulation"),
    ("batches", "promote", "Promote batch"),
    ("offerings", "allocate_faculty", "Allocate faculty"),
    ("offerings", "bulk_create", "Bulk create offerings"),
    ("registration", "self", "Self registration"),
    ("registration", "allocate", "Run elective allocation"),
    ("registration", "override", "Override registration rules"),
    ("registration", "bulk", "Bulk register"),
    ("timetable", "generate", "Auto-generate timetable"),
    ("timetable", "substitute", "Manage substitutions"),
    ("attendance", "mark", "Mark attendance"),
    ("attendance", "self", "View own attendance"),
    ("attendance", "condone", "Condonation"),
    ("attendance", "edit_finalized", "Edit finalized attendance"),
    ("attendance", "staff_view_all", "View all staff attendance"),
    ("attendance", "staff_self", "View own staff attendance"),
    ("attendance", "device_manage", "Manage attendance devices"),
    ("marks", "enter", "Enter marks"),
    ("marks", "verify", "Verify marks"),
    ("marks", "lock", "Lock marks"),
    ("marks", "correct", "Correct locked marks"),
    ("projects", "guide", "Guide projects"),
    ("projects", "review", "Review projects"),
    ("exams", "configure", "Configure exams"),
    ("exams", "self", "Student exam self-service"),
    ("exams", "eligibility", "Apply eligibility"),
    ("exams", "hall_tickets", "Generate hall tickets"),
    ("exams", "seating", "Seating plans"),
    ("exams", "invigilation", "Invigilation"),
    ("exams", "conduct", "Conduct exams"),
    ("exams", "qp", "Question paper management"),
    ("exams", "qp_print", "Print question papers"),
    ("exams", "code", "Code scripts"),
    ("exams", "custody", "Script custody"),
    ("exams", "valuation_assign", "Assign valuation"),
    ("exams", "evaluate", "Evaluate scripts"),
    ("exams", "moderate", "Moderation"),
    ("exams", "decode", "Decode dummy numbers"),
    ("exams", "reval", "Revaluation processing"),
    ("exams", "malpractice", "Malpractice cases"),
    ("results", "compute", "Compute results"),
    ("results", "verify", "Verify results"),
    ("results", "self", "View own results"),
    ("results", "transcript", "Transcripts"),
    ("results", "legacy_import", "Legacy result import"),
    ("degrees", "award", "Award degrees"),
    ("degrees", "issue", "Issue certificates"),
    ("degrees", "convocation_manage", "Manage convocation"),
    ("obe", "configure", "Configure attainment"),
    ("obe", "compute", "Compute attainment"),
    ("lms", "grade", "Grade LMS work"),
    ("admissions", "verify", "Verify documents"),
    ("admissions", "merit", "Merit lists"),
    ("admissions", "allot", "Seat allotment"),
    ("admissions", "import", "Import applicants"),
    ("admissions", "admit", "Admit applicants"),
    ("admissions", "refund", "Admission refunds"),
    ("students", "holds", "Manage holds"),
    ("students", "standing", "Manage academic standing"),
    ("students", "exit", "NEP exit"),
    ("students", "transfer", "Transfers"),
    ("students", "undertakings", "Undertakings"),
    ("students", "id_card", "ID cards"),
    ("students", "bulk_import", "Bulk import"),
    ("students", "self", "Student self-service"),
    ("credit_transfers", "verify", "Verify credit transfers"),
    ("faculty", "research", "Research profile"),
    ("faculty", "workload_manage", "Workload management"),
    ("hr", "service_book", "Service book"),
    ("hr", "recruitment", "Recruitment"),
    ("hr", "appraisal", "Appraisals"),
    ("hr", "cas", "CAS"),
    ("hr", "guest_manage", "Guest faculty"),
    ("leaves", "self", "Own leaves"),
    ("leaves", "encash", "Leave encashment"),
    ("payroll", "self", "Own payslips"),
    ("payroll", "generate", "Generate payroll"),
    ("payroll", "mark_paid", "Mark paid"),
    ("payroll", "statutory", "Statutory config"),
    ("research", "ethics", "Ethics approvals"),
    ("research", "incentives", "Research incentives"),
    ("research", "mous", "MoUs"),
    ("research", "incubation", "Incubation"),
    ("phd", "self", "Scholar self-service"),
    ("phd", "guide", "Guide actions"),
    ("phd", "dc", "Doctoral committee"),
    ("phd", "examine", "Thesis examination"),
    ("phd", "fellowship", "Fellowships"),
    ("phd", "etd", "ETD upload"),
    ("fees", "self", "Own fees"),
    ("fees", "collect", "Collect fees"),
    ("fees", "refund", "Refunds"),
    ("fees", "cancel_receipt", "Cancel receipts"),
    ("fees", "reconcile", "Reconciliation"),
    ("fees", "structure_manage", "Fee structures"),
    ("fees", "concession", "Concessions"),
    ("scholarships", "verify", "Verify scholarship"),
    ("scholarships", "sanction", "Sanction scholarship"),
    ("scholarships", "disburse", "Disburse scholarship"),
    ("no_dues", "request", "Request no-dues"),
    ("hostel", "self", "Own hostel"),
    ("hostel", "allot", "Allot hostel"),
    ("hostel", "gate", "Gate scanning"),
    ("hostel", "warden", "Warden operations"),
    ("hostel", "roll_call", "Roll call"),
    ("hostel", "mess_manage", "Mess management"),
    ("hostel", "discipline", "Hostel discipline"),
    ("library", "self", "Own library"),
    ("library", "circulate", "Circulation"),
    ("library", "fines", "Library fines"),
    ("transport", "gps_ingest", "GPS ingest"),
    ("transport", "driver", "Driver app"),
    ("inventory", "indent", "Raise indent"),
    ("inventory", "approve_indent", "Approve indent"),
    ("inventory", "receive", "Receive goods"),
    ("inventory", "issue", "Issue stock"),
    ("inventory", "asset_audit", "Asset audit"),
    ("procurement", "quote", "Quotations"),
    ("procurement", "po_approve", "Approve PO"),
    ("procurement", "bill_approve", "Approve vendor bills"),
    ("accounting", "post", "Post entries"),
    ("accounting", "reconcile", "Bank reconciliation"),
    ("events", "organise", "Organise events"),
    ("events", "certify", "Event certificates"),
    ("facilities", "book", "Book facilities"),
    ("facilities", "approve_booking", "Approve bookings"),
    ("facilities", "service_assign", "Assign service requests"),
    ("health", "record", "Health records"),
    ("placement", "self", "Own placement"),
    ("placement", "drive_manage", "Manage drives"),
    ("placement", "override_eligibility", "Override eligibility"),
    ("placement", "offer_manage", "Manage offers"),
    ("placement", "recruiter", "Recruiter portal"),
    ("alumni", "self", "Own alumni profile"),
    ("alumni", "verify", "Verify alumni"),
    ("alumni", "campaign", "Campaigns"),
    ("fundraising", "receipt", "Donation receipts"),
    ("mentoring", "self", "Own mentoring"),
    ("mentoring", "wards", "Wards mentoring"),
    ("mentoring", "refer", "Counselling referrals"),
    ("grievances", "triage", "Triage grievances"),
    ("grievances", "resolve", "Resolve grievances"),
    ("grievances", "escalate", "Escalate grievances"),
    ("grievances", "committee", "Committee routing"),
    ("discipline", "decide", "Decide cases"),
    ("discipline", "appeal", "Handle appeals"),
    ("surveys", "respond", "Respond to surveys"),
    ("surveys", "analyse", "Analyse surveys"),
    ("clubs", "verify_hours", "Verify activity hours"),
    ("accreditation", "compute", "Compute metrics"),
    ("accreditation", "override", "Override metrics"),
    ("accreditation", "submit", "Submit compliance"),
    ("accreditation", "evidence", "Manage evidence"),
    ("governance", "committees", "Committees"),
    ("governance", "minutes", "Minutes"),
    ("governance", "resolutions", "Resolutions"),
    ("affiliation", "apply", "Apply for affiliation"),
    ("affiliation", "inspect", "Inspections"),
    ("affiliation", "decide", "Decide affiliation"),
    ("affiliation", "submit", "Submit college data"),
    ("affiliation", "verify_submission", "Verify submissions"),
    ("communication", "send", "Send messages"),
    ("communication", "bulk", "Bulk campaigns"),
    ("communication", "template_manage", "Manage templates"),
    ("communication", "emergency", "Emergency broadcast"),
    ("templates", "render", "Render templates"),
    ("certificates", "self", "Request own certificates"),
    ("certificates", "request_approve", "Approve certificate requests"),
    ("certificates", "issue", "Issue certificates"),
    ("reports", "run", "Run reports"),
    ("reports", "schedule", "Schedule reports"),
    ("reports", "statutory", "Statutory reports"),
    ("audit_logs", "verify_chain", "Verify audit chain"),
    ("integrations", "connect", "Manage connections"),
    ("integrations", "api_keys", "API keys"),
    ("integrations", "webhooks", "Webhooks"),
    ("integrations", "import", "Data imports"),
    ("jobs", "cancel", "Cancel jobs"),
)

PLATFORM_ONLY_PERMISSIONS: frozenset[str] = frozenset({"users:impersonate", "features:manage"})


def _catalogue() -> dict[str, str]:
    perms: dict[str, str] = {}
    for m in MODULES:
        for a in STANDARD_ACTIONS:
            perms[f"{m}:{a}"] = f"{m}:{a}"
    for m, a, d in BESPOKE_ACTIONS:
        perms[f"{m}:{a}"] = d
    return perms


PERMISSIONS: dict[str, str] = _catalogue()  # "module:action" → description
ACTIONS_BY_MODULE: dict[str, list[str]] = {m: list(STANDARD_ACTIONS) for m in MODULES}
for _m, _a, _ in BESPOKE_ACTIONS:
    ACTIONS_BY_MODULE[_m].append(_a)


# ---- §36.2 role templates ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RoleMeta:
    name: str
    slug: str
    is_system: bool
    default_scope_type: str
    portal: str


ROLE_META: tuple[RoleMeta, ...] = tuple(
    RoleMeta(n, s, True, sc, p)
    for n, s, sc, p in (
        ("Super Admin", "super_admin", "institution", "super_admin"),
        ("Support Agent", "support_agent", "institution", "super_admin"),
        ("Institution Admin", "institution_admin", "institution", "admin"),
        ("Vice Chancellor / Principal", "vice_chancellor", "institution", "admin"),
        ("Registrar", "registrar", "institution", "admin"),
        ("Controller of Examinations", "controller_of_examinations", "institution", "admin"),
        ("Exam Cell", "exam_cell", "institution", "admin"),
        ("Exam Decoder", "exam_decoder", "institution", "admin"),
        ("Dean", "dean", "faculty", "admin"),
        ("Head of Department", "hod", "department", "admin"),
        ("Class Advisor", "class_advisor", "offering", "admin"),
        ("Faculty", "faculty", "self", "faculty"),
        ("Guest Faculty", "guest_faculty", "self", "faculty"),
        ("External Examiner", "external_examiner", "self", "evaluator"),
        ("Invigilator", "invigilator", "self", "faculty"),
        ("Research Guide", "research_guide", "self", "faculty"),
        ("Research Scholar", "research_scholar", "self", "scholar"),
        ("Research Cell", "research_cell", "institution", "admin"),
        ("IQAC Coordinator", "iqac_coordinator", "institution", "admin"),
        ("OBE Coordinator", "obe_coordinator", "institution", "admin"),
        ("Admissions Officer", "admissions_officer", "institution", "admin"),
        ("Accountant", "accountant", "institution", "admin"),
        ("HR Officer", "hr_officer", "institution", "admin"),
        ("Placement Officer", "placement_officer", "institution", "admin"),
        ("Alumni Coordinator", "alumni_coordinator", "institution", "admin"),
        ("Hostel Warden", "hostel_warden", "self", "warden"),
        ("Hostel Gate Staff", "hostel_gate_staff", "self", "warden"),
        ("Librarian", "librarian", "institution", "admin"),
        ("Transport Manager", "transport_manager", "institution", "admin"),
        ("Inventory Manager", "inventory_manager", "institution", "admin"),
        ("Estate Officer", "estate_officer", "institution", "admin"),
        ("Security Officer", "security_officer", "institution", "admin"),
        ("Medical Officer", "medical_officer", "institution", "admin"),
        ("Sports Officer", "sports_officer", "institution", "admin"),
        ("Grievance Officer", "grievance_officer", "institution", "admin"),
        ("Discipline Committee", "discipline_committee", "institution", "admin"),
        ("Committee Secretary", "committee_secretary", "committee", "admin"),
        ("Legal Officer", "legal_officer", "institution", "admin"),
        ("Public Information Officer", "pio", "institution", "admin"),
        ("Receptionist", "receptionist", "institution", "admin"),
        ("Driver", "driver", "self", "driver"),
        ("Integration Admin", "integration_admin", "institution", "admin"),
        ("College Admin", "college_admin", "college", "admin"),
        ("College Exam Coordinator", "college_exam_coordinator", "college", "admin"),
        ("Auditor", "auditor", "institution", "admin"),
        ("Recruiter", "recruiter", "self", "recruiter"),
        ("Learner", "learner", "self", "student"),
        ("Student", "student", "self", "student"),
        ("Parent", "parent", "self", "parent"),
        ("Alumni", "alumni", "self", "alumni"),
        ("Applicant", "applicant", "self", "applicant"),
    )
)
ROLE_SLUGS: tuple[str, ...] = tuple(r.slug for r in ROLE_META)
PLATFORM_ROLES: frozenset[str] = frozenset({"super_admin", "support_agent"})

# Roles whose members must present a TOTP code when ``security.mfa`` is on (overridable per institution through
# ``institution_settings[security.mfa_required_roles]`` — Prompts/02 §02.6 rule 1).
MFA_REQUIRED_ROLES: tuple[str, ...] = (
    "super_admin",
    "controller_of_examinations",
    "exam_decoder",
    "registrar",
    "institution_admin",
    "accountant",
)

SCOPE_TYPES: tuple[str, ...] = (
    "institution",
    "college",
    "faculty",
    "department",
    "program",
    "offering",
    "self",
    "committee",
    "hostel",
)
# scope_type → table that must hold scope_id inside the institution (docs/Roles_and_Permissions.md §4)
SCOPE_TABLES: dict[str, str] = {
    "college": "colleges",
    "faculty": "faculties",
    "department": "departments",
    "program": "programs",
    "offering": "course_offerings",
    "committee": "committees",
    "hostel": "hostels",
}
# additional tables a scope id may name (Phase 05: ``class_advisor`` @offering is assigned to a batch *section* until
# Phase 09 course offerings exist; both share the ``offering`` scope type)
SCOPE_ALT_TABLES: dict[str, tuple[str, ...]] = {"offering": ("batch_sections",)}
# roles that may additionally be college-scoped although their template default is ``institution``
COLLEGE_SCOPABLE_ROLES: frozenset[str] = frozenset(
    {
        "exam_cell",
        "admissions_officer",
        "accountant",
        "librarian",
        "placement_officer",
        "inventory_manager",
        "receptionist",
    }
)


def allowed_scope_types(role_slug: str, default_scope_type: str) -> tuple[str, ...]:
    """Scope types an assignment of ``role_slug`` may carry (§4): unit-scoped roles are pinned to their unit."""
    if default_scope_type in {"college", "faculty", "department", "offering", "committee", "hostel", "program"}:
        return (default_scope_type,)
    if default_scope_type == "self":
        return ("self",)
    if role_slug in PLATFORM_ROLES:
        return ("institution",)
    if role_slug in COLLEGE_SCOPABLE_ROLES:
        return ("institution", "college")
    return ("institution", "college") if role_slug not in {"institution_admin"} else ("institution",)


# ---- docs/Roles_and_Permissions.md §3 — default grants per template --------------------------------------------
def P(module: str, *actions: str) -> set[str]:
    return {f"{module}:{a}" for a in actions}


def ALL(*actions: str, exclude: tuple[str, ...] = ()) -> set[str]:
    return {f"{m}:{a}" for m in MODULES if m not in exclude for a in actions}


def MODULE_ALL(module: str, exclude: tuple[str, ...] = ()) -> set[str]:
    """Every action of a module except ``manage`` (and ``exclude``) — used where the wildcard must not apply."""
    return {f"{module}:{a}" for a in ACTIONS_BY_MODULE[module] if a != "manage" and a not in exclude}


# Phase 03: ``institutions:view`` is granted to every role — institution, colleges, faculties, departments, academic
# years/terms and holidays are institution-wide readable by any authenticated member (Prompts/03 "Visibility rules")
COMMON: set[str] = P("dashboard", "view") | P("jobs", "view", "cancel") | P("institutions", "view")
ACADEMIC_READ: set[str] = (
    P("programs", "view")
    | P("regulations", "view")
    | P("curriculum", "view")
    | P("courses", "view")
    | P("batches", "view")
)
# staff self-service — always present where it makes sense (docs/Authorization_and_Visibility.md §4)
STAFF_SELF: set[str] = (
    COMMON
    | P("leaves", "self", "create", "view")
    | P("payroll", "self")
    | P("attendance", "staff_self")
    | P("hr", "view")
    # Phase 06: staff request encashment of their own encashable leave (gated by {hr.leave_encashment})
    | P("leaves", "encash")
    | P("calendar", "view")
    | P("communication", "view")
    | P("events", "view")
    | P("certificates", "self")
    | P("grievances", "create")
    | P("facilities", "book", "view")
    | P("surveys", "respond")
    | P("library", "self")
    | P("timetable", "view")
    | P("no_dues", "request")
    | P("settings", "view")
    # Phase 05: programmes, regulations, curricula, courses and batches are institution-wide readable by all staff
    | ACADEMIC_READ
)

FACULTY: set[str] = (
    STAFF_SELF
    | P("attendance", "mark", "self", "view")
    | P("marks", "enter", "view")
    | P("students", "view")
    | P("lms", "manage", "grade", "view")
    | P("projects", "guide", "review", "view")
    | P("research", "manage", "view")
    | P("mentoring", "manage", "view")
    | P("exams", "evaluate", "invigilation", "malpractice", "view")
    | P("surveys", "analyse", "view")
    | P("courses", "view")
    | P("offerings", "view")
    | P("curriculum", "view")
    | P("registration", "view")
    | P("faculty", "view", "research")
    | P("inventory", "indent", "view")
    | P("clubs", "view")
    | P("results", "view")
)

_INSTITUTION_ADMIN: set[str] = (
    ALL("manage", exclude=("features", "exams"))
    | P("features", "view", "institution_toggle")
    | MODULE_ALL("exams", exclude=("decode",))
    | COMMON
    | STAFF_SELF
)

_COLLEGE_ADMIN: set[str] = (
    ALL("manage", exclude=("features", "exams", "regulations", "results", "degrees", "institutions"))
    | MODULE_ALL("exams", exclude=("decode",))
    | MODULE_ALL("regulations", exclude=("approve",))
    | MODULE_ALL("results", exclude=("publish",))
    | MODULE_ALL("degrees", exclude=("award",))
    | P("institutions", "view")
    | COMMON
    | STAFF_SELF
)

STUDENT: set[str] = (
    COMMON
    | P("students", "self", "undertakings", "id_card", "view")
    | P("registration", "self")
    | P("attendance", "self")
    | P("marks", "view")
    | P("exams", "self")
    | P("results", "self")
    | P("fees", "self")
    | P("scholarships", "create", "view")
    | P("no_dues", "request")
    | P("hostel", "self")
    | P("library", "self")
    | P("placement", "self")
    | P("mentoring", "self")
    | P("surveys", "respond")
    | P("grievances", "create", "view")
    | P("clubs", "view")
    | P("certificates", "self")
    | P("credit_transfers", "create", "view")
    | P("events", "view")
    | P("alumni", "self")
    | P("timetable", "view")
    | P("lms", "view")
    | P("projects", "view")
    | P("calendar", "view")
    | P("communication", "view")
    | P("facilities", "book", "view")
    | P("transport", "view")
    | P("health", "view")
    | P("sports", "view")
)

# Phase 05 (Prompts/05 "Visibility rules"): edits are narrowed to the holder's units by the services
REGISTRAR_ACADEMICS: set[str] = (
    P("programs", "manage")
    | MODULE_ALL("regulations", exclude=("approve", "view_pii"))
    | P("curriculum", "manage")
    | P("courses", "manage")
    | P("batches", "manage")
)
HOD_ACADEMICS: set[str] = (
    P("courses", "create", "update", "export") | P("curriculum", "manage") | P("batches", "manage")
)
DEAN_ACADEMICS: set[str] = P("courses", "approve")  # dean @faculty approves the drafted courses of its departments
# Phase 06: dean @faculty approves the course-allocation proposals and reads the workload of its departments
DEAN_HR: set[str] = P("faculty", "workload_manage")
AUDITOR_HR: set[str] = P("attendance", "staff_view_all")

ROLE_TEMPLATES: dict[str, set[str]] = {
    "super_admin": {"*:*"},
    "support_agent": ALL("view", "view_all") | P("users", "impersonate") | COMMON,
    "institution_admin": _INSTITUTION_ADMIN,
    "vice_chancellor": ALL("view", "view_all")
    | P("leaves", "approve")
    | P("regulations", "approve")
    | P("degrees", "award")
    | P("governance", "manage")
    | P("grievances", "escalate")
    | P("results", "approve")
    | STAFF_SELF,
    "registrar": STAFF_SELF
    | P("students", "manage", "view_pii")
    | P("admissions", "manage")
    | P("credit_transfers", "approve", "view_all", "verify")
    | P("certificates", "manage", "issue")
    | P("templates", "render", "view")
    | P("results", "transcript", "view_all")
    | P("degrees", "award", "issue", "convocation_manage", "view_all")
    | P("affiliation", "manage")
    | P("sessions", "manage")
    | P("reports", "statutory", "run", "view")
    | P("hr", "view_all")
    | P("fees", "view_all")
    | P("hostel", "view_all")
    | P("users", "view_all", "create", "update", "reset_password")
    | P("roles", "view", "assign")
    | P("institutions", "view")
    | P("colleges", "view_all")
    | P("departments", "view_all")
    | P("faculties", "view_all")
    | P("programs", "view_all")
    | P("batches", "view_all")
    | P("attendance", "view_all")
    # Phase 05: the registrar owns the academic backbone (programmes, regulations short of approval, curricula)
    | REGISTRAR_ACADEMICS,
    "controller_of_examinations": STAFF_SELF
    | P("exams", "manage")
    | P("results", "manage")
    | P("marks", "lock", "correct", "view_all")
    | P("degrees", "award", "view_all")
    | P("students", "view_all")
    | P("hr", "view_all")
    | P("fees", "view_all")
    | P("reports", "run", "view")
    | P("attendance", "view_all")
    | P("timetable", "view_all")
    | P("courses", "view_all")
    | P("offerings", "view_all")
    | P("programs", "view_all")
    | P("batches", "view_all"),
    "exam_cell": STAFF_SELF
    | P(
        "exams",
        "view",
        "view_all",
        "configure",
        "eligibility",
        "hall_tickets",
        "seating",
        "invigilation",
        "conduct",
        "qp",
        "qp_print",
        "code",
        "custody",
        "valuation_assign",
        "reval",
        "malpractice",
        "export",
    )
    | P("results", "compute", "verify", "view_all")
    | P("students", "view_all")
    | P("attendance", "view_all")
    | P("marks", "view_all")
    | P("courses", "view_all")
    | P("offerings", "view_all"),
    "exam_decoder": STAFF_SELF | P("exams", "decode", "view"),
    "dean": ALL("view", "view_all")
    | P("leaves", "approve")
    | P("regulations", "approve")
    | DEAN_ACADEMICS
    | DEAN_HR
    | P("offerings", "allocate_faculty")
    | P("events", "approve")
    | STAFF_SELF,
    "hod": FACULTY
    | P("students", "view_all")
    | P("hr", "view_all")
    | P("leaves", "approve", "view_all")
    | P("attendance", "view_all", "condone")
    | P("marks", "verify", "view_all")
    | P("offerings", "manage")
    | P("faculty", "workload_manage", "view_all")
    | P("inventory", "approve_indent", "view_all")
    | P("governance", "minutes", "view")
    | P("accreditation", "view")
    | P("courses", "view_all")
    | P("timetable", "view_all")
    | P("curriculum", "view_all")
    | P("programs", "view_all")
    | P("batches", "view_all")
    | P("registration", "view_all", "approve")
    | P("projects", "view_all")
    | P("lms", "view_all")
    | P("results", "view_all")
    | P("research", "view_all")
    | P("departments", "view")
    # Phase 05: HOD @department drafts the courses, structures and batches of its own department
    | HOD_ACADEMICS,
    "class_advisor": FACULTY | P("registration", "approve") | P("attendance", "view"),
    "faculty": FACULTY,
    "guest_faculty": (FACULTY - P("leaves", "self", "create", "view", "encash")),
    "external_examiner": COMMON | P("exams", "evaluate", "qp", "view") | P("payroll", "self"),
    "invigilator": COMMON
    | P("exams", "conduct", "malpractice", "invigilation", "view")
    | P("leaves", "self", "create", "view")
    | P("payroll", "self")
    | P("attendance", "staff_self"),
    "research_guide": FACULTY | P("phd", "guide", "dc", "examine", "view"),
    "research_scholar": COMMON
    | P("phd", "self", "view")
    | P("students", "self")
    | P("fees", "self")
    | P("library", "self")
    | P("results", "self")
    | P("certificates", "self")
    | P("grievances", "create")
    | P("surveys", "respond")
    | P("events", "view")
    | P("hostel", "self")
    | P("attendance", "self")
    | P("research", "view"),
    "research_cell": STAFF_SELF
    | P("research", "manage")
    | P("phd", "manage")
    | P("accounting", "view_all")
    | P("hr", "view_all")
    | P("faculty", "view_all", "research")
    | P("reports", "run", "view"),
    "iqac_coordinator": ALL("view", "view_all")
    | P("accreditation", "manage")
    | P("surveys", "manage")
    | P("reports", "statutory", "run")
    | STAFF_SELF,
    "obe_coordinator": STAFF_SELF
    | P("obe", "manage", "configure", "compute", "export")
    | P("marks", "view_all")
    | P("results", "view_all")
    | P("courses", "view_all")
    | P("curriculum", "view_all")
    | P("programs", "view_all"),
    "admissions_officer": STAFF_SELF
    | P("admissions", "manage")
    | P("students", "view_all", "create")
    | P("fees", "view_all")
    | P("programs", "view_all")
    | P("colleges", "view_all")
    | P("departments", "view_all")
    | P("reports", "run", "view")
    | P("communication", "send"),
    "accountant": STAFF_SELF
    | P("fees", "manage")
    | P("scholarships", "disburse", "view_all", "view")
    | P("no_dues", "approve", "view_all")
    | P("payroll", "manage")
    | P("accounting", "manage")
    | P("procurement", "bill_approve", "view_all")
    | P("library", "fines", "view_all")
    | P("hr", "view_all")
    | P("leaves", "view_all")
    | P("attendance", "staff_view_all")
    | P("students", "view_all")
    | P("hostel", "view_all")
    | P("inventory", "view_all")
    | P("transport", "view_all")
    | P("fundraising", "view_all", "receipt")
    | P("reports", "run", "view"),
    "hr_officer": STAFF_SELF
    | P("hr", "manage", "view_pii")
    | P("recruitment", "manage")
    | P("leaves", "manage")
    | P("attendance", "staff_view_all", "device_manage")
    | P("payroll", "generate", "statutory", "view_all")
    | P("users", "view_all", "create", "update", "reset_password")
    | P("faculty", "view_all", "workload_manage")
    | P("departments", "view_all")
    | P("colleges", "view_all")
    | P("reports", "run", "view")
    | P("communication", "send"),
    "placement_officer": STAFF_SELF
    | P("placement", "manage")
    | P("students", "view_all")
    | P("results", "view_all")
    | P("attendance", "view_all")
    | P("alumni", "view_all")
    | P("reports", "run", "view")
    | P("communication", "send")
    | P("events", "organise"),
    "alumni_coordinator": STAFF_SELF
    | P("alumni", "manage")
    | P("fundraising", "manage")
    | P("events", "organise")
    | P("communication", "send", "bulk")
    | P("reports", "run", "view"),
    "hostel_warden": STAFF_SELF
    | P("hostel", "manage")
    | P("students", "view")
    | P("attendance", "view")
    | P("fees", "view")
    | P("communication", "send"),
    "hostel_gate_staff": COMMON | P("hostel", "gate", "view"),
    "librarian": STAFF_SELF
    | P("library", "manage")
    | P("students", "view_all")
    | P("hr", "view_all")
    | P("no_dues", "approve", "view_all")
    | P("fees", "view")
    | P("reports", "run", "view"),
    "transport_manager": STAFF_SELF
    | P("transport", "manage")
    | P("students", "view_all")
    | P("hr", "view_all")
    | P("fees", "view_all")
    | P("reports", "run", "view"),
    "inventory_manager": STAFF_SELF
    | P("inventory", "manage")
    | P("procurement", "quote", "po_approve", "view_all", "create", "update")
    | P("accounting", "view")
    | P("reports", "run", "view"),
    "estate_officer": STAFF_SELF
    | P("facilities", "manage")
    | P("timetable", "view_all")
    | P("inventory", "indent", "view")
    | P("reports", "run", "view"),
    "security_officer": STAFF_SELF
    | P("facilities", "manage")
    | P("communication", "emergency", "send")
    | P("hostel", "view")
    | P("students", "view")
    | P("users", "view_all"),
    "medical_officer": STAFF_SELF | P("health", "manage") | P("students", "view"),
    "sports_officer": STAFF_SELF
    | P("sports", "manage")
    | P("clubs", "verify_hours", "view")
    | P("events", "organise")
    | P("students", "view_all"),
    "grievance_officer": STAFF_SELF
    | P("grievances", "triage", "resolve", "escalate", "committee", "view_all", "update", "view")
    | P("students", "view")
    | P("communication", "send"),
    "discipline_committee": STAFF_SELF | P("discipline", "manage") | P("students", "view") | P("hostel", "view"),
    "committee_secretary": STAFF_SELF
    | P("governance", "committees", "minutes", "resolutions", "view", "create", "update"),
    "legal_officer": STAFF_SELF | P("legal", "manage") | P("efile", "manage") | P("rti", "view"),
    "pio": STAFF_SELF | P("rti", "manage") | P("efile", "view"),
    "receptionist": STAFF_SELF | P("admissions", "create", "view") | P("facilities", "manage") | P("students", "view"),
    "driver": COMMON
    | P("transport", "driver", "view")
    | P("payroll", "self")
    | P("leaves", "self", "create", "view")
    | P("attendance", "staff_self"),
    "integration_admin": STAFF_SELF | P("integrations", "manage") | P("jobs", "view_all") | P("audit_logs", "view_all"),
    "college_admin": _COLLEGE_ADMIN,
    "college_exam_coordinator": STAFF_SELF
    | P("affiliation", "submit", "view")
    | P("exams", "conduct", "hall_tickets", "view", "view_all")
    | P("marks", "view_all")
    | P("results", "view_all")
    | P("students", "view_all"),
    # Phase 06: staff attendance is a bespoke action (``staff_view_all``) outside ALL(view, view_all) — the auditor
    # reads every HR register (Prompts/06 visibility table)
    "auditor": ALL("view", "view_all") | P("reports", "run") | AUDITOR_HR | COMMON,
    "recruiter": COMMON | P("placement", "recruiter", "view"),
    "learner": COMMON
    | P("students", "self")
    | P("registration", "self")
    | P("lms", "view")
    | P("fees", "self")
    | P("certificates", "self")
    | P("results", "self")
    | P("attendance", "self")
    | P("events", "view")
    | P("surveys", "respond")
    | P("grievances", "create")
    | P("library", "self"),
    "student": STUDENT,
    "parent": COMMON
    | P("students", "view")
    | P("attendance", "view")
    | P("results", "view")
    | P("marks", "view")
    | P("fees", "self")
    | P("hostel", "view")
    | P("mentoring", "wards")
    | P("surveys", "respond")
    | P("grievances", "create", "view")
    | P("communication", "view")
    | P("timetable", "view")
    | P("calendar", "view")
    | P("events", "view")
    | P("transport", "view"),
    "alumni": COMMON
    | P("alumni", "self")
    | P("certificates", "self")
    | P("results", "transcript", "self")
    | P("placement", "self")
    | P("fundraising", "view")
    | P("events", "view")
    | P("communication", "view"),
    "applicant": COMMON | P("admissions", "create", "view") | P("fees", "self") | P("communication", "view"),
}

# ---- import-time invariants ------------------------------------------------------------------------------------
assert set(ROLE_TEMPLATES) == set(ROLE_SLUGS), "ROLE_TEMPLATES must cover exactly the 51 role templates"
for _slug, _grants in ROLE_TEMPLATES.items():
    _unknown = {g for g in _grants if g != "*:*" and g not in PERMISSIONS}
    assert not _unknown, f"role template {_slug} cites unknown permissions: {sorted(_unknown)}"


# Grants added to templates by a later phase that must also reach the roles already cloned into tenants (revision
# ``0003`` backfills them; grants an administrator removed afterwards are not re-added by later revisions).
BACKFILL_GRANTS: dict[str, frozenset[str]] = {
    "0003": frozenset({"institutions:view"}),
    "0005": frozenset(ACADEMIC_READ | REGISTRAR_ACADEMICS | HOD_ACADEMICS | DEAN_ACADEMICS),
    "0006": frozenset(P("leaves", "encash") | DEAN_HR | AUDITOR_HR),
}


def template_permissions(slug: str) -> set[str]:
    """Concrete ``module:action`` grants of a template (``*:*`` expands to the whole catalogue)."""
    grants = ROLE_TEMPLATES[slug]
    if "*:*" in grants:
        return set(PERMISSIONS)
    return set(grants)
