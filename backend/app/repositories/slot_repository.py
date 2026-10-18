"""Time slots (slot groups) — Prompts/10 §10.5 ``slot_repository.py``. Institution-wide read; a slot group is the
ordered list of a college's slots sharing ``slot_group``."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.timetable import TimeSlot


class SlotRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID):
        self.db = db
        self.inst = institution_id

    async def group(
        self, college_id: uuid.UUID | None, slot_group: str | None = None, *, active_only: bool = True
    ) -> list[TimeSlot]:
        stmt = select(TimeSlot).where(TimeSlot.institution_id == self.inst)
        if college_id:
            stmt = stmt.where(TimeSlot.college_id == college_id)
        if slot_group:
            stmt = stmt.where(TimeSlot.slot_group == slot_group)
        if active_only:
            stmt = stmt.where(TimeSlot.is_active.is_(True))
        stmt = stmt.order_by(TimeSlot.college_id, TimeSlot.slot_group, TimeSlot.sequence)
        return list((await self.db.execute(stmt)).scalars().all())

    async def groups(self, college_id: uuid.UUID | None) -> list[str]:
        stmt = select(TimeSlot.slot_group).where(TimeSlot.institution_id == self.inst).distinct()
        if college_id:
            stmt = stmt.where(TimeSlot.college_id == college_id)
        return sorted((await self.db.execute(stmt)).scalars().all())

    async def get_one(self, slot_id: uuid.UUID) -> TimeSlot:
        row = (
            await self.db.execute(select(TimeSlot).where(TimeSlot.id == slot_id, TimeSlot.institution_id == self.inst))
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Time slot not found", {"field": "time_slot_id"})
        return row

    async def rows(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, TimeSlot]:
        wanted = [i for i in set(ids) if i]
        if not wanted:
            return {}
        res = await self.db.execute(select(TimeSlot).where(TimeSlot.id.in_(wanted)))
        return {s.id: s for s in res.scalars().all()}

    async def span(self, start: TimeSlot, slot_span: int) -> list[TimeSlot]:
        """The ``slot_span`` consecutive teaching slots starting at ``start`` (breaks / lunch interrupt a span)."""
        group = await self.group(start.college_id, start.slot_group)
        idx = next((i for i, s in enumerate(group) if s.id == start.id), None)
        if idx is None:
            return [start]
        out = group[idx : idx + slot_span]
        if len(out) < slot_span or any(s.slot_type in ("break", "lunch") for s in out[1:]):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"A span of {slot_span} slot(s) from {start.name} runs past the day or across a break",
                {"field": "slot_span"},
            )
        return out
