"""Holds — Prompts/07 §07.5 ``hold_repository.py`` (``open_holds(enrollment_id, gate)``: a gate is blocked by an open
hold of the gate's own type or of type ``all``; the partial index ``ix_student_holds_open`` serves these lookups)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.students import Student, StudentHold, StudentProgramEnrollment
from app.repositories.student_scope import visible_enrollment_ids


class HoldRepository:
    def __init__(self, db: AsyncSession, principal: Any = None, institution_id: uuid.UUID | None = None):
        self.db, self.principal, self.institution_id = db, principal, institution_id

    async def open_holds(self, enrollment_id: uuid.UUID, gate: str | None = None) -> Sequence[StudentHold]:
        stmt = select(StudentHold).where(
            StudentHold.student_program_enrollment_id == enrollment_id, StudentHold.released_at.is_(None)
        )
        if gate is not None:
            stmt = stmt.where(StudentHold.hold_type.in_((gate, "all")))
        return (await self.db.execute(stmt.order_by(StudentHold.placed_at))).scalars().all()

    async def for_enrollments(
        self, enrollment_ids: Sequence[uuid.UUID], open_only: bool = False
    ) -> Sequence[StudentHold]:
        if not enrollment_ids:
            return []
        stmt = select(StudentHold).where(StudentHold.student_program_enrollment_id.in_(list(enrollment_ids)))
        if open_only:
            stmt = stmt.where(StudentHold.released_at.is_(None))
        return (await self.db.execute(stmt.order_by(StudentHold.placed_at.desc()))).scalars().all()

    async def open_counts(self, enrollment_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not enrollment_ids:
            return {}
        stmt = (
            select(StudentHold.student_program_enrollment_id, func.count())
            .where(
                StudentHold.student_program_enrollment_id.in_(list(enrollment_ids)), StudentHold.released_at.is_(None)
            )
            .group_by(StudentHold.student_program_enrollment_id)
        )
        return {e: int(n) for e, n in (await self.db.execute(stmt)).all()}

    async def get(self, hold_id: uuid.UUID, *, for_update: bool = False) -> StudentHold | None:
        stmt = select(StudentHold).where(StudentHold.id == hold_id)
        if self.principal is not None:
            stmt = stmt.where(StudentHold.student_program_enrollment_id.in_(visible_enrollment_ids(self.principal)))
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    def queue(
        self, *, status: str | None, hold_type: str | None, q: str | None, scope: str | None = "all"
    ) -> Select[tuple[StudentHold]]:
        stmt = select(StudentHold).join(
            StudentProgramEnrollment, StudentProgramEnrollment.id == StudentHold.student_program_enrollment_id
        )
        if self.institution_id is not None:
            stmt = stmt.where(StudentHold.institution_id == self.institution_id)
        if self.principal is not None:
            stmt = stmt.where(
                StudentHold.student_program_enrollment_id.in_(visible_enrollment_ids(self.principal, scope))
            )
        if status == "open":
            stmt = stmt.where(StudentHold.released_at.is_(None))
        elif status == "released":
            stmt = stmt.where(StudentHold.released_at.is_not(None))
        if hold_type:
            stmt = stmt.where(StudentHold.hold_type == hold_type)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                StudentProgramEnrollment.student_id.in_(
                    select(Student.id).where(
                        (Student.first_name + " " + func.coalesce(Student.last_name, "")).ilike(like)
                        | Student.registration_number.ilike(like)
                    )
                )
            )
        return stmt

    async def paginate_queue(
        self, stmt: Select[tuple[StudentHold]], offset: int, limit: int
    ) -> tuple[Sequence[StudentHold], int]:
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = (
            (await self.db.execute(stmt.order_by(StudentHold.placed_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return rows, total

    async def release_reasons(self, hold_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        """The release reason of released holds — kept in the audit row (the DDL has no column for it)."""
        if not hold_ids:
            return {}
        rows = (
            await self.db.execute(
                text(
                    "SELECT record_id, new_values->>'release_reason' AS reason FROM audit_logs "
                    "WHERE record_type = 'student_hold' AND action = 'release' "
                    "AND record_id = ANY(CAST(:ids AS uuid[])) ORDER BY occurred_at"
                ),
                {"ids": [str(i) for i in hold_ids]},
            )
        ).all()
        return {uuid.UUID(str(r.record_id)): r.reason for r in rows if r.reason}

    async def add(self, obj: StudentHold) -> StudentHold:
        self.db.add(obj)
        await self.db.flush()
        return obj
