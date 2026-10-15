"""Holidays — Prompts/03 §03.5 ``holiday_repository`` (institution-wide rows have ``college_id`` NULL)."""

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.platform import College, Holiday
from app.repositories.base import BaseRepository


class HolidayRepository(BaseRepository[Holiday]):
    model = Holiday
    module = "holidays"

    def filtered(
        self,
        *,
        college_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        holiday_type: str | None = None,
        applies_to: str | None = None,
    ) -> Select[tuple[Holiday]]:
        # holidays of a soft-deleted college are not shown or exported (Phase 03 UI walk, 2026-10-05)
        stmt = self._base().where(
            or_(
                Holiday.college_id.is_(None),
                Holiday.college_id.in_(select(College.id).where(College.deleted_at.is_(None))),
            )
        )
        if college_id is not None:
            stmt = stmt.where(or_(Holiday.college_id == college_id, Holiday.college_id.is_(None)))
        if date_from:
            stmt = stmt.where(func.coalesce(Holiday.end_date, Holiday.holiday_date) >= date_from)
        if date_to:
            stmt = stmt.where(Holiday.holiday_date <= date_to)
        if holiday_type:
            stmt = stmt.where(Holiday.holiday_type == holiday_type)
        if applies_to:
            stmt = stmt.where(Holiday.applies_to.in_([applies_to, "all"]))
        return stmt

    async def get_one(self, holiday_id: uuid.UUID) -> Holiday:
        obj = (await self.db.execute(self._base().where(Holiday.id == holiday_id))).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Holiday not found")
        return obj

    async def duplicate(
        self, institution_id: uuid.UUID, college_id: uuid.UUID | None, day: date, name: str
    ) -> Holiday | None:
        """Soft-deleted rows included: the UNIQUE constraint still covers them (NULL college ids never collide)."""
        stmt = select(Holiday).where(
            Holiday.institution_id == institution_id, Holiday.holiday_date == day, Holiday.name == name
        )
        stmt = stmt.where(Holiday.college_id.is_(None) if college_id is None else Holiday.college_id == college_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def covering(
        self, institution_id: uuid.UUID, day: date, college_id: uuid.UUID | None, applies_to: str | None
    ) -> Sequence[Holiday]:
        stmt = self._base().where(
            Holiday.institution_id == institution_id,
            Holiday.holiday_date <= day,
            func.coalesce(Holiday.end_date, Holiday.holiday_date) >= day,
        )
        stmt = stmt.where(
            Holiday.college_id.is_(None)
            if college_id is None
            else or_(Holiday.college_id == college_id, Holiday.college_id.is_(None))
        )
        if applies_to:
            stmt = stmt.where(Holiday.applies_to.in_([applies_to, "all"]))
        return (await self.db.execute(stmt)).scalars().all()
