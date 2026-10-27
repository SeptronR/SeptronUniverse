"""Role dashboard compositions, stat / list / action keys — Prompts/35 §35.6 dashboard_service step 2.

Stats resolve to ``mv_kpi_daily`` columns at institution / college scope and to a number / gauge chart (``scoped_chart``)
under department / own / self scope, so the same card shows department numbers to an HOD and own numbers to faculty.
Lists reuse the owning modules' services (approvals inbox → ``WorkflowService.inbox``; today's classes →
``SessionService.today_sessions``) or a fixed-filter query under the module's scope; actions are routes behind a
permission. Student / parent dashboards only carry own numbers with the class average as the comparison.
"""

from typing import Any

from sqlalchemy import text

from app.core.dashboards import (
    ActionDef,
    ListDef,
    StatDef,
    WidgetSpec,
    register_action,
    register_dashboard,
    register_list,
    register_stat,
)


def _v(m: str) -> tuple[str, ...]:
    return (f"{m}:view_all", f"{m}:manage", f"{m}:view")


def _va(m: str) -> tuple[str, ...]:
    return (f"{m}:view_all", f"{m}:manage")


# ---- stats --------------------------------------------------------------------------------------------------------------
for _s in (
    StatDef(
        "students_active",
        "Active students",
        "students_active",
        "students",
        _v("students"),
        scoped_chart="students.active_count",
        route="/admin/students",
        public=True,
    ),
    StatDef(
        "programmes",
        "Programmes",
        "programmes",
        "programs",
        _v("programs") + _v("students"),
        route="/admin/academics/programs",
        public=True,
    ),
    StatDef(
        "faculty_count", "Faculty", "faculty_count", "hr", _v("hr") + _v("faculty"), route="/admin/hr/staff", public=True
    ),
    StatDef("staff_active", "Staff", "staff_active", "hr", _v("hr"), scoped_chart="hr.headcount", route="/admin/hr/staff"),
    StatDef(
        "staff_present_today",
        "Staff present today",
        "staff_present_today",
        "hr",
        _v("hr"),
        scoped_chart="hr.present_today",
        route="/admin/hr/attendance",
    ),
    StatDef(
        "leaves_pending",
        "Leaves pending",
        "leaves_pending",
        "leaves",
        _va("leaves") + _va("hr"),
        direction="lower",
        route="/admin/hr/leaves",
    ),
    StatDef(
        "attendance_avg_pct",
        "Attendance %",
        "attendance_avg_pct",
        "attendance",
        _v("attendance") + ("attendance:self",),
        fmt="pct",
        target_key="attendance_pct",
        scoped_chart="attendance.avg_pct",
        route="/admin/attendance",
    ),
    StatDef(
        "attendance_shortfall",
        "Below attendance threshold",
        "attendance_shortfall",
        "attendance",
        _v("attendance"),
        direction="lower",
        route="/admin/attendance",
    ),
    StatDef(
        "fee_collection_pct",
        "Fee collection %",
        "fee_collection_pct",
        "fees",
        _va("fees"),
        fmt="pct",
        target_key="fee_collection_pct",
        scoped_chart="fees.collection_pct",
        route="/admin/fees/invoices",
    ),
    StatDef(
        "fee_collected_today",
        "Collected today",
        "fee_collected_today_paise",
        "fees",
        _va("fees"),
        fmt="inr",
        scoped_chart="fees.collected_today",
        route="/admin/fees/payments",
    ),
    StatDef(
        "fee_overdue",
        "Overdue dues",
        "fee_overdue_paise",
        "fees",
        _va("fees") + ("fees:self",),
        fmt="inr",
        direction="lower",
        scoped_chart="fees.overdue_total",
        route="/admin/fees/invoices",
    ),
    StatDef(
        "my_dues",
        "My dues",
        None,
        "fees",
        ("fees:self",) + _v("fees"),
        fmt="decimal",
        direction="lower",
        scoped_chart="fees.my_dues",
        route="/student/fees",
    ),
    StatDef(
        "fee_defaulters",
        "Defaulters",
        "fee_defaulters",
        "fees",
        _va("fees"),
        direction="lower",
        route="/admin/fees/invoices",
    ),
    StatDef(
        "exam_sessions_active",
        "Active exam sessions",
        "exam_sessions_active",
        "exams",
        _v("exams"),
        scoped_chart="exams.active_sessions",
        route="/admin/exams/sessions",
    ),
    StatDef("valuation_pct", "Valuation %", "valuation_pct", "exams", _v("exams"), fmt="pct", route="/admin/exams/sessions"),
    StatDef(
        "result_pass_pct",
        "Result pass %",
        "result_pass_pct",
        "results",
        _v("results"),
        fmt="pct",
        target_key="result_pass_pct",
        scoped_chart="results.pass_pct",
        route="/admin/results/analysis",
    ),
    StatDef("avg_sgpa", "Average SGPA", "avg_sgpa", "results", _v("results"), fmt="decimal", route="/admin/results/analysis"),
    StatDef(
        "applications",
        "Applications (open cycles)",
        "applications",
        "admissions",
        _v("admissions"),
        route="/admin/admissions/applicants",
    ),
    StatDef(
        "admitted",
        "Admitted",
        "admitted",
        "admissions",
        _v("admissions"),
        scoped_chart="admissions.admitted",
        route="/admin/admissions/applicants",
    ),
    StatDef(
        "enquiries_open",
        "Open enquiries",
        "enquiries_open",
        "admissions",
        _v("admissions"),
        route="/admin/admissions/enquiries",
    ),
    StatDef(
        "placement_offers",
        "Placement offers",
        "placement_offers",
        "placement",
        _v("placement"),
        scoped_chart="placement.offers",
        route="/admin/placement/drives",
        public=True,
    ),
    StatDef(
        "placement_pct",
        "Placement %",
        "placement_pct",
        "placement",
        _v("placement"),
        fmt="pct",
        target_key="placement_pct",
        scoped_chart="placement.placement_pct",
        route="/admin/placement/drives",
    ),
    StatDef(
        "hostel_occupied",
        "Hostel beds occupied",
        "hostel_occupied",
        "hostel",
        _v("hostel"),
        route="/admin/hostel/allocations",
    ),
    StatDef("hostel_out_today", "Out on leave", "hostel_out_today", "hostel", _v("hostel"), route="/admin/hostel/leaves"),
    StatDef(
        "hostel_complaints_open",
        "Hostel complaints open",
        "hostel_complaints_open",
        "hostel",
        _v("hostel"),
        direction="lower",
        route="/admin/hostel/complaints",
    ),
    StatDef(
        "library_issued", "Books on loan", "library_issued", "library", _v("library"), route="/admin/library/circulation"
    ),
    StatDef(
        "library_overdue",
        "Overdue books",
        "library_overdue",
        "library",
        _v("library"),
        direction="lower",
        scoped_chart="library.overdues",
        route="/admin/library/circulation",
    ),
    StatDef(
        "grievances_open",
        "Open grievances",
        "grievances_open",
        "grievances",
        _va("grievances"),
        direction="lower",
        scoped_chart="grievances.open",
        route="/admin/grievances",
    ),
    StatDef(
        "grievance_sla_pct",
        "Grievance SLA %",
        "grievance_sla_pct",
        "grievances",
        _va("grievances"),
        fmt="pct",
        target_key="grievance_sla_pct",
        route="/admin/grievances",
    ),
    StatDef(
        "service_open",
        "Open service tickets",
        "service_open",
        "facilities",
        _v("facilities"),
        direction="lower",
        scoped_chart="service_desk.open",
        route="/admin/facilities/service-desk",
    ),
    StatDef(
        "service_breached",
        "Tickets past SLA",
        "service_breached",
        "facilities",
        _v("facilities"),
        direction="lower",
        route="/admin/facilities/service-desk",
    ),
    StatDef(
        "risk_high",
        "High-risk students",
        "risk_high",
        "mentoring",
        _va("mentoring") + ("mentoring:manage",),
        direction="lower",
        scoped_chart="risk.high_count",
        feature="analytics.early_warning",
        route="/admin/risk/analytics",
    ),
    StatDef(
        "publications_year",
        "Publications (this year)",
        "publications_year",
        "research",
        _v("research"),
        route="/admin/research/publications",
    ),
    StatDef(
        "projects_active",
        "Active research projects",
        "projects_active",
        "research",
        _v("research"),
        route="/admin/research/projects",
    ),
    StatDef(
        "scholars_active", "PhD scholars", "scholars_active", "phd", _v("phd") + _v("research"), route="/admin/phd/scholars"
    ),
    StatDef(
        "holds_active",
        "Students on hold",
        "holds_active",
        "students",
        _v("students"),
        direction="lower",
        route="/admin/students",
    ),
):
    register_stat(_s)


# ---- lists --------------------------------------------------------------------------------------------------------------
async def _approvals(svc: Any, limit: int = 8) -> list[dict[str, Any]]:
    from app.services.workflow_service import WorkflowService

    rows = await WorkflowService(svc.db, svc.principal, svc.request).inbox()
    return [
        {
            "id": str(r.step_id),
            "title": r.entity_summary or r.instance.title,
            "route": r.route or "/approvals",
            "meta": r.via,
        }
        for r in rows[:limit]
    ]


async def _today_classes(svc: Any, limit: int = 10) -> list[dict[str, Any]]:
    from app.services.timetable.session_service import SessionService

    rows = await SessionService(svc.db, svc.principal, svc.request).today_sessions()
    return [
        {
            "id": str(r.id),
            "title": f"{r.course_code or ''} {r.course_title or ''}".strip(),
            "meta": f"{r.start_time:%H:%M}–{r.end_time:%H:%M}",
            "route": "/timetable",
        }
        for r in rows[:limit]
    ]


async def _sql_list(
    svc: Any, module: str, sql: str, cols: dict[str, str | None], route: str, limit: int = 8
) -> list[dict[str, Any]]:
    from app.core.charts import ChartContext

    scope = await svc.resolve_scope(module)
    ctx = ChartContext(db=svc.db, institution_id=svc.inst, scope=scope, service=svc)
    full: dict[str, str | None] = {
        "institution": None,
        "college": None,
        "department": None,
        "program": None,
        "batch": None,
        "term": None,
    }
    full.update(cols)
    pred, binds = ctx.where(alias="", **full)  # type: ignore[arg-type]
    rows = (await svc.db.execute(text(sql.format(where=pred) + f" LIMIT {int(limit)}"), binds)).mappings().all()
    return [
        {"id": str(r["id"]), "title": str(r["title"]), "meta": str(r.get("meta") or ""), "route": route} for r in rows
    ]


async def _receipts_today(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "fees",
        "SELECT p.id, p.receipt_number AS title, (p.amount_paise / 100.0)::text || ' · ' || p.payment_mode AS meta "
        "FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id WHERE {where} AND p.status IN ('success', 'reconciled') "
        "AND p.payment_date::date = CURRENT_DATE ORDER BY p.created_at DESC",
        {"institution": "p.institution_id", "college": "i.college_id", "enrollment": "i.student_program_enrollment_id"},
        "/admin/fees/payments",
    )


async def _discrepancies(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "exams",
        "SELECT x.exam_session_id AS id, x.name AS title, x.discrepancies::text || ' discrepancies' AS meta "
        "FROM mv_exam_progress x WHERE {where} AND x.discrepancies > 0 ORDER BY x.discrepancies DESC",
        {"institution": "x.institution_id", "college": "x.college_id", "term": "x.term_id"},
        "/admin/exams/sessions",
    )


async def _shortfall(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "attendance",
        "SELECT x.enrollment_id AS id, s.registration_number AS title, ROUND(MIN(x.pct), 1)::text || '%' AS meta "
        "FROM mv_attendance_term x JOIN student_program_enrollments e ON e.id = x.enrollment_id JOIN students s ON s.id = e.student_id "
        "WHERE {where} AND x.is_short AND x.term_id IN (SELECT id FROM academic_terms WHERE institution_id = :_inst AND is_current) "
        "GROUP BY x.enrollment_id, s.registration_number ORDER BY MIN(x.pct)",
        {
            "institution": "x.institution_id",
            "college": "x.college_id",
            "department": "x.department_id",
            "enrollment": "x.enrollment_id",
            "offering": "x.offering_id",
        },
        "/admin/attendance",
    )


async def _risk_list(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "mentoring",
        "SELECT f.student_program_enrollment_id AS id, s.registration_number AS title, f.level || ' · ' || f.score::text AS meta "
        "FROM risk_flags f JOIN student_program_enrollments e ON e.id = f.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "WHERE {where} AND f.level = 'high' AND f.term_id IN (SELECT id FROM academic_terms WHERE institution_id = :_inst AND is_current) "
        "ORDER BY f.score DESC",
        {
            "institution": "f.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "enrollment": "f.student_program_enrollment_id",
        },
        "/admin/risk/analytics",
    )


async def _leaves_pending(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "leaves",
        "SELECT l.id, COALESCE(st.first_name, '') || ' ' || COALESCE(st.last_name, '') AS title, l.from_date::text || ' → ' || l.to_date::text AS meta "
        "FROM staff_leaves l JOIN staff st ON st.id = l.staff_id WHERE {where} AND l.status = 'pending' ORDER BY l.from_date",
        {
            "institution": "l.institution_id",
            "college": "st.college_id",
            "department": "st.department_id",
            "staff": "l.staff_id",
        },
        "/admin/hr/leaves",
    )


async def _holds(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "students",
        "SELECT h.id, s.registration_number AS title, h.hold_type AS meta FROM student_holds h "
        "JOIN student_program_enrollments e ON e.id = h.student_program_enrollment_id JOIN students s ON s.id = e.student_id "
        "WHERE {where} AND h.released_at IS NULL ORDER BY h.placed_at DESC",
        {
            "institution": "h.institution_id",
            "college": "e.college_id",
            "department": "e.department_id",
            "enrollment": "h.student_program_enrollment_id",
        },
        "/admin/students",
    )


async def _complaints(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "hostel",
        "SELECT c.id, c.category AS title, c.status AS meta FROM hostel_complaints c JOIN hostels h ON h.id = c.hostel_id "
        "WHERE {where} AND c.status NOT IN ('resolved', 'closed') ORDER BY c.created_at DESC",
        {
            "institution": "c.institution_id",
            "college": "h.college_id",
            "hostel": "c.hostel_id",
            "enrollment": "c.student_program_enrollment_id",
        },
        "/admin/hostel/complaints",
    )


async def _overdue_books(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "library",
        "SELECT b.id, m.member_code AS title, 'due ' || b.due_on::text AS meta FROM book_issues b JOIN library_members m ON m.id = b.member_id "
        "WHERE {where} AND b.returned_on IS NULL AND b.due_on < CURRENT_DATE ORDER BY b.due_on",
        {"institution": "b.institution_id"},
        "/admin/library/circulation",
    )


async def _tickets(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "facilities",
        "SELECT r.id, r.ticket_number AS title, r.category || ' · ' || r.status AS meta FROM service_requests r "
        "WHERE {where} AND r.status NOT IN ('resolved', 'closed') AND r.sla_due_at < NOW() ORDER BY r.sla_due_at",
        {"institution": "r.institution_id", "college": "r.college_id"},
        "/admin/facilities/service-desk",
    )


async def _my_holds(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "students",
        "SELECT h.id, h.hold_type AS title, h.reason AS meta FROM student_holds h WHERE {where} AND h.released_at IS NULL",
        {"institution": "h.institution_id", "enrollment": "h.student_program_enrollment_id"},
        "/student/profile",
    )


async def _upcoming_exams(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "exams",
        "SELECT s.id, s.name AS title, s.start_date::text AS meta FROM exam_sessions s WHERE {where} AND s.deleted_at IS NULL "
        "AND s.start_date >= CURRENT_DATE ORDER BY s.start_date",
        {"institution": "s.institution_id", "college": "s.college_id", "term": "s.term_id"},
        "/student/exams",
    )


async def _submissions_due(svc: Any) -> list[dict[str, Any]]:
    return await _sql_list(
        svc,
        "affiliation",
        "SELECT s.id, s.submission_type AS title, s.status AS meta FROM college_data_submissions s WHERE {where} "
        "AND s.status IN ('draft', 'returned', 'submitted') ORDER BY s.updated_at DESC",
        {"institution": "s.institution_id", "college": "s.college_id", "term": "s.term_id"},
        "/university/affiliation/submissions",
    )


for _l in (
    ListDef("approvals.inbox", "Approvals inbox", "workflow", ("dashboard:view",), "/approvals", _approvals),
    ListDef(
        "timetable.today",
        "Today's classes",
        "timetable",
        ("timetable:view", "timetable:view_all", "timetable:manage"),
        "/timetable",
        _today_classes,
    ),
    ListDef("fees.today_receipts", "Today's receipts", "fees", _va("fees"), "/admin/fees/payments", _receipts_today),
    ListDef(
        "exams.discrepancies_open", "Valuation discrepancies", "exams", _v("exams"), "/admin/exams/sessions", _discrepancies
    ),
    ListDef(
        "attendance.shortfall",
        "Attendance shortfall",
        "attendance",
        _v("attendance"),
        "/admin/attendance",
        _shortfall,
    ),
    ListDef(
        "risk.high",
        "High-risk students",
        "mentoring",
        _va("mentoring") + ("mentoring:manage",),
        "/admin/risk/analytics",
        _risk_list,
        "analytics.early_warning",
    ),
    ListDef(
        "leaves.pending",
        "Leaves awaiting approval",
        "leaves",
        _va("leaves") + ("leaves:approve",),
        "/admin/hr/leaves",
        _leaves_pending,
    ),
    ListDef("students.holds", "Students on hold", "students", _v("students"), "/admin/students", _holds),
    ListDef("hostel.complaints", "Open hostel complaints", "hostel", _v("hostel"), "/admin/hostel/complaints", _complaints),
    ListDef("library.overdues", "Overdue books", "library", _v("library"), "/admin/library/circulation", _overdue_books),
    ListDef(
        "service_desk.breached",
        "Tickets past SLA",
        "facilities",
        _v("facilities"),
        "/admin/facilities/service-desk",
        _tickets,
    ),
    ListDef("me.holds", "My holds", "students", ("students:self",) + _v("students"), "/student/profile", _my_holds),
    ListDef("exams.upcoming", "Upcoming exams", "exams", ("exams:self",) + _v("exams"), "/student/exams", _upcoming_exams),
    ListDef(
        "affiliation.submissions_due",
        "College data submissions",
        "affiliation",
        _v("affiliation") + ("affiliation:submit",),
        "/university/affiliation/submissions",
        _submissions_due,
        "affiliation.data_submissions",
    ),
):
    register_list(_l)

# ---- quick actions ------------------------------------------------------------------------------------------------------
for _a in (
    ActionDef(
        "announce", "Announce", "/announcements", ("communication:create", "communication:manage"), "megaphone"
    ),
    ActionDef("read_only", "Read-only mode", "/admin/settings", ("settings:manage",), "lock"),
    ActionDef("reports", "Reports", "/admin/analytics", ("reports:view", "reports:run", "reports:manage"), "file-text"),
    ActionDef("collect_fee", "Collect fee", "/admin/fees/collect", ("fees:collect", "fees:manage"), "indian-rupee"),
    ActionDef("mark_attendance", "Mark attendance", "/faculty/attendance", ("attendance:mark",), "check-square"),
    ActionDef("enter_marks", "Enter marks", "/faculty/offerings", ("marks:enter",), "pen-line"),
    ActionDef("apply_leave", "Apply leave", "/me", ("leaves:self", "leaves:create"), "calendar-plus"),
    ActionDef("pay_fees", "Pay fees", "/student/fees", ("fees:self",), "credit-card"),
    ActionDef("my_timetable", "Timetable", "/student/timetable", ("timetable:view",), "calendar"),
    ActionDef("my_results", "Results", "/student/results", ("results:self",), "award"),
    ActionDef("new_drive", "New drive", "/admin/placement/drives", ("placement:manage",), "briefcase"),
    ActionDef("issue_book", "Issue book", "/admin/library/circulation", ("library:circulate", "library:manage"), "book-open"),
    ActionDef(
        "log_intervention",
        "Log intervention",
        "/admin/risk/analytics",
        ("mentoring:manage",),
        "heart-handshake",
        "analytics.early_warning",
    ),
    ActionDef(
        "refresh_models",
        "Refresh analytics",
        "/admin/analytics/readmodels",
        ("analytics:manage",),
        "refresh-cw",
        "analytics.core",
    ),
    ActionDef("analytics", "Analytics", "/admin/analytics", ("analytics:view",), "bar-chart-3", "analytics.core"),
):
    register_action(_a)


def W(key: str, size: str = "md", **kw: Any) -> WidgetSpec:
    """``W("stat:students_active")`` / ``W("chart:fees.dues_aging", "lg")`` / ``W("list:approvals.inbox")``."""
    kind, _, ref = key.partition(":")
    field = {"stat": "stat_key", "chart": "chart_key", "list": "list_key", "action": "action_key"}[kind]
    return WidgetSpec(key=ref, size=size, **{field: ref}, **kw)  # type: ignore[arg-type]


_ADMIN = [
    W("stat:students_active", "sm"),
    W("stat:attendance_avg_pct", "sm"),
    W("stat:fee_collection_pct", "sm"),
    W("stat:result_pass_pct", "sm"),
    W("stat:staff_present_today", "sm"),
    W("stat:placement_offers", "sm"),
    W("stat:grievance_sla_pct", "sm"),
    W("stat:risk_high", "sm"),
    W("chart:students.enrolment_by_department", "lg"),
    W("chart:attendance.pct_by_department"),
    W("chart:fees.collection_by_mode_daily", "lg"),
    W("chart:exams.session_progress", "lg"),
    W("chart:results.pass_pct_by_program"),
    W("chart:admissions.funnel"),
    W("chart:placement.funnel"),
    W("chart:grievances.by_category_sla"),
    W("chart:risk.cohort_by_department", "lg"),
    W("chart:research.publications_trend"),
    W("list:approvals.inbox"),
    W("action:announce", "sm"),
    W("action:read_only", "sm"),
    W("action:reports", "sm"),
    W("action:analytics", "sm"),
]
for _role in ("institution_admin", "vice_chancellor", "super_admin"):
    register_dashboard(_role, _ADMIN)
register_dashboard(
    "college_admin", _ADMIN + [W("list:affiliation.submissions_due"), W("chart:fees.collection_by_college")]
)
register_dashboard(
    "registrar",
    [
        W("stat:students_active", "sm"),
        W("stat:applications", "sm"),
        W("stat:admitted", "sm"),
        W("stat:holds_active", "sm"),
        W("chart:admissions.funnel", "lg"),
        W("chart:registration.progress"),
        W("chart:registration.waitlists"),
        W("chart:students.enrolment_by_program", "lg"),
        W("chart:affiliation.college_compliance", "lg"),
        W("chart:affiliation.applications_by_status"),
        W("chart:risk.cohort_by_department"),
        W("list:students.holds"),
        W("list:approvals.inbox"),
        W("list:affiliation.submissions_due"),
        W("action:announce", "sm"),
        W("action:reports", "sm"),
        W("action:refresh_models", "sm"),
    ],
)
_COE = [
    W("stat:exam_sessions_active", "sm"),
    W("stat:valuation_pct", "sm"),
    W("stat:result_pass_pct", "sm"),
    W("chart:exams.session_progress", "xl"),
    W("chart:exams.hall_tickets_by_session", "lg"),
    W("chart:exams.valuation_pct"),
    W("chart:exams.reval_queue"),
    W("chart:exams.malpractice_by_category"),
    W("chart:results.pass_pct_by_program"),
    W("chart:results.sgpa_histogram"),
    W("list:exams.discrepancies_open"),
    W("list:approvals.inbox"),
    W("action:reports", "sm"),
]
for _role in ("controller_of_examinations", "exam_cell"):
    register_dashboard(_role, _COE)
_HOD = [
    W("stat:students_active", "sm"),
    W("stat:attendance_avg_pct", "sm"),
    W("stat:result_pass_pct", "sm"),
    W("stat:risk_high", "sm"),
    W("chart:attendance.pct_by_batch"),
    W("chart:attendance.pct_by_offering", "lg"),
    W("chart:marks.cia_status"),
    W("chart:results.pass_pct_by_batch"),
    W("chart:hr.attendance_today"),
    W("chart:hr.leaves_pending_by_department"),
    W("chart:risk.cohort_by_department", "lg"),
    W("chart:research.publications_by_department"),
    W("chart:governance.meetings_pending_atr"),
    W("list:risk.high"),
    W("list:leaves.pending"),
    W("list:approvals.inbox"),
    W("action:announce", "sm"),
    W("action:log_intervention", "sm"),
]
for _role in ("hod", "dean"):
    register_dashboard(_role, _HOD)
_FACULTY = [
    W("stat:attendance_avg_pct", "sm"),
    W("stat:risk_high", "sm"),
    W("list:timetable.today", "lg"),
    W("chart:attendance.pct_by_offering"),
    W("chart:marks.cia_avg_by_offering"),
    W("chart:lms.assignment_submission_rate"),
    W("list:attendance.shortfall"),
    W("list:risk.high"),
    W("list:approvals.inbox"),
    W("action:mark_attendance", "sm"),
    W("action:enter_marks", "sm"),
    W("action:apply_leave", "sm"),
]
for _role in ("faculty", "guest_faculty", "research_guide"):
    register_dashboard(_role, _FACULTY)
register_dashboard(
    "class_advisor",
    [
        W("stat:attendance_avg_pct", "sm"),
        W("stat:risk_high", "sm"),
        W("chart:registration.progress"),
        W("chart:attendance.pct_by_batch"),
        W("list:attendance.shortfall", "lg"),
        W("list:risk.high", "lg"),
        W("list:timetable.today"),
        W("action:mark_attendance", "sm"),
        W("action:log_intervention", "sm"),
    ],
)
_STUDENT = [
    W("stat:attendance_avg_pct", "sm"),
    W("stat:my_dues", "sm"),
    W("list:timetable.today", "lg"),
    W("chart:attendance.pct_by_offering", "lg", title="My attendance by course"),
    W("chart:results.my_sgpa_trend", "lg"),
    W("list:me.holds"),
    W("list:exams.upcoming"),
    W("action:pay_fees", "sm"),
    W("action:my_timetable", "sm"),
    W("action:my_results", "sm"),
]
register_dashboard("student", _STUDENT)
register_dashboard("parent", [w for w in _STUDENT if w.key not in ("timetable.today",)])
register_dashboard(
    "research_scholar", [W("list:timetable.today"), W("list:exams.upcoming"), W("action:my_results", "sm")]
)
register_dashboard(
    "accountant",
    [
        W("stat:fee_collected_today", "sm"),
        W("stat:fee_collection_pct", "sm"),
        W("stat:fee_overdue", "sm"),
        W("stat:fee_defaulters", "sm"),
        W("chart:fees.collection_by_mode_daily", "lg"),
        W("chart:fees.dues_aging"),
        W("chart:fees.day_book_status"),
        W("chart:fees.refunds_pending", "sm"),
        W("chart:accounting.budget_utilisation", "lg"),
        W("chart:accounting.income_vs_expense", "lg"),
        W("list:fees.today_receipts"),
        W("action:collect_fee", "sm"),
        W("action:reports", "sm"),
    ],
)
register_dashboard(
    "hr_officer",
    [
        W("stat:staff_active", "sm"),
        W("stat:staff_present_today", "sm"),
        W("stat:leaves_pending", "sm"),
        W("chart:hr.staff_by_cadre"),
        W("chart:hr.attendance_today", "lg"),
        W("chart:hr.leaves_trend"),
        W("chart:hr.vacancies"),
        W("list:leaves.pending"),
    ],
)
register_dashboard(
    "admissions_officer",
    [
        W("stat:applications", "sm"),
        W("stat:admitted", "sm"),
        W("stat:enquiries_open", "sm"),
        W("chart:admissions.funnel", "lg"),
        W("chart:admissions.seat_fill", "lg"),
        W("chart:admissions.allotments_by_status"),
        W("chart:admissions.enquiries_by_stage"),
        W("chart:admissions.funnel_by_category"),
    ],
)
register_dashboard(
    "placement_officer",
    [
        W("stat:placement_offers", "sm"),
        W("stat:placement_pct", "sm"),
        W("chart:placement.funnel", "lg"),
        W("chart:placement.ctc_bands"),
        W("chart:placement.offers_by_department"),
        W("chart:placement.top_drives", "lg"),
        W("chart:placement.internships_by_status"),
        W("action:new_drive", "sm"),
    ],
)
register_dashboard(
    "hostel_warden",
    [
        W("stat:hostel_occupied", "sm"),
        W("stat:hostel_out_today", "sm"),
        W("stat:hostel_complaints_open", "sm"),
        W("chart:hostel.occupancy", "lg"),
        W("chart:hostel.leaves_today"),
        W("chart:hostel.late_returns"),
        W("chart:hostel.mess_attendance"),
        W("list:hostel.complaints"),
        W("list:risk.high"),
    ],
)
register_dashboard(
    "librarian",
    [
        W("stat:library_issued", "sm"),
        W("stat:library_overdue", "sm"),
        W("chart:library.circulation_trend", "lg"),
        W("chart:library.issues_by_member_type"),
        W("chart:library.fines_trend"),
        W("list:library.overdues"),
        W("action:issue_book", "sm"),
    ],
)
register_dashboard(
    "transport_manager",
    [W("chart:transport.trips_today"), W("chart:transport.vehicle_alerts"), W("chart:transport.gps_health")],
)
register_dashboard(
    "estate_officer",
    [
        W("stat:service_open", "sm"),
        W("stat:service_breached", "sm"),
        W("chart:service_desk.sla", "lg"),
        W("chart:service_desk.mttr_by_category"),
        W("chart:service_desk.sla_pct", "sm"),
        W("chart:events.upcoming", "sm"),
        W("list:service_desk.breached"),
    ],
)
register_dashboard(
    "iqac_coordinator",
    [
        W("chart:accreditation.criteria_completion", "lg"),
        W("chart:accreditation.metrics_verified"),
        W("chart:accreditation.metric_trend", "lg"),
        W("chart:affiliation.college_compliance"),
        W("chart:surveys.completion"),
        W("chart:research.publications_by_indexing"),
        W("chart:results.pass_pct_by_program"),
        W("chart:placement.placement_pct", "sm"),
    ],
)
register_dashboard(
    "research_cell",
    [
        W("stat:publications_year", "sm"),
        W("stat:projects_active", "sm"),
        W("stat:scholars_active", "sm"),
        W("chart:research.publications_trend", "lg"),
        W("chart:research.grants_amount"),
        W("chart:research.projects_by_status"),
        W("chart:phd.scholars_by_status"),
        W("chart:phd.thesis_by_stage"),
    ],
)
register_dashboard(
    "alumni_coordinator",
    [W("chart:alumni.verified_pct", "sm"), W("chart:alumni.engagement", "lg"), W("chart:alumni.donations_trend")],
)
register_dashboard(
    "auditor",
    [
        W("stat:students_active", "sm"),
        W("stat:fee_collection_pct", "sm"),
        W("stat:staff_active", "sm"),
        W("chart:fees.dues_aging"),
        W("chart:accounting.income_vs_expense", "lg"),
        W("chart:accounting.budget_utilisation", "lg"),
        W("chart:students.enrolment_by_category"),
        W("chart:hr.staff_by_cadre"),
    ],
)
for _role in ("alumni", "recruiter", "applicant"):
    register_dashboard(_role, [W("action:reports", "sm")] if _role == "recruiter" else [W("action:my_results", "sm")])
