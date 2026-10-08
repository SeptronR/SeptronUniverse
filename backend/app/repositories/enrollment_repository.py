"""Programme enrolments — Prompts/07 §07.5 ``enrollment_repository.py`` (``module="students"`` — enrolments share the
students visibility: an enrolment is visible when its student is). Backlog counts read ``student_arrears`` (Phase 09
owns the table and its model; Phase 07 only counts open rows for the detention rule)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import case, func, select, text

from app.core.errors import APIError, ErrorCode
from app.enums.students import OPEN_ENROLLMENT
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.base import BaseRepository
from app.repositories.student_scope import visible_student_ids

# open enrolments first, then the most recent one (a student's "current" enrolment)
_ORDER = (
    case((StudentProgramEnrollment.status.in_(OPEN_ENROLLMENT), 0), else_=1),
    StudentProgramEnrollment.admission_date.desc(),
    StudentProgramEnrollment.created_at.desc(),
)


class EnrollmentRepository(BaseRepository[StudentProgramEnrollment]):
    model = StudentProgramEnrollment
    module = "students"

    async def get_visible(self, enrollment_id: uuid.UUID, *, for_update: bool = False) -> StudentProgramEnrollment:
        stmt = self._base().where(StudentProgramEnrollment.id == enrollment_id)
        if self.principal is not None:
            stmt = stmt.where(StudentProgramEnrollment.student_id.in_(visible_student_ids(self.principal)))
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found")
        return row

    async def by_id(self, enrollment_id: uuid.UUID, *, for_update: bool = False) -> StudentProgramEnrollment | None:
        stmt = self._base().where(StudentProgramEnrollment.id == enrollment_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def for_student(self, student_id: uuid.UUID) -> Sequence[StudentProgramEnrollment]:
        stmt = self._base().where(StudentProgramEnrollment.student_id == student_id).order_by(*_ORDER)
        return (await self.db.execute(stmt)).scalars().all()

    async def current(self, student_id: uuid.UUID, *, for_update: bool = False) -> StudentProgramEnrollment | None:
        stmt = self._base().where(StudentProgramEnrollment.student_id == student_id).order_by(*_ORDER).limit(1)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def open_for(self, student_id: uuid.UUID, *, for_update: bool = False) -> StudentProgramEnrollment | None:
        stmt = self._base().where(
            StudentProgramEnrollment.student_id == student_id,
            StudentProgramEnrollment.status.in_(OPEN_ENROLLMENT),
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def current_for(self, student_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, StudentProgramEnrollment]:
        if not student_ids:
            return {}
        stmt = self._base().where(StudentProgramEnrollment.student_id.in_(list(student_ids))).order_by(*_ORDER)
        out: dict[uuid.UUID, StudentProgramEnrollment] = {}
        for row in (await self.db.execute(stmt)).scalars():
            out.setdefault(row.student_id, row)
        return out

    async def exists(self, student_id: uuid.UUID, program_id: uuid.UUID, batch_id: uuid.UUID) -> bool:
        stmt = select(StudentProgramEnrollment.id).where(
            StudentProgramEnrollment.student_id == student_id,
            StudentProgramEnrollment.program_id == program_id,
            StudentProgramEnrollment.batch_id == batch_id,
        )
        return (await self.db.execute(stmt)).first() is not None

    async def of_batch(
        self, batch_id: uuid.UUID, statuses: Sequence[str] | None = None, *, for_update: bool = False
    ) -> Sequence[tuple[StudentProgramEnrollment, Student]]:
        stmt = (
            select(StudentProgramEnrollment, Student)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(
                StudentProgramEnrollment.batch_id == batch_id,
                StudentProgramEnrollment.deleted_at.is_(None),
                Student.deleted_at.is_(None),
            )
            .order_by(Student.registration_number)
        )
        if statuses:
            stmt = stmt.where(StudentProgramEnrollment.status.in_(list(statuses)))
        if for_update:
            stmt = stmt.with_for_update(of=StudentProgramEnrollment)
        return [(e, s) for e, s in (await self.db.execute(stmt)).all()]

    async def backlog_counts(self, enrollment_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Open arrears per enrolment (``student_arrears.status IN ('open','registered')`` — Phases 09/15 fill it)."""
        if not enrollment_ids:
            return {}
        rows = (
            await self.db.execute(
                text(
                    "SELECT student_program_enrollment_id AS e, COUNT(*) AS n FROM student_arrears "
                    "WHERE student_program_enrollment_id = ANY(CAST(:ids AS uuid[])) AND status IN ('open','registered') "
                    "GROUP BY student_program_enrollment_id"
                ),
                {"ids": [str(i) for i in enrollment_ids]},
            )
        ).all()
        return {uuid.UUID(str(r.e)): int(r.n) for r in rows}

    async def counts_by_batch(self, batch_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
        if not batch_ids:
            return {}
        stmt = (
            select(StudentProgramEnrollment.batch_id, StudentProgramEnrollment.status, func.count())
            .where(
                StudentProgramEnrollment.batch_id.in_(list(batch_ids)), StudentProgramEnrollment.deleted_at.is_(None)
            )
            .group_by(StudentProgramEnrollment.batch_id, StudentProgramEnrollment.status)
        )
        out: dict[uuid.UUID, dict[str, int]] = {}
        for b, st, n in (await self.db.execute(stmt)).all():
            out.setdefault(b, {})[st] = int(n)
        return out


def first(rows: Sequence[Any]) -> Any:
    return rows[0] if rows else None
