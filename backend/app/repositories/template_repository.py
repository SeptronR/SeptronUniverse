"""Notification templates, DLT and WhatsApp registries — Prompts/04 §04.5 ``template_repository``.

``resolve(institution, event, language)``: the institution's active template in that language, else the platform
default (``institution_id`` NULL) — latest active version first; the language falls back to ``en``.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication import DltTemplate, NotificationTemplate, WhatsappTemplate


class TemplateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(
        self, institution_id: uuid.UUID, event_trigger: str | None = None, include_inactive: bool = False
    ) -> Sequence[NotificationTemplate]:
        q = select(NotificationTemplate).where(
            or_(NotificationTemplate.institution_id == institution_id, NotificationTemplate.institution_id.is_(None))
        )
        if event_trigger:
            q = q.where(NotificationTemplate.event_trigger == event_trigger)
        if not include_inactive:
            q = q.where(NotificationTemplate.is_active.is_(True))
        q = q.order_by(
            NotificationTemplate.event_trigger,
            NotificationTemplate.language,
            NotificationTemplate.institution_id.nulls_last(),
            NotificationTemplate.version.desc(),
        )
        return (await self.db.execute(q)).scalars().all()

    async def get(self, template_id: uuid.UUID, institution_id: uuid.UUID) -> NotificationTemplate | None:
        return (
            await self.db.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.id == template_id,
                    or_(
                        NotificationTemplate.institution_id == institution_id,
                        NotificationTemplate.institution_id.is_(None),
                    ),
                )
            )
        ).scalar_one_or_none()

    async def resolve(
        self, institution_id: uuid.UUID | None, event_trigger: str, language: str | None
    ) -> NotificationTemplate | None:
        for lang in dict.fromkeys([(language or "en").split("-")[0], "en"]):
            for inst in ([institution_id, None] if institution_id else [None]):
                q = select(NotificationTemplate).where(
                    NotificationTemplate.event_trigger == event_trigger,
                    NotificationTemplate.language == lang,
                    NotificationTemplate.is_active.is_(True),
                    (
                        NotificationTemplate.institution_id == inst
                        if inst is not None
                        else NotificationTemplate.institution_id.is_(None)
                    ),
                )
                row = (
                    await self.db.execute(q.order_by(NotificationTemplate.version.desc()).limit(1))
                ).scalar_one_or_none()
                if row is not None:
                    return row
        return None

    async def next_version(self, institution_id: uuid.UUID, event_trigger: str, language: str) -> int:
        current = (
            await self.db.execute(
                select(func.max(NotificationTemplate.version)).where(
                    NotificationTemplate.institution_id == institution_id,
                    NotificationTemplate.event_trigger == event_trigger,
                    NotificationTemplate.language == language,
                )
            )
        ).scalar_one_or_none()
        return int(current or 0) + 1

    async def deactivate_others(self, keep: NotificationTemplate) -> None:
        await self.db.execute(
            update(NotificationTemplate)
            .where(
                NotificationTemplate.institution_id == keep.institution_id,
                NotificationTemplate.event_trigger == keep.event_trigger,
                NotificationTemplate.language == keep.language,
                NotificationTemplate.id != keep.id,
            )
            .values(is_active=False)
        )

    async def versions(
        self, institution_id: uuid.UUID, event_trigger: str, language: str
    ) -> Sequence[NotificationTemplate]:
        return (
            (
                await self.db.execute(
                    select(NotificationTemplate)
                    .where(
                        NotificationTemplate.institution_id == institution_id,
                        NotificationTemplate.event_trigger == event_trigger,
                        NotificationTemplate.language == language,
                    )
                    .order_by(NotificationTemplate.version.desc())
                )
            )
            .scalars()
            .all()
        )

    # ---- DLT / WhatsApp ---------------------------------------------------------------------------------------
    async def dlt_list(self, institution_id: uuid.UUID) -> Sequence[DltTemplate]:
        return (
            (
                await self.db.execute(
                    select(DltTemplate)
                    .where(DltTemplate.institution_id == institution_id)
                    .order_by(DltTemplate.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    async def dlt_by_template_id(self, institution_id: uuid.UUID, template_id: str) -> DltTemplate | None:
        return (
            await self.db.execute(
                select(DltTemplate).where(
                    DltTemplate.institution_id == institution_id, DltTemplate.template_id == template_id
                )
            )
        ).scalar_one_or_none()

    async def wa_list(self, institution_id: uuid.UUID) -> Sequence[WhatsappTemplate]:
        return (
            (
                await self.db.execute(
                    select(WhatsappTemplate)
                    .where(WhatsappTemplate.institution_id == institution_id)
                    .order_by(WhatsappTemplate.name)
                )
            )
            .scalars()
            .all()
        )

    async def wa_get(self, institution_id: uuid.UUID, template_id: uuid.UUID) -> WhatsappTemplate | None:
        return (
            await self.db.execute(
                select(WhatsappTemplate).where(
                    WhatsappTemplate.institution_id == institution_id, WhatsappTemplate.id == template_id
                )
            )
        ).scalar_one_or_none()

    async def wa_by_name(self, institution_id: uuid.UUID, name: str, language: str) -> WhatsappTemplate | None:
        return (
            await self.db.execute(
                select(WhatsappTemplate).where(
                    WhatsappTemplate.institution_id == institution_id,
                    WhatsappTemplate.name == name,
                    WhatsappTemplate.language == language,
                )
            )
        ).scalar_one_or_none()
