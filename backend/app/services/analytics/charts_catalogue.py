"""The retro-registered chart catalogue — Prompts/35 §35.6 chart_service step 1 (≈ 140 keys across the modules).

Providers read the Phase 35 read models where one exists (``source_view`` → ``stale`` flag, longer ``cache_ttl``), else
the module source tables (short ``cache_ttl``). Every query runs under the scope predicate (``{where}`` / ``x.``) of the
chart's **module** visibility. Phase 32 ``metric_values`` (``accreditation.metric_trend`` / ``metrics_verified``), Phase 27
``risk_flags`` (through ``mv_risk_cohort``), Phase 11 ``attendance_summaries`` (``mv_attendance_term``), Phase 13 CIA
(``cia_consolidations``), Phase 15 results (``mv_results_summary``), Phase 12 dues (``mv_fees_position``), Phase 33
governance and Phase 34 affiliation tables are read, never recomputed. Imported once by ``app.services.analytics``.
"""

from typing import Any

from app.services.analytics.chart_helpers import sql_chart, view_chart

ALL = ("college", "department", "program", "batch", "term", "period")
INST = ("college", "period")


def V(module: str) -> tuple[str, ...]:
    return (f"{module}:view_all", f"{module}:manage", f"{module}:view")


def VA(module: str) -> tuple[str, ...]:
    return (f"{module}:view_all", f"{module}:manage")


ACTIVE = "x.status = 'active'"
MONTH = "to_char(date_trunc('month', {c}), 'YYYY-MM')"
EW = "analytics.early_warning"

# ---- students (mv_enrolment_daily) ------------------------------------------------------------------------------------
_S: dict[str, Any] = {
    "module": "students",
    "permission": V("students"),
    "view": "mv_enrolment_daily",
    "route": "/admin/students",
    "drill_rows": "students",
}
view_chart(
    "students.enrolment_by_category",
    title="Enrolment by category",
    label="x.category",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    **_S,
)
view_chart(
    "students.by_gender_program",
    title="Gender by programme",
    kind="stacked",
    label="x.program_id",
    series="x.gender",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    label_kind="program",
    **_S,
)
view_chart(
    "students.enrolment_by_department",
    title="Enrolment by department",
    label="x.department_id",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    label_kind="department",
    **_S,
)
view_chart(
    "students.enrolment_by_program",
    title="Enrolment by programme",
    label="x.program_id",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    label_kind="program",
    **_S,
)
view_chart(
    "students.enrolment_by_batch",
    title="Enrolment by batch",
    label="x.batch_id",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    label_kind="batch",
    **_S,
)
view_chart(
    "students.enrolment_by_quota",
    title="Enrolment by admission quota",
    kind="pie",
    label="x.quota",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    **_S,
)
view_chart(
    "students.enrolment_by_status",
    title="Enrolments by status",
    kind="donut",
    label="x.status",
    measures=(("value", "SUM(x.enrolments)"),),
    **_S,
)
view_chart(
    "students.enrolment_by_college",
    title="Enrolment by college",
    label="x.college_id",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    label_kind="college",
    **_S,
)
view_chart(
    "students.gender_mix",
    title="Gender mix",
    kind="donut",
    label="x.gender",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    **_S,
)
view_chart(
    "students.admissions_trend",
    title="New enrolments by month",
    kind="line",
    label=MONTH.format(c="x.day"),
    measures=(("value", "SUM(x.enrolments)"),),
    where="x.day >= CURRENT_DATE - INTERVAL '24 months'",
    order="1",
    **_S,
)
view_chart(
    "students.active_count",
    title="Active students",
    kind="number",
    label="'total'",
    measures=(("value", "SUM(x.enrolments)"),),
    where=ACTIVE,
    **_S,
)
sql_chart(
    "students.holds_by_type",
    module="students",
    permission=V("students"),
    title="Open holds by type",
    kind="pie",
    sql="SELECT h.hold_type AS label, COUNT(*) AS value FROM student_holds h JOIN student_program_enrollments e "
    "ON e.id = h.student_program_enrollment_id WHERE {where} AND h.released_at IS NULL GROUP BY 1 ORDER BY 2 DESC",
    cols={
        "institution": "h.institution_id",
        "college": "e.college_id",
        "department": "e.department_id",
        "program": "e.program_id",
        "batch": "e.batch_id",
        "enrollment": "h.student_program_enrollment_id",
    },
    dims=("college", "department", "program", "batch"),
    route="/admin/students",
)

# ---- attendance (mv_attendance_term — Phase 11 summaries) ------------------------------------------------------------
_A: dict[str, Any] = {
    "module": "attendance",
    "permission": V("attendance") + ("attendance:self",),
    "view": "mv_attendance_term",
    "current_term": True,
    "route": "/admin/attendance",
    "drill_rows": "attendance",
}
view_chart(
    "attendance.pct_by_department",
    title="Attendance % by department",
    label="x.department_id",
    measures=(("value", "ROUND(AVG(x.pct), 2)"),),
    label_kind="department",
    **_A,
)
view_chart(
    "attendance.pct_by_program",
    title="Attendance % by programme",
    label="x.program_id",
    measures=(("value", "ROUND(AVG(x.pct), 2)"),),
    label_kind="program",
    **_A,
)
view_chart(
    "attendance.pct_by_batch",
    title="Attendance % by batch",
    label="x.batch_id",
    measures=(("value", "ROUND(AVG(x.pct), 2)"),),
    label_kind="batch",
    **_A,
)
view_chart(
    "attendance.pct_by_college",
    title="Attendance % by college",
    label="x.college_id",
    measures=(("value", "ROUND(AVG(x.pct), 2)"),),
    label_kind="college",
    **_A,
)
view_chart(
    "attendance.pct_by_offering",
    title="Attendance % by course offering",
    label="x.offering_id",
    measures=(("value", "ROUND(AVG(x.pct), 2)"),),
    label_kind="offering",
    order="2 ASC",
    **_A,
)
view_chart(
    "attendance.shortfall_list",
    title="Attendance shortfall",
    kind="table",
    label="x.enrollment_id",
    measures=(("value", "ROUND(MIN(x.pct), 2)"), ("courses_short", "COUNT(*)")),
    where="x.is_short",
    label_kind="enrollment",
    order="2 ASC",
    limit=200,
    **_A,
)
view_chart(
    "attendance.shortfall_by_department",
    title="Students below threshold by department",
    label="x.department_id",
    measures=(("value", "COUNT(DISTINCT x.enrollment_id)"),),
    where="x.is_short",
    label_kind="department",
    **_A,
)
view_chart(
    "attendance.eligibility_mix",
    title="Eligibility mix",
    kind="donut",
    label="x.eligibility",
    measures=(("value", "COUNT(*)"),),
    **_A,
)
view_chart(
    "attendance.avg_pct",
    title="Average attendance %",
    kind="gauge",
    label="'attendance_pct'",
    measures=(("value", "ROUND(AVG(x.pct), 2)"),),
    **_A,
)
view_chart(
    "attendance.distribution",
    title="Attendance distribution",
    label="CASE WHEN x.pct < 50 THEN '<50' WHEN x.pct < 65 THEN '50-65' WHEN x.pct < 75 THEN '65-75' WHEN x.pct < 85 THEN '75-85' ELSE '85+' END",
    measures=(("value", "COUNT(*)"),),
    order="1",
    **_A,
)

# ---- fees (mv_fees_position — Phase 12 dues) -------------------------------------------------------------------------
_F: dict[str, Any] = {
    "module": "fees",
    "permission": V("fees") + ("fees:self",),
    "view": "mv_fees_position",
    "route": "/admin/fees/invoices",
    "drill_rows": "fees",
}
view_chart(
    "fees.dues_aging",
    title="Dues aging",
    label="'aging'",
    measures=(
        ("d0_30", "SUM(x.aging_0_30_paise) / 100.0"),
        ("d31_60", "SUM(x.aging_31_60_paise) / 100.0"),
        ("d61_90", "SUM(x.aging_61_90_paise) / 100.0"),
        ("d90_plus", "SUM(x.aging_90_plus_paise) / 100.0"),
    ),
    kind="stacked",
    order="1",
    **_F,
)
view_chart(
    "fees.billed_vs_paid_by_department",
    title="Billed vs paid by department (₹)",
    kind="stacked",
    label="x.department_id",
    measures=(("paid", "SUM(x.paid_paise) / 100.0"), ("balance", "SUM(x.balance_paise) / 100.0")),
    label_kind="department",
    **_F,
)
view_chart(
    "fees.overdue_by_program",
    title="Overdue by programme (₹)",
    label="x.program_id",
    measures=(("value", "SUM(x.overdue_paise) / 100.0"),),
    label_kind="program",
    **_F,
)
view_chart(
    "fees.defaulters_by_batch",
    title="Defaulters by batch",
    label="x.batch_id",
    measures=(("value", "COUNT(*) FILTER (WHERE x.overdue_paise > 0)"),),
    label_kind="batch",
    **_F,
)
view_chart(
    "fees.collection_pct",
    title="Fee collection %",
    kind="gauge",
    label="'fee_collection_pct'",
    measures=(("value", "ROUND(100.0 * SUM(x.paid_paise) / NULLIF(SUM(x.billed_paise), 0), 2)"),),
    **_F,
)
view_chart(
    "fees.overdue_total",
    title="Overdue dues (₹)",
    kind="number",
    label="'total'",
    measures=(("value", "SUM(x.overdue_paise) / 100.0"),),
    **_F,
)
view_chart(
    "fees.collection_by_college",
    title="Collection % by college",
    label="x.college_id",
    measures=(("value", "ROUND(100.0 * SUM(x.paid_paise) / NULLIF(SUM(x.billed_paise), 0), 2)"),),
    label_kind="college",
    **_F,
)
view_chart(
    "fees.my_dues",
    title="My dues (₹)",
    kind="number",
    label="'total'",
    measures=(("value", "SUM(x.balance_paise) / 100.0"),),
    **_F,
)
_PAY = "FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id LEFT JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id WHERE {where} AND p.status IN ('success', 'reconciled') AND p.payment_date >= :_from AND p.payment_date < :_to"
_PAYC: dict[str, Any] = {
    "institution": "p.institution_id",
    "college": "i.college_id",
    "department": "e.department_id",
    "program": "e.program_id",
    "batch": "e.batch_id",
    "enrollment": "i.student_program_enrollment_id",
}
sql_chart(
    "fees.collection_by_mode_daily",
    module="fees",
    permission=VA("fees"),
    title="Collection by mode (daily, ₹)",
    kind="stacked",
    sql=f"SELECT p.payment_date::date AS label, p.payment_mode AS series, SUM(p.amount_paise) / 100.0 AS value {_PAY} GROUP BY 1, 2 ORDER BY 1",
    cols=_PAYC,
    period="last_30d",
    route="/admin/fees/payments",
    drill_rows="payments",
)
sql_chart(
    "fees.collection_trend",
    module="fees",
    permission=VA("fees"),
    title="Collection trend (₹)",
    kind="line",
    sql=f"SELECT to_char(date_trunc('month', p.payment_date), 'YYYY-MM') AS label, SUM(p.amount_paise) / 100.0 AS value {_PAY} GROUP BY 1 ORDER BY 1",
    cols=_PAYC,
    period="last_12m",
)
sql_chart(
    "fees.collected_today",
    module="fees",
    permission=VA("fees"),
    title="Collected today (₹)",
    kind="number",
    sql=f"SELECT 'today' AS label, COALESCE(SUM(p.amount_paise), 0) / 100.0 AS value {_PAY}",
    cols=_PAYC,
    period="today",
    ttl=60,
)
sql_chart(
    "fees.collection_by_mode",
    module="fees",
    permission=VA("fees"),
    title="Collection by mode (₹)",
    kind="pie",
    sql=f"SELECT p.payment_mode AS label, SUM(p.amount_paise) / 100.0 AS value {_PAY} GROUP BY 1 ORDER BY 2 DESC",
    cols=_PAYC,
    period="this_month",
)
_SCH: dict[str, Any] = {
    "institution": "a.institution_id",
    "college": "e.college_id",
    "department": "e.department_id",
    "program": "e.program_id",
    "batch": "e.batch_id",
    "enrollment": "a.student_program_enrollment_id",
}
sql_chart(
    "fees.scholarship_disbursed",
    module="scholarships",
    permission=V("scholarships") + VA("fees"),
    title="Scholarships disbursed (₹)",
    kind="bar",
    sql="SELECT to_char(date_trunc('month', a.disbursed_at), 'YYYY-MM') AS label, SUM(a.sanctioned_paise) / 100.0 AS value FROM scholarship_applications a JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id WHERE {where} AND a.status = 'disbursed' AND a.disbursed_at >= :_from GROUP BY 1 ORDER BY 1",
    cols=_SCH,
    period="fy",
)
sql_chart(
    "fees.scholarships_by_status",
    module="scholarships",
    permission=V("scholarships") + VA("fees"),
    title="Scholarship applications by status",
    kind="donut",
    sql="SELECT a.status AS label, COUNT(*) AS value FROM scholarship_applications a JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id WHERE {where} GROUP BY 1 ORDER BY 2 DESC",
    cols=_SCH,
    dims=("college", "department", "program", "batch"),
)
sql_chart(
    "fees.refunds_pending",
    module="fees",
    permission=VA("fees"),
    title="Refunds pending",
    kind="number",
    sql="SELECT 'pending' AS label, COUNT(*) AS value FROM fee_refunds r JOIN fee_invoices i ON i.id = r.invoice_id WHERE {where} AND r.status IN ('requested', 'approved')",
    cols={"institution": "r.institution_id", "college": "i.college_id"},
    dims=("college",),
)
sql_chart(
    "fees.no_dues_status",
    module="no_dues",
    permission=V("no_dues") + VA("fees"),
    title="No-dues requests",
    kind="pie",
    sql="SELECT n.status AS label, COUNT(*) AS value FROM no_dues_requests n JOIN student_program_enrollments e ON e.id = n.student_program_enrollment_id WHERE {where} GROUP BY 1",
    cols={
        "institution": "n.institution_id",
        "college": "e.college_id",
        "department": "e.department_id",
        "enrollment": "n.student_program_enrollment_id",
    },
    dims=("college", "department"),
)
sql_chart(
    "fees.day_book_status",
    module="fees",
    permission=VA("fees"),
    title="Day book (reconciliation pending)",
    kind="bar",
    sql="SELECT d.status AS label, COUNT(*) AS value FROM day_book_entries d WHERE {where} AND d.entry_date >= :_from GROUP BY 1",
    cols={"institution": "d.institution_id", "college": "d.college_id"},
    period="last_30d",
    dims=("college", "period"),
)

# ---- exams (mv_exam_progress) ------------------------------------------------------------------------------------------
_E: dict[str, Any] = {
    "module": "exams",
    "permission": V("exams"),
    "view": "mv_exam_progress",
    "route": "/admin/exams/sessions",
    "dims": ("college", "term"),
}
view_chart(
    "exams.session_progress",
    title="Exam session status board",
    kind="table",
    label="x.exam_session_id",
    measures=(
        ("registrations", "SUM(x.registrations)"),
        ("hall_tickets", "SUM(x.hall_tickets)"),
        ("scripts", "SUM(x.scripts)"),
        ("valuation_pct", "MAX(x.valuation_pct)"),
        ("discrepancies", "SUM(x.discrepancies)"),
    ),
    label_kind="session",
    where="x.status NOT IN ('draft', 'closed')",
    **_E,
)
view_chart(
    "exams.valuation_pct",
    title="Valuation progress %",
    label="x.exam_session_id",
    measures=(("value", "MAX(x.valuation_pct)"),),
    label_kind="session",
    where="x.status IN ('in_progress', 'valuation', 'result_processing')",
    **_E,
)
view_chart(
    "exams.registrations_by_session",
    title="Registrations by session",
    label="x.exam_session_id",
    measures=(("value", "SUM(x.registrations)"),),
    label_kind="session",
    **_E,
)
view_chart(
    "exams.hall_tickets_by_session",
    title="Hall tickets issued",
    kind="stacked",
    label="x.exam_session_id",
    measures=(("hall_tickets", "SUM(x.hall_tickets)"), ("pending", "SUM(x.registrations - x.hall_tickets)")),
    label_kind="session",
    where="x.status NOT IN ('draft', 'closed')",
    **_E,
)
view_chart(
    "exams.discrepancies_open",
    title="Valuation discrepancies",
    label="x.exam_session_id",
    measures=(("value", "SUM(x.discrepancies)"),),
    label_kind="session",
    where="x.discrepancies > 0",
    **_E,
)
view_chart(
    "exams.sessions_by_status",
    title="Sessions by status",
    kind="donut",
    label="x.status",
    measures=(("value", "COUNT(*)"),),
    **_E,
)
view_chart(
    "exams.active_sessions",
    title="Active exam sessions",
    kind="number",
    label="'total'",
    measures=(("value", "COUNT(*)"),),
    where="x.status NOT IN ('draft', 'results_published', 'closed')",
    **_E,
)
view_chart(
    "exams.results_stage",
    title="Results stage",
    kind="pie",
    label="x.results_stage",
    measures=(("value", "COUNT(*)"),),
    **_E,
)
_RV: dict[str, Any] = {"institution": "r.institution_id", "college": "s.college_id"}
sql_chart(
    "exams.reval_queue",
    module="exams",
    permission=V("exams"),
    title="Revaluation queue",
    kind="bar",
    sql="SELECT r.status AS label, COUNT(*) AS value FROM reval_requests r JOIN exam_sessions s ON s.id = r.exam_session_id WHERE {where} GROUP BY 1 ORDER BY 2 DESC",
    cols=_RV,
    dims=("college",),
    route="/admin/exams/revaluation",
)
sql_chart(
    "exams.malpractice_open",
    module="exams",
    permission=V("exams"),
    title="Malpractice cases open",
    kind="number",
    sql="SELECT 'open' AS label, COUNT(*) AS value FROM malpractice_cases r JOIN exam_sessions s ON s.id = r.exam_session_id WHERE {where} AND r.status NOT IN ('decided', 'closed')",
    cols=_RV,
    dims=("college",),
)
sql_chart(
    "exams.malpractice_by_category",
    module="exams",
    permission=V("exams"),
    title="Malpractice by category",
    kind="pie",
    sql="SELECT r.category AS label, COUNT(*) AS value FROM malpractice_cases r JOIN exam_sessions s ON s.id = r.exam_session_id WHERE {where} GROUP BY 1",
    cols=_RV,
    dims=("college",),
)

# ---- results (mv_results_summary — Phase 15) --------------------------------------------------------------------------
_R: dict[str, Any] = {
    "module": "results",
    "permission": V("results") + ("results:self",),
    "view": "mv_results_summary",
    "route": "/admin/results/analysis",
    "drill_rows": "results",
}
view_chart(
    "results.pass_pct_by_program",
    title="Pass % by programme",
    label="x.program_id",
    measures=(("value", "ROUND(100.0 * SUM(x.passed) / NULLIF(SUM(x.students), 0), 2)"),),
    label_kind="program",
    **_R,
)
view_chart(
    "results.pass_pct_by_department",
    title="Pass % by department",
    label="x.department_id",
    measures=(("value", "ROUND(100.0 * SUM(x.passed) / NULLIF(SUM(x.students), 0), 2)"),),
    label_kind="department",
    **_R,
)
view_chart(
    "results.pass_pct_by_batch",
    title="Pass % by batch",
    label="x.batch_id",
    measures=(("value", "ROUND(100.0 * SUM(x.passed) / NULLIF(SUM(x.students), 0), 2)"),),
    label_kind="batch",
    **_R,
)
view_chart(
    "results.pass_pct_by_college",
    title="Pass % by college",
    label="x.college_id",
    measures=(("value", "ROUND(100.0 * SUM(x.passed) / NULLIF(SUM(x.students), 0), 2)"),),
    label_kind="college",
    **_R,
)
view_chart(
    "results.sgpa_histogram",
    title="SGPA distribution",
    label="'sgpa'",
    measures=(
        ("lt5", "SUM(x.sgpa_lt5)"),
        ("s5_6", "SUM(x.sgpa_5_6)"),
        ("s6_7", "SUM(x.sgpa_6_7)"),
        ("s7_8", "SUM(x.sgpa_7_8)"),
        ("s8_9", "SUM(x.sgpa_8_9)"),
        ("s9_plus", "SUM(x.sgpa_9_plus)"),
    ),
    kind="stacked",
    order="1",
    **_R,
)
view_chart(
    "results.arrears_by_program",
    title="Arrears by programme",
    label="x.program_id",
    measures=(("value", "SUM(x.arrears)"),),
    label_kind="program",
    **_R,
)
view_chart(
    "results.toppers",
    title="Top SGPA by programme",
    kind="table",
    label="x.program_id",
    measures=(("value", "MAX(x.top_sgpa)"), ("avg_sgpa", "ROUND(AVG(x.avg_sgpa), 2)")),
    label_kind="program",
    **_R,
)
view_chart(
    "results.pass_pct_trend",
    title="Pass % by term",
    kind="line",
    label="x.term_id",
    measures=(("value", "ROUND(100.0 * SUM(x.passed) / NULLIF(SUM(x.students), 0), 2)"),),
    label_kind="term",
    order="1",
    **_R,
)
view_chart(
    "results.pass_pct",
    title="Result pass %",
    kind="gauge",
    label="'result_pass_pct'",
    measures=(("value", "ROUND(100.0 * SUM(x.passed) / NULLIF(SUM(x.students), 0), 2)"),),
    **_R,
)
view_chart(
    "results.avg_sgpa_by_batch",
    title="Average SGPA by batch",
    label="x.batch_id",
    measures=(("value", "ROUND(AVG(x.avg_sgpa), 2)"),),
    label_kind="batch",
    **_R,
)
sql_chart(
    "results.arrears_by_course",
    module="results",
    permission=VA("results"),
    title="Arrears by course",
    sql="SELECT r.course_id AS label, COUNT(*) AS value FROM student_course_results r JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id WHERE {where} AND r.is_current AND r.result_status = 'fail' GROUP BY 1 ORDER BY 2 DESC LIMIT 25",
    cols={
        "institution": "r.institution_id",
        "college": "r.college_id",
        "department": "e.department_id",
        "program": "e.program_id",
        "batch": "e.batch_id",
        "term": "r.term_id",
        "enrollment": "r.student_program_enrollment_id",
    },
    label_kind="course",
    dims=("college", "department", "program", "batch", "term"),
)
sql_chart(
    "results.my_sgpa_trend",
    module="results",
    permission=("results:self",) + V("results"),
    title="SGPA trend",
    kind="line",
    sql="SELECT t.name AS label, r.sgpa AS value, (SELECT ROUND(AVG(r2.sgpa), 2) FROM student_term_results r2 JOIN student_term_records tr2 ON tr2.id = r2.student_term_record_id JOIN student_program_enrollments e2 ON e2.id = tr2.student_program_enrollment_id WHERE r2.is_current AND r2.status = 'published' AND tr2.term_id = tr.term_id AND e2.batch_id = e.batch_id) AS class_average FROM student_term_results r JOIN student_term_records tr ON tr.id = r.student_term_record_id JOIN student_program_enrollments e ON e.id = tr.student_program_enrollment_id JOIN academic_terms t ON t.id = tr.term_id WHERE {where} AND r.is_current AND r.status = 'published' ORDER BY t.start_date",
    cols={"institution": "r.institution_id", "enrollment": "tr.student_program_enrollment_id"},
    dims=(),
    description="Own SGPA per term with the class (batch) average as the only comparison",
)

# ---- HR (mv_hr_snapshot) ------------------------------------------------------------------------------------------------
_H: dict[str, Any] = {
    "module": "hr",
    "permission": V("hr"),
    "view": "mv_hr_snapshot",
    "route": "/admin/hr/staff",
    "dims": ("college", "department"),
    "drill_rows": "staff",
}
view_chart(
    "hr.staff_by_cadre", title="Staff by cadre", label="x.cadre", measures=(("value", "SUM(x.headcount)"),), **_H
)
view_chart(
    "hr.staff_by_department",
    title="Staff by department",
    label="x.department_id",
    measures=(("value", "SUM(x.headcount)"),),
    label_kind="department",
    **_H,
)
view_chart(
    "hr.staff_by_category",
    title="Teaching / non-teaching",
    kind="donut",
    label="x.staff_category",
    measures=(("value", "SUM(x.headcount)"),),
    **_H,
)
view_chart(
    "hr.staff_by_designation",
    title="Staff by designation",
    label="x.designation_id",
    measures=(("value", "SUM(x.headcount)"),),
    label_kind="designation",
    **_H,
)
view_chart(
    "hr.attendance_today",
    title="Staff attendance today",
    kind="stacked",
    label="x.department_id",
    measures=(
        ("present", "SUM(x.present_today)"),
        ("on_leave", "SUM(x.on_leave_today)"),
        ("not_marked", "SUM(GREATEST(x.headcount - x.present_today - x.on_leave_today, 0))"),
    ),
    label_kind="department",
    ttl=300,
    **_H,
)
view_chart(
    "hr.leaves_pending_by_department",
    title="Leaves pending by department",
    label="x.department_id",
    measures=(("value", "SUM(x.leaves_pending)"),),
    label_kind="department",
    **_H,
)
view_chart(
    "hr.headcount", title="Headcount", kind="number", label="'total'", measures=(("value", "SUM(x.headcount)"),), **_H
)
view_chart(
    "hr.present_today",
    title="Staff present today",
    kind="number",
    label="'total'",
    measures=(("value", "SUM(x.present_today)"),),
    ttl=300,
    **_H,
)
view_chart(
    "hr.staff_by_college",
    title="Staff by college",
    label="x.college_id",
    measures=(("value", "SUM(x.headcount)"),),
    label_kind="college",
    **_H,
)
_LV: dict[str, Any] = {
    "institution": "l.institution_id",
    "college": "s.college_id",
    "department": "s.department_id",
    "staff": "l.staff_id",
}
sql_chart(
    "hr.leaves_trend",
    module="leaves",
    permission=V("leaves") + VA("hr"),
    title="Leaves by month",
    kind="line",
    sql="SELECT to_char(date_trunc('month', l.from_date), 'YYYY-MM') AS label, SUM(l.days_count) AS value FROM staff_leaves l JOIN staff s ON s.id = l.staff_id WHERE {where} AND l.status = 'approved' AND l.from_date >= :_from GROUP BY 1 ORDER BY 1",
    cols=_LV,
    period="last_12m",
    route="/admin/hr/leaves",
)
sql_chart(
    "hr.leaves_by_status",
    module="leaves",
    permission=V("leaves") + VA("hr"),
    title="Leave requests by status",
    kind="donut",
    sql="SELECT l.status AS label, COUNT(*) AS value FROM staff_leaves l JOIN staff s ON s.id = l.staff_id WHERE {where} AND l.from_date >= :_from GROUP BY 1",
    cols=_LV,
    period="last_90d",
    route="/admin/hr/leaves",
)
sql_chart(
    "hr.vacancies",
    module="recruitment",
    permission=V("recruitment") + VA("hr"),
    title="Open vacancies by department",
    sql="SELECT j.department_id AS label, SUM(j.vacancies) AS value FROM job_postings j WHERE {where} AND j.status = 'open' GROUP BY 1 ORDER BY 2 DESC",
    cols={"institution": "j.institution_id", "college": "j.college_id", "department": "j.department_id"},
    label_kind="department",
    dims=("college", "department"),
)

# ---- admissions (mv_admissions_funnel) -----------------------------------------------------------------------------------
_AD: dict[str, Any] = {
    "module": "admissions",
    "permission": V("admissions"),
    "view": "mv_admissions_funnel",
    "route": "/admin/admissions/applicants",
    "dims": ("college", "program"),
    "drill_rows": "applicants",
}
view_chart(
    "admissions.funnel",
    title="Admissions funnel",
    kind="funnel",
    label="'funnel'",
    measures=(
        ("applications", "SUM(x.applications)"),
        ("verified", "SUM(x.verified)"),
        ("merit", "SUM(x.merit)"),
        ("allotted", "SUM(x.allotted)"),
        ("admitted", "SUM(x.admitted)"),
    ),
    order="1",
    params_schema={"type": "object", "properties": {"cycle_id": {"type": "string", "format": "uuid"}}},
    **_AD,
)
view_chart(
    "admissions.seat_fill",
    title="Seat fill by programme",
    kind="stacked",
    label="x.program_id",
    measures=(("admitted", "SUM(x.admitted)"), ("allotted_pending", "SUM(x.allotted - x.admitted)")),
    label_kind="program",
    **_AD,
)
view_chart(
    "admissions.funnel_by_category",
    title="Applications by category",
    kind="stacked",
    label="x.category",
    measures=(("applications", "SUM(x.applications)"), ("admitted", "SUM(x.admitted)")),
    **_AD,
)
view_chart(
    "admissions.funnel_by_quota",
    title="Applications by quota",
    kind="stacked",
    label="x.quota",
    measures=(("applications", "SUM(x.applications)"), ("admitted", "SUM(x.admitted)")),
    **_AD,
)
view_chart(
    "admissions.applications_by_cycle",
    title="Applications by cycle",
    label="x.cycle_id",
    measures=(("value", "SUM(x.applications)"),),
    label_kind="cycle",
    **_AD,
)
view_chart(
    "admissions.admitted",
    title="Admitted (open cycles)",
    kind="number",
    label="'total'",
    measures=(("value", "SUM(x.admitted)"),),
    **_AD,
)
_EQ: dict[str, Any] = {"institution": "q.institution_id", "college": "q.college_id"}
sql_chart(
    "admissions.enquiries_by_stage",
    module="admissions",
    permission=V("admissions"),
    title="Enquiries by stage",
    kind="funnel",
    sql="SELECT q.stage AS label, COUNT(*) AS value FROM enquiries q WHERE {where} AND q.created_at >= :_from GROUP BY 1 ORDER BY 2 DESC",
    cols=_EQ,
    period="this_year",
    dims=INST,
    route="/admin/admissions/enquiries",
)
sql_chart(
    "admissions.enquiries_by_source",
    module="admissions",
    permission=V("admissions"),
    title="Enquiries by source",
    kind="pie",
    sql="SELECT q.source AS label, COUNT(*) AS value FROM enquiries q WHERE {where} AND q.created_at >= :_from GROUP BY 1 ORDER BY 2 DESC",
    cols=_EQ,
    period="this_year",
    dims=INST,
)
sql_chart(
    "admissions.allotments_by_status",
    module="admissions",
    permission=V("admissions"),
    title="Seat allotments by status",
    kind="bar",
    sql="SELECT a.status AS label, COUNT(*) AS value FROM seat_allotments a WHERE {where} GROUP BY 1 ORDER BY 2 DESC",
    cols={"institution": "a.institution_id", "college": "a.college_id", "program": "a.program_id"},
    dims=("college", "program"),
)

# ---- registration / LMS / CIA (source tables) -----------------------------------------------------------------------
_CR: dict[str, Any] = {
    "institution": "c.institution_id",
    "college": "c.college_id",
    "department": "e.department_id",
    "program": "e.program_id",
    "batch": "e.batch_id",
    "term": "c.term_id",
    "enrollment": "c.student_program_enrollment_id",
}
sql_chart(
    "registration.progress",
    module="registration",
    permission=V("registration"),
    title="Registration progress (current term)",
    kind="funnel",
    sql="SELECT c.status AS label, COUNT(*) AS value FROM course_registrations c JOIN student_program_enrollments e ON e.id = c.student_program_enrollment_id WHERE {where} AND c.term_id IN (SELECT id FROM academic_terms WHERE institution_id = :_inst AND is_current) GROUP BY 1 ORDER BY 2 DESC",
    cols=_CR,
    dims=("college", "department", "program", "batch"),
    route="/admin/registration/windows",
)
_OF: dict[str, Any] = {
    "institution": "o.institution_id",
    "college": "o.college_id",
    "department": "o.department_id",
    "term": "o.term_id",
    "offering": "o.id",
}
_CUR = "o.term_id IN (SELECT id FROM academic_terms WHERE institution_id = :_inst AND is_current)"
sql_chart(
    "registration.waitlists",
    module="registration",
    permission=V("registration") + V("offerings"),
    title="Waitlists by department",
    sql=f"SELECT o.department_id AS label, SUM(o.waitlist_count) AS value FROM course_offerings o WHERE {{where}} AND {_CUR} AND o.deleted_at IS NULL GROUP BY 1 HAVING SUM(o.waitlist_count) > 0 ORDER BY 2 DESC",
    cols=_OF,
    label_kind="department",
    dims=("college", "department"),
)
sql_chart(
    "registration.seat_utilisation",
    module="offerings",
    permission=V("offerings") + V("registration"),
    title="Seat utilisation by department",
    kind="stacked",
    sql=f"SELECT o.department_id AS label, SUM(o.enrolled_count) AS enrolled, SUM(GREATEST(o.max_seats - o.enrolled_count, 0)) AS vacant FROM course_offerings o WHERE {{where}} AND {_CUR} AND o.deleted_at IS NULL GROUP BY 1 ORDER BY 2 DESC",
    cols=_OF,
    label_kind="department",
    dims=("college", "department"),
)
_LMS: dict[str, Any] = {
    "institution": "a.institution_id",
    "college": "o.college_id",
    "department": "o.department_id",
    "offering": "a.offering_id",
}
sql_chart(
    "lms.assignment_submission_rate",
    module="lms",
    permission=V("lms"),
    title="Assignment submission rate by offering (%)",
    sql=f"SELECT a.offering_id AS label, ROUND(100.0 * COUNT(s.id) FILTER (WHERE s.submitted_at IS NOT NULL) / NULLIF(COUNT(DISTINCT a.id) * MAX(o.enrolled_count), 0), 2) AS value FROM lms_assignments a JOIN course_offerings o ON o.id = a.offering_id LEFT JOIN assignment_submissions s ON s.assignment_id = a.id WHERE {{where}} AND {_CUR} GROUP BY 1 ORDER BY 2 ASC LIMIT 30",
    cols=_LMS,
    label_kind="offering",
    dims=("college", "department"),
)
sql_chart(
    "lms.late_submissions",
    module="lms",
    permission=V("lms"),
    title="Late submissions (term)",
    kind="number",
    sql=f"SELECT 'late' AS label, COUNT(s.id) AS value FROM lms_assignments a JOIN course_offerings o ON o.id = a.offering_id JOIN assignment_submissions s ON s.assignment_id = a.id WHERE {{where}} AND {_CUR} AND s.is_late",
    cols=_LMS,
    dims=("college", "department"),
)
sql_chart(
    "marks.cia_status",
    module="marks",
    permission=V("marks"),
    title="CIA consolidation status (current term)",
    kind="donut",
    sql=f"SELECT c.status AS label, COUNT(*) AS value FROM cia_consolidations c JOIN course_offerings o ON o.id = c.offering_id WHERE {{where}} AND {_CUR} GROUP BY 1",
    cols={
        "institution": "c.institution_id",
        "college": "o.college_id",
        "department": "o.department_id",
        "offering": "c.offering_id",
        "enrollment": "c.student_program_enrollment_id",
    },
    dims=("college", "department"),
)
sql_chart(
    "marks.cia_avg_by_offering",
    module="marks",
    permission=V("marks"),
    title="CIA average by offering",
    sql=f"SELECT c.offering_id AS label, ROUND(AVG(c.cia_scaled), 2) AS value FROM cia_consolidations c JOIN course_offerings o ON o.id = c.offering_id WHERE {{where}} AND {_CUR} GROUP BY 1 ORDER BY 2 ASC LIMIT 30",
    cols={
        "institution": "c.institution_id",
        "college": "o.college_id",
        "department": "o.department_id",
        "offering": "c.offering_id",
        "enrollment": "c.student_program_enrollment_id",
    },
    label_kind="offering",
    dims=("college", "department"),
)

# ---- hostel (mv_hostel_occupancy) -------------------------------------------------------------------------------------------
_HO: dict[str, Any] = {
    "module": "hostel",
    "permission": V("hostel"),
    "view": "mv_hostel_occupancy",
    "route": "/admin/hostel/allocations",
    "dims": ("college",),
}
view_chart(
    "hostel.occupancy",
    title="Hostel occupancy",
    kind="stacked",
    label="x.hostel_id",
    measures=(("occupied", "SUM(x.occupied)"), ("vacant", "SUM(x.beds - x.occupied)")),
    label_kind="hostel",
    **_HO,
)
view_chart(
    "hostel.occupancy_by_block",
    title="Occupancy by block",
    kind="stacked",
    label="x.block_id",
    measures=(("occupied", "SUM(x.occupied)"), ("vacant", "SUM(x.beds - x.occupied)")),
    label_kind="block",
    **_HO,
)
view_chart(
    "hostel.occupancy_pct",
    title="Occupancy %",
    kind="gauge",
    label="'hostel_occupancy_pct'",
    measures=(("value", "ROUND(100.0 * SUM(x.occupied) / NULLIF(SUM(x.beds), 0), 2)"),),
    **_HO,
)
view_chart(
    "hostel.leaves_today",
    title="Students out on leave",
    label="x.hostel_id",
    measures=(("value", "SUM(x.leave_out_today)"),),
    label_kind="hostel",
    ttl=300,
    **_HO,
)
view_chart(
    "hostel.complaints_open",
    title="Open complaints",
    label="x.hostel_id",
    measures=(("value", "SUM(x.complaints_open)"),),
    label_kind="hostel",
    **_HO,
)
sql_chart(
    "hostel.complaints_by_category",
    module="hostel",
    permission=V("hostel"),
    title="Complaints by category",
    kind="pie",
    sql="SELECT c.category AS label, COUNT(*) AS value FROM hostel_complaints c JOIN hostels h ON h.id = c.hostel_id WHERE {where} AND c.created_at >= :_from GROUP BY 1",
    cols={
        "institution": "c.institution_id",
        "college": "h.college_id",
        "hostel": "c.hostel_id",
        "enrollment": "c.student_program_enrollment_id",
    },
    period="last_90d",
    dims=INST,
)
sql_chart(
    "hostel.late_returns",
    module="hostel",
    permission=V("hostel"),
    title="Late returns (last 30 days)",
    kind="bar",
    sql="SELECT l.hostel_id AS label, COUNT(*) AS value FROM hostel_leaves l JOIN hostels h ON h.id = l.hostel_id WHERE {where} AND l.late_minutes > 0 AND l.actual_return_at >= :_from GROUP BY 1",
    cols={
        "institution": "l.institution_id",
        "college": "h.college_id",
        "hostel": "l.hostel_id",
        "enrollment": "l.student_program_enrollment_id",
    },
    label_kind="hostel",
    period="last_30d",
    dims=INST,
)
sql_chart(
    "hostel.mess_attendance",
    module="hostel",
    permission=VA("hostel"),
    title="Mess attendance (7 days)",
    kind="stacked",
    sql="SELECT m.on_date AS label, m.status AS series, COUNT(*) AS value FROM mess_attendance m WHERE {where} AND m.on_date >= :_from GROUP BY 1, 2 ORDER BY 1",
    cols={"institution": "m.institution_id"},
    period="last_7d",
    dims=("period",),
)

# ---- library / transport / inventory / accounting / comms / events -------------------------------------------------------
_BI: dict[str, Any] = {"institution": "b.institution_id"}
sql_chart(
    "library.circulation_trend",
    module="library",
    permission=V("library"),
    title="Circulation by month",
    kind="line",
    sql="SELECT to_char(date_trunc('month', b.issued_on), 'YYYY-MM') AS label, COUNT(*) AS value FROM book_issues b WHERE {where} AND b.issued_on >= :_from GROUP BY 1 ORDER BY 1",
    cols=_BI,
    period="last_12m",
    dims=("period",),
    route="/admin/library/circulation",
)
sql_chart(
    "library.overdues",
    module="library",
    permission=V("library"),
    title="Overdue books",
    kind="number",
    sql="SELECT 'overdue' AS label, COUNT(*) AS value FROM book_issues b WHERE {where} AND b.returned_on IS NULL AND b.due_on < CURRENT_DATE",
    cols=_BI,
    dims=(),
)
sql_chart(
    "library.issues_by_member_type",
    module="library",
    permission=V("library"),
    title="Issues by member type",
    kind="pie",
    sql="SELECT m.member_type AS label, COUNT(*) AS value FROM book_issues b JOIN library_members m ON m.id = b.member_id WHERE {where} AND b.issued_on >= :_from GROUP BY 1",
    cols=_BI,
    period="this_year",
    dims=("period",),
)
sql_chart(
    "library.fines_trend",
    module="library",
    permission=V("library"),
    title="Fines (₹) by month",
    kind="bar",
    sql="SELECT to_char(date_trunc('month', b.returned_on), 'YYYY-MM') AS label, SUM(b.fine_paise) / 100.0 AS value FROM book_issues b WHERE {where} AND b.returned_on >= :_from AND b.fine_paise > 0 GROUP BY 1 ORDER BY 1",
    cols=_BI,
    period="last_12m",
    dims=("period",),
)
sql_chart(
    "transport.trips_today",
    module="transport",
    permission=V("transport"),
    title="Trips today",
    kind="pie",
    sql="SELECT t.status AS label, COUNT(*) AS value FROM transport_trips t WHERE {where} AND t.trip_date = CURRENT_DATE GROUP BY 1",
    cols={"institution": "t.institution_id"},
    dims=(),
    ttl=60,
    route="/admin/transport/trips",
)
sql_chart(
    "transport.vehicle_alerts",
    module="transport",
    permission=V("transport"),
    title="Vehicle documents expiring (30 days)",
    kind="bar",
    sql="SELECT v.vehicle_type AS label, COUNT(*) AS value FROM vehicles v WHERE {where} AND v.deleted_at IS NULL AND LEAST(COALESCE(v.insurance_expiry, '9999-12-31'), COALESCE(v.fitness_expiry, '9999-12-31'), COALESCE(v.permit_expiry, '9999-12-31'), COALESCE(v.puc_expiry, '9999-12-31')) <= CURRENT_DATE + 30 GROUP BY 1",
    cols={"institution": "v.institution_id", "college": "v.college_id"},
    dims=("college",),
)
sql_chart(
    "transport.gps_health",
    module="transport",
    permission=V("transport"),
    title="Vehicles with GPS",
    kind="donut",
    sql="SELECT CASE WHEN v.gps_device_id IS NULL THEN 'no device' ELSE 'device' END AS label, COUNT(*) AS value FROM vehicles v WHERE {where} AND v.deleted_at IS NULL GROUP BY 1",
    cols={"institution": "v.institution_id", "college": "v.college_id"},
    dims=("college",),
)
sql_chart(
    "inventory.indents_by_status",
    module="inventory",
    permission=V("inventory") + V("procurement"),
    title="Indents by status",
    kind="bar",
    sql="SELECT i.status AS label, COUNT(*) AS value FROM indents i WHERE {where} AND i.created_at >= :_from GROUP BY 1",
    cols={"institution": "i.institution_id", "department": "i.department_id"},
    period="fy",
    dims=("department", "period"),
)
sql_chart(
    "inventory.po_value_trend",
    module="procurement",
    permission=V("procurement") + V("inventory"),
    title="Purchase orders (₹) by month",
    kind="bar",
    sql="SELECT to_char(date_trunc('month', p.order_date), 'YYYY-MM') AS label, SUM(p.total_paise) / 100.0 AS value FROM purchase_orders p WHERE {where} AND p.order_date >= :_from GROUP BY 1 ORDER BY 1",
    cols={"institution": "p.institution_id"},
    period="fy",
    dims=("period",),
)
sql_chart(
    "inventory.assets_by_category",
    module="inventory",
    permission=V("inventory"),
    title="Assets by category",
    kind="pie",
    sql="SELECT a.category AS label, COUNT(*) AS value FROM assets a WHERE {where} AND a.deleted_at IS NULL GROUP BY 1 ORDER BY 2 DESC",
    cols={
        "institution": "a.institution_id",
        "college": "a.college_id",
        "department": "a.department_id",
        "staff": "a.custodian_staff_id",
    },
    dims=("college", "department"),
)
sql_chart(
    "inventory.stock_alerts",
    module="inventory",
    permission=V("inventory"),
    title="Items at zero stock",
    kind="number",
    sql="SELECT 'zero' AS label, COUNT(*) AS value FROM stock_levels s WHERE {where} AND s.quantity <= 0",
    cols={"institution": "s.institution_id"},
    dims=(),
)
sql_chart(
    "accounting.income_vs_expense",
    module="accounting",
    permission=V("accounting"),
    title="Income vs expense (₹)",
    kind="line",
    sql="SELECT t.label, t.series, SUM(t.value) AS value FROM (SELECT r.institution_id, r.college_id, r.received_on AS on_date, to_char(date_trunc('month', r.received_on), 'YYYY-MM') AS label, 'income' AS series, r.amount_paise / 100.0 AS value FROM income_records r UNION ALL SELECT x.institution_id, x.college_id, x.spent_on, to_char(date_trunc('month', x.spent_on), 'YYYY-MM'), 'expense', x.amount_paise / 100.0 FROM expense_records x WHERE x.status NOT IN ('rejected', 'cancelled')) t WHERE {where} AND t.on_date >= :_from GROUP BY 1, 2 ORDER BY 1",
    cols={"institution": "t.institution_id", "college": "t.college_id"},
    period="fy",
    dims=("college", "period"),
    route="/admin/accounting/dashboard",
)
sql_chart(
    "accounting.budget_utilisation",
    module="accounting",
    permission=V("accounting"),
    title="Budget utilisation by department (₹)",
    kind="stacked",
    sql="SELECT b.department_id AS label, SUM(b.utilised_paise) / 100.0 AS utilised, SUM(b.committed_paise) / 100.0 AS committed, SUM(GREATEST(b.allocated_paise - b.utilised_paise - b.committed_paise, 0)) / 100.0 AS available FROM budget_heads b WHERE {where} AND b.academic_year_id IN (SELECT id FROM academic_years WHERE institution_id = :_inst AND is_current) GROUP BY 1 ORDER BY 2 DESC",
    cols={"institution": "b.institution_id", "college": "b.college_id", "department": "b.department_id"},
    label_kind="department",
    dims=("college", "department"),
)
sql_chart(
    "accounting.expense_by_department",
    module="accounting",
    permission=V("accounting"),
    title="Expense by department (₹)",
    kind="bar",
    sql="SELECT x.department_id AS label, SUM(x.amount_paise) / 100.0 AS value FROM expense_records x WHERE {where} AND x.spent_on >= :_from AND x.status NOT IN ('rejected', 'cancelled') GROUP BY 1 ORDER BY 2 DESC",
    cols={"institution": "x.institution_id", "college": "x.college_id", "department": "x.department_id"},
    label_kind="department",
    period="fy",
    dims=("college", "department", "period"),
)
sql_chart(
    "comms.delivery_by_channel",
    module="communication",
    permission=VA("communication"),
    title="Message delivery by channel",
    kind="stacked",
    sql="SELECT m.channel AS label, m.status AS series, COUNT(*) AS value FROM message_logs m WHERE {where} AND m.created_at >= :_from GROUP BY 1, 2 ORDER BY 1",
    cols={"institution": "m.institution_id"},
    period="last_30d",
    dims=("period",),
)
sql_chart(
    "events.by_type",
    module="events",
    permission=V("events"),
    title="Events by type",
    kind="bar",
    sql="SELECT e.event_type AS label, COUNT(*) AS value FROM events e WHERE {where} AND e.deleted_at IS NULL AND e.from_on >= :_from GROUP BY 1 ORDER BY 2 DESC",
    cols={
        "institution": "e.institution_id",
        "college": "e.college_id",
        "department": "e.organiser_department_id",
        "staff": "e.organiser_staff_id",
    },
    period="this_year",
    dims=("college", "department", "period"),
)
sql_chart(
    "events.upcoming",
    module="events",
    permission=V("events"),
    title="Upcoming events (30 days)",
    kind="number",
    sql="SELECT 'upcoming' AS label, COUNT(*) AS value FROM events e WHERE {where} AND e.deleted_at IS NULL AND e.from_on BETWEEN CURRENT_DATE AND CURRENT_DATE + 30 AND e.status IN ('approved', 'scheduled')",
    cols={
        "institution": "e.institution_id",
        "college": "e.college_id",
        "department": "e.organiser_department_id",
        "staff": "e.organiser_staff_id",
    },
    dims=("college", "department"),
)

# ---- service desk (mv_service_desk_sla) / mentoring / grievances / surveys ----------------------------------------------
_SD: dict[str, Any] = {
    "module": "facilities",
    "permission": V("facilities"),
    "view": "mv_service_desk_sla",
    "route": "/admin/facilities/service-desk",
    "dims": ("college",),
}
view_chart(
    "service_desk.sla",
    title="Service desk SLA by category",
    kind="stacked",
    label="x.category",
    measures=(("within", "SUM(x.open - x.breached)"), ("breached", "SUM(x.breached)")),
    **_SD,
)
view_chart(
    "service_desk.mttr_by_category",
    title="Mean time to resolve (hours)",
    label="x.category",
    measures=(("value", "ROUND(AVG(x.mttr_hours), 1)"),),
    **_SD,
)
view_chart(
    "service_desk.open",
    title="Open tickets",
    kind="number",
    label="'total'",
    measures=(("value", "SUM(x.open)"),),
    **_SD,
)
view_chart(
    "service_desk.sla_pct",
    title="Resolved within SLA %",
    kind="gauge",
    label="'service_sla_pct'",
    measures=(("value", "ROUND(100.0 * SUM(x.within_sla) / NULLIF(SUM(x.resolved), 0), 2)"),),
    **_SD,
)
sql_chart(
    "mentoring.coverage",
    module="mentoring",
    permission=V("mentoring"),
    title="Mentor coverage by department",
    kind="stacked",
    sql="SELECT e.department_id AS label, COUNT(*) FILTER (WHERE ma.id IS NOT NULL) AS with_mentor, COUNT(*) FILTER (WHERE ma.id IS NULL) AS without_mentor FROM student_program_enrollments e LEFT JOIN mentor_assignments ma ON ma.student_program_enrollment_id = e.id AND ma.status = 'active' WHERE {where} AND e.status = 'active' AND e.deleted_at IS NULL GROUP BY 1 ORDER BY 3 DESC",
    cols={
        "institution": "e.institution_id",
        "college": "e.college_id",
        "department": "e.department_id",
        "program": "e.program_id",
        "batch": "e.batch_id",
        "enrollment": "e.id",
    },
    label_kind="department",
    dims=("college", "department", "program", "batch"),
    route="/admin/mentoring",
)
sql_chart(
    "mentoring.sessions_trend",
    module="mentoring",
    permission=V("mentoring"),
    title="Mentoring sessions by month",
    kind="line",
    sql="SELECT to_char(date_trunc('month', s.held_on), 'YYYY-MM') AS label, COUNT(*) AS value FROM mentoring_sessions s JOIN mentor_assignments ma ON ma.id = s.mentor_assignment_id JOIN student_program_enrollments e ON e.id = ma.student_program_enrollment_id WHERE {where} AND s.held_on >= :_from GROUP BY 1 ORDER BY 1",
    cols={
        "institution": "s.institution_id",
        "college": "e.college_id",
        "department": "e.department_id",
        "enrollment": "ma.student_program_enrollment_id",
        "staff": "ma.mentor_staff_id",
    },
    period="last_12m",
)
_GV: dict[str, Any] = {
    "institution": "g.institution_id",
    "college": "g.college_id",
    "enrollment": "g.student_program_enrollment_id",
}
sql_chart(
    "grievances.by_category_sla",
    module="grievances",
    permission=VA("grievances"),
    title="Grievances by category (SLA)",
    kind="stacked",
    sql="SELECT g.category AS label, COUNT(*) FILTER (WHERE g.status NOT IN ('resolved', 'closed') AND (g.sla_due_at IS NULL OR g.sla_due_at >= NOW())) AS within_sla, COUNT(*) FILTER (WHERE g.status NOT IN ('resolved', 'closed') AND g.sla_due_at < NOW()) AS breached, COUNT(*) FILTER (WHERE g.status IN ('resolved', 'closed')) AS resolved FROM grievances g WHERE {where} AND g.created_at >= :_from GROUP BY 1 ORDER BY 3 DESC",
    cols=_GV,
    period="this_year",
    dims=INST,
    route="/admin/grievances",
)
sql_chart(
    "grievances.by_status",
    module="grievances",
    permission=VA("grievances"),
    title="Grievances by status",
    kind="donut",
    sql="SELECT g.status AS label, COUNT(*) AS value FROM grievances g WHERE {where} AND g.created_at >= :_from GROUP BY 1",
    cols=_GV,
    period="this_year",
    dims=INST,
)
sql_chart(
    "grievances.open",
    module="grievances",
    permission=VA("grievances"),
    title="Open grievances",
    kind="number",
    sql="SELECT 'open' AS label, COUNT(*) AS value FROM grievances g WHERE {where} AND g.status NOT IN ('resolved', 'closed')",
    cols=_GV,
    dims=("college",),
)
sql_chart(
    "surveys.completion",
    module="surveys",
    permission=V("surveys"),
    title="Survey responses",
    kind="bar",
    sql="SELECT f.title AS label, COUNT(r.id) AS value FROM feedback_surveys f LEFT JOIN feedback_responses r ON r.survey_id = f.id WHERE {where} AND f.status IN ('open', 'closed', 'analysed') AND COALESCE(f.opens_at, f.created_at) >= :_from GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
    cols={"institution": "f.institution_id", "college": "f.college_id", "term": "f.term_id"},
    period="this_year",
    dims=("college", "term", "period"),
)

# ---- placement (mv_placement_funnel) / alumni -----------------------------------------------------------------------------------
_P: dict[str, Any] = {
    "module": "placement",
    "permission": V("placement"),
    "view": "mv_placement_funnel",
    "route": "/admin/placement/drives",
    "dims": ("college", "department", "batch"),
    "drill_rows": "placement",
}
view_chart(
    "placement.funnel",
    title="Placement funnel",
    kind="funnel",
    label="'funnel'",
    measures=(
        ("eligible", "SUM(x.eligible)"),
        ("applied", "SUM(x.applied)"),
        ("in_rounds", "SUM(x.in_rounds)"),
        ("offers", "SUM(x.offers)"),
        ("accepted", "SUM(x.accepted)"),
    ),
    order="1",
    **_P,
)
view_chart(
    "placement.ctc_bands",
    title="Offers by CTC band",
    kind="stacked",
    label="'ctc'",
    measures=(
        ("lt5l", "SUM(x.ctc_lt5l)"),
        ("l5_10", "SUM(x.ctc_5_10l)"),
        ("l10_20", "SUM(x.ctc_10_20l)"),
        ("l20_plus", "SUM(x.ctc_20l_plus)"),
    ),
    order="1",
    **_P,
)
view_chart(
    "placement.offers_by_department",
    title="Offers by department",
    label="x.department_id",
    measures=(("value", "SUM(x.offers)"),),
    label_kind="department",
    **_P,
)
view_chart(
    "placement.placement_pct",
    title="Placement %",
    kind="gauge",
    label="'placement_pct'",
    measures=(("value", "ROUND(100.0 * SUM(x.accepted) / NULLIF(SUM(x.eligible), 0), 2)"),),
    **_P,
)
view_chart(
    "placement.drives_by_status",
    title="Drives by status",
    kind="donut",
    label="x.drive_status",
    measures=(("value", "COUNT(DISTINCT x.drive_id)"),),
    **_P,
)
view_chart(
    "placement.offers",
    title="Offers (all drives)",
    kind="number",
    label="'total'",
    measures=(("value", "SUM(x.offers)"),),
    **_P,
)
view_chart(
    "placement.top_drives",
    title="Top drives by offers",
    kind="table",
    label="x.drive_id",
    measures=(
        ("value", "SUM(x.offers)"),
        ("applied", "SUM(x.applied)"),
        ("max_ctc_lpa", "ROUND(MAX(x.max_ctc_paise) / 10000000.0, 2)"),
    ),
    label_kind="drive",
    limit=15,
    **_P,
)
sql_chart(
    "placement.internships_by_status",
    module="placement",
    permission=V("placement"),
    title="Internships by status",
    kind="pie",
    sql="SELECT i.status AS label, COUNT(*) AS value FROM internships i JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id WHERE {where} GROUP BY 1",
    cols={
        "institution": "i.institution_id",
        "college": "e.college_id",
        "department": "e.department_id",
        "batch": "e.batch_id",
        "enrollment": "i.student_program_enrollment_id",
    },
    dims=("college", "department", "batch"),
)
sql_chart(
    "alumni.engagement",
    module="alumni",
    permission=V("alumni"),
    title="Alumni engagement by graduation year",
    kind="stacked",
    sql="SELECT a.graduation_year::text AS label, COUNT(*) FILTER (WHERE a.is_verified) AS verified, COUNT(*) FILTER (WHERE a.willing_to_mentor) AS mentors, COUNT(*) FILTER (WHERE a.willing_to_recruit) AS recruiters FROM alumni_profiles a WHERE {where} AND a.graduation_year IS NOT NULL GROUP BY 1 ORDER BY 1 DESC LIMIT 15",
    cols={"institution": "a.institution_id", "program": "a.program_id"},
    dims=("program",),
)
sql_chart(
    "alumni.verified_pct",
    module="alumni",
    permission=V("alumni"),
    title="Alumni verified %",
    kind="gauge",
    sql="SELECT 'verified' AS label, ROUND(100.0 * COUNT(*) FILTER (WHERE a.is_verified) / NULLIF(COUNT(*), 0), 2) AS value FROM alumni_profiles a WHERE {where}",
    cols={"institution": "a.institution_id", "program": "a.program_id"},
    dims=("program",),
)
sql_chart(
    "alumni.donations_trend",
    module="fundraising",
    permission=V("fundraising") + V("alumni"),
    title="Donations (₹) by month",
    kind="bar",
    sql="SELECT to_char(date_trunc('month', d.on_date), 'YYYY-MM') AS label, SUM(d.amount_paise) / 100.0 AS value FROM donations d WHERE {where} AND d.on_date >= :_from GROUP BY 1 ORDER BY 1",
    cols={"institution": "d.institution_id"},
    period="fy",
    dims=("period",),
)

# ---- research / PhD (mv_research_counts) ------------------------------------------------------------------------------------
_RS: dict[str, Any] = {
    "module": "research",
    "permission": V("research"),
    "view": "mv_research_counts",
    "route": "/admin/research/publications",
    "dims": ("college", "department"),
}
view_chart(
    "research.publications_trend",
    title="Publications by year",
    kind="line",
    label="x.year::text",
    measures=(("value", "SUM(x.count)"),),
    where="x.metric = 'publications' AND x.year >= EXTRACT(YEAR FROM CURRENT_DATE) - 5",
    order="1",
    **_RS,
)
view_chart(
    "research.publications_by_indexing",
    title="Publications by indexing",
    kind="pie",
    label="x.sub_key",
    measures=(("value", "SUM(x.count)"),),
    where="x.metric = 'publications'",
    **_RS,
)
view_chart(
    "research.grants_amount",
    title="Grants sanctioned (₹ lakh) by year",
    kind="bar",
    label="x.year::text",
    measures=(("value", "ROUND(SUM(x.amount_paise) / 10000000.0, 2)"),),
    where="x.metric = 'projects' AND x.year >= EXTRACT(YEAR FROM CURRENT_DATE) - 5",
    order="1",
    **_RS,
)
view_chart(
    "research.projects_by_status",
    title="Projects by status",
    kind="donut",
    label="x.sub_key",
    measures=(("value", "SUM(x.count)"),),
    where="x.metric = 'projects'",
    **_RS,
)
view_chart(
    "research.publications_by_department",
    title="Publications by department",
    label="x.department_id",
    measures=(("value", "SUM(x.count)"),),
    where="x.metric = 'publications'",
    label_kind="department",
    **_RS,
)
view_chart(
    "phd.scholars_by_status",
    module="phd",
    permission=V("phd") + V("research"),
    title="PhD scholars by status",
    kind="bar",
    view="mv_research_counts",
    label="x.sub_key",
    measures=(("value", "SUM(x.count)"),),
    where="x.metric = 'scholars'",
    dims=("college", "department"),
    route="/admin/phd/scholars",
)
sql_chart(
    "phd.thesis_by_stage",
    module="phd",
    permission=V("phd"),
    title="Thesis submissions by stage",
    kind="bar",
    sql="SELECT t.stage AS label, COUNT(*) AS value FROM thesis_submissions t JOIN research_scholars rs ON rs.id = t.scholar_id JOIN student_program_enrollments e ON e.id = rs.student_program_enrollment_id WHERE {where} GROUP BY 1",
    cols={
        "institution": "t.institution_id",
        "college": "e.college_id",
        "department": "e.department_id",
        "enrollment": "rs.student_program_enrollment_id",
        "staff": "rs.guide_staff_id",
    },
    dims=("college", "department"),
)

# ---- accreditation (Phase 32 metric_values) / governance (Phase 33) / affiliation (Phase 34) -------------------------
_MV: dict[str, Any] = {"institution": "m.institution_id", "college": "m.college_id", "program": "m.program_id"}
sql_chart(
    "accreditation.metric_trend",
    module="accreditation",
    permission=V("accreditation"),
    title="Metric trend (Phase 32 metric values)",
    kind="line",
    sql="SELECT m.period_label AS label, ROUND(AVG(m.value), 4) AS value FROM metric_values m WHERE {where} AND m.metric_key = :p_metric_key GROUP BY 1 ORDER BY 1",
    cols=_MV,
    params_schema={
        "type": "object",
        "required": ["metric_key"],
        "properties": {"metric_key": {"type": "string", "minLength": 2, "default": "faculty.fsr"}},
    },
    dims=("college", "program"),
    route="/iqac/metrics",
    ttl=900,
)
sql_chart(
    "accreditation.metrics_verified",
    module="accreditation",
    permission=V("accreditation"),
    title="Metric values verified",
    kind="donut",
    sql="SELECT CASE WHEN m.verified_at IS NOT NULL THEN 'verified' ELSE 'unverified' END AS label, COUNT(*) AS value FROM metric_values m WHERE {where} AND m.period_label = (SELECT MAX(period_label) FROM metric_values WHERE institution_id = :_inst) GROUP BY 1",
    cols=_MV,
    dims=("college",),
    ttl=900,
)
sql_chart(
    "accreditation.criteria_completion",
    module="accreditation",
    permission=V("accreditation"),
    title="Criterion responses by status",
    kind="stacked",
    sql="SELECT c.name AS label, r.status AS series, COUNT(*) AS value FROM criterion_responses r JOIN accreditation_cycles c ON c.id = r.cycle_id WHERE {where} AND c.status NOT IN ('closed', 'archived') GROUP BY 1, 2 ORDER BY 1",
    cols={
        "institution": "r.institution_id",
        "college": "c.college_id",
        "program": "c.program_id",
        "staff": "r.owner_staff_id",
    },
    dims=("college",),
    route="/iqac/cycles",
)
sql_chart(
    "governance.meetings_pending_atr",
    module="governance",
    permission=V("governance"),
    title="Resolutions pending action (ATR)",
    kind="bar",
    sql="SELECT m.committee_id AS label, COUNT(*) AS value FROM resolutions r JOIN meetings m ON m.id = r.meeting_id JOIN committees c ON c.id = m.committee_id WHERE {where} AND r.status = 'passed' AND r.action_owner_staff_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
    cols={"institution": "r.institution_id", "college": "c.college_id", "staff": "r.action_owner_staff_id"},
    label_kind="committee",
    dims=("college",),
    route="/admin/governance/meetings",
)
sql_chart(
    "governance.meetings_by_status",
    module="governance",
    permission=V("governance"),
    title="Meetings by status (this year)",
    kind="pie",
    sql="SELECT m.status AS label, COUNT(*) AS value FROM meetings m JOIN committees c ON c.id = m.committee_id WHERE {where} AND m.held_on >= :_from GROUP BY 1",
    cols={"institution": "m.institution_id", "college": "c.college_id"},
    period="this_year",
    dims=("college", "period"),
)
sql_chart(
    "governance.rti_by_status",
    module="rti",
    permission=V("rti") + VA("governance"),
    title="RTI requests by status",
    kind="pie",
    sql="SELECT r.status AS label, COUNT(*) AS value FROM rti_requests r WHERE {where} AND r.received_on >= :_from GROUP BY 1",
    cols={"institution": "r.institution_id", "staff": "r.pio_staff_id"},
    period="this_year",
    dims=("period",),
)
sql_chart(
    "governance.efiles_by_status",
    module="efile",
    permission=V("efile"),
    title="e-Files by status",
    kind="pie",
    sql="SELECT f.status AS label, COUNT(*) AS value FROM efiles f WHERE {where} GROUP BY 1",
    cols={"institution": "f.institution_id"},
    dims=(),
)
_AF: dict[str, Any] = {"institution": "s.institution_id", "college": "s.college_id", "term": "s.term_id"}
sql_chart(
    "affiliation.college_compliance",
    module="affiliation",
    permission=V("affiliation"),
    feature="affiliation.data_submissions",
    title="Data-submission compliance by college (%)",
    sql="SELECT s.college_id AS label, ROUND(100.0 * COUNT(*) FILTER (WHERE s.status IN ('accepted', 'locked')) / NULLIF(COUNT(*), 0), 2) AS value FROM college_data_submissions s WHERE {where} AND s.term_id IN (SELECT id FROM academic_terms WHERE institution_id = :_inst AND is_current) GROUP BY 1 ORDER BY 2 ASC LIMIT 100",
    cols=_AF,
    label_kind="college",
    dims=("college", "term"),
    route="/university/affiliation/submissions",
)
sql_chart(
    "affiliation.applications_by_status",
    module="affiliation",
    permission=V("affiliation"),
    feature="affiliation.core",
    title="Affiliation applications by status",
    kind="bar",
    sql="SELECT a.status AS label, COUNT(*) AS value FROM affiliation_applications a WHERE {where} AND a.academic_year_id IN (SELECT id FROM academic_years WHERE institution_id = :_inst AND is_current) GROUP BY 1",
    cols={"institution": "a.institution_id", "college": "a.college_id"},
    dims=("college",),
    route="/university/affiliation/applications",
)
sql_chart(
    "affiliation.colleges_by_type",
    module="affiliation",
    permission=V("affiliation"),
    feature="affiliation.core",
    title="Colleges by type",
    kind="donut",
    sql="SELECT c.college_type AS label, COUNT(*) AS value FROM colleges c WHERE {where} AND c.deleted_at IS NULL GROUP BY 1",
    cols={"institution": "c.institution_id", "college": "c.id"},
    dims=(),
)

# ---- early warning (mv_risk_cohort — Phase 27 risk_flags) ------------------------------------------------------------
_RK: dict[str, Any] = {
    "module": "mentoring",
    "permission": VA("mentoring") + ("mentoring:manage",),
    "view": "mv_risk_cohort",
    "feature": EW,
    "current_term": True,
    "route": "/admin/risk/analytics",
    "drill_rows": "risk",
}
view_chart(
    "risk.cohort_by_department",
    title="Risk cohort by department",
    kind="heatmap",
    label="x.department_id",
    series="x.level",
    measures=(("value", "SUM(x.students)"),),
    label_kind="department",
    order="1",
    **_RK,
)
view_chart(
    "risk.level_distribution",
    title="Risk levels",
    kind="donut",
    label="x.level",
    measures=(("value", "SUM(x.students)"),),
    **_RK,
)
view_chart(
    "risk.factor_means",
    title="Risk factor means (high risk)",
    label="'factors'",
    measures=(
        ("attendance", "ROUND(AVG(x.attendance_mean), 3)"),
        ("cia", "ROUND(AVG(x.cia_mean), 3)"),
        ("dues", "ROUND(AVG(x.dues_mean), 3)"),
        ("standing", "ROUND(AVG(x.standing_mean), 3)"),
        ("hostel", "ROUND(AVG(x.hostel_mean), 3)"),
        ("engagement", "ROUND(AVG(x.engagement_mean), 3)"),
    ),
    where="x.level = 'high'",
    order="1",
    **_RK,
)
view_chart(
    "risk.trend",
    title="High-risk students by term",
    kind="line",
    label="x.term_id",
    series="x.level",
    measures=(("value", "SUM(x.students)"),),
    label_kind="term",
    order="1",
    **{**_RK, "current_term": False},
)
view_chart(
    "risk.high_count",
    title="High-risk students",
    kind="number",
    label="'total'",
    measures=(("value", "SUM(x.students)"),),
    where="x.level = 'high'",
    **_RK,
)
view_chart(
    "risk.acknowledged_pct",
    title="High risk acknowledged %",
    kind="gauge",
    label="'acknowledged'",
    measures=(("value", "ROUND(100.0 * SUM(x.acknowledged) / NULLIF(SUM(x.students), 0), 2)"),),
    where="x.level = 'high'",
    **_RK,
)
