"""Offering waitlists — Prompts/09 §09.5 ``waitlist_repository.py``.

Positions are FCFS per offering (``max(position) + 1``); ``next_waiting`` returns the first ``waiting`` row locked
``FOR UPDATE SKIP LOCKED`` (the offering row is already locked by the caller); ``expired_offers`` feeds the Beat
``waitlist.expire``.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.registration import OfferingWaitlist


class WaitlistRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID | None = None):
        self.db, self.inst = db, institution_id

    def _base(self) -> Any:
        stmt = select(OfferingWaitlist)
        if self.inst is not None:
            stmt = stmt.where(OfferingWaitlist.institution_id == self.inst)
        return stmt

    async def get(self, waitlist_id: uuid.UUID, *, for_update: bool = False) -> OfferingWaitlist:
        stmt = self._base().where(OfferingWaitlist.id == waitlist_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Waitlist entry not found")
        return row

    async def for_student(self, offering_id: uuid.UUID, enrollment_id: uuid.UUID) -> OfferingWaitlist | None:
        stmt = self._base().where(
            OfferingWaitlist.offering_id == offering_id,
            OfferingWaitlist.student_program_enrollment_id == enrollment_id,
        )
        return (await self.db.execute(stmt.with_for_update())).scalar_one_or_none()

    async def for_enrollment(
        self, enrollment_id: uuid.UUID, offering_ids: Sequence[uuid.UUID] | None = None
    ) -> list[OfferingWaitlist]:
        stmt = self._base().where(OfferingWaitlist.student_program_enrollment_id == enrollment_id)
        if offering_ids is not None:
            stmt = stmt.where(OfferingWaitlist.offering_id.in_(list(offering_ids)))
        return list((await self.db.execute(stmt.order_by(OfferingWaitlist.created_at))).scalars().all())

    async def next_position(self, offering_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(OfferingWaitlist.position), 0)).where(
            OfferingWaitlist.offering_id == offering_id
        )
        return int((await self.db.execute(stmt)).scalar_one()) + 1

    async def next_waiting(self, offering_id: uuid.UUID) -> OfferingWaitlist | None:
        stmt = (
            self._base()
            .where(OfferingWaitlist.offering_id == offering_id, OfferingWaitlist.status == "waiting")
            .order_by(OfferingWaitlist.position)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def expired_offers(self, now: datetime) -> list[OfferingWaitlist]:
        stmt = (
            self._base()
            .where(OfferingWaitlist.status == "offered", OfferingWaitlist.offered_until < now)
            .order_by(OfferingWaitlist.offered_until)
            .with_for_update(skip_locked=True)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def add(self, row: OfferingWaitlist) -> OfferingWaitlist:
        self.db.add(row)
        await self.db.flush()
        return row
