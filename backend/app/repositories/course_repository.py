"""Courses and prerequisites — Prompts/05 §05.5 ``course_repository`` (``module="courses"``; search by code/title
with ``pg_trgm`` similarity, filters regulation / department / type / status)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, delete, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.curriculum import Course, CoursePrerequisite
from app.repositories.base import BaseRepository

WORD_SIMILARITY = 0.5


class CourseRepository(BaseRepository[Course]):
    model = Course
    module = "courses"

    def filtered(
        self,
        *,
        regulation_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        department_ids: Sequence[uuid.UUID] | None = None,
        course_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
    ) -> Select[tuple[Course]]:
        stmt = self._base()
        if regulation_id:
            stmt = stmt.where(Course.regulation_id == regulation_id)
        if department_id:
            stmt = stmt.where(Course.department_id == department_id)
        if department_ids is not None:
            stmt = stmt.where(Course.department_id.in_(list(department_ids)))
        if course_type:
            stmt = stmt.where(Course.course_type == course_type)
        if status:
            stmt = stmt.where(Course.status == status)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Course.code).like(like),
                    func.lower(Course.title).like(like),
                    # pg_trgm word similarity: typo-tolerant against any word run of the title ("algoritms")
                    func.word_similarity(q, Course.title) > WORD_SIMILARITY,
                )
            ).order_by(func.word_similarity(q, Course.title).desc(), Course.code)
        return stmt

    async def get_course(self, course_id: uuid.UUID, *, for_update: bool = False) -> Course:
        stmt = self._base().where(Course.id == course_id)
        if for_update:
            stmt = stmt.with_for_update()
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course not found")
        return obj

    async def by_code(self, regulation_id: uuid.UUID, code: str) -> Course | None:
        return (
            await self.db.execute(
                self._base().where(Course.regulation_id == regulation_id, func.upper(Course.code) == code.upper())
            )
        ).scalar_one_or_none()

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Course]:
        if not ids:
            return {}
        rows = (await self.db.execute(self._base().where(Course.id.in_(list(set(ids)))))).scalars().all()
        return {c.id: c for c in rows}

    async def for_regulation(self, regulation_id: uuid.UUID) -> Sequence[Course]:
        return (
            (await self.db.execute(self._base().where(Course.regulation_id == regulation_id).order_by(Course.code)))
            .scalars()
            .all()
        )

    # ---- prerequisites -----------------------------------------------------------------------------------------------
    async def prerequisites(self, course_ids: Sequence[uuid.UUID]) -> Sequence[CoursePrerequisite]:
        if not course_ids:
            return []
        return (
            (
                await self.db.execute(
                    select(CoursePrerequisite).where(CoursePrerequisite.course_id.in_(list(course_ids)))
                )
            )
            .scalars()
            .all()
        )

    async def prerequisite_edges(self, regulation_id: uuid.UUID) -> Sequence[tuple[uuid.UUID, uuid.UUID, str]]:
        """(course_id, related_course_id, relation) of every course of the regulation."""
        rows = (
            await self.db.execute(
                select(CoursePrerequisite.course_id, CoursePrerequisite.related_course_id, CoursePrerequisite.relation)
                .join(Course, Course.id == CoursePrerequisite.course_id)
                .where(Course.regulation_id == regulation_id)
            )
        ).all()
        return [(r[0], r[1], r[2]) for r in rows]

    async def replace_prerequisites(self, course_id: uuid.UUID, rows: list[CoursePrerequisite]) -> None:
        await self.db.execute(delete(CoursePrerequisite).where(CoursePrerequisite.course_id == course_id))
        for row in rows:
            self.db.add(row)
        await self.db.flush()

    async def delete_antirequisite_mirror(self, course_id: uuid.UUID, keep: set[uuid.UUID]) -> None:
        """Antirequisites are symmetric: drop mirrored rows pointing at ``course_id`` that are no longer declared."""
        stmt = delete(CoursePrerequisite).where(
            CoursePrerequisite.related_course_id == course_id, CoursePrerequisite.relation == "antirequisite"
        )
        if keep:
            stmt = stmt.where(CoursePrerequisite.course_id.not_in(list(keep)))
        await self.db.execute(stmt)

    async def ensure_antirequisite(self, institution_id: uuid.UUID, course_id: uuid.UUID, related: uuid.UUID) -> None:
        exists = (
            await self.db.execute(
                select(CoursePrerequisite.id).where(
                    CoursePrerequisite.course_id == course_id,
                    CoursePrerequisite.related_course_id == related,
                    CoursePrerequisite.relation == "antirequisite",
                )
            )
        ).first()
        if exists is None:
            self.db.add(
                CoursePrerequisite(
                    institution_id=institution_id,
                    course_id=course_id,
                    related_course_id=related,
                    relation="antirequisite",
                    is_hard=True,
                )
            )
