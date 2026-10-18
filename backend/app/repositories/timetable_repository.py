"""Timetables and entries — Prompts/10 §10.5 ``timetable_repository.py`` (``module="timetable"``; scope columns
institution / college; department through the scope id).

Reads apply ``timetable_scope.timetable_predicate`` / ``entry_predicate`` (staff institution-wide, students their
section / batch / department and confirmed offerings, parents their wards'). ``occupying`` is the conflict query:
the entries of *other* timetables that are live (``is_active`` = the published version of their scope) plus the
entries of the timetable being edited, at a weekday × set of slots, for a room / staff member / section, week-pattern
aware (``all`` clashes with everything, ``odd`` only with ``odd`` / ``all``).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.timetable import Timetable, TimetableEntry
from app.repositories.base import BaseRepository
from app.repositories.timetable_scope import entry_predicate, timetable_predicate


def clashing_patterns(pattern: str) -> tuple[str, ...]:
    return ("all", "odd", "even") if pattern == "all" else ("all", pattern)


class TimetableRepository(BaseRepository[Timetable]):
    model = Timetable
    module = "timetable"

    def filtered(
        self,
        *,
        term_id: uuid.UUID | None = None,
        college_id: uuid.UUID | None = None,
        scope_type: str | None = None,
        scope_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> Select[tuple[Timetable]]:
        stmt = self._base()
        if self.principal is not None:
            stmt = stmt.where(timetable_predicate(self.principal))
        if term_id:
            stmt = stmt.where(Timetable.term_id == term_id)
        if college_id:
            stmt = stmt.where(Timetable.college_id == college_id)
        if scope_type:
            stmt = stmt.where(Timetable.scope_type == scope_type)
        if scope_id:
            stmt = stmt.where(Timetable.scope_id == scope_id)
        if status:
            stmt = stmt.where(Timetable.status == status)
        return stmt

    async def get_one(self, timetable_id: uuid.UUID, *, for_update: bool = False) -> Timetable:
        stmt = self._base().where(Timetable.id == timetable_id)
        if self.principal is not None:
            stmt = stmt.where(timetable_predicate(self.principal))
        if for_update:
            stmt = stmt.with_for_update(of=Timetable)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Timetable not found")
        return row

    async def lock_scope(self, term_id: uuid.UUID, scope_type: str, scope_id: uuid.UUID) -> list[Timetable]:
        """All versions of a scope, locked ``FOR UPDATE`` (serialises version numbering and publication)."""
        stmt = (
            select(Timetable)
            .where(Timetable.term_id == term_id, Timetable.scope_type == scope_type, Timetable.scope_id == scope_id)
            .order_by(Timetable.version)
            .with_for_update()
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def published_for(self, term_id: uuid.UUID | None, scope_ids: Sequence[uuid.UUID]) -> list[Timetable]:
        if not scope_ids:
            return []
        stmt = select(Timetable).where(Timetable.status == "published", Timetable.scope_id.in_(list(scope_ids)))
        if term_id:
            stmt = stmt.where(Timetable.term_id == term_id)
        return list((await self.db.execute(stmt)).scalars().all())

    # ---- entries ------------------------------------------------------------------------------------------------
    async def entries(self, timetable_ids: Sequence[uuid.UUID]) -> list[TimetableEntry]:
        if not timetable_ids:
            return []
        stmt = (
            select(TimetableEntry)
            .where(TimetableEntry.timetable_id.in_(list(timetable_ids)))
            .order_by(TimetableEntry.day_of_week, TimetableEntry.created_at)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def entry_counts(self, timetable_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not timetable_ids:
            return {}
        rows = await self.db.execute(
            select(TimetableEntry.timetable_id, func.count())
            .where(TimetableEntry.timetable_id.in_(list(timetable_ids)))
            .group_by(TimetableEntry.timetable_id)
        )
        return {tid: int(n) for tid, n in rows.all()}

    async def entry(self, entry_id: uuid.UUID, *, for_update: bool = False) -> TimetableEntry:
        stmt = select(TimetableEntry).where(TimetableEntry.id == entry_id, TimetableEntry.institution_id == self.inst)
        if self.principal is not None:
            stmt = stmt.where(entry_predicate(self.principal))
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Timetable entry not found", {"field": "entry_id"})
        return row

    @property
    def inst(self) -> Any:
        return self.institution_id or getattr(self.principal, "institution_id", None)

    async def live_entries(self, **where: Any) -> list[TimetableEntry]:
        """Active (published) entries filtered by equality on entry columns (``staff_id=…``, ``room_id=…``)."""
        stmt = select(TimetableEntry).where(TimetableEntry.is_active.is_(True))
        for col, value in where.items():
            if value is None:
                continue
            column = getattr(TimetableEntry, col)
            stmt = stmt.where(column.in_(list(value)) if isinstance(value, list | set | tuple) else column == value)
        if self.inst is not None:
            stmt = stmt.where(TimetableEntry.institution_id == self.inst)
        return list((await self.db.execute(stmt)).scalars().all())

    async def occupying(
        self,
        *,
        term_id: uuid.UUID,
        timetable: Timetable,
        day_of_week: int,
        slot_ids: Sequence[uuid.UUID],
        week_pattern: str,
        exclude_entry: uuid.UUID | None = None,
        lock: bool = False,
    ) -> list[TimetableEntry]:
        """Entries that share the weekday × any slot × a clashing week pattern: this timetable's own entries plus
        the live entries of every *other* scope (the version being replaced by this draft is ignored)."""
        same_scope = select(Timetable.id).where(
            Timetable.term_id == timetable.term_id,
            Timetable.scope_type == timetable.scope_type,
            Timetable.scope_id == timetable.scope_id,
        )
        stmt = select(TimetableEntry).where(
            TimetableEntry.term_id == term_id,
            TimetableEntry.day_of_week == day_of_week,
            TimetableEntry.time_slot_id.in_(list(slot_ids)),
            TimetableEntry.week_pattern.in_(clashing_patterns(week_pattern)),
            or_(
                TimetableEntry.timetable_id == timetable.id,
                (TimetableEntry.is_active.is_(True)) & TimetableEntry.timetable_id.notin_(same_scope),
            ),
        )
        if exclude_entry:
            stmt = stmt.where(TimetableEntry.id != exclude_entry)
        if lock:
            stmt = stmt.with_for_update()
        return list((await self.db.execute(stmt)).scalars().all())

    async def day_entries(
        self, term_id: uuid.UUID, day_of_week: int, *, timetable: Timetable | None = None
    ) -> list[TimetableEntry]:
        """Every entry a span may collide with on a weekday (live + the edited timetable's)."""
        stmt = select(TimetableEntry).where(
            TimetableEntry.term_id == term_id, TimetableEntry.day_of_week == day_of_week
        )
        if timetable is not None:
            same_scope = select(Timetable.id).where(
                Timetable.term_id == timetable.term_id,
                Timetable.scope_type == timetable.scope_type,
                Timetable.scope_id == timetable.scope_id,
            )
            stmt = stmt.where(
                or_(
                    TimetableEntry.timetable_id == timetable.id,
                    (TimetableEntry.is_active.is_(True)) & TimetableEntry.timetable_id.notin_(same_scope),
                )
            )
        else:
            stmt = stmt.where(TimetableEntry.is_active.is_(True))
        return list((await self.db.execute(stmt)).scalars().all())
