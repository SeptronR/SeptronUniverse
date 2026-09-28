"""Announcements and acknowledgements — Prompts/04 §04.5 ``announcement_repository`` (audience via
``AudienceRepository``; creators and ``communication:view_all`` holders see every announcement + stats)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.communication import Announcement, AnnouncementAcknowledgement


class AnnouncementRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def base(self, institution_id: uuid.UUID) -> Select[tuple[Announcement]]:
        return select(Announcement).where(
            Announcement.institution_id == institution_id, Announcement.deleted_at.is_(None)
        )

    def published(self, institution_id: uuid.UUID) -> Select[tuple[Announcement]]:
        now = datetime.now(UTC)
        return self.base(institution_id).where(
            Announcement.is_active.is_(True),
            Announcement.publish_at.is_not(None),
            Announcement.publish_at <= now,
            or_(Announcement.expires_at.is_(None), Announcement.expires_at > now),
        )

    async def get(
        self, institution_id: uuid.UUID, announcement_id: uuid.UUID, *, for_update: bool = False
    ) -> Announcement:
        q = self.base(institution_id).where(Announcement.id == announcement_id)
        if for_update:
            q = q.with_for_update()
        row = (await self.db.execute(q)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Announcement not found")
        return row

    async def acks(self, announcement_id: uuid.UUID, user_id: uuid.UUID) -> AnnouncementAcknowledgement | None:
        return (
            await self.db.execute(
                select(AnnouncementAcknowledgement).where(
                    AnnouncementAcknowledgement.announcement_id == announcement_id,
                    AnnouncementAcknowledgement.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def my_acks(
        self, ids: Sequence[uuid.UUID], user_id: uuid.UUID
    ) -> dict[uuid.UUID, AnnouncementAcknowledgement]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(AnnouncementAcknowledgement).where(
                    AnnouncementAcknowledgement.announcement_id.in_(ids), AnnouncementAcknowledgement.user_id == user_id
                )
            )
        ).scalars()
        return {r.announcement_id: r for r in rows}

    async def stats(self, announcement_id: uuid.UUID) -> tuple[int, int]:
        """(read, acknowledged) counts."""
        row = (
            await self.db.execute(
                select(func.count(), func.count(AnnouncementAcknowledgement.acknowledged_at)).where(
                    AnnouncementAcknowledgement.announcement_id == announcement_id
                )
            )
        ).one()
        return int(row[0]), int(row[1])

    async def upsert_ack(
        self, institution_id: uuid.UUID, announcement_id: uuid.UUID, user_id: uuid.UUID, acknowledge: bool
    ) -> AnnouncementAcknowledgement:
        row = await self.acks(announcement_id, user_id)
        now = datetime.now(UTC)
        if row is None:
            row = AnnouncementAcknowledgement(
                institution_id=institution_id, announcement_id=announcement_id, user_id=user_id, read_at=now
            )
            self.db.add(row)
        if acknowledge and row.acknowledged_at is None:
            row.acknowledged_at = now
        await self.db.flush()
        return row
