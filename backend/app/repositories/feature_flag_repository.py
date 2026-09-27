"""``platform_features`` / ``institution_feature_flags`` / ``feature_flag_changes`` repository — Prompts/02 §02.5.

Per-tenant rows are RLS-protected: the caller's session must be pinned to the institution (``bind_tenant``) — the
feature service does that for super-admin calls that name the tenant in the path; ``matrix`` runs on the platform
session because it is cross-tenant by nature.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import FeatureFlagChange, Institution, InstitutionFeatureFlag, PlatformFeature


class FeatureFlagRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def definitions(self) -> Sequence[PlatformFeature]:
        return (
            (await self.db.execute(select(PlatformFeature).order_by(PlatformFeature.group_name, PlatformFeature.key)))
            .scalars()
            .all()
        )

    async def definition(self, key: str) -> PlatformFeature | None:
        return (await self.db.execute(select(PlatformFeature).where(PlatformFeature.key == key))).scalar_one_or_none()

    async def flags(self, institution_id: uuid.UUID) -> dict[str, InstitutionFeatureFlag]:
        rows = (
            (
                await self.db.execute(
                    select(InstitutionFeatureFlag).where(InstitutionFeatureFlag.institution_id == institution_id)
                )
            )
            .scalars()
            .all()
        )
        return {r.feature_key: r for r in rows}

    async def upsert(
        self,
        institution_id: uuid.UUID,
        key: str,
        *,
        platform_enabled: bool | None = None,
        institution_enabled: bool | None = None,
        source: str | None = None,
        config: dict[str, Any] | None = None,
        set_by: uuid.UUID | None,
        default_platform: bool = True,
    ) -> InstitutionFeatureFlag:
        row = (
            await self.db.execute(
                select(InstitutionFeatureFlag).where(
                    InstitutionFeatureFlag.institution_id == institution_id, InstitutionFeatureFlag.feature_key == key
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = InstitutionFeatureFlag(
                institution_id=institution_id,
                feature_key=key,
                platform_enabled=default_platform if platform_enabled is None else platform_enabled,
                institution_enabled=True if institution_enabled is None else institution_enabled,
                source=source or "override",
                config=config,
                set_by=set_by,
            )
            self.db.add(row)
        else:
            if platform_enabled is not None:
                row.platform_enabled = platform_enabled
            if institution_enabled is not None:
                row.institution_enabled = institution_enabled
            if source is not None:
                row.source = source
            if config is not None:
                row.config = config
            row.set_by = set_by
            row.set_at = datetime.now(UTC)
        await self.db.flush()
        return row

    async def log_change(
        self,
        institution_id: uuid.UUID,
        key: str,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
        changed_by: uuid.UUID | None,
        reason: str | None,
    ) -> FeatureFlagChange:
        row = FeatureFlagChange(
            institution_id=institution_id,
            feature_key=key,
            old_value=old,
            new_value=new,
            changed_by=changed_by,
            reason=reason,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def changes(
        self, institution_id: uuid.UUID, key: str | None = None, limit: int = 100
    ) -> Sequence[FeatureFlagChange]:
        q = select(FeatureFlagChange).where(FeatureFlagChange.institution_id == institution_id)
        if key:
            q = q.where(FeatureFlagChange.feature_key == key)
        return (await self.db.execute(q.order_by(FeatureFlagChange.changed_at.desc()).limit(limit))).scalars().all()

    async def matrix(self) -> tuple[Sequence[Institution], dict[uuid.UUID, dict[str, InstitutionFeatureFlag]]]:
        """Every active institution with its flag rows (platform session — cross-tenant)."""
        institutions = (
            (
                await self.db.execute(
                    select(Institution).where(Institution.deleted_at.is_(None)).order_by(Institution.name)
                )
            )
            .scalars()
            .all()
        )
        rows = (await self.db.execute(select(InstitutionFeatureFlag))).scalars().all()
        by_inst: dict[uuid.UUID, dict[str, InstitutionFeatureFlag]] = {}
        for r in rows:
            by_inst.setdefault(r.institution_id, {})[r.feature_key] = r
        return institutions, by_inst

    async def plan_features(self, institution_id: uuid.UUID) -> tuple[str | None, list[str]]:
        """(plan code, enabled_features[]) of the tenant's current subscription (plan | trial | active | grace)."""
        row = (
            await self.db.execute(
                text(
                    "SELECT p.code, p.enabled_features FROM institution_subscriptions s "
                    "JOIN subscription_plans p ON p.id = s.plan_id WHERE s.institution_id = :i "
                    "AND s.status IN ('trial','active','grace') ORDER BY s.starts_on DESC LIMIT 1"
                ),
                {"i": institution_id},
            )
        ).first()
        if row is None:
            return None, []
        return str(row[0]), list(row[1] or [])
