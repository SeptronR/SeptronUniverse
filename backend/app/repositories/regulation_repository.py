"""Regulations — Prompts/05 §05.5 ``regulation_repository`` (``module="regulations"``; ``with_courses``)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.academic import ProgramRegulation, Regulation
from app.models.curriculum import Course
from app.repositories.base import BaseRepository


class RegulationRepository(BaseRepository[Regulation]):
    model = Regulation
    module = "regulations"

    def filtered(
        self,
        *,
        college_ids: Sequence[uuid.UUID] | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> Select[tuple[Regulation]]:
        stmt = self._base()
        if college_ids is not None:
            stmt = stmt.where(or_(Regulation.college_id.in_(college_ids), Regulation.college_id.is_(None)))
        if status:
            stmt = stmt.where(Regulation.status == status)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(Regulation.name).like(like), func.lower(Regulation.code).like(like)))
        return stmt

    async def get_regulation(self, regulation_id: uuid.UUID, *, for_update: bool = False) -> Regulation:
        stmt = self._base().where(Regulation.id == regulation_id)
        if for_update:
            stmt = stmt.with_for_update()
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Regulation not found")
        return obj

    async def by_code(self, institution_id: uuid.UUID, college_id: uuid.UUID | None, code: str) -> Regulation | None:
        stmt = select(Regulation).where(
            Regulation.institution_id == institution_id,
            func.upper(Regulation.code) == code.upper(),
            Regulation.deleted_at.is_(None),
        )
        stmt = stmt.where(
            Regulation.college_id.is_(None) if college_id is None else Regulation.college_id == college_id
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def with_courses(self, regulation_id: uuid.UUID) -> tuple[Regulation, Sequence[Course]]:
        reg = await self.get_regulation(regulation_id)
        courses = (
            (
                await self.db.execute(
                    select(Course)
                    .where(Course.regulation_id == regulation_id, Course.deleted_at.is_(None))
                    .order_by(Course.code)
                )
            )
            .scalars()
            .all()
        )
        return reg, courses

    async def predecessor(self, reg: Regulation) -> Regulation | None:
        """The regulation this one superseded (``superseded_by_id`` → reg), else the latest older one of the same
        college scope (for a draft clone whose source is still active)."""
        stmt = self._base().where(Regulation.superseded_by_id == reg.id)
        prev = (await self.db.execute(stmt)).scalars().first()
        if prev is not None:
            return prev
        source_id = await self.clone_source(reg)
        if source_id is not None:
            return (await self.db.execute(self._base().where(Regulation.id == source_id))).scalar_one_or_none()
        stmt = (
            self._base()
            .where(
                Regulation.id != reg.id,
                Regulation.effective_from_admission_year <= reg.effective_from_admission_year,
                Regulation.created_at < reg.created_at,
                Regulation.college_id.is_(None) if reg.college_id is None else Regulation.college_id == reg.college_id,
            )
            .order_by(Regulation.effective_from_admission_year.desc(), Regulation.created_at.desc())
        )
        return (await self.db.execute(stmt)).scalars().first()

    async def clone_source(self, reg: Regulation) -> uuid.UUID | None:
        """``rules`` is a validated document, so the clone's source id travels in the audit trail instead: the
        ``clone`` audit row of the new regulation records ``source_id``."""
        from sqlalchemy import text

        row = (
            await self.db.execute(
                text(
                    "SELECT new_values->>'source_id' FROM audit_logs WHERE record_type = 'regulation' "
                    "AND record_id = :r AND action = 'clone' ORDER BY occurred_at DESC LIMIT 1"
                ),
                {"r": reg.id},
            )
        ).first()
        return uuid.UUID(row[0]) if row and row[0] else None

    async def counts(self, ids: Sequence[uuid.UUID]) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
        if not ids:
            return {}, {}
        courses = (
            await self.db.execute(
                select(Course.regulation_id, func.count())
                .where(Course.regulation_id.in_(list(ids)), Course.deleted_at.is_(None))
                .group_by(Course.regulation_id)
            )
        ).all()
        programs = (
            await self.db.execute(
                select(ProgramRegulation.regulation_id, func.count())
                .where(ProgramRegulation.regulation_id.in_(list(ids)), ProgramRegulation.deleted_at.is_(None))
                .group_by(ProgramRegulation.regulation_id)
            )
        ).all()
        return {r: int(n) for r, n in courses}, {r: int(n) for r, n in programs}

    async def codes(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
        """id → (code, status)."""
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(Regulation.id, Regulation.code, Regulation.status).where(Regulation.id.in_(list(ids)))
            )
        ).all()
        return {r[0]: (r[1], r[2]) for r in rows}
