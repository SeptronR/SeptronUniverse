"""Public course catalogue — Prompts/05 §05.6 ``course_service`` "public catalogue projection" + §05.8 public routes.

Rules
1. Unauthenticated; the tenant comes from ``?institution=<slug>``, ``X-Institution-Slug``, the custom host or
   ``X-Institution-Id`` (the endpoint pins RLS to it). ``academics.public_catalog`` must be enabled for the tenant
   (403 ``FEATURE_DISABLED``).
2. Projection: ``active`` programmes; per programme its **active** programme-regulation (latest effective admission
   year) and the curriculum courses flagged ``is_public_catalog`` (plus the courses of its baskets) — codes, titles,
   L-T-P-C and term; no internal ids. Course detail adds the syllabus and textbooks.
3. Cached in Redis ``catalog:{institution}:{key}`` for 10 minutes; the outbox consumer ``catalog.invalidate``
   (``program.*``, ``course.*``, ``regulation.*``, ``curriculum.replaced``) drops the tenant's keys.
"""

import hashlib
import json
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client
from app.models.academic import Program, ProgramRegulation, Regulation
from app.models.curriculum import Course, CurriculumCourse, ElectiveBasket, ElectiveBasketCourse
from app.models.platform import College, Department, Institution
from app.schemas.academics import PublicCatalogCourse, PublicCatalogProgram, PublicCatalogResponse

CACHE_TTL = 600


def cache_prefix(institution_id: uuid.UUID | str) -> str:
    return f"catalog:{institution_id}:"


async def invalidate_catalog(institution_id: uuid.UUID | str) -> int:
    keys = [k async for k in redis_client.scan_iter(match=f"{cache_prefix(institution_id)}*")]
    if keys:
        await redis_client.delete(*keys)
    return len(keys)


class CatalogService:
    def __init__(self, db: AsyncSession, institution: Institution):
        self.db = db
        self.inst = institution

    async def _cached(self, key: str, build: Any) -> dict[str, Any]:
        full = cache_prefix(self.inst.id) + hashlib.sha1(key.encode()).hexdigest()[:16]  # noqa: S324 - cache key
        with suppress(Exception):  # a Redis outage never breaks the public page
            hit = await redis_client.get(full)
            if hit:
                return json.loads(hit)  # type: ignore[no-any-return]
        value = await build()
        with suppress(Exception):
            await redis_client.set(full, json.dumps(value, default=str), ex=CACHE_TTL)
        return value  # type: ignore[no-any-return]

    # ---- rule 2 ----------------------------------------------------------------------------------------------------
    async def catalog(self, program: str | None, level: str | None, college: str | None) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            stmt = (
                select(Program, College.code, College.name, Department.code)
                .join(College, College.id == Program.college_id)
                .join(Department, Department.id == Program.department_id)
                .where(Program.institution_id == self.inst.id, Program.status == "active", Program.deleted_at.is_(None))
                .order_by(College.code, Program.code)
            )
            if program:
                stmt = stmt.where(Program.code == program.upper())
            if level:
                stmt = stmt.where(Program.level == level)
            if college:
                stmt = stmt.where(College.code == college.upper())
            programs = []
            for p, ccode, cname, dcode in (await self.db.execute(stmt)).all():
                programs.append(await self._program(p, ccode, cname, dcode, with_syllabus=False))
            return PublicCatalogResponse(
                institution=self.inst.slug, programs=programs, generated_at=datetime.now(UTC)
            ).model_dump(mode="json")

        return await self._cached(f"list|{program}|{level}|{college}", build)

    async def program_detail(self, code: str, college: str | None) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            stmt = (
                select(Program, College.code, College.name, Department.code)
                .join(College, College.id == Program.college_id)
                .join(Department, Department.id == Program.department_id)
                .where(
                    Program.institution_id == self.inst.id,
                    Program.code == code.upper(),
                    Program.status == "active",
                    Program.deleted_at.is_(None),
                )
            )
            if college:
                stmt = stmt.where(College.code == college.upper())
            row = (await self.db.execute(stmt)).first()
            if row is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Programme not found")
            return (await self._program(row[0], row[1], row[2], row[3], with_syllabus=True)).model_dump(mode="json")

        return await self._cached(f"program|{code}|{college}", build)

    async def course_detail(self, regulation: str, code: str) -> dict[str, Any]:
        async def build() -> dict[str, Any]:
            row = (
                await self.db.execute(
                    select(Course, Regulation.code, Department.code)
                    .join(Regulation, Regulation.id == Course.regulation_id)
                    .join(Department, Department.id == Course.department_id)
                    .where(
                        Course.institution_id == self.inst.id,
                        Regulation.code == regulation.upper(),
                        Regulation.status.in_(("active", "superseded")),
                        Course.code == code.upper(),
                        Course.is_public_catalog.is_(True),
                        Course.status.in_(("active", "retired")),
                        Course.deleted_at.is_(None),
                    )
                )
            ).first()
            if row is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Course not found")
            return self._course(row[0], row[1], row[2], None, with_syllabus=True).model_dump(mode="json")

        return await self._cached(f"course|{regulation}|{code}", build)

    async def _program(
        self, p: Program, college_code: str, college_name: str, dept_code: str, *, with_syllabus: bool
    ) -> PublicCatalogProgram:
        binding = (
            await self.db.execute(
                select(ProgramRegulation, Regulation.code)
                .join(Regulation, Regulation.id == ProgramRegulation.regulation_id)
                .where(
                    ProgramRegulation.program_id == p.id,
                    ProgramRegulation.deleted_at.is_(None),
                    Regulation.status == "active",
                )
                .order_by(Regulation.effective_from_admission_year.desc())
                .limit(1)
            )
        ).first()
        out = PublicCatalogProgram(
            code=p.code,
            name=p.name,
            degree_name=p.degree_name,
            specialization=p.specialization,
            level=p.level,
            mode=p.mode,
            duration_years=p.duration_years,
            total_terms=p.total_terms,
            sanctioned_intake=p.sanctioned_intake,
            college=college_code,
            college_name=college_name,
            department=dept_code,
        )
        if binding is None:
            return out
        pr, reg_code = binding
        out.regulation, out.total_credits = reg_code, pr.total_credits_required
        placed = (
            await self.db.execute(
                select(CurriculumCourse.term_number, Course, Department.code)
                .join(Course, Course.id == CurriculumCourse.course_id)
                .join(Department, Department.id == Course.department_id)
                .where(CurriculumCourse.program_regulation_id == pr.id, Course.is_public_catalog.is_(True))
                .order_by(CurriculumCourse.term_number, CurriculumCourse.sequence, Course.code)
            )
        ).all()
        in_baskets = (
            await self.db.execute(
                select(ElectiveBasket.term_number, Course, Department.code)
                .join(ElectiveBasketCourse, ElectiveBasketCourse.basket_id == ElectiveBasket.id)
                .join(Course, Course.id == ElectiveBasketCourse.course_id)
                .join(Department, Department.id == Course.department_id)
                .where(
                    ElectiveBasket.program_regulation_id == pr.id,
                    ElectiveBasket.deleted_at.is_(None),
                    Course.is_public_catalog.is_(True),
                )
                .order_by(ElectiveBasket.term_number, Course.code)
            )
        ).all()
        seen: set[str] = set()
        both: list[Any] = [*placed, *in_baskets]
        rows: list[tuple[int | None, Course, str]] = [(r[0], r[1], r[2]) for r in both]
        for term, c, dcode in rows:
            if c.code in seen:
                continue
            seen.add(c.code)
            out.courses.append(self._course(c, reg_code, dcode, term, with_syllabus=with_syllabus))
        return out

    @staticmethod
    def _course(
        c: Course, reg_code: str, dept_code: str | None, term: int | None, *, with_syllabus: bool
    ) -> PublicCatalogCourse:
        return PublicCatalogCourse(
            code=c.code,
            title=c.title,
            course_type=c.course_type,
            credits=c.credits,
            lecture_hours=c.lecture_hours,
            tutorial_hours=c.tutorial_hours,
            practical_hours=c.practical_hours,
            term_number=term,
            regulation=reg_code,
            department=dept_code,
            syllabus=c.syllabus if with_syllabus else None,
            textbooks=c.textbooks if with_syllabus else None,
        )
