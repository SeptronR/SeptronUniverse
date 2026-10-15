"""Counselling rounds, seat allotments and offers — Prompts/08 §08.5 ``counselling_repository.py``."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.enums.admissions import HOLDING_ALLOTMENTS
from app.models.admissions import AdmissionOffer, CounsellingRound, SeatAllotment


class CounsellingRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID):
        self.db, self.inst = db, institution_id

    async def rounds(self, cycle_id: uuid.UUID) -> Sequence[CounsellingRound]:
        stmt = (
            select(CounsellingRound)
            .where(CounsellingRound.cycle_id == cycle_id, CounsellingRound.institution_id == self.inst)
            .order_by(CounsellingRound.round_number)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def round(self, round_id: uuid.UUID, *, for_update: bool = False) -> CounsellingRound:
        stmt = select(CounsellingRound).where(
            CounsellingRound.id == round_id, CounsellingRound.institution_id == self.inst
        )
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Counselling round not found")
        return row

    async def allotment_counts(self, round_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not round_ids:
            return {}
        stmt = (
            select(SeatAllotment.round_id, func.count())
            .where(SeatAllotment.round_id.in_(list(round_ids)))
            .group_by(SeatAllotment.round_id)
        )
        return {k: int(v) for k, v in (await self.db.execute(stmt)).all()}

    async def allotments(self, round_id: uuid.UUID, status: str | None = None) -> Sequence[SeatAllotment]:
        stmt = select(SeatAllotment).where(SeatAllotment.round_id == round_id)
        if status:
            stmt = stmt.where(SeatAllotment.status == status)
        return (await self.db.execute(stmt.order_by(SeatAllotment.created_at))).scalars().all()

    async def allotment(self, allotment_id: uuid.UUID, *, for_update: bool = False) -> SeatAllotment:
        stmt = select(SeatAllotment).where(SeatAllotment.id == allotment_id, SeatAllotment.institution_id == self.inst)
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Allotment not found")
        return row

    async def holding(
        self, applicant_ids: Sequence[uuid.UUID] | None = None, cycle_round_ids: Any = None
    ) -> dict[uuid.UUID, SeatAllotment]:
        """The seat-holding allotment per applicant (newest first)."""
        stmt = select(SeatAllotment).where(
            SeatAllotment.institution_id == self.inst, SeatAllotment.status.in_(list(HOLDING_ALLOTMENTS))
        )
        if applicant_ids is not None:
            if not applicant_ids:
                return {}
            stmt = stmt.where(SeatAllotment.applicant_id.in_(list(applicant_ids)))
        if cycle_round_ids is not None:
            stmt = stmt.where(SeatAllotment.round_id.in_(cycle_round_ids))
        out: dict[uuid.UUID, SeatAllotment] = {}
        for row in (await self.db.execute(stmt.order_by(SeatAllotment.created_at.desc()))).scalars().all():
            out.setdefault(row.applicant_id, row)
        return out

    async def latest_for(self, applicant_id: uuid.UUID) -> SeatAllotment | None:
        stmt = (
            select(SeatAllotment)
            .where(SeatAllotment.applicant_id == applicant_id)
            .order_by(SeatAllotment.created_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def lapsable(self, now: datetime) -> Sequence[tuple[SeatAllotment, CounsellingRound]]:
        stmt = (
            select(SeatAllotment, CounsellingRound)
            .join(CounsellingRound, CounsellingRound.id == SeatAllotment.round_id)
            .where(
                SeatAllotment.institution_id == self.inst,
                SeatAllotment.status == "allotted",
                CounsellingRound.reporting_deadline.is_not(None),
                CounsellingRound.reporting_deadline < now,
            )
            .with_for_update(of=SeatAllotment)
        )
        return [(a, r) for a, r in (await self.db.execute(stmt)).all()]

    # ---- offers -------------------------------------------------------------------------------------------------------
    async def offers(self, applicant_ids: Any = None) -> Sequence[AdmissionOffer]:
        stmt = select(AdmissionOffer).where(AdmissionOffer.institution_id == self.inst)
        if applicant_ids is not None:
            stmt = stmt.where(AdmissionOffer.applicant_id.in_(applicant_ids))
        return (await self.db.execute(stmt.order_by(AdmissionOffer.created_at.desc()))).scalars().all()
