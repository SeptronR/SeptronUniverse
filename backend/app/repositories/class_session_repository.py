"""Class sessions — Prompts/10 §10.5 ``session_repository.py`` (``module="attendance"``, shared with Phase 11;
ownership ``class_sessions.staff_id``; students through confirmed items). The file is named
``class_session_repository.py`` because ``session_repository.py`` already holds the Phase 02 user sessions."""

import uuid
from collections.abc import Sequence
from datetime import date, time

from sqlalchemy import Select, delete, select

from app.core.errors import APIError, ErrorCode
from app.models.timetable import ClassSession
from app.repositories.base import BaseRepository
from app.repositories.timetable_scope import session_predicate

LIVE = ("scheduled", "conducted")


class ClassSessionRepository(BaseRepository[ClassSession]):
    model = ClassSession
    module = "attendance"

    def filtered(
        self,
        scope: str | None = None,
        *,
        offering_id: uuid.UUID | None = None,
        offering_ids: Sequence[uuid.UUID] | None = None,
        on: date | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        staff_id: uuid.UUID | None = None,
        room_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> Select[tuple[ClassSession]]:
        stmt = self._base()
        if self.principal is not None:
            stmt = stmt.where(session_predicate(self.principal, scope))
        if offering_id:
            stmt = stmt.where(ClassSession.offering_id == offering_id)
        if offering_ids is not None:
            stmt = stmt.where(ClassSession.offering_id.in_(list(offering_ids)))
        if on:
            stmt = stmt.where(ClassSession.session_date == on)
        if date_from:
            stmt = stmt.where(ClassSession.session_date >= date_from)
        if date_to:
            stmt = stmt.where(ClassSession.session_date <= date_to)
        if staff_id:
            stmt = stmt.where(ClassSession.staff_id == staff_id)
        if room_id:
            stmt = stmt.where(ClassSession.room_id == room_id)
        if status:
            stmt = stmt.where(ClassSession.status == status)
        return stmt

    async def get_one(self, session_id: uuid.UUID, *, for_update: bool = False, visible: bool = True) -> ClassSession:
        stmt = self._base().where(ClassSession.id == session_id)
        if visible and self.principal is not None:
            stmt = stmt.where(session_predicate(self.principal, "all"))
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Class session not found")
        return row

    async def of_entry(self, entry_id: uuid.UUID, on: date) -> ClassSession | None:
        stmt = select(ClassSession).where(ClassSession.timetable_entry_id == entry_id, ClassSession.session_date == on)
        return (await self.db.execute(stmt.order_by(ClassSession.start_time).limit(1))).scalar_one_or_none()

    async def for_entries(
        self, entry_ids: Sequence[uuid.UUID], *, date_from: date | None = None, for_update: bool = False
    ) -> list[ClassSession]:
        if not entry_ids:
            return []
        stmt = select(ClassSession).where(ClassSession.timetable_entry_id.in_(list(entry_ids)))
        if date_from:
            stmt = stmt.where(ClassSession.session_date >= date_from)
        if for_update:
            stmt = stmt.with_for_update()
        return list((await self.db.execute(stmt)).scalars().all())

    async def for_offerings_from(self, offering_ids: Sequence[uuid.UUID], date_from: date) -> list[ClassSession]:
        if not offering_ids:
            return []
        stmt = select(ClassSession).where(
            ClassSession.offering_id.in_(list(offering_ids)), ClassSession.session_date >= date_from
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def on_dates(self, dates: Sequence[date], *, status: str = "scheduled") -> list[ClassSession]:
        if not dates:
            return []
        stmt = select(ClassSession).where(
            ClassSession.institution_id == self.institution_id,
            ClassSession.session_date.in_(list(dates)),
            ClassSession.status == status,
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def of_staff_between(self, staff_id: uuid.UUID, date_from: date, date_to: date) -> list[ClassSession]:
        stmt = (
            select(ClassSession)
            .where(
                ClassSession.staff_id == staff_id,
                ClassSession.session_date >= date_from,
                ClassSession.session_date <= date_to,
                ClassSession.status.in_(LIVE),
            )
            .order_by(ClassSession.session_date, ClassSession.start_time)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def overlapping(
        self,
        on: date,
        start: time,
        end: time,
        *,
        staff_id: uuid.UUID | None = None,
        room_id: uuid.UUID | None = None,
        exclude: uuid.UUID | None = None,
    ) -> list[ClassSession]:
        stmt = select(ClassSession).where(
            ClassSession.session_date == on,
            ClassSession.status.in_(LIVE),
            ClassSession.start_time < end,
            ClassSession.end_time > start,
        )
        if self.institution_id is not None:
            stmt = stmt.where(ClassSession.institution_id == self.institution_id)
        if staff_id:
            stmt = stmt.where(ClassSession.staff_id == staff_id)
        if room_id:
            stmt = stmt.where(ClassSession.room_id == room_id)
        if exclude:
            stmt = stmt.where(ClassSession.id != exclude)
        return list((await self.db.execute(stmt.with_for_update())).scalars().all())

    async def delete_ids(self, ids: Sequence[uuid.UUID]) -> int:
        if not ids:
            return 0
        res = await self.db.execute(delete(ClassSession).where(ClassSession.id.in_(list(ids))))
        return int(res.rowcount or 0)  # type: ignore[attr-defined]
