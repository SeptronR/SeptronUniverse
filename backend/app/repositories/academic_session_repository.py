"""Academic years and terms — Prompts/03 §03.5 ``academic_session_repository``.

``get_current_term(college_id)`` answers the college's current term and falls back to the institution-wide one
(``college_id`` NULL). Overlap checks compare closed date ranges inside the same scope (``college_id IS NOT DISTINCT
FROM``). ``clear_current_*`` run before a new row is flagged so the partial unique index ``one_current_year`` never
sees two current rows in one transaction.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, and_, or_, select, update

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm, AcademicYear
from app.models.platform import College
from app.repositories.base import BaseRepository


def _same_scope(col: object, college_id: uuid.UUID | None) -> object:
    return col.is_(None) if college_id is None else col == college_id  # type: ignore[attr-defined]


def _live_college(column: Any) -> Any:
    """Institution-wide rows, or rows whose college is not soft-deleted."""
    return or_(column.is_(None), column.in_(select(College.id).where(College.deleted_at.is_(None))))


class AcademicYearRepository(BaseRepository[AcademicYear]):
    model = AcademicYear
    module = "sessions"

    def filtered(
        self, college_id: uuid.UUID | None = None, include_institution: bool = True, current_only: bool = False
    ) -> Select[tuple[AcademicYear]]:
        # years of a soft-deleted college are history, not choices (Phase 03 UI walk, 2026-10-05)
        stmt = self._base().where(_live_college(AcademicYear.college_id))
        if college_id is not None:
            stmt = stmt.where(
                or_(AcademicYear.college_id == college_id, AcademicYear.college_id.is_(None))
                if include_institution
                else AcademicYear.college_id == college_id
            )
        if current_only:
            stmt = stmt.where(AcademicYear.is_current.is_(True))
        return stmt.order_by(AcademicYear.start_date.desc())

    async def get_one(self, year_id: uuid.UUID, *, for_update: bool = False) -> AcademicYear:
        stmt = self._base().where(AcademicYear.id == year_id)
        if for_update:
            stmt = stmt.with_for_update()
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Academic year not found")
        return obj

    async def by_name(self, institution_id: uuid.UUID, college_id: uuid.UUID | None, name: str) -> AcademicYear | None:
        return (
            await self.db.execute(
                select(AcademicYear).where(
                    AcademicYear.institution_id == institution_id,
                    _same_scope(AcademicYear.college_id, college_id),  # type: ignore[arg-type]
                    AcademicYear.name == name,
                )
            )
        ).scalar_one_or_none()

    async def overlapping(
        self,
        institution_id: uuid.UUID,
        college_id: uuid.UUID | None,
        start: date,
        end: date,
        exclude: uuid.UUID | None = None,
    ) -> AcademicYear | None:
        stmt = self._base().where(
            AcademicYear.institution_id == institution_id,
            _same_scope(AcademicYear.college_id, college_id),  # type: ignore[arg-type]
            AcademicYear.start_date <= end,
            AcademicYear.end_date >= start,
        )
        if exclude is not None:
            stmt = stmt.where(AcademicYear.id != exclude)
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    async def current(self, institution_id: uuid.UUID, college_id: uuid.UUID | None) -> AcademicYear | None:
        return (
            await self.db.execute(
                self._base().where(
                    AcademicYear.institution_id == institution_id,
                    _same_scope(AcademicYear.college_id, college_id),  # type: ignore[arg-type]
                    AcademicYear.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def clear_current(self, institution_id: uuid.UUID, college_id: uuid.UUID | None) -> None:
        await self.db.execute(
            update(AcademicYear)
            .where(
                AcademicYear.institution_id == institution_id,
                _same_scope(AcademicYear.college_id, college_id),  # type: ignore[arg-type]
                AcademicYear.is_current.is_(True),
            )
            .values(is_current=False)
        )
        await self.db.flush()


class AcademicTermRepository(BaseRepository[AcademicTerm]):
    model = AcademicTerm
    module = "sessions"

    def filtered(
        self,
        *,
        academic_year_id: uuid.UUID | None = None,
        college_id: uuid.UUID | None = None,
        status: str | None = None,
        current_only: bool = False,
    ) -> Select[tuple[AcademicTerm]]:
        stmt = self._base().where(_live_college(AcademicTerm.college_id))
        if academic_year_id:
            stmt = stmt.where(AcademicTerm.academic_year_id == academic_year_id)
        if college_id is not None:
            stmt = stmt.where(or_(AcademicTerm.college_id == college_id, AcademicTerm.college_id.is_(None)))
        if status:
            stmt = stmt.where(AcademicTerm.status == status)
        if current_only:
            stmt = stmt.where(AcademicTerm.is_current.is_(True))
        return stmt.order_by(AcademicTerm.start_date.desc(), AcademicTerm.sequence)

    async def get_one(self, term_id: uuid.UUID, *, for_update: bool = False) -> AcademicTerm:
        stmt = self._base().where(AcademicTerm.id == term_id)
        if for_update:
            stmt = stmt.with_for_update()
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Academic term not found")
        return obj

    async def of_years(self, year_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[AcademicTerm]]:
        if not year_ids:
            return {}
        rows = (
            (
                await self.db.execute(
                    self._base()
                    .where(AcademicTerm.academic_year_id.in_(year_ids))
                    .order_by(AcademicTerm.sequence, AcademicTerm.start_date)
                )
            )
            .scalars()
            .all()
        )
        out: dict[uuid.UUID, list[AcademicTerm]] = {}
        for t in rows:
            out.setdefault(t.academic_year_id, []).append(t)
        return out

    async def overlapping(
        self, year_id: uuid.UUID, start: date, end: date, exclude: uuid.UUID | None = None
    ) -> AcademicTerm | None:
        stmt = self._base().where(
            AcademicTerm.academic_year_id == year_id,
            and_(AcademicTerm.start_date <= end, AcademicTerm.end_date >= start),
        )
        if exclude is not None:
            stmt = stmt.where(AcademicTerm.id != exclude)
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    async def duplicate(self, year_id: uuid.UUID, term_type: str, sequence: int) -> AcademicTerm | None:
        return (
            await self.db.execute(
                select(AcademicTerm).where(
                    AcademicTerm.academic_year_id == year_id,
                    AcademicTerm.term_type == term_type,
                    AcademicTerm.sequence == sequence,
                )
            )
        ).scalar_one_or_none()

    async def get_current_term(self, institution_id: uuid.UUID, college_id: uuid.UUID | None) -> AcademicTerm | None:
        """The college's current term, else the institution-wide current term."""
        if college_id is not None:
            row = (
                await self.db.execute(
                    self._base().where(
                        AcademicTerm.institution_id == institution_id,
                        AcademicTerm.college_id == college_id,
                        AcademicTerm.is_current.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                return row
        return (
            await self.db.execute(
                self._base().where(
                    AcademicTerm.institution_id == institution_id,
                    AcademicTerm.college_id.is_(None),
                    AcademicTerm.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def clear_current(self, institution_id: uuid.UUID, college_id: uuid.UUID | None) -> None:
        await self.db.execute(
            update(AcademicTerm)
            .where(
                AcademicTerm.institution_id == institution_id,
                _same_scope(AcademicTerm.college_id, college_id),  # type: ignore[arg-type]
                AcademicTerm.is_current.is_(True),
            )
            .values(is_current=False)
        )
        await self.db.flush()

    async def due_for_auto_status(self, today: date) -> Sequence[AcademicTerm]:
        """Terms whose dates say they should advance (Beat ``terms.auto_status``; platform session, all tenants)."""
        return (
            (
                await self.db.execute(
                    select(AcademicTerm).where(
                        AcademicTerm.deleted_at.is_(None),
                        or_(
                            and_(
                                AcademicTerm.status == "planned",
                                AcademicTerm.registration_start.is_not(None),
                                AcademicTerm.registration_start <= today,
                            ),
                            and_(AcademicTerm.status == "registration", AcademicTerm.start_date <= today),
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
