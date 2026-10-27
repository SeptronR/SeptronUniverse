"""Generic chart providers used by the catalogue (``charts_catalogue.py``) — Prompts/35 §35.6 chart_service step 1.

* :func:`view_chart` — a grouped aggregate over a read model (``mv_*``) under the scope predicate;
* :func:`sql_chart` — an aggregate over source tables (module ``stats_service``-style, short ``cache_ttl``); the SQL
  carries a ``{where}`` placeholder that receives the scope predicate (columns named in ``cols``, fully qualified);
* :func:`label_rows` — resolves UUID labels to codes / names (departments, programmes, batches, colleges, terms,
  offerings, hostels, cycles, drives, exam sessions, designations) and keeps the raw id in ``_id`` for drill-down.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.charts import ChartContext, ChartResult, register_chart

__all__ = ["DRILL_FIELD", "VIEW_COLS", "label_rows", "period_bounds", "sql_chart", "view_chart"]

ALL_DIMS = ("college", "department", "program", "batch", "term", "period")

VIEW_COLS: dict[str, dict[str, str | None]] = {
    "mv_enrolment_daily": {
        "college": "college_id",
        "department": "department_id",
        "program": "program_id",
        "batch": "batch_id",
    },
    "mv_attendance_term": {
        "college": "college_id",
        "department": "department_id",
        "program": "program_id",
        "batch": "batch_id",
        "term": "term_id",
        "enrollment": "enrollment_id",
        "offering": "offering_id",
    },
    "mv_fees_position": {
        "college": "college_id",
        "department": "department_id",
        "program": "program_id",
        "batch": "batch_id",
        "enrollment": "enrollment_id",
    },
    "mv_exam_progress": {
        "college": "college_id",
        "department": None,
        "program": None,
        "batch": None,
        "term": "term_id",
    },
    "mv_results_summary": {
        "college": "college_id",
        "department": "department_id",
        "program": "program_id",
        "batch": "batch_id",
        "term": "term_id",
    },
    "mv_hr_snapshot": {"college": "college_id", "department": "department_id", "program": None, "batch": None},
    "mv_admissions_funnel": {"college": "college_id", "department": None, "program": "program_id", "batch": None},
    "mv_placement_funnel": {
        "college": "college_id",
        "department": "department_id",
        "program": None,
        "batch": "batch_id",
    },
    "mv_hostel_occupancy": {
        "college": "college_id",
        "department": None,
        "program": None,
        "batch": None,
        "hostel": "hostel_id",
    },
    "mv_research_counts": {"college": "college_id", "department": "department_id", "program": None, "batch": None},
    "mv_service_desk_sla": {"college": "college_id", "department": None, "program": None, "batch": None},
    "mv_risk_cohort": {
        "college": "college_id",
        "department": "department_id",
        "program": "program_id",
        "batch": "batch_id",
        "term": "term_id",
        "hostel": "hostel_id",
    },
}

_LOOKUPS: dict[str, str] = {
    "department": "SELECT id, code FROM departments WHERE id = ANY(:ids)",
    "program": "SELECT id, code FROM programs WHERE id = ANY(:ids)",
    "batch": "SELECT id, code FROM batches WHERE id = ANY(:ids)",
    "college": "SELECT id, code FROM colleges WHERE id = ANY(:ids)",
    "term": "SELECT id, name FROM academic_terms WHERE id = ANY(:ids)",
    "offering": "SELECT o.id, c.code || COALESCE('-' || o.section_code, '') FROM course_offerings o "
    "JOIN courses c ON c.id = o.course_id WHERE o.id = ANY(:ids)",
    "course": "SELECT id, code FROM courses WHERE id = ANY(:ids)",
    "hostel": "SELECT id, name FROM hostels WHERE id = ANY(:ids)",
    "block": "SELECT id, name FROM hostel_blocks WHERE id = ANY(:ids)",
    "cycle": "SELECT id, name FROM admission_cycles WHERE id = ANY(:ids)",
    "drive": "SELECT id, title FROM placement_drives WHERE id = ANY(:ids)",
    "session": "SELECT id, name FROM exam_sessions WHERE id = ANY(:ids)",
    "designation": "SELECT id, name FROM designations WHERE id = ANY(:ids)",
    "enrollment": "SELECT e.id, s.registration_number FROM student_program_enrollments e "
    "JOIN students s ON s.id = e.student_id WHERE e.id = ANY(:ids)",
    "committee": "SELECT id, name FROM committees WHERE id = ANY(:ids)",
}

DRILL_FIELD: dict[str, str] = {
    "department": "department_id",
    "program": "program_id",
    "batch": "batch_id",
    "college": "college_id",
    "term": "term_id",
    "offering": "offering_id",
    "hostel": "hostel_id",
    "cycle": "cycle_id",
    "drive": "drive_id",
    "session": "exam_session_id",
    "enrollment": "enrollment_id",
    "course": "course_id",
}


def period_bounds(ctx: ChartContext, default: str = "last_30d") -> tuple[date, date]:
    """``dims.period``: today | last_7d | last_30d | last_90d | this_month | this_year | fy | last_12m (end exclusive)."""
    today = date.today()
    p = str((ctx.dims or {}).get("period") or (ctx.params or {}).get("period") or default)
    end = today + timedelta(days=1)
    if p == "today":
        return today, end
    if p == "last_7d":
        return today - timedelta(days=6), end
    if p == "last_90d":
        return today - timedelta(days=89), end
    if p == "this_month":
        return today.replace(day=1), end
    if p == "this_year":
        return today.replace(month=1, day=1), end
    if p == "fy":
        start_year = today.year if today.month >= 4 else today.year - 1
        return date(start_year, 4, 1), end
    if p == "last_12m":
        return (today.replace(day=1) - timedelta(days=365)).replace(day=1), end
    if p == "last_5y":
        return date(today.year - 4, 1, 1), end
    return today - timedelta(days=29), end


async def label_rows(ctx: ChartContext, rows: list[dict[str, Any]], kind: str | None, field: str = "label") -> None:
    if not rows:
        return
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, Decimal):
                r[k] = float(v)
            elif isinstance(v, date):
                r[k] = v.isoformat()
    if not kind or kind not in _LOOKUPS:
        for r in rows:
            if isinstance(r.get(field), uuid.UUID):
                r[field] = str(r[field])
        return
    ids = [r[field] for r in rows if isinstance(r.get(field), uuid.UUID)]
    names: dict[Any, str] = {}
    if ids:
        res = await ctx.db.execute(text(_LOOKUPS[kind]), {"ids": list(set(ids))})
        names = {a: str(b) for a, b in res.all()}
    for r in rows:
        v = r.get(field)
        if isinstance(v, uuid.UUID):
            r["_id"] = str(v)
            r[field] = names.get(v, "—")
        elif v is None:
            r[field] = "—"


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


_FIELD_MAP = {
    "quota": "quota",
    "category": "category",
    "gender": "gender",
    "status": "status",
    "eligibility": "eligibility",
    "level": "level",
}


def _label_field(label: str, series: str | None) -> str | None:
    col = label.removeprefix("x.") if label.startswith("x.") and label[2:].isidentifier() else None
    if col in _FIELD_MAP:
        return _FIELD_MAP[col]
    if series and series.removeprefix("x.") in _FIELD_MAP:
        return "series"
    return None


def view_chart(
    key: str,
    *,
    module: str,
    permission: tuple[str, ...],
    title: str,
    view: str,
    label: str,
    measures: tuple[tuple[str, str], ...],
    kind: str = "bar",
    series: str | None = None,
    where: str = "",
    order: str | None = None,
    limit: int = 50,
    label_kind: str | None = None,
    dims: tuple[str, ...] = ALL_DIMS,
    current_term: bool = False,
    feature: str | None = None,
    route: str | None = None,
    drill_rows: str | None = None,
    ttl: int = 900,
    params_schema: dict[str, Any] | None = None,
    description: str = "",
) -> None:
    cols = VIEW_COLS[view]

    async def provider(ctx: ChartContext) -> ChartResult:
        pred, binds = ctx.where(alias="x", **cols)  # type: ignore[arg-type]
        extra = [where] if where else []
        if current_term and cols.get("term") and not (ctx.dims or {}).get("term_id"):
            extra.append("x.term_id IN (SELECT id FROM academic_terms WHERE institution_id = :_inst AND is_current)")
        sel = [f"{label} AS label"] + ([f"{series} AS series"] if series else [])
        sel += [f"{expr} AS {name}" for name, expr in measures]
        group = "1, 2" if series else "1"
        first = 3 if series else 2
        sql = (
            f"SELECT {', '.join(sel)} FROM {view} x WHERE {pred}"
            + "".join(f" AND {e}" for e in extra)
            + f" GROUP BY {group} ORDER BY {order or f'{first} DESC NULLS LAST'} LIMIT {int(limit)}"
        )
        rows = [dict(r) for r in (await ctx.db.execute(text(sql), binds)).mappings().all()]
        await label_rows(ctx, rows, label_kind)
        if series:
            await label_rows(ctx, rows, None, "series")
        total = sum(_num(r.get(measures[0][0])) for r in rows) if kind not in ("gauge", "number") else None
        return ChartResult(points=rows, total=total, drill={"_id": DRILL_FIELD.get(label_kind or "", "")})

    register_chart(
        key,
        module=module,
        permission=permission,
        title=title,
        kind=kind,
        feature=feature,
        dims=dims,
        params_schema=params_schema,
        drilldown_route=route,
        drilldown_rows=drill_rows,
        cache_ttl=ttl,
        source_view=view,
        description=description,
        label_field=_label_field(label, series),
    )(provider)


def sql_chart(
    key: str,
    *,
    module: str,
    permission: tuple[str, ...],
    title: str,
    sql: str,
    cols: dict[str, str | None],
    kind: str = "bar",
    label_kind: str | None = None,
    period: str | None = None,
    dims: tuple[str, ...] = ("college", "department", "period"),
    feature: str | None = None,
    route: str | None = None,
    drill_rows: str | None = None,
    ttl: int = 120,
    params_schema: dict[str, Any] | None = None,
    binds: dict[str, Any] | None = None,
    description: str = "",
) -> None:
    """``sql`` selects ``label`` [, ``series``], measures … with ``{where}`` (scope predicate) and, when ``period`` is set,
    ``:_from`` / ``:_to`` binds (``dims.period``, default ``period``)."""
    full: dict[str, str | None] = {
        "institution": None,
        "college": None,
        "department": None,
        "program": None,
        "batch": None,
        "term": None,
    }
    full.update(cols)

    async def provider(ctx: ChartContext) -> ChartResult:
        pred, b = ctx.where(alias="", **full)  # type: ignore[arg-type]
        if period:
            lo, hi = period_bounds(ctx, period)
            b.update({"_from": lo, "_to": hi})
        for name, spec in (params_schema or {}).get("properties", {}).items():
            b[f"p_{name}"] = (ctx.params or {}).get(name, spec.get("default"))
        b.update(binds or {})
        rows = [dict(r) for r in (await ctx.db.execute(text(sql.format(where=pred)), b)).mappings().all()]
        await label_rows(ctx, rows, label_kind)
        if rows and "series" in rows[0]:
            await label_rows(ctx, rows, None, "series")
        vk = next((k for k in (rows[0] if rows else {}) if k not in ("label", "series", "_id")), "value")
        total = sum(_num(r.get(vk)) for r in rows) if kind not in ("gauge", "number") else None
        return ChartResult(points=rows, total=total, drill={"_id": DRILL_FIELD.get(label_kind or "", "")})

    if full.get("institution") is None:
        raise AssertionError(f"chart {key}: sql_chart needs cols['institution']")
    register_chart(
        key,
        module=module,
        permission=permission,
        title=title,
        kind=kind,
        feature=feature,
        dims=dims,
        params_schema=params_schema,
        drilldown_route=route,
        drilldown_rows=drill_rows,
        cache_ttl=ttl,
        source_view=None,
        description=description,
    )(provider)
