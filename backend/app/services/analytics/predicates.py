"""Scope → SQL predicate for chart providers and read models (Prompts/35 §35.5 ``analytics_repository``).

``scope_sql`` maps the :class:`~app.core.charts.ResolvedScope` onto the dimension columns a query exposes:

* ``all`` → ``institution_id`` only;
* ``college`` → the college column (else the enrolment / staff column through its college);
* ``department`` → the department column (else the enrolment / staff column through its department);
* ``self`` → own rows: enrolment ids (self / wards / mentees / advisees / students of own offerings), own offerings,
  own staff id, own hostels — whichever columns the query has;
* anything unmappable → ``FALSE`` (a chart can never widen visibility).

Requested dims (``college_id``, ``department_id``, ``program_id``, ``batch_id``, ``term_id``) are ANDed on top.
"""

import uuid
from typing import Any

__all__ = ["scope_sql"]


def _uuid(v: Any) -> uuid.UUID | None:
    if v in (None, ""):
        return None
    try:
        return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))
    except (TypeError, ValueError):
        return None


def scope_sql(ctx: Any, *, alias: str, cols: dict[str, str | None]) -> tuple[str, dict[str, Any]]:
    a = f"{alias}." if alias else ""

    def c(name: str) -> str | None:
        col = cols.get(name)
        return f"{a}{col}" if col else None

    s = ctx.scope
    binds: dict[str, Any] = {"_inst": ctx.institution_id}
    parts = [f"{c('institution')} = :_inst"]
    if s.level == "all":
        pass
    elif s.level == "college":
        binds["_colleges"] = list(s.college_ids)
        if c("college"):
            parts.append(f"{c('college')} = ANY(:_colleges)")
        elif c("enrollment"):
            parts.append(
                f"{c('enrollment')} IN (SELECT id FROM student_program_enrollments WHERE college_id = ANY(:_colleges))"
            )
        elif c("staff"):
            parts.append(f"{c('staff')} IN (SELECT id FROM staff WHERE college_id = ANY(:_colleges))")
        else:
            parts.append("FALSE")
    elif s.level == "department":
        binds["_depts"] = list(s.department_ids)
        if c("department"):
            parts.append(f"{c('department')} = ANY(:_depts)")
        elif c("enrollment"):
            parts.append(
                f"{c('enrollment')} IN (SELECT id FROM student_program_enrollments WHERE department_id = ANY(:_depts))"
            )
        elif c("staff"):
            parts.append(f"{c('staff')} IN (SELECT id FROM staff WHERE department_id = ANY(:_depts))")
        else:
            parts.append("FALSE")
    elif s.level == "self":
        own: list[str] = []
        if c("enrollment") and s.enrollment_ids:
            binds["_enrols"] = list(s.enrollment_ids)
            own.append(f"{c('enrollment')} = ANY(:_enrols)")
        if c("offering") and s.offering_ids:
            binds["_offerings"] = list(s.offering_ids)
            own.append(f"{c('offering')} = ANY(:_offerings)")
        if c("staff") and s.staff_id:
            binds["_staff"] = s.staff_id
            own.append(f"{c('staff')} = :_staff")
        if c("hostel") and s.hostel_ids:
            binds["_hostels"] = list(s.hostel_ids)
            own.append(f"{c('hostel')} = ANY(:_hostels)")
        parts.append(f"({' OR '.join(own)})" if own else "FALSE")
    else:
        parts.append("FALSE")

    dims = ctx.dims or {}
    for dim, col in (
        ("college_id", "college"),
        ("department_id", "department"),
        ("program_id", "program"),
        ("batch_id", "batch"),
        ("term_id", "term"),
    ):
        v = _uuid(dims.get(dim))
        if v is not None and c(col):
            binds[f"_d_{dim}"] = v
            parts.append(f"{c(col)} = :_d_{dim}")
    return " AND ".join(parts), binds
