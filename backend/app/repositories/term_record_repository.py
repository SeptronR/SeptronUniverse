"""Term records — Prompts/07 §07.5 ``term_record_repository.py`` (``get_or_create(enrollment, term)`` is idempotent on
the DDL's ``UNIQUE (student_program_enrollment_id, term_id)``; the "next term" after a term is the following academic
term of the same college — or institution-wide — by start date)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academic import AcademicTerm, AcademicYear
from app.models.students import StudentTermRecord


class TermRecordRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID | None = None):
        self.db, self.institution_id = db, institution_id

    async def get_or_create(
        self,
        enrollment_id: uuid.UUID,
        term_id: uuid.UUID,
        term_number: int,
        *,
        section_id: uuid.UUID | None = None,
        roll_number: str | None = None,
        status: str = "pending_registration",
    ) -> tuple[StudentTermRecord, bool]:
        stmt = select(StudentTermRecord).where(
            StudentTermRecord.student_program_enrollment_id == enrollment_id, StudentTermRecord.term_id == term_id
        )
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is not None:
            return row, False
        row = StudentTermRecord(
            institution_id=self.institution_id,
            student_program_enrollment_id=enrollment_id,
            term_id=term_id,
            term_number=term_number,
            section_id=section_id,
            roll_number=roll_number,
            status=status,
        )
        self.db.add(row)
        await self.db.flush()
        return row, True

    async def for_enrollment(self, enrollment_id: uuid.UUID) -> Sequence[StudentTermRecord]:
        stmt = (
            select(StudentTermRecord)
            .where(StudentTermRecord.student_program_enrollment_id == enrollment_id)
            .order_by(StudentTermRecord.term_number, StudentTermRecord.created_at)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def latest_for(self, enrollment_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, StudentTermRecord]:
        if not enrollment_ids:
            return {}
        stmt = (
            select(StudentTermRecord)
            .where(StudentTermRecord.student_program_enrollment_id.in_(list(enrollment_ids)))
            .order_by(StudentTermRecord.term_number.desc(), StudentTermRecord.created_at.desc())
        )
        out: dict[uuid.UUID, StudentTermRecord] = {}
        for row in (await self.db.execute(stmt)).scalars():
            out.setdefault(row.student_program_enrollment_id, row)
        return out

    async def at_number(
        self, enrollment_ids: Sequence[uuid.UUID], term_number: int, *, for_update: bool = False
    ) -> dict[uuid.UUID, StudentTermRecord]:
        if not enrollment_ids:
            return {}
        stmt = select(StudentTermRecord).where(
            StudentTermRecord.student_program_enrollment_id.in_(list(enrollment_ids)),
            StudentTermRecord.term_number == term_number,
        )
        if for_update:
            stmt = stmt.with_for_update()
        out: dict[uuid.UUID, StudentTermRecord] = {}
        for row in (await self.db.execute(stmt.order_by(StudentTermRecord.created_at.desc()))).scalars():
            out.setdefault(row.student_program_enrollment_id, row)
        return out

    async def count_at(self, enrollment_ids: Sequence[uuid.UUID], term_number: int) -> int:
        if not enrollment_ids:
            return 0
        stmt = select(func.count()).where(
            StudentTermRecord.student_program_enrollment_id.in_(list(enrollment_ids)),
            StudentTermRecord.term_number == term_number,
        )
        return int((await self.db.execute(stmt)).scalar_one())

    # ---- academic terms -----------------------------------------------------------------------------------------
    async def term(self, term_id: uuid.UUID) -> AcademicTerm | None:
        return (await self.db.execute(select(AcademicTerm).where(AcademicTerm.id == term_id))).scalar_one_or_none()

    async def term_meta(self, term_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
        """term id → (term name, academic year name)."""
        clean = [t for t in term_ids if t]
        if not clean:
            return {}
        rows = (
            await self.db.execute(
                select(AcademicTerm.id, AcademicTerm.name, AcademicYear.name)
                .join(AcademicYear, AcademicYear.id == AcademicTerm.academic_year_id)
                .where(AcademicTerm.id.in_(clean))
            )
        ).all()
        return {r[0]: (r[1], r[2]) for r in rows}

    async def next_term(self, after: AcademicTerm, college_id: uuid.UUID | None) -> AcademicTerm | None:
        """The academic term that follows ``after`` for the college (its own terms first, then institution-wide)."""
        stmt = (
            select(AcademicTerm)
            .where(
                AcademicTerm.institution_id == after.institution_id,
                AcademicTerm.deleted_at.is_(None),
                AcademicTerm.start_date > after.start_date,
                (
                    or_(AcademicTerm.college_id.is_(None), AcademicTerm.college_id == college_id)
                    if college_id is not None
                    else AcademicTerm.college_id.is_(None)
                ),
            )
            .order_by(AcademicTerm.start_date, AcademicTerm.college_id.is_(None))
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def year_of(self, term: AcademicTerm) -> AcademicYear | None:
        return (
            await self.db.execute(select(AcademicYear).where(AcademicYear.id == term.academic_year_id))
        ).scalar_one_or_none()


def as_float(value: Any) -> float | None:
    return None if value is None else float(value)
