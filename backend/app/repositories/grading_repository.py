"""Grading scales — Prompts/05 §05.5 ``grading_repository`` (configuration only; read institution-wide, written with
``exams:configure``)."""

import uuid

from sqlalchemy import Select, func, or_, select, update

from app.core.errors import APIError, ErrorCode
from app.models.academic import GradingScale
from app.repositories.base import BaseRepository


class GradingRepository(BaseRepository[GradingScale]):
    model = GradingScale
    module = "grading"

    def filtered(self, regulation_id: uuid.UUID | None = None, q: str | None = None) -> Select[tuple[GradingScale]]:
        stmt = self._base()
        if regulation_id:
            stmt = stmt.where(or_(GradingScale.regulation_id == regulation_id, GradingScale.regulation_id.is_(None)))
        if q:
            stmt = stmt.where(func.lower(GradingScale.name).like(f"%{q.lower()}%"))
        return stmt

    async def get_scale(self, scale_id: uuid.UUID) -> GradingScale:
        obj = (await self.db.execute(self._base().where(GradingScale.id == scale_id))).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Grading scale not found")
        return obj

    async def by_name(self, institution_id: uuid.UUID, name: str) -> GradingScale | None:
        return (
            await self.db.execute(
                select(GradingScale).where(
                    GradingScale.institution_id == institution_id,
                    func.lower(GradingScale.name) == name.lower(),
                    GradingScale.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def default_scale(self, institution_id: uuid.UUID) -> GradingScale | None:
        return (
            (
                await self.db.execute(
                    self._base()
                    .where(GradingScale.institution_id == institution_id, GradingScale.regulation_id.is_(None))
                    .order_by(GradingScale.is_default.desc(), GradingScale.created_at)
                )
            )
            .scalars()
            .first()
        )

    async def clear_default(self, institution_id: uuid.UUID, except_id: uuid.UUID) -> None:
        await self.db.execute(
            update(GradingScale)
            .where(GradingScale.institution_id == institution_id, GradingScale.id != except_id)
            .values(is_default=False)
        )
