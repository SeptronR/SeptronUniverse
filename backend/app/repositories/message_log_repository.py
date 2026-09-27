"""Message logs — Prompts/04 §04.5 ``message_log_repository`` (``module="communication"``; partitioned parent)."""

import contextlib
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import MessageLog
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


class MessageLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, **values: Any) -> MessageLog:
        row = MessageLog(**values)
        self.db.add(row)
        await self.db.flush()
        return row

    async def search(
        self,
        institution_id: uuid.UUID,
        params: PageParams,
        channel: str | None,
        status: str | None,
        recipient: str | None,
        event_type: str | None,
        since: datetime | None,
    ) -> tuple[Sequence[MessageLog], PaginationMeta]:
        from sqlalchemy import func

        q = select(MessageLog).where(MessageLog.institution_id == institution_id)
        if channel:
            q = q.where(MessageLog.channel == channel)
        if status:
            q = q.where(MessageLog.status == status)
        if recipient:
            q = q.where(MessageLog.recipient.ilike(f"%{recipient}%"))
        if event_type:
            q = q.where(MessageLog.event_type == event_type)
        if since:
            q = q.where(MessageLog.created_at >= since)
        total = (await self.db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (
            (
                await self.db.execute(
                    q.order_by(MessageLog.created_at.desc()).offset(params.offset).limit(params.page_size)
                )
            )
            .scalars()
            .all()
        )
        return rows, PaginationMeta(
            page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size))
        )

    async def get(self, log_id: uuid.UUID, institution_id: uuid.UUID | None = None) -> MessageLog | None:
        q = select(MessageLog).where(MessageLog.id == log_id)
        if institution_id is not None:
            q = q.where(MessageLog.institution_id == institution_id)
        return (await self.db.execute(q)).scalars().first()

    async def by_provider_ref(self, ref: str) -> MessageLog | None:
        """Webhook lookup: the provider's message id, or our own log id."""
        conds = [MessageLog.provider_message_id == ref]
        with contextlib.suppress(ValueError):
            conds.append(MessageLog.id == uuid.UUID(ref))
        return (
            (
                await self.db.execute(
                    select(MessageLog).where(or_(*conds)).order_by(MessageLog.created_at.desc()).limit(1)
                )
            )
            .scalars()
            .first()
        )

    async def due(self, statuses: Sequence[str], before: datetime, limit: int = 500) -> Sequence[MessageLog]:
        return (
            (
                await self.db.execute(
                    select(MessageLog)
                    .where(MessageLog.status.in_(statuses), MessageLog.created_at <= before)
                    .order_by(MessageLog.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
