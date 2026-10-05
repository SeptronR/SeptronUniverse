"""Event catalogue of the communication core — Prompts/04 §04.6.

Every event a module may notify about, with its preference **category**, default channels and the platform default
template (seeded by revision ``0004`` as ``notification_templates`` rows with ``institution_id`` NULL). Bodies are
Jinja2 (rendered sandboxed, ``StrictUndefined`` over ``variables``). ``hi`` bodies are shipped where the IN pack
supplies them; other languages fall back to ``en``. Categories drive ``notification_preferences``; ``MANDATORY``
categories (security, emergency) ignore a user's channel opt-outs and quiet hours.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EventDef:
    key: str
    category: str
    name: str
    subject: str
    body: str
    variables: tuple[str, ...] = ()
    channels: tuple[str, ...] = ("in_app",)
    hi_body: str | None = None
    link: str | None = None  # client route template, e.g. "/announcements/{{ announcement_id }}"
    extra: dict[str, str] = field(default_factory=dict)


CATEGORIES = (
    "security",
    "announcements",
    "approvals",
    "admissions",
    "academics",
    "attendance",
    "fees",
    "exams",
    "hostel",
    "library",
    "placement",
    "mentoring",
    "grievances",
    "hr",
    "emergency",
)
MANDATORY_CATEGORIES = frozenset({"security", "emergency"})

EVENTS: tuple[EventDef, ...] = (
    EventDef(
        "auth.password_reset",
        "security",
        "Password reset",
        "Reset your password",
        "Use this link to reset your password: {{ reset_url }} (valid {{ ttl_minutes }} minutes).",
        ("reset_url", "ttl_minutes"),
        ("email",),
    ),
    EventDef(
        "auth.otp",
        "security",
        "Sign-in code",
        "Your sign-in code",
        "Your SeptronUniverse sign-in code is {{ code }}. It expires in {{ ttl_minutes }} minutes.",
        ("code", "ttl_minutes"),
        ("sms", "email"),
        hi_body="आपका SeptronUniverse साइन-इन कोड {{ code }} है। यह {{ ttl_minutes }} मिनट में समाप्त होगा।",
    ),
    EventDef(
        "auth.welcome",
        "security",
        "Welcome",
        "Welcome to {{ institution_name }}",
        "Hello {{ name }}, your {{ institution_name }} account {{ username }} is ready.",
        ("name", "institution_name", "username"),
        ("email", "in_app"),
    ),
    EventDef(
        "announcement.published",
        "announcements",
        "Announcement",
        "{{ title }}",
        "{{ title }} — {{ summary }}",
        ("title", "summary", "announcement_id"),
        ("in_app", "push"),
        hi_body="{{ title }} — {{ summary }}",
        link="/announcements/{{ announcement_id }}",
    ),
    EventDef(
        "workflow.step_pending",
        "approvals",
        "Approval pending",
        "Approval needed: {{ title }}",
        "{{ requester }} is waiting for your approval: {{ title }}.",
        ("title", "requester", "instance_id"),
        ("in_app", "push", "email"),
        link="/approvals?instance={{ instance_id }}",
    ),
    EventDef(
        "workflow.approved",
        "approvals",
        "Request approved",
        "Approved: {{ title }}",
        "Your request “{{ title }}” was approved.",
        ("title", "instance_id"),
        ("in_app", "push"),
        hi_body="आपका अनुरोध “{{ title }}” स्वीकृत हो गया है।",
        link="/approvals/instances/{{ instance_id }}",
    ),
    EventDef(
        "workflow.rejected",
        "approvals",
        "Request rejected",
        "Rejected: {{ title }}",
        "Your request “{{ title }}” was rejected{% if comment %}: {{ comment }}{% endif %}.",
        ("title", "comment", "instance_id"),
        ("in_app", "push"),
        link="/approvals/instances/{{ instance_id }}",
    ),
    EventDef(
        "workflow.escalated",
        "approvals",
        "Approval escalated",
        "Escalated: {{ title }}",
        "“{{ title }}” passed its SLA and was escalated to you.",
        ("title", "instance_id"),
        ("in_app", "push", "email"),
        link="/approvals?instance={{ instance_id }}",
    ),
    EventDef(
        "admissions.status_changed",
        "admissions",
        "Application status",
        "Application {{ application_no }}",
        "Your application {{ application_no }} is now {{ status }}.",
        ("application_no", "status"),
        ("in_app", "sms", "email"),
    ),
    EventDef(
        "registration.approved",
        "academics",
        "Registration approved",
        "Course registration approved",
        "Your course registration for {{ term }} was approved.",
        ("term",),
        ("in_app", "push"),
    ),
    EventDef(
        "attendance.absent_alert",
        "attendance",
        "Absence alert",
        "Absent today",
        "{{ student_name }} was marked absent for {{ course }} on {{ date }}.",
        ("student_name", "course", "date"),
        ("sms", "push"),
        hi_body="{{ student_name }} {{ date }} को {{ course }} में अनुपस्थित रहे।",
    ),
    EventDef(
        "attendance.below_threshold",
        "attendance",
        "Attendance below threshold",
        "Attendance warning",
        "Attendance in {{ course }} is {{ percentage }}% (minimum {{ minimum }}%).",
        ("course", "percentage", "minimum"),
        ("in_app", "sms", "push"),
    ),
    EventDef(
        "fees.invoice_created",
        "fees",
        "Fee invoice",
        "Invoice {{ invoice_no }}",
        "Invoice {{ invoice_no }} of {{ amount }} is due on {{ due_date }}.",
        ("invoice_no", "amount", "due_date"),
        ("in_app", "sms", "email"),
    ),
    EventDef(
        "fees.payment_received",
        "fees",
        "Payment received",
        "Receipt {{ receipt_no }}",
        "We received {{ amount }} (receipt {{ receipt_no }}). Thank you.",
        ("amount", "receipt_no"),
        ("in_app", "sms", "email"),
        hi_body="{{ amount }} प्राप्त हुए (रसीद {{ receipt_no }})। धन्यवाद।",
    ),
    EventDef(
        "fees.due_reminder",
        "fees",
        "Fee reminder",
        "Fee due {{ due_date }}",
        "{{ amount }} is due on {{ due_date }}.",
        ("amount", "due_date"),
        ("sms", "push"),
    ),
    EventDef(
        "exams.hall_ticket_ready",
        "exams",
        "Hall ticket ready",
        "Hall ticket for {{ exam }}",
        "Your hall ticket for {{ exam }} is ready to download.",
        ("exam",),
        ("in_app", "push", "sms"),
    ),
    EventDef(
        "results.published",
        "exams",
        "Results published",
        "{{ exam }} results",
        "Results of {{ exam }} are published.",
        ("exam",),
        ("in_app", "push", "sms"),
        hi_body="{{ exam }} के परिणाम प्रकाशित हो गए हैं।",
    ),
    EventDef(
        "results.reval_decided",
        "exams",
        "Revaluation decided",
        "Revaluation of {{ course }}",
        "The revaluation of {{ course }} is complete: {{ outcome }}.",
        ("course", "outcome"),
        ("in_app", "sms"),
    ),
    EventDef(
        "hostel.leave_decided",
        "hostel",
        "Hostel leave",
        "Leave {{ status }}",
        "Leave from {{ from_date }} to {{ to_date }} was {{ status }}.",
        ("from_date", "to_date", "status"),
        ("in_app", "sms"),
    ),
    EventDef(
        "hostel.late_return",
        "hostel",
        "Late return",
        "Late return",
        "{{ student_name }} returned late to the hostel at {{ time }}.",
        ("student_name", "time"),
        ("sms",),
    ),
    EventDef(
        "library.due_reminder",
        "library",
        "Library due",
        "Book due {{ due_date }}",
        "“{{ book }}” is due on {{ due_date }}.",
        ("book", "due_date"),
        ("in_app", "push"),
    ),
    EventDef(
        "placement.drive_published",
        "placement",
        "Placement drive",
        "{{ company }} drive",
        "{{ company }} is hiring: apply by {{ deadline }}.",
        ("company", "deadline"),
        ("in_app", "push", "email"),
    ),
    EventDef(
        "placement.offer_received",
        "placement",
        "Offer received",
        "Offer from {{ company }}",
        "Congratulations! {{ company }} has made you an offer.",
        ("company",),
        ("in_app", "push", "email"),
    ),
    EventDef(
        "mentoring.meeting_scheduled",
        "mentoring",
        "Mentoring meeting",
        "Meeting on {{ date }}",
        "Your mentor scheduled a meeting on {{ date }} at {{ time }}.",
        ("date", "time"),
        ("in_app", "push"),
    ),
    EventDef(
        "grievance.updated",
        "grievances",
        "Grievance update",
        "Grievance {{ ticket_no }}",
        "Your grievance {{ ticket_no }} is now {{ status }}.",
        ("ticket_no", "status"),
        ("in_app", "email"),
    ),
    EventDef(
        "emergency.alert",
        "emergency",
        "Emergency alert",
        "EMERGENCY: {{ title }}",
        "{{ message }}",
        ("title", "message"),
        ("in_app", "push", "sms"),
        hi_body="आपातकाल: {{ message }}",
    ),
    # ---- Phase 06: HR (category ``hr``) ------------------------------------------------------------------------
    EventDef(
        "leave.approved",
        "hr",
        "Leave approved",
        "Leave approved: {{ leave_type }}",
        "Your {{ leave_type }} from {{ from_date }} to {{ to_date }} ({{ days }} day(s)) was approved.",
        ("leave_type", "from_date", "to_date", "days"),
        ("in_app", "push", "email"),
        hi_body="आपकी {{ leave_type }} ({{ from_date }} – {{ to_date }}) स्वीकृत हो गई है।",
        link="/me?tab=leaves",
    ),
    EventDef(
        "leave.rejected",
        "hr",
        "Leave rejected",
        "Leave not approved: {{ leave_type }}",
        "Your {{ leave_type }} from {{ from_date }} to {{ to_date }} was not approved. {{ comment }}",
        ("leave_type", "from_date", "to_date", "comment"),
        ("in_app", "push", "email"),
        link="/me?tab=leaves",
    ),
    EventDef(
        "payroll.payslip_ready",
        "hr",
        "Payslip ready",
        "Payslip for {{ period }}",
        "Your payslip for {{ period }} is ready. Net pay: {{ net }}.",
        ("period", "net"),
        ("in_app", "push", "email"),
        link="/me?tab=payslips",
    ),
    EventDef(
        "payroll.reminder",
        "hr",
        "Payroll reminder",
        "Payroll for {{ period }}",
        "Payroll for {{ period }} has not been generated yet ({{ pending }} staff pending).",
        ("period", "pending"),
        ("in_app", "email"),
        link="/admin/hr/payroll",
    ),
    EventDef(
        "staff.welcome",
        "security",
        "Staff account created",
        "Your staff account",
        "Welcome {{ name }}! Employee id {{ employee_id }}. Your SeptronUniverse username is {{ username }}; the HR "
        "office hands over your temporary password — you will be asked to change it at the first sign-in.",
        ("name", "employee_id", "username"),
        ("email",),
    ),
    EventDef(
        "hr.document_expiring",
        "hr",
        "Document expiring",
        "{{ doc_type }} expires on {{ expires_on }}",
        "The {{ doc_type }} of {{ staff_name }} expires on {{ expires_on }}. Please upload a renewed copy.",
        ("doc_type", "expires_on", "staff_name"),
        ("in_app", "email"),
    ),
    EventDef(
        "recruitment.posted",
        "hr",
        "Job posting published",
        "New opening: {{ title }}",
        "{{ title }} ({{ vacancies }} post(s)) is open for applications until {{ closes_at }}.",
        ("title", "vacancies", "closes_at"),
        ("in_app",),
        link="/careers",
    ),
    EventDef(
        "recruitment.application_received",
        "hr",
        "Application received",
        "Application received: {{ title }}",
        "Dear {{ name }}, we received your application for {{ title }}. Reference: {{ reference }}.",
        ("name", "title", "reference"),
        ("email",),
    ),
)

BY_KEY: dict[str, EventDef] = {e.key: e for e in EVENTS}


def category_of(event_type: str) -> str:
    ev = BY_KEY.get(event_type)
    if ev is not None:
        return ev.category
    prefix = event_type.split(".", 1)[0]
    return {"workflow": "approvals", "announcement": "announcements", "auth": "security"}.get(prefix, prefix)[:40]
