"""Faculty workloads and course-allocation proposals — Prompts/06 §06.5 ``workload_repository.py``.

Teaching hours come from ``course_offering_faculty.hours_per_week`` (Phase 09 — the table exists from ``0001`` but
holds no rows until offerings are created, so the computation reports 0 against the cadre norm until then)."""

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.hr import CourseAllocationProposal, FacultyWorkload


class WorkloadRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, staff_id: uuid.UUID, term_id: uuid.UUID) -> FacultyWorkload | None:
        stmt = select(FacultyWorkload).where(FacultyWorkload.staff_id == staff_id, FacultyWorkload.term_id == term_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def add(self, row: FacultyWorkload) -> FacultyWorkload:
        self.db.add(row)
        await self.db.flush()
        return row

    async def teaching_hours(
        self, staff_ids: Sequence[uuid.UUID], term_id: uuid.UUID
    ) -> dict[uuid.UUID, dict[str, Decimal]]:
        """staff id → {theory, tutorial, lab} weekly hours from the term's offerings (Phase 09)."""
        if not staff_ids:
            return {}
        rows = (
            await self.db.execute(
                text(
                    "SELECT f.staff_id, f.role, COALESCE(SUM(f.hours_per_week), 0) AS hours "
                    "FROM course_offering_faculty f JOIN course_offerings o ON o.id = f.offering_id "
                    "WHERE o.term_id = :t AND f.staff_id = ANY(CAST(:s AS uuid[])) GROUP BY f.staff_id, f.role"
                ),
                {"t": term_id, "s": [str(s) for s in staff_ids]},
            )
        ).all()
        out: dict[uuid.UUID, dict[str, Decimal]] = {}
        for staff_id, role, hours in rows:
            bucket = "lab" if role == "lab_instructor" else "tutorial" if role == "teaching_assistant" else "theory"
            slot = out.setdefault(
                uuid.UUID(str(staff_id)), {"theory": Decimal(0), "tutorial": Decimal(0), "lab": Decimal(0)}
            )
            slot[bucket] += Decimal(str(hours))
        return out

    async def offerings_count(self, department_id: uuid.UUID, term_id: uuid.UUID) -> int:
        row = (
            await self.db.execute(
                text("SELECT COUNT(*) FROM course_offerings WHERE department_id = :d AND term_id = :t"),
                {"d": department_id, "t": term_id},
            )
        ).scalar()
        return int(row or 0)


class AllocationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def for_department(
        self, department_id: uuid.UUID, term_id: uuid.UUID, *, for_update: bool = False
    ) -> CourseAllocationProposal | None:
        stmt = select(CourseAllocationProposal).where(
            CourseAllocationProposal.department_id == department_id, CourseAllocationProposal.term_id == term_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_one(self, proposal_id: uuid.UUID, *, for_update: bool = False) -> CourseAllocationProposal:
        stmt = select(CourseAllocationProposal).where(CourseAllocationProposal.id == proposal_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Allocation proposal not found")
        return row

    async def add(self, row: CourseAllocationProposal) -> CourseAllocationProposal:
        self.db.add(row)
        await self.db.flush()
        return row
