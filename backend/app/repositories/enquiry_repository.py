"""Enquiry CRM — Prompts/08 §08.5 ``enquiry_repository.py`` (ownership ``assigned_to``; ``admissions:view_all`` @
institution sees every enquiry, @college the college's)."""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.admissions import Enquiry
from app.repositories.applicant_scope import enquiry_predicate


class EnquiryRepository:
    def __init__(self, db: AsyncSession, principal: Any, institution_id: uuid.UUID):
        self.db, self.principal, self.inst = db, principal, institution_id

    def filtered(
        self,
        *,
        scope: str | None = None,
        stage: str | None = None,
        source: str | None = None,
        assigned_to: uuid.UUID | None = None,
        q: str | None = None,
    ) -> Select[tuple[Enquiry]]:
        stmt = select(Enquiry).where(Enquiry.institution_id == self.inst)
        if self.principal is not None:
            stmt = stmt.where(enquiry_predicate(self.principal, scope))
        for col, value in ((Enquiry.stage, stage), (Enquiry.source, source), (Enquiry.assigned_to, assigned_to)):
            if value is not None:
                stmt = stmt.where(col == value)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(Enquiry.name.ilike(like), Enquiry.phone.ilike(like), Enquiry.email.ilike(like)))
        return stmt

    async def get(self, enquiry_id: uuid.UUID, *, for_update: bool = False) -> Enquiry:
        stmt = self.filtered().where(Enquiry.id == enquiry_id)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Enquiry not found")
        return row

    async def grouped(self, column: Any, scope: str | None = None) -> dict[str, int]:
        sub = self.filtered(scope=scope).subquery()
        stmt = select(getattr(sub.c, column.key), func.count()).group_by(getattr(sub.c, column.key))
        return {str(k): int(v) for k, v in (await self.db.execute(stmt)).all()}

    async def due_follow_ups(self, today: date) -> Sequence[Enquiry]:
        stmt = select(Enquiry).where(
            Enquiry.institution_id == self.inst,
            Enquiry.follow_up_on.is_not(None),
            Enquiry.follow_up_on <= today,
            Enquiry.stage.not_in(("admitted", "lost")),
            Enquiry.assigned_to.is_not(None),
        )
        return (await self.db.execute(stmt)).scalars().all()
