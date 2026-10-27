"""Materialized read models — Prompts/35 §35.2 (``0035_phase35_analytics_read_models``; ``Database_Schema.sql`` §37).

Each view carries ``institution_id`` and the scope dimensions (``college_id``, ``department_id``, ``program_id``,
``batch_id``, ``enrollment_id`` / ``staff_id`` where the grain has them) so the analytics repository applies the same
visibility predicate to it as to the source tables, plus a ``UNIQUE`` index for ``REFRESH … CONCURRENTLY``. The SQL is
defined once here: the migration executes :data:`READ_MODELS` and ``Database_Schema.sql`` section 37 holds the same text
(``python -m app.services.analytics.read_models`` prints it). Statements are idempotent (``IF NOT EXISTS``) because a
fresh ``0001`` already applies section 37.

Refresh runs as the owning platform role (``PlatformSessionLocal``): materialized views carry no RLS, so every read goes
through the repository's ``institution_id`` + dimension predicate.
"""

from dataclasses import dataclass

__all__ = ["READ_MODELS", "VIEW_NAMES", "ReadModel", "schema_section"]

ZERO = "'00000000-0000-0000-0000-000000000000'::uuid"


@dataclass(frozen=True)
class ReadModel:
    name: str
    select: str
    unique: tuple[str, ...]
    sources: tuple[str, ...]  # source modules whose events mark the view dirty
    description: str

    @property
    def create_sql(self) -> str:
        return f"CREATE MATERIALIZED VIEW IF NOT EXISTS {self.name} AS\n{self.select.strip()};"

    @property
    def index_sql(self) -> str:
        return f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{self.name} ON {self.name} ({', '.join(self.unique)});"

    @property
    def tenant_index_sql(self) -> str:
        return f"CREATE INDEX IF NOT EXISTS ix_{self.name}_inst ON {self.name} (institution_id);"

    def statements(self) -> list[str]:
        return [self.create_sql, self.index_sql, self.tenant_index_sql]


_ENROLMENT_DAILY = """
SELECT e.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id,
       COALESCE(s.category, '') AS category, COALESCE(s.gender, '') AS gender, COALESCE(s.admission_quota, '') AS quota,
       e.status, COALESCE(e.admission_date, e.created_at::date) AS day, COUNT(*)::int AS enrolments
FROM student_program_enrollments e
JOIN students s ON s.id = e.student_id
WHERE e.deleted_at IS NULL AND s.deleted_at IS NULL
GROUP BY e.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, COALESCE(s.category, ''),
         COALESCE(s.gender, ''), COALESCE(s.admission_quota, ''), e.status, COALESCE(e.admission_date, e.created_at::date)
"""

_ATTENDANCE_TERM = """
SELECT a.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, o.term_id,
       o.department_id AS offering_department_id, a.offering_id, a.student_program_enrollment_id AS enrollment_id,
       a.total_sessions AS sessions_held, (a.present + a.late + a.on_duty) AS sessions_present, a.pct,
       GREATEST(0, 75 - a.pct)::numeric(5,2) AS shortfall_pct, (a.eligibility <> 'eligible') AS is_short,
       a.eligibility, a.computed_at AS last_computed
FROM attendance_summaries a
JOIN course_offerings o ON o.id = a.offering_id
JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id
"""

_FEES_POSITION = """
SELECT i.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id,
       i.student_program_enrollment_id AS enrollment_id,
       SUM(i.total_paise - i.discount_paise + i.tax_paise + i.fine_paise)::bigint AS billed_paise,
       SUM(i.paid_paise)::bigint AS paid_paise, SUM(i.balance_paise)::bigint AS balance_paise,
       SUM(CASE WHEN i.due_date < CURRENT_DATE THEN i.balance_paise ELSE 0 END)::bigint AS overdue_paise,
       SUM(CASE WHEN i.due_date < CURRENT_DATE AND CURRENT_DATE - i.due_date <= 30 THEN i.balance_paise ELSE 0 END)::bigint AS aging_0_30_paise,
       SUM(CASE WHEN CURRENT_DATE - i.due_date BETWEEN 31 AND 60 THEN i.balance_paise ELSE 0 END)::bigint AS aging_31_60_paise,
       SUM(CASE WHEN CURRENT_DATE - i.due_date BETWEEN 61 AND 90 THEN i.balance_paise ELSE 0 END)::bigint AS aging_61_90_paise,
       SUM(CASE WHEN CURRENT_DATE - i.due_date > 90 THEN i.balance_paise ELSE 0 END)::bigint AS aging_90_plus_paise,
       COUNT(*)::int AS invoices, MAX(i.updated_at) AS last_activity_at
FROM fee_invoices i
JOIN student_program_enrollments e ON e.id = i.student_program_enrollment_id
WHERE i.student_program_enrollment_id IS NOT NULL AND i.status NOT IN ('cancelled', 'refunded')
GROUP BY i.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, i.student_program_enrollment_id
"""

_EXAM_PROGRESS = """
SELECT s.institution_id, s.college_id, s.term_id, s.id AS exam_session_id, s.name, s.exam_kind, s.status,
       COALESCE(r.registrations, 0) AS registrations, COALESCE(r.confirmed, 0) AS confirmed,
       COALESCE(r.eligibility_applied, 0) AS eligibility_applied, COALESCE(r.hall_tickets, 0) AS hall_tickets,
       COALESCE(sc.scripts, 0) AS scripts, COALESCE(sc.valuated, 0) AS scripts_valuated,
       COALESCE(sc.discrepancies, 0) AS discrepancies,
       CASE WHEN COALESCE(sc.scripts, 0) = 0 THEN 0
            ELSE ROUND(100.0 * sc.valuated / sc.scripts, 2) END::numeric(5,2) AS valuation_pct,
       CASE WHEN s.status IN ('results_published', 'closed') THEN 'published'
            WHEN s.status = 'result_processing' THEN 'processing' ELSE 'pending' END AS results_stage
FROM exam_sessions s
LEFT JOIN (
  SELECT exam_session_id, COUNT(*)::int AS registrations,
         COUNT(*) FILTER (WHERE status = 'confirmed')::int AS confirmed,
         COUNT(*) FILTER (WHERE eligibility_snapshot IS NOT NULL)::int AS eligibility_applied,
         COUNT(*) FILTER (WHERE hall_ticket_issued_at IS NOT NULL)::int AS hall_tickets
  FROM exam_registrations GROUP BY exam_session_id
) r ON r.exam_session_id = s.id
LEFT JOIN (
  SELECT er.exam_session_id, COUNT(a.id)::int AS scripts,
         COUNT(a.id) FILTER (WHERE a.status IN ('valuated', 'finalized', 'moderated', 'decoded', 'archived'))::int AS valuated,
         COUNT(a.id) FILTER (WHERE a.status IN ('discrepancy', 'third_valuation'))::int AS discrepancies
  FROM answer_scripts a
  JOIN exam_registration_items it ON it.id = a.exam_registration_item_id
  JOIN exam_registrations er ON er.id = it.exam_registration_id
  GROUP BY er.exam_session_id
) sc ON sc.exam_session_id = s.id
WHERE s.deleted_at IS NULL
"""

_RESULTS_SUMMARY = """
SELECT e.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, tr.term_id,
       COUNT(*)::int AS students, COUNT(*) FILTER (WHERE r.backlog_count = 0)::int AS passed,
       ROUND(100.0 * COUNT(*) FILTER (WHERE r.backlog_count = 0) / NULLIF(COUNT(*), 0), 2)::numeric(5,2) AS pass_pct,
       ROUND(AVG(r.sgpa), 2)::numeric(4,2) AS avg_sgpa, MAX(r.sgpa) AS top_sgpa,
       SUM(r.backlog_count)::int AS arrears,
       COUNT(*) FILTER (WHERE r.sgpa < 5)::int AS sgpa_lt5,
       COUNT(*) FILTER (WHERE r.sgpa >= 5 AND r.sgpa < 6)::int AS sgpa_5_6,
       COUNT(*) FILTER (WHERE r.sgpa >= 6 AND r.sgpa < 7)::int AS sgpa_6_7,
       COUNT(*) FILTER (WHERE r.sgpa >= 7 AND r.sgpa < 8)::int AS sgpa_7_8,
       COUNT(*) FILTER (WHERE r.sgpa >= 8 AND r.sgpa < 9)::int AS sgpa_8_9,
       COUNT(*) FILTER (WHERE r.sgpa >= 9)::int AS sgpa_9_plus
FROM student_term_results r
JOIN student_term_records tr ON tr.id = r.student_term_record_id
JOIN student_program_enrollments e ON e.id = tr.student_program_enrollment_id
WHERE r.is_current AND r.status = 'published'
GROUP BY e.institution_id, e.college_id, e.department_id, e.program_id, e.batch_id, tr.term_id
"""

_HR_SNAPSHOT = f"""
SELECT s.institution_id, s.college_id, s.department_id, COALESCE(s.designation_id, {ZERO}) AS designation_id,
       COALESCE(d.cadre, '') AS cadre, COALESCE(s.staff_category, '') AS staff_category,
       COUNT(*) FILTER (WHERE s.status IN ('active', 'on_leave'))::int AS headcount,
       COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM staff_leaves l WHERE l.staff_id = s.id AND l.status = 'approved'
                                      AND CURRENT_DATE BETWEEN l.from_date AND l.to_date))::int AS on_leave_today,
       COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM staff_attendance a WHERE a.staff_id = s.id
                                      AND a.attendance_date = CURRENT_DATE
                                      AND a.status IN ('present', 'half_day', 'on_duty')))::int AS present_today,
       COALESCE(SUM((SELECT COUNT(*) FROM staff_leaves l WHERE l.staff_id = s.id AND l.status = 'pending')), 0)::int AS leaves_pending
FROM staff s
LEFT JOIN designations d ON d.id = s.designation_id
WHERE s.deleted_at IS NULL AND s.status <> 'exited'
GROUP BY s.institution_id, s.college_id, s.department_id, COALESCE(s.designation_id, {ZERO}), COALESCE(d.cadre, ''),
         COALESCE(s.staff_category, '')
"""

_ADMISSIONS_FUNNEL = f"""
SELECT a.institution_id, COALESCE(p.college_id, c.college_id) AS college_id, a.cycle_id,
       COALESCE(p.program_id, {ZERO}) AS program_id, COALESCE(a.category, '') AS category,
       COALESCE(a.quota_claimed, '') AS quota,
       COUNT(*) FILTER (WHERE a.status <> 'draft')::int AS applications,
       COUNT(*) FILTER (WHERE a.status IN ('verified', 'waitlisted', 'merit_listed', 'allotted', 'accepted',
                                           'provisionally_admitted', 'admitted'))::int AS verified,
       COUNT(*) FILTER (WHERE a.status IN ('merit_listed', 'allotted', 'accepted', 'provisionally_admitted',
                                           'admitted'))::int AS merit,
       COUNT(*) FILTER (WHERE a.status IN ('allotted', 'accepted', 'provisionally_admitted', 'admitted'))::int AS allotted,
       COUNT(*) FILTER (WHERE a.status IN ('provisionally_admitted', 'admitted') OR a.admitted_student_id IS NOT NULL)::int AS admitted,
       COUNT(*)::int AS started
FROM applicants a
JOIN admission_cycles c ON c.id = a.cycle_id
LEFT JOIN applicant_preferences p ON p.applicant_id = a.id AND p.priority = 1
WHERE a.deleted_at IS NULL
GROUP BY a.institution_id, COALESCE(p.college_id, c.college_id), a.cycle_id, COALESCE(p.program_id, {ZERO}),
         COALESCE(a.category, ''), COALESCE(a.quota_claimed, '')
"""

_PLACEMENT_FUNNEL = f"""
SELECT d.institution_id, COALESCE(e.college_id, d.college_id) AS college_id, e.department_id,
       COALESCE(e.batch_id, {ZERO}) AS batch_id, d.id AS drive_id, d.status AS drive_status, d.drive_on,
       COUNT(da.id) FILTER (WHERE da.is_eligible)::int AS eligible, COUNT(da.id)::int AS applied,
       COUNT(da.id) FILTER (WHERE da.status IN ('shortlisted', 'in_process', 'selected', 'offer_accepted',
                                                'offer_declined'))::int AS in_rounds,
       COUNT(o.id)::int AS offers, COUNT(o.id) FILTER (WHERE o.status IN ('accepted', 'joined'))::int AS accepted,
       COUNT(o.id) FILTER (WHERE o.ctc_paise < 50000000)::int AS ctc_lt5l,
       COUNT(o.id) FILTER (WHERE o.ctc_paise >= 50000000 AND o.ctc_paise < 100000000)::int AS ctc_5_10l,
       COUNT(o.id) FILTER (WHERE o.ctc_paise >= 100000000 AND o.ctc_paise < 200000000)::int AS ctc_10_20l,
       COUNT(o.id) FILTER (WHERE o.ctc_paise >= 200000000)::int AS ctc_20l_plus,
       COALESCE(MAX(o.ctc_paise), 0)::bigint AS max_ctc_paise
FROM placement_drives d
LEFT JOIN drive_applications da ON da.drive_id = d.id
LEFT JOIN student_program_enrollments e ON e.id = da.student_program_enrollment_id
LEFT JOIN placement_offers o ON o.application_id = da.id
GROUP BY d.institution_id, COALESCE(e.college_id, d.college_id), e.department_id, COALESCE(e.batch_id, {ZERO}), d.id,
         d.status, d.drive_on
"""

_HOSTEL_OCCUPANCY = """
SELECT h.institution_id, h.college_id, h.id AS hostel_id, b.id AS block_id, h.name AS hostel_name, b.name AS block_name,
       h.warden_staff_id,
       COUNT(bd.id)::int AS beds, COUNT(bd.id) FILTER (WHERE bd.status = 'allocated')::int AS occupied,
       (SELECT COUNT(*) FROM hostel_leaves l WHERE l.hostel_id = h.id AND l.status = 'out')::int AS leave_out_today,
       (SELECT COUNT(*) FROM hostel_complaints c JOIN hostel_rooms cr ON cr.id = c.room_id
         WHERE cr.block_id = b.id AND c.status NOT IN ('resolved', 'closed'))::int AS complaints_open
FROM hostels h
JOIN hostel_blocks b ON b.hostel_id = h.id
LEFT JOIN hostel_rooms r ON r.block_id = b.id
LEFT JOIN hostel_beds bd ON bd.room_id = r.id
WHERE h.deleted_at IS NULL
GROUP BY h.institution_id, h.college_id, h.id, b.id, h.name, b.name, h.warden_staff_id
"""

_RESEARCH_COUNTS = f"""
SELECT x.institution_id, x.college_id, COALESCE(x.department_id, {ZERO}) AS department_id, x.year, x.metric, x.sub_key,
       COUNT(*)::int AS count, COALESCE(SUM(x.amount_paise), 0)::bigint AS amount_paise
FROM (
  SELECT p.institution_id, s.college_id, s.department_id, COALESCE(p.year, 0)::int AS year, 'publications' AS metric,
         COALESCE(p.indexing, 'none') AS sub_key, 0::bigint AS amount_paise
  FROM publications p LEFT JOIN staff s ON s.id = p.staff_id
  UNION ALL
  SELECT rp.institution_id, s.college_id, s.department_id, COALESCE(EXTRACT(YEAR FROM rp.start_on), 0)::int, 'projects',
         rp.status, COALESCE(rp.sanctioned_paise, 0)::bigint
  FROM research_projects rp LEFT JOIN staff s ON s.id = rp.pi_staff_id
  UNION ALL
  SELECT rs.institution_id, e.college_id, e.department_id, COALESCE(EXTRACT(YEAR FROM rs.registration_date), 0)::int,
         'scholars', rs.status, 0::bigint
  FROM research_scholars rs JOIN student_program_enrollments e ON e.id = rs.student_program_enrollment_id
) x
GROUP BY x.institution_id, x.college_id, COALESCE(x.department_id, {ZERO}), x.year, x.metric, x.sub_key
"""

_SERVICE_DESK_SLA = f"""
SELECT r.institution_id, COALESCE(r.college_id, {ZERO}) AS college_id, r.category,
       COUNT(*) FILTER (WHERE r.status NOT IN ('resolved', 'closed'))::int AS open,
       COUNT(*) FILTER (WHERE r.status NOT IN ('resolved', 'closed') AND r.sla_due_at < NOW())::int AS breached,
       COUNT(*) FILTER (WHERE r.resolved_at IS NOT NULL)::int AS resolved,
       COUNT(*) FILTER (WHERE r.resolved_at IS NOT NULL AND (r.sla_due_at IS NULL OR r.resolved_at <= r.sla_due_at))::int AS within_sla,
       ROUND(AVG(EXTRACT(EPOCH FROM (r.resolved_at - r.created_at)) / 3600.0)
             FILTER (WHERE r.resolved_at IS NOT NULL), 2)::numeric(10,2) AS mttr_hours
FROM service_requests r
GROUP BY r.institution_id, COALESCE(r.college_id, {ZERO}), r.category
"""

_RISK_COHORT = f"""
SELECT f.institution_id, e.college_id, f.term_id, e.department_id, e.program_id, e.batch_id,
       COALESCE(s.category, '') AS category, COALESCE(h.hostel_id, {ZERO}) AS hostel_id, f.level,
       COUNT(*)::int AS students,
       ROUND(AVG((f.factors -> 'attendance' ->> 'value')::numeric), 3) AS attendance_mean,
       ROUND(AVG((f.factors -> 'cia' ->> 'value')::numeric), 3) AS cia_mean,
       ROUND(AVG((f.factors -> 'dues' ->> 'value')::numeric), 3) AS dues_mean,
       ROUND(AVG((f.factors -> 'standing' ->> 'value')::numeric), 3) AS standing_mean,
       ROUND(AVG((f.factors -> 'hostel' ->> 'value')::numeric), 3) AS hostel_mean,
       ROUND(AVG((f.factors -> 'engagement' ->> 'value')::numeric), 3) AS engagement_mean,
       ROUND(AVG(f.score), 2) AS score_mean,
       COUNT(*) FILTER (WHERE f.acknowledged_at IS NOT NULL)::int AS acknowledged,
       ROUND(100.0 * COUNT(*) FILTER (WHERE f.acknowledged_at IS NOT NULL) / NULLIF(COUNT(*), 0), 2)::numeric(5,2) AS acknowledged_pct,
       COALESCE(SUM((SELECT COUNT(*) FROM mentoring_sessions ms JOIN mentor_assignments ma ON ma.id = ms.mentor_assignment_id
                      WHERE ma.student_program_enrollment_id = f.student_program_enrollment_id
                        AND ms.mode = 'intervention')), 0)::int AS interventions
FROM risk_flags f
JOIN student_program_enrollments e ON e.id = f.student_program_enrollment_id
JOIN students s ON s.id = e.student_id
LEFT JOIN LATERAL (
  SELECT ha.hostel_id FROM hostel_allocations ha
  WHERE ha.student_program_enrollment_id = e.id AND ha.status IN ('allotted', 'checked_in')
  ORDER BY ha.created_at DESC LIMIT 1
) h ON TRUE
GROUP BY f.institution_id, e.college_id, f.term_id, e.department_id, e.program_id, e.batch_id, COALESCE(s.category, ''),
         COALESCE(h.hostel_id, {ZERO}), f.level
"""

# (column, source alias, aggregate expression) — every source CTE groups by GROUPING SETS ((institution, college),
# (institution)) and is keyed by ``ckey`` ('all' for the institution row, the college id otherwise, 'none' for rows
# without a college) so per-college rows and the institution total come from one pass.
_KPI_SOURCES: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "stu",
        "SELECT e.institution_id, e.college_id, e.status FROM student_program_enrollments e WHERE e.deleted_at IS NULL",
        (
            ("students_active", "COUNT(*) FILTER (WHERE status = 'active')"),
            ("students_total", "COUNT(*)"),
        ),
    ),
    (
        "prg",
        "SELECT institution_id, college_id, status FROM programs WHERE deleted_at IS NULL",
        (("programmes", "COUNT(*) FILTER (WHERE status = 'active')"),),
    ),
    (
        "stf",
        "SELECT institution_id, college_id, staff_category, status FROM staff WHERE deleted_at IS NULL AND status <> 'exited'",
        (
            ("staff_active", "COUNT(*)"),
            ("faculty_count", "COUNT(*) FILTER (WHERE staff_category = 'teaching')"),
        ),
    ),
    (
        "hrs",
        "SELECT institution_id, college_id, present_today, on_leave_today, leaves_pending FROM mv_hr_snapshot",
        (
            ("staff_present_today", "SUM(present_today)"),
            ("staff_on_leave_today", "SUM(on_leave_today)"),
            ("leaves_pending", "SUM(leaves_pending)"),
        ),
    ),
    (
        "att",
        "SELECT institution_id, college_id, pct, is_short, enrollment_id FROM mv_attendance_term a "
        "WHERE a.term_id IN (SELECT id FROM academic_terms WHERE is_current)",
        (
            ("attendance_avg_pct", "ROUND(AVG(pct), 2)"),
            ("attendance_shortfall", "COUNT(DISTINCT enrollment_id) FILTER (WHERE is_short)"),
        ),
    ),
    (
        "fee",
        "SELECT institution_id, college_id, billed_paise, paid_paise, overdue_paise FROM mv_fees_position",
        (
            ("fee_billed_paise", "SUM(billed_paise)"),
            ("fee_collected_paise", "SUM(paid_paise)"),
            ("fee_overdue_paise", "SUM(overdue_paise)"),
            ("fee_defaulters", "COUNT(*) FILTER (WHERE overdue_paise > 0)"),
            ("fee_collection_pct", "ROUND(100.0 * SUM(paid_paise) / NULLIF(SUM(billed_paise), 0), 2)"),
        ),
    ),
    (
        "pay",
        "SELECT p.institution_id, i.college_id, p.amount_paise FROM fee_payments p JOIN fee_invoices i ON i.id = p.invoice_id "
        "WHERE p.status IN ('success', 'reconciled') AND p.payment_date::date = CURRENT_DATE",
        (("fee_collected_today_paise", "SUM(amount_paise)"),),
    ),
    (
        "exm",
        "SELECT institution_id, college_id, status, valuation_pct FROM mv_exam_progress",
        (
            ("exam_sessions_active", "COUNT(*) FILTER (WHERE status NOT IN ('draft', 'results_published', 'closed'))"),
            ("valuation_pct", "ROUND(AVG(valuation_pct) FILTER (WHERE status = 'valuation'), 2)"),
        ),
    ),
    (
        "res",
        "SELECT institution_id, college_id, students, passed, avg_sgpa FROM mv_results_summary",
        (
            ("result_pass_pct", "ROUND(100.0 * SUM(passed) / NULLIF(SUM(students), 0), 2)"),
            ("avg_sgpa", "ROUND(AVG(avg_sgpa), 2)"),
        ),
    ),
    (
        "adm",
        "SELECT f.institution_id, f.college_id, f.applications, f.admitted FROM mv_admissions_funnel f "
        "JOIN admission_cycles c ON c.id = f.cycle_id WHERE c.status NOT IN ('archived')",
        (("applications", "SUM(applications)"), ("admitted", "SUM(admitted)")),
    ),
    (
        "enq",
        "SELECT institution_id, college_id, stage FROM enquiries",
        (("enquiries_open", "COUNT(*) FILTER (WHERE stage NOT IN ('admitted', 'lost'))"),),
    ),
    (
        "plc",
        "SELECT institution_id, college_id, offers, accepted, eligible FROM mv_placement_funnel",
        (
            ("placement_offers", "SUM(offers)"),
            ("placement_accepted", "SUM(accepted)"),
            ("placement_pct", "ROUND(100.0 * SUM(accepted) / NULLIF(SUM(eligible), 0), 2)"),
        ),
    ),
    (
        "hst",
        "SELECT institution_id, college_id, beds, occupied, leave_out_today, complaints_open FROM mv_hostel_occupancy",
        (
            ("hostel_beds", "SUM(beds)"),
            ("hostel_occupied", "SUM(occupied)"),
            ("hostel_out_today", "SUM(leave_out_today)"),
            ("hostel_complaints_open", "SUM(complaints_open)"),
        ),
    ),
    (
        "lib",
        "SELECT institution_id, NULL::uuid AS college_id, status, due_on, returned_on FROM book_issues",
        (
            ("library_issued", "COUNT(*) FILTER (WHERE returned_on IS NULL)"),
            ("library_overdue", "COUNT(*) FILTER (WHERE returned_on IS NULL AND due_on < CURRENT_DATE)"),
        ),
    ),
    (
        "grv",
        "SELECT institution_id, college_id, status, sla_due_at, resolved_at FROM grievances",
        (
            ("grievances_open", "COUNT(*) FILTER (WHERE status NOT IN ('resolved', 'closed'))"),
            (
                "grievances_breached",
                "COUNT(*) FILTER (WHERE status NOT IN ('resolved', 'closed') AND sla_due_at < NOW())",
            ),
            (
                "grievance_sla_pct",
                "ROUND(100.0 * COUNT(*) FILTER (WHERE resolved_at IS NOT NULL AND (sla_due_at IS NULL OR resolved_at <= sla_due_at)) "
                "/ NULLIF(COUNT(*) FILTER (WHERE resolved_at IS NOT NULL), 0), 2)",
            ),
        ),
    ),
    (
        "srv",
        f"SELECT institution_id, NULLIF(college_id, {ZERO}) AS college_id, open, breached FROM mv_service_desk_sla",
        (("service_open", "SUM(open)"), ("service_breached", "SUM(breached)")),
    ),
    (
        "rsk",
        "SELECT institution_id, college_id, level, students FROM mv_risk_cohort "
        "WHERE term_id IN (SELECT id FROM academic_terms WHERE is_current)",
        (
            ("risk_high", "SUM(students) FILTER (WHERE level = 'high')"),
            ("risk_medium", "SUM(students) FILTER (WHERE level = 'medium')"),
        ),
    ),
    (
        "rch",
        "SELECT institution_id, college_id, metric, sub_key, year, count FROM mv_research_counts",
        (
            (
                "publications_year",
                "SUM(count) FILTER (WHERE metric = 'publications' AND year = EXTRACT(YEAR FROM CURRENT_DATE))",
            ),
            (
                "projects_active",
                "SUM(count) FILTER (WHERE metric = 'projects' AND sub_key IN ('sanctioned', 'ongoing'))",
            ),
            (
                "scholars_active",
                "SUM(count) FILTER (WHERE metric = 'scholars' AND sub_key NOT IN ('awarded', 'discontinued'))",
            ),
        ),
    ),
    (
        "hld",
        "SELECT h.institution_id, e.college_id FROM student_holds h JOIN student_program_enrollments e "
        "ON e.id = h.student_program_enrollment_id WHERE h.released_at IS NULL",
        (("holds_active", "COUNT(*)"),),
    ),
)


def _kpi_select() -> str:
    ctes = [
        "keys AS (SELECT institution_id, id AS college_id, id::text AS ckey FROM colleges WHERE deleted_at IS NULL "
        "UNION ALL SELECT id, NULL::uuid, 'all' FROM institutions WHERE deleted_at IS NULL)"
    ]
    cols: list[str] = []
    joins: list[str] = []
    for alias, source, measures in _KPI_SOURCES:
        aggs = ", ".join(f"{expr} AS {col}" for col, expr in measures)
        ctes.append(
            f"{alias} AS (SELECT institution_id, CASE WHEN GROUPING(college_id) = 1 THEN 'all' "
            f"ELSE COALESCE(college_id::text, 'none') END AS ckey, {aggs} FROM ({source}) s "
            f"GROUP BY GROUPING SETS ((institution_id, college_id), (institution_id)))"
        )
        joins.append(f"LEFT JOIN {alias} ON {alias}.institution_id = k.institution_id AND {alias}.ckey = k.ckey")
        # ratios stay NULL without data (a college with no students is not "0 % attendance" — no false KPI breach)
        cols += [
            f"{alias}.{col} AS {col}"
            if col.endswith("_pct") or col == "avg_sgpa"
            else f"COALESCE({alias}.{col}, 0) AS {col}"
            for col, _ in measures
        ]
    return (
        "WITH "
        + ",\n".join(ctes)
        + "\nSELECT k.institution_id, k.college_id, k.ckey AS college_key, CURRENT_DATE AS day, NOW() AS refreshed_at,\n       "
        + ",\n       ".join(cols)
        + "\nFROM keys k\n"
        + "\n".join(joins)
    )


KPI_COLUMNS: tuple[str, ...] = tuple(col for _, _, ms in _KPI_SOURCES for col, _ in ms)

READ_MODELS: tuple[ReadModel, ...] = (
    ReadModel(
        "mv_enrolment_daily",
        _ENROLMENT_DAILY,
        (
            "institution_id",
            "college_id",
            "department_id",
            "program_id",
            "batch_id",
            "category",
            "gender",
            "quota",
            "status",
            "day",
        ),
        ("students", "admissions"),
        "Enrolments by college / department / programme / batch / category / gender / quota / status per day",
    ),
    ReadModel(
        "mv_attendance_term",
        _ATTENDANCE_TERM,
        ("offering_id", "enrollment_id"),
        ("attendance", "registration"),
        "Per enrolment × offering: sessions held / present / %, shortfall vs threshold",
    ),
    ReadModel(
        "mv_fees_position",
        _FEES_POSITION,
        ("enrollment_id",),
        ("fees",),
        "Per enrolment: billed / paid / overdue paise and aging bands",
    ),
    ReadModel(
        "mv_exam_progress",
        _EXAM_PROGRESS,
        ("exam_session_id",),
        ("exams", "results"),
        "Per exam session: registrations, eligibility, hall tickets, scripts, valuation %, discrepancies, results stage",
    ),
    ReadModel(
        "mv_results_summary",
        _RESULTS_SUMMARY,
        ("institution_id", "college_id", "department_id", "program_id", "batch_id", "term_id"),
        ("results",),
        "Per term × programme × batch: pass %, SGPA distribution, arrears, toppers",
    ),
    ReadModel(
        "mv_hr_snapshot",
        _HR_SNAPSHOT,
        ("institution_id", "college_id", "department_id", "designation_id", "cadre", "staff_category"),
        ("hr", "leaves"),
        "Staff by department / designation / cadre, leaves pending, attendance today",
    ),
    ReadModel(
        "mv_admissions_funnel",
        _ADMISSIONS_FUNNEL,
        ("institution_id", "college_id", "cycle_id", "program_id", "category", "quota"),
        ("admissions",),
        "Per cycle × programme: applications → verified → merit → allotted → admitted, by category / quota",
    ),
    ReadModel(
        "mv_placement_funnel",
        _PLACEMENT_FUNNEL,
        ("institution_id", "college_id", "department_id", "batch_id", "drive_id"),
        ("placement",),
        "Per drive / batch: eligible → applied → rounds → offers → accepted, CTC bands",
    ),
    ReadModel(
        "mv_hostel_occupancy",
        _HOSTEL_OCCUPANCY,
        ("block_id",),
        ("hostel",),
        "Per hostel / block: beds, occupied, leave-out today, complaints open",
    ),
    ReadModel(
        "mv_research_counts",
        _RESEARCH_COUNTS,
        ("institution_id", "college_id", "department_id", "year", "metric", "sub_key"),
        ("research", "phd"),
        "Per department / year: publications by indexing, projects / grants amount, PhD scholars by status",
    ),
    ReadModel(
        "mv_service_desk_sla",
        _SERVICE_DESK_SLA,
        ("institution_id", "college_id", "category"),
        ("facilities",),
        "Per category: open, breached, MTTR",
    ),
    ReadModel(
        "mv_risk_cohort",
        _RISK_COHORT,
        (
            "institution_id",
            "college_id",
            "term_id",
            "department_id",
            "program_id",
            "batch_id",
            "category",
            "hostel_id",
            "level",
        ),
        ("mentoring",),
        "Per term × department × programme × batch × level: counts, factor means, acknowledged %, interventions",
    ),
    ReadModel(
        "mv_kpi_daily",
        _kpi_select(),
        ("institution_id", "college_key", "day"),
        ("*",),
        "One row per institution × college × day: the headline numbers used by Home cards",
    ),
)

VIEW_NAMES: tuple[str, ...] = tuple(m.name for m in READ_MODELS)
BY_NAME: dict[str, ReadModel] = {m.name: m for m in READ_MODELS}

# source module → views it feeds (event-driven dirty marking)
SOURCE_VIEWS: dict[str, tuple[str, ...]] = {}
for _m in READ_MODELS:
    for _s in _m.sources:
        SOURCE_VIEWS[_s] = (*SOURCE_VIEWS.get(_s, ()), _m.name)


def schema_section() -> str:
    """``Database_Schema.sql`` section 37 (same statements, in dependency order — ``mv_kpi_daily`` reads the others)."""
    out = [
        "-- ===================================== 37. ANALYTICS READ MODELS =====================================",
        "-- Phase 35 materialized views (app/services/analytics/read_models.py is the single source; Alembic 0035 applies the",
        "-- same statements). Refreshed CONCURRENTLY by the analytics.refresh_scheduler Beat task; no RLS on matviews — the",
        "-- analytics repository applies institution_id + the scope-dimension predicate on every read.",
    ]
    for m in READ_MODELS:
        out.append(f"-- {m.name}: {m.description}")
        out += m.statements()
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    print(schema_section())  # noqa: T201
