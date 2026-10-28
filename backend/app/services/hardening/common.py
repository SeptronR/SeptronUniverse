"""Shared helpers of the Phase 43 services: platform / institution meta reads and writes, permission checks."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode

META = "privacy_meta"


def forbidden(msg: str) -> APIError:
    return APIError(403, ErrorCode.PERMISSION_DENIED, msg)


class HardeningBase:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request

    @property
    def inst(self) -> uuid.UUID:
        iid = getattr(self.principal, "institution_id", None)
        if iid is None:
            raise APIError(422, ErrorCode.VALIDATION, "An institution context is required")
        return uuid.UUID(str(iid))

    def can(self, module: str, action: str) -> bool:
        p = self.principal
        return bool(p is not None and (getattr(p, "is_super_admin", False) or p.has(module, action)))

    def require(self, *perms: str) -> None:
        if not any(self.can(*p.split(":", 1)) for p in perms):
            raise forbidden(f"{' or '.join(perms)} required")

    async def platform_value(self, key: str, default: Any = None) -> Any:
        row = (await self.db.execute(text("SELECT value FROM platform_settings WHERE key = :k"), {"k": key})).first()
        return row[0] if row and row[0] is not None else default

    async def put_platform_value(self, key: str, value: Any) -> None:
        await self.db.execute(
            text(
                "INSERT INTO platform_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"k": key, "v": json.dumps(value, default=str)},
        )

    async def meta(self, key: str, category: str = META, inst: uuid.UUID | None = None) -> Any:
        row = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                    "AND category = :c AND key = :k"
                ),
                {"i": inst or self.inst, "c": category, "k": key},
            )
        ).first()
        return row[0] if row else None

    async def put_meta(self, key: str, value: Any, category: str = META, inst: uuid.UUID | None = None) -> None:
        await self.db.execute(
            text(
                "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, "
                "is_public, created_at, updated_at) VALUES (:id, :i, NULL, :c, :k, CAST(:v AS jsonb), 'json', FALSE, "
                "NOW(), NOW()) ON CONFLICT (institution_id, college_id, category, key) "
                "DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"id": uuid.uuid4(), "i": inst or self.inst, "c": category, "k": key, "v": json.dumps(value, default=str)},
        )

    async def setting(self, category: str, key: str, default: Any = None) -> Any:
        """Institution setting with the template default (``SettingsService`` semantics, read-only)."""
        row = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND college_id IS NULL "
                    "AND category = :c AND key = :k"
                ),
                {"i": self.inst, "c": category, "k": key},
            )
        ).first()
        return row[0] if row else default
