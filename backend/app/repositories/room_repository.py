"""Buildings and rooms — Prompts/10 §10.5 ``room_repository.py`` (``module="timetable"``).

Rooms and buildings are readable institution-wide (``timetable:view``), so reads only pin the tenant (no row
predicate). ``busy_room_ids`` answers the availability finder: rooms holding an active entry at a weekday × slot (week
pattern aware) or a live class session overlapping a date × time window.
"""

import uuid
from collections.abc import Sequence
from datetime import date, time
from typing import Any

from sqlalchemy import Select, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.timetable import Building, ClassSession, Room, TimetableEntry
from app.repositories.base import BaseRepository


class BuildingRepository(BaseRepository[Building]):
    model = Building
    module = "timetable"

    async def get_one(self, building_id: uuid.UUID) -> Building:
        row = (await self.db.execute(self._base().where(Building.id == building_id))).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Building not found")
        return row

    async def listed(self, college_id: uuid.UUID | None = None) -> list[Building]:
        stmt = self._base()
        if college_id:
            stmt = stmt.where(Building.college_id == college_id)
        return list((await self.db.execute(stmt.order_by(Building.code))).scalars().all())

    async def by_code(self, college_id: uuid.UUID, code: str) -> Building | None:
        stmt = self._base().where(Building.college_id == college_id, func.lower(Building.code) == code.lower())
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def room_counts(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not ids:
            return {}
        rows = await self.db.execute(
            select(Room.building_id, func.count())
            .where(Room.building_id.in_(list(ids)), Room.deleted_at.is_(None))
            .group_by(Room.building_id)
        )
        return {bid: int(n) for bid, n in rows.all() if bid is not None}


class RoomRepository(BaseRepository[Room]):
    model = Room
    module = "timetable"

    def filtered(
        self,
        *,
        college_id: uuid.UUID | None = None,
        building_id: uuid.UUID | None = None,
        room_type: str | None = None,
        min_capacity: int | None = None,
        bookable: bool | None = None,
        q: str | None = None,
        active_only: bool = False,
    ) -> Select[tuple[Room]]:
        stmt = self._base()
        if college_id:
            stmt = stmt.where(Room.college_id == college_id)
        if building_id:
            stmt = stmt.where(Room.building_id == building_id)
        if room_type:
            stmt = stmt.where(Room.room_type == room_type)
        if min_capacity:
            stmt = stmt.where(Room.capacity >= min_capacity)
        if bookable is not None:
            stmt = stmt.where(Room.is_bookable.is_(bookable))
        if active_only:
            stmt = stmt.where(Room.is_active.is_(True))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Room.code.ilike(like), Room.name.ilike(like)))
        return stmt

    async def get_one(self, room_id: uuid.UUID, *, for_update: bool = False) -> Room:
        stmt = self._base().where(Room.id == room_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Room not found", {"field": "room_id"})
        return row

    async def by_code(self, college_id: uuid.UUID, code: str) -> Room | None:
        stmt = self._base(include_deleted=True).where(
            Room.college_id == college_id, func.lower(Room.code) == code.lower()
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def rows(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, Room]:
        wanted = [i for i in set(ids) if i]
        if not wanted:
            return {}
        res = await self.db.execute(select(Room).where(Room.id.in_(wanted)))
        return {r.id: r for r in res.scalars().all()}

    async def entries_using(self, room_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(TimetableEntry.room_id == room_id, TimetableEntry.is_active.is_(True))
        return int((await self.db.execute(stmt)).scalar_one())

    async def busy_on(
        self, term_id: uuid.UUID | None, day_of_week: int, slot_ids: Sequence[uuid.UUID], week_patterns: Sequence[str]
    ) -> dict[uuid.UUID, list[uuid.UUID]]:
        """room id → active entry ids occupying it at the weekday × any of ``slot_ids`` (week-pattern aware)."""
        if not slot_ids:
            return {}
        stmt = select(TimetableEntry.room_id, TimetableEntry.id).where(
            TimetableEntry.is_active.is_(True),
            TimetableEntry.room_id.is_not(None),
            TimetableEntry.day_of_week == day_of_week,
            TimetableEntry.time_slot_id.in_(list(slot_ids)),
            TimetableEntry.week_pattern.in_(list(week_patterns)),
        )
        if term_id:
            stmt = stmt.where(TimetableEntry.term_id == term_id)
        out: dict[uuid.UUID, list[uuid.UUID]] = {}
        for rid, eid in (await self.db.execute(stmt)).all():
            out.setdefault(rid, []).append(eid)
        return out

    async def busy_sessions(
        self, on: date, start: time, end: time, *, exclude_session: uuid.UUID | None = None
    ) -> dict[uuid.UUID, list[Any]]:
        """room id → live sessions overlapping ``[start, end)`` on ``on``."""
        stmt = select(ClassSession).where(
            ClassSession.session_date == on,
            ClassSession.room_id.is_not(None),
            ClassSession.status.in_(("scheduled", "conducted")),
            ClassSession.start_time < end,
            ClassSession.end_time > start,
        )
        if exclude_session:
            stmt = stmt.where(ClassSession.id != exclude_session)
        out: dict[uuid.UUID, list[Any]] = {}
        for s in (await self.db.execute(stmt)).scalars().all():
            if s.room_id is not None:
                out.setdefault(s.room_id, []).append(s)
        return out
