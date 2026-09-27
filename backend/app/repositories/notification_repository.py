"""In-app notifications, preferences and device tokens — Prompts/04 §04.5 (``module="notifications"``, self only)."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import Notification, NotificationPreference
from app.models.platform import DeviceToken
from app.repositories.base import BaseRepository
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


class NotificationRepository(BaseRepository[Notification]):
    model = Notification
    module = "notifications"

    async def mine(
        self, user_id: uuid.UUID, params: PageParams, unread_only: bool = False, category: str | None = None
    ) -> tuple[Sequence[Notification], PaginationMeta]:
        q = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            q = q.where(Notification.is_read.is_(False))
        if category:
            q = q.where(Notification.category == category)
        q = q.order_by(Notification.created_at.desc())
        return await self.paginate(q, params)

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.user_id == user_id, Notification.is_read.is_(False))
                )
            ).scalar_one()
        )

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID | None = None) -> int:
        q = update(Notification).where(Notification.user_id == user_id, Notification.is_read.is_(False))
        if notification_id is not None:
            q = q.where(Notification.id == notification_id)
        res = await self.db.execute(q.values(is_read=True, read_at=datetime.now(UTC)))
        return int(getattr(res, "rowcount", 0) or 0)

    async def mark_read_by_link(self, user_id: uuid.UUID, key: str, value: str) -> None:
        await self.db.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id, Notification.is_read.is_(False), Notification.link[key].astext == value
            )
            .values(is_read=True, read_at=datetime.now(UTC))
        )


class PreferenceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def for_user(self, user_id: uuid.UUID) -> Sequence[NotificationPreference]:
        return (
            (await self.db.execute(select(NotificationPreference).where(NotificationPreference.user_id == user_id)))
            .scalars()
            .all()
        )

    async def for_users(self, user_ids: Sequence[uuid.UUID], category: str) -> dict[uuid.UUID, NotificationPreference]:
        if not user_ids:
            return {}
        rows = (
            await self.db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id.in_(user_ids), NotificationPreference.category == category
                )
            )
        ).scalars()
        return {r.user_id: r for r in rows}

    async def upsert(
        self,
        institution_id: uuid.UUID | None,
        user_id: uuid.UUID,
        category: str,
        channels: list[str],
        quiet_hours: dict[str, str] | None,
        digest: str,
    ) -> NotificationPreference:
        row = (
            await self.db.execute(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user_id, NotificationPreference.category == category
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = NotificationPreference(
                institution_id=institution_id,
                user_id=user_id,
                category=category,
                channels=channels,
                quiet_hours=quiet_hours,
                digest=digest,
            )
            self.db.add(row)
        else:
            row.channels, row.quiet_hours, row.digest = channels, quiet_hours, digest
        await self.db.flush()
        return row


class DeviceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_token(self, provider: str, token: str) -> DeviceToken | None:
        return (
            await self.db.execute(
                select(DeviceToken).where(DeviceToken.provider == provider, DeviceToken.token == token)
            )
        ).scalar_one_or_none()

    async def active_for(self, user_ids: Sequence[uuid.UUID]) -> Sequence[DeviceToken]:
        if not user_ids:
            return []
        return (
            (
                await self.db.execute(
                    select(DeviceToken).where(DeviceToken.user_id.in_(user_ids), DeviceToken.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )

    async def mine(self, user_id: uuid.UUID) -> Sequence[DeviceToken]:
        return (
            (
                await self.db.execute(
                    select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
