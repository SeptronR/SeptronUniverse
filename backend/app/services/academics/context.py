"""Unit scopes of the Phase 05 writes and the list visibility (Prompts/05 "Visibility rules").

Reads of programmes, regulations, courses, baskets, structures and batches are **institution-wide** for every staff
member (``programs:view`` … are part of the staff self-service grants). Writes are narrowed to the caller's units:

* ``writable_department_ids`` — ``None`` (everything) for institution-scoped principals and the super admin, else
  the departments of the caller's ``department`` assignments, of the faculties of its ``faculty`` assignments and of
  the colleges of its ``college`` assignments (``hod`` @department drafts the courses of its own department,
  ``college_admin`` @college edits its college's programmes). An empty set means "no unit" → 403 on create, 404 on
  the write lookup (no existence leak — same as Phase 03);
* ``check_regulation_writable`` — institution-wide regulations need an institution scope, college regulations the
  college in scope (``college_admin`` @college for college-level regulations);
* ``academic_visibility`` — ``meta.visibility``: tabs ``all`` (+ ``department`` / ``college`` when the caller holds
  those scopes; the narrowest one is then the default, like the Phase 03 ``college`` tab).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.platform import Department
from app.services.institution.context import college_scope_ids, has_institution_scope
from app.utils.response import VisibilityMeta


def _scope_ids(principal: Any, scope_type: str) -> list[uuid.UUID]:
    return [sid for st, sid in getattr(principal, "scopes", []) if st == scope_type and sid is not None]


async def writable_department_ids(db: AsyncSession, principal: Any) -> set[uuid.UUID] | None:
    if has_institution_scope(principal):
        return None
    ids = set(_scope_ids(principal, "department"))
    faculties = _scope_ids(principal, "faculty")
    colleges = college_scope_ids(principal)
    if faculties or colleges:
        stmt = select(Department.id).where(Department.deleted_at.is_(None))
        conds = []
        if faculties:
            conds.append(Department.faculty_id.in_(faculties))
        if colleges:
            conds.append(Department.college_id.in_(colleges))
        ids |= set((await db.execute(stmt.where(or_(*conds)))).scalars().all())
    return ids


async def writable_college_ids_for_units(db: AsyncSession, principal: Any) -> set[uuid.UUID] | None:
    """Colleges the caller may write in (a department/faculty scope implies its college)."""
    if has_institution_scope(principal):
        return None
    colleges = set(college_scope_ids(principal))
    depts = await writable_department_ids(db, principal) or set()
    if depts:
        rows = (await db.execute(select(Department.college_id).where(Department.id.in_(list(depts))))).scalars()
        colleges |= set(rows)
    return colleges


def check_department_writable(writable: set[uuid.UUID] | None, department_id: uuid.UUID, *, create: bool) -> None:
    if writable is None or department_id in writable:
        return
    if create:
        raise APIError(
            403,
            ErrorCode.PERMISSION_DENIED,
            "Outside your department scope",
            {"reason": "department_scope", "department_id": str(department_id)},
        )
    raise APIError(404, ErrorCode.NOT_FOUND, "Record not found")


def check_regulation_writable(principal: Any, college_id: uuid.UUID | None, *, create: bool = False) -> None:
    if has_institution_scope(principal):
        return
    if college_id is not None and college_id in college_scope_ids(principal):
        return
    if create or college_id is None:
        raise APIError(
            403,
            ErrorCode.PERMISSION_DENIED,
            "Institution-wide regulations need an institution scope; college regulations your college scope",
            {"reason": "college_scope", "college_id": str(college_id) if college_id else None},
        )
    raise APIError(404, ErrorCode.NOT_FOUND, "Regulation not found")


def academic_visibility(principal: Any) -> VisibilityMeta:
    depts = _scope_ids(principal, "department")
    colleges = college_scope_ids(principal)
    scopes = (["department"] if depts else []) + (["college"] if colleges else []) + ["all"]
    default = "all"
    if not has_institution_scope(principal):
        default = "department" if depts else ("college" if colleges else "all")
    return VisibilityMeta(self=False, scopes=scopes, default=default, pii=False)


def scope_filters(principal: Any, scope: str | None) -> tuple[Sequence[uuid.UUID] | None, Sequence[uuid.UUID] | None]:
    """(department_ids, college_ids) narrowing of a list for the requested tab (``all`` / none → no narrowing)."""
    effective = scope or academic_visibility(principal).default
    if effective == "department":
        ids = _scope_ids(principal, "department")
        return (ids or None), None
    if effective == "college":
        ids = college_scope_ids(principal)
        return None, (ids or None)
    return None, None
