"""Merit lists and entries — Prompts/08 §08.5 ``merit_repository.py``."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.admissions import Applicant, MeritList, MeritListEntry


class MeritRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID):
        self.db, self.inst = db, institution_id

    async def lists(self, cycle_id: uuid.UUID | None = None, status: str | None = None) -> Sequence[MeritList]:
        stmt = select(MeritList).where(MeritList.institution_id == self.inst)
        if cycle_id is not None:
            stmt = stmt.where(MeritList.cycle_id == cycle_id)
        if status is not None:
            stmt = stmt.where(MeritList.status == status)
        return (await self.db.execute(stmt.order_by(MeritList.created_at.desc()))).scalars().all()

    async def get(self, list_id: uuid.UUID, *, for_update: bool = False) -> MeritList:
        stmt = select(MeritList).where(MeritList.id == list_id, MeritList.institution_id == self.inst)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Merit list not found")
        return row

    async def same_scope(self, ml: MeritList) -> Sequence[MeritList]:
        """Older non-superseded lists with the same (cycle, programme, college, quota, category) scope."""
        stmt = select(MeritList).where(
            MeritList.cycle_id == ml.cycle_id,
            MeritList.id != ml.id,
            MeritList.status != "superseded",
        )
        for col, value in (
            (MeritList.program_id, ml.program_id),
            (MeritList.college_id, ml.college_id),
            (MeritList.quota, ml.quota),
            (MeritList.category, ml.category),
        ):
            stmt = stmt.where(col.is_(None) if value is None else col == value)
        return (await self.db.execute(stmt.with_for_update())).scalars().all()

    async def entries(self, list_id: uuid.UUID) -> Sequence[tuple[MeritListEntry, Applicant]]:
        stmt = (
            select(MeritListEntry, Applicant)
            .join(Applicant, Applicant.id == MeritListEntry.applicant_id)
            .where(MeritListEntry.merit_list_id == list_id)
            .order_by(MeritListEntry.rank)
        )
        return [(e, a) for e, a in (await self.db.execute(stmt)).all()]

    async def entry_counts(self, list_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not list_ids:
            return {}
        stmt = (
            select(MeritListEntry.merit_list_id, func.count())
            .where(MeritListEntry.merit_list_id.in_(list(list_ids)))
            .group_by(MeritListEntry.merit_list_id)
        )
        return {k: int(v) for k, v in (await self.db.execute(stmt)).all()}

    async def ranks_for_cycle(self, cycle_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Overall rank per applicant from the cycle's newest cycle-wide list (published preferred, else draft)."""
        lists = [m for m in await self.lists(cycle_id) if m.status != "superseded" and m.program_id is None]
        if not lists:
            lists = [m for m in await self.lists(cycle_id) if m.status != "superseded"]
        if not lists:
            return {}
        lists.sort(key=lambda m: (m.status != "published", -(m.created_at.timestamp() if m.created_at else 0)))
        rows: Any = (
            await self.db.execute(
                select(MeritListEntry.applicant_id, MeritListEntry.rank).where(
                    MeritListEntry.merit_list_id == lists[0].id
                )
            )
        ).all()
        return {a: int(r) for a, r in rows}
