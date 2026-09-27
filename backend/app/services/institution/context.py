"""Tenant and scope resolution for the Phase 03 services (Prompts/03 "Visibility rules").

* ``tenant_id`` — the principal's institution, or ``X-Institution-Id`` for the super admin (422 without one);
* ``writable_college_ids`` — ``None`` (every college) for institution-scoped principals and the super admin, else the
  college ids of the principal's ``college`` assignments (``college_admin`` @college edits only its college);
* ``structure_visibility`` — ``meta.visibility`` of the institution-wide readable lists: tabs ``all`` (+ ``college``
  when the principal holds college scopes, which is then the default filter).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import Request

from app.core.errors import APIError, ErrorCode
from app.utils.response import VisibilityMeta


def tenant_id(principal: Any, request: Request | None) -> uuid.UUID:
    inst = getattr(principal, "institution_id", None)
    if inst is None and request is not None and getattr(principal, "is_super_admin", False):
        raw = getattr(request.state, "institution_id", None)
        inst = uuid.UUID(str(raw)) if raw else None
    if inst is None:
        raise APIError(422, ErrorCode.VALIDATION, "An institution context is required (X-Institution-Id)")
    return uuid.UUID(str(inst))


def college_scope_ids(principal: Any) -> list[uuid.UUID]:
    return [sid for st, sid in getattr(principal, "scopes", []) if st == "college" and sid is not None]


def has_institution_scope(principal: Any) -> bool:
    if getattr(principal, "is_super_admin", False):
        return True
    return any(st == "institution" for st, _ in getattr(principal, "scopes", []))


def writable_college_ids(principal: Any) -> Sequence[uuid.UUID] | None:
    if has_institution_scope(principal):
        return None
    return college_scope_ids(principal)


def check_college_writable(principal: Any, college_id: uuid.UUID | None) -> None:
    """Institution-wide rows (``college_id`` NULL) need an institution scope; college rows the college in scope."""
    writable = writable_college_ids(principal)
    if writable is None:
        return
    if college_id is None or college_id not in writable:
        raise APIError(
            403,
            ErrorCode.PERMISSION_DENIED,
            "Outside your college scope",
            {"reason": "college_scope", "college_id": str(college_id) if college_id else None},
        )


def structure_visibility(principal: Any) -> VisibilityMeta:
    colleges = college_scope_ids(principal)
    scopes = ["college", "all"] if colleges else ["all"]
    default = "college" if colleges and not has_institution_scope(principal) else "all"
    return VisibilityMeta(self=False, scopes=scopes, default=default, pii=False)


def scope_college_filter(principal: Any, scope: str | None) -> list[uuid.UUID] | None:
    """The ``college`` tab narrows a list to the principal's colleges; ``all`` (or no college scopes) does not."""
    effective = scope or structure_visibility(principal).default
    if effective == "college":
        ids = college_scope_ids(principal)
        return ids or None
    return None
