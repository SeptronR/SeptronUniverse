"""SQL helpers shared by the metric computation modules: scope fragments (college / programme / department view) and
scalar / row execution under the tenant session (RLS) with an explicit ``institution_id`` filter."""

import uuid
from typing import Any

from sqlalchemy import text

from app.core.metrics import MetricContext


def scope(
    ctx: MetricContext,
    *,
    college: str | None = None,
    program: str | None = None,
    department: str | None = None,
    predicate: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """`` AND …`` fragment for the context's college / programme / department view and an optional visibility
    predicate (``{department_ids?, college_ids?}``) — column names are the caller's aliases."""
    parts: list[str] = []
    params: dict[str, Any] = {"inst": ctx.institution_id}
    if college and ctx.college_id:
        parts.append(f"{college} = :college_id")
        params["college_id"] = ctx.college_id
    if program and ctx.program_id:
        parts.append(f"{program} = :program_id")
        params["program_id"] = ctx.program_id
    depts: list[uuid.UUID] | None = ctx.department_ids
    if predicate and predicate.get("department_ids") is not None:
        depts = list(predicate["department_ids"])
    if department and depts is not None:
        parts.append(f"{department} = ANY(:dept_ids)")
        params["dept_ids"] = depts or [uuid.uuid4()]
    if college and predicate and predicate.get("college_ids") is not None:
        parts.append(f"{college} = ANY(:college_ids)")
        params["college_ids"] = list(predicate["college_ids"]) or [uuid.uuid4()]
    return ("".join(f" AND {p}" for p in parts), params)


async def scalar(ctx: MetricContext, sql: str, params: dict[str, Any]) -> Any:
    return (await ctx.db.execute(text(sql), params)).scalar()


async def rows(ctx: MetricContext, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r._mapping) for r in (await ctx.db.execute(text(sql), params)).all()]


def window(ctx: MetricContext) -> dict[str, Any]:
    return {"p_start": ctx.period.start, "p_end": ctx.period.end}


def mask_name(first: str | None, last: str | None = None) -> str:
    """PII masking for drill-down rows: initials plus the first letter of the surname."""
    f = (first or "").strip()
    l_ = (last or "").strip()
    return f"{f[:1]}{'*' * max(len(f) - 1, 0)} {l_[:1]}." if f else "—"
