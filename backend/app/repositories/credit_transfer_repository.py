"""Credit transfers — Prompts/07 §07.5 ``credit_transfer_repository.py`` (visible through the student; the MOOC cap sums
the live MOOC transfers of the enrolment)."""

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.enums.students import MOOC_SOURCES
from app.models.students import CreditTransfer, Student, StudentProgramEnrollment
from app.repositories.student_scope import visible_enrollment_ids

LIVE = ("submitted", "verified", "approved", "credited")


class CreditTransferRepository:
    def __init__(self, db: AsyncSession, principal: Any = None, institution_id: uuid.UUID | None = None):
        self.db, self.principal, self.institution_id = db, principal, institution_id

    def filtered(
        self,
        *,
        enrollment_ids: Sequence[uuid.UUID] | None = None,
        status: str | None = None,
        source: str | None = None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
        scope: str | None = "all",
    ) -> Select[tuple[CreditTransfer]]:
        stmt = select(CreditTransfer)
        if self.institution_id is not None:
            stmt = stmt.where(CreditTransfer.institution_id == self.institution_id)
        if self.principal is not None:
            stmt = stmt.where(
                CreditTransfer.student_program_enrollment_id.in_(visible_enrollment_ids(self.principal, scope))
            )
        if enrollment_ids is not None:
            stmt = stmt.where(CreditTransfer.student_program_enrollment_id.in_(list(enrollment_ids)))
        if status:
            stmt = stmt.where(CreditTransfer.status == status)
        if source:
            stmt = stmt.where(CreditTransfer.source == source)
        if department_id is not None:
            stmt = stmt.where(
                CreditTransfer.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.department_id == department_id)
                )
            )
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                CreditTransfer.source_title.ilike(like)
                | CreditTransfer.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(
                        (Student.first_name + " " + func.coalesce(Student.last_name, "")).ilike(like)
                        | Student.registration_number.ilike(like)
                    )
                )
            )
        return stmt

    async def page(
        self, stmt: Select[tuple[CreditTransfer]], offset: int, limit: int
    ) -> tuple[Sequence[CreditTransfer], int]:
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            (await self.db.execute(stmt.order_by(CreditTransfer.created_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return rows, total

    async def get(self, ct_id: uuid.UUID, *, for_update: bool = False) -> CreditTransfer:
        stmt = self.filtered().where(CreditTransfer.id == ct_id)
        if for_update:
            stmt = stmt.with_for_update(of=CreditTransfer)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Credit transfer not found")
        return row

    async def get_any(self, ct_id: uuid.UUID, *, for_update: bool = False) -> CreditTransfer | None:
        stmt = select(CreditTransfer).where(CreditTransfer.id == ct_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def mooc_credits(self, enrollment_id: uuid.UUID, exclude: uuid.UUID | None = None) -> Decimal:
        stmt = select(func.coalesce(func.sum(CreditTransfer.credits), 0)).where(
            CreditTransfer.student_program_enrollment_id == enrollment_id,
            CreditTransfer.source.in_(sorted(MOOC_SOURCES)),
            CreditTransfer.status.in_(LIVE),
        )
        if exclude is not None:
            stmt = stmt.where(CreditTransfer.id != exclude)
        return Decimal(str((await self.db.execute(stmt)).scalar_one()))

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> Sequence[CreditTransfer]:
        if not ids:
            return []
        return (await self.db.execute(select(CreditTransfer).where(CreditTransfer.id.in_(list(ids))))).scalars().all()

    async def pending_count(self, enrollment_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            CreditTransfer.student_program_enrollment_id == enrollment_id,
            CreditTransfer.status.in_(("submitted", "verified")),
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def add(self, obj: CreditTransfer) -> CreditTransfer:
        self.db.add(obj)
        await self.db.flush()
        return obj
