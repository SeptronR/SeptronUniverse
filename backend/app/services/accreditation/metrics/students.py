"""Students / admissions metrics — enrolment by category / gender / programme, seats filled vs reserved, dropout,
gender ratio, PwD, NIRF RD / WD (registered in ``app/core/metrics.py``)."""

from typing import Any

from app.core.metrics import MetricContext, MetricResult, register_drilldown, register_metric
from app.services.accreditation.metrics._sql import mask_name, rows, scalar, scope, window

_ACTIVE = (
    "FROM student_program_enrollments e JOIN students s ON s.id = e.student_id "
    "WHERE e.institution_id = :inst AND e.admission_date <= :p_end "
    "AND (e.exit_date IS NULL OR e.exit_date >= :p_start) AND e.status NOT IN ('cancelled')"
)


def _sc(ctx: MetricContext, predicate: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    frag, params = scope(
        ctx, college="e.college_id", program="e.program_id", department="e.department_id", predicate=predicate
    )
    return frag, {**params, **window(ctx)}


async def _group(ctx: MetricContext, col: str) -> dict[str, int]:
    frag, params = _sc(ctx)
    out = await rows(
        ctx, f"SELECT COALESCE({col}, 'unspecified') AS k, count(*) AS n {_ACTIVE}{frag} GROUP BY 1", params
    )
    return {str(r["k"]): int(r["n"]) for r in out}


@register_metric("students.enrolment_by_category", source_module="students")
async def enrolment_by_category(ctx: MetricContext) -> MetricResult:
    by_cat = await _group(ctx, "s.category")
    total = sum(by_cat.values())
    if not total:
        return MetricResult.empty("no active enrolments in the period")
    return MetricResult(
        total,
        total,
        None,
        {"by_category": by_cat, "by_gender": await _group(ctx, "s.gender")},
        "students.enrolments",
    )


@register_metric("students.seats_filled_vs_reserved", source_module="admissions")
async def seats_filled(ctx: MetricContext) -> MetricResult:
    frag, params = scope(ctx, college="p.college_id", program="p.id", department="p.department_id")
    intake = int(
        await scalar(
            ctx,
            f"SELECT COALESCE(sum(COALESCE(p.sanctioned_intake, 0)), 0) FROM programs p WHERE p.institution_id = :inst{frag}",
            params,
        )
        or 0
    )
    frag2, params2 = _sc(ctx)
    admitted = int(
        await scalar(
            ctx,
            "SELECT count(*) FROM student_program_enrollments e WHERE e.institution_id = :inst "
            f"AND e.admission_date BETWEEN :p_start AND :p_end AND e.entry_term_number = 1{frag2}",
            params2,
        )
        or 0
    )
    return MetricResult.ratio(admitted, intake, breakdown={"sanctioned_intake": intake}, query="students.enrolments")


@register_metric("students.dropout_pct", source_module="students")
async def dropout(ctx: MetricContext) -> MetricResult:
    frag, params = _sc(ctx)
    total = int(await scalar(ctx, f"SELECT count(*) {_ACTIVE}{frag}", params) or 0)
    dropped = int(
        await scalar(
            ctx,
            f"SELECT count(*) {_ACTIVE}{frag} AND e.status IN ('discontinued', 'dropped', 'withdrawn') "
            "AND e.exit_date BETWEEN :p_start AND :p_end",
            params,
        )
        or 0
    )
    return MetricResult.ratio(dropped, total, query="students.enrolments")


@register_metric("values.gender_ratio", source_module="students")
async def gender_ratio(ctx: MetricContext) -> MetricResult:
    g = await _group(ctx, "lower(s.gender)")
    female = sum(v for k, v in g.items() if k in ("f", "female"))
    male = sum(v for k, v in g.items() if k in ("m", "male"))
    return MetricResult.ratio(female, male, pct=False, breakdown={"by_gender": g}, query="students.enrolments")


@register_metric("nirf.wd", source_module="students")
async def women_diversity(ctx: MetricContext) -> MetricResult:
    g = await _group(ctx, "lower(s.gender)")
    female = sum(v for k, v in g.items() if k in ("f", "female"))
    return MetricResult.ratio(female, sum(g.values()), breakdown={"by_gender": g}, query="students.enrolments")


@register_metric("values.pwd_ratio", source_module="students")
async def pwd_ratio(ctx: MetricContext) -> MetricResult:
    frag, params = _sc(ctx)
    total = int(await scalar(ctx, f"SELECT count(*) {_ACTIVE}{frag}", params) or 0)
    pwd = int(await scalar(ctx, f"SELECT count(*) {_ACTIVE}{frag} AND s.is_pwd", params) or 0)
    return MetricResult.ratio(pwd, total, query="students.enrolments")


@register_metric("nirf.rd", source_module="students")
async def regional_diversity(ctx: MetricContext) -> MetricResult:
    frag, params = _sc(ctx)
    home = await scalar(
        ctx, "SELECT address->>'state' FROM institutions WHERE id = :inst", {"inst": ctx.institution_id}
    )
    total = int(await scalar(ctx, f"SELECT count(*) {_ACTIVE}{frag}", params) or 0)
    other = int(
        await scalar(
            ctx,
            f"SELECT count(*) {_ACTIVE}{frag} AND (s.is_international OR "
            "(s.domicile_state IS NOT NULL AND lower(s.domicile_state) <> lower(COALESCE(:home, ''))))",
            {**params, "home": home},
        )
        or 0
    )
    return MetricResult.ratio(other, total, breakdown={"home_state": home}, query="students.enrolments")


@register_drilldown("students.enrolments")
async def enrolment_rows(ctx: MetricContext, predicate: dict[str, Any] | None) -> list[dict[str, Any]]:
    frag, params = _sc(ctx, predicate)
    out = await rows(
        ctx,
        "SELECT e.id, s.registration_number, s.first_name, s.last_name, s.gender, s.category, e.status, "
        f"e.admission_date, e.department_id, e.program_id, e.college_id {_ACTIVE}{frag} "
        "ORDER BY s.registration_number LIMIT 5000",
        params,
    )
    for r in out:
        r["name"] = mask_name(r.pop("first_name"), r.pop("last_name"))
        r["link"] = f"/students/enrolments/{r['id']}"
    return out
