"""Payroll components, salary structures, payroll runs/items and loans — Prompts/06 §06.5 ``payroll_repository.py``
(``module="payroll"``; ``FOR UPDATE`` on the run row of a (staff, month, year) during generation)."""

import uuid
from collections.abc import Sequence
from datetime import date

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.hr import LoanAdvance, PayrollComponent, Staff, StaffPayroll, StaffPayrollItem, StaffSalaryStructure
from app.repositories.base import BaseRepository
from app.repositories.hr_scope import visible_staff_ids


class PayrollComponentRepository(BaseRepository[PayrollComponent]):
    model = PayrollComponent
    module = "payroll"

    async def all(self, include_inactive: bool = False) -> Sequence[PayrollComponent]:
        stmt = self._base()
        if not include_inactive:
            stmt = stmt.where(PayrollComponent.is_active.is_(True))
        return (await self.db.execute(stmt.order_by(PayrollComponent.sequence, PayrollComponent.code))).scalars().all()

    async def get_one(self, component_id: uuid.UUID) -> PayrollComponent:
        row = (await self.db.execute(self._base().where(PayrollComponent.id == component_id))).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Payroll component not found")
        return row

    async def by_code(self, code: str) -> PayrollComponent | None:
        return (await self.db.execute(self._base().where(PayrollComponent.code == code))).scalar_one_or_none()


class SalaryStructureRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def for_staff(self, staff_id: uuid.UUID) -> Sequence[StaffSalaryStructure]:
        stmt = (
            select(StaffSalaryStructure)
            .where(StaffSalaryStructure.staff_id == staff_id)
            .order_by(StaffSalaryStructure.effective_from.desc(), StaffSalaryStructure.created_at.desc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def effective(self, staff_id: uuid.UUID, on: date) -> StaffSalaryStructure | None:
        stmt = (
            select(StaffSalaryStructure)
            .where(
                StaffSalaryStructure.staff_id == staff_id,
                StaffSalaryStructure.effective_from <= on,
                or_(StaffSalaryStructure.effective_to.is_(None), StaffSalaryStructure.effective_to >= on),
            )
            .order_by(StaffSalaryStructure.effective_from.desc(), StaffSalaryStructure.created_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def open_ended(self, staff_id: uuid.UUID) -> Sequence[StaffSalaryStructure]:
        stmt = select(StaffSalaryStructure).where(
            StaffSalaryStructure.staff_id == staff_id, StaffSalaryStructure.effective_to.is_(None)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def add(self, row: StaffSalaryStructure) -> StaffSalaryStructure:
        self.db.add(row)
        await self.db.flush()
        return row


class PayrollRepository(BaseRepository[StaffPayroll]):
    model = StaffPayroll
    module = "payroll"

    def filtered(
        self,
        *,
        scope: str | None,
        month: int | None = None,
        year: int | None = None,
        status: str | None = None,
        staff_id: uuid.UUID | None = None,
        college_id: uuid.UUID | None = None,
    ) -> Select[tuple[StaffPayroll]]:
        stmt = self._base()
        if self.principal is not None:
            stmt = stmt.where(StaffPayroll.staff_id.in_(visible_staff_ids(self.principal, "payroll", scope)))
        if month:
            stmt = stmt.where(StaffPayroll.month == month)
        if year:
            stmt = stmt.where(StaffPayroll.year == year)
        if status:
            stmt = stmt.where(StaffPayroll.status == status)
        if staff_id:
            stmt = stmt.where(StaffPayroll.staff_id == staff_id)
        if college_id:
            stmt = stmt.where(StaffPayroll.staff_id.in_(select(Staff.id).where(Staff.college_id == college_id)))
        return stmt

    async def get_visible(self, payroll_id: uuid.UUID, *, for_update: bool = False) -> StaffPayroll:
        stmt = self.filtered(scope="all").where(StaffPayroll.id == payroll_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Payroll not found")
        return row

    async def run_for(
        self, staff_id: uuid.UUID, month: int, year: int, *, for_update: bool = False
    ) -> StaffPayroll | None:
        stmt = select(StaffPayroll).where(
            StaffPayroll.staff_id == staff_id, StaffPayroll.month == month, StaffPayroll.year == year
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def runs_of_staff(self, staff_id: uuid.UUID) -> Sequence[StaffPayroll]:
        stmt = (
            select(StaffPayroll)
            .where(StaffPayroll.staff_id == staff_id)
            .order_by(StaffPayroll.year, StaffPayroll.month)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def period(self, month: int, year: int, status: Sequence[str] | None = None) -> Sequence[StaffPayroll]:
        stmt = self._base().where(StaffPayroll.month == month, StaffPayroll.year == year)
        if status:
            stmt = stmt.where(StaffPayroll.status.in_(list(status)))
        return (await self.db.execute(stmt)).scalars().all()

    async def items(self, payroll_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[StaffPayrollItem]]:
        if not payroll_ids:
            return {}
        rows = (
            (await self.db.execute(select(StaffPayrollItem).where(StaffPayrollItem.payroll_id.in_(list(payroll_ids)))))
            .scalars()
            .all()
        )
        out: dict[uuid.UUID, list[StaffPayrollItem]] = {pid: [] for pid in payroll_ids}
        for r in rows:
            out.setdefault(r.payroll_id, []).append(r)
        return out

    async def clear_items(self, payroll_id: uuid.UUID) -> None:
        await self.db.execute(delete(StaffPayrollItem).where(StaffPayrollItem.payroll_id == payroll_id))

    async def add_item(self, item: StaffPayrollItem) -> None:
        self.db.add(item)

    async def arrears_paid(
        self, staff_id: uuid.UUID, structure_id: uuid.UUID, exclude_payroll: uuid.UUID | None
    ) -> set[str]:
        """Labels of arrears items already paid for a structure (dedupe across runs)."""
        stmt = (
            select(StaffPayrollItem.label)
            .join(StaffPayroll, StaffPayroll.id == StaffPayrollItem.payroll_id)
            .where(
                StaffPayroll.staff_id == staff_id,
                StaffPayrollItem.source_type == "arrears",
                StaffPayrollItem.source_id == structure_id,
            )
        )
        if exclude_payroll:
            stmt = stmt.where(StaffPayroll.id != exclude_payroll)
        return set((await self.db.execute(stmt)).scalars().all())

    async def source_used(self, source_type: str, source_id: uuid.UUID, exclude_payroll: uuid.UUID | None) -> bool:
        stmt = select(StaffPayrollItem.id).where(
            StaffPayrollItem.source_type == source_type, StaffPayrollItem.source_id == source_id
        )
        if exclude_payroll:
            stmt = stmt.where(StaffPayrollItem.payroll_id != exclude_payroll)
        return (await self.db.execute(stmt.limit(1))).first() is not None

    async def year_runs(
        self, staff_ids: Sequence[uuid.UUID], periods: Sequence[tuple[int, int]]
    ) -> Sequence[StaffPayroll]:
        conds = [(StaffPayroll.year == y) & (StaffPayroll.month == m) for y, m in periods]
        stmt = self._base().where(
            StaffPayroll.staff_id.in_(list(staff_ids)), or_(*conds), StaffPayroll.status != "cancelled"
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def unpaid_count(self, staff_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            StaffPayroll.staff_id == staff_id, StaffPayroll.status.in_(("draft", "approved"))
        )
        return int((await self.db.execute(stmt)).scalar_one())


class LoanRepository(BaseRepository[LoanAdvance]):
    model = LoanAdvance
    module = "payroll"

    def filtered(
        self, *, scope: str | None, status: str | None = None, staff_id: uuid.UUID | None = None
    ) -> Select[tuple[LoanAdvance]]:
        stmt = self._base()
        if self.principal is not None:
            stmt = stmt.where(LoanAdvance.staff_id.in_(visible_staff_ids(self.principal, "payroll", scope)))
        if status:
            stmt = stmt.where(LoanAdvance.status == status)
        if staff_id:
            stmt = stmt.where(LoanAdvance.staff_id == staff_id)
        return stmt

    async def get_visible(self, loan_id: uuid.UUID, *, for_update: bool = False) -> LoanAdvance:
        stmt = self.filtered(scope="all").where(LoanAdvance.id == loan_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Loan not found")
        return row

    async def get_any(self, loan_id: uuid.UUID) -> LoanAdvance | None:
        return (await self.db.execute(select(LoanAdvance).where(LoanAdvance.id == loan_id))).scalar_one_or_none()

    async def active_for(self, staff_id: uuid.UUID, month_start: date) -> Sequence[LoanAdvance]:
        stmt = select(LoanAdvance).where(
            LoanAdvance.staff_id == staff_id,
            LoanAdvance.status == "active",
            LoanAdvance.start_month <= month_start,
            LoanAdvance.balance_paise > 0,
        )
        return (await self.db.execute(stmt)).scalars().all()
