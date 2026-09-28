"""Batches and sections — Prompts/05 §05.5 ``batch_repository`` (``module="batches"``; ``promote`` support: the
active batches of an institution with their programme's term count)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, delete, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.academic import Batch, BatchSection, Program
from app.repositories.base import BaseRepository


class BatchRepository(BaseRepository[Batch]):
    model = Batch
    module = "batches"

    def filtered(
        self,
        *,
        college_ids: Sequence[uuid.UUID] | None = None,
        program_id: uuid.UUID | None = None,
        department_ids: Sequence[uuid.UUID] | None = None,
        admission_year: int | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> Select[tuple[Batch]]:
        stmt = self._base()
        if college_ids is not None:
            stmt = stmt.where(Batch.college_id.in_(list(college_ids)))
        if program_id:
            stmt = stmt.where(Batch.program_id == program_id)
        if department_ids is not None:
            stmt = stmt.where(
                Batch.program_id.in_(select(Program.id).where(Program.department_id.in_(list(department_ids))))
            )
        if admission_year:
            stmt = stmt.where(Batch.admission_year == admission_year)
        if status:
            stmt = stmt.where(Batch.status == status)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(func.lower(Batch.code).like(like), func.lower(func.coalesce(Batch.name, "")).like(like))
            )
        return stmt

    async def get_batch(self, batch_id: uuid.UUID) -> Batch:
        obj = (await self.db.execute(self._base().where(Batch.id == batch_id))).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Batch not found")
        return obj

    async def find(
        self, institution_id: uuid.UUID, college_id: uuid.UUID, program_id: uuid.UUID, year: int, entry_type: str
    ) -> Batch | None:
        return (
            await self.db.execute(
                select(Batch).where(
                    Batch.institution_id == institution_id,
                    Batch.college_id == college_id,
                    Batch.program_id == program_id,
                    Batch.admission_year == year,
                    Batch.entry_type == entry_type,
                    Batch.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def sections(self, batch_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[BatchSection]]:
        out: dict[uuid.UUID, list[BatchSection]] = {b: [] for b in batch_ids}
        if not batch_ids:
            return out
        rows = (
            (
                await self.db.execute(
                    select(BatchSection).where(BatchSection.batch_id.in_(list(batch_ids))).order_by(BatchSection.name)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            out.setdefault(r.batch_id, []).append(r)
        return out

    async def section(self, batch_id: uuid.UUID, section_id: uuid.UUID) -> BatchSection:
        obj = (
            await self.db.execute(
                select(BatchSection).where(BatchSection.id == section_id, BatchSection.batch_id == batch_id)
            )
        ).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Section not found")
        return obj

    async def delete_sections(self, ids: Sequence[uuid.UUID]) -> None:
        if ids:
            await self.db.execute(delete(BatchSection).where(BatchSection.id.in_(list(ids))))

    async def promotable(self, institution_id: uuid.UUID) -> Sequence[tuple[Batch, int]]:
        """Active batches with their programme's ``total_terms`` (rollover proposal)."""
        rows = (
            await self.db.execute(
                select(Batch, Program.total_terms)
                .join(Program, Program.id == Batch.program_id)
                .where(Batch.institution_id == institution_id, Batch.status == "active", Batch.deleted_at.is_(None))
            )
        ).all()
        return [(r[0], int(r[1])) for r in rows]
