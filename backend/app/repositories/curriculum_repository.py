"""Programme structure — Prompts/05 §05.5 ``curriculum_repository``: structure terms + curriculum courses + elective
baskets (with their courses) of one programme-regulation in one loader; transactional replace helpers."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.academic import ProgramStructureTerm
from app.models.curriculum import Course, CurriculumCourse, ElectiveBasket, ElectiveBasketCourse
from app.repositories.base import BaseRepository


@dataclass
class StructureBundle:
    terms: list[ProgramStructureTerm] = field(default_factory=list)
    courses: list[CurriculumCourse] = field(default_factory=list)
    baskets: list[ElectiveBasket] = field(default_factory=list)
    basket_courses: dict[uuid.UUID, list[ElectiveBasketCourse]] = field(default_factory=dict)


class CurriculumRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID):
        self.db = db
        self.inst = institution_id

    async def load(self, program_regulation_id: uuid.UUID) -> StructureBundle:
        terms = (
            (
                await self.db.execute(
                    select(ProgramStructureTerm)
                    .where(ProgramStructureTerm.program_regulation_id == program_regulation_id)
                    .order_by(ProgramStructureTerm.term_number)
                )
            )
            .scalars()
            .all()
        )
        courses = (
            (
                await self.db.execute(
                    select(CurriculumCourse)
                    .where(CurriculumCourse.program_regulation_id == program_regulation_id)
                    .order_by(CurriculumCourse.term_number, CurriculumCourse.sequence)
                )
            )
            .scalars()
            .all()
        )
        baskets = await self.baskets(program_regulation_id)
        return StructureBundle(
            terms=list(terms),
            courses=list(courses),
            baskets=list(baskets),
            basket_courses=await self.basket_courses([b.id for b in baskets]),
        )

    async def baskets(self, program_regulation_id: uuid.UUID) -> Sequence[ElectiveBasket]:
        return (
            (
                await self.db.execute(
                    select(ElectiveBasket)
                    .where(
                        ElectiveBasket.program_regulation_id == program_regulation_id,
                        ElectiveBasket.deleted_at.is_(None),
                    )
                    .order_by(ElectiveBasket.term_number.nulls_last(), ElectiveBasket.code)
                )
            )
            .scalars()
            .all()
        )

    async def basket_courses(self, basket_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ElectiveBasketCourse]]:
        out: dict[uuid.UUID, list[ElectiveBasketCourse]] = {b: [] for b in basket_ids}
        if not basket_ids:
            return out
        rows = (
            (
                await self.db.execute(
                    select(ElectiveBasketCourse).where(ElectiveBasketCourse.basket_id.in_(list(basket_ids)))
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            out.setdefault(r.basket_id, []).append(r)
        return out

    async def replace_terms_and_courses(self, program_regulation_id: uuid.UUID) -> None:
        await self.db.execute(
            delete(CurriculumCourse).where(CurriculumCourse.program_regulation_id == program_regulation_id)
        )
        await self.db.execute(
            delete(ProgramStructureTerm).where(ProgramStructureTerm.program_regulation_id == program_regulation_id)
        )
        await self.db.flush()

    async def delete_baskets(self, program_regulation_id: uuid.UUID) -> None:
        """Hard delete (the structure editor owns them; nothing downstream references a draft basket yet)."""
        await self.db.execute(
            delete(ElectiveBasket).where(ElectiveBasket.program_regulation_id == program_regulation_id)
        )
        await self.db.flush()

    async def replace_basket_courses(self, basket_id: uuid.UUID, rows: list[ElectiveBasketCourse]) -> None:
        await self.db.execute(delete(ElectiveBasketCourse).where(ElectiveBasketCourse.basket_id == basket_id))
        for r in rows:
            self.db.add(r)
        await self.db.flush()


class BasketRepository(BaseRepository[ElectiveBasket]):
    model = ElectiveBasket
    module = "curriculum"

    async def get_basket(self, basket_id: uuid.UUID) -> ElectiveBasket:
        obj = (await self.db.execute(self._base().where(ElectiveBasket.id == basket_id))).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Elective basket not found")
        return obj

    async def by_code(self, program_regulation_id: uuid.UUID, code: str) -> ElectiveBasket | None:
        return (
            await self.db.execute(
                self._base().where(
                    ElectiveBasket.program_regulation_id == program_regulation_id,
                    func.upper(ElectiveBasket.code) == code.upper(),
                )
            )
        ).scalar_one_or_none()

    async def course_briefs(self, course_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Course]:
        if not course_ids:
            return {}
        rows = (await self.db.execute(select(Course).where(Course.id.in_(list(course_ids))))).scalars().all()
        return {c.id: c for c in rows}
