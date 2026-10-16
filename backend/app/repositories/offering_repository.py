"""Course offerings — Prompts/09 §09.5 ``offering_repository.py`` (``module="offerings"``).

Offerings are readable institution-wide by every holder of ``offerings:view`` (staff); students reach them through the
catalog only. Filters: term / college / department / course / faculty / status / text. Seat changes lock the offering
row ``FOR UPDATE`` (``get_one(..., for_update=True)`` / ``lock``) so concurrent registrations never exceed
``max_seats``. ``roster()`` lists the live items of an offering with the student's identity (no PII beyond name and
registration number).
"""

import uuid
from collections.abc import Sequence
from typing import Any, TypeVar

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.academic import Batch, BatchSection
from app.models.hr import Staff
from app.models.offerings import CourseOffering, CourseOfferingFaculty, CourseOfferingTarget
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.repositories.base import BaseRepository
from app.repositories.registration_scope import taught_offering_ids

T = TypeVar("T")


class OfferingRepository(BaseRepository[CourseOffering]):
    model = CourseOffering
    module = "offerings"

    def __init__(self, db: AsyncSession, principal: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, institution_id)

    # ---- reads -------------------------------------------------------------------------------------------------------
    def filtered(
        self,
        *,
        term_id: uuid.UUID | None = None,
        college_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        department_ids: Sequence[uuid.UUID] | None = None,
        course_id: uuid.UUID | None = None,
        staff_id: uuid.UUID | None = None,
        status: str | None = None,
        q: str | None = None,
        mine: bool = False,
        include_cancelled: bool = True,
    ) -> Select[tuple[CourseOffering]]:
        from app.models.curriculum import Course

        stmt = self._base()
        if term_id:
            stmt = stmt.where(CourseOffering.term_id == term_id)
        if college_id:
            stmt = stmt.where(CourseOffering.college_id == college_id)
        if department_id:
            stmt = stmt.where(CourseOffering.department_id == department_id)
        if department_ids is not None:
            stmt = stmt.where(CourseOffering.department_id.in_(list(department_ids)))
        if course_id:
            stmt = stmt.where(CourseOffering.course_id == course_id)
        if status:
            stmt = stmt.where(CourseOffering.status == status)
        elif not include_cancelled:
            stmt = stmt.where(CourseOffering.status != "cancelled")
        if staff_id:
            stmt = stmt.where(
                CourseOffering.id.in_(
                    select(CourseOfferingFaculty.offering_id).where(CourseOfferingFaculty.staff_id == staff_id)
                )
            )
        if mine and self.principal is not None:
            stmt = stmt.where(CourseOffering.id.in_(taught_offering_ids(self.principal)))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                CourseOffering.course_id.in_(
                    select(Course.id).where(or_(Course.code.ilike(like), Course.title.ilike(like)))
                )
            )
        return stmt

    async def get_one(self, offering_id: uuid.UUID, *, for_update: bool = False) -> CourseOffering:
        stmt = self._base().where(CourseOffering.id == offering_id)
        if for_update:
            stmt = stmt.with_for_update(of=CourseOffering)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course offering not found")
        return row

    async def lock(self, offering_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, CourseOffering]:
        """Lock several offerings ``FOR UPDATE`` in id order (no deadlocks between concurrent bulk operations)."""
        if not offering_ids:
            return {}
        ids = sorted(set(offering_ids), key=str)
        stmt = self._base().where(CourseOffering.id.in_(ids)).order_by(CourseOffering.id).with_for_update()
        return {o.id: o for o in (await self.db.execute(stmt)).scalars().all()}

    async def find(self, term_id: uuid.UUID, course_id: uuid.UUID, section_code: str) -> CourseOffering | None:
        stmt = self._base().where(
            CourseOffering.term_id == term_id,
            CourseOffering.course_id == course_id,
            CourseOffering.section_code == section_code,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def for_courses(
        self, term_id: uuid.UUID, course_ids: Sequence[uuid.UUID], *, statuses: Sequence[str] | None = None
    ) -> list[CourseOffering]:
        if not course_ids:
            return []
        stmt = self._base().where(CourseOffering.term_id == term_id, CourseOffering.course_id.in_(list(course_ids)))
        if statuses:
            stmt = stmt.where(CourseOffering.status.in_(list(statuses)))
        return list((await self.db.execute(stmt.order_by(CourseOffering.section_code))).scalars().all())

    async def of_term(self, term_id: uuid.UUID) -> list[CourseOffering]:
        stmt = self._base().where(CourseOffering.term_id == term_id)
        return list((await self.db.execute(stmt)).scalars().all())

    async def faculty(self, offering_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[CourseOfferingFaculty]]:
        if not offering_ids:
            return {}
        rows = (
            await self.db.execute(
                select(CourseOfferingFaculty)
                .where(CourseOfferingFaculty.offering_id.in_(list(offering_ids)))
                .order_by(CourseOfferingFaculty.created_at)
            )
        ).scalars()
        out: dict[uuid.UUID, list[CourseOfferingFaculty]] = {}
        for r in rows:
            out.setdefault(r.offering_id, []).append(r)
        return out

    async def targets(self, offering_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[CourseOfferingTarget]]:
        if not offering_ids:
            return {}
        rows = (
            await self.db.execute(
                select(CourseOfferingTarget).where(CourseOfferingTarget.offering_id.in_(list(offering_ids)))
            )
        ).scalars()
        out: dict[uuid.UUID, list[CourseOfferingTarget]] = {}
        for r in rows:
            out.setdefault(r.offering_id, []).append(r)
        return out

    async def targeted_at(
        self, term_id: uuid.UUID, batch_id: uuid.UUID, section_id: uuid.UUID | None
    ) -> set[uuid.UUID]:
        """Offerings of the term targeted at the batch (whole batch or the given section)."""
        stmt = (
            select(CourseOfferingTarget.offering_id)
            .join(CourseOffering, CourseOffering.id == CourseOfferingTarget.offering_id)
            .where(
                CourseOffering.term_id == term_id,
                CourseOffering.deleted_at.is_(None),
                CourseOfferingTarget.batch_id == batch_id,
                or_(CourseOfferingTarget.section_id.is_(None), CourseOfferingTarget.section_id == section_id),
            )
        )
        return set((await self.db.execute(stmt)).scalars().all())

    async def replace_faculty(self, offering_id: uuid.UUID, rows: list[CourseOfferingFaculty]) -> None:
        for old in (
            await self.db.execute(select(CourseOfferingFaculty).where(CourseOfferingFaculty.offering_id == offering_id))
        ).scalars():
            await self.db.delete(old)
        await self.db.flush()
        for r in rows:
            self.db.add(r)
        await self.db.flush()

    async def upsert_faculty(self, row: CourseOfferingFaculty) -> bool:
        existing = (
            await self.db.execute(
                select(CourseOfferingFaculty).where(
                    CourseOfferingFaculty.offering_id == row.offering_id,
                    CourseOfferingFaculty.staff_id == row.staff_id,
                    CourseOfferingFaculty.role == row.role,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.hours_per_week = row.hours_per_week
            await self.db.flush()
            return False
        self.db.add(row)
        await self.db.flush()
        return True

    async def replace_targets(self, offering_id: uuid.UUID, rows: list[CourseOfferingTarget]) -> None:
        for old in (
            await self.db.execute(select(CourseOfferingTarget).where(CourseOfferingTarget.offering_id == offering_id))
        ).scalars():
            await self.db.delete(old)
        await self.db.flush()
        for r in rows:
            self.db.add(r)
        await self.db.flush()

    async def add_target(self, row: CourseOfferingTarget) -> bool:
        exists = (
            await self.db.execute(
                select(CourseOfferingTarget.id).where(
                    CourseOfferingTarget.offering_id == row.offering_id,
                    CourseOfferingTarget.batch_id == row.batch_id,
                    (
                        CourseOfferingTarget.section_id.is_(None)
                        if row.section_id is None
                        else CourseOfferingTarget.section_id == row.section_id
                    ),
                )
            )
        ).first()
        if exists is not None:
            return False
        self.db.add(row)
        await self.db.flush()
        return True

    async def confirmed_count(self, offering_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            CourseRegistrationItem.offering_id == offering_id, CourseRegistrationItem.status == "confirmed"
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def seated_counts(self, offering_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
        """offering → (seated items, waitlisted items) from the registration items (``enrolled_count`` recount)."""
        if not offering_ids:
            return {}
        stmt = (
            select(CourseRegistrationItem.offering_id, CourseRegistrationItem.status, func.count())
            .where(CourseRegistrationItem.offering_id.in_(list(offering_ids)))
            .group_by(CourseRegistrationItem.offering_id, CourseRegistrationItem.status)
        )
        out: dict[uuid.UUID, tuple[int, int]] = {}
        for oid, status, n in (await self.db.execute(stmt)).all():
            seated, waiting = out.get(oid, (0, 0))
            if status in ("selected", "confirmed"):
                seated += int(n)
            elif status == "waitlisted":
                waiting += int(n)
            out[oid] = (seated, waiting)
        return out

    async def is_taught_by(self, offering_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        row = (
            await self.db.execute(
                select(CourseOfferingFaculty.id)
                .join(Staff, Staff.id == CourseOfferingFaculty.staff_id)
                .where(CourseOfferingFaculty.offering_id == offering_id, Staff.user_id == user_id)
            )
        ).first()
        return row is not None

    async def roster(self, offering_id: uuid.UUID, statuses: Sequence[str] = ("selected", "confirmed")) -> list[Any]:
        stmt = (
            select(
                CourseRegistrationItem,
                CourseRegistration,
                Student,
                StudentProgramEnrollment,
                StudentTermRecord,
            )
            .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
            .join(
                StudentProgramEnrollment,
                StudentProgramEnrollment.id == CourseRegistration.student_program_enrollment_id,
            )
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .join(StudentTermRecord, StudentTermRecord.id == CourseRegistration.student_term_record_id)
            .where(CourseRegistrationItem.offering_id == offering_id, CourseRegistrationItem.status.in_(list(statuses)))
            .order_by(Student.registration_number)
        )
        return list((await self.db.execute(stmt)).all())

    # ---- batch lookups ---------------------------------------------------------------------------------------------------
    async def rows(self, model: type[T], ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, T]:
        wanted = [i for i in set(ids) if i]
        if not wanted:
            return {}
        m: Any = model
        return {r.id: r for r in (await self.db.execute(select(m).where(m.id.in_(wanted)))).scalars().all()}

    async def sections_of(self, batch_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[BatchSection]]:
        if not batch_ids:
            return {}
        rows = (
            await self.db.execute(
                select(BatchSection)
                .where(BatchSection.batch_id.in_(list(batch_ids)), BatchSection.is_active.is_(True))
                .order_by(BatchSection.name)
            )
        ).scalars()
        out: dict[uuid.UUID, list[BatchSection]] = {}
        for s in rows:
            out.setdefault(s.batch_id, []).append(s)
        return out

    async def batches(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Batch]:
        return await self.rows(Batch, ids)
