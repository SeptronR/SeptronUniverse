"""Course registrations — Prompts/09 §09.5 ``registration_repository.py`` (``module="registration"``).

Visibility comes from ``registration_scope`` (self via the enrolment → ``Student.user_id``, advisees via the
``BatchSection.class_advisor_staff_id`` / ``class_advisor`` @offering of the term record's section, department /
college / institution with ``registration:view_all``); a registration outside the caller's visibility is a 404.
Items are loaded per page in one query (``items()``) rather than through a mapped relationship.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.repositories.base import BaseRepository
from app.repositories.registration_scope import visible_enrollment_ids


class RegistrationRepository(BaseRepository[CourseRegistration]):
    model = CourseRegistration
    module = "registration"

    def __init__(self, db: AsyncSession, principal: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, institution_id)

    def filtered(
        self,
        *,
        scope: str | None = None,
        term_id: uuid.UUID | None = None,
        status: str | None = None,
        batch_id: uuid.UUID | None = None,
        section_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
        enrollment_ids: Any = None,
    ) -> Select[tuple[CourseRegistration]]:
        stmt = self._base()
        if self.principal is not None:
            stmt = stmt.where(
                CourseRegistration.student_program_enrollment_id.in_(visible_enrollment_ids(self.principal, scope))
            )
        if enrollment_ids is not None:
            stmt = stmt.where(CourseRegistration.student_program_enrollment_id.in_(enrollment_ids))
        if term_id:
            stmt = stmt.where(CourseRegistration.term_id == term_id)
        if status:
            stmt = stmt.where(CourseRegistration.status == status)
        if batch_id or department_id or q:
            sub = select(StudentProgramEnrollment.id).join(Student, Student.id == StudentProgramEnrollment.student_id)
            if batch_id:
                sub = sub.where(StudentProgramEnrollment.batch_id == batch_id)
            if department_id:
                sub = sub.where(StudentProgramEnrollment.department_id == department_id)
            if q:
                like = f"%{q.strip()}%"
                sub = sub.where(
                    or_(
                        Student.registration_number.ilike(like),
                        Student.first_name.ilike(like),
                        Student.last_name.ilike(like),
                    )
                )
            stmt = stmt.where(CourseRegistration.student_program_enrollment_id.in_(sub))
        if section_id:
            stmt = stmt.where(
                CourseRegistration.student_term_record_id.in_(
                    select(StudentTermRecord.id).where(StudentTermRecord.section_id == section_id)
                )
            )
        return stmt

    async def get_visible(self, registration_id: uuid.UUID, *, for_update: bool = False) -> CourseRegistration:
        stmt = self.filtered(scope="all").where(CourseRegistration.id == registration_id)
        if for_update:
            stmt = stmt.with_for_update(of=CourseRegistration)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Registration not found")
        return row

    async def by_id(self, registration_id: uuid.UUID, *, for_update: bool = False) -> CourseRegistration | None:
        stmt = self._base().where(CourseRegistration.id == registration_id)
        if for_update:
            stmt = stmt.with_for_update(of=CourseRegistration)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def for_enrollment(
        self, enrollment_id: uuid.UUID, term_id: uuid.UUID, *, for_update: bool = False
    ) -> CourseRegistration | None:
        stmt = self._base().where(
            CourseRegistration.student_program_enrollment_id == enrollment_id, CourseRegistration.term_id == term_id
        )
        if for_update:
            stmt = stmt.with_for_update(of=CourseRegistration)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def history(self, enrollment_ids: Sequence[uuid.UUID]) -> list[CourseRegistration]:
        if not enrollment_ids:
            return []
        stmt = self._base().where(CourseRegistration.student_program_enrollment_id.in_(list(enrollment_ids)))
        return list((await self.db.execute(stmt.order_by(CourseRegistration.created_at.desc()))).scalars().all())

    async def add(self, row: CourseRegistration) -> CourseRegistration:
        self.db.add(row)
        await self.db.flush()
        return row

    # ---- items -------------------------------------------------------------------------------------------------------
    async def items(self, registration_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[CourseRegistrationItem]]:
        if not registration_ids:
            return {}
        rows = (
            await self.db.execute(
                select(CourseRegistrationItem)
                .where(CourseRegistrationItem.registration_id.in_(list(registration_ids)))
                .order_by(CourseRegistrationItem.added_at)
            )
        ).scalars()
        out: dict[uuid.UUID, list[CourseRegistrationItem]] = {rid: [] for rid in registration_ids}
        for r in rows:
            out.setdefault(r.registration_id, []).append(r)
        return out

    async def item(self, item_id: uuid.UUID, *, for_update: bool = False) -> CourseRegistrationItem:
        stmt = select(CourseRegistrationItem).where(CourseRegistrationItem.id == item_id)
        if self.institution_id is not None:
            stmt = stmt.where(CourseRegistrationItem.institution_id == self.institution_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Registration item not found")
        return row

    async def item_for_offering(
        self, registration_id: uuid.UUID, offering_id: uuid.UUID
    ) -> CourseRegistrationItem | None:
        stmt = select(CourseRegistrationItem).where(
            CourseRegistrationItem.registration_id == registration_id,
            CourseRegistrationItem.offering_id == offering_id,
        )
        return (await self.db.execute(stmt.with_for_update())).scalar_one_or_none()

    async def add_item(self, row: CourseRegistrationItem) -> CourseRegistrationItem:
        self.db.add(row)
        await self.db.flush()
        return row

    async def counts(self, registration_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
        """registration → (live seated items, waitlisted items)."""
        if not registration_ids:
            return {}
        stmt = (
            select(CourseRegistrationItem.registration_id, CourseRegistrationItem.status, func.count())
            .where(CourseRegistrationItem.registration_id.in_(list(registration_ids)))
            .group_by(CourseRegistrationItem.registration_id, CourseRegistrationItem.status)
        )
        out: dict[uuid.UUID, tuple[int, int]] = {}
        for rid, status, n in (await self.db.execute(stmt)).all():
            seated, waiting = out.get(rid, (0, 0))
            if status in ("selected", "confirmed"):
                seated += int(n)
            elif status == "waitlisted":
                waiting += int(n)
            out[rid] = (seated, waiting)
        return out

    async def pending_in_term(self, term_id: uuid.UUID, statuses: Sequence[str]) -> int:
        stmt = select(func.count()).where(
            CourseRegistration.term_id == term_id, CourseRegistration.status.in_(statuses)
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def to_lock(self, term_id: uuid.UUID) -> list[CourseRegistration]:
        stmt = (
            self._base()
            .where(CourseRegistration.term_id == term_id, CourseRegistration.status == "approved")
            .with_for_update(skip_locked=True)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def confirmed_courses(self, enrollment_id: uuid.UUID, term_id: uuid.UUID) -> list[CourseRegistrationItem]:
        stmt = (
            select(CourseRegistrationItem)
            .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
            .where(
                CourseRegistration.student_program_enrollment_id == enrollment_id,
                CourseRegistration.term_id == term_id,
                CourseRegistrationItem.status == "confirmed",
            )
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def live_course_ids(self, enrollment_id: uuid.UUID, exclude_term: uuid.UUID | None = None) -> set[uuid.UUID]:
        """Courses the enrolment has a live (selected / confirmed / waitlisted) item for in any term."""
        stmt = (
            select(CourseRegistrationItem.course_id)
            .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
            .where(
                CourseRegistration.student_program_enrollment_id == enrollment_id,
                CourseRegistrationItem.status.in_(("selected", "confirmed", "waitlisted")),
            )
        )
        if exclude_term is not None:
            stmt = stmt.where(CourseRegistration.term_id != exclude_term)
        return set((await self.db.execute(stmt)).scalars().all())
