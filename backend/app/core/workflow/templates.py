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

AFFILIATION_APPLICATION_STEPS: list[dict[str, Any]] = []


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
        # Phase 34 type variants (``0034`` stores this as version 2): registrar scrutiny → inspection convenor (only when
        # the type / last-inspection age requires one) → Academic / Executive Council secretaries (autonomy, with
        # ``governance.minutes``) → VC decision
        "steps": AFFILIATION_APPLICATION_STEPS,
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
# Phase 22: vendor bills above ``inventory.bill_approval_threshold_paise`` (the inventory manager verifies before)
INVENTORY_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "procurement.bill",
        "module": "procurement",
        "name": "Vendor bill approval",
        "steps": _chain("accountant", "vice_chancellor"),
    },
)
# Phase 23: manual expenses above ``accounting.expense_approval_threshold_paise`` and budget allocations
ACCOUNTING_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {"key": "accounting.expense", "module": "accounting", "name": "Expense approval", "steps": _chain("accountant", "vice_chancellor")},
    {
        "key": "accounting.budget_allocation",
        "module": "accounting",
        "name": "Budget allocation",
        "steps": _chain("accountant", "vice_chancellor"),
    },
)
# Phase 25: equipment bookings (custodian named in the start context → estate officer) and event budgets (accountant)
FACILITIES_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "facilities.equipment_booking",
        "module": "facilities",
        "name": "Equipment booking",
        "steps": [
            {"order": 1, "approver": {"type": "scope_rule", "value": "context.custodian_user_id"}, "mode": "sequential", "sla_hours": 24},
            _role("estate_officer", 2, 24),
        ],
    },
    {"key": "event.budget", "module": "events", "name": "Event budget", "steps": _chain("accountant", sla=48, escalate=None)},
)
# Phase 27: committee decisions with suspension / expulsion go to the principal (the committee chair decides through the
# case API - ``context.chair_user_id`` records who); appeals are decided by the principal
SUPPORT_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {"key": "discipline.case", "module": "discipline", "name": "Disciplinary decision", "steps": _chain("vice_chancellor", sla=72)},
    {"key": "discipline.appeal", "module": "discipline", "name": "Disciplinary appeal", "steps": _chain("vice_chancellor", sla=168)},
)
# Phase 30: incentives (HOD recommends → research cell → dean only above ``research.incentive_dean_threshold_paise`` —
# ``skip_unless`` reads the start context), project sanction (research cell verifies → principal acknowledges), ethics
# review (the assigned member reviews → the committee chair decides, both named in the start context) and MoUs
# (research cell → legal officer only when ``governance.legal`` is on → principal)
RESEARCH_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "research.incentive",
        "module": "research",
        "name": "Research incentive",
        "steps": [
            _role("hod", 1, 72, escalate="research_cell"),
            _role("research_cell", 2, 72, escalate="vice_chancellor"),
            {**_role("dean", 3, 72, escalate="vice_chancellor"), "skip_unless": "above_threshold"},
        ],
    },
    {
        "key": "research.project_sanction",
        "module": "research",
        "name": "Research project sanction",
        "steps": _chain("research_cell", "vice_chancellor", sla=72),
    },
    {
        "key": "research.ethics_review",
        "module": "research",
        "name": "Ethics review",
        "steps": [
            {"order": 1, "approver": {"type": "scope_rule", "value": "context.reviewer_user_id"}, "mode": "sequential", "sla_hours": 168},
            {"order": 2, "approver": {"type": "scope_rule", "value": "context.chair_user_id"}, "mode": "sequential", "sla_hours": 168},
        ],
    },
    {
        "key": "research.mou",
        "module": "research",
        "name": "MoU approval",
        "steps": [
            _role("research_cell", 1, 72, escalate="vice_chancellor"),
            {**_role("legal_officer", 2, 72, escalate="vice_chancellor"), "skip_unless": "legal_review"},
            _role("vice_chancellor", 3, 72),
        ],
    },
)
# Phase 31: examiner panel (the guide's proposal is the start → dean approves → VC only when ``vc_approval`` is set
# from ``phd.panel_vc_approval``), DC approval of a thesis (the DC members named in the start context approve in
# parallel — empty member slots are skipped — then the convenor) and the award (research cell → dean → academic council
# resolution only when ``governance.minutes`` is on)
PHD_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "phd.examiner_panel",
        "module": "phd",
        "name": "PhD examiner panel",
        "steps": [
            _role("dean", 1, 72, escalate="vice_chancellor"),
            {**_role("vice_chancellor", 2, 72), "skip_unless": "vc_approval"},
        ],
    },
    {
        "key": "phd.thesis_dc_approval",
        "module": "phd",
        "name": "Thesis DC approval",
        "steps": [
            *(
                {
                    "order": 1,
                    "approver": {"type": "scope_rule", "value": f"context.dc_member_{i}"},
                    "mode": "parallel",
                    "sla_hours": 168,
                    "skip_unless": f"dc_member_{i}",
                }
                for i in range(1, 7)
            ),
            {
                "order": 2,
                "approver": {"type": "scope_rule", "value": "context.convenor"},
                "mode": "sequential",
                "sla_hours": 72,
            },
        ],
    },
    {
        "key": "phd.award",
        "module": "phd",
        "name": "PhD award",
        "steps": [
            _role("research_cell", 1, 72, escalate="vice_chancellor"),
            _role("dean", 2, 72, escalate="vice_chancellor"),
            {**_role("vice_chancellor", 3, 168), "skip_unless": "council_resolution"},
        ],
    },
)
# Phase 32: criterion response review (owner submits → the owner's HOD when a department is known → IQAC → principal)
ACCREDITATION_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "accreditation.response_review",
        "module": "accreditation",
        "name": "Criterion response review",
        "steps": [
            {
                "order": 1,
                "approver": {"type": "scope_rule", "value": "entity.department.hod"},
                "mode": "sequential",
                "sla_hours": 72,
                "skip_unless": "department_id",
            },
            _role("iqac_coordinator", 2, 72, escalate="vice_chancellor"),
            {**_role("vice_chancellor", 3, 96), "approver": {"type": "scope_rule", "value": "entity.college.principal"}},
        ],
    },
)
AFFILIATION_APPLICATION_STEPS.extend(
    [
        _role("registrar", 1, 168),
        {
            "order": 2,
            "approver": {"type": "scope_rule", "value": "context.inspector"},
            "mode": "sequential",
            "sla_hours": 336,
            "skip_unless": "inspection_required",
        },
        {
            "order": 3,
            "approver": {"type": "scope_rule", "value": "context.ac_user"},
            "mode": "sequential",
            "sla_hours": 720,
            "skip_unless": "council_required",
        },
        {
            "order": 4,
            "approver": {"type": "scope_rule", "value": "context.ec_user"},
            "mode": "sequential",
            "sla_hours": 720,
            "skip_unless": "council_required",
        },
        _role("vice_chancellor", 5, 168),
    ]
)
# Phase 34: college data submission review (college submits → university verifier → COE accept / lock for exam types,
# registrar for the rest — the acceptor is carried in the context)
AFFILIATION_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "affiliation.submission_review",
        "module": "affiliation",
        "name": "College data submission review",
        "steps": [
            _role("registrar", 1, 72),
            {"order": 2, "approver": {"type": "scope_rule", "value": "context.acceptor"}, "mode": "sequential", "sla_hours": 72},
        ],
    },
)
# Phase 33: minutes approval (the secretary submits → the chair named in the context approves), policy approval (owner
# submits → registrar → principal; the council resolution is cited on approve) and e-file approval routes chosen at
# movement time (up to four ad-hoc approvers carried in the context; empty slots are skipped)
GOVERNANCE_WORKFLOW_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "key": "governance.minutes_approval",
        "module": "governance",
        "name": "Minutes approval",
        "steps": [
            {"order": 1, "approver": {"type": "scope_rule", "value": "context.chair_user_id"}, "mode": "sequential", "sla_hours": 168}
        ],
    },
    {
        "key": "governance.policy_approval",
        "module": "governance",
        "name": "Policy approval",
        "steps": [_role("registrar", 1, 72, escalate="vice_chancellor"), _role("vice_chancellor", 2, 120)],
    },
    {
        "key": "efile.approval",
        "module": "efile",
        "name": "e-File approval route",
        "steps": [
            {
                "order": i,
                "approver": {"type": "scope_rule", "value": f"context.route_{i}"},
                "mode": "sequential",
                "sla_hours": 168,
                "skip_unless": f"route_{i}",
            }
            for i in range(1, 5)
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
    + INVENTORY_WORKFLOW_TEMPLATES
    + ACCOUNTING_WORKFLOW_TEMPLATES
    + FACILITIES_WORKFLOW_TEMPLATES
    + SUPPORT_WORKFLOW_TEMPLATES
    + RESEARCH_WORKFLOW_TEMPLATES
    + PHD_WORKFLOW_TEMPLATES
    + ACCREDITATION_WORKFLOW_TEMPLATES
    + GOVERNANCE_WORKFLOW_TEMPLATES
    + AFFILIATION_WORKFLOW_TEMPLATES
)

assert len(WORKFLOW_TEMPLATES) == 54, (
    "Prompts/04 ships 18 templates, Prompts/06 adds 5, Prompts/07 2, Prompts/08 1, Prompts/10 1, Prompts/11 1, "
    "Prompts/12 1, Prompts/16 3, Prompts/20 3, Prompts/22 1, Prompts/23 2, Prompts/25 2, Prompts/27 2, Prompts/30 4, Prompts/31 3, Prompts/32 1, Prompts/33 3, Prompts/34 1"
)
