"""Results metrics — final-year pass %, success rate in the stipulated period, academic performance index and NIRF
GPH (registered in ``app/core/metrics.py``). Reads published current ``student_course_results`` of terms that end inside
the period."""

from typing import Any

from app.core.metrics import MetricContext, MetricResult, register_drilldown, register_metric
from app.services.accreditation.metrics._sql import mask_name, rows, scope, window

_PASS = "('pass', 'passed', 'cleared', 'exempted')"
_FINAL = (
    "FROM student_course_results r "
    "JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id "
    "JOIN programs p ON p.id = e.program_id "
    "JOIN academic_terms t ON t.id = r.term_id "
    "JOIN student_term_records tr ON tr.student_program_enrollment_id = e.id AND tr.term_id = r.term_id "
    "WHERE r.institution_id = :inst AND r.is_current AND r.status = 'published' "
    "AND t.end_date BETWEEN :p_start AND :p_end AND tr.term_number >= p.total_terms - 1"
)


def _sc(ctx: MetricContext, predicate: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    frag, params = scope(
        ctx, college="e.college_id", program="e.program_id", department="e.department_id", predicate=predicate
    )
    return frag, {**params, **window(ctx)}


async def _final_year(ctx: MetricContext) -> tuple[int, int]:
    """(students appeared, students who passed every course) in final-year terms of the period."""
    frag, params = _sc(ctx)
    out = await rows(
        ctx,
        f"SELECT e.id, bool_and(lower(r.result_status) IN {_PASS}) AS ok {_FINAL}{frag} GROUP BY e.id",
        params,
    )
    return len(out), sum(1 for r in out if r["ok"])


@register_metric("results.pass_pct_final_year", source_module="results")
async def pass_pct(ctx: MetricContext) -> MetricResult:
    appeared, passed = await _final_year(ctx)
    if not appeared:
        return MetricResult.empty("no published final-year results in the period")
    return MetricResult.ratio(passed, appeared, breakdown={"appeared": appeared}, query="results.final_year")


@register_metric("nirf.gph", source_module="results")
async def gph(ctx: MetricContext) -> MetricResult:
    """Graduation outcome: final-year students graduating on time (passed all courses at the first attempt)."""
    frag, params = _sc(ctx)
    out = await rows(
        ctx,
        f"SELECT e.id, bool_and(lower(r.result_status) IN {_PASS} AND r.attempt_number = 1) AS ok {_FINAL}{frag} "
        "GROUP BY e.id",
        params,
    )
    if not out:
        return MetricResult.empty("no published final-year results in the period")
    return MetricResult.ratio(sum(1 for r in out if r["ok"]), len(out), query="results.final_year")


@register_metric("results.success_rate", source_module="results")
async def success_rate(ctx: MetricContext) -> MetricResult:
    """NBA 4.2: students of the batch admitted N years ago who graduated without backlogs in the stipulated period."""
    frag, params = scope(ctx, college="e.college_id", program="e.program_id", department="e.department_id")
    out = await rows(
        ctx,
        "SELECT e.id, e.status, p.duration_years, e.admission_date "
        "FROM student_program_enrollments e JOIN programs p ON p.id = e.program_id "
        "WHERE e.institution_id = :inst AND e.entry_term_number = 1 "
        "AND e.admission_date + (p.duration_years * interval '1 year') BETWEEN CAST(:p_start AS date) AND CAST(:p_end AS date) + interval '6 months'"
        f"{frag}",
        {**params, **window(ctx)},
    )
    if not out:
        return MetricResult.empty("no batch due to graduate in the period")
    grads = sum(1 for r in out if r["status"] in ("completed", "graduated"))
    return MetricResult.ratio(grads, len(out), breakdown={"batch_size": len(out)}, query="results.final_year")


@register_metric("results.academic_performance_index", source_module="results")
async def api_index(ctx: MetricContext) -> MetricResult:
    """NBA 4.3/4.4: mean CGPA of the students with results × (successful / appeared)."""
    frag, params = scope(ctx, college="e.college_id", program="e.program_id", department="e.department_id")
    row = (
        await rows(
            ctx,
            "SELECT avg(tr.cgpa) AS mean, count(*) AS appeared, "
            "count(*) FILTER (WHERE tr.status IN ('promoted', 'completed', 'passed')) AS ok "
            "FROM student_term_records tr JOIN student_program_enrollments e ON e.id = tr.student_program_enrollment_id "
            "JOIN academic_terms t ON t.id = tr.term_id "
            f"WHERE tr.institution_id = :inst AND tr.cgpa IS NOT NULL AND t.end_date BETWEEN :p_start AND :p_end{frag}",
            {**params, **window(ctx)},
        )
    )[0]
    if not row["appeared"]:
        return MetricResult.empty("no term records with CGPA in the period")
    mean = float(row["mean"] or 0)
    share = int(row["ok"]) / int(row["appeared"])
    return MetricResult(round(mean * share, 4), row["ok"], row["appeared"], {"mean_cgpa": round(mean, 2)})


@register_drilldown("results.final_year")
async def final_rows(ctx: MetricContext, predicate: dict[str, Any] | None) -> list[dict[str, Any]]:
    frag, params = _sc(ctx, predicate)
    out = await rows(
        ctx,
        "SELECT e.id, s.registration_number, s.first_name, s.last_name, e.department_id, e.program_id, e.college_id, "
        f"bool_and(lower(r.result_status) IN {_PASS}) AS passed_all, count(*) AS courses "
        f"{_FINAL.replace('WHERE', 'JOIN students s ON s.id = e.student_id WHERE', 1)}{frag} "
        "GROUP BY e.id, s.registration_number, s.first_name, s.last_name, e.department_id, e.program_id, e.college_id "
        "ORDER BY s.registration_number LIMIT 5000",
        params,
    )
    for r in out:
        r["name"] = mask_name(r.pop("first_name"), r.pop("last_name"))
        r["link"] = f"/results/students/{r['id']}"
    return out
