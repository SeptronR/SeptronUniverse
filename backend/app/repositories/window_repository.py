"""Registration windows — Prompts/09 §09.5 ``window_repository.py``.

``open_windows(term, enrollment, record, now)`` returns the windows of the term (institution-wide or of the
enrolment's college) that are open *now* (``starts_at ≤ now < ends_at`` and not ``closed`` by the registrar) and whose
``applies_to`` rules match the enrolment: every key present must contain the enrolment's value (``program_ids``,
``batch_ids``, ``section_ids``, ``department_ids``, ``term_numbers``, ``entry_types``); an empty / missing
``applies_to`` matches everyone.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.registration import RegistrationWindow

# order in which an open window is picked as "the" window of a registration
TYPE_ORDER = ("regular", "add_drop", "late", "arrear", "summer", "minor_honours", "audit")


def window_is_open(w: RegistrationWindow, now: datetime) -> bool:
    return w.status != "closed" and w.starts_at <= now < w.ends_at


def applies(w: RegistrationWindow, enrollment: Any, record: Any) -> bool:
    rules = w.applies_to or {}

    def match(key: str, value: Any) -> bool:
        wanted = rules.get(key)
        if not wanted:
            return True
        return str(value) in {str(v) for v in wanted}

    return (
        match("program_ids", enrollment.program_id)
        and match("batch_ids", enrollment.batch_id)
        and match("department_ids", enrollment.department_id)
        and match("entry_types", enrollment.entry_type)
        and match("section_ids", getattr(record, "section_id", None))
        and match("term_numbers", getattr(record, "term_number", None))
    )


class WindowRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID | None = None):
        self.db, self.inst = db, institution_id

    def _base(self) -> Any:
        stmt = select(RegistrationWindow)
        if self.inst is not None:
            stmt = stmt.where(RegistrationWindow.institution_id == self.inst)
        return stmt

    async def list_all(
        self,
        term_id: uuid.UUID | None = None,
        status: str | None = None,
        college_ids: Sequence[uuid.UUID] | None = None,
        window_type: str | None = None,
    ) -> list[RegistrationWindow]:
        stmt = self._base()
        if term_id:
            stmt = stmt.where(RegistrationWindow.term_id == term_id)
        if status:
            stmt = stmt.where(RegistrationWindow.status == status)
        if window_type:
            stmt = stmt.where(RegistrationWindow.window_type == window_type)
        if college_ids is not None:
            stmt = stmt.where(
                or_(RegistrationWindow.college_id.is_(None), RegistrationWindow.college_id.in_(list(college_ids)))
            )
        return list((await self.db.execute(stmt.order_by(RegistrationWindow.starts_at))).scalars().all())

    async def get(self, window_id: uuid.UUID, *, for_update: bool = False) -> RegistrationWindow:
        stmt = self._base().where(RegistrationWindow.id == window_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Registration window not found")
        return row

    async def add(self, row: RegistrationWindow) -> RegistrationWindow:
        self.db.add(row)
        await self.db.flush()
        return row

    async def for_term(self, term_id: uuid.UUID, college_id: uuid.UUID | None) -> list[RegistrationWindow]:
        stmt = self._base().where(
            RegistrationWindow.term_id == term_id,
            or_(RegistrationWindow.college_id.is_(None), RegistrationWindow.college_id == college_id),
        )
        return list((await self.db.execute(stmt.order_by(RegistrationWindow.starts_at))).scalars().all())

    async def open_windows(
        self, term_id: uuid.UUID, enrollment: Any, record: Any, now: datetime
    ) -> list[RegistrationWindow]:
        rows = [
            w
            for w in await self.for_term(term_id, enrollment.college_id)
            if window_is_open(w, now) and applies(w, enrollment, record)
        ]
        return sorted(rows, key=lambda w: TYPE_ORDER.index(w.window_type) if w.window_type in TYPE_ORDER else 99)

    async def due_for_status(self) -> list[RegistrationWindow]:
        stmt = (
            self._base().where(RegistrationWindow.status.in_(("scheduled", "open"))).with_for_update(skip_locked=True)
        )
        return list((await self.db.execute(stmt)).scalars().all())
