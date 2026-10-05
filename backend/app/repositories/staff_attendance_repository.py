"""Staff attendance and attendance devices — Prompts/06 §06.5 ``staff_attendance_repository.py`` (``module=
"attendance"`` with the ``staff_self`` / ``staff_view_all`` actions)."""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, delete, select

from app.core.errors import APIError, ErrorCode
from app.models.hr import AttendanceDevice, Staff, StaffAttendance
from app.repositories.base import BaseRepository
from app.repositories.hr_scope import visible_staff_ids


class StaffAttendanceRepository(BaseRepository[StaffAttendance]):
    model = StaffAttendance
    module = "attendance"

    def filtered(
        self,
        *,
        scope: str | None,
        date_from: date,
        date_to: date,
        staff_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> Select[tuple[StaffAttendance]]:
        stmt = self._base().where(
            StaffAttendance.attendance_date >= date_from, StaffAttendance.attendance_date <= date_to
        )
        if self.principal is not None:
            stmt = stmt.where(StaffAttendance.staff_id.in_(visible_staff_ids(self.principal, "attendance", scope)))
        if staff_id:
            stmt = stmt.where(StaffAttendance.staff_id == staff_id)
        if department_id:
            stmt = stmt.where(
                StaffAttendance.staff_id.in_(select(Staff.id).where(Staff.department_id == department_id))
            )
        if status:
            stmt = stmt.where(StaffAttendance.status == status)
        return stmt

    async def rows(self, stmt: Select[tuple[StaffAttendance]]) -> Sequence[StaffAttendance]:
        return (await self.db.execute(stmt.order_by(StaffAttendance.attendance_date))).scalars().all()

    async def day(self, staff_id: uuid.UUID, day: date, *, for_update: bool = False) -> StaffAttendance | None:
        stmt = select(StaffAttendance).where(
            StaffAttendance.staff_id == staff_id, StaffAttendance.attendance_date == day
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def range_for(
        self, staff_ids: Sequence[uuid.UUID], date_from: date, date_to: date
    ) -> Sequence[StaffAttendance]:
        if not staff_ids:
            return []
        stmt = select(StaffAttendance).where(
            StaffAttendance.staff_id.in_(list(staff_ids)),
            StaffAttendance.attendance_date >= date_from,
            StaffAttendance.attendance_date <= date_to,
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def remove_leave_rows(self, staff_id: uuid.UUID, date_from: date, date_to: date) -> int:
        res = await self.db.execute(
            delete(StaffAttendance).where(
                StaffAttendance.staff_id == staff_id,
                StaffAttendance.attendance_date >= date_from,
                StaffAttendance.attendance_date <= date_to,
                StaffAttendance.status == "on_leave",
            )
        )
        return int(getattr(res, "rowcount", 0) or 0)

    async def add(self, **values: Any) -> StaffAttendance:
        row = StaffAttendance(**values)
        self.db.add(row)
        await self.db.flush()
        return row


class AttendanceDeviceRepository(BaseRepository[AttendanceDevice]):
    model = AttendanceDevice
    module = "attendance"

    async def all(self) -> Sequence[AttendanceDevice]:
        return (await self.db.execute(self._base().order_by(AttendanceDevice.name))).scalars().all()

    async def get_one(self, device_id: uuid.UUID) -> AttendanceDevice:
        row = (await self.db.execute(self._base().where(AttendanceDevice.id == device_id))).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Device not found")
        return row

    async def by_token_hash(self, token_hash: str) -> AttendanceDevice | None:
        stmt = select(AttendanceDevice).where(
            AttendanceDevice.token_hash == token_hash, AttendanceDevice.is_active.is_(True)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()


async def device_institution(device_id: uuid.UUID) -> uuid.UUID | None:
    """The institution of an active device, read on the platform session (the token-authenticated punch route has no
    tenant context yet — RLS would hide the row from the app role)."""
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as pdb:
        row = (
            await pdb.execute(
                select(AttendanceDevice.institution_id).where(
                    AttendanceDevice.id == device_id, AttendanceDevice.is_active.is_(True)
                )
            )
        ).first()
    return uuid.UUID(str(row[0])) if row else None
