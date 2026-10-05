"""Leave types and leave requests — Prompts/06 §06.5 ``leave_repository.py`` (``module="leaves"``).

Lists are filtered through ``hr_scope.visible_staff_ids(principal, "leaves", scope)`` (self / team / all) plus the
approver link (an open workflow step addressed to the caller) on the ``all`` view."""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import ColumnElement, Select, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.hr import LeaveType, Staff, StaffLeave
from app.repositories.base import BaseRepository
from app.repositories.hr_scope import approver_instances, effective_scope, visible_staff_ids

OPEN_LEAVE = ("pending", "approved")


class LeaveTypeRepository(BaseRepository[LeaveType]):
    model = LeaveType
    module = "leaves"

    async def all(self, include_inactive: bool = False) -> Sequence[LeaveType]:
        stmt = self._base()
        if not include_inactive:
            stmt = stmt.where(LeaveType.is_active.is_(True))
        return (await self.db.execute(stmt.order_by(LeaveType.code))).scalars().all()

    async def get_one(self, leave_type_id: uuid.UUID) -> LeaveType:
        row = (await self.db.execute(self._base().where(LeaveType.id == leave_type_id))).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Leave type not found")
        return row

    async def by_code(self, code: str) -> LeaveType | None:
        return (await self.db.execute(self._base().where(LeaveType.code == code.upper()))).scalar_one_or_none()

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, LeaveType]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = (await self.db.execute(select(LeaveType).where(LeaveType.id.in_(ids)))).scalars().all()
        return {r.id: r for r in rows}


class LeaveRepository(BaseRepository[StaffLeave]):
    model = StaffLeave
    module = "leaves"

    def _visible(self, stmt: Select[tuple[StaffLeave]], scope: str | None) -> Select[tuple[StaffLeave]]:
        if self.principal is None:
            return stmt
        cond: ColumnElement[bool] = StaffLeave.staff_id.in_(visible_staff_ids(self.principal, "leaves", scope))
        if effective_scope(self.principal, "leaves", scope) == "all":
            cond = or_(cond, StaffLeave.workflow_instance_id.in_(approver_instances(self.principal)))
        return stmt.where(cond)

    def filtered(
        self,
        *,
        scope: str | None,
        status: str | None = None,
        staff_id: uuid.UUID | None = None,
        leave_type_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> Select[tuple[StaffLeave]]:
        stmt = self._visible(self._base(), scope)
        if status:
            stmt = stmt.where(StaffLeave.status == status)
        if staff_id:
            stmt = stmt.where(StaffLeave.staff_id == staff_id)
        if leave_type_id:
            stmt = stmt.where(StaffLeave.leave_type_id == leave_type_id)
        if department_id:
            stmt = stmt.where(StaffLeave.staff_id.in_(select(Staff.id).where(Staff.department_id == department_id)))
        if date_from:
            stmt = stmt.where(StaffLeave.to_date >= date_from)
        if date_to:
            stmt = stmt.where(StaffLeave.from_date <= date_to)
        return stmt

    async def get_visible(self, leave_id: uuid.UUID, *, for_update: bool = False) -> StaffLeave:
        stmt = self._visible(self._base().where(StaffLeave.id == leave_id), "all")
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Leave not found")
        return row

    async def get_any(self, leave_id: uuid.UUID, *, for_update: bool = False) -> StaffLeave | None:
        stmt = select(StaffLeave).where(StaffLeave.id == leave_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def overlapping(
        self, staff_id: uuid.UUID, from_date: date, to_date: date, exclude: uuid.UUID | None = None
    ) -> StaffLeave | None:
        stmt = select(StaffLeave).where(
            StaffLeave.staff_id == staff_id,
            StaffLeave.status.in_(OPEN_LEAVE),
            StaffLeave.from_date <= to_date,
            StaffLeave.to_date >= from_date,
        )
        if exclude:
            stmt = stmt.where(StaffLeave.id != exclude)
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    async def pending_days(self, staff_id: uuid.UUID, year: int) -> dict[uuid.UUID, Decimal]:
        rows = (
            await self.db.execute(
                select(StaffLeave.leave_type_id, func.coalesce(func.sum(StaffLeave.days_count), 0))
                .where(
                    StaffLeave.staff_id == staff_id,
                    StaffLeave.status == "pending",
                    func.extract("year", StaffLeave.from_date) == year,
                )
                .group_by(StaffLeave.leave_type_id)
            )
        ).all()
        return {lt: Decimal(str(n)) for lt, n in rows}

    async def open_count(self, staff_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(StaffLeave.staff_id == staff_id, StaffLeave.status == "pending")
        return int((await self.db.execute(stmt)).scalar_one())

    async def approved_in_range(
        self,
        staff_ids: Sequence[uuid.UUID],
        date_from: date,
        date_to: date,
        unpaid_type_ids: Sequence[uuid.UUID] | None = None,
    ) -> Sequence[StaffLeave]:
        stmt = select(StaffLeave).where(
            StaffLeave.staff_id.in_(list(staff_ids)),
            StaffLeave.status == "approved",
            StaffLeave.from_date <= date_to,
            StaffLeave.to_date >= date_from,
        )
        if unpaid_type_ids is not None:
            stmt = stmt.where(StaffLeave.leave_type_id.in_(list(unpaid_type_ids)))
        return (await self.db.execute(stmt)).scalars().all()
