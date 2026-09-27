"""Number sequences — Prompts/03 §03.6 ``sequence_service`` (feature ``institution.number_sequences_custom``).

Business rules
1. CRUD: ``scope_key`` unique per (institution, college) → 409; the pattern may only use the known tokens and must
   contain ``{seq}`` / ``{seq:N}`` (422). College sequences need the college in the caller's write scope.
2. ``preview`` renders the next ``count`` values **without consuming** them (context: institution-local today, the
   row's college code, optional ``prog_code`` / ``term``).
3. ``next(scope_key, college_id)`` reserves a value atomically (``UPDATE … RETURNING`` inside the caller's
   transaction — concurrent callers serialise on the row lock, a rollback gives the value back).
4. Reset policies: ``yearly`` sequences restart at 1 on the start date of the scope's current academic year (1 January
   without one), ``per_term`` on the current term's start date — Beat ``sequences.reset`` (daily 00:05) applies them.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.tenancy import today_for
from app.models.platform import NumberSequence
from app.repositories.college_repository import CollegeRepository
from app.repositories.institution_repository import InstitutionRepository
from app.repositories.sequence_repository import SequenceRepository, date_context, render, validate_pattern
from app.schemas.institution import (
    NumberSequenceCreate,
    NumberSequenceNext,
    NumberSequencePreview,
    NumberSequencePreviewRequest,
    NumberSequenceResponse,
    NumberSequenceUpdate,
)
from app.services.institution.context import check_college_writable, structure_visibility, tenant_id
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta


def _snap(s: NumberSequence) -> dict[str, Any]:
    return {
        "scope_key": s.scope_key,
        "pattern": s.pattern,
        "next_value": s.next_value,
        "padding": s.padding,
        "reset_policy": s.reset_policy,
        "college_id": str(s.college_id) if s.college_id else None,
    }


class SequenceService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None, institution_id: Any = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = uuid.UUID(str(institution_id)) if institution_id else tenant_id(principal, request)
        self.repo = SequenceRepository(db, principal, self.inst)

    async def _context(self, s: NumberSequence, extra: dict[str, Any] | None = None) -> dict[str, str]:
        institution = await InstitutionRepository(self.db).get(self.inst)
        ctx: dict[str, str] = date_context(today_for(institution))
        if s.college_id:
            codes = await CollegeRepository(self.db, self.principal, self.inst).codes([s.college_id])
            ctx["college_code"] = codes.get(s.college_id, "")
        for k, v in (extra or {}).items():
            if v:
                ctx[k] = str(v)
        return ctx

    async def _response(self, s: NumberSequence) -> NumberSequenceResponse:
        r = NumberSequenceResponse.model_validate(s)
        r.sample = render(s.pattern, await self._context(s), s.next_value, s.padding)
        return r

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, college_id: uuid.UUID | None, q: str | None
    ) -> tuple[list[NumberSequenceResponse], PaginationMeta, VisibilityMeta]:
        if not params.sort:
            params = params.model_copy(update={"sort": "scope_key"})
        rows, pagination = await self.repo.paginate(self.repo.filtered(college_id, q), params)
        return [await self._response(s) for s in rows], pagination, structure_visibility(self.principal)

    async def create(self, body: NumberSequenceCreate) -> NumberSequenceResponse:
        check_college_writable(self.principal, body.college_id)
        validate_pattern(body.pattern)
        if body.college_id is not None:
            await CollegeRepository(self.db, self.principal, self.inst).get_readable(body.college_id)
        if await self.repo.by_scope(self.inst, body.scope_key, body.college_id):
            raise APIError(
                409, ErrorCode.CONFLICT, f"Sequence {body.scope_key!r} already exists", {"field": "scope_key"}
            )
        s = await self.repo.create(
            institution_id=self.inst,
            college_id=body.college_id,
            scope_key=body.scope_key,
            pattern=body.pattern,
            next_value=body.next_value,
            padding=body.padding,
            reset_policy=body.reset_policy.value,
        )
        await self._audit("create", s, None, _snap(s))
        return await self._response(s)

    async def update(self, seq_id: uuid.UUID, body: NumberSequenceUpdate) -> NumberSequenceResponse:
        s = await self.repo.get_one(seq_id, for_update=True)
        check_college_writable(self.principal, s.college_id)
        values = {k: (v.value if hasattr(v, "value") else v) for k, v in body.model_dump(exclude_unset=True).items()}
        if "pattern" in values:
            validate_pattern(values["pattern"])
        old = _snap(s)
        await self.repo.update(s, **values)
        await self._audit("update", s, old, _snap(s))
        return await self._response(s)

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def preview(self, seq_id: uuid.UUID, body: NumberSequencePreviewRequest) -> NumberSequencePreview:
        s = await self.repo.get_one(seq_id)
        ctx = await self._context(s, {"prog_code": body.prog_code, "term": body.term})
        values = [render(s.pattern, ctx, s.next_value + i, s.padding) for i in range(body.count)]
        return NumberSequencePreview(scope_key=s.scope_key, pattern=s.pattern, values=values, tokens=ctx)

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def next(
        self, scope_key: str, college_id: uuid.UUID | None = None, extra: dict[str, Any] | None = None
    ) -> NumberSequenceNext:
        value, s = await self.repo.next_value(self.inst, scope_key, college_id)
        rendered = render(s.pattern, await self._context(s, extra), value, s.padding)
        return NumberSequenceNext(scope_key=scope_key, value=value, rendered=rendered)

    async def next_by_id(self, seq_id: uuid.UUID) -> NumberSequenceNext:
        s = await self.repo.get_one(seq_id)
        return await self.next(s.scope_key, s.college_id)

    async def _audit(
        self, action: str, s: NumberSequence, old: dict[str, Any] | None, new: dict[str, Any] | None
    ) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="settings",
            action=action,
            record_type="number_sequence",
            record_id=s.id,
            old=old,
            new=new,
            request=self.request,
        )


# ---- rule 4 (Beat, platform session) ---------------------------------------------------------------------------------
async def reset_due_sequences(db: AsyncSession, today_by_institution: dict[uuid.UUID, date]) -> int:
    """Restart ``yearly`` / ``per_term`` sequences whose period starts today (institution-local dates)."""
    from sqlalchemy import text

    repo = SequenceRepository(db)
    due: list[uuid.UUID] = []
    for policy, table in (("yearly", "academic_years"), ("per_term", "academic_terms")):
        for s in await repo.with_policy(policy):
            today = today_by_institution.get(s.institution_id)
            if today is None:
                continue
            row = (
                await db.execute(
                    text(
                        f"SELECT start_date FROM {table} WHERE institution_id = :i AND is_current AND deleted_at IS NULL "  # noqa: S608 - table is a literal
                        "AND (college_id IS NOT DISTINCT FROM :c OR college_id IS NULL) "
                        "ORDER BY college_id NULLS LAST LIMIT 1"
                    ),
                    {"i": s.institution_id, "c": s.college_id},
                )
            ).first()
            start = row[0] if row else (date(today.year, 1, 1) if policy == "yearly" else None)
            if start == today and s.next_value != 1:
                due.append(s.id)
    return await repo.reset(due)
