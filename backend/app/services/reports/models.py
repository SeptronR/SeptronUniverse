"""Builder whitelist — Prompts/36 §36.6 ``builder_service`` (``@register_report_model``).

Each :class:`~app.core.reports.ReportModel` names a base entity (``FROM … b``), the scope-column mapping applied by
``scope_sql`` (so every builder row passes the same visibility as the module's own lists — an HOD gets department
rows, faculty own-offering students), the selectable / filterable / aggregatable columns with PII flags, and up to a
few optional joins. Expressions are server-side only; clients pick keys.
"""

from app.core.reports import ModelColumn as M
from app.core.reports import ModelJoin, ReportModel, register_report_model

NAME = "s.first_name || ' ' || COALESCE(s.last_name, '')"
ENROL = {
    "institution": "b.institution_id",
    "college": "b.college_id",
    "department": "b.department_id",
    "program": "b.program_id",
    "batch": "b.batch_id",
    "enrollment": "b.id",
}
J_PROGRAM = ModelJoin(
    "program",
    "Programme",
    "LEFT JOIN programs jp ON jp.id = {fk}",
    [M("code", "jp.code", "Programme code"), M("name", "jp.name", "Programme"), M("level", "jp.level", "Level")],
)
J_DEPT = ModelJoin(
    "department",
    "Department",
    "LEFT JOIN departments jd ON jd.id = {fk}",
    [M("code", "jd.code", "Department code"), M("name", "jd.name", "Department")],
)
J_BATCH = ModelJoin(
    "batch",
    "Batch",
    "LEFT JOIN batches jb ON jb.id = {fk}",
    [
        M("code", "jb.code", "Batch"),
        M("admission_year", "jb.admission_year", "Admission year", type="int", aggregatable=False),
    ],
)
J_COLLEGE = ModelJoin(
    "college",
    "College",
    "LEFT JOIN colleges jc ON jc.id = {fk}",
    [M("code", "jc.code", "College code"), M("name", "jc.name", "College")],
)


def j(base: ModelJoin, fk: str) -> ModelJoin:
    return ModelJoin(base.key, base.label, base.sql.format(fk=fk), list(base.columns))


register_report_model(
    ReportModel(
        key="students",
        module="students",
        base_entity="student_program_enrollments",
        label="Students (enrolments)",
        base_sql="FROM student_program_enrollments b JOIN students s ON s.id = b.student_id",
        base_where="b.deleted_at IS NULL AND s.deleted_at IS NULL",
        cols=ENROL,
        columns=[
            M("registration_number", "s.registration_number", "Reg. no"),
            M("name", NAME, "Name"),
            M("gender", "s.gender"),
            M("category", "s.category"),
            M("quota", "s.admission_quota", "Quota"),
            M("dob", "s.dob", "Date of birth", type="date", pii=True),
            M("phone", "s.phone", pii=True),
            M("email", "s.email", pii=True),
            M("domicile_state", "s.domicile_state", "State"),
            M("status", "b.status"),
            M("admission_date", "b.admission_date", type="date"),
            M("cgpa", "b.cgpa", "CGPA", type="number", aggregatable=True),
            M("credits_earned", "b.credits_earned", type="number", aggregatable=True),
            M("id", "b.id", "Enrolment id", sortable=False),
        ],
        joins=[
            j(J_PROGRAM, "b.program_id"),
            j(J_DEPT, "b.department_id"),
            j(J_BATCH, "b.batch_id"),
            j(J_COLLEGE, "b.college_id"),
        ],
        default_sort="registration_number",
        permission=("students:view", "students:view_all"),
    )
)

register_report_model(
    ReportModel(
        key="attendance_summaries",
        module="attendance",
        base_entity="mv_attendance_term",
        label="Attendance summaries",
        base_sql="FROM mv_attendance_term b JOIN student_program_enrollments e ON e.id = b.enrollment_id "
        "JOIN students s ON s.id = e.student_id JOIN course_offerings o ON o.id = b.offering_id JOIN courses c ON c.id = o.course_id",
        cols={**ENROL, "enrollment": "b.enrollment_id", "term": "b.term_id", "offering": "b.offering_id"},
        columns=[
            M("registration_number", "s.registration_number", "Reg. no"),
            M("name", NAME, "Name"),
            M("course", "c.code", "Course"),
            M("sessions_held", "b.sessions_held", type="int", aggregatable=True),
            M("sessions_present", "b.sessions_present", type="int", aggregatable=True),
            M("pct", "b.pct", "%", type="pct", aggregatable=True),
            M("eligibility", "b.eligibility"),
            M("is_short", "b.is_short", "Short", type="bool"),
        ],
        joins=[j(J_PROGRAM, "b.program_id"), j(J_DEPT, "b.department_id"), j(J_BATCH, "b.batch_id")],
        default_sort="registration_number",
        permission=("attendance:view", "attendance:view_all", "attendance:mark"),
    )
)

register_report_model(
    ReportModel(
        key="registrations",
        module="registration",
        base_entity="course_registration_items",
        label="Course registrations",
        base_sql="FROM course_registration_items b JOIN course_registrations r ON r.id = b.registration_id "
        "JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "JOIN course_offerings o ON o.id = b.offering_id JOIN courses c ON c.id = o.course_id",
        cols={
            "institution": "b.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "e.id",
            "term": "o.term_id",
            "offering": "b.offering_id",
        },
        columns=[
            M("registration_number", "s.registration_number", "Reg. no"),
            M("name", NAME, "Name"),
            M("course", "c.code", "Course"),
            M("title", "c.title", "Course title"),
            M("status", "b.status"),
            M("credits", "c.credits", type="number", aggregatable=True),
        ],
        default_sort="registration_number",
        permission=("registration:view", "registration:view_all"),
    )
)

register_report_model(
    ReportModel(
        key="results",
        module="results",
        base_entity="student_term_results",
        label="Term results",
        base_sql="FROM student_term_results b JOIN student_term_records tr ON tr.id = b.student_term_record_id "
        "JOIN student_program_enrollments e ON e.id = tr.student_program_enrollment_id JOIN students s ON s.id = e.student_id",
        base_where="b.is_current AND b.status = 'published'",
        cols={
            "institution": "b.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "e.id",
            "term": "tr.term_id",
        },
        columns=[
            M("registration_number", "s.registration_number", "Reg. no"),
            M("name", NAME, "Name"),
            M("category", "s.category"),
            M("gender", "s.gender"),
            M("sgpa", "b.sgpa", "SGPA", type="number", aggregatable=True),
            M("cgpa", "b.cgpa", "CGPA", type="number", aggregatable=True),
            M("backlog_count", "b.backlog_count", "Arrears", type="int", aggregatable=True),
            M("credits_earned", "b.credits_earned", type="number", aggregatable=True),
            M("result_class", "b.result_class", "Class"),
        ],
        joins=[j(J_PROGRAM, "e.program_id"), j(J_DEPT, "e.department_id"), j(J_BATCH, "e.batch_id")],
        default_sort="registration_number",
        permission=("results:view", "results:view_all"),
    )
)

register_report_model(
    ReportModel(
        key="marks",
        module="marks",
        base_entity="student_course_results",
        label="Course marks",
        base_sql="FROM student_course_results b JOIN student_program_enrollments e ON e.id = b.student_program_enrollment_id "
        "JOIN students s ON s.id = e.student_id JOIN courses c ON c.id = b.course_id",
        cols={
            "institution": "b.institution_id",
            "college": "b.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "e.id",
            "term": "b.term_id",
            "offering": "b.offering_id",
        },
        columns=[
            M("registration_number", "s.registration_number", "Reg. no"),
            M("name", NAME, "Name"),
            M("course", "c.code", "Course"),
            M("cia_marks", "b.cia_marks", "CIA", type="number", aggregatable=True),
            M("ese_marks", "b.ese_marks", "ESE", type="number", aggregatable=True),
            M("attempt_type", "b.attempt_type", "Attempt"),
        ],
        default_sort="course",
        permission=("marks:view", "marks:view_all", "marks:enter"),
    )
)

register_report_model(
    ReportModel(
        key="fee_invoices",
        module="fees",
        base_entity="fee_invoices",
        label="Fee invoices",
        base_sql="FROM fee_invoices b LEFT JOIN student_program_enrollments e ON e.id = b.student_program_enrollment_id "
        "LEFT JOIN students s ON s.id = e.student_id",
        base_where="b.status <> 'cancelled'",
        cols={
            "institution": "b.institution_id",
            "college": "b.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "b.student_program_enrollment_id",
            "term": "b.term_id",
        },
        columns=[
            M("invoice_number", "b.invoice_number", "Invoice"),
            M("registration_number", "s.registration_number", "Reg. no"),
            M("payer_type", "b.payer_type", "Payer"),
            M("description", "b.description"),
            M("total_paise", "b.total_paise", "Total (₹)", type="money", aggregatable=True),
            M("paid_paise", "b.paid_paise", "Paid (₹)", type="money", aggregatable=True),
            M("balance_paise", "b.balance_paise", "Balance (₹)", type="money", aggregatable=True),
            M("due_date", "b.due_date", type="date"),
            M("status", "b.status"),
            M("category", "s.category"),
        ],
        joins=[j(J_PROGRAM, "e.program_id"), j(J_DEPT, "e.department_id"), j(J_BATCH, "e.batch_id")],
        default_sort="invoice_number",
        permission=("fees:view_all", "fees:export", "fees:manage"),
        feature="fees.core",
    )
)

register_report_model(
    ReportModel(
        key="fee_payments",
        module="fees",
        base_entity="fee_payments",
        label="Fee payments",
        base_sql="FROM fee_payments b JOIN fee_invoices i ON i.id = b.invoice_id "
        "LEFT JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id",
        base_where="b.status IN ('success', 'reconciled')",
        cols={
            "institution": "b.institution_id",
            "college": "i.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "i.student_program_enrollment_id",
        },
        columns=[
            M("receipt_number", "b.receipt_number", "Receipt"),
            M("payment_date", "b.payment_date", "Date", type="date"),
            M("payment_mode", "b.payment_mode", "Mode"),
            M("amount_paise", "b.amount_paise", "Amount (₹)", type="money", aggregatable=True),
            M("reference_no", "b.reference_no", "Reference", pii=True),
            M("invoice_number", "i.invoice_number", "Invoice"),
        ],
        joins=[j(J_PROGRAM, "e.program_id"), j(J_DEPT, "e.department_id")],
        default_sort="payment_date",
        permission=("fees:view_all", "fees:export", "fees:manage"),
        feature="fees.core",
    )
)

STAFF = {"institution": "b.institution_id", "college": "b.college_id", "department": "b.department_id", "staff": "b.id"}
register_report_model(
    ReportModel(
        key="staff",
        module="hr",
        base_entity="staff",
        label="Staff",
        base_sql="FROM staff b LEFT JOIN designations dg ON dg.id = b.designation_id",
        base_where="b.deleted_at IS NULL",
        cols=STAFF,
        columns=[
            M("employee_id", "b.employee_id", "Employee ID"),
            M("name", "b.first_name || ' ' || COALESCE(b.last_name, '')", "Name"),
            M("gender", "b.gender"),
            M("designation", "dg.name"),
            M("cadre", "dg.cadre"),
            M("staff_category", "b.staff_category", "Category"),
            M("employment_type", "b.employment_type", "Employment"),
            M("joining_date", "b.joining_date", type="date"),
            M("phone", "b.phone", pii=True),
            M("email", "b.email", pii=True),
            M("status", "b.status"),
        ],
        joins=[
            j(J_DEPT, "b.department_id"),
            j(J_COLLEGE, "b.college_id"),
            ModelJoin(
                "leaves",
                "Leaves",
                "LEFT JOIN staff_leaves jl ON jl.staff_id = b.id",
                [
                    M("status", "jl.status", "Leave status"),
                    M("days_count", "jl.days_count", "Leave days", type="number", aggregatable=True),
                    M("from_date", "jl.from_date", "Leave from", type="date"),
                ],
            ),
        ],
        default_sort="employee_id",
        permission=("hr:view_all", "hr:manage", "hr:export"),
    )
)

register_report_model(
    ReportModel(
        key="leaves",
        module="hr",
        base_entity="staff_leaves",
        label="Leaves",
        base_sql="FROM staff_leaves b JOIN staff st ON st.id = b.staff_id JOIN leave_types lt ON lt.id = b.leave_type_id",
        cols={
            "institution": "b.institution_id",
            "college": "st.college_id",
            "department": "st.department_id",
            "staff": "b.staff_id",
        },
        columns=[
            M("employee_id", "st.employee_id", "Employee ID"),
            M("name", "st.first_name || ' ' || COALESCE(st.last_name, '')", "Name"),
            M("leave_type", "lt.code", "Type"),
            M("from_date", "b.from_date", type="date"),
            M("to_date", "b.to_date", type="date"),
            M("days_count", "b.days_count", "Days", type="number", aggregatable=True),
            M("status", "b.status"),
        ],
        joins=[j(J_DEPT, "st.department_id")],
        default_sort="from_date",
        permission=("hr:view_all", "leaves:view_all", "hr:manage"),
    )
)

register_report_model(
    ReportModel(
        key="payroll",
        module="payroll",
        base_entity="staff_payrolls",
        label="Payroll",
        base_sql="FROM staff_payrolls b JOIN staff st ON st.id = b.staff_id",
        cols={
            "institution": "b.institution_id",
            "college": "st.college_id",
            "department": "st.department_id",
            "staff": "b.staff_id",
        },
        columns=[
            M("employee_id", "st.employee_id", "Employee ID"),
            M("year", "b.year", type="int"),
            M("month", "b.month", type="int"),
            M("gross_paise", "b.gross_paise", "Gross (₹)", type="money", pii=True, aggregatable=True),
            M("deductions_paise", "b.deductions_paise", "Deductions (₹)", type="money", pii=True, aggregatable=True),
            M("net_paise", "b.net_paise", "Net (₹)", type="money", pii=True, aggregatable=True),
            M("status", "b.status"),
        ],
        joins=[j(J_DEPT, "st.department_id")],
        default_sort="employee_id",
        permission=("payroll:view_all", "payroll:manage"),
        feature="hr.payroll",
    )
)

register_report_model(
    ReportModel(
        key="applicants",
        module="admissions",
        base_entity="applicants",
        label="Applicants",
        base_sql="FROM applicants b JOIN admission_cycles c ON c.id = b.cycle_id "
        "LEFT JOIN applicant_preferences p ON p.applicant_id = b.id AND p.priority = 1",
        base_where="b.deleted_at IS NULL",
        cols={"institution": "b.institution_id", "college": "c.college_id", "program": "p.program_id"},
        columns=[
            M("application_number", "b.application_number", "Application no"),
            M("name", "b.first_name || ' ' || COALESCE(b.last_name, '')", "Name"),
            M("gender", "b.gender"),
            M("category", "b.category"),
            M("quota", "b.quota_claimed", "Quota"),
            M("domicile_state", "b.domicile_state", "State"),
            M("merit_score", "b.merit_score", type="number", aggregatable=True),
            M("status", "b.status"),
            M("cycle", "c.name", "Cycle"),
            M("phone", "b.contact ->> 'phone'", pii=True),
        ],
        joins=[j(J_PROGRAM, "p.program_id")],
        default_sort="application_number",
        permission=("admissions:view_all", "admissions:manage"),
    )
)

register_report_model(
    ReportModel(
        key="hostel_allocations",
        module="hostel",
        base_entity="hostel_allocations",
        label="Hostel allocations",
        base_sql="FROM hostel_allocations b JOIN hostels h ON h.id = b.hostel_id "
        "JOIN student_program_enrollments e ON e.id = b.student_program_enrollment_id JOIN students s ON s.id = e.student_id",
        cols={
            "institution": "b.institution_id",
            "college": "h.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "e.id",
            "hostel": "b.hostel_id",
        },
        columns=[
            M("hostel", "h.name"),
            M("registration_number", "s.registration_number", "Reg. no"),
            M("name", NAME, "Name"),
            M("gender", "s.gender"),
            M("status", "b.status"),
            M("from_on", "b.from_on", "From", type="date"),
        ],
        default_sort="hostel",
        permission=("hostel:view_all", "hostel:view", "hostel:manage"),
        feature="hostel.core",
    )
)

register_report_model(
    ReportModel(
        key="library_issues",
        module="library",
        base_entity="book_issues",
        label="Library issues",
        base_sql="FROM book_issues b JOIN library_copies c ON c.id = b.copy_id JOIN books bk ON bk.id = c.book_id "
        "JOIN library_members m ON m.id = b.member_id",
        cols={"institution": "b.institution_id", "college": "bk.college_id"},
        columns=[
            M("issued_on", "b.issued_on", type="date"),
            M("due_on", "b.due_on", type="date"),
            M("returned_on", "b.returned_on", type="date"),
            M("title", "bk.title"),
            M("subject", "bk.subject"),
            M("member_type", "m.member_type"),
            M("status", "b.status"),
            M("fine_paise", "b.fine_paise", "Fine (₹)", type="money", aggregatable=True),
        ],
        default_sort="issued_on",
        permission=("library:view_all", "library:manage"),
        feature="library.core",
    )
)

register_report_model(
    ReportModel(
        key="assets",
        module="inventory",
        base_entity="assets",
        label="Assets",
        base_sql="FROM assets b",
        base_where="b.deleted_at IS NULL",
        cols={
            "institution": "b.institution_id",
            "college": "b.college_id",
            "department": "b.department_id",
            "staff": "b.custodian_staff_id",
        },
        columns=[
            M("asset_tag", "b.asset_tag", "Tag"),
            M("name", "b.name"),
            M("category", "b.category"),
            M("purchase_date", "b.purchase_date", type="date"),
            M("cost_paise", "b.cost_paise", "Cost (₹)", type="money", aggregatable=True),
            M("current_value_paise", "b.current_value_paise", "Book value (₹)", type="money", aggregatable=True),
            M("status", "b.status"),
        ],
        joins=[j(J_DEPT, "b.department_id")],
        default_sort="asset_tag",
        permission=("inventory:view_all", "inventory:manage"),
        feature="inventory.assets",
    )
)

register_report_model(
    ReportModel(
        key="placements",
        module="placement",
        base_entity="placement_offers",
        label="Placement offers",
        base_sql="FROM placement_offers b JOIN drive_applications da ON da.id = b.application_id "
        "JOIN student_program_enrollments e ON e.id = da.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "JOIN companies co ON co.id = b.company_id",
        cols={
            "institution": "b.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "e.id",
        },
        columns=[
            M("registration_number", "s.registration_number", "Reg. no"),
            M("name", NAME, "Name"),
            M("company", "co.name"),
            M("sector", "co.sector"),
            M("ctc_paise", "b.ctc_paise", "CTC (₹)", type="money", aggregatable=True),
            M("status", "b.status"),
            M("offered_on", "b.offered_on", type="date"),
        ],
        joins=[j(J_PROGRAM, "e.program_id"), j(J_DEPT, "e.department_id"), j(J_BATCH, "e.batch_id")],
        default_sort="company",
        permission=("placement:view_all", "placement:manage"),
        feature="placement.core",
    )
)

register_report_model(
    ReportModel(
        key="publications",
        module="research",
        base_entity="publications",
        label="Publications",
        base_sql="FROM publications b LEFT JOIN staff st ON st.id = b.staff_id",
        cols={
            "institution": "b.institution_id",
            "college": "st.college_id",
            "department": "st.department_id",
            "staff": "b.staff_id",
        },
        columns=[
            M("year", "b.year", type="int"),
            M("pub_type", "b.pub_type", "Type"),
            M("title", "b.title"),
            M("indexing", "b.indexing"),
            M("citations", "b.citations", type="int", aggregatable=True),
            M("impact_factor", "b.impact_factor", type="number", aggregatable=True),
            M("author", "st.employee_id", "Author (employee)"),
        ],
        joins=[j(J_DEPT, "st.department_id")],
        default_sort="year",
        permission=("research:view", "research:view_all", "research:manage"),
        feature="research.publications",
    )
)

register_report_model(
    ReportModel(
        key="scholars",
        module="phd",
        base_entity="research_scholars",
        label="Research scholars",
        base_sql="FROM research_scholars b JOIN student_program_enrollments e ON e.id = b.student_program_enrollment_id "
        "JOIN students s ON s.id = e.student_id",
        cols={
            "institution": "b.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "program": "e.program_id",
            "batch": "e.batch_id",
            "enrollment": "e.id",
            "staff": "b.guide_staff_id",
        },
        columns=[
            M("registration_number", "s.registration_number", "Reg. no"),
            M("name", NAME, "Name"),
            M("mode", "b.mode"),
            M("fellowship_type", "b.fellowship_type", "Fellowship"),
            M("status", "b.status"),
            M("registration_date", "b.registration_date", type="date"),
        ],
        joins=[j(J_DEPT, "e.department_id")],
        default_sort="registration_number",
        permission=("phd:view_all", "phd:view", "phd:guide", "phd:manage"),
        feature="phd.core",
    )
)

register_report_model(
    ReportModel(
        key="grievances",
        module="grievances",
        base_entity="grievances",
        label="Grievances",
        base_sql="FROM grievances b LEFT JOIN student_program_enrollments e ON e.id = b.student_program_enrollment_id",
        cols={
            "institution": "b.institution_id",
            "college": "b.college_id",
            "department": "e.department_id",
            "enrollment": "b.student_program_enrollment_id",
        },
        columns=[
            M("ticket_number", "b.ticket_number", "Ticket"),
            M("category", "b.category"),
            M("committee", "b.committee"),
            M("priority", "b.priority"),
            M("status", "b.status"),
            M("created_at", "b.created_at", "Raised", type="datetime"),
            M("resolved_at", "b.resolved_at", "Resolved", type="datetime"),
            M("satisfaction_rating", "b.satisfaction_rating", "Rating", type="int", aggregatable=True),
        ],
        default_sort="created_at",
        permission=("grievances:view_all", "grievances:manage"),
        feature="grievances.core",
    )
)

register_report_model(
    ReportModel(
        key="events",
        module="events",
        base_entity="events",
        label="Events",
        base_sql="FROM events b",
        base_where="b.deleted_at IS NULL",
        cols={
            "institution": "b.institution_id",
            "college": "b.college_id",
            "department": "b.organiser_department_id",
            "staff": "b.organiser_staff_id",
        },
        columns=[
            M("title", "b.title"),
            M("event_type", "b.event_type", "Type"),
            M("from_on", "b.from_on", type="date"),
            M("participants_count", "b.participants_count", "Participants", type="int", aggregatable=True),
            M("budget_paise", "b.budget_paise", "Budget (₹)", type="money", aggregatable=True),
            M("status", "b.status"),
        ],
        joins=[j(J_DEPT, "b.organiser_department_id")],
        default_sort="from_on",
        permission=("events:view_all", "events:manage", "events:view"),
    )
)

register_report_model(
    ReportModel(
        key="service_requests",
        module="facilities",
        base_entity="service_requests",
        label="Service requests",
        base_sql="FROM service_requests b",
        cols={"institution": "b.institution_id", "college": "b.college_id"},
        columns=[
            M("ticket_number", "b.ticket_number", "Ticket"),
            M("category", "b.category"),
            M("priority", "b.priority"),
            M("status", "b.status"),
            M("created_at", "b.created_at", "Raised", type="datetime"),
            M("resolved_at", "b.resolved_at", "Resolved", type="datetime"),
            M("rating", "b.rating", type="int", aggregatable=True),
        ],
        default_sort="created_at",
        permission=("facilities:view_all", "facilities:manage"),
        feature="facilities.service_desk",
    )
)
