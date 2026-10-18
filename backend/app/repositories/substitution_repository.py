"""Timetable substitutions — Prompts/10 §10.5 ``substitution_repository.py``.

A request names an entry and a date (``UNIQUE (timetable_entry_id, on_date)``). Visibility: the absent faculty and the
substitute read their own; HODs (``timetable:approve``) the requests of their departments' offerings; registrar /
institution scope all. ``source='leave_auto'`` rows carry the leave id in the reason prefix (``[leave:<uuid>]``) —
the DDL has no column for it.
"""

import re
import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.offerings import CourseOffering
from app.models.timetable import TimetableEntry, TimetableSubstitution
from app.repositories.timetable_scope import my_staff_ids

LEAVE_TAG = re.compile(r"^\[leave:([0-9a-f-]{36})\]\s*")


def leave_tag(leave_id: uuid.UUID) -> str:
    return f"[leave:{leave_id}] "


def leave_of(reason: str | None) -> uuid.UUID | None:
    m = LEAVE_TAG.match(reason or "")
    return uuid.UUID(m.group(1)) if m else None


def strip_tag(reason: str | None) -> str | None:
    return LEAVE_TAG.sub("", reason) if reason else reason


class SubstitutionRepository:
    def __init__(self, db: AsyncSession, principal: Any, institution_id: uuid.UUID):
        self.db = db
        self.principal = principal
        self.inst = institution_id

    def filtered(
        self,
        *,
        department_ids: Sequence[uuid.UUID] | None,
        mine_only: bool,
        status: str | None = None,
        source: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> Select[tuple[TimetableSubstitution]]:
        stmt = select(TimetableSubstitution).where(TimetableSubstitution.institution_id == self.inst)
        p = self.principal
        own = None
        if p is not None and getattr(p, "id", None) is not None:
            own = or_(
                TimetableSubstitution.substitute_staff_id.in_(my_staff_ids(p)),
                TimetableSubstitution.timetable_entry_id.in_(
                    select(TimetableEntry.id).where(TimetableEntry.staff_id.in_(my_staff_ids(p)))
                ),
            )
        if mine_only:
            if own is not None:
                stmt = stmt.where(own)
        elif department_ids is not None:
            dept = TimetableSubstitution.timetable_entry_id.in_(
                select(TimetableEntry.id).where(
                    TimetableEntry.offering_id.in_(
                        select(CourseOffering.id).where(CourseOffering.department_id.in_(list(department_ids)))
                    )
                )
            )
            stmt = stmt.where(or_(dept, own) if own is not None else dept)
        if status:
            stmt = stmt.where(TimetableSubstitution.status == status)
        if source:
            stmt = stmt.where(TimetableSubstitution.source == source)
        if date_from:
            stmt = stmt.where(TimetableSubstitution.on_date >= date_from)
        if date_to:
            stmt = stmt.where(TimetableSubstitution.on_date <= date_to)
        return stmt.order_by(TimetableSubstitution.on_date.desc(), TimetableSubstitution.created_at.desc())

    async def get_one(self, sub_id: uuid.UUID, *, for_update: bool = False) -> TimetableSubstitution:
        stmt = select(TimetableSubstitution).where(
            TimetableSubstitution.id == sub_id, TimetableSubstitution.institution_id == self.inst
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Substitution not found")
        return row

    async def find(self, entry_id: uuid.UUID, on: date) -> TimetableSubstitution | None:
        stmt = select(TimetableSubstitution).where(
            TimetableSubstitution.timetable_entry_id == entry_id, TimetableSubstitution.on_date == on
        )
        return (await self.db.execute(stmt.with_for_update())).scalar_one_or_none()

    async def of_leave(self, leave_id: uuid.UUID) -> list[TimetableSubstitution]:
        stmt = select(TimetableSubstitution).where(
            TimetableSubstitution.institution_id == self.inst,
            TimetableSubstitution.source == "leave_auto",
            TimetableSubstitution.reason.like(f"[leave:{leave_id}]%"),
        )
        return list((await self.db.execute(stmt.with_for_update())).scalars().all())
