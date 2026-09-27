"""``consent_records`` / ``data_subject_requests`` repository — Prompts/02 §02.5 (privacy)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import ConsentRecord, DataSubjectRequest


class ConsentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def latest_for_user(self, user_id: uuid.UUID) -> Sequence[ConsentRecord]:
        """Every record of the user, newest first (the service keeps the latest per purpose)."""
        q = select(ConsentRecord).where(ConsentRecord.user_id == user_id).order_by(ConsentRecord.recorded_at.desc())
        return (await self.db.execute(q)).scalars().all()

    async def record(
        self,
        *,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        purpose: str,
        granted: bool,
        text_version: str | None,
        granted_by_user_id: uuid.UUID | None,
        ip: str | None,
    ) -> ConsentRecord:
        now = datetime.now(UTC)
        if not granted:
            # withdrawing closes the open grant(s) of that purpose
            await self.db.execute(
                update(ConsentRecord)
                .where(
                    ConsentRecord.user_id == user_id,
                    ConsentRecord.purpose == purpose,
                    ConsentRecord.granted.is_(True),
                    ConsentRecord.withdrawn_at.is_(None),
                )
                .values(withdrawn_at=now)
            )
        row = ConsentRecord(
            institution_id=institution_id,
            user_id=user_id,
            purpose=purpose,
            granted=granted,
            text_version=text_version,
            granted_by_user_id=granted_by_user_id,
            ip=ip,
        )
        self.db.add(row)
        await self.db.flush()
        return row


class DataSubjectRequestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        *,
        institution_id: uuid.UUID,
        user_id: uuid.UUID,
        request_type: str,
        details: str | None,
        sla_days: int = 30,
    ) -> DataSubjectRequest:
        row = DataSubjectRequest(
            institution_id=institution_id,
            user_id=user_id,
            request_type=request_type,
            status="received",
            details=details,
            due_at=datetime.now(UTC) + timedelta(days=sla_days),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def for_user(self, user_id: uuid.UUID) -> Sequence[DataSubjectRequest]:
        q = (
            select(DataSubjectRequest)
            .where(DataSubjectRequest.user_id == user_id)
            .order_by(DataSubjectRequest.created_at.desc())
        )
        return (await self.db.execute(q)).scalars().all()

    async def all_open(self, institution_id: uuid.UUID) -> Sequence[DataSubjectRequest]:
        q = (
            select(DataSubjectRequest)
            .where(DataSubjectRequest.institution_id == institution_id)
            .order_by(DataSubjectRequest.created_at.desc())
        )
        return (await self.db.execute(q)).scalars().all()
