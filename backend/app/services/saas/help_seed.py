"""Platform help articles seeded by revision ``0038`` — Prompts/38 §38.2 (≈ 60: one per module with its contextual
slug ``help:<route>`` + a getting-started article per role family). Platform articles (``institution_id`` NULL) are
read by every tenant; an institution article with the same slug overrides one for that tenant only. The same list is
the JSON ``/help/admin/import`` format, so ``docs/help`` exports round-trip.
"""

from typing import Any

# module key → (title, client route, what it covers, first steps)
MODULES: dict[str, tuple[str, str, str, list[str]]] = {
    "institutions": (
        "Institution profile and structure",
        "/admin/institution",
        "colleges, faculties, departments, holidays and academic years",
        [
            "Complete the profile and statutory identifiers",
            "Add colleges / departments",
            "Create the academic year and its terms",
        ],
    ),
    "users": (
        "Users and roles",
        "/admin/users",
        "accounts, role assignments with scopes, credential sheets",
        [
            "Invite staff or import them",
            "Assign roles with the right scope",
            "Print credential sheets for first sign-in",
        ],
    ),
    "features": (
        "Features and entitlements",
        "/admin/settings/features",
        "which modules your plan includes and institution switches",
        ["Review the plan's features", "Switch optional modules on or off", "Check limits on the entitlements page"],
    ),
    "settings": (
        "Settings",
        "/admin/settings",
        "the typed settings catalogue, locks, history and import / export",
        ["Search a setting", "Give a reason for sensitive changes", "Use history to undo a change"],
    ),
    "programs": (
        "Programmes and batches",
        "/admin/programs",
        "programmes, intakes and batches",
        ["Create a programme with its duration", "Open a batch per intake", "Attach the regulation"],
    ),
    "regulations": (
        "Regulations and curricula",
        "/admin/regulations",
        "regulations, course structure, credits and grading",
        ["Clone the previous regulation", "Edit the structure per term", "Send it for approval"],
    ),
    "courses": (
        "Course catalogue",
        "/admin/courses",
        "courses, credits, outcomes and the public catalogue",
        ["Add courses with L-T-P", "Map outcomes", "Publish to the catalogue"],
    ),
    "offerings": (
        "Course offerings",
        "/admin/offerings",
        "per-term offerings, sections and faculty allocation",
        ["Bulk-create offerings for the term", "Allocate faculty", "Set capacities"],
    ),
    "registration": (
        "Course registration",
        "/admin/registration",
        "windows, electives, allocation and add / drop",
        ["Open a registration window", "Run elective allocation", "Approve overrides"],
    ),
    "timetable": (
        "Timetable",
        "/admin/timetable",
        "slots, rooms, generation and substitutions",
        ["Define slots and rooms", "Generate a draft", "Publish and handle substitutions"],
    ),
    "attendance": (
        "Attendance",
        "/admin/attendance",
        "marking, QR / biometric, condonation and eligibility",
        ["Mark a session", "Review shortages", "Process condonation"],
    ),
    "marks": (
        "Internal assessment",
        "/admin/assessment",
        "assessment schemes, marks entry, verification and locks",
        ["Configure the scheme", "Enter and verify marks", "Lock for consolidation"],
    ),
    "exams": (
        "Examinations",
        "/admin/exams",
        "sessions, registration, hall tickets, seating and valuation",
        ["Create the exam session", "Generate hall tickets", "Plan seating and invigilation"],
    ),
    "results": (
        "Results",
        "/admin/results",
        "result processing, moderation, publication and revaluation",
        ["Run a result computation", "Verify and approve", "Publish to students"],
    ),
    "degrees": (
        "Degrees and convocation",
        "/admin/degrees",
        "eligibility, degree award and certificates",
        ["Check eligibility", "Award with the council resolution", "Issue certificates"],
    ),
    "obe": (
        "Outcome-based education",
        "/admin/obe",
        "CO / PO mapping and attainment",
        ["Map COs to POs", "Configure targets", "Compute attainment"],
    ),
    "lms": (
        "Learning management",
        "/staff/lms",
        "course pages, assignments and grading",
        ["Publish course material", "Create an assignment", "Grade submissions"],
    ),
    "admissions": (
        "Admissions",
        "/admin/admissions",
        "cycles, applications, merit lists and seat allotment",
        ["Open a cycle", "Verify documents", "Publish merit lists and allot seats"],
    ),
    "students": (
        "Student records",
        "/admin/students",
        "the student master, enrolments, holds and ID cards",
        ["Search a student", "Update records with a reason", "Place or release holds"],
    ),
    "hr": (
        "Staff and HR",
        "/admin/staff",
        "staff master, service book, appraisals and recruitment",
        ["Add staff", "Maintain the service book", "Run appraisals"],
    ),
    "leaves": (
        "Leave management",
        "/staff/leaves",
        "leave types, balances and approvals",
        ["Apply for leave", "Approve requests", "Review balances"],
    ),
    "payroll": (
        "Payroll",
        "/admin/payroll",
        "salary structures, payroll runs and statutory deductions",
        ["Configure structures", "Generate the month's payroll", "Mark paid and publish payslips"],
    ),
    "fees": (
        "Fees and collection",
        "/admin/fees/collect",
        "fee structures, invoices, collection, online payments and refunds",
        ["Define the fee structure", "Collect at the counter or online", "Reconcile the day-book"],
    ),
    "scholarships": (
        "Scholarships",
        "/admin/scholarships",
        "schemes, verification, sanction and disbursement",
        ["Verify applications", "Sanction", "Disburse"],
    ),
    "no_dues": (
        "No-dues",
        "/admin/no-dues",
        "clearance requests across departments",
        ["Raise a request", "Clear per department", "Issue the certificate"],
    ),
    "hostel": (
        "Hostels",
        "/admin/hostel",
        "allotment, mess, gate pass and discipline",
        ["Allot rooms", "Run roll call", "Manage leave and gate passes"],
    ),
    "library": (
        "Library",
        "/admin/library",
        "catalogue, circulation, fines and members",
        ["Catalogue books", "Issue and return", "Collect fines"],
    ),
    "transport": (
        "Transport",
        "/admin/transport",
        "routes, stops, vehicles, passes and GPS",
        ["Set routes and stops", "Issue passes", "Track vehicles"],
    ),
    "inventory": (
        "Inventory and procurement",
        "/admin/inventory",
        "stores, indents, purchase orders and assets",
        ["Raise an indent", "Approve and order", "Receive and issue stock"],
    ),
    "accounting": (
        "Accounting",
        "/admin/accounting",
        "ledgers, vouchers, budgets and bank reconciliation",
        ["Post vouchers", "Reconcile the bank", "Review budgets"],
    ),
    "communication": (
        "Communication",
        "/admin/communication",
        "announcements, SMS / WhatsApp / e-mail and campaigns",
        ["Write an announcement", "Choose the audience", "Check delivery logs"],
    ),
    "calendar": (
        "Calendar and events",
        "/admin/calendar",
        "the institutional calendar, events and bookings",
        ["Add events", "Book facilities", "Share calendars"],
    ),
    "facilities": (
        "Facilities and service desk",
        "/admin/facilities",
        "rooms, bookings, maintenance requests and counselling",
        ["Book a facility", "Raise a service request", "Track SLAs"],
    ),
    "certificates": (
        "Documents and certificates",
        "/admin/documents",
        "templates, requests, issuance and verification",
        ["Design a template", "Approve requests", "Issue with QR verification"],
    ),
    "grievances": (
        "Grievances",
        "/admin/grievances",
        "grievance intake, committees and escalation",
        ["Triage a grievance", "Route to the committee", "Resolve and close"],
    ),
    "mentoring": (
        "Mentoring and student support",
        "/staff/mentoring",
        "mentor allocation, sessions and early warning",
        ["Review mentees", "Record sessions", "Act on risk flags"],
    ),
    "placement": (
        "Placements and internships",
        "/admin/placement",
        "drives, eligibility, offers and internships",
        ["Create a drive", "Publish eligibility", "Record offers"],
    ),
    "alumni": (
        "Alumni",
        "/admin/alumni",
        "the alumni directory, verification, events and fundraising",
        ["Verify alumni", "Run a campaign", "Record donations"],
    ),
    "research": (
        "Research",
        "/admin/research",
        "publications, projects, patents and MoUs",
        ["Record publications", "Track projects", "Verify research records"],
    ),
    "phd": (
        "PhD programme",
        "/admin/phd",
        "scholars, doctoral committees, progress and thesis",
        ["Admit scholars", "Hold DC meetings", "Track thesis submission"],
    ),
    "accreditation": (
        "Accreditation (NAAC / NBA / NIRF)",
        "/admin/accreditation",
        "metrics, evidence and compliance submissions",
        ["Compute metrics", "Attach evidence", "Generate the submission"],
    ),
    "governance": (
        "Governance",
        "/admin/governance",
        "committees, meetings, minutes, resolutions, RTI and e-files",
        ["Schedule a meeting", "Approve minutes", "Track action taken"],
    ),
    "affiliation": (
        "Affiliation",
        "/admin/affiliation",
        "college applications, inspections and data submissions",
        ["Review applications", "Plan inspections", "Decide with the resolution"],
    ),
    "reports": (
        "Reports",
        "/admin/reports",
        "the report catalogue, builder, schedules and statutory reports",
        ["Run a report", "Save a builder query", "Schedule delivery"],
    ),
    "analytics": (
        "Dashboards and analytics",
        "/admin/analytics",
        "role dashboards, KPIs and early warning",
        ["Pin charts", "Set KPI targets", "Review alerts"],
    ),
    "audit_logs": (
        "Audit logs and security",
        "/admin/audit-logs",
        "the audit explorer, chain integrity and the security console",
        ["Filter by module and user", "Verify the chain", "Acknowledge anomalies"],
    ),
    "integrations": (
        "Integrations",
        "/admin/integrations",
        "providers, API keys, webhooks and data imports",
        ["Connect a provider", "Create an API key", "Watch connection health"],
    ),
    "support": (
        "Support and billing",
        "/admin/support",
        "raising tickets, your subscription, invoices and usage",
        ["Raise a ticket with a category", "Reply and rate when resolved", "Pay invoices from Billing"],
    ),
}

# role family → (title, route, what to do first)
ROLES: dict[str, tuple[str, str, list[str]]] = {
    "institution_admin": (
        "Getting started as an institution admin",
        "/admin",
        ["Finish the institution profile", "Invite users and assign roles", "Review features, settings and billing"],
    ),
    "registrar": (
        "Getting started as the registrar",
        "/admin",
        ["Check the academic calendar", "Review admissions and student records", "Watch pending approvals"],
    ),
    "vice_chancellor": (
        "Getting started as the VC / principal",
        "/admin",
        ["Read the dashboard KPIs", "Approve pending decisions", "Review governance and accreditation"],
    ),
    "controller_of_examinations": (
        "Getting started as the COE",
        "/admin/exams",
        ["Create the exam session", "Track readiness", "Approve and publish results"],
    ),
    "hod": (
        "Getting started as a head of department",
        "/admin",
        ["Review department offerings", "Approve leaves and requests", "Track attendance and results"],
    ),
    "dean": ("Getting started as a dean", "/admin", ["Review faculty units", "Approve offerings", "Watch KPIs"]),
    "faculty": (
        "Getting started as faculty",
        "/staff",
        ["Open your timetable", "Mark attendance", "Enter marks and post LMS material"],
    ),
    "accountant": (
        "Getting started in accounts",
        "/admin/fees/collect",
        ["Collect fees", "Reconcile the day-book", "Post vouchers"],
    ),
    "admissions_officer": (
        "Getting started in admissions",
        "/admin/admissions",
        ["Open the cycle", "Verify applications", "Allot seats"],
    ),
    "librarian": (
        "Getting started in the library",
        "/admin/library",
        ["Catalogue books", "Issue / return", "Run reports"],
    ),
    "hostel_warden": (
        "Getting started as a warden",
        "/warden",
        ["Check today's roll call", "Approve leave", "Record discipline"],
    ),
    "placement_officer": (
        "Getting started in placements",
        "/admin/placement",
        ["Create a drive", "Shortlist students", "Record offers"],
    ),
    "iqac_coordinator": (
        "Getting started as the IQAC coordinator",
        "/admin/accreditation",
        ["Review metric values", "Collect evidence", "Prepare submissions"],
    ),
    "integration_admin": (
        "Getting started as the integration admin",
        "/admin/integrations",
        ["Connect SMS / e-mail / payment providers", "Create API keys", "Monitor health"],
    ),
    "college_admin": (
        "Getting started as a college admin",
        "/admin",
        ["Review your college's data", "Submit affiliation data", "Raise support tickets"],
    ),
    "auditor": (
        "Getting started as an auditor",
        "/admin/audit-logs",
        ["Read the audit trail", "Verify the chain", "Export evidence"],
    ),
    "student": (
        "Getting started as a student",
        "/student",
        ["Complete undertakings", "Register for courses", "Check attendance, fees and results"],
    ),
    "parent": (
        "Getting started as a parent",
        "/parent",
        ["Link your ward", "Watch attendance and fees", "Read announcements"],
    ),
    "alumni": ("Getting started as an alumnus", "/alumni", ["Verify your profile", "Join events", "Request documents"]),
    "applicant": (
        "Getting started as an applicant",
        "/applicant",
        ["Fill the application", "Upload documents", "Pay the fee and track status"],
    ),
}


def platform_articles() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for module, (title, route, covers, steps) in MODULES.items():
        body = (
            f"## {title}\n\nThis module covers {covers}.\n\n### First steps\n"
            + "".join(f"{i}. {s}\n" for i, s in enumerate(steps, 1))
            + "\nThe lists follow your visibility scope (Mine | Department | College | All); exports run as background "
            "jobs. Use **Help → Feedback** to tell us what is missing."
        )
        out.append(
            {
                "slug": f"help:{route}",
                "title": title,
                "body": body,
                "module": module,
                "audience": {"roles": [], "portals": [], "public": True},
                "is_published": True,
            }
        )
    for role, (title, route, steps) in ROLES.items():
        body = (
            f"## {title}\n\n"
            + "".join(f"- {s}\n" for s in steps)
            + f"\nYour home page is `{route}`; the sidebar shows what your roles allow."
        )
        out.append(
            {
                "slug": f"getting-started-{role.replace('_', '-')}",
                "title": title,
                "body": body,
                "module": "dashboard",
                "audience": {"roles": [role], "portals": [], "public": False},
                "is_published": True,
            }
        )
    return out
