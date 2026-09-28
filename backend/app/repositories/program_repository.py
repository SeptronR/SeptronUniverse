"""Programmes and programme-regulation bindings — Prompts/05 §05.5 ``program_repository`` (``module="programs"``;
scope columns institution / college / faculty / department). Reads are institution-wide (Prompts/05 "Visibility
rules"), so list queries do not apply ``visible()``; writes are narrowed by the services' unit scope."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.academic import Batch, Program, ProgramRegulation, Regulation
from app.repositories.base import BaseRepository


class ProgramRepository(BaseRepository[Program]):
    model = Program
    module = "programs"

    def filtered(
        self,
        *,
        college_ids: Sequence[uuid.UUID] | None = None,
        department_id: uuid.UUID | None = None,
        faculty_id: uuid.UUID | None = None,
        level: str | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> Select[tuple[Program]]:
        stmt = self._base()
        if college_ids is not None:
            stmt = stmt.where(Program.college_id.in_(college_ids))
        if department_id:
            stmt = stmt.where(Program.department_id == department_id)
        if faculty_id:
            stmt = stmt.where(Program.faculty_id == faculty_id)
        if level:
            stmt = stmt.where(Program.level == level)
        if status:
            stmt = stmt.where(Program.status == status)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(Program.name).like(like), func.lower(Program.code).like(like)))
        return stmt

    async def get_program(self, program_id: uuid.UUID) -> Program:
        obj = (await self.db.execute(self._base().where(Program.id == program_id))).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Programme not found")
        return obj

    async def by_code(self, institution_id: uuid.UUID, college_id: uuid.UUID, code: str) -> Program | None:
        return (
            await self.db.execute(
                select(Program).where(
                    Program.institution_id == institution_id,
                    Program.college_id == college_id,
                    func.upper(Program.code) == code.upper(),
                    Program.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def active_batch_count(self, program_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Batch)
                    .where(Batch.program_id == program_id, Batch.status == "active", Batch.deleted_at.is_(None))
                )
            ).scalar_one()
        )

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Program]:
        if not ids:
            return {}
        rows = (await self.db.execute(select(Program).where(Program.id.in_(list(ids))))).scalars().all()
        return {p.id: p for p in rows}


class ProgramRegulationRepository(BaseRepository[ProgramRegulation]):
    model = ProgramRegulation
    module = "curriculum"

    def filtered(
        self,
        *,
        program_id: uuid.UUID | None = None,
        regulation_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> Select[tuple[ProgramRegulation]]:
        stmt = self._base()
        if program_id:
            stmt = stmt.where(ProgramRegulation.program_id == program_id)
        if regulation_id:
            stmt = stmt.where(ProgramRegulation.regulation_id == regulation_id)
        if status:
            stmt = stmt.where(ProgramRegulation.status == status)
        return stmt

    async def get_binding(self, pr_id: uuid.UUID, *, for_update: bool = False) -> ProgramRegulation:
        stmt = self._base().where(ProgramRegulation.id == pr_id)
        if for_update:
            stmt = stmt.with_for_update()
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Programme-regulation not found")
        return obj

    async def find(self, program_id: uuid.UUID, regulation_id: uuid.UUID) -> ProgramRegulation | None:
        return (
            await self.db.execute(
                self._base().where(
                    ProgramRegulation.program_id == program_id, ProgramRegulation.regulation_id == regulation_id
                )
            )
        ).scalar_one_or_none()

    async def for_regulation(self, regulation_id: uuid.UUID) -> Sequence[ProgramRegulation]:
        return (
            (await self.db.execute(self._base().where(ProgramRegulation.regulation_id == regulation_id)))
            .scalars()
            .all()
        )

    async def for_program(self, program_id: uuid.UUID) -> Sequence[tuple[ProgramRegulation, Regulation]]:
        rows = (
            await self.db.execute(
                select(ProgramRegulation, Regulation)
                .join(Regulation, Regulation.id == ProgramRegulation.regulation_id)
                .where(ProgramRegulation.program_id == program_id, ProgramRegulation.deleted_at.is_(None))
                .order_by(Regulation.effective_from_admission_year.desc())
            )
        ).all()
        return [(r[0], r[1]) for r in rows]
