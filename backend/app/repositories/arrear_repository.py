"""Arrears register — Prompts/09 §09.5 ``arrear_repository.py``.

``open_for(enrollment)`` lists the arrears a student can register for (``open``); lists are narrowed by the
registration visibility (self / advisees / department / college / all — ``registration_scope``) or, for the
``/students/{id}/arrears`` route, by the student the caller already sees.
"""

import uuid
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.registration import StudentArrear
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.registration_scope import visible_enrollment_ids


class ArrearRepository:
    def __init__(self, db: AsyncSession, principal: Any = None, institution_id: uuid.UUID | None = None):
        self.db, self.principal, self.inst = db, principal, institution_id

    def _base(self) -> Select[tuple[StudentArrear]]:
        stmt = select(StudentArrear)
        if self.inst is not None:
            stmt = stmt.where(StudentArrear.institution_id == self.inst)
        return stmt

    def filtered(
        self,
        *,
        scope: str | None = None,
        status: str | None = None,
        enrollment_id: uuid.UUID | None = None,
        course_id: uuid.UUID | None = None,
        q: str | None = None,
        visible: bool = True,
    ) -> Select[tuple[StudentArrear]]:
        stmt = self._base()
        if visible and self.principal is not None:
            stmt = stmt.where(
                StudentArrear.student_program_enrollment_id.in_(visible_enrollment_ids(self.principal, scope))
            )
        if status:
            stmt = stmt.where(StudentArrear.status == status)
        if enrollment_id:
            stmt = stmt.where(StudentArrear.student_program_enrollment_id == enrollment_id)
        if course_id:
            stmt = stmt.where(StudentArrear.course_id == course_id)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                StudentArrear.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(
                        or_(
                            Student.registration_number.ilike(like),
                            Student.first_name.ilike(like),
                            Student.last_name.ilike(like),
                        )
                    )
                )
            )
        return stmt

    async def get(self, arrear_id: uuid.UUID, *, for_update: bool = False, visible: bool = True) -> StudentArrear:
        stmt = self.filtered(scope="all", visible=visible).where(StudentArrear.id == arrear_id)
        if for_update:
            stmt = stmt.with_for_update(of=StudentArrear)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Arrear not found")
        return row

    async def open_for(self, enrollment_id: uuid.UUID, statuses: tuple[str, ...] = ("open",)) -> list[StudentArrear]:
        stmt = self._base().where(
            StudentArrear.student_program_enrollment_id == enrollment_id, StudentArrear.status.in_(statuses)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def for_course(
        self, enrollment_id: uuid.UUID, course_id: uuid.UUID, *, for_update: bool = False
    ) -> StudentArrear | None:
        stmt = self._base().where(
            StudentArrear.student_program_enrollment_id == enrollment_id, StudentArrear.course_id == course_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def add(self, row: StudentArrear) -> StudentArrear:
        self.db.add(row)
        await self.db.flush()
        return row
