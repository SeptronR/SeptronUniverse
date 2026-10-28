"""Permission catalogue, role templates and scope rules — Prompts/02 §02.2, §02.6; docs/Roles_and_Permissions.md.

* ``PERMISSIONS`` mirrors ``Database_Schema.sql`` §36.1 exactly (modules × standard actions + bespoke actions); the
  Phase 02 seed revision and ``seed_platform.py`` upsert it (``ON CONFLICT DO NOTHING``) and the in-process
  verification asserts the two sets are identical.
* ``ROLE_META`` mirrors §36.2 (name, slug, is_system, default scope, portal) for the 53 platform role templates (Phase 22 added ``vendor`` and ``store_keeper``).
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
    # Phase 38: the platform operator's console (super admin / support agent only — never granted to tenant roles) and
    # support tickets (tenants raise / reply; platform staff triage)
    "platform",
    "support",
    # Phase 43: DPDP privacy office (notices, consent reports, DSR board), security posture, verification suites
    "privacy",
    "security",
    "qa",
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
    # Phase 25: counsellors publish slots and keep encrypted session notes (Prompts/25 visibility table)
    ("facilities", "counsel", "Counselling appointments"),
    ("placement", "self", "Own placement"),
    ("placement", "drive_manage", "Manage drives"),
    ("placement", "override_eligibility", "Override eligibility"),
    ("placement", "offer_manage", "Manage offers"),
    ("placement", "recruiter", "Recruiter portal"),
    # Phase 28: guardians read their ward's drives / offers; internship course faculty evaluate assigned internships
    ("placement", "wards", "Wards placement"),
    ("placement", "evaluate", "Evaluate internships"),
    # Phase 30: HOD first-level / research cell final verification of publications, patents, awards
    ("research", "verify", "Verify research records"),
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
    # Phase 33: policy repository management and statutory / AG audit paras (replies by finance)
    ("governance", "policies", "Manage policies"),
    ("governance", "audit_paras", "Audit paras"),
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
    # Phase 37: security events console (login failures, sessions, impersonation, anomalies) and exam audit trails
    ("audit_logs", "security", "Security events console"),
    ("exams", "audit", "Exam audit trail"),
    ("integrations", "connect", "Manage connections"),
    ("integrations", "api_keys", "API keys"),
    ("integrations", "webhooks", "Webhooks"),
    ("integrations", "import", "Data imports"),
    ("jobs", "cancel", "Cancel jobs"),
    # Phase 43: run verification suites / golden / access-matrix jobs (non-production only)
    ("qa", "run", "Run verification suites"),
    # Phase 38: platform billing (plans, subscriptions, invoices), help-centre authoring and the support desk
    ("platform", "billing", "Platform billing"),
    ("platform", "help", "Author platform help articles"),
    ("platform", "support", "Platform support desk"),
)


def _catalogue() -> dict[str, str]:
    perms: dict[str, str] = {}
    for m in MODULES:
        for a in STANDARD_ACTIONS:
            perms[f"{m}:{a}"] = f"{m}:{a}"
    for m, a, d in BESPOKE_ACTIONS:
        perms[f"{m}:{a}"] = d
    return perms


PERMISSIONS: dict[str, str] = _catalogue()  # "module:action" → description
# never grantable to tenant roles (``RbacService`` refuses them); Phase 38 adds every ``platform:*`` action
PLATFORM_MODULES: tuple[str, ...] = ("platform",)
PLATFORM_ONLY_PERMISSIONS: frozenset[str] = frozenset(
    {"users:impersonate", "features:manage"} | {k for k in PERMISSIONS if k.split(":", 1)[0] in PLATFORM_MODULES}
)
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
        # Phase 22 — supplier portal user and store keeper (stores owned through stores.keeper_staff_id)
        ("Vendor", "vendor", "self", "vendor"),
        ("Store Keeper", "store_keeper", "self", "admin"),
        # Phase 43 — DPDP privacy officer (notices, consents, data-subject requests)
        ("Privacy Officer", "privacy_officer", "institution", "admin"),
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
# additional tables a scope id may name (Phase 05: ``class_advisor`` @offering is assigned to a batch *section*; from
# Phase 09 a real ``course_offerings`` id is valid too — both share the ``offering`` scope type and section assignments
# keep working: ``student_scope.advised_sections`` reads either)
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


# Phase 43: privacy office / security posture / QA are granted explicitly (``PHASE43_GRANTS``), never through ALL()
EXPLICIT_MODULES: tuple[str, ...] = ("privacy", "security", "qa")


def ALL(*actions: str, exclude: tuple[str, ...] = ()) -> set[str]:
    """Every module × ``actions`` — never the platform-only modules (Phase 38 ``platform``) nor the Phase 43 office
    modules (granted explicitly)."""
    return {
        f"{m}:{a}"
        for m in MODULES
        if m not in exclude and m not in PLATFORM_MODULES and m not in EXPLICIT_MODULES
        for a in actions
    }


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
ADMISSIONS_STAFF_READ: set[str] = P("admissions", "view")  # Phase 08 — see HOD_ADMISSIONS below
# staff self-service — always present where it makes sense (docs/Authorization_and_Visibility.md §4)
# Phase 27: staff read own / committee grievances and own cases; committee members decide (services narrow rows)
STAFF_SUPPORT: set[str] = P("grievances", "view") | P("discipline", "view")
COMMITTEE_SUPPORT: set[str] = P("discipline", "decide")
# Phase 28: internship course faculty evaluate the internships mapped to their offerings
FACULTY_PLACEMENT: set[str] = P("placement", "evaluate")
# Phase 33: staff see their own committees / meetings / resolutions / files and acknowledge policies; student members
# read their committees (rows narrowed in the governance services)
STAFF_GOVERNANCE: set[str] = P("governance", "view") | P("efile", "create", "view")
STUDENT_GOVERNANCE: set[str] = P("governance", "view")
STAFF_SELF: set[str] = (
    COMMON
    | STAFF_GOVERNANCE
    | P("leaves", "self", "create", "view")
    | P("payroll", "self")
    | P("attendance", "staff_self")
    | P("hr", "view")
    # Phase 21: staff passengers read their own transport allocation
    | P("transport", "view")
    # Phase 06: staff request encashment of their own encashable leave (gated by {hr.leave_encashment})
    | P("leaves", "encash")
    | P("calendar", "view")
    | P("communication", "view")
    | P("events", "view")
    | P("certificates", "self")
    | P("grievances", "create")
    | STAFF_SUPPORT
    | P("facilities", "book", "view")
    # Phase 25: own health visits / counselling bookings and sports participation
    | P("health", "view")
    | P("sports", "view")
    | P("surveys", "respond")
    | P("library", "self")
    | P("timetable", "view")
    | P("no_dues", "request")
    | P("settings", "view")
    # Phase 05: programmes, regulations, curricula, courses and batches are institution-wide readable by all staff
    | ACADEMIC_READ
    # Phase 08: admission cycles, seat matrix and merit lists are readable by all staff
    | ADMISSIONS_STAFF_READ
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
    | P("exams", "evaluate", "invigilation", "malpractice", "view", "qp")
    | P("surveys", "analyse", "view")
    | P("courses", "view")
    | P("offerings", "view")
    | P("curriculum", "view")
    | P("registration", "view")
    | P("faculty", "view", "research")
    | P("inventory", "indent", "view")
    # Phase 23: principal investigators read their own grant ledgers
    | P("accounting", "view")
    # Phase 25: faculty organise their own events (FACULTY_EVENTS)
    | P("events", "organise")
    | P("clubs", "view")
    | COMMITTEE_SUPPORT
    | FACULTY_PLACEMENT
    | P("results", "view")
    # Phase 10: faculty request substitutions for their own classes (FACULTY_TIMETABLE below)
    | P("timetable", "substitute")
    # Phase 17: own offerings' attainment (FACULTY_OBE below)
    | P("obe", "view", "compute")
)

# Phase 07 (Prompts/07 "Visibility rules"): registrar / institution_admin read student PII; HOD verifies the credit
# transfers of its department (step 1 of ``students.credit_transfer``) and lists them
STUDENTS_ADMIN_PII: set[str] = P("students", "view_pii")
HOD_STUDENTS: set[str] = P("credit_transfers", "verify", "view_all")
# Phase 08 (Prompts/08 "Visibility rules"): cycles / seat matrix / merit lists are readable by all staff; the HOD reads
# the applicants with a preference for its department's programmes; admissions office, registrar and institution
# admin read applicant PII
HOD_ADMISSIONS: set[str] = P("admissions", "view_all")
ADMISSIONS_PII: set[str] = P("admissions", "view_pii")

_INSTITUTION_ADMIN: set[str] = (
    ALL("manage", exclude=("features", "exams"))
    | P("features", "view", "institution_toggle")
    | MODULE_ALL("exams", exclude=("decode",))
    | STUDENTS_ADMIN_PII
    | ADMISSIONS_PII
    | COMMON
    | STAFF_SELF
)

_COLLEGE_ADMIN: set[str] = (
    ALL("manage", exclude=("features", "exams", "regulations", "results", "degrees", "institutions", "support"))
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
    | STUDENT_GOVERNANCE
    | P("students", "self", "undertakings", "id_card", "view")
    | P("registration", "self")
    | P("attendance", "self")
    | P("marks", "view")
    | P("exams", "self")
    | P("results", "self")
    | P("obe", "view")
    | P("degrees", "view")
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
# Phase 09 (Prompts/09 "Visibility rules"): the registrar creates offerings and owns registration (windows, overrides,
# bulk registration, elective allocation); the dean creates / bulk-generates the offerings of its faculty's departments
REGISTRAR_REGISTRATION: set[str] = P(
    "offerings", "view_all", "create", "update", "manage", "bulk_create", "allocate_faculty", "export"
) | P("registration", "view_all", "manage", "override", "bulk", "allocate", "approve", "export")
DEAN_OFFERINGS: set[str] = P("offerings", "create", "bulk_create")
# Phase 10 (Prompts/10 "Visibility rules"): the registrar manages every timetable, room and slot group
# (``timetable:manage`` = create / publish / generate / substitute / approve); HOD @department drafts and publishes the
# timetables of its department's sections / batches, edits its department labs and decides substitutions; the estate
# officer edits rooms and buildings (``timetable:update``); faculty request substitutions for their own classes and
# mark / manage their sessions (``attendance:mark`` already in FACULTY)
REGISTRAR_TIMETABLE: set[str] = P("timetable", "manage", "view_all")
HOD_TIMETABLE: set[str] = P("timetable", "create", "update", "publish", "approve", "substitute", "export")
ESTATE_TIMETABLE: set[str] = P("timetable", "update")
FACULTY_TIMETABLE: set[str] = P("timetable", "substitute")
# Phase 11 (Prompts/11 "Visibility rules"): the registrar marks / corrects attendance (``edit_finalized``), approves
# condonation and computes / decides eligibility (``exams:eligibility``); the HOD edits finalized attendance of its
# department with a reason; the controller of examinations computes eligibility; the vice-chancellor (principal) holds
# the final condonation step of the Phase 04 template
REGISTRAR_ATTENDANCE: set[str] = P("attendance", "mark", "edit_finalized", "condone") | P("exams", "eligibility")
HOD_ATTENDANCE: set[str] = P("attendance", "edit_finalized")
COE_ATTENDANCE: set[str] = P("exams", "eligibility")
VC_ATTENDANCE: set[str] = P("attendance", "condone")
# Phase 12 (Prompts/12 visibility table): registrar sanctions scholarships / approves refunds; the vice-chancellor
# ("principal") is the last step of receipt cancellation / refund / sanction; HOD recommends scholarships, signs the
# department / lab no-dues and reads its department's dues; class advisors read advisees' dues; the warden, sports,
# transport and placement offices sign their own no-dues; the accountant verifies scholarships; parents read their
# wards' scholarships / no-dues
REGISTRAR_FEES: set[str] = (
    P("fees", "approve", "refund")
    | P("scholarships", "sanction", "view_all", "view")
    | P("no_dues", "approve", "view_all", "view")
)
VC_FEES: set[str] = P("fees", "approve", "cancel_receipt") | P("scholarships", "sanction")
HOD_FEES: set[str] = (
    P("fees", "view_all")
    | P("scholarships", "approve", "view_all", "view")
    | P("no_dues", "approve", "view_all", "view")
)
ADVISOR_FEES: set[str] = P("fees", "view")
ACCOUNTANT_FEES: set[str] = P("scholarships", "verify")
OFFICE_NO_DUES: set[str] = P("no_dues", "approve", "view")
PARENT_FEES: set[str] = P("scholarships", "view") | P("no_dues", "view")
# Phase 13 (Prompts/13 visibility): the exam cell locks / reopens marks; the HOD edits OBE definitions of its
# programmes / courses (narrowed in the service), shares the department's question bank / projects and handles
# post-lock change requests; the dean edits OBE definitions; the registrar reads marks institution-wide; parents read
# their wards' LMS pages and projects
EXAM_CELL_MARKS: set[str] = P("marks", "lock")
HOD_ASSESSMENT: set[str] = (
    P("obe", "manage", "view") | P("lms", "view_all") | P("projects", "view_all") | P("marks", "correct")
)
DEAN_OBE: set[str] = P("obe", "manage")
REGISTRAR_MARKS: set[str] = P("marks", "view_all")
PARENT_LMS: set[str] = P("lms", "view") | P("projects", "view")
# Phase 14 (Prompts/14 visibility): HOD reads its department's sessions / registrations / duties; faculty set question
# papers (own assignments only — qp_predicate); parents read their wards' exam registrations / hall tickets / seats
HOD_EXAMS: set[str] = P("exams", "view", "view_all")
FACULTY_QP: set[str] = P("exams", "qp")
PARENT_EXAMS: set[str] = P("exams", "view")
# Phase 15 (Prompts/15 visibility): the HOD reads its department's runs (after verification) and published results
HOD_RESULTS: set[str] = P("results", "view_all")
# Phase 16 (Prompts/16 visibility): the registrar reads reval / malpractice queues (exams view_all) and approves medals;
# discipline-committee members and committee secretaries read the malpractice cases of their committees (narrowed by
# ``committee_members`` in the service) and the committee chair decides them
REGISTRAR_POST_RESULT: set[str] = P("exams", "view_all") | P("results", "approve")
COMMITTEE_EXAMS: set[str] = P("exams", "view")
# Phase 17 (Prompts/17 visibility): faculty compute / read the attainment of their own offerings (narrowed to
# ``course_offering_faculty`` in the service) and own CQI actions; the dean configures and computes; IQAC manages the
# CQI register and exports NBA SAR; students read their own CO achievement only when ``obe.show_students`` is on
FACULTY_OBE: set[str] = P("obe", "view", "compute")
DEAN_ATTAINMENT: set[str] = P("obe", "configure", "compute", "export")
IQAC_OBE: set[str] = P("obe", "manage", "compute", "export")
STUDENT_OBE: set[str] = P("obe", "view")
# Phase 18 (Prompts/18 visibility): students / parents / alumni read their own (wards') eligibility, convocation,
# awards and credential status (narrowed in the services); the registrar overrides eligibility (degrees:manage); the
# HOD reads its department's checks and awards
SELF_DEGREES: set[str] = P("degrees", "view")
REGISTRAR_DEGREES: set[str] = P("degrees", "manage", "view")
HOD_DEGREES: set[str] = P("degrees", "view_all")
# Phase 19 (Prompts/19 visibility): parents read their wards' library cards / issues / fines; the HOD reads its
# department's members and overdue lists
PARENT_LIBRARY: set[str] = P("library", "self")
HOD_LIBRARY: set[str] = P("library", "view_all")
# Phase 20 (Prompts/20 visibility): the registrar runs allotments / approves evictions (hostel:manage, institution);
# the HOD reads its department's residents (view_all, department); class advisors read their advisees (view)
REGISTRAR_HOSTEL: set[str] = P("hostel", "manage")
HOD_HOSTEL: set[str] = P("hostel", "view_all")
ADVISOR_HOSTEL: set[str] = P("hostel", "view")
# Phase 21 (Prompts/21 visibility): HODs read their department's transport allocations (view_all, department);
# staff passengers read their own (transport:view added to STAFF_SELF)
HOD_TRANSPORT: set[str] = P("transport", "view_all")
STAFF_TRANSPORT: set[str] = P("transport", "view")
# Phase 22 (Prompts/22 visibility): store keepers move stock in the stores they keep; the inventory manager also
# receives / issues / audits; the accountant and the vice-chancellor approve POs (threshold workflow) and bills
STORE_KEEPER: set[str] = P("inventory", "receive", "issue", "view", "indent")
INVENTORY_MANAGER_OPS: set[str] = P("inventory", "receive", "issue", "asset_audit", "view_all", "view_pii")
ACCOUNTANT_PROCUREMENT: set[str] = P("procurement", "po_approve")
VC_PROCUREMENT: set[str] = P("procurement", "po_approve", "bill_approve")
VENDOR_PORTAL: set[str] = P("procurement", "quote") | P("inventory", "view")
# Phase 23 (Prompts/23 visibility): HODs record / read their department's expenses and budgets; faculty read their own
# grant ledgers (PI); the accountant posts, reconciles, approves (below the threshold) and exports; the vice-chancellor
# approves above it; IQAC reads aggregates
HOD_ACCOUNTING: set[str] = P("accounting", "view", "post")
FACULTY_ACCOUNTING: set[str] = P("accounting", "view")
ACCOUNTANT_ACCOUNTING: set[str] = P("accounting", "post", "reconcile", "approve", "export", "view_all")
VC_ACCOUNTING: set[str] = P("accounting", "approve")
IQAC_ACCOUNTING: set[str] = P("accounting", "view_all")
# Phase 24 (Prompts/24 visibility): the registrar runs campaigns, approves large ones and may broadcast emergencies; the
# vice-chancellor approves and broadcasts; HODs send department campaigns (in-app / e-mail / push)
REGISTRAR_COMMS: set[str] = P("communication", "bulk", "approve", "emergency", "view_all", "template_manage")
VC_COMMS: set[str] = P("communication", "approve", "emergency")
HOD_COMMS: set[str] = P("communication", "send")
# Phase 25 (Prompts/25 "Visibility rules"): HODs approve step 1 of their department's events and read department
# bookings / tickets; the registrar manages the calendar, approves events and runs the estate; the estate officer
# approves bookings and assigns tickets; security reads every gate / SOS record; the medical officer records
# confidential visits; the sports officer reads all participation; faculty organise their own events; the accountant
# reads event fees / budgets; staff and parents use the self-service wellness, sports and wallet screens
HOD_FACILITIES: set[str] = P("events", "approve", "view_all") | P("facilities", "view_all") | P("calendar", "view_all")
REGISTRAR_FACILITIES: set[str] = (
    P("calendar", "manage", "view_all")
    | P("events", "manage", "approve", "view_all", "certify", "organise")
    | P("facilities", "manage", "view_all", "approve_booking", "service_assign")
    | P("sports", "view_all")
    | P("health", "view_all")
)
VC_FACILITIES: set[str] = P("events", "approve", "certify") | P("facilities", "approve_booking")
FACULTY_EVENTS: set[str] = P("events", "organise")
ESTATE_FACILITIES: set[str] = P("facilities", "approve_booking", "service_assign", "view_all") | P(
    "calendar", "view_all"
)
SECURITY_FACILITIES: set[str] = P("facilities", "view_all", "service_assign")
MEDICAL_HEALTH: set[str] = P("health", "record", "view_all") | P("facilities", "counsel")
SPORTS_FACILITIES: set[str] = P("sports", "view_all")
ACCOUNTANT_FACILITIES: set[str] = P("events", "view_all")
STAFF_CAMPUS: set[str] = P("health", "view") | P("sports", "view")
PARENT_FACILITIES: set[str] = P("calendar", "view") | P("events", "view") | P("facilities", "view")
CANTEEN_POS: set[str] = P("facilities", "view")
# Phase 26 — document templates, issued register, certificate requests (per-type limits applied in the services)
REGISTRAR_DOCUMENTS: set[str] = P("certificates", "request_approve", "view_all") | P("templates", "manage")
HR_DOCUMENTS: set[str] = P("certificates", "request_approve", "issue", "view_all") | P("templates", "view", "manage")
COE_DOCUMENTS: set[str] = P("certificates", "request_approve", "issue", "view_all") | P(
    "templates", "view", "manage", "render"
)
HOD_DOCUMENTS: set[str] = P("certificates", "view_all")
OFFICE_DOCUMENTS: set[str] = P("certificates", "issue", "view_all") | P("templates", "view", "render")
PARENT_DOCUMENTS: set[str] = P("certificates", "self")
# Phase 27 (Prompts/27 "Visibility rules"): staff read their own / committee grievances and their own disciplinary cases
# (rows narrowed by committee membership / assignee / subject in the services); faculty and committee secretaries
# decide the cases of committees they sit on; HODs read department mentoring / grievances (non-confidential) /
# discipline / survey results / clubs; the registrar reads the student-support registers; the principal decides
# appeals; grievance officers constitute grievance committees; parents read clubs / hours / achievements
HOD_SUPPORT: set[str] = (
    P("mentoring", "view_all")
    | P("grievances", "view_all")
    | P("discipline", "view_all")
    | P("surveys", "view_all", "analyse")
    | P("clubs", "view_all")
)
REGISTRAR_SUPPORT: set[str] = (
    P("mentoring", "view_all")
    | P("grievances", "view_all")
    | P("discipline", "view_all", "appeal")
    | P("surveys", "view_all")
    | P("clubs", "view_all", "manage")
    | P("governance", "committees")
)
VC_SUPPORT: set[str] = P("discipline", "appeal")
# Phase 28 (Prompts/28 "Visibility rules"): the placement officer runs drives / overrides / offers / blacklist and reads
# academics; HODs and class advisors read department drives, applications, offers, profiles and evaluate department
# internships; internship course faculty evaluate the internships mapped to their offerings; guardians read the ward's
# drives / offers; the registrar and accountant read aggregates (training vendor costs)
PLACEMENT_OFFICER: set[str] = P(
    "placement", "drive_manage", "override_eligibility", "offer_manage", "view_all", "export"
)
HOD_PLACEMENT: set[str] = P("placement", "view_all", "evaluate")
PARENT_PLACEMENT: set[str] = P("placement", "wards")
READ_PLACEMENT: set[str] = P("placement", "view_all")
ACCOUNTANT_PLACEMENT: set[str] = P("placement", "view")
# Phase 29 (Prompts/29 "Visibility rules"): the alumni coordinator verifies / merges / exports profiles, runs campaigns
# and issues 80G receipts; HODs read department alumni (consented), the registrar / principal-level readers aggregates;
# the accountant records offline donations and keeps the 80G register (fundraising:receipt)
ALUMNI_COORDINATOR: set[str] = P("alumni", "verify", "campaign", "view_all", "export") | P(
    "fundraising", "receipt", "view_all", "export"
)
HOD_ALUMNI: set[str] = P("alumni", "view_all")
READ_ALUMNI: set[str] = P("alumni", "view_all") | P("fundraising", "view_all")
# Phase 30 (Prompts/30 "Visibility rules"): the research cell verifies / imports / sanctions and runs the ethics
# secretariat, incentives, MoUs and incubation; HODs verify their department's records first and recommend incentives;
# the accountant reaches project / consultancy money and incentive disbursement through accounting:*; IQAC / principal-level readers aggregates
RESEARCH_CELL: set[str] = P("research", "verify", "view_all", "export", "ethics", "incentives", "mous", "incubation")
HOD_RESEARCH: set[str] = P("research", "verify", "view_all")
READ_RESEARCH: set[str] = P("research", "view_all")
# Phase 31 (Prompts/31 "Visibility rules"): guides are faculty (own scholars through guide / co-guide / DC membership);
# HODs / deans read their units' scholars and approve request / panel steps; the research cell runs fellowships,
# examinations and ETD; the CoE records examiner remuneration / viva results; the accountant pays disbursements
FACULTY_PHD: set[str] = P("phd", "guide", "view")
HOD_PHD: set[str] = P("phd", "dc", "view_all", "approve")
RESEARCH_CELL_PHD: set[str] = P("phd", "fellowship", "examine", "etd", "view_all", "export", "approve")
COE_PHD: set[str] = P("phd", "examine", "view")
ACCOUNTANT_PHD: set[str] = P("phd", "fellowship", "view")
# Phase 32 (Prompts/32 "Visibility rules"): faculty upload evidence and write the criterion responses they own; HODs
# read department metrics, propose overrides and upload department evidence; the principal (vice_chancellor) / dean
# verify overrides and approve responses; module officers read their own module's metrics (``view``); IQAC holds
# ``accreditation:manage`` (compute / override / submit / evidence through the wildcard)
FACULTY_ACCREDITATION: set[str] = P("accreditation", "view", "evidence")
HOD_ACCREDITATION: set[str] = P("accreditation", "view", "override", "evidence")
PRINCIPAL_ACCREDITATION: set[str] = P("accreditation", "approve", "override")
OFFICER_ACCREDITATION: set[str] = P("accreditation", "view")
# Phase 33 (Prompts/33 "Visibility rules"): every staff member sees their committees / meetings / owned resolutions,
# creates and moves e-files and acknowledges policies (``governance:view`` + ``efile:create|view``; rows narrowed by
# membership / ownership / holder in the services); student members read their committees; the registrar administers
# governance (manage), reads legal / RTI, decides first RTI appeals (``rti:approve``) and administers e-files; the
# principal (vice_chancellor) approves minutes, policies and files; finance replies to audit paras
REGISTRAR_GOVERNANCE: set[str] = (
    P("governance", "manage") | P("legal", "view_all") | P("rti", "view_all", "approve") | P("efile", "manage")
)
VC_GOVERNANCE: set[str] = P("governance", "approve") | P("efile", "approve")
ACCOUNTANT_GOVERNANCE: set[str] = P("governance", "audit_paras")
GRIEVANCE_OFFICER_SUPPORT: set[str] = P("governance", "committees")
# Phase 34 (Prompts/34 "Visibility rules"): the registrar runs the affiliation office (manage + verify submissions;
# the VC decides); the COE verifies exam submissions and reads the registry (accept / lock through exams:configure);
# college admins apply / submit for their college (college scope); staff may sit on inspection committees
# (``affiliation:inspect`` — rows narrowed to assigned inspections); the accountant reads dues
REGISTRAR_AFFILIATION: set[str] = P("affiliation", "manage", "verify_submission", "view_all")
VC_AFFILIATION: set[str] = P("affiliation", "decide", "view_all")
COE_AFFILIATION: set[str] = P("affiliation", "verify_submission", "view_all") | P("exams", "configure")
COLLEGE_AFFILIATION: set[str] = P("affiliation", "apply", "submit", "view")
STAFF_AFFILIATION: set[str] = P("affiliation", "inspect")
ACCOUNTANT_AFFILIATION: set[str] = P("affiliation", "view")
PARENT_SUPPORT: set[str] = P("clubs", "view")

ROLE_TEMPLATES: dict[str, set[str]] = {
    "super_admin": {"*:*"},
    "support_agent": ALL("view", "view_all") | P("users", "impersonate") | COMMON | P("platform", "view", "support"),
    "institution_admin": _INSTITUTION_ADMIN,
    "vice_chancellor": ALL("view", "view_all")
    | VC_AFFILIATION
    | VC_GOVERNANCE
    | PRINCIPAL_ACCREDITATION
    | VC_PROCUREMENT
    | VC_ACCOUNTING
    | VC_COMMS
    | VC_FACILITIES
    | VC_SUPPORT
    | P("leaves", "approve")
    | P("regulations", "approve")
    | P("degrees", "award")
    | P("governance", "manage")
    | P("grievances", "escalate")
    | P("results", "approve")
    | VC_ATTENDANCE
    | VC_FEES
    | STAFF_SELF,
    "registrar": STAFF_SELF
    | REGISTRAR_AFFILIATION
    | REGISTRAR_GOVERNANCE
    | OFFICER_ACCREDITATION
    | REGISTRAR_SUPPORT
    | READ_PLACEMENT
    | READ_ALUMNI
    | REGISTRAR_DOCUMENTS
    | P("students", "manage", "view_pii")
    | P("admissions", "manage")
    | ADMISSIONS_PII
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
    | REGISTRAR_ACADEMICS
    | REGISTRAR_REGISTRATION
    | REGISTRAR_TIMETABLE
    | REGISTRAR_ATTENDANCE
    | REGISTRAR_FEES
    | REGISTRAR_MARKS
    | REGISTRAR_POST_RESULT
    | REGISTRAR_DEGREES
    | REGISTRAR_HOSTEL
    | REGISTRAR_COMMS
    | REGISTRAR_FACILITIES,
    "controller_of_examinations": STAFF_SELF
    | COE_AFFILIATION
    | OFFICER_ACCREDITATION
    | COE_PHD
    | COE_DOCUMENTS
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
    | P("batches", "view_all")
    | COE_ATTENDANCE,
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
    | P("offerings", "view_all")
    | EXAM_CELL_MARKS,
    "exam_decoder": STAFF_SELF | P("exams", "decode", "view"),
    "dean": ALL("view", "view_all")
    | STAFF_AFFILIATION
    | PRINCIPAL_ACCREDITATION
    | HOD_PHD
    | P("leaves", "approve")
    | P("regulations", "approve")
    | DEAN_ACADEMICS
    | DEAN_HR
    | P("offerings", "allocate_faculty")
    | DEAN_OFFERINGS
    | P("events", "approve")
    | DEAN_OBE
    | DEAN_ATTAINMENT
    | STAFF_SELF,
    "hod": FACULTY
    | STAFF_AFFILIATION
    | HOD_ACCREDITATION
    | FACULTY_PHD
    | HOD_PHD
    | HOD_RESEARCH
    | HOD_SUPPORT
    | HOD_PLACEMENT
    | HOD_ALUMNI
    | HOD_DOCUMENTS
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
    | HOD_ACADEMICS
    | HOD_STUDENTS
    | HOD_ADMISSIONS
    | HOD_TIMETABLE
    | HOD_ATTENDANCE
    | HOD_FEES
    | HOD_ASSESSMENT
    | HOD_EXAMS
    | HOD_RESULTS
    | HOD_DEGREES
    | HOD_LIBRARY
    | HOD_HOSTEL
    | HOD_TRANSPORT
    | HOD_ACCOUNTING
    | HOD_COMMS
    | HOD_FACILITIES,
    "class_advisor": FACULTY
    | HOD_DOCUMENTS
    | HOD_PLACEMENT
    | P("registration", "approve")
    | P("attendance", "view")
    | ADVISOR_FEES
    | ADVISOR_HOSTEL,
    "faculty": FACULTY | FACULTY_PHD | FACULTY_ACCREDITATION | STAFF_AFFILIATION,
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
    | RESEARCH_CELL
    | RESEARCH_CELL_PHD
    | P("phd", "manage")
    | P("accounting", "view_all")
    | P("hr", "view_all")
    | P("faculty", "view_all", "research")
    | P("reports", "run", "view"),
    "iqac_coordinator": ALL("view", "view_all")
    | READ_RESEARCH
    | IQAC_ACCOUNTING
    | P("accreditation", "manage")
    | P("surveys", "manage")
    | P("reports", "statutory", "run")
    | IQAC_OBE
    | STAFF_SELF,
    "obe_coordinator": STAFF_SELF
    | OFFICER_ACCREDITATION
    | P("obe", "manage", "configure", "compute", "export")
    | P("marks", "view_all")
    | P("results", "view_all")
    | P("courses", "view_all")
    | P("curriculum", "view_all")
    | P("programs", "view_all"),
    "admissions_officer": STAFF_SELF
    | P("admissions", "manage")
    | ADMISSIONS_PII
    | P("students", "view_all", "create")
    | P("fees", "view_all")
    | P("programs", "view_all")
    | P("colleges", "view_all")
    | P("departments", "view_all")
    | P("reports", "run", "view")
    | P("communication", "send"),
    "accountant": STAFF_SELF
    | ACCOUNTANT_AFFILIATION
    | ACCOUNTANT_GOVERNANCE
    | OFFICER_ACCREDITATION
    | ACCOUNTANT_PHD
    | ACCOUNTANT_PLACEMENT
    | P("fees", "manage")
    | ACCOUNTANT_FACILITIES
    | P("scholarships", "disburse", "view_all", "view")
    | P("no_dues", "approve", "view_all")
    | P("payroll", "manage")
    | P("accounting", "manage")
    | P("procurement", "bill_approve", "view_all")
    | ACCOUNTANT_PROCUREMENT
    | ACCOUNTANT_ACCOUNTING
    | P("library", "fines", "view_all")
    | P("hr", "view_all")
    | P("leaves", "view_all")
    | P("attendance", "staff_view_all")
    | P("students", "view_all")
    | P("hostel", "view_all")
    | P("inventory", "view_all")
    | P("transport", "view_all")
    | P("fundraising", "view_all", "receipt")
    | P("reports", "run", "view")
    | ACCOUNTANT_FEES,
    "hr_officer": STAFF_SELF
    | HR_DOCUMENTS
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
    | OFFICER_ACCREDITATION
    | P("placement", "manage")
    | PLACEMENT_OFFICER
    | P("students", "view_all")
    | P("results", "view_all")
    | P("attendance", "view_all")
    | P("alumni", "view_all")
    | P("reports", "run", "view")
    | P("communication", "send")
    | P("events", "organise")
    | OFFICE_NO_DUES,
    "alumni_coordinator": STAFF_SELF
    | P("alumni", "manage")
    | ALUMNI_COORDINATOR
    | P("fundraising", "manage")
    | P("events", "organise")
    | P("communication", "send", "bulk")
    | P("reports", "run", "view"),
    "hostel_warden": STAFF_SELF
    | P("hostel", "manage")
    | P("students", "view")
    | P("attendance", "view")
    | P("fees", "view")
    | P("communication", "send")
    | OFFICE_NO_DUES,
    "hostel_gate_staff": COMMON | P("hostel", "gate", "view"),
    "librarian": STAFF_SELF
    | OFFICER_ACCREDITATION
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
    | P("reports", "run", "view")
    | OFFICE_NO_DUES,
    "inventory_manager": STAFF_SELF
    | P("inventory", "manage")
    | INVENTORY_MANAGER_OPS
    | P("procurement", "quote", "po_approve", "view_all", "create", "update")
    | P("accounting", "view")
    | P("reports", "run", "view"),
    "estate_officer": STAFF_SELF
    | P("facilities", "manage")
    | ESTATE_FACILITIES
    | P("timetable", "view_all")
    | ESTATE_TIMETABLE
    | P("inventory", "indent", "view")
    | P("reports", "run", "view"),
    "security_officer": STAFF_SELF
    | P("facilities", "manage")
    | SECURITY_FACILITIES
    | P("communication", "emergency", "send")
    | P("hostel", "view")
    | P("students", "view")
    | P("users", "view_all"),
    "medical_officer": STAFF_SELF | P("health", "manage") | MEDICAL_HEALTH | P("students", "view"),
    "sports_officer": STAFF_SELF
    | P("sports", "manage")
    | SPORTS_FACILITIES
    | P("clubs", "verify_hours", "view")
    | P("events", "organise")
    | P("students", "view_all")
    | OFFICE_NO_DUES,
    "grievance_officer": STAFF_SELF
    | GRIEVANCE_OFFICER_SUPPORT
    | P("grievances", "triage", "resolve", "escalate", "committee", "view_all", "update", "view")
    | P("students", "view")
    | P("communication", "send"),
    "discipline_committee": STAFF_SELF
    | P("discipline", "manage")
    | P("students", "view")
    | P("hostel", "view")
    | COMMITTEE_EXAMS,
    "committee_secretary": STAFF_SELF
    | COMMITTEE_SUPPORT
    | P("governance", "committees", "minutes", "resolutions", "view", "create", "update")
    | COMMITTEE_EXAMS,
    "legal_officer": STAFF_SELF | P("legal", "manage") | P("efile", "manage") | P("rti", "view"),
    "pio": STAFF_SELF | P("rti", "manage") | P("efile", "view"),
    "receptionist": STAFF_SELF
    | OFFICE_DOCUMENTS
    | P("admissions", "create", "view")
    | P("facilities", "manage")
    | P("students", "view"),
    "driver": COMMON
    | P("transport", "driver", "view")
    | P("payroll", "self")
    | P("leaves", "self", "create", "view")
    | P("attendance", "staff_self"),
    "integration_admin": STAFF_SELF | P("integrations", "manage") | P("jobs", "view_all") | P("audit_logs", "view_all"),
    "college_admin": _COLLEGE_ADMIN | COLLEGE_AFFILIATION,
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
    "vendor": COMMON | VENDOR_PORTAL | CANTEEN_POS,
    "store_keeper": STAFF_SELF | STORE_KEEPER,
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
    | PARENT_SUPPORT
    | PARENT_PLACEMENT
    | PARENT_DOCUMENTS
    | SELF_DEGREES
    | PARENT_LIBRARY
    | PARENT_FACILITIES
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
    | P("transport", "view")
    | PARENT_FEES
    | PARENT_LMS
    | PARENT_EXAMS,
    "alumni": COMMON
    | SELF_DEGREES
    | P("alumni", "self")
    | P("certificates", "self")
    | P("results", "transcript", "self")
    | P("placement", "self")
    | P("fundraising", "view")
    | P("events", "view")
    | P("communication", "view"),
    "applicant": COMMON | P("admissions", "create", "view") | P("fees", "self") | P("communication", "view"),
}

# Phase 35 (Prompts/35 "Visibility rules"): dashboards never widen visibility — ``analytics:view`` only opens the chart
# catalogue / Insights; every provider still narrows rows through the module's own scope. Office roles read their module
# charts (``<module>:view_all`` decides which), registrar / principal / IQAC / accountant / college admin export, the
# registrar and institution admin manage read models (refresh) — ``analytics:manage``.
ANALYTICS_READ: set[str] = P("analytics", "view")
ANALYTICS_EXPORT: set[str] = P("analytics", "view", "export")
ANALYTICS_ADMIN: set[str] = P("analytics", "view", "export", "manage")
PHASE35_GRANTS: dict[str, set[str]] = {
    "institution_admin": ANALYTICS_ADMIN,
    "registrar": ANALYTICS_ADMIN,
    "vice_chancellor": ANALYTICS_EXPORT,
    "iqac_coordinator": ANALYTICS_EXPORT,
    "accountant": ANALYTICS_EXPORT,
    "college_admin": ANALYTICS_EXPORT,
    "controller_of_examinations": ANALYTICS_READ,
    "exam_cell": ANALYTICS_READ,
    "dean": ANALYTICS_READ,
    "hod": ANALYTICS_READ,
    "faculty": ANALYTICS_READ,
    "class_advisor": ANALYTICS_READ,
    "research_guide": ANALYTICS_READ,
    "hr_officer": ANALYTICS_READ,
    "admissions_officer": ANALYTICS_READ,
    "placement_officer": ANALYTICS_READ,
    "hostel_warden": ANALYTICS_READ,
    "librarian": ANALYTICS_READ,
    "transport_manager": ANALYTICS_READ,
    "estate_officer": ANALYTICS_READ,
    "research_cell": ANALYTICS_READ,
    "alumni_coordinator": ANALYTICS_READ,
}
for _slug, _extra in PHASE35_GRANTS.items():
    if "*:*" not in ROLE_TEMPLATES[_slug]:
        ROLE_TEMPLATES[_slug] = ROLE_TEMPLATES[_slug] | _extra  # new set: templates may share base sets

# Phase 36 (Prompts/36 "Visibility rules"): ``reports:view`` opens the catalogue, ``reports:run`` runs / previews /
# builds (rows still narrowed by every provider to the caller's module scope), ``reports:schedule`` schedules (private
# for faculty), ``reports:statutory`` the statutory workspace (generation per code is limited to its sign-off roles +
# registrar / IQAC / principal), ``reports:view_all`` sees every run, ``reports:manage`` shares saved reports / edits
# others' schedules / reads the access log.
REPORTS_READ: set[str] = P("reports", "view", "run")
REPORTS_SCHEDULE: set[str] = P("reports", "view", "run", "schedule")
REPORTS_STATUTORY: set[str] = P("reports", "view", "run", "schedule", "statutory")
PHASE36_GRANTS: dict[str, set[str]] = {
    "registrar": REPORTS_STATUTORY | P("reports", "view_all"),
    "vice_chancellor": REPORTS_STATUTORY,
    "iqac_coordinator": REPORTS_STATUTORY,
    "controller_of_examinations": REPORTS_SCHEDULE,
    "exam_cell": REPORTS_SCHEDULE,
    "dean": REPORTS_SCHEDULE,
    "hod": REPORTS_SCHEDULE,
    "faculty": REPORTS_SCHEDULE,
    "class_advisor": REPORTS_SCHEDULE,
    "research_guide": REPORTS_SCHEDULE,
    "accountant": REPORTS_STATUTORY,
    "hr_officer": REPORTS_SCHEDULE,
    "admissions_officer": REPORTS_SCHEDULE,
    "placement_officer": REPORTS_STATUTORY,
    "librarian": REPORTS_SCHEDULE,
    "hostel_warden": REPORTS_SCHEDULE,
    "transport_manager": REPORTS_SCHEDULE,
    "inventory_manager": REPORTS_SCHEDULE,
    "estate_officer": REPORTS_SCHEDULE,
    "alumni_coordinator": REPORTS_SCHEDULE,
    "research_cell": REPORTS_STATUTORY,
    "pio": REPORTS_STATUTORY,
    "auditor": P("reports", "statutory"),
}
for _slug, _extra in PHASE36_GRANTS.items():
    if "*:*" not in ROLE_TEMPLATES[_slug]:
        ROLE_TEMPLATES[_slug] = ROLE_TEMPLATES[_slug] | _extra  # new set: templates may share base sets

# Phase 37 (Prompts/37 "Visibility rules"): every user reads their own audit rows (``audit_logs:view`` → ``/audit-logs/me``
# and the self tab); ``audit_logs:view_all`` widens by scope (HOD department, college admin college, registrar /
# principal / auditor all — IQAC aggregates only); ``audit_logs:security`` opens the security console; ``exams:audit``
# the per-session exam audit (decode events only with ``exams:decode`` / institution admin / auditor); the principal
# manages settings; the auditor verifies the chain (read-only everywhere else).
AUDIT_SELF: set[str] = P("audit_logs", "view")
PHASE37_GRANTS: dict[str, set[str]] = {
    "registrar": P("audit_logs", "view_all", "security") | P("exams", "audit") | P("settings", "view"),
    "vice_chancellor": P("audit_logs", "view_all", "security") | P("exams", "audit") | P("settings", "view", "manage"),
    "controller_of_examinations": P("exams", "audit") | P("settings", "view"),
    "exam_cell": P("exams", "audit") | P("settings", "view"),
    "hod": P("audit_logs", "view_all") | P("settings", "view"),
    "dean": P("audit_logs", "view_all") | P("settings", "view"),
    "security_officer": P("audit_logs", "security") | P("settings", "view"),
    "iqac_coordinator": P("settings", "view"),
    "auditor": P("audit_logs", "view_all", "verify_chain", "security") | P("exams", "audit") | P("settings", "view"),
}
for _slug in ROLE_TEMPLATES:
    if "*:*" not in ROLE_TEMPLATES[_slug]:
        ROLE_TEMPLATES[_slug] = ROLE_TEMPLATES[_slug] | AUDIT_SELF | PHASE37_GRANTS.get(_slug, set())

# Phase 38 (Prompts/38 "Visibility rules"): tenant institution admins hold ``support:manage`` through their
# ``ALL("manage")`` (raise, reply, close own tickets); integration and college admins may raise tickets
# (``support:create``); the support agent reads every tenant (``support:view_all``, masked) and works the desk
# (``platform:support``) — ``platform:*`` is never granted to a tenant role.
SUPPORT_RAISE: set[str] = P("support", "create", "view")
PHASE38_GRANTS: dict[str, set[str]] = {
    "integration_admin": SUPPORT_RAISE,
    "college_admin": SUPPORT_RAISE,
    "support_agent": P("support", "view_all", "create", "update"),
}
for _slug, _extra in PHASE38_GRANTS.items():
    ROLE_TEMPLATES[_slug] = ROLE_TEMPLATES[_slug] | _extra

# Phase 40 (Prompts/40 "Visibility rules"): the registrar runs the website (``manage`` + ``publish``); college admins
# edit their ``college:{code}`` sub-site and HODs their ``department:{code}`` pages (section scope checked in the
# service); IQAC edits the disclosures; admissions officers / receptionists read enquiries through ``admissions:create``
# (Phase 08 CRM); auditors read (``website:view`` via ``ALL("view")``). Institution admins hold it via ``ALL("manage")``.
WEBSITE_EDITOR: set[str] = P("website", "view", "create", "update")
PHASE40_GRANTS: dict[str, set[str]] = {
    "registrar": P("website", "view", "view_all", "create", "update", "delete", "manage", "publish"),
    "college_admin": WEBSITE_EDITOR | P("website", "publish"),
    "hod": WEBSITE_EDITOR,
    "iqac_coordinator": WEBSITE_EDITOR | P("accreditation", "manage"),
    "admissions_officer": P("website", "view"),
}
for _slug, _extra in PHASE40_GRANTS.items():
    ROLE_TEMPLATES[_slug] = ROLE_TEMPLATES[_slug] | _extra

# Phase 43 (Prompts/43 "Visibility rules"): the privacy officer runs notices / consent reports / DSRs; the security
# officer owns the posture dashboard; auditors read both (``ALL("view")``); institution admins hold everything via
# ``ALL("manage")``; record owners fulfil DSR correction work items through their own ``<module>:update``.
PRIVACY_OFFICE: set[str] = P("privacy", "view", "view_all", "create", "update", "manage")
PHASE43_GRANTS: dict[str, set[str]] = {
    "institution_admin": P("privacy", "manage") | P("security", "manage") | P("qa", "manage", "run"),
    "security_officer": P("security", "view", "view_all", "manage") | P("privacy", "view") | P("qa", "view", "run"),
    "auditor": P("privacy", "view", "view_all") | P("security", "view", "view_all") | P("qa", "view"),
}
ROLE_TEMPLATES["privacy_officer"] = (
    STAFF_SELF
    | PRIVACY_OFFICE
    | P("settings", "view")
    | P("audit_logs", "view_all")
    | P("users", "view_all")
    | P("students", "view_pii")
    | P("security", "view")
)
for _slug, _extra in PHASE43_GRANTS.items():
    ROLE_TEMPLATES[_slug] = ROLE_TEMPLATES[_slug] | _extra

# ---- import-time invariants ------------------------------------------------------------------------------------
assert set(ROLE_TEMPLATES) == set(ROLE_SLUGS), "ROLE_TEMPLATES must cover exactly the 54 role templates"
for _slug, _grants in ROLE_TEMPLATES.items():
    _unknown = {g for g in _grants if g != "*:*" and g not in PERMISSIONS}
    assert not _unknown, f"role template {_slug} cites unknown permissions: {sorted(_unknown)}"


# Grants added to templates by a later phase that must also reach the roles already cloned into tenants (revision
# ``0003`` backfills them; grants an administrator removed afterwards are not re-added by later revisions).
BACKFILL_GRANTS: dict[str, frozenset[str]] = {
    "0043": frozenset(PHASE43_GRANTS["institution_admin"] | PHASE43_GRANTS["security_officer"] | PHASE43_GRANTS["auditor"]),
    "0040": frozenset(PHASE40_GRANTS["registrar"] | PHASE40_GRANTS["college_admin"] | PHASE40_GRANTS["iqac_coordinator"]),
    "0038": frozenset(SUPPORT_RAISE | P("support", "manage")),
    "0037": frozenset(AUDIT_SELF | P("exams", "audit") | P("audit_logs", "security") | P("settings", "view")),
    "0036": frozenset(REPORTS_STATUTORY | P("reports", "view_all")),
    "0035": frozenset(ANALYTICS_ADMIN),
    "0034": frozenset(
        REGISTRAR_AFFILIATION
        | VC_AFFILIATION
        | COE_AFFILIATION
        | COLLEGE_AFFILIATION
        | STAFF_AFFILIATION
        | ACCOUNTANT_AFFILIATION
    ),
    "0033": frozenset(
        STAFF_GOVERNANCE | STUDENT_GOVERNANCE | REGISTRAR_GOVERNANCE | VC_GOVERNANCE | ACCOUNTANT_GOVERNANCE
    ),
    "0032": frozenset(FACULTY_ACCREDITATION | HOD_ACCREDITATION | PRINCIPAL_ACCREDITATION | OFFICER_ACCREDITATION),
    "0031": frozenset(FACULTY_PHD | HOD_PHD | RESEARCH_CELL_PHD | COE_PHD | ACCOUNTANT_PHD),
    "0030": frozenset(RESEARCH_CELL | HOD_RESEARCH | READ_RESEARCH),
    "0029": frozenset(ALUMNI_COORDINATOR | HOD_ALUMNI | READ_ALUMNI),
    "0028": frozenset(
        PLACEMENT_OFFICER | HOD_PLACEMENT | FACULTY_PLACEMENT | PARENT_PLACEMENT | READ_PLACEMENT | ACCOUNTANT_PLACEMENT
    ),
    "0027": frozenset(
        STAFF_SUPPORT
        | COMMITTEE_SUPPORT
        | HOD_SUPPORT
        | REGISTRAR_SUPPORT
        | VC_SUPPORT
        | GRIEVANCE_OFFICER_SUPPORT
        | PARENT_SUPPORT
    ),
    "0026": frozenset(
        REGISTRAR_DOCUMENTS | HR_DOCUMENTS | COE_DOCUMENTS | HOD_DOCUMENTS | OFFICE_DOCUMENTS | PARENT_DOCUMENTS
    ),
    "0003": frozenset({"institutions:view"}),
    "0005": frozenset(ACADEMIC_READ | REGISTRAR_ACADEMICS | HOD_ACADEMICS | DEAN_ACADEMICS),
    "0006": frozenset(P("leaves", "encash") | DEAN_HR | AUDITOR_HR),
    "0007": frozenset(STUDENTS_ADMIN_PII | HOD_STUDENTS),
    "0008": frozenset(ADMISSIONS_STAFF_READ | HOD_ADMISSIONS | ADMISSIONS_PII),
    "0009": frozenset(REGISTRAR_REGISTRATION | DEAN_OFFERINGS),
    "0010": frozenset(REGISTRAR_TIMETABLE | HOD_TIMETABLE | ESTATE_TIMETABLE | FACULTY_TIMETABLE),
    "0011": frozenset(REGISTRAR_ATTENDANCE | HOD_ATTENDANCE | COE_ATTENDANCE | VC_ATTENDANCE),
    "0025": frozenset(
        HOD_FACILITIES
        | REGISTRAR_FACILITIES
        | VC_FACILITIES
        | FACULTY_EVENTS
        | ESTATE_FACILITIES
        | SECURITY_FACILITIES
        | MEDICAL_HEALTH
        | SPORTS_FACILITIES
        | ACCOUNTANT_FACILITIES
        | STAFF_CAMPUS
        | PARENT_FACILITIES
        | CANTEEN_POS
    ),
    "0024": frozenset(REGISTRAR_COMMS | VC_COMMS | HOD_COMMS),
    "0023": frozenset(HOD_ACCOUNTING | FACULTY_ACCOUNTING | ACCOUNTANT_ACCOUNTING | VC_ACCOUNTING | IQAC_ACCOUNTING),
    "0022": frozenset(STORE_KEEPER | INVENTORY_MANAGER_OPS | ACCOUNTANT_PROCUREMENT | VC_PROCUREMENT | VENDOR_PORTAL),
    "0021": frozenset(HOD_TRANSPORT | STAFF_TRANSPORT),
    "0020": frozenset(REGISTRAR_HOSTEL | HOD_HOSTEL | ADVISOR_HOSTEL),
    "0019": frozenset(PARENT_LIBRARY | HOD_LIBRARY),
    "0018": frozenset(SELF_DEGREES | REGISTRAR_DEGREES | HOD_DEGREES),
    "0017": frozenset(FACULTY_OBE | DEAN_ATTAINMENT | IQAC_OBE | STUDENT_OBE),
    "0016": frozenset(REGISTRAR_POST_RESULT | COMMITTEE_EXAMS),
    "0015": frozenset(HOD_RESULTS),
    "0014": frozenset(HOD_EXAMS | FACULTY_QP | PARENT_EXAMS),
    "0013": frozenset(EXAM_CELL_MARKS | HOD_ASSESSMENT | DEAN_OBE | REGISTRAR_MARKS | PARENT_LMS),
    "0012": frozenset(
        REGISTRAR_FEES | VC_FEES | HOD_FEES | ADVISOR_FEES | ACCOUNTANT_FEES | OFFICE_NO_DUES | PARENT_FEES
    ),
}


def template_permissions(slug: str) -> set[str]:
    """Concrete ``module:action`` grants of a template (``*:*`` expands to the whole catalogue)."""
    grants = ROLE_TEMPLATES[slug]
    if "*:*" in grants:
        return set(PERMISSIONS)
    return set(grants)
