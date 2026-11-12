"""Academics, student support, campus, finance and OBE metrics (registered in ``app/core/metrics.py``): CBCS %,
value-added / new courses, programme count, scholarships, SSS score, grievance SLA, mentoring ratio, events by type /
extension, professional activities, qualifying exams, hostel occupancy, transport routes, library / infra / capex /
opex spend, NIRF FRU / ESCS / GUE, CO / PO attainment and the attainment gap, functional MoUs, quality initiatives,
affiliated colleges and placement offers."""

from decimal import Decimal
from typing import Any

from app.core.metrics import MetricContext, MetricResult, register_drilldown, register_metric
from app.services.accreditation.metrics._sql import rows, scalar, scope, window


async def _count(ctx: MetricContext, sql: str, params: dict[str, Any]) -> int:
    return int(await scalar(ctx, sql, params) or 0)


# ---- academics ------------------------------------------------------------------------------------------------------------
@register_metric("academics.cbcs_pct", source_module="academics")
async def cbcs_pct(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="p.college_id", program="p.id", department="p.department_id")
    total = await _count(ctx, f"SELECT count(*) FROM programs p WHERE p.institution_id = :inst{frag}", params)
    elective = await _count(
        ctx,
        "SELECT count(DISTINCT p.id) FROM programs p JOIN courses c ON c.department_id = p.department_id "
        f"WHERE p.institution_id = :inst AND c.course_type IN ('program_elective', 'open_elective'){frag}",
        params,
    )
    return MetricResult.ratio(elective, total)


@register_metric("academics.value_added_courses", source_module="academics")
async def value_added(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="c.college_id", department="c.department_id")
    n = await _count(
        ctx,
        f"SELECT count(*) FROM courses c WHERE c.institution_id = :inst AND c.course_type = 'value_added'{frag}",
        params,
    )
    return MetricResult(n, n)


@register_metric("academics.new_courses_pct", source_module="academics")
async def new_courses(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="c.college_id", department="c.department_id")
    params |= window(ctx)
    total = await _count(ctx, f"SELECT count(*) FROM courses c WHERE c.institution_id = :inst{frag}", params)
    new = await _count(
        ctx,
        f"SELECT count(*) FROM courses c WHERE c.institution_id = :inst AND c.created_at::date BETWEEN :p_start AND :p_end{frag}",
        params,
    )
    return MetricResult.ratio(new, total)


@register_metric("academics.programs_count", source_module="academics")
async def programs_count(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="p.college_id", department="p.department_id")
    rws = await rows(
        ctx, f"SELECT p.level, count(*) AS n FROM programs p WHERE p.institution_id = :inst{frag} GROUP BY 1", params
    )
    by = {str(r["level"]): int(r["n"]) for r in rws}
    return MetricResult(sum(by.values()), sum(by.values()), None, {"by_level": by})


# ---- student support ------------------------------------------------------------------------------------------------------
@register_metric("scholarships.beneficiaries_pct", source_module="fees")
async def scholarships(ctx: MetricContext) -> MetricResult:
    from app.services.accreditation.metrics.hr import active_students

    frag, params = scope(ctx, college="e.college_id", program="e.program_id", department="e.department_id")
    params |= window(ctx)
    n = await _count(
        ctx,
        "SELECT count(DISTINCT a.student_program_enrollment_id) FROM scholarship_applications a "
        "JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id "
        "WHERE a.institution_id = :inst AND a.status IN ('sanctioned', 'disbursed') "
        f"AND a.updated_at::date BETWEEN :p_start AND :p_end{frag}",
        params,
    )
    return MetricResult.ratio(n, await active_students(ctx))


@register_metric("nirf.escs", source_module="fees")
async def escs(ctx: MetricContext) -> MetricResult:
    from app.services.accreditation.metrics.hr import active_students

    frag, params = scope(ctx, college="e.college_id", program="e.program_id", department="e.department_id")
    params |= window(ctx)
    n = await _count(
        ctx,
        "SELECT count(DISTINCT e.id) FROM student_program_enrollments e JOIN students s ON s.id = e.student_id "
        "WHERE e.institution_id = :inst AND e.admission_date <= :p_end AND (e.exit_date IS NULL OR e.exit_date >= :p_start) "
        "AND (lower(COALESCE(s.category, '')) IN ('sc', 'st', 'obc', 'ews') OR EXISTS (SELECT 1 FROM scholarship_applications a "
        f"WHERE a.student_program_enrollment_id = e.id AND a.status IN ('sanctioned', 'disbursed'))){frag}",
        params,
    )
    return MetricResult.ratio(n, await active_students(ctx))


@register_metric("surveys.sss_score", source_module="surveys")
async def sss(ctx: MetricContext) -> MetricResult:
    params = {"inst": ctx.institution_id, **window(ctx)}
    v = await scalar(
        ctx,
        "SELECT avg(a.value::numeric) FROM feedback_responses sr JOIN feedback_surveys s ON s.id = sr.survey_id "
        "CROSS JOIN LATERAL jsonb_each_text(CASE WHEN jsonb_typeof(sr.answers) = 'object' THEN sr.answers ELSE '{}'::jsonb END) a "
        "WHERE sr.institution_id = :inst AND s.survey_type = 'sss' AND sr.submitted_at::date BETWEEN :p_start AND :p_end "
        "AND a.value ~ '^[0-9]+(\\.[0-9]+)?$'",
        params,
    )
    if v is None:
        return MetricResult.empty("no analysed student satisfaction survey in the period")
    return MetricResult(round(Decimal(v), 4))


@register_metric("governance.grievance_sla_pct", source_module="grievances")
async def grievance_sla(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="g.college_id")
    params |= window(ctx)
    base = f"FROM grievances g WHERE g.institution_id = :inst AND g.created_at::date BETWEEN :p_start AND :p_end{frag}"
    total = await _count(ctx, f"SELECT count(*) {base} AND g.status IN ('resolved', 'closed')", params)
    within = await _count(
        ctx,
        f"SELECT count(*) {base} AND g.status IN ('resolved', 'closed') AND g.resolved_at <= COALESCE(g.sla_due_at, g.resolved_at)",
        params,
    )
    return MetricResult.ratio(within, total, query="campus.grievances")


@register_metric("mentoring.ratio", source_module="mentoring")
async def mentoring_ratio(ctx: MetricContext) -> MetricResult:
    params = {"inst": ctx.institution_id, **window(ctx)}
    out = (
        await rows(
            ctx,
            "SELECT count(DISTINCT m.student_program_enrollment_id) AS mentees, count(DISTINCT m.mentor_staff_id) AS mentors "
            "FROM mentor_assignments m JOIN academic_terms t ON t.id = m.term_id "
            "WHERE m.institution_id = :inst AND t.start_date <= :p_end AND t.end_date >= :p_start",
            params,
        )
    )[0]
    return MetricResult.ratio(int(out["mentees"]), int(out["mentors"]), pct=False)


async def _events(ctx: MetricContext, types: tuple[str, ...] | None = None) -> dict[str, int]:
    frag, params = scope(ctx, college="ev.college_id", department="ev.organiser_department_id")
    params |= window(ctx)
    cond = " AND ev.event_type = ANY(:types)" if types else ""
    if types:
        params["types"] = list(types)
    out = await rows(
        ctx,
        "SELECT ev.event_type AS k, count(*) AS n FROM events ev WHERE ev.institution_id = :inst AND ev.deleted_at IS NULL "
        f"AND ev.status = 'completed' AND ev.from_on BETWEEN :p_start AND :p_end{cond}{frag} GROUP BY 1",
        params,
    )
    return {str(r["k"]): int(r["n"]) for r in out}


@register_metric("events.count_by_type", source_module="events")
async def events_by_type(ctx: MetricContext) -> MetricResult:
    by = await _events(ctx)
    return MetricResult(sum(by.values()), sum(by.values()), None, {"by_type": by}, "campus.events")


@register_metric("events.extension_activities", source_module="events")
async def extension(ctx: MetricContext) -> MetricResult:
    by = await _events(ctx, ("outreach",))
    frag, params = scope(ctx, department="e.department_id")
    params |= window(ctx)
    hours = await _count(
        ctx,
        "SELECT count(DISTINCT a.id) FROM activity_hours a JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id "
        f"WHERE a.institution_id = :inst AND a.activity_type IN ('nss', 'ncc', 'community_service') AND a.on_date BETWEEN :p_start AND :p_end{frag}",
        params,
    )
    n = sum(by.values())
    return MetricResult(n, n, None, {"outreach_events": n, "nss_ncc_records": hours}, "campus.events")


@register_metric("students.professional_activities", source_module="clubs")
async def professional(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="e.college_id", program="e.program_id", department="e.department_id")
    params |= window(ctx)
    out = await rows(
        ctx,
        "SELECT a.activity_type AS k, count(DISTINCT a.student_program_enrollment_id) AS n FROM activity_hours a "
        "JOIN student_program_enrollments e ON e.id = a.student_program_enrollment_id "
        f"WHERE a.institution_id = :inst AND a.verified_at IS NOT NULL AND a.on_date BETWEEN :p_start AND :p_end{frag} GROUP BY 1",
        params,
    )
    by = {str(r["k"]): int(r["n"]) for r in out}
    return MetricResult(sum(by.values()), sum(by.values()), None, {"by_activity": by})


@register_metric("students.qualifying_exams", source_module="placement")
async def qualifying(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="e.college_id", program="e.program_id", department="e.department_id")
    n = await _count(
        ctx,
        "SELECT count(*) FROM student_placement_profiles sp JOIN student_program_enrollments e ON e.id = sp.student_program_enrollment_id "
        f"WHERE sp.institution_id = :inst AND (sp.higher_studies ? 'qualifying_exam' OR sp.higher_studies ? 'exam'){frag}",
        params,
    )
    return MetricResult(n, n)


@register_metric("hostel.occupancy_pct", source_module="hostel")
async def hostel_occupancy(ctx: MetricContext) -> MetricResult:
    params = {"inst": ctx.institution_id}
    beds = await _count(
        ctx, "SELECT count(*) FROM hostel_beds b WHERE b.institution_id = :inst AND b.status <> 'blocked'", params
    )
    taken = await _count(
        ctx, "SELECT count(*) FROM hostel_beds b WHERE b.institution_id = :inst AND b.status = 'allocated'", params
    )
    return MetricResult.ratio(taken, beds)


@register_metric("transport.routes", source_module="transport")
async def transport_routes(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="r.college_id")
    n = await _count(
        ctx, f"SELECT count(*) FROM transport_routes r WHERE r.institution_id = :inst AND r.is_active{frag}", params
    )
    return MetricResult(n, n)


# ---- finance ----------------------------------------------------------------------------------------------------------------
async def _spend(ctx: MetricContext, name_like: tuple[str, ...] | None, exclude_salary: bool = True) -> int:
    frag, params = scope(ctx, college="x.college_id", department="x.department_id")
    params |= window(ctx)
    cond = ""
    if name_like:
        cond = " AND (" + " OR ".join(f"lower(la.name) LIKE :n{i}" for i in range(len(name_like))) + ")"
        params |= {f"n{i}": f"%{n}%" for i, n in enumerate(name_like)}
    if exclude_salary:
        cond += " AND lower(la.name) NOT LIKE '%salar%'"
    return await _count(
        ctx,
        "SELECT COALESCE(sum(x.amount_paise), 0) FROM expense_records x JOIN ledger_accounts la ON la.id = x.ledger_account_id "
        f"WHERE x.institution_id = :inst AND x.status IN ('approved', 'paid') AND x.spent_on BETWEEN :p_start AND :p_end{cond}{frag}",
        params,
    )


@register_metric("finance.capex", source_module="accounting")
async def capex(ctx: MetricContext) -> MetricResult:
    v = await _spend(ctx, ("capital", "equipment", "building", "furniture", "infrastructure"))
    return MetricResult(v, v, None, {}, "campus.expenses")


@register_metric("finance.opex", source_module="accounting")
async def opex(ctx: MetricContext) -> MetricResult:
    v = await _spend(ctx, None)
    return MetricResult(v, v, None, {}, "campus.expenses")


@register_metric("finance.infra_spend_pct", source_module="accounting")
async def infra_pct(ctx: MetricContext) -> MetricResult:
    infra = await _spend(ctx, ("capital", "equipment", "building", "furniture", "infrastructure"))
    return MetricResult.ratio(infra, await _spend(ctx, None), query="campus.expenses")


@register_metric("library.spend", source_module="accounting")
async def library_spend(ctx: MetricContext) -> MetricResult:
    v = await _spend(ctx, ("library", "book", "journal"))
    return MetricResult(v, v, None, {}, "campus.expenses")


@register_metric("nirf.fru", source_module="accounting", depends_on=("finance.capex", "finance.opex"))
async def fru(ctx: MetricContext) -> MetricResult:
    from app.services.accreditation.metrics.hr import active_students

    cap, op = ctx.computed.get("finance.capex"), ctx.computed.get("finance.opex")
    if cap is None or op is None or cap.value is None or op.value is None:
        return MetricResult.empty("finance.capex / finance.opex not available")
    students = await active_students(ctx)
    per = (Decimal(str(cap.value)) + Decimal(str(op.value))) / Decimal(students) if students else None
    return MetricResult(
        round(per, 4) if per is not None else None,
        Decimal(str(cap.value)) + Decimal(str(op.value)),
        students,
        {"per_student_paise": str(per) if per else None},
    )


# ---- OBE ---------------------------------------------------------------------------------------------------------------------
@register_metric("obe.co_attainment", source_module="obe")
async def co_attainment(ctx: MetricContext) -> MetricResult:
    params = {"inst": ctx.institution_id, **window(ctx)}
    v = await scalar(
        ctx,
        "SELECT avg(c.final_level) FROM co_attainments c WHERE c.institution_id = :inst "
        "AND c.computed_at::date BETWEEN :p_start AND :p_end",
        params,
    )
    return (
        MetricResult(round(Decimal(v), 4))
        if v is not None
        else MetricResult.empty("no CO attainment run in the period")
    )


@register_metric("obe.po_attainment", source_module="obe")
async def po_attainment(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, program="pa.program_id")
    params |= window(ctx)
    out = (
        await rows(
            ctx,
            "SELECT avg(pa.final_level) AS lvl, count(*) AS n, count(*) FILTER (WHERE pa.gap > 0) AS below "
            f"FROM po_attainments pa WHERE pa.institution_id = :inst AND pa.computed_at::date BETWEEN :p_start AND :p_end{frag}",
            params,
        )
    )[0]
    if not out["n"] or out["lvl"] is None:  # final_level not computed yet: the average is NULL
        return MetricResult.empty("no PO attainment run in the period")
    return MetricResult(
        round(Decimal(out["lvl"]), 4),
        out["below"],
        out["n"],
        {"outcomes": int(out["n"]), "below_target": int(out["below"])},
    )


@register_metric("obe.attainment_gap_pct", source_module="obe", depends_on=("obe.po_attainment",))
async def attainment_gap(ctx: MetricContext) -> MetricResult:
    po = ctx.computed.get("obe.po_attainment")
    if po is None or not po.denominator:
        return MetricResult.empty("obe.po_attainment not available")
    return MetricResult.ratio(po.numerator or 0, po.denominator)


# ---- research / governance ------------------------------------------------------------------------------------------------
@register_metric("research.mous_functional", source_module="research")
async def mous_functional(ctx: MetricContext) -> MetricResult:
    params = {"inst": ctx.institution_id, **window(ctx)}
    total = await _count(
        ctx, "SELECT count(*) FROM mous m WHERE m.institution_id = :inst AND m.status = 'active'", params
    )
    functional = await _count(
        ctx,
        "SELECT count(*) FROM mous m WHERE m.institution_id = :inst AND m.status = 'active' "
        "AND jsonb_typeof(m.activities) = 'array' AND jsonb_array_length(m.activities) > 0",
        params,
    )
    return MetricResult(functional, functional, total, {"active": total})


@register_metric("governance.quality_initiatives", source_module="accreditation")
async def quality_initiatives(ctx: MetricContext) -> MetricResult:
    params = {"inst": ctx.institution_id, "label": ctx.period.label}
    subs = await _count(
        ctx,
        "SELECT count(*) FROM compliance_submissions c WHERE c.institution_id = :inst AND c.period_label = :label "
        "AND c.status IN ('submitted', 'acknowledged')",
        params,
    )
    audits = await _count(
        ctx, "SELECT count(*) FROM audit_registers a WHERE a.institution_id = :inst AND a.period_label = :label", params
    )
    return MetricResult(subs + audits, subs + audits, None, {"submissions": subs, "audits": audits})


@register_metric("affiliation.colleges_count", source_module="affiliation")
async def colleges_count(ctx: MetricContext) -> MetricResult:
    n = await _count(
        ctx,
        "SELECT count(*) FROM colleges c WHERE c.institution_id = :inst AND c.college_type = 'affiliated' AND c.is_active",
        {"inst": ctx.institution_id},
    )
    return MetricResult(n, n)


@register_metric("placement.offers", source_module="placement")
async def placement_offers(ctx: MetricContext) -> MetricResult:
    params = {"inst": ctx.institution_id, "min_ctc": int(ctx.params.get("min_ctc_paise") or 0), **window(ctx)}
    n = await _count(
        ctx,
        "SELECT count(*) FROM placement_offers o WHERE o.institution_id = :inst AND o.status IN ('accepted', 'joined', 'offered') "
        "AND o.ctc_paise >= :min_ctc AND COALESCE(o.offered_on, o.created_at::date) BETWEEN :p_start AND :p_end",
        params,
    )
    return MetricResult(n, n, None, {"min_ctc_paise": params["min_ctc"]})


@register_metric(
    "nirf.gue", source_module="placement", depends_on=("placement.placed_pct", "students.higher_studies_pct")
)
async def gue(ctx: MetricContext) -> MetricResult:
    pl, hs = ctx.computed.get("placement.placed_pct"), ctx.computed.get("students.higher_studies_pct")
    if pl is None or pl.value is None:
        return MetricResult.empty("placement.placed_pct not published for the period")
    v = min(Decimal(100), Decimal(str(pl.value)) + Decimal(str(hs.value if hs and hs.value is not None else 0)))
    return MetricResult(
        v, None, None, {"placed_pct": str(pl.value), "higher_studies_pct": str(hs.value) if hs else None}
    )


# ---- drill-downs --------------------------------------------------------------------------------------------------------------
@register_drilldown("campus.grievances")
async def grievance_rows(ctx: MetricContext, predicate: dict[str, Any] | None) -> list[dict[str, Any]]:
    frag, params = scope(ctx, college="g.college_id", predicate=predicate)
    params |= window(ctx)
    out = await rows(
        ctx,
        "SELECT g.id, g.ticket_number, g.category, g.status, g.created_at, g.resolved_at, g.sla_due_at, g.college_id "
        f"FROM grievances g WHERE g.institution_id = :inst AND g.created_at::date BETWEEN :p_start AND :p_end{frag} "
        "ORDER BY g.created_at LIMIT 5000",
        params,
    )
    for r in out:
        r["link"] = f"/support/grievances/{r['id']}"
    return out


@register_drilldown("campus.events")
async def event_rows(ctx: MetricContext, predicate: dict[str, Any] | None) -> list[dict[str, Any]]:
    frag, params = scope(ctx, college="ev.college_id", department="ev.organiser_department_id", predicate=predicate)
    params |= window(ctx)
    out = await rows(
        ctx,
        "SELECT ev.id, ev.title, ev.event_type, ev.from_on, ev.participants_count, ev.naac_criterion, ev.report_url, "
        "ev.organiser_department_id AS department_id FROM events ev WHERE ev.institution_id = :inst AND ev.deleted_at IS NULL "
        f"AND ev.status = 'completed' AND ev.from_on BETWEEN :p_start AND :p_end{frag} ORDER BY ev.from_on LIMIT 5000",
        params,
    )
    for r in out:
        r["link"] = f"/events/{r['id']}"
    return out


@register_drilldown("campus.expenses")
async def expense_rows(ctx: MetricContext, predicate: dict[str, Any] | None) -> list[dict[str, Any]]:
    frag, params = scope(ctx, college="x.college_id", department="x.department_id", predicate=predicate)
    params |= window(ctx)
    out = await rows(
        ctx,
        "SELECT x.id, x.spent_on, la.name AS ledger, x.amount_paise, x.description, x.department_id, x.college_id "
        "FROM expense_records x JOIN ledger_accounts la ON la.id = x.ledger_account_id WHERE x.institution_id = :inst "
        f"AND x.status IN ('approved', 'paid') AND x.spent_on BETWEEN :p_start AND :p_end{frag} ORDER BY x.spent_on LIMIT 5000",
        params,
    )
    for r in out:
        r["link"] = f"/accounting/expenses/{r['id']}"
    return out
