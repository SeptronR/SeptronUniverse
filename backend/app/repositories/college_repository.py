"""Colleges — Prompts/03 §03.5 ``college_repository`` (``module="colleges"``).

Reads are institution-wide (every member holds ``institutions:view``); the ``college`` scope tab narrows the list to
the principal's college assignments. Writes go through ``get_writable`` which hides colleges outside a college-scoped
admin's assignments (404, never 403 — Prompts/03 §03.11 step 3).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.platform import College, Department
from app.repositories.base import BaseRepository
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


class CollegeRepository(BaseRepository[College]):
    model = College
    module = "colleges"

    def filtered(
        self,
        *,
        q: str | None = None,
        college_type: str | None = None,
        is_exam_centre: bool | None = None,
        college_ids: Sequence[uuid.UUID] | None = None,
        include_inactive: bool = False,
    ) -> Select[tuple[College]]:
        stmt = self._base()
        if not include_inactive:
            stmt = stmt.where(College.is_active.is_(True))
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(College.name).like(like), func.lower(College.code).like(like)))
        if college_type:
            stmt = stmt.where(College.college_type == college_type)
        if is_exam_centre is not None:
            stmt = stmt.where(College.is_exam_centre.is_(is_exam_centre))
        if college_ids is not None:
            stmt = stmt.where(College.id.in_(college_ids))
        return stmt

    async def list_filtered(self, params: PageParams, **filters: Any) -> tuple[Sequence[College], PaginationMeta]:
        if not params.sort:
            params = params.model_copy(update={"sort": "code"})
        return await self.paginate(self.filtered(**filters), params)

    async def get_readable(self, college_id: uuid.UUID) -> College:
        obj = (await self.db.execute(self._base().where(College.id == college_id))).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "College not found")
        return obj

    async def get_writable(
        self, college_id: uuid.UUID, writable_ids: Sequence[uuid.UUID] | None, *, for_update: bool = True
    ) -> College:
        """404 when the college is outside the principal's writable set (``None`` = every college)."""
        stmt = self._base().where(College.id == college_id)
        if writable_ids is not None:
            stmt = stmt.where(College.id.in_(writable_ids))
        if for_update:
            stmt = stmt.with_for_update()
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "College not found")
        return obj

    async def by_code(self, institution_id: uuid.UUID, code: str) -> College | None:
        """Includes soft-deleted rows: UNIQUE (institution_id, code) still holds for them."""
        return (
            await self.db.execute(
                select(College).where(
                    College.institution_id == institution_id, func.upper(College.code) == code.upper()
                )
            )
        ).scalar_one_or_none()

    async def count_active(self, institution_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(College)
                    .where(College.institution_id == institution_id, College.deleted_at.is_(None))
                )
            ).scalar_one()
        )

    async def mains(self, institution_id: uuid.UUID, exclude: uuid.UUID | None = None) -> Sequence[College]:
        stmt = select(College).where(
            College.institution_id == institution_id, College.is_main.is_(True), College.deleted_at.is_(None)
        )
        if exclude is not None:
            stmt = stmt.where(College.id != exclude)
        return (await self.db.execute(stmt.with_for_update())).scalars().all()

    async def department_counts(self, college_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not college_ids:
            return {}
        rows = (
            await self.db.execute(
                select(Department.college_id, func.count())
                .where(Department.college_id.in_(college_ids), Department.deleted_at.is_(None))
                .group_by(Department.college_id)
            )
        ).all()
        return {cid: int(n) for cid, n in rows}

    async def codes(self, college_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not college_ids:
            return {}
        rows = (await self.db.execute(select(College.id, College.code).where(College.id.in_(college_ids)))).all()
        return {row[0]: row[1] for row in rows}
