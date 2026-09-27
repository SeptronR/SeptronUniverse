"""Colleges — Prompts/03 §03.6 ``college_service``.

Business rules
1. Reads are institution-wide (``institutions:view``); college-scoped users get the ``college`` tab as their default.
2. Create: only institution-scoped admins (a college admin cannot add colleges — 403); ``code`` unique per institution
   (soft-deleted rows included, the UNIQUE constraint still covers them) → ``409 CONFLICT``; a second college needs
   ``institution.multi_college`` (403 FEATURE_DISABLED); ``study_centre`` colleges are allowed (their use is limited to
   distance/online programmes by Phase 05 — ``programs.mode``).
3. ``is_main``: exactly one main college in a non-university institution — the first college of such an institution is
   main automatically, setting another as main moves the flag (the previous main is cleared in the same transaction),
   the main college cannot be un-flagged or deleted while it is the only one (409 RULE_VIOLATION).
4. Update/delete look the college up through the caller's college write scope (``college_admin`` @college B editing
   college A → 404). Delete is a soft delete and is refused while departments exist (409).
5. Every change is audited with the old/new values; events ``college.created`` / ``college.updated``.
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.institution.visibility  # noqa: F401  (registers the Phase 03 visibility modules)
from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.enums.institution import InstitutionType
from app.models.platform import College
from app.repositories.college_repository import CollegeRepository
from app.repositories.institution_repository import InstitutionRepository
from app.schemas.institution import CollegeCreate, CollegeResponse, CollegeUpdate
from app.services.institution.context import (
    has_institution_scope,
    scope_college_filter,
    structure_visibility,
    tenant_id,
    writable_college_ids,
)
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

AUDITED = (
    "code",
    "name",
    "slug",
    "college_type",
    "affiliation_number",
    "principal_staff_id",
    "exam_centre_code",
    "is_exam_centre",
    "aishe_code",
    "aicte_pid",
    "gstin",
    "timezone",
    "is_main",
    "is_active",
)


def snapshot(c: College) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in ((k, getattr(c, k)) for k in AUDITED)}


class CollegeService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = tenant_id(principal, request)
        self.repo = CollegeRepository(db, principal, self.inst)

    def _response(self, c: College, dept_counts: dict[uuid.UUID, int] | None = None) -> CollegeResponse:
        writable = writable_college_ids(self.principal)
        resp = CollegeResponse.model_validate(c)
        resp.department_count = (dept_counts or {}).get(c.id, 0)
        resp.can_edit = self.principal.has("colleges", "update") and (writable is None or c.id in writable)
        return resp

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def list_page(
        self,
        params: PageParams,
        scope: str | None,
        q: str | None,
        college_type: str | None,
        is_exam_centre: bool | None,
        include_inactive: bool = False,
    ) -> tuple[list[CollegeResponse], PaginationMeta, VisibilityMeta]:
        rows, pagination = await self.repo.list_filtered(
            params,
            q=q,
            college_type=college_type,
            is_exam_centre=is_exam_centre,
            college_ids=scope_college_filter(self.principal, scope),
            include_inactive=include_inactive,
        )
        counts = await self.repo.department_counts([c.id for c in rows])
        return [self._response(c, counts) for c in rows], pagination, structure_visibility(self.principal)

    async def get(self, college_id: uuid.UUID) -> CollegeResponse:
        c = await self.repo.get_readable(college_id)
        return self._response(c, await self.repo.department_counts([c.id]))

    # ---- rules 2-3 ------------------------------------------------------------------------------------------------
    async def create(self, body: CollegeCreate) -> CollegeResponse:
        if not has_institution_scope(self.principal):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only institution-level admins can add colleges")
        institution = await InstitutionRepository(self.db).get(self.inst, for_update=True)
        if institution is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")
        if await self.repo.by_code(self.inst, body.code):
            raise APIError(409, ErrorCode.CONFLICT, f"College code {body.code!r} already exists", {"field": "code"})
        existing = await self.repo.count_active(self.inst)
        if existing >= 1 and not await is_enabled(self.inst, "institution.multi_college"):
            raise APIError(
                403,
                ErrorCode.FEATURE_DISABLED,
                "More than one college needs the 'institution.multi_college' feature",
                {"feature": "institution.multi_college"},
            )
        is_main = body.is_main or (existing == 0 and institution.institution_type != InstitutionType.UNIVERSITY)
        if is_main:
            for other in await self.repo.mains(self.inst):
                other.is_main = False
        values = body.model_dump(exclude={"is_main"})
        values["code"] = body.code.upper()
        c = await self.repo.create(institution_id=self.inst, is_main=is_main, created_by=self.principal.id, **values)
        await self._audit("create", c, None, snapshot(c))
        await self._emit("college.created", c)
        return self._response(c)

    async def update(self, college_id: uuid.UUID, body: CollegeUpdate) -> CollegeResponse:
        c = await self.repo.get_writable(college_id, writable_college_ids(self.principal))
        old = snapshot(c)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if "is_main" in values:
            await self._apply_main(c, bool(values.pop("is_main")))
        await self.repo.update(c, expected_version=body.version, **values)
        await self._audit("update", c, old, snapshot(c))
        await self._emit("college.updated", c)
        return self._response(c, await self.repo.department_counts([c.id]))

    async def _apply_main(self, c: College, wanted: bool) -> None:
        if wanted == c.is_main:
            return
        if not has_institution_scope(self.principal):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Only institution-level admins can change the main college"
            )
        if wanted:
            for other in await self.repo.mains(self.inst, exclude=c.id):
                other.is_main = False
            c.is_main = True
            return
        institution = await InstitutionRepository(self.db).get(self.inst)
        if institution is not None and institution.institution_type != InstitutionType.UNIVERSITY:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "A non-university institution needs exactly one main college; mark another college as main instead",
                {"field": "is_main"},
            )
        c.is_main = False

    async def delete(self, college_id: uuid.UUID) -> None:
        c = await self.repo.get_writable(college_id, writable_college_ids(self.principal))
        if (await self.repo.department_counts([c.id])).get(c.id):
            raise APIError(409, ErrorCode.RULE_VIOLATION, "The college still has departments")
        if c.is_main and await self.repo.count_active(self.inst) > 1:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Mark another college as main before deleting this one")
        old = snapshot(c)
        await self.repo.soft_delete(c, self.principal.id)
        await self._audit("delete", c, old, None)
        await self._emit("college.updated", c, deleted=True)

    async def set_logo(self, college_id: uuid.UUID, url: str) -> CollegeResponse:
        c = await self.repo.get_writable(college_id, writable_college_ids(self.principal))
        old = {"logo_url": c.logo_url}
        c.logo_url = url
        await self.db.flush()
        await self._audit("update", c, old, {"logo_url": url})
        return self._response(c)

    # ---- rule 5 ---------------------------------------------------------------------------------------------------
    async def _audit(self, action: str, c: College, old: dict[str, Any] | None, new: dict[str, Any] | None) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="colleges",
            action=action,
            record_type="college",
            record_id=c.id,
            old=old,
            new=new,
            request=self.request,
        )

    async def _emit(self, event_type: str, c: College, deleted: bool = False) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=event_type,
            payload={"college_id": str(c.id), "code": c.code, "name": c.name, "deleted": deleted},
            aggregate_type="college",
            aggregate_id=c.id,
            actor_user_id=self.principal.id,
        )
