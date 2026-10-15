"""Applicants, preferences and document verifications — Prompts/08 §08.5 ``applicant_repository.py``
(``module="admissions"``; search by application number / name / phone; filters cycle / programme preference / status /
category / quota / verified). Visibility: ``repositories/applicant_scope.py`` (self ``Applicant.user_id``, HOD /
college through the preferences, ``admissions:view_all`` @institution)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.admissions import Applicant, ApplicantDocumentVerification, ApplicantPreference
from app.repositories.applicant_scope import applicant_predicate
from app.repositories.base import BaseRepository

NAME_EXPR = Applicant.first_name + " " + func.coalesce(Applicant.last_name, "")


class ApplicantRepository(BaseRepository[Applicant]):
    model = Applicant
    module = "admissions"

    def __init__(self, db: AsyncSession, principal: Any = None, institution_id: Any = None):
        super().__init__(db, principal, institution_id)

    def filtered(
        self,
        *,
        scope: str | None = None,
        cycle_id: uuid.UUID | None = None,
        status: str | None = None,
        statuses: Sequence[str] | None = None,
        program_id: uuid.UUID | None = None,
        category: str | None = None,
        quota: str | None = None,
        entry_type: str | None = None,
        verified: bool | None = None,
        q: str | None = None,
    ) -> Select[tuple[Applicant]]:
        stmt = self._base()
        if self.principal is not None:
            stmt = stmt.where(applicant_predicate(self.principal, scope))
        for col, value in (
            (Applicant.cycle_id, cycle_id),
            (Applicant.status, status),
            (Applicant.category, category),
            (Applicant.quota_claimed, quota),
            (Applicant.entry_type, entry_type),
        ):
            if value is not None:
                stmt = stmt.where(col == value)
        if statuses:
            stmt = stmt.where(Applicant.status.in_(list(statuses)))
        if program_id is not None:
            stmt = stmt.where(
                Applicant.id.in_(
                    select(ApplicantPreference.applicant_id).where(ApplicantPreference.program_id == program_id)
                )
            )
        if verified is not None:
            pending = select(ApplicantDocumentVerification.applicant_id).where(
                ApplicantDocumentVerification.status != "verified"
            )
            stmt = stmt.where(Applicant.id.not_in(pending) if verified else Applicant.id.in_(pending))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    Applicant.application_number.ilike(like),
                    NAME_EXPR.ilike(like),
                    Applicant.contact["phone"].astext.ilike(like),
                )
            )
        return stmt

    async def get_visible(self, applicant_id: uuid.UUID, *, for_update: bool = False) -> Applicant:
        stmt = self.filtered().where(Applicant.id == applicant_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Applicant not found")
        return row

    async def get_any(self, applicant_id: uuid.UUID, *, for_update: bool = False) -> Applicant | None:
        stmt = select(Applicant).where(Applicant.id == applicant_id, Applicant.deleted_at.is_(None))
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def of_user(self, user_id: uuid.UUID, cycle_id: uuid.UUID | None = None) -> Applicant | None:
        stmt = select(Applicant).where(Applicant.user_id == user_id, Applicant.deleted_at.is_(None))
        if cycle_id is not None:
            stmt = stmt.where(Applicant.cycle_id == cycle_id)
        return (await self.db.execute(stmt.order_by(Applicant.created_at.desc()).limit(1))).scalar_one_or_none()

    async def by_number(self, number: str) -> Applicant | None:
        stmt = select(Applicant).where(
            Applicant.institution_id == self.institution_id,
            Applicant.application_number == number,
            Applicant.deleted_at.is_(None),
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def by_phone(self, cycle_id: uuid.UUID, phone: str) -> Applicant | None:
        stmt = select(Applicant).where(
            Applicant.cycle_id == cycle_id,
            Applicant.contact["phone"].astext == phone,
            Applicant.deleted_at.is_(None),
        )
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    # ---- preferences ------------------------------------------------------------------------------------------------
    async def preferences(self, applicant_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[ApplicantPreference]]:
        out: dict[uuid.UUID, list[ApplicantPreference]] = {a: [] for a in applicant_ids}
        if not applicant_ids:
            return out
        rows = (
            (
                await self.db.execute(
                    select(ApplicantPreference)
                    .where(ApplicantPreference.applicant_id.in_(list(applicant_ids)))
                    .order_by(ApplicantPreference.applicant_id, ApplicantPreference.priority)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            out.setdefault(r.applicant_id, []).append(r)
        return out

    async def replace_preferences(self, applicant: Applicant, prefs: Sequence[tuple[uuid.UUID, uuid.UUID]]) -> None:
        await self.db.execute(delete(ApplicantPreference).where(ApplicantPreference.applicant_id == applicant.id))
        await self.db.flush()
        for i, (program_id, college_id) in enumerate(prefs, start=1):
            self.db.add(
                ApplicantPreference(
                    institution_id=applicant.institution_id,
                    applicant_id=applicant.id,
                    program_id=program_id,
                    college_id=college_id,
                    priority=i,
                )
            )
        await self.db.flush()

    # ---- documents ----------------------------------------------------------------------------------------------------
    async def documents(
        self, applicant_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[ApplicantDocumentVerification]]:
        out: dict[uuid.UUID, list[ApplicantDocumentVerification]] = {a: [] for a in applicant_ids}
        if not applicant_ids:
            return out
        rows = (
            (
                await self.db.execute(
                    select(ApplicantDocumentVerification)
                    .where(ApplicantDocumentVerification.applicant_id.in_(list(applicant_ids)))
                    .order_by(ApplicantDocumentVerification.doc_type)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            out.setdefault(r.applicant_id, []).append(r)
        return out

    async def document(
        self, applicant_id: uuid.UUID, doc_type: str, *, for_update: bool = False
    ) -> ApplicantDocumentVerification | None:
        stmt = select(ApplicantDocumentVerification).where(
            ApplicantDocumentVerification.applicant_id == applicant_id,
            ApplicantDocumentVerification.doc_type == doc_type,
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def status_counts(self, cycle_id: uuid.UUID, scope_pred: Any = None) -> dict[str, int]:
        stmt = select(Applicant.status, func.count()).where(
            Applicant.cycle_id == cycle_id, Applicant.deleted_at.is_(None)
        )
        if scope_pred is not None:
            stmt = stmt.where(scope_pred)
        return {s: int(n) for s, n in (await self.db.execute(stmt.group_by(Applicant.status))).all()}
