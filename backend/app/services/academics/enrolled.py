"""Curriculum reads through the enrolment (Prompts/05 visibility note, registered by Phase 07).

Staff read programmes, curricula and courses institution-wide with ``curriculum:view`` / ``courses:view``. Students
(``students:self``) and parents (``students:view`` on consented wards) hold neither: they read only the
programme-regulation they — or their wards — are enrolled in, and the courses of that curriculum (core courses and
the courses of its elective baskets). Anything else answers 404, never 403 (no existence leak).
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.curriculum import CurriculumCourse, ElectiveBasket, ElectiveBasketCourse
from app.repositories.student_scope import enrolled_program_regulations


def reads_curriculum(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or any(
        principal.has("curriculum", a) for a in ("view", "view_all")
    )


def reads_courses(principal: Any) -> bool:
    return bool(getattr(principal, "is_super_admin", False)) or any(
        principal.has("courses", a) for a in ("view", "view_all")
    )


async def enrolled_pr_ids(db: AsyncSession, principal: Any) -> set[uuid.UUID]:
    return set((await db.execute(enrolled_program_regulations(principal))).scalars().all())


async def ensure_enrolled_program_regulation(db: AsyncSession, principal: Any, pr_id: uuid.UUID) -> None:
    if reads_curriculum(principal):
        return
    if pr_id not in await enrolled_pr_ids(db, principal):
        raise APIError(404, ErrorCode.NOT_FOUND, "Programme-regulation not found")


async def ensure_course_in_enrolled_curriculum(db: AsyncSession, principal: Any, course_id: uuid.UUID) -> None:
    if reads_courses(principal):
        return
    prs = await enrolled_pr_ids(db, principal)
    if prs:
        direct = select(CurriculumCourse.id).where(
            CurriculumCourse.program_regulation_id.in_(prs), CurriculumCourse.course_id == course_id
        )
        basket = (
            select(ElectiveBasketCourse.id)
            .join(ElectiveBasket, ElectiveBasket.id == ElectiveBasketCourse.basket_id)
            .where(ElectiveBasket.program_regulation_id.in_(prs), ElectiveBasketCourse.course_id == course_id)
        )
        if (await db.execute(direct.limit(1))).first() or (await db.execute(basket.limit(1))).first():
            return
    raise APIError(404, ErrorCode.NOT_FOUND, "Course not found")
