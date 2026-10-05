"""Appraisals (PBAS) and CAS applications — Prompts/06 §06.5 ``appraisal_repository.py`` (self + reviewer link:
``appraisals.reviewer_staff_id`` of the caller's staff row, and an open workflow step addressed to the caller)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicYear
from app.models.hr import Appraisal, CasApplication, Staff
from app.repositories.base import BaseRepository
from app.repositories.hr_scope import approver_instances, effective_scope, visible_staff_ids


class AppraisalRepository(BaseRepository[Appraisal]):
    model = Appraisal
    module = "appraisals"

    def _visible(self, stmt: Select[tuple[Appraisal]], scope: str | None) -> Select[tuple[Appraisal]]:
        if self.principal is None:
            return stmt
        cond: ColumnElement[bool] = Appraisal.staff_id.in_(visible_staff_ids(self.principal, "appraisals", scope))
        if effective_scope(self.principal, "appraisals", scope) == "all":
            mine = select(Staff.id).where(Staff.user_id == self.principal.id)
            cond = or_(
                cond,
                Appraisal.reviewer_staff_id.in_(mine),
                Appraisal.workflow_instance_id.in_(approver_instances(self.principal)),
            )
        return stmt.where(cond)

    def filtered(
        self, *, scope: str | None, status: str | None = None, academic_year_id: uuid.UUID | None = None
    ) -> Select[tuple[Appraisal]]:
        stmt = self._visible(self._base(), scope)
        if status:
            stmt = stmt.where(Appraisal.status == status)
        if academic_year_id:
            stmt = stmt.where(Appraisal.academic_year_id == academic_year_id)
        return stmt

    async def get_visible(self, appraisal_id: uuid.UUID, *, for_update: bool = False) -> Appraisal:
        stmt = self._visible(self._base().where(Appraisal.id == appraisal_id), "all")
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Appraisal not found")
        return row

    async def get_any(self, appraisal_id: uuid.UUID) -> Appraisal | None:
        return (await self.db.execute(select(Appraisal).where(Appraisal.id == appraisal_id))).scalar_one_or_none()

    async def for_year(self, staff_id: uuid.UUID, academic_year_id: uuid.UUID) -> Appraisal | None:
        stmt = select(Appraisal).where(Appraisal.staff_id == staff_id, Appraisal.academic_year_id == academic_year_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def latest_for(self, staff_id: uuid.UUID) -> Appraisal | None:
        stmt = select(Appraisal).where(Appraisal.staff_id == staff_id).order_by(Appraisal.created_at.desc()).limit(1)
        return (await self.db.execute(stmt)).scalar_one_or_none()


class CasRepository(BaseRepository[CasApplication]):
    model = CasApplication
    module = "appraisals"

    def _visible(self, stmt: Select[tuple[CasApplication]], scope: str | None) -> Select[tuple[CasApplication]]:
        if self.principal is None:
            return stmt
        cond: ColumnElement[bool] = CasApplication.staff_id.in_(visible_staff_ids(self.principal, "appraisals", scope))
        if effective_scope(self.principal, "appraisals", scope) == "all":
            cond = or_(cond, CasApplication.workflow_instance_id.in_(approver_instances(self.principal)))
        return stmt.where(cond)

    def filtered(self, *, scope: str | None, status: str | None = None) -> Select[tuple[CasApplication]]:
        stmt = self._visible(self._base(), scope)
        if status:
            stmt = stmt.where(CasApplication.status == status)
        return stmt

    async def get_visible(self, cas_id: uuid.UUID, *, for_update: bool = False) -> CasApplication:
        stmt = self._visible(self._base().where(CasApplication.id == cas_id), "all")
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "CAS application not found")
        return row

    async def get_any(self, cas_id: uuid.UUID) -> CasApplication | None:
        return (await self.db.execute(select(CasApplication).where(CasApplication.id == cas_id))).scalar_one_or_none()

    async def open_for(self, staff_id: uuid.UUID) -> Sequence[CasApplication]:
        stmt = select(CasApplication).where(
            CasApplication.staff_id == staff_id,
            CasApplication.status.in_(("draft", "submitted", "screened", "interviewed")),
        )
        return (await self.db.execute(stmt)).scalars().all()


class AcademicYearLookup:
    """Current / named academic year for the appraisal cycle (institution-wide rows first)."""

    def __init__(self, db: AsyncSession, institution_id: uuid.UUID):
        self.db, self.inst = db, institution_id

    async def current(self, college_id: uuid.UUID | None) -> AcademicYear | None:
        stmt = (
            select(AcademicYear)
            .where(
                AcademicYear.institution_id == self.inst,
                AcademicYear.is_current.is_(True),
                AcademicYear.deleted_at.is_(None),
                or_(AcademicYear.college_id.is_(None), AcademicYear.college_id == college_id),
            )
            .order_by(AcademicYear.college_id.is_(None))
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get(self, year_id: uuid.UUID) -> AcademicYear | None:
        stmt = select(AcademicYear).where(AcademicYear.id == year_id, AcademicYear.institution_id == self.inst)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def names(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(select(AcademicYear.id, AcademicYear.name).where(AcademicYear.id.in_(list(ids))))
        ).all()
        return {r[0]: r[1] for r in rows}
