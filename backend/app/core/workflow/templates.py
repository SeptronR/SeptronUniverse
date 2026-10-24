"""The 18 shipped workflow templates — Prompts/04 §04.6 (stored in ``platform_settings['workflow_templates']`` by
revision ``0004`` and copied into every institution's ``workflow_definitions`` by ``seed_institution_defaults``).

Step spec: ``{order, approver:{type: role|scope_rule|user, value}, mode: sequential|parallel, sla_hours,
escalate_to:{type, value}}`` — several specs with the same ``order`` form one step (parallel mode: every approver
must approve, any reject rejects; sequential: the first approver of the pool decides). Role approvers are resolved
inside the scope the start ``context`` names (``department_id`` → the ``hod`` of that department, ``college_id`` →
college-scoped holders, else institution-scoped holders). "Principal" is the ``vice_chancellor`` template (Vice
Chancellor / Principal); "accounts" the ``accountant``; the academic council secretary the ``committee_secretary``.
"""

from typing import Any


def _role(
    slug: str, order: int = 1, sla: int = 48, mode: str = "sequential", escalate: str | None = None
) -> dict[str, Any]:
    step: dict[str, Any] = {"order": order, "approver": {"type": "role", "value": slug}, "mode": mode, "sla_hours": sla}
    if escalate:
        step["escalate_to"] = {"type": "role", "value": escalate}
    return step


def _chain(*slugs: str, sla: int = 48, escalate: str | None = "vice_chancellor") -> list[dict[str, Any]]:
    return [_role(s, i + 1, sla, escalate=escalate if s != escalate else None) for i, s in enumerate(slugs)]


WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "leave.approval",
        "module": "leaves",
        "name": "Leave approval",
        "steps": _chain("hod", "hr_officer", sla=24),
    },
    {
        "key": "attendance.condonation",
        "module": "attendance",
        "name": "Attendance condonation",
        "steps": _chain("hod", "registrar", "vice_chancellor"),
    },
    {
        "key": "marks.change",
        "module": "marks",
        "name": "Marks change request",
        "steps": _chain("hod", "controller_of_examinations"),
    },
    {
        "key": "registration.advisor",
        "module": "registration",
        "name": "Registration advisor approval",
        "steps": _chain("class_advisor", sla=72, escalate="hod"),
    },
    {
        "key": "procurement.indent",
        "module": "procurement",
        "name": "Purchase indent",
        "steps": _chain("hod", "inventory_manager", "accountant"),
    },
    {
        "key": "procurement.po",
        "module": "procurement",
        "name": "Purchase order",
        "steps": _chain("accountant", "vice_chancellor"),
    },
    {"key": "fees.refund", "module": "fees", "name": "Fee refund", "steps": _chain("accountant", "vice_chancellor")},
    {
        "key": "fees.receipt_cancel",
        "module": "fees",
        "name": "Receipt cancellation",
        "steps": _chain("accountant", "vice_chancellor"),
    },
    {
        "key": "certificates.request",
        "module": "certificates",
        "name": "Certificate request",
        "steps": _chain("registrar", sla=72),
    },
    {
        "key": "regulation.approval",
        "module": "regulations",
        "name": "Regulation approval",
        "steps": _chain("dean", "committee_secretary", sla=168),
    },
    {
        "key": "affiliation.application",
        "module": "affiliation",
        "name": "Affiliation application",
        "steps": [
            _role("registrar", 1, 168),
            {
                "order": 2,
                "approver": {"type": "scope_rule", "value": "context.inspector"},
                "mode": "sequential",
                "sla_hours": 336,
            },
            _role("vice_chancellor", 3, 168),
        ],
    },
    {
        "key": "grievance.escalation",
        "module": "grievances",
        "name": "Grievance escalation",
        "steps": _chain("grievance_officer", "vice_chancellor", sla=72),
    },
    {"key": "event.approval", "module": "events", "name": "Event approval", "steps": _chain("hod", "vice_chancellor")},
    {
        "key": "facilities.room_booking",
        "module": "facilities",
        "name": "Room booking",
        "steps": _chain("estate_officer", sla=24, escalate=None),
    },
    {
        "key": "scholarship.sanction",
        "module": "scholarships",
        "name": "Scholarship sanction",
        "steps": _chain("accountant", "vice_chancellor"),
    },
    {"key": "hr.appraisal", "module": "hr", "name": "Appraisal", "steps": _chain("hod", "hr_officer", sla=168)},
    {
        "key": "phd.request",
        "module": "phd",
        "name": "PhD scholar request",
        "steps": [
            {
                "order": 1,
                "approver": {"type": "scope_rule", "value": "context.guide"},
                "mode": "sequential",
                "sla_hours": 72,
            },
            _role("research_cell", 2, 72),
            _role("dean", 3, 72),
        ],
    },
    {
        "key": "no_dues.clearance",
        "module": "no_dues",
        "name": "No-dues clearance",
        "steps": [
            _role(slug, 1, 72, mode="parallel")
            for slug in ("accountant", "librarian", "hostel_warden", "hod", "inventory_manager", "sports_officer")
        ],
    },
)

# Phase 06 (Prompts/06 §06.7 "Workflows used"): ``leave.approval`` and ``hr.appraisal`` ship with Phase 04; these five
# complete the HR set. ``hr.course_allocation`` is the dean's approval of a department's course-allocation proposal.
HR_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "attendance.regularise",
        "module": "attendance",
        "name": "Staff attendance regularisation",
        "steps": _chain("hod", sla=48, escalate="hr_officer"),
    },
    {"key": "hr.loan", "module": "payroll", "name": "Loan / advance", "steps": _chain("hr_officer", "accountant")},
    {"key": "hr.cas", "module": "hr", "name": "CAS promotion", "steps": _chain("hr_officer", sla=168)},
    {
        "key": "hr.leave_encashment",
        "module": "leaves",
        "name": "Leave encashment",
        "steps": _chain("hr_officer", "accountant"),
    },
    {
        "key": "hr.course_allocation",
        "module": "faculty",
        "name": "Course allocation proposal",
        "steps": _chain("dean", sla=72, escalate=None),
    },
)
# Phase 07 (Prompts/07 §07.7 "Workflows"): transfers / migration (registrar → principal) and credit transfers
# (department verification by the HOD of the student's department → registrar approval).
STUDENT_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "students.transfer",
        "module": "students",
        "name": "Student transfer / migration",
        "steps": _chain("registrar", "vice_chancellor", sla=72),
    },
    {
        "key": "students.credit_transfer",
        "module": "credit_transfers",
        "name": "Credit transfer (MOOC / ABC / prior learning)",
        "steps": _chain("hod", "registrar", sla=120, escalate="registrar"),
    },
)
# Phase 08: an applicant's withdrawal refund (admissions office → accounts; Phase 12 pays it out)
ADMISSION_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "admissions.refund",
        "module": "admissions",
        "name": "Admission withdrawal refund",
        "steps": _chain("admissions_officer", "accountant", sla=72, escalate="registrar"),
    },
)
# Phase 10: a timetable substitution (manual or auto-requested from approved leave) is decided by the HOD of the
# offering's department (``department_id`` in the start context); escalation to the registrar
TIMETABLE_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "timetable.substitution",
        "module": "timetable",
        "name": "Class substitution",
        "steps": _chain("hod", sla=24, escalate="registrar"),
    },
)
# Phase 11: optional on-duty approval by the HOD of the student's department (``attendance.condonation`` ships with
# Prompts/04: HOD → registrar → vice-chancellor)
ATTENDANCE_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "attendance.on_duty",
        "module": "attendance",
        "name": "On-duty request",
        "steps": _chain("hod", sla=48, escalate="registrar"),
    },
)
# Phase 12: concessions (accountant → registrar). ``fees.refund``, ``fees.receipt_cancel``, ``scholarship.sanction`` and
# the parallel ``no_dues.clearance`` ship with Prompts/04.
FEE_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "fees.concession",
        "module": "fees",
        "name": "Fee concession",
        "steps": _chain("accountant", "registrar", sla=72),
    },
)
# Phase 16: transcript issue (registrar verifies dues / holds), readmission of a detained student (registrar) and the
# malpractice appeal (committee secretary → COE). ``marks.change`` is reused for result corrections.
POST_RESULT_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "transcripts.issue",
        "module": "results",
        "name": "Transcript issue",
        "steps": _chain("registrar", sla=72, escalate="vice_chancellor"),
    },
    {
        "key": "students.readmission",
        "module": "students",
        "name": "Readmission after detention",
        "steps": _chain("registrar", sla=120, escalate="vice_chancellor"),
    },
    {
        "key": "malpractice.appeal",
        "module": "exams",
        "name": "Malpractice appeal",
        "steps": _chain("committee_secretary", "controller_of_examinations", sla=168, escalate="vice_chancellor"),
    },
)
# Phase 20: hostel leave and room change (the warden of the hostel — resolved from ``context.warden_user_id``) and the
# eviction (warden → registrar). Guardian consent is a service gate, not a step.
_WARDEN = {"type": "scope_rule", "value": "context.warden_user_id"}
HOSTEL_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "hostel.leave",
        "module": "hostel",
        "name": "Hostel leave / out-pass",
        "steps": [
            {
                "order": 1,
                "approver": _WARDEN,
                "mode": "sequential",
                "sla_hours": 12,
                "escalate_to": {"type": "role", "value": "registrar"},
            }
        ],
    },
    {
        "key": "hostel.room_change",
        "module": "hostel",
        "name": "Hostel room change",
        "steps": [{"order": 1, "approver": _WARDEN, "mode": "sequential", "sla_hours": 72}],
    },
    {
        "key": "hostel.eviction",
        "module": "hostel",
        "name": "Hostel eviction",
        "steps": [
            {"order": 1, "approver": _WARDEN, "mode": "sequential", "sla_hours": 48},
            {
                "order": 2,
                "approver": {"type": "role", "value": "registrar"},
                "mode": "sequential",
                "sla_hours": 72,
                "escalate_to": {"type": "role", "value": "vice_chancellor"},
            },
        ],
    },
)
WORKFLOW_TEMPLATES = (
    WORKFLOW_TEMPLATES
    + HR_WORKFLOW_TEMPLATES
    + STUDENT_WORKFLOW_TEMPLATES
    + ADMISSION_WORKFLOW_TEMPLATES
    + TIMETABLE_WORKFLOW_TEMPLATES
    + ATTENDANCE_WORKFLOW_TEMPLATES
    + FEE_WORKFLOW_TEMPLATES
    + POST_RESULT_WORKFLOW_TEMPLATES
    + HOSTEL_WORKFLOW_TEMPLATES
)

assert len(WORKFLOW_TEMPLATES) == 35, (
    "Prompts/04 ships 18 templates, Prompts/06 adds 5, Prompts/07 2, Prompts/08 1, Prompts/10 1, Prompts/11 1, "
    "Prompts/12 1, Prompts/16 3, Prompts/20 3"
)
