"""Elective choice forms and allocation runs — Prompts/09 §09.5 ``choice_form_repository.py``."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.registration import ElectiveAllocationRun, ElectiveChoiceForm


class ChoiceFormRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID | None = None):
        self.db, self.inst = db, institution_id

    def _base(self) -> Any:
        stmt = select(ElectiveChoiceForm)
        if self.inst is not None:
            stmt = stmt.where(ElectiveChoiceForm.institution_id == self.inst)
        return stmt

    async def get_for(
        self, enrollment_id: uuid.UUID, basket_id: uuid.UUID, term_id: uuid.UUID, *, for_update: bool = False
    ) -> ElectiveChoiceForm | None:
        stmt = self._base().where(
            ElectiveChoiceForm.student_program_enrollment_id == enrollment_id,
            ElectiveChoiceForm.elective_basket_id == basket_id,
            ElectiveChoiceForm.term_id == term_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get(self, form_id: uuid.UUID, *, for_update: bool = False) -> ElectiveChoiceForm:
        stmt = self._base().where(ElectiveChoiceForm.id == form_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Choice form not found")
        return row

    async def for_enrollment(self, enrollment_id: uuid.UUID, term_id: uuid.UUID) -> list[ElectiveChoiceForm]:
        stmt = self._base().where(
            ElectiveChoiceForm.student_program_enrollment_id == enrollment_id, ElectiveChoiceForm.term_id == term_id
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def for_basket(
        self, basket_id: uuid.UUID, term_id: uuid.UUID, statuses: tuple[str, ...] | None = None, *, lock: bool = False
    ) -> list[ElectiveChoiceForm]:
        stmt = self._base().where(
            ElectiveChoiceForm.elective_basket_id == basket_id, ElectiveChoiceForm.term_id == term_id
        )
        if statuses:
            stmt = stmt.where(ElectiveChoiceForm.status.in_(statuses))
        if lock:
            stmt = stmt.with_for_update()
        return list((await self.db.execute(stmt.order_by(ElectiveChoiceForm.submitted_at))).scalars().all())

    async def add(self, row: Any) -> Any:
        self.db.add(row)
        await self.db.flush()
        return row

    async def run(self, run_id: uuid.UUID) -> ElectiveAllocationRun:
        stmt = select(ElectiveAllocationRun).where(ElectiveAllocationRun.id == run_id)
        if self.inst is not None:
            stmt = stmt.where(ElectiveAllocationRun.institution_id == self.inst)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Allocation run not found")
        return row

    async def runs(self, basket_id: uuid.UUID | None, term_id: uuid.UUID | None) -> list[ElectiveAllocationRun]:
        stmt = select(ElectiveAllocationRun)
        if self.inst is not None:
            stmt = stmt.where(ElectiveAllocationRun.institution_id == self.inst)
        if basket_id:
            stmt = stmt.where(ElectiveAllocationRun.elective_basket_id == basket_id)
        if term_id:
            stmt = stmt.where(ElectiveAllocationRun.term_id == term_id)
        return list((await self.db.execute(stmt.order_by(ElectiveAllocationRun.run_at.desc()).limit(50))).scalars())
