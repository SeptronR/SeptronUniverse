"""Module report registrations — Prompts/36 §36.6 ``report_service`` steps 1, 3, 4.

Every module's catalogue entries live here (as Phase 32 keeps its metric registrations in one package, the reports of
all modules are registered from this file so ``check_report_registry.py`` imports one place). Three kinds:

* **module reports** — :func:`sql_report` definitions over the module tables and the Phase 35 read models
  (``mv_*``; same scope-column mapping as the chart drill-down queries), plus Phase 32 ``metric_values``;
* **registers** (``layout='ledger'``, ``register=<name>``) — admission, attendance, fee day-book, results, script
  custody, degree, certificates, leave, stock, assets, library issues, hostel occupancy, visitor, grievance;
* **retro-registered Round 3–4 exports** (``legacy.py``) and **chart exports** (every Phase 35 chart table as a report,
  ``chart.<key>`` — rendered through ``ChartService`` under the same scope rules).
"""

from app.core.reports import ReportColumn as C
from app.core.reports import sql_report

# shared scope-column mappings -----------------------------------------------------------------------------------------------
ENROL = {
    "college": "e.college_id",
    "department": "e.department_id",
    "program": "e.program_id",
    "batch": "e.batch_id",
    "enrollment": "e.id",
}
STAFF = {"college": "st.college_id", "department": "st.department_id", "staff": "st.id"}
NAME = "s.first_name || ' ' || COALESCE(s.last_name, '')"
STAFF_NAME = "st.first_name || ' ' || COALESCE(st.last_name, '')"
DIMS4 = ("college", "department", "program", "batch")

# ============================================================== students / admissions
sql_report(
    "students.list_export",
    module="students",
    name="Students list",
    category="students",
    description="Enrolled students with programme, batch and status (DataTable export)",
    permission=("students:view_all", "students:view", "students:export"),
    feature=None,
    sql=(
        "SELECT s.registration_number, "
        + NAME
        + " AS name, s.gender, s.category, s.phone, s.email, p.code AS program, "
        "b.code AS batch, d.code AS department, e.admission_date, e.status FROM student_program_enrollments e "
        "JOIN students s ON s.id = e.student_id JOIN programs p ON p.id = e.program_id JOIN batches b ON b.id = e.batch_id "
        "JOIN departments d ON d.id = e.department_id WHERE {where} AND e.deleted_at IS NULL AND s.deleted_at IS NULL "
        "ORDER BY s.registration_number"
    ),
    cols={**ENROL, "institution": "e.institution_id"},
    columns=[
        C("registration_number", "Reg. no"),
        C("name", "Name"),
        C("gender"),
        C("category"),
        C("phone", pii=True),
        C("email", pii=True),
        C("program", "Programme"),
        C("batch"),
        C("department"),
        C("admission_date", type="date"),
        C("status"),
    ],
    filters={"status": "e.status = :v", "category": "s.category = :v", "gender": "s.gender = :v"},
    params_schema={
        "properties": {
            "status": {"type": "string", "enum": ["active", "break", "detained", "completed", "withdrawn"]},
            "category": {"type": "string"},
            "gender": {"type": "string"},
        }
    },
    date_column="e.admission_date",
    dims=DIMS4,
    layout="landscape",
)

sql_report(
    "students.category_gender",
    module="students",
    name="Enrolment by category and gender",
    category="students",
    description="Aggregate enrolment counts (mv_enrolment_daily)",
    permission=("students:view_all", "students:view", "accreditation:view"),
    sql=(
        "SELECT x.category, x.gender, SUM(x.enrolments)::int AS students FROM mv_enrolment_daily x "
        "WHERE {where} AND x.status = 'active' GROUP BY x.category, x.gender ORDER BY x.category, x.gender"
    ),
    cols={
        "institution": "x.institution_id",
        "college": "x.college_id",
        "department": "x.department_id",
        "program": "x.program_id",
        "batch": "x.batch_id",
    },
    columns=[C("category"), C("gender"), C("students", type="int", total=True)],
    dims=DIMS4,
    chart_key="students.enrolment_by_category",
)

sql_report(
    "admissions.register",
    module="students",
    name="Admission register",
    category="registers",
    description="Admitted students in admission order (ledger)",
    permission=("admissions:view_all", "admissions:manage", "students:view_all"),
    sql=(
        "SELECT e.admission_date, s.registration_number, " + NAME + " AS name, s.dob, s.gender, s.category, "
        "s.admission_quota AS quota, s.admission_mode AS mode, p.code AS program, a.application_number "
        "FROM student_program_enrollments e JOIN students s ON s.id = e.student_id JOIN programs p ON p.id = e.program_id "
        "LEFT JOIN applicants a ON a.admitted_student_id = s.id WHERE {where} AND e.deleted_at IS NULL "
        "ORDER BY e.admission_date, s.registration_number"
    ),
    cols={**ENROL, "institution": "e.institution_id"},
    columns=[
        C("admission_date", type="date"),
        C("registration_number", "Reg. no"),
        C("name"),
        C("dob", "Date of birth", type="date", pii=True),
        C("gender"),
        C("category"),
        C("quota"),
        C("mode"),
        C("program", "Programme"),
        C("application_number", "Application no"),
    ],
    filters={"cycle_id": "a.cycle_id = :v"},
    params_schema={"properties": {"cycle_id": {"type": "string", "format": "uuid", "x-picker": "admission_cycle"}}},
    date_column="e.admission_date",
    dims=DIMS4,
    layout="ledger",
    register="admission",
)

sql_report(
    "admissions.funnel",
    module="admissions",
    name="Admissions funnel",
    category="admissions",
    permission=("admissions:view_all", "admissions:view", "admissions:manage"),
    feature="admissions.cycles",
    sql=(
        "SELECT x.category, x.quota, SUM(x.applications)::int AS applications, SUM(x.verified)::int AS verified, "
        "SUM(x.merit)::int AS merit, SUM(x.allotted)::int AS allotted, SUM(x.admitted)::int AS admitted "
        "FROM mv_admissions_funnel x WHERE {where} GROUP BY x.category, x.quota ORDER BY x.category, x.quota"
    ),
    cols={"institution": "x.institution_id", "college": "x.college_id", "program": "x.program_id"},
    columns=[
        C("category"),
        C("quota"),
        C("applications", type="int", total=True),
        C("verified", type="int", total=True),
        C("merit", type="int", total=True),
        C("allotted", type="int", total=True),
        C("admitted", type="int", total=True),
    ],
    filters={"cycle_id": "x.cycle_id = :v"},
    params_schema={"properties": {"cycle_id": {"type": "string", "format": "uuid", "x-picker": "admission_cycle"}}},
    dims=("college", "program"),
    chart_key="admissions.funnel",
)

sql_report(
    "admissions.applicants",
    module="admissions",
    name="Applicants list",
    category="admissions",
    permission=("admissions:view_all", "admissions:manage"),
    feature="admissions.cycles",
    sql=(
        "SELECT a.application_number, a.first_name || ' ' || COALESCE(a.last_name, '') AS name, a.gender, a.category, "
        "a.quota_claimed AS quota, a.merit_score, a.status, a.submitted_at, a.contact ->> 'phone' AS phone "
        "FROM applicants a JOIN admission_cycles c ON c.id = a.cycle_id LEFT JOIN applicant_preferences p "
        "ON p.applicant_id = a.id AND p.priority = 1 WHERE {where} AND a.deleted_at IS NULL ORDER BY a.application_number"
    ),
    cols={"institution": "a.institution_id", "college": "c.college_id", "program": "p.program_id"},
    columns=[
        C("application_number", "Application no"),
        C("name"),
        C("gender"),
        C("category"),
        C("quota"),
        C("merit_score", type="number"),
        C("status"),
        C("submitted_at", type="datetime"),
        C("phone", pii=True),
    ],
    filters={"cycle_id": "a.cycle_id = :v", "status": "a.status = :v"},
    params_schema={
        "properties": {
            "cycle_id": {"type": "string", "format": "uuid", "x-picker": "admission_cycle"},
            "status": {"type": "string"},
        }
    },
    dims=("college", "program"),
    layout="landscape",
)

# ============================================================== attendance
_OFFERING_CHECK = (
    "SELECT 1 FROM course_offerings o WHERE {where} AND o.id = :id AND o.deleted_at IS NULL",
    {
        "college": "o.college_id",
        "department": "o.department_id",
        "offering": "o.id",
        "term": "o.term_id",
        "program": None,
        "batch": None,
    },
)
sql_report(
    "attendance.register",
    module="attendance",
    name="Attendance register",
    category="registers",
    description="Per offering and month: sessions held / attended per student (ledger)",
    permission=("attendance:view_all", "attendance:view", "attendance:mark"),
    feature=None,
    sql=(
        "SELECT s.registration_number, " + NAME + " AS name, COUNT(*)::int AS held, "
        "COUNT(*) FILTER (WHERE a.status IN ('present', 'late', 'on_duty'))::int AS attended, "
        "COUNT(*) FILTER (WHERE a.status = 'absent')::int AS absent, "
        "ROUND(100.0 * COUNT(*) FILTER (WHERE a.status IN ('present', 'late', 'on_duty')) / NULLIF(COUNT(*), 0), 2) AS pct "
        "FROM student_class_attendance a JOIN class_sessions cs ON cs.id = a.session_id "
        "JOIN course_offerings o ON o.id = cs.offering_id "
        "JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "WHERE {where} GROUP BY s.registration_number, s.first_name, s.last_name ORDER BY s.registration_number"
    ),
    cols={
        "institution": "a.institution_id",
        "college": "o.college_id",
        "department": "o.department_id",
        "program": "e.program_id",
        "batch": "e.batch_id",
        "term": "o.term_id",
        "enrollment": "e.id",
        "offering": "cs.offering_id",
    },
    columns=[
        C("registration_number", "Reg. no"),
        C("name"),
        C("held", type="int"),
        C("attended", type="int"),
        C("absent", type="int"),
        C("pct", "%", type="pct"),
    ],
    filters={"offering_id": "cs.offering_id = :v", "month": "to_char(a.session_date, 'YYYY-MM') = :v"},
    params_schema={
        "properties": {
            "offering_id": {"type": "string", "format": "uuid", "x-picker": "offering"},
            "month": {"type": "string", "pattern": "^\\d{4}-\\d{2}$", "title": "Month (YYYY-MM)"},
        },
        "required": ["offering_id"],
    },
    date_column="a.session_date",
    dims=("term",),
    layout="ledger",
    register="attendance",
    entity_checks={"offering_id": _OFFERING_CHECK},
)

sql_report(
    "attendance.shortfall_list",
    module="attendance",
    name="Attendance shortfall list",
    category="attendance",
    description="Students below the eligibility threshold per offering (mv_attendance_term)",
    permission=("attendance:view_all", "attendance:view", "attendance:mark"),
    sql=(
        "SELECT s.registration_number, " + NAME + " AS name, c.code AS course, x.sessions_held, x.sessions_present, "
        "x.pct, x.shortfall_pct, x.eligibility FROM mv_attendance_term x JOIN student_program_enrollments e "
        "ON e.id = x.enrollment_id JOIN students s ON s.id = e.student_id JOIN course_offerings o ON o.id = x.offering_id "
        "JOIN courses c ON c.id = o.course_id WHERE {where} AND x.is_short ORDER BY x.pct, s.registration_number"
    ),
    cols={
        "institution": "x.institution_id",
        "college": "x.college_id",
        "department": "x.department_id",
        "program": "x.program_id",
        "batch": "x.batch_id",
        "term": "x.term_id",
        "enrollment": "x.enrollment_id",
        "offering": "x.offering_id",
    },
    columns=[
        C("registration_number", "Reg. no"),
        C("name"),
        C("course"),
        C("sessions_held", type="int"),
        C("sessions_present", type="int"),
        C("pct", "%", type="pct"),
        C("shortfall_pct", "Shortfall %", type="pct"),
        C("eligibility"),
    ],
    filters={"offering_id": "x.offering_id = :v"},
    params_schema={"properties": {"offering_id": {"type": "string", "format": "uuid", "x-picker": "offering"}}},
    dims=(*DIMS4, "term"),
    chart_key="attendance.shortfall_by_department",
)

sql_report(
    "attendance.offering_summary",
    module="attendance",
    name="Attendance by offering",
    category="attendance",
    permission=("attendance:view_all", "attendance:view", "attendance:mark"),
    sql=(
        "SELECT c.code AS course, o.section_code AS section, COUNT(*)::int AS students, ROUND(AVG(x.pct), 2) AS avg_pct, "
        "COUNT(*) FILTER (WHERE x.is_short)::int AS short FROM mv_attendance_term x JOIN course_offerings o "
        "ON o.id = x.offering_id JOIN courses c ON c.id = o.course_id WHERE {where} "
        "GROUP BY c.code, o.section_code ORDER BY c.code, o.section_code"
    ),
    cols={
        "institution": "x.institution_id",
        "college": "x.college_id",
        "department": "x.offering_department_id",
        "program": "x.program_id",
        "batch": "x.batch_id",
        "term": "x.term_id",
        "offering": "x.offering_id",
    },
    columns=[
        C("course"),
        C("section"),
        C("students", type="int", total=True),
        C("avg_pct", "Average %", type="pct"),
        C("short", "Below threshold", type="int", total=True),
    ],
    dims=("college", "department", "term"),
)

# ============================================================== assessment / results / exams
sql_report(
    "assessment.marks_sheet",
    module="marks",
    name="Marks sheet",
    category="assessment",
    description="CIA / ESE marks per course result (own offerings for faculty)",
    permission=("marks:view_all", "marks:view", "marks:enter"),
    sql=(
        "SELECT c.code AS course, s.registration_number, " + NAME + " AS name, r.cia_marks, r.cia_max, r.ese_marks, "
        "r.ese_max, r.attempt_type FROM student_course_results r JOIN courses c ON c.id = r.course_id "
        "JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "WHERE {where} ORDER BY c.code, s.registration_number"
    ),
    cols={
        "institution": "r.institution_id",
        "college": "r.college_id",
        "department": "e.department_id",
        "program": "e.program_id",
        "batch": "e.batch_id",
        "term": "r.term_id",
        "enrollment": "e.id",
        "offering": "r.offering_id",
    },
    columns=[
        C("course"),
        C("registration_number", "Reg. no"),
        C("name"),
        C("cia_marks", "CIA", type="number"),
        C("cia_max", "CIA max", type="number"),
        C("ese_marks", "ESE", type="number"),
        C("ese_max", "ESE max", type="number"),
        C("attempt_type", "Attempt"),
    ],
    filters={"offering_id": "r.offering_id = :v"},
    params_schema={"properties": {"offering_id": {"type": "string", "format": "uuid", "x-picker": "offering"}}},
    dims=(*DIMS4, "term"),
    layout="landscape",
)

sql_report(
    "results.register",
    module="results",
    name="Results register",
    category="registers",
    description="Published term results per student (SGPA / CGPA / arrears / class) for a session or term (ledger)",
    permission=("results:view_all", "results:view", "exams:view_all", "exams:configure"),
    sql=(
        "SELECT s.registration_number, " + NAME + " AS name, p.code AS program, t.name AS term, r.credits_registered, "
        "r.credits_earned, r.sgpa, r.cgpa, r.backlog_count, r.result_class FROM student_term_results r "
        "JOIN student_term_records tr ON tr.id = r.student_term_record_id JOIN academic_terms t ON t.id = tr.term_id "
        "JOIN student_program_enrollments e ON e.id = tr.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "JOIN programs p ON p.id = e.program_id WHERE {where} AND r.is_current AND r.status = 'published' "
        "ORDER BY p.code, s.registration_number"
    ),
    cols={"institution": "r.institution_id", **ENROL, "term": "tr.term_id"},
    columns=[
        C("registration_number", "Reg. no"),
        C("name"),
        C("program", "Programme"),
        C("term"),
        C("credits_registered", type="number"),
        C("credits_earned", type="number"),
        C("sgpa", "SGPA", type="number"),
        C("cgpa", "CGPA", type="number"),
        C("backlog_count", "Arrears", type="int", total=True),
        C("result_class", "Class"),
    ],
    filters={
        "exam_session_id": "r.run_id IN (SELECT id FROM result_processing_runs WHERE exam_session_id = :v)",
    },
    params_schema={"properties": {"exam_session_id": {"type": "string", "format": "uuid", "x-picker": "exam_session"}}},
    dims=(*DIMS4, "term"),
    layout="ledger",
    register="results",
)

sql_report(
    "results.summary",
    module="results",
    name="Results summary",
    category="results",
    description="Pass %, average SGPA and arrears per programme / batch / term (mv_results_summary)",
    permission=("results:view_all", "results:view", "accreditation:view"),
    sql=(
        "SELECT p.code AS program, b.code AS batch, t.name AS term, x.students, x.passed, x.pass_pct, x.avg_sgpa, "
        "x.top_sgpa, x.arrears FROM mv_results_summary x JOIN programs p ON p.id = x.program_id "
        "JOIN batches b ON b.id = x.batch_id JOIN academic_terms t ON t.id = x.term_id WHERE {where} "
        "ORDER BY t.start_date DESC, p.code, b.code"
    ),
    cols={
        "institution": "x.institution_id",
        "college": "x.college_id",
        "department": "x.department_id",
        "program": "x.program_id",
        "batch": "x.batch_id",
        "term": "x.term_id",
    },
    columns=[
        C("program", "Programme"),
        C("batch"),
        C("term"),
        C("students", type="int", total=True),
        C("passed", type="int", total=True),
        C("pass_pct", "Pass %", type="pct"),
        C("avg_sgpa", "Avg SGPA", type="number"),
        C("top_sgpa", "Top SGPA", type="number"),
        C("arrears", type="int", total=True),
    ],
    dims=(*DIMS4, "term"),
    chart_key="results.pass_pct_by_program",
)

sql_report(
    "exams.progress",
    module="exams",
    name="Exam session progress",
    category="exams",
    permission=("exams:view_all", "exams:configure", "exams:manage"),
    sql=(
        "SELECT x.name AS session, x.exam_kind, x.status, x.registrations, x.confirmed, x.hall_tickets, x.scripts, "
        "x.scripts_valuated, x.valuation_pct, x.discrepancies, x.results_stage FROM mv_exam_progress x WHERE {where} "
        "ORDER BY x.name"
    ),
    cols={"institution": "x.institution_id", "college": "x.college_id", "term": "x.term_id"},
    columns=[
        C("session"),
        C("exam_kind", "Kind"),
        C("status"),
        C("registrations", type="int", total=True),
        C("confirmed", type="int", total=True),
        C("hall_tickets", type="int", total=True),
        C("scripts", type="int", total=True),
        C("scripts_valuated", "Valuated", type="int", total=True),
        C("valuation_pct", "Valuation %", type="pct"),
        C("discrepancies", type="int", total=True),
        C("results_stage", "Results"),
    ],
    dims=("college", "term"),
)

sql_report(
    "exams.script_custody_register",
    module="exams",
    name="Script custody register",
    category="registers",
    description="Answer-script bundle movements (dispatch / receipt / hand-over) per session (ledger)",
    permission=("exams:view_all", "exams:configure", "exams:manage"),
    sql=(
        "SELECT l.at, es.name AS session, ep.paper_code, b.bundle_number, b.script_count, l.action, l.location, "
        "fs.employee_id AS from_staff, ts.employee_id AS to_staff, l.remarks FROM script_custody_log l "
        "JOIN answer_script_bundles b ON b.id = l.bundle_id JOIN exam_papers ep ON ep.id = b.exam_paper_id "
        "JOIN exam_sessions es ON es.id = ep.exam_session_id LEFT JOIN staff fs ON fs.id = l.from_staff_id "
        "LEFT JOIN staff ts ON ts.id = l.to_staff_id WHERE {where} ORDER BY l.at, b.bundle_number"
    ),
    cols={"institution": "l.institution_id", "college": "es.college_id", "term": "es.term_id"},
    columns=[
        C("at", "At", type="datetime"),
        C("session"),
        C("paper_code", "Paper"),
        C("bundle_number", "Bundle"),
        C("script_count", "Scripts", type="int", total=True),
        C("action"),
        C("location"),
        C("from_staff", "From"),
        C("to_staff", "To"),
        C("remarks"),
    ],
    filters={"exam_session_id": "es.id = :v"},
    params_schema={"properties": {"exam_session_id": {"type": "string", "format": "uuid", "x-picker": "exam_session"}}},
    date_column="l.at::date",
    dims=("college", "term"),
    layout="ledger",
    register="script_custody",
)

sql_report(
    "degrees.register",
    module="degrees",
    name="Degree register",
    category="registers",
    description="Degrees awarded with certificate / serial numbers (ledger)",
    permission=("degrees:view_all", "degrees:manage", "degrees:approve"),
    sql=(
        "SELECT d.date_of_award, d.serial_no, d.certificate_number, s.registration_number, " + NAME + " AS name, "
        "d.degree_name, d.specialization, d.result_class, d.cgpa, d.status FROM degrees_awarded d "
        "JOIN student_program_enrollments e ON e.id = d.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "WHERE {where} AND d.status <> 'cancelled' ORDER BY d.date_of_award, d.serial_no"
    ),
    cols={"institution": "d.institution_id", **ENROL},
    columns=[
        C("date_of_award", "Awarded on", type="date"),
        C("serial_no", "Serial"),
        C("certificate_number", "Certificate no"),
        C("registration_number", "Reg. no"),
        C("name"),
        C("degree_name", "Degree"),
        C("specialization"),
        C("result_class", "Class"),
        C("cgpa", "CGPA", type="number"),
        C("status"),
    ],
    filters={"convocation_id": "d.convocation_id = :v", "award_type": "d.award_type = :v"},
    params_schema={
        "properties": {
            "convocation_id": {"type": "string", "format": "uuid"},
            "award_type": {
                "type": "string",
                "enum": ["certificate", "diploma", "degree", "honours", "pg_diploma", "phd"],
            },
        }
    },
    date_column="d.date_of_award",
    dims=DIMS4,
    layout="ledger",
    register="degree",
)

sql_report(
    "documents.certificates_register",
    module="certificates",
    name="Certificates serial register",
    category="registers",
    description="Issued documents by serial / document number (ledger)",
    permission=("certificates:view_all", "certificates:manage", "templates:manage"),
    feature="documents.templates",
    sql=(
        "SELECT d.issued_at, d.document_number, d.serial_no, d.template_type, d.person_type, d.entity_type, "
        "CASE WHEN d.revoked_at IS NULL THEN 'valid' ELSE 'revoked' END AS state, d.revoke_reason "
        "FROM issued_documents d LEFT JOIN student_program_enrollments e ON d.person_type = 'student' "
        "AND e.student_id = d.person_id AND e.is_active WHERE {where} ORDER BY d.issued_at, d.document_number"
    ),
    cols={
        "institution": "d.institution_id",
        "college": "e.college_id",
        "department": "e.department_id",
        "program": "e.program_id",
        "batch": "e.batch_id",
    },
    columns=[
        C("issued_at", "Issued", type="datetime"),
        C("document_number", "Document no"),
        C("serial_no", "Serial"),
        C("template_type", "Type"),
        C("person_type", "Person"),
        C("entity_type", "Entity"),
        C("state"),
        C("revoke_reason", "Revoke reason"),
    ],
    filters={"template_type": "d.template_type = :v"},
    params_schema={"properties": {"template_type": {"type": "string"}}},
    date_column="d.issued_at::date",
    layout="ledger",
    register="certificates",
)

# ============================================================== fees / scholarships / accounting
_PAY_COLS = {
    "institution": "p.institution_id",
    "college": "i.college_id",
    "department": "e.department_id",
    "program": "e.program_id",
    "batch": "e.batch_id",
    "enrollment": "i.student_program_enrollment_id",
}
sql_report(
    "fees.collection_register",
    module="fees",
    name="Fee collection register (day book)",
    category="registers",
    description="Receipts in date order with mode and amount; page-wise and grand totals",
    permission=("fees:view_all", "fees:export", "fees:manage"),
    feature="fees.core",
    sql=(
        "SELECT p.payment_date, p.receipt_number, i.invoice_number, s.registration_number, "
        "COALESCE(" + NAME + ", i.description) AS payer, p.payment_mode, p.reference_no, p.amount_paise "
        "FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id "
        "LEFT JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id "
        "LEFT JOIN students s ON s.id = e.student_id WHERE {where} AND p.status IN ('success', 'reconciled') "
        "ORDER BY p.payment_date, p.receipt_number"
    ),
    cols=_PAY_COLS,
    columns=[
        C("payment_date", "Date", type="date"),
        C("receipt_number", "Receipt"),
        C("invoice_number", "Invoice"),
        C("registration_number", "Reg. no"),
        C("payer"),
        C("payment_mode", "Mode"),
        C("reference_no", "Reference", pii=True),
        C("amount_paise", "Amount (₹)", type="money"),
    ],
    filters={"payment_mode": "p.payment_mode = :v"},
    params_schema={"properties": {"payment_mode": {"type": "string"}}},
    date_column="p.payment_date",
    dims=DIMS4,
    layout="ledger",
    register="fee",
    chart_key="fees.collection_trend",
)

sql_report(
    "fees.daily_collection",
    module="fees",
    name="Daily fee collection",
    category="fees",
    description="Collection per day and mode (scheduled digest for the accountant / principal)",
    permission=("fees:view_all", "fees:export", "fees:manage"),
    feature="fees.core",
    sql=(
        "SELECT p.payment_date, p.payment_mode, COUNT(*)::int AS receipts, SUM(p.amount_paise)::bigint AS amount_paise "
        "FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id "
        "LEFT JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id "
        "WHERE {where} AND p.status IN ('success', 'reconciled') GROUP BY p.payment_date, p.payment_mode "
        "ORDER BY p.payment_date DESC, p.payment_mode"
    ),
    cols=_PAY_COLS,
    columns=[
        C("payment_date", "Date", type="date"),
        C("payment_mode", "Mode"),
        C("receipts", type="int", total=True),
        C("amount_paise", "Amount (₹)", type="money"),
    ],
    date_column="p.payment_date",
    dims=DIMS4,
)

sql_report(
    "fees.dues_position",
    module="fees",
    name="Dues position and aging",
    category="fees",
    permission=("fees:view_all", "fees:export", "fees:manage"),
    feature="fees.core",
    sql=(
        "SELECT s.registration_number, " + NAME + " AS name, p.code AS program, x.billed_paise, x.paid_paise, "
        "x.balance_paise, x.overdue_paise, x.aging_0_30_paise, x.aging_31_60_paise, x.aging_61_90_paise, "
        "x.aging_90_plus_paise FROM mv_fees_position x JOIN student_program_enrollments e ON e.id = x.enrollment_id "
        "JOIN students s ON s.id = e.student_id JOIN programs p ON p.id = x.program_id WHERE {where} "
        "AND x.balance_paise > 0 ORDER BY x.overdue_paise DESC, s.registration_number"
    ),
    cols={
        "institution": "x.institution_id",
        "college": "x.college_id",
        "department": "x.department_id",
        "program": "x.program_id",
        "batch": "x.batch_id",
        "enrollment": "x.enrollment_id",
    },
    columns=[
        C("registration_number", "Reg. no"),
        C("name"),
        C("program", "Programme"),
        C("billed_paise", "Billed (₹)", type="money"),
        C("paid_paise", "Paid (₹)", type="money"),
        C("balance_paise", "Balance (₹)", type="money"),
        C("overdue_paise", "Overdue (₹)", type="money"),
        C("aging_0_30_paise", "0–30 d (₹)", type="money"),
        C("aging_31_60_paise", "31–60 d (₹)", type="money"),
        C("aging_61_90_paise", "61–90 d (₹)", type="money"),
        C("aging_90_plus_paise", "90+ d (₹)", type="money"),
    ],
    dims=DIMS4,
    layout="landscape",
    chart_key="fees.dues_aging",
)

sql_report(
    "scholarships.applications",
    module="scholarships",
    name="Scholarship applications",
    category="scholarships",
    permission=("scholarships:view_all", "scholarships:manage", "fees:view_all"),
    sql=(
        "SELECT sc.name AS scheme, sc.provider, s.registration_number, " + NAME + " AS name, s.category, "
        "a.income_paise, a.status, a.sanctioned_paise, a.disbursement_mode, a.disbursed_at FROM scholarship_applications a "
        "JOIN scholarships sc ON sc.id = a.scholarship_id JOIN student_program_enrollments e "
        "ON e.id = a.student_program_enrollment_id JOIN students s ON s.id = e.student_id WHERE {where} "
        "ORDER BY sc.name, s.registration_number"
    ),
    cols={"institution": "a.institution_id", **ENROL},
    columns=[
        C("scheme"),
        C("provider"),
        C("registration_number", "Reg. no"),
        C("name"),
        C("category"),
        C("income_paise", "Family income (₹)", type="money", pii=True),
        C("status"),
        C("sanctioned_paise", "Sanctioned (₹)", type="money"),
        C("disbursement_mode", "Disbursement"),
        C("disbursed_at", type="datetime"),
    ],
    filters={"status": "a.status = :v", "provider": "sc.provider = :v"},
    params_schema={"properties": {"status": {"type": "string"}, "provider": {"type": "string"}}},
    dims=DIMS4,
    layout="landscape",
)

# ============================================================== HR / payroll / leave
sql_report(
    "hr.staff_list",
    module="hr",
    name="Staff list",
    category="hr",
    permission=("hr:view_all", "hr:export", "hr:manage"),
    sql=(
        "SELECT st.employee_id, " + STAFF_NAME + " AS name, d.code AS department, dg.name AS designation, "
        "st.staff_category, st.employment_type, st.joining_date, st.phone, st.email, st.status FROM staff st "
        "LEFT JOIN departments d ON d.id = st.department_id LEFT JOIN designations dg ON dg.id = st.designation_id "
        "WHERE {where} AND st.deleted_at IS NULL ORDER BY st.employee_id"
    ),
    cols={"institution": "st.institution_id", **STAFF},
    columns=[
        C("employee_id", "Employee ID"),
        C("name"),
        C("department"),
        C("designation"),
        C("staff_category", "Category"),
        C("employment_type", "Employment"),
        C("joining_date", type="date"),
        C("phone", pii=True),
        C("email", pii=True),
        C("status"),
    ],
    filters={"status": "st.status = :v", "staff_category": "st.staff_category = :v"},
    params_schema={"properties": {"status": {"type": "string"}, "staff_category": {"type": "string"}}},
    dims=("college", "department"),
    layout="landscape",
)

sql_report(
    "hr.headcount",
    module="hr",
    name="HR headcount",
    category="hr",
    description="Headcount by department / cadre with leave and attendance today (mv_hr_snapshot)",
    permission=("hr:view_all", "hr:export", "hr:manage", "accreditation:view"),
    sql=(
        "SELECT d.code AS department, x.cadre, x.staff_category, SUM(x.headcount)::int AS headcount, "
        "SUM(x.on_leave_today)::int AS on_leave_today, SUM(x.present_today)::int AS present_today, "
        "SUM(x.leaves_pending)::int AS leaves_pending FROM mv_hr_snapshot x LEFT JOIN departments d ON d.id = x.department_id "
        "WHERE {where} GROUP BY d.code, x.cadre, x.staff_category ORDER BY d.code, x.cadre"
    ),
    cols={"institution": "x.institution_id", "college": "x.college_id", "department": "x.department_id"},
    columns=[
        C("department"),
        C("cadre"),
        C("staff_category", "Category"),
        C("headcount", type="int", total=True),
        C("on_leave_today", type="int", total=True),
        C("present_today", type="int", total=True),
        C("leaves_pending", type="int", total=True),
    ],
    dims=("college", "department"),
    chart_key="hr.staff_by_department",
)

sql_report(
    "hr.leave_register",
    module="hr",
    name="Leave register",
    category="registers",
    permission=("hr:view_all", "leaves:view_all", "leaves:approve", "hr:manage"),
    sql=(
        "SELECT l.from_date, l.to_date, st.employee_id, " + STAFF_NAME + " AS name, d.code AS department, "
        "lt.code AS leave_type, l.days_count, l.status, l.reviewed_at FROM staff_leaves l JOIN staff st ON st.id = l.staff_id "
        "JOIN leave_types lt ON lt.id = l.leave_type_id LEFT JOIN departments d ON d.id = st.department_id "
        "WHERE {where} ORDER BY l.from_date, st.employee_id"
    ),
    cols={"institution": "l.institution_id", **STAFF},
    columns=[
        C("from_date", "From", type="date"),
        C("to_date", "To", type="date"),
        C("employee_id", "Employee ID"),
        C("name"),
        C("department"),
        C("leave_type", "Type"),
        C("days_count", "Days", type="number", total=True),
        C("status"),
        C("reviewed_at", "Reviewed", type="datetime"),
    ],
    filters={"status": "l.status = :v"},
    params_schema={
        "properties": {"status": {"type": "string", "enum": ["pending", "approved", "rejected", "cancelled"]}}
    },
    date_column="l.from_date",
    dims=("college", "department"),
    layout="ledger",
    register="leave",
)

sql_report(
    "payroll.register",
    module="payroll",
    name="Payroll register",
    category="hr",
    permission=("payroll:view_all", "payroll:manage", "payroll:approve"),
    feature="hr.payroll",
    sql=(
        "SELECT pr.year, pr.month, st.employee_id, " + STAFF_NAME + " AS name, d.code AS department, pr.paid_days, "
        "pr.lop_days, pr.gross_paise, pr.deductions_paise, pr.net_paise, pr.status FROM staff_payrolls pr "
        "JOIN staff st ON st.id = pr.staff_id LEFT JOIN departments d ON d.id = st.department_id WHERE {where} "
        "ORDER BY pr.year, pr.month, st.employee_id"
    ),
    cols={"institution": "pr.institution_id", **STAFF},
    columns=[
        C("year", type="int"),
        C("month", type="int"),
        C("employee_id", "Employee ID"),
        C("name"),
        C("department"),
        C("paid_days", type="number"),
        C("lop_days", "LOP days", type="number"),
        C("gross_paise", "Gross (₹)", type="money", pii=True),
        C("deductions_paise", "Deductions (₹)", type="money", pii=True),
        C("net_paise", "Net (₹)", type="money", pii=True),
        C("status"),
    ],
    filters={"year": "pr.year = :v", "month": "pr.month = :v"},
    params_schema={"properties": {"year": {"type": "integer"}, "month": {"type": "integer"}}},
    dims=("college", "department"),
    layout="landscape",
)

# ============================================================== hostel / library / inventory / facilities
sql_report(
    "hostel.occupancy_register",
    module="hostel",
    name="Hostel occupancy register",
    category="registers",
    permission=("hostel:view_all", "hostel:view", "hostel:manage"),
    feature="hostel.core",
    sql=(
        "SELECT h.name AS hostel, bd.bed_label AS bed, s.registration_number, " + NAME + " AS name, s.gender, "
        "a.from_on, a.to_on, a.status, a.check_in_at FROM hostel_allocations a JOIN hostels h ON h.id = a.hostel_id "
        "JOIN hostel_beds bd ON bd.id = a.bed_id JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id "
        "JOIN students s ON s.id = e.student_id WHERE {where} AND a.status IN ('allotted', 'checked_in') "
        "ORDER BY h.name, bd.bed_label"
    ),
    cols={
        "institution": "a.institution_id",
        "college": "h.college_id",
        "department": "e.department_id",
        "program": "e.program_id",
        "batch": "e.batch_id",
        "enrollment": "e.id",
        "hostel": "a.hostel_id",
    },
    columns=[
        C("hostel"),
        C("bed"),
        C("registration_number", "Reg. no"),
        C("name"),
        C("gender"),
        C("from_on", "From", type="date"),
        C("to_on", "To", type="date"),
        C("status"),
        C("check_in_at", "Checked in", type="datetime"),
    ],
    filters={"hostel_id": "a.hostel_id = :v"},
    params_schema={"properties": {"hostel_id": {"type": "string", "format": "uuid", "x-picker": "hostel"}}},
    dims=("college",),
    layout="ledger",
    register="hostel_occupancy",
)

sql_report(
    "library.issue_register",
    module="library",
    name="Library issue register",
    category="registers",
    permission=("library:view_all", "library:manage"),
    feature="library.core",
    sql=(
        "SELECT i.issued_on, c.accession_number, b.title, m.member_code, m.member_type, i.due_on, i.returned_on, "
        "i.status, i.fine_paise FROM book_issues i JOIN library_copies c ON c.id = i.copy_id JOIN books b ON b.id = c.book_id "
        "JOIN library_members m ON m.id = i.member_id WHERE {where} ORDER BY i.issued_on, c.accession_number"
    ),
    cols={"institution": "i.institution_id", "college": "b.college_id"},
    columns=[
        C("issued_on", "Issued", type="date"),
        C("accession_number", "Accession"),
        C("title"),
        C("member_code", "Member"),
        C("member_type", "Type"),
        C("due_on", "Due", type="date"),
        C("returned_on", "Returned", type="date"),
        C("status"),
        C("fine_paise", "Fine (₹)", type="money"),
    ],
    filters={"status": "i.status = :v"},
    params_schema={"properties": {"status": {"type": "string", "enum": ["issued", "returned", "overdue", "lost"]}}},
    date_column="i.issued_on",
    layout="ledger",
    register="library_issues",
)

sql_report(
    "inventory.stock_register",
    module="inventory",
    name="Stock register",
    category="registers",
    permission=("inventory:view_all", "inventory:manage", "inventory:export"),
    feature="inventory.core",
    sql=(
        "SELECT t.occurred_at, st.name AS store, it.item_code, it.name AS item, t.txn_type, t.quantity, "
        "t.unit_cost_paise, (t.quantity * COALESCE(t.unit_cost_paise, 0))::bigint AS value_paise, t.remarks "
        "FROM stock_transactions t JOIN stores st ON st.id = t.store_id JOIN items it ON it.id = t.item_id "
        "WHERE {where} ORDER BY t.occurred_at, it.item_code"
    ),
    cols={"institution": "t.institution_id", "college": "st.college_id", "department": "st.department_id"},
    columns=[
        C("occurred_at", "At", type="datetime"),
        C("store"),
        C("item_code", "Item code"),
        C("item"),
        C("txn_type", "Type"),
        C("quantity", type="number"),
        C("unit_cost_paise", "Unit cost (₹)", type="money"),
        C("value_paise", "Value (₹)", type="money"),
        C("remarks"),
    ],
    filters={"store_id": "t.store_id = :v", "txn_type": "t.txn_type = :v"},
    params_schema={"properties": {"store_id": {"type": "string", "format": "uuid"}, "txn_type": {"type": "string"}}},
    date_column="t.occurred_at::date",
    dims=("college", "department"),
    layout="ledger",
    register="stock",
)

sql_report(
    "inventory.asset_register",
    module="inventory",
    name="Asset register",
    category="registers",
    permission=("inventory:view_all", "inventory:manage", "inventory:export"),
    feature="inventory.assets",
    sql=(
        "SELECT a.asset_tag, a.name, a.category, a.serial_no, d.code AS department, a.purchase_date, a.cost_paise, "
        "a.current_value_paise, a.status FROM assets a LEFT JOIN departments d ON d.id = a.department_id "
        "WHERE {where} AND a.deleted_at IS NULL ORDER BY a.asset_tag"
    ),
    cols={
        "institution": "a.institution_id",
        "college": "a.college_id",
        "department": "a.department_id",
        "staff": "a.custodian_staff_id",
    },
    columns=[
        C("asset_tag", "Tag"),
        C("name"),
        C("category"),
        C("serial_no", "Serial"),
        C("department"),
        C("purchase_date", type="date"),
        C("cost_paise", "Cost (₹)", type="money"),
        C("current_value_paise", "Book value (₹)", type="money"),
        C("status"),
    ],
    filters={"status": "a.status = :v", "category": "a.category = :v"},
    params_schema={"properties": {"status": {"type": "string"}, "category": {"type": "string"}}},
    date_column="a.purchase_date",
    dims=("college", "department"),
    layout="ledger",
    register="assets",
)

sql_report(
    "facilities.visitor_register",
    module="facilities",
    name="Visitor register",
    category="registers",
    permission=("facilities:view_all", "facilities:manage"),
    feature="facilities.visitor_gate",
    sql=(
        "SELECT v.valid_from, v.pass_code, v.visitor ->> 'name' AS visitor, v.visitor ->> 'phone' AS phone, v.purpose, "
        "v.vehicle_no, v.gate_in_at, v.gate_out_at, v.status FROM visitor_passes v WHERE {where} "
        "ORDER BY v.valid_from, v.pass_code"
    ),
    cols={"institution": "v.institution_id", "college": "v.college_id"},
    columns=[
        C("valid_from", "Date", type="datetime"),
        C("pass_code", "Pass"),
        C("visitor"),
        C("phone", pii=True),
        C("purpose"),
        C("vehicle_no", "Vehicle"),
        C("gate_in_at", "In", type="datetime"),
        C("gate_out_at", "Out", type="datetime"),
        C("status"),
    ],
    date_column="v.valid_from::date",
    dims=("college",),
    layout="ledger",
    register="visitor",
)

sql_report(
    "facilities.service_desk_sla",
    module="facilities",
    name="Service desk SLA",
    category="facilities",
    permission=("facilities:view_all", "facilities:manage"),
    sql=(
        "SELECT x.category, SUM(x.open)::int AS open, SUM(x.breached)::int AS breached, SUM(x.resolved)::int AS resolved, "
        "SUM(x.within_sla)::int AS within_sla, ROUND(AVG(x.mttr_hours), 2) AS mttr_hours FROM mv_service_desk_sla x "
        "WHERE {where} GROUP BY x.category ORDER BY x.category"
    ),
    cols={"institution": "x.institution_id", "college": "x.college_id"},
    columns=[
        C("category"),
        C("open", type="int", total=True),
        C("breached", type="int", total=True),
        C("resolved", type="int", total=True),
        C("within_sla", "Within SLA", type="int", total=True),
        C("mttr_hours", "MTTR (h)", type="number"),
    ],
    dims=("college",),
)

sql_report(
    "events.list",
    module="events",
    name="Events held",
    category="events",
    permission=("events:view_all", "events:manage", "accreditation:view"),
    sql=(
        "SELECT ev.from_on, ev.to_on, ev.event_type, ev.title, d.code AS department, ev.participants_count, "
        "ev.external_participants_count, ev.budget_paise, ev.naac_criterion, ev.status FROM events ev "
        "LEFT JOIN departments d ON d.id = ev.organiser_department_id WHERE {where} AND ev.deleted_at IS NULL "
        "ORDER BY ev.from_on"
    ),
    cols={
        "institution": "ev.institution_id",
        "college": "ev.college_id",
        "department": "ev.organiser_department_id",
        "staff": "ev.organiser_staff_id",
    },
    columns=[
        C("from_on", "From", type="date"),
        C("to_on", "To", type="date"),
        C("event_type", "Type"),
        C("title"),
        C("department"),
        C("participants_count", "Participants", type="int", total=True),
        C("external_participants_count", "External", type="int", total=True),
        C("budget_paise", "Budget (₹)", type="money"),
        C("naac_criterion", "NAAC"),
        C("status"),
    ],
    filters={"event_type": "ev.event_type = :v"},
    params_schema={"properties": {"event_type": {"type": "string"}}},
    date_column="ev.from_on",
    dims=("college", "department"),
    layout="landscape",
)

# ============================================================== communication
sql_report(
    "communication.delivery_summary",
    module="communication",
    name="Message delivery summary",
    category="communication",
    permission=("communication:view_all", "communication:manage"),
    sql=(
        "SELECT m.created_at::date AS day, m.channel, m.status, COUNT(*)::int AS messages, "
        "COALESCE(SUM(m.cost_paise), 0)::bigint AS cost_paise FROM message_logs m WHERE {where} "
        "GROUP BY m.created_at::date, m.channel, m.status ORDER BY day DESC, m.channel, m.status"
    ),
    cols={"institution": "m.institution_id"},
    columns=[
        C("day", type="date"),
        C("channel"),
        C("status"),
        C("messages", type="int", total=True),
        C("cost_paise", "Cost (₹)", type="money"),
    ],
    filters={"channel": "m.channel = :v"},
    params_schema={
        "properties": {"channel": {"type": "string", "enum": ["sms", "whatsapp", "email", "push", "in_app"]}}
    },
    date_column="m.created_at::date",
)

# ============================================================== mentoring / grievance / discipline
sql_report(
    "grievance.register",
    module="grievances",
    name="Grievance register",
    category="registers",
    description="Tickets with category, committee, SLA and resolution (anonymous raisers stay anonymous)",
    permission=("grievances:view_all", "grievances:manage"),
    feature="grievances.core",
    sql=(
        "SELECT g.created_at, g.ticket_number, g.category, g.committee, g.priority, g.status, g.sla_due_at, g.resolved_at, "
        "CASE WHEN g.is_anonymous THEN NULL ELSE s.registration_number END AS registration_number, "
        "(g.resolved_at IS NOT NULL AND (g.sla_due_at IS NULL OR g.resolved_at <= g.sla_due_at)) AS within_sla "
        "FROM grievances g LEFT JOIN student_program_enrollments e ON e.id = g.student_program_enrollment_id "
        "LEFT JOIN students s ON s.id = e.student_id WHERE {where} ORDER BY g.created_at, g.ticket_number"
    ),
    cols={
        "institution": "g.institution_id",
        "college": "g.college_id",
        "department": "e.department_id",
        "program": "e.program_id",
        "batch": "e.batch_id",
        "enrollment": "g.student_program_enrollment_id",
    },
    columns=[
        C("created_at", "Raised", type="datetime"),
        C("ticket_number", "Ticket"),
        C("category"),
        C("committee"),
        C("priority"),
        C("status"),
        C("sla_due_at", "SLA due", type="datetime"),
        C("resolved_at", "Resolved", type="datetime"),
        C("registration_number", "Reg. no", pii=True),
        C("within_sla", "Within SLA", type="bool"),
    ],
    filters={"category": "g.category = :v", "status": "g.status = :v"},
    params_schema={"properties": {"category": {"type": "string"}, "status": {"type": "string"}}},
    date_column="g.created_at::date",
    dims=("college",),
    layout="ledger",
    register="grievance",
)

sql_report(
    "grievance.sla_summary",
    module="grievances",
    name="Grievance SLA summary",
    category="student_support",
    permission=("grievances:view_all", "grievances:manage", "accreditation:view"),
    feature="grievances.core",
    sql=(
        "SELECT g.category, COUNT(*)::int AS raised, COUNT(*) FILTER (WHERE g.status NOT IN ('resolved', 'closed'))::int AS open, "
        "COUNT(*) FILTER (WHERE g.resolved_at IS NOT NULL)::int AS resolved, "
        "COUNT(*) FILTER (WHERE g.resolved_at IS NOT NULL AND (g.sla_due_at IS NULL OR g.resolved_at <= g.sla_due_at))::int AS within_sla, "
        "COUNT(*) FILTER (WHERE g.status NOT IN ('resolved', 'closed') AND g.sla_due_at < NOW())::int AS breached "
        "FROM grievances g WHERE {where} GROUP BY g.category ORDER BY g.category"
    ),
    cols={"institution": "g.institution_id", "college": "g.college_id"},
    columns=[
        C("category"),
        C("raised", type="int", total=True),
        C("open", type="int", total=True),
        C("resolved", type="int", total=True),
        C("within_sla", "Within SLA", type="int", total=True),
        C("breached", type="int", total=True),
    ],
    date_column="g.created_at::date",
    dims=("college",),
)

sql_report(
    "mentoring.risk_list",
    module="mentoring",
    name="At-risk students",
    category="student_support",
    permission=("mentoring:view_all", "mentoring:view", "mentoring:manage"),
    feature="mentoring.early_warning",
    sql=(
        "SELECT s.registration_number, " + NAME + " AS name, p.code AS program, f.level, f.score, f.acknowledged_at "
        "FROM risk_flags f JOIN student_program_enrollments e ON e.id = f.student_program_enrollment_id "
        "JOIN students s ON s.id = e.student_id JOIN programs p ON p.id = e.program_id WHERE {where} "
        "ORDER BY f.score DESC, s.registration_number"
    ),
    cols={"institution": "f.institution_id", **ENROL, "term": "f.term_id"},
    columns=[
        C("registration_number", "Reg. no"),
        C("name"),
        C("program", "Programme"),
        C("level"),
        C("score", type="number"),
        C("acknowledged_at", "Acknowledged", type="datetime"),
    ],
    filters={"level": "f.level = :v"},
    params_schema={"properties": {"level": {"type": "string", "enum": ["low", "medium", "high"]}}},
    dims=(*DIMS4, "term"),
)

# ============================================================== placement / alumni
sql_report(
    "placement.funnel",
    module="placement",
    name="Placement funnel",
    category="placement",
    description="Per drive: eligible → applied → rounds → offers → accepted, CTC bands (mv_placement_funnel)",
    permission=("placement:view_all", "placement:manage", "placement:view"),
    feature="placement.core",
    sql=(
        "SELECT c.name AS company, d.title AS drive, x.drive_on, SUM(x.eligible)::int AS eligible, "
        "SUM(x.applied)::int AS applied, SUM(x.in_rounds)::int AS in_rounds, SUM(x.offers)::int AS offers, "
        "SUM(x.accepted)::int AS accepted, MAX(x.max_ctc_paise)::bigint AS max_ctc_paise FROM mv_placement_funnel x "
        "JOIN placement_drives d ON d.id = x.drive_id JOIN companies c ON c.id = d.company_id WHERE {where} "
        "GROUP BY c.name, d.title, x.drive_on ORDER BY x.drive_on DESC NULLS LAST, c.name"
    ),
    cols={
        "institution": "x.institution_id",
        "college": "x.college_id",
        "department": "x.department_id",
        "batch": "x.batch_id",
    },
    columns=[
        C("company"),
        C("drive"),
        C("drive_on", type="date"),
        C("eligible", type="int", total=True),
        C("applied", type="int", total=True),
        C("in_rounds", "In rounds", type="int", total=True),
        C("offers", type="int", total=True),
        C("accepted", type="int", total=True),
        C("max_ctc_paise", "Max CTC (₹)", type="money"),
    ],
    date_column="x.drive_on",
    dims=("college", "department", "batch"),
    layout="landscape",
    chart_key="placement.funnel",
)

sql_report(
    "placement.offers_list",
    module="placement",
    name="Placement offers",
    category="placement",
    permission=("placement:view_all", "placement:manage"),
    feature="placement.core",
    sql=(
        "SELECT s.registration_number, "
        + NAME
        + " AS name, p.code AS program, c.name AS company, o.role, o.ctc_paise, "
        "o.offered_on, o.status, o.is_ppo FROM placement_offers o JOIN drive_applications da ON da.id = o.application_id "
        "JOIN student_program_enrollments e ON e.id = da.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "JOIN programs p ON p.id = e.program_id JOIN companies c ON c.id = o.company_id WHERE {where} "
        "ORDER BY o.offered_on DESC NULLS LAST, s.registration_number"
    ),
    cols={"institution": "o.institution_id", **ENROL},
    columns=[
        C("registration_number", "Reg. no"),
        C("name"),
        C("program", "Programme"),
        C("company"),
        C("role"),
        C("ctc_paise", "CTC (₹)", type="money"),
        C("offered_on", type="date"),
        C("status"),
        C("is_ppo", "PPO", type="bool"),
    ],
    date_column="o.offered_on",
    dims=DIMS4,
    layout="landscape",
)

sql_report(
    "alumni.directory",
    module="alumni",
    name="Alumni directory",
    category="alumni",
    permission=("alumni:view_all", "alumni:manage"),
    feature="alumni.core",
    sql=(
        "SELECT s.registration_number, " + NAME + " AS name, a.graduation_year, p.code AS program, a.current_company, "
        "a.designation, a.city, a.country, a.email, a.phone, a.is_verified FROM alumni_profiles a "
        "JOIN students s ON s.id = a.student_id LEFT JOIN programs p ON p.id = a.program_id WHERE {where} "
        "ORDER BY a.graduation_year DESC NULLS LAST, s.registration_number"
    ),
    cols={"institution": "a.institution_id", "college": "s.college_id", "program": "a.program_id"},
    columns=[
        C("registration_number", "Reg. no"),
        C("name"),
        C("graduation_year", "Year", type="int"),
        C("program", "Programme"),
        C("current_company", "Company"),
        C("designation"),
        C("city"),
        C("country"),
        C("email", pii=True),
        C("phone", pii=True),
        C("is_verified", "Verified", type="bool"),
    ],
    filters={"graduation_year": "a.graduation_year = :v"},
    params_schema={"properties": {"graduation_year": {"type": "integer"}}},
    dims=("college", "program"),
    layout="landscape",
)

# ============================================================== research / PhD
sql_report(
    "research.publications_list",
    module="research",
    name="Publications",
    category="research",
    permission=("research:view_all", "research:view", "research:manage"),
    feature="research.publications",
    sql=(
        "SELECT p.year, p.pub_type, p.title, p.venue, p.indexing, p.doi, st.employee_id, " + STAFF_NAME + " AS author, "
        "d.code AS department, p.citations, p.is_verified FROM publications p LEFT JOIN staff st ON st.id = p.staff_id "
        "LEFT JOIN departments d ON d.id = st.department_id WHERE {where} ORDER BY p.year DESC NULLS LAST, p.title"
    ),
    cols={"institution": "p.institution_id", **STAFF},
    columns=[
        C("year", type="int"),
        C("pub_type", "Type"),
        C("title"),
        C("venue"),
        C("indexing"),
        C("doi", "DOI"),
        C("employee_id", "Employee ID"),
        C("author"),
        C("department"),
        C("citations", type="int", total=True),
        C("is_verified", "Verified", type="bool"),
    ],
    filters={"year": "p.year = :v", "indexing": "p.indexing = :v"},
    params_schema={"properties": {"year": {"type": "integer"}, "indexing": {"type": "string"}}},
    dims=("college", "department"),
    layout="landscape",
)

sql_report(
    "phd.scholars_list",
    module="phd",
    name="Research scholars",
    category="research",
    permission=("phd:view_all", "phd:manage", "phd:guide", "phd:view"),
    feature="phd.core",
    sql=(
        "SELECT s.registration_number, " + NAME + " AS name, d.code AS department, g.employee_id AS guide, rs.mode, "
        "rs.fellowship_type, rs.registration_date, rs.coursework_status, rs.status, rs.max_duration_end "
        "FROM research_scholars rs JOIN student_program_enrollments e ON e.id = rs.student_program_enrollment_id "
        "JOIN students s ON s.id = e.student_id JOIN departments d ON d.id = e.department_id "
        "JOIN staff g ON g.id = rs.guide_staff_id WHERE {where} ORDER BY d.code, s.registration_number"
    ),
    cols={"institution": "rs.institution_id", **ENROL, "staff": "rs.guide_staff_id"},
    columns=[
        C("registration_number", "Reg. no"),
        C("name"),
        C("department"),
        C("guide"),
        C("mode"),
        C("fellowship_type", "Fellowship"),
        C("registration_date", type="date"),
        C("coursework_status", "Coursework"),
        C("status"),
        C("max_duration_end", "Max duration", type="date"),
    ],
    filters={"status": "rs.status = :v"},
    params_schema={"properties": {"status": {"type": "string"}}},
    dims=("college", "department"),
    layout="landscape",
)

# ============================================================== accreditation / governance / affiliation / audit
sql_report(
    "accreditation.metric_values",
    module="accreditation",
    name="Metric values",
    category="accreditation",
    description="Phase 32 metric values for a period (institution-level and per college / programme)",
    permission=("accreditation:view", "accreditation:view_all", "accreditation:manage"),
    feature="accreditation.aishe",
    sql=(
        "SELECT m.metric_key, md.name, m.period_label, c.code AS college, p.code AS program, m.value, m.numerator, "
        "m.denominator, m.source, (m.verified_at IS NOT NULL) AS verified FROM metric_values m "
        "JOIN metric_definitions md ON md.key = m.metric_key LEFT JOIN colleges c ON c.id = m.college_id "
        "LEFT JOIN programs p ON p.id = m.program_id WHERE {where} ORDER BY m.metric_key, c.code NULLS FIRST, p.code NULLS FIRST"
    ),
    cols={
        "institution": "m.institution_id",
        "college": "m.college_id",
        "program": "m.program_id",
        "department": "p.department_id",
    },
    columns=[
        C("metric_key", "Metric"),
        C("name"),
        C("period_label", "Period"),
        C("college"),
        C("program", "Programme"),
        C("value", type="number"),
        C("numerator", type="number"),
        C("denominator", type="number"),
        C("source"),
        C("verified", type="bool"),
    ],
    filters={"period_label": "m.period_label = :v", "prefix": "m.metric_key LIKE (:v || '%')"},
    params_schema={
        "properties": {
            "period_label": {"type": "string", "title": "Period (e.g. 2025-26)"},
            "prefix": {"type": "string"},
        },
        "required": ["period_label"],
    },
    dims=("college", "program"),
    layout="landscape",
)

sql_report(
    "governance.rti_register",
    module="rti",
    name="RTI register",
    category="governance",
    permission=("rti:view_all", "rti:manage", "rti:approve"),
    feature="governance.rti",
    sql=(
        "SELECT r.received_on, r.request_no, LEFT(r.subject, 200) AS subject, r.due_on, r.responded_on, r.status, "
        "(r.first_appeal IS NOT NULL) AS appealed, r.fee_paise, (r.responded_on IS NOT NULL AND r.responded_on <= r.due_on) "
        "AS within_time FROM rti_requests r WHERE {where} ORDER BY r.received_on, r.request_no"
    ),
    cols={"institution": "r.institution_id", "staff": "r.pio_staff_id"},
    columns=[
        C("received_on", "Received", type="date"),
        C("request_no", "Request no"),
        C("subject"),
        C("due_on", "Due", type="date"),
        C("responded_on", "Responded", type="date"),
        C("status"),
        C("appealed", type="bool"),
        C("fee_paise", "Fee (₹)", type="money"),
        C("within_time", "Within 30 days", type="bool"),
    ],
    date_column="r.received_on",
    layout="landscape",
)

sql_report(
    "governance.resolutions",
    module="governance",
    name="Resolutions register",
    category="governance",
    permission=("governance:view_all", "governance:manage", "governance:view"),
    feature="governance.minutes",
    sql=(
        "SELECT m.held_on::date AS held_on, cm.committee_type, r.number, r.subject, r.status, r.due_on FROM resolutions r "
        "JOIN meetings m ON m.id = r.meeting_id JOIN committees cm ON cm.id = m.committee_id WHERE {where} "
        "ORDER BY m.held_on, r.number"
    ),
    cols={
        "institution": "r.institution_id",
        "college": "cm.college_id",
        "department": "cm.department_id",
        "staff": "r.action_owner_staff_id",
    },
    columns=[
        C("held_on", "Meeting", type="date"),
        C("committee_type", "Committee"),
        C("number"),
        C("subject"),
        C("status"),
        C("due_on", "ATR due", type="date"),
    ],
    filters={"committee_type": "cm.committee_type = :v"},
    params_schema={"properties": {"committee_type": {"type": "string"}}},
    date_column="m.held_on::date",
    dims=("college", "department"),
)

sql_report(
    "affiliation.colleges",
    module="affiliation",
    name="Affiliated colleges",
    category="affiliation",
    permission=("affiliation:view_all", "affiliation:manage", "affiliation:view"),
    feature="affiliation.core",
    sql=(
        "SELECT c.code, c.name, c.college_type, c.affiliation_number, c.affiliated_since, c.aishe_code, "
        "(SELECT COUNT(*) FROM programs p WHERE p.college_id = c.id AND p.status = 'active')::int AS programmes, "
        "(SELECT COUNT(*) FROM student_program_enrollments e WHERE e.college_id = c.id AND e.status = 'active')::int AS students "
        "FROM colleges c WHERE {where} AND c.deleted_at IS NULL AND c.college_type IN ('affiliated', 'autonomous') "
        "ORDER BY c.code"
    ),
    cols={"institution": "c.institution_id", "college": "c.id"},
    columns=[
        C("code"),
        C("name"),
        C("college_type", "Type"),
        C("affiliation_number", "Affiliation no"),
        C("affiliated_since", "Since", type="date"),
        C("aishe_code", "AISHE code"),
        C("programmes", type="int", total=True),
        C("students", type="int", total=True),
    ],
    layout="landscape",
)

sql_report(
    "audit.activity",
    module="audit_logs",
    name="Audit activity",
    category="audit",
    description="Audit-log rows by module / action (who changed what)",
    permission=("audit_logs:view_all",),
    sql=(
        "SELECT a.occurred_at, a.module, a.action, a.record_type, a.record_id, u.email AS user_email FROM audit_logs a "
        "LEFT JOIN users u ON u.id = a.user_id WHERE {where} ORDER BY a.occurred_at DESC"
    ),
    cols={"institution": "a.institution_id"},
    columns=[
        C("occurred_at", "At", type="datetime"),
        C("module"),
        C("action"),
        C("record_type", "Record"),
        C("record_id", "Record id"),
        C("user_email", "User", pii=True),
    ],
    filters={"module": "a.module = :v", "action": "a.action = :v"},
    params_schema={"properties": {"module": {"type": "string"}, "action": {"type": "string"}}},
    date_column="a.occurred_at::date",
    layout="landscape",
)

# Phase 37 audit / exam audit exports
from app.services.audit import registrations as _audit_reports  # noqa: E402, F401

# Phase 38 billing exports (usage by month, subscription invoices)
from app.services.saas import registrations as _saas_reports  # noqa: E402, F401
from app.services.reports import legacy  # noqa: E402, F401  (retro-registered Round 3–4 exports + chart exports)
