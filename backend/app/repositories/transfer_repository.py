"""Student transfers / migration — Prompts/07 §07.5 ``transfer_repository.py`` (visible through the student)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.students import Student, StudentTransfer
from app.repositories.student_scope import visible_student_ids


class TransferRepository:
    def __init__(self, db: AsyncSession, principal: Any = None, institution_id: uuid.UUID | None = None):
        self.db, self.principal, self.institution_id = db, principal, institution_id

    def filtered(
        self,
        *,
        student_id: uuid.UUID | None = None,
        status: str | None = None,
        transfer_type: str | None = None,
        q: str | None = None,
        scope: str | None = "all",
    ) -> Select[tuple[StudentTransfer]]:
        stmt = select(StudentTransfer)
        if self.institution_id is not None:
            stmt = stmt.where(StudentTransfer.institution_id == self.institution_id)
        if self.principal is not None:
            stmt = stmt.where(StudentTransfer.student_id.in_(visible_student_ids(self.principal, scope)))
        if student_id is not None:
            stmt = stmt.where(StudentTransfer.student_id == student_id)
        if status:
            stmt = stmt.where(StudentTransfer.status == status)
        if transfer_type:
            stmt = stmt.where(StudentTransfer.transfer_type == transfer_type)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                StudentTransfer.student_id.in_(
                    select(Student.id).where(
                        (Student.first_name + " " + func.coalesce(Student.last_name, "")).ilike(like)
                        | Student.registration_number.ilike(like)
                    )
                )
            )
        return stmt

    async def page(
        self, stmt: Select[tuple[StudentTransfer]], offset: int, limit: int
    ) -> tuple[Sequence[StudentTransfer], int]:
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            (await self.db.execute(stmt.order_by(StudentTransfer.requested_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return rows, total

    async def get(self, transfer_id: uuid.UUID, *, for_update: bool = False) -> StudentTransfer:
        stmt = self.filtered().where(StudentTransfer.id == transfer_id)
        if for_update:
            stmt = stmt.with_for_update(of=StudentTransfer)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Transfer request not found")
        return row

    async def get_any(self, transfer_id: uuid.UUID, *, for_update: bool = False) -> StudentTransfer | None:
        stmt = select(StudentTransfer).where(StudentTransfer.id == transfer_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def open_for(self, student_id: uuid.UUID) -> StudentTransfer | None:
        stmt = select(StudentTransfer).where(
            StudentTransfer.student_id == student_id,
            StudentTransfer.status.in_(("requested", "dues_check", "approved")),
        )
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    async def add(self, obj: StudentTransfer) -> StudentTransfer:
        self.db.add(obj)
        await self.db.flush()
        return obj
