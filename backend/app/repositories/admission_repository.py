"""Admission cycles, cycle programmes and the seat matrix — Prompts/08 §08.5 ``admission_repository.py``.

Cycles are readable by every holder of ``admissions:view`` (no row predicate); ``seat_rows(..., for_update=True)``
locks the cycle's seat rows ``FOR UPDATE`` in id order while an allotment runs, so concurrent runs serialise and the
``filled`` counters never exceed ``seats``.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.academic import Program
from app.models.admissions import AdmissionCycle, AdmissionCycleProgram, Applicant, SeatMatrix
from app.models.platform import College


class AdmissionRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID):
        self.db, self.inst = db, institution_id

    # ---- cycles ---------------------------------------------------------------------------------------------------
    def _cycles(self) -> Any:
        return select(AdmissionCycle).where(
            AdmissionCycle.institution_id == self.inst, AdmissionCycle.deleted_at.is_(None)
        )

    async def list_cycles(self, status: str | None = None, level: str | None = None) -> Sequence[AdmissionCycle]:
        stmt = self._cycles()
        if status:
            stmt = stmt.where(AdmissionCycle.status == status)
        if level:
            stmt = stmt.where(AdmissionCycle.level == level)
        return (await self.db.execute(stmt.order_by(AdmissionCycle.created_at.desc()))).scalars().all()

    async def cycle(self, cycle_id: uuid.UUID, *, for_update: bool = False) -> AdmissionCycle:
        stmt = self._cycles().where(AdmissionCycle.id == cycle_id)
        if for_update:
            stmt = stmt.with_for_update()
        row: AdmissionCycle | None = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Admission cycle not found")
        return row

    async def by_slug(self, slug: str) -> AdmissionCycle | None:
        return (await self.db.execute(self._cycles().where(AdmissionCycle.slug == slug))).scalar_one_or_none()

    async def slug_taken(self, slug: str) -> bool:
        stmt = select(AdmissionCycle.id).where(AdmissionCycle.institution_id == self.inst, AdmissionCycle.slug == slug)
        return (await self.db.execute(stmt)).first() is not None

    async def counts(self, cycle_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int, int]]:
        """``{cycle_id: (programmes, applicants, intake)}``."""
        if not cycle_ids:
            return {}
        ids = list(cycle_ids)
        progs: dict[uuid.UUID, tuple[int, int]] = {}
        for cid, n, total in (
            await self.db.execute(
                select(
                    AdmissionCycleProgram.cycle_id,
                    func.count(),
                    func.sum(AdmissionCycleProgram.intake + AdmissionCycleProgram.lateral_intake),
                )
                .where(AdmissionCycleProgram.cycle_id.in_(ids))
                .group_by(AdmissionCycleProgram.cycle_id)
            )
        ).all():
            progs[cid] = (int(n), int(total or 0))
        apps: dict[uuid.UUID, int] = {}
        for cid, n in (
            await self.db.execute(
                select(Applicant.cycle_id, func.count())
                .where(Applicant.cycle_id.in_(ids), Applicant.deleted_at.is_(None))
                .group_by(Applicant.cycle_id)
            )
        ).all():
            apps[cid] = int(n)
        return {c: (progs.get(c, (0, 0))[0], apps.get(c, 0), progs.get(c, (0, 0))[1]) for c in ids}

    # ---- cycle programmes -----------------------------------------------------------------------------------------
    async def programs(self, cycle_id: uuid.UUID) -> Sequence[AdmissionCycleProgram]:
        stmt = (
            select(AdmissionCycleProgram)
            .where(AdmissionCycleProgram.cycle_id == cycle_id)
            .order_by(AdmissionCycleProgram.created_at, AdmissionCycleProgram.id)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def program_rows(self, program_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Program]:
        if not program_ids:
            return {}
        rows = (await self.db.execute(select(Program).where(Program.id.in_(list(set(program_ids)))))).scalars().all()
        return {r.id: r for r in rows}

    async def college_rows(self, college_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, College]:
        if not college_ids:
            return {}
        rows = (await self.db.execute(select(College).where(College.id.in_(list(set(college_ids)))))).scalars().all()
        return {r.id: r for r in rows}

    async def program(self, program_id: uuid.UUID) -> Program:
        row = (
            await self.db.execute(select(Program).where(Program.id == program_id, Program.institution_id == self.inst))
        ).scalar_one_or_none()
        if row is None:
            raise APIError(422, ErrorCode.VALIDATION, "Unknown programme", {"field": "program_id"})
        return row

    # ---- seat matrix ------------------------------------------------------------------------------------------------
    async def seat_rows(self, cycle_id: uuid.UUID, *, for_update: bool = False) -> Sequence[SeatMatrix]:
        stmt = select(SeatMatrix).where(SeatMatrix.cycle_id == cycle_id).order_by(SeatMatrix.id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalars().all()

    async def seat_row(self, seat_id: uuid.UUID, *, for_update: bool = False) -> SeatMatrix | None:
        stmt = select(SeatMatrix).where(SeatMatrix.id == seat_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()
