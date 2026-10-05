"""Leave balances — Prompts/06 §06.5 ``leave_balance_repository.py``. One row per (staff, leave type, year);
``balance = opening + accrued − used − encashed`` is maintained transactionally by ``LeaveService`` (row lock on
every change)."""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import StaffLeaveBalance


class LeaveBalanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(
        self, staff_id: uuid.UUID, leave_type_id: uuid.UUID, year: int, *, for_update: bool = False
    ) -> StaffLeaveBalance | None:
        stmt = select(StaffLeaveBalance).where(
            StaffLeaveBalance.staff_id == staff_id,
            StaffLeaveBalance.leave_type_id == leave_type_id,
            StaffLeaveBalance.year == year,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def for_staff(self, staff_id: uuid.UUID, year: int) -> Sequence[StaffLeaveBalance]:
        stmt = select(StaffLeaveBalance).where(StaffLeaveBalance.staff_id == staff_id, StaffLeaveBalance.year == year)
        return (await self.db.execute(stmt)).scalars().all()

    async def for_year(self, year: int, leave_type_ids: Sequence[uuid.UUID]) -> Sequence[StaffLeaveBalance]:
        stmt = select(StaffLeaveBalance).where(
            StaffLeaveBalance.year == year, StaffLeaveBalance.leave_type_id.in_(list(leave_type_ids))
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def create(
        self,
        institution_id: uuid.UUID,
        staff_id: uuid.UUID,
        leave_type_id: uuid.UUID,
        year: int,
        opening: Decimal,
        accrued: Decimal,
    ) -> StaffLeaveBalance:
        row = StaffLeaveBalance(
            institution_id=institution_id,
            staff_id=staff_id,
            leave_type_id=leave_type_id,
            year=year,
            opening=opening,
            accrued=accrued,
            used=Decimal(0),
            encashed=Decimal(0),
            balance=opening + accrued,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    @staticmethod
    def recompute(row: StaffLeaveBalance) -> None:
        row.balance = Decimal(row.opening) + Decimal(row.accrued) - Decimal(row.used) - Decimal(row.encashed)
