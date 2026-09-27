"""Institution profile, settings and platform tenant list — Prompts/03 §03.5 ``institution_repository``.

Settings rows are upserted on ``(institution_id, college_id, category, key)``; the table's UNIQUE constraint does not
fire for ``college_id IS NULL`` (NULLs are distinct), so the upsert looks the row up first under ``FOR UPDATE``.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import College, Institution, InstitutionProfile, InstitutionSetting, User
from app.models.saas import InstitutionSubscription, SubscriptionPlan
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


class InstitutionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---- institution + profile ------------------------------------------------------------------------------------
    async def get(self, institution_id: uuid.UUID, *, for_update: bool = False) -> Institution | None:
        q = select(Institution).where(Institution.id == institution_id, Institution.deleted_at.is_(None))
        if for_update:
            q = q.with_for_update()
        return (await self.db.execute(q)).scalar_one_or_none()

    async def by_slug(self, slug: str) -> Institution | None:
        return (await self.db.execute(select(Institution).where(Institution.slug == slug))).scalar_one_or_none()

    async def profile(self, institution_id: uuid.UUID) -> InstitutionProfile | None:
        return (
            await self.db.execute(select(InstitutionProfile).where(InstitutionProfile.institution_id == institution_id))
        ).scalar_one_or_none()

    async def get_or_create_profile(self, institution_id: uuid.UUID) -> InstitutionProfile:
        row = await self.profile(institution_id)
        if row is None:
            row = InstitutionProfile(institution_id=institution_id)
            self.db.add(row)
            await self.db.flush()
        return row

    async def create(self, **values: Any) -> Institution:
        row = Institution(**values)
        self.db.add(row)
        await self.db.flush()
        return row

    # ---- platform list (super admin, platform session) ------------------------------------------------------------
    async def list_platform(
        self, params: PageParams, q: str | None, status: str | None
    ) -> tuple[list[tuple[Institution, int, int, str | None, str | None]], PaginationMeta]:
        base = select(Institution).where(Institution.deleted_at.is_(None))
        if q:
            like = f"%{q.lower()}%"
            base = base.where(func.lower(Institution.name).like(like) | func.lower(Institution.slug).like(like))
        if status:
            base = base.where(Institution.status == status)
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        rows = (
            (
                await self.db.execute(
                    base.order_by(Institution.created_at.desc()).offset(params.offset).limit(params.page_size)
                )
            )
            .scalars()
            .all()
        )
        out = []
        for inst in rows:
            out.append((inst, *await self.counts(inst.id)))
        return out, PaginationMeta(
            page=params.page,
            page_size=params.page_size,
            total=total,
            total_pages=max(1, -(-total // params.page_size)),
        )

    async def counts(self, institution_id: uuid.UUID) -> tuple[int, int, str | None, str | None]:
        colleges = (
            await self.db.execute(
                select(func.count())
                .select_from(College)
                .where(College.institution_id == institution_id, College.deleted_at.is_(None))
            )
        ).scalar_one()
        users = (
            await self.db.execute(
                select(func.count())
                .select_from(User)
                .where(User.institution_id == institution_id, User.deleted_at.is_(None))
            )
        ).scalar_one()
        sub = (
            await self.db.execute(
                select(SubscriptionPlan.code, InstitutionSubscription.status)
                .join(SubscriptionPlan, SubscriptionPlan.id == InstitutionSubscription.plan_id)
                .where(InstitutionSubscription.institution_id == institution_id)
                .order_by(InstitutionSubscription.created_at.desc())
                .limit(1)
            )
        ).first()
        return int(colleges), int(users), (sub[0] if sub else None), (sub[1] if sub else None)

    async def user_ids(self, institution_id: uuid.UUID) -> Sequence[uuid.UUID]:
        return (await self.db.execute(select(User.id).where(User.institution_id == institution_id))).scalars().all()

    async def revoke_sessions(self, institution_id: uuid.UUID, reason: str) -> int:
        """Revoke every open session of the institution's users (suspension)."""
        res = await self.db.execute(
            text(
                "UPDATE user_sessions SET revoked_at = NOW(), revoked_reason = :r WHERE revoked_at IS NULL "
                "AND user_id IN (SELECT id FROM users WHERE institution_id = :i)"
            ),
            {"i": institution_id, "r": reason[:60]},
        )
        return int(getattr(res, "rowcount", 0) or 0)

    async def any_term_in_progress(self, institution_id: uuid.UUID) -> bool:
        row = (
            await self.db.execute(
                text(
                    "SELECT 1 FROM academic_terms WHERE institution_id = :i AND status = 'in_progress' "
                    "AND deleted_at IS NULL LIMIT 1"
                ),
                {"i": institution_id},
            )
        ).first()
        return row is not None

    async def platform_setting(self, key: str) -> Any | None:
        row = (await self.db.execute(text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key})).first()
        return row[0] if row else None


class SettingsRepository:
    """``institution_settings`` — institution rows (``college_id`` NULL) and college overrides."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def rows(
        self, institution_id: uuid.UUID, category: str | None = None, college_id: uuid.UUID | None = None
    ) -> Sequence[InstitutionSetting]:
        q = select(InstitutionSetting).where(InstitutionSetting.institution_id == institution_id)
        if category:
            q = q.where(InstitutionSetting.category == category)
        if college_id is None:
            q = q.where(InstitutionSetting.college_id.is_(None))
        else:
            q = q.where((InstitutionSetting.college_id.is_(None)) | (InstitutionSetting.college_id == college_id))
        return (await self.db.execute(q)).scalars().all()

    async def get(
        self, institution_id: uuid.UUID, category: str, key: str, college_id: uuid.UUID | None = None
    ) -> InstitutionSetting | None:
        q = select(InstitutionSetting).where(
            InstitutionSetting.institution_id == institution_id,
            InstitutionSetting.category == category,
            InstitutionSetting.key == key,
        )
        q = (
            q.where(InstitutionSetting.college_id.is_(None))
            if college_id is None
            else q.where(InstitutionSetting.college_id == college_id)
        )
        return (await self.db.execute(q.with_for_update())).scalar_one_or_none()

    async def upsert(
        self,
        institution_id: uuid.UUID,
        category: str,
        key: str,
        *,
        value: Any,
        value_type: str,
        is_public: bool,
        college_id: uuid.UUID | None,
        updated_by: uuid.UUID | None,
    ) -> tuple[InstitutionSetting, Any]:
        """Returns (row, previous value)."""
        row = await self.get(institution_id, category, key, college_id)
        old = None
        if row is None:
            row = InstitutionSetting(
                institution_id=institution_id,
                college_id=college_id,
                category=category,
                key=key,
                value=value,
                value_type=value_type,
                is_public=is_public,
                updated_by=updated_by,
            )
            self.db.add(row)
        else:
            old = row.value
            row.value, row.value_type, row.is_public, row.updated_by = value, value_type, is_public, updated_by
        await self.db.flush()
        return row, old

    async def public_rows(self, institution_id: uuid.UUID) -> Sequence[InstitutionSetting]:
        return (
            (
                await self.db.execute(
                    select(InstitutionSetting).where(
                        InstitutionSetting.institution_id == institution_id,
                        InstitutionSetting.college_id.is_(None),
                        InstitutionSetting.is_public.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )


class MessageLogRepository:
    """``message_logs`` is partitioned and owned by Phase 04 (not mapped yet): provider tests insert through SQL."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(
        self,
        *,
        institution_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        recipient: str,
        channel: str,
        event_type: str,
        subject: str | None,
        body_preview: str,
        provider: str,
        provider_message_id: str | None,
        status: str,
        error: str | None = None,
    ) -> uuid.UUID:
        row = (
            await self.db.execute(
                text(
                    "INSERT INTO message_logs (institution_id, user_id, recipient, channel, event_type, subject, "
                    "body_preview, provider, provider_message_id, status, error, sent_at) VALUES (:i, :u, :r, :c, :e, "
                    ":s, :b, :p, :pm, :st, :err, :sent_at) RETURNING id"
                ),
                {
                    "i": institution_id,
                    "u": user_id,
                    "r": recipient[:200],
                    "c": channel,
                    "e": event_type,
                    "s": subject,
                    "b": body_preview[:255],
                    "p": provider,
                    "pm": provider_message_id,
                    "st": status,
                    "err": error,
                    "sent_at": datetime.now(UTC) if status == "sent" else None,
                },
            )
        ).first()
        assert row is not None
        return uuid.UUID(str(row[0]))
