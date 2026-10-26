"""HR / faculty metrics — FSR, PhD %, cadre ratio, qualification index, non-teaching count and the derived NIRF
FSR / FQE scores (registered in ``app/core/metrics.py``)."""

from decimal import Decimal
from typing import Any

from app.core.metrics import MetricContext, MetricResult, register_drilldown, register_metric
from app.services.accreditation.metrics._sql import mask_name, rows, scalar, scope, window

_TEACHING = (
    "FROM staff st LEFT JOIN faculty_profiles fp ON fp.staff_id = st.id "
    "WHERE st.institution_id = :inst AND st.staff_category = 'teaching' "
    "AND (st.joining_date IS NULL OR st.joining_date <= :p_end) "
    "AND (st.exit_date IS NULL OR st.exit_date >= :p_start) AND st.status NOT IN ('terminated')"
)


def _sc(ctx: MetricContext, predicate: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    frag, params = scope(ctx, college="st.college_id", department="st.department_id", predicate=predicate)
    return frag, {**params, **window(ctx)}


async def teachers(ctx: MetricContext) -> int:
    frag, params = _sc(ctx)
    return int(await scalar(ctx, f"SELECT count(*) {_TEACHING}{frag}", params) or 0)


async def active_students(ctx: MetricContext) -> int:
    frag, params = scope(ctx, college="e.college_id", program="e.program_id", department="e.department_id")
    return int(
        await scalar(
            ctx,
            "SELECT count(*) FROM student_program_enrollments e WHERE e.institution_id = :inst "
            "AND e.admission_date <= :p_end AND (e.exit_date IS NULL OR e.exit_date >= :p_start) "
            f"AND e.status NOT IN ('cancelled'){frag}",
            {**params, **window(ctx)},
        )
        or 0
    )


@register_metric("faculty.fsr", source_module="hr")
async def fsr(ctx: MetricContext) -> MetricResult:
    """numerator = active students, denominator = active teaching staff (students per teacher)."""
    return MetricResult.ratio(await active_students(ctx), await teachers(ctx), pct=False, query="hr.teachers")


@register_metric("faculty.phd_pct", source_module="hr")
async def phd_pct(ctx: MetricContext) -> MetricResult:
    frag, params = _sc(ctx)
    phd = int(await scalar(ctx, f"SELECT count(*) {_TEACHING}{frag} AND fp.is_phd", params) or 0)
    return MetricResult.ratio(phd, await teachers(ctx), query="hr.teachers")


@register_metric("faculty.cadre_ratio", source_module="hr")
async def cadre_ratio(ctx: MetricContext) -> MetricResult:
    frag, params = _sc(ctx)
    out = await rows(
        ctx, f"SELECT lower(COALESCE(fp.cadre, 'unspecified')) AS k, count(*) AS n {_TEACHING}{frag} GROUP BY 1", params
    )
    by = {str(r["k"]): int(r["n"]) for r in out}
    prof = sum(v for k, v in by.items() if k.startswith("prof"))
    assoc = sum(v for k, v in by.items() if "assoc" in k)
    assist = sum(v for k, v in by.items() if "assist" in k)
    # AICTE norm 1 : 2 : 6 — the value is the share of the required senior cadre met (capped at 100 %)
    total = prof + assoc + assist
    required_senior = Decimal(total) * Decimal(3) / Decimal(9)
    if not total:
        return MetricResult.empty("no teaching staff with a cadre in the period")
    met = min(Decimal(prof + assoc), required_senior)
    return MetricResult.ratio(
        met,
        required_senior,
        breakdown={"by_cadre": by, "professor": prof, "associate": assoc, "assistant": assist},
        query="hr.teachers",
    )


@register_metric("faculty.fqi", source_module="hr")
async def fqi(ctx: MetricContext) -> MetricResult:
    """NBA 5.3 faculty qualification index: (10·PhD + 6·PG) / teachers, scaled to 10."""
    frag, params = _sc(ctx)
    phd = int(await scalar(ctx, f"SELECT count(*) {_TEACHING}{frag} AND fp.is_phd", params) or 0)
    total = await teachers(ctx)
    pg = max(total - phd, 0)
    if not total:
        return MetricResult.empty("no teaching staff in the period")
    v = Decimal(10 * phd + 6 * pg) / Decimal(total)
    return MetricResult(round(v, 4), 10 * phd + 6 * pg, total, {"phd": phd, "pg": pg}, "hr.teachers")


@register_metric("faculty.non_teaching_count", source_module="hr")
async def non_teaching(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="st.college_id", department="st.department_id")
    n = int(
        await scalar(
            ctx,
            "SELECT count(*) FROM staff st WHERE st.institution_id = :inst AND st.staff_category <> 'teaching' "
            f"AND st.status = 'active'{frag}",
            params,
        )
        or 0
    )
    return MetricResult(n, n, None, {})


@register_metric("nirf.fsr", source_module="hr", depends_on=("faculty.fsr",))
async def nirf_fsr(ctx: MetricContext) -> MetricResult:
    """NIRF FSR score (30 marks): full marks at 1:15, proportional below (``depends_on`` faculty.fsr)."""
    base = ctx.computed.get("faculty.fsr")
    if base is None or base.value is None:
        return MetricResult.empty("faculty.fsr not available")
    ratio = Decimal(str(base.value))
    score = Decimal(30) if ratio <= 15 else Decimal(30) * Decimal(15) / ratio
    return MetricResult(round(score, 4), base.numerator, base.denominator, {"students_per_teacher": str(ratio)})


@register_metric("nirf.fqe", source_module="hr", depends_on=("faculty.phd_pct", "faculty.fqi"))
async def nirf_fqe(ctx: MetricContext) -> MetricResult:
    """NIRF FQE (20 marks): 10 for PhD share (full at 95 %), 10 for the qualification index (full at 10)."""
    phd = ctx.computed.get("faculty.phd_pct")
    q = ctx.computed.get("faculty.fqi")
    if phd is None or phd.value is None or q is None or q.value is None:
        return MetricResult.empty("faculty.phd_pct / faculty.fqi not available")
    fq = min(Decimal(10), Decimal(10) * Decimal(str(phd.value)) / Decimal(95))
    fe = min(Decimal(10), Decimal(str(q.value)))
    return MetricResult(round(fq + fe, 4), None, None, {"fq": str(round(fq, 2)), "fe": str(round(fe, 2))})


@register_drilldown("hr.teachers")
async def teacher_rows(ctx: MetricContext, predicate: dict[str, Any] | None) -> list[dict[str, Any]]:
    frag, params = _sc(ctx, predicate)
    out = await rows(
        ctx,
        "SELECT st.id, st.employee_id, st.first_name, st.last_name, st.department_id, st.college_id, fp.cadre, "
        f"fp.is_phd, fp.highest_qualification {_TEACHING}{frag} ORDER BY st.employee_id LIMIT 5000",
        params,
    )
    for r in out:
        r["name"] = mask_name(r.pop("first_name"), r.pop("last_name"))
        r["link"] = f"/hr/staff/{r['id']}"
    return out
