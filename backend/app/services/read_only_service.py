"""Read-only mode — Prompts/01 §01.6 (``read_only_modes`` windows cached in Redis for the middleware).

Business rules
1. Two scopes: **platform** (``institution_id IS NULL``, super admin only) and **institution** (``settings:manage``
   of that tenant; super admins may target any tenant with ``institution_id``). ``READ_ONLY_MODE=true`` in the
   environment is a third, static switch that always wins.
2. ``set(enabled=True)`` closes any active window of the same scope and opens a new one (``reason``, optional
   ``ends_at``); ``set(enabled=False)`` deactivates the active window. Both are audited (``settings:read_only``) and
   emit ``platform.read_only_changed``.
3. Cache keys ``ro:platform`` / ``ro:{institution_id}`` hold the JSON state; TTL = time until ``ends_at`` (or none).
   ``ReadOnlyModeMiddleware`` consults only the cache, so a Redis outage never blocks writes; ``refresh_cache`` rebuilds
   the keys from the table (startup / Beat).
4. ``expire`` (Beat ``read_only.expire``, every minute) deactivates windows whose ``ends_at`` passed and clears their
   cache keys, emitting ``platform.read_only_changed`` with ``enabled=false``.
5. ``state(institution_id)`` is public: clients render the banner from it (``GET /platform/read-only``).
"""

import contextlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.models.platform import ReadOnlyMode
from app.repositories.platform_repository import ReadOnlyModeRepository
from app.schemas.platform import ReadOnlyModeRequest, ReadOnlyState

log = structlog.get_logger()


def cache_key(institution_id: uuid.UUID | str | None) -> str:
    return "ro:platform" if institution_id is None else f"ro:{institution_id}"


class ReadOnlyService:
    def __init__(self, db: AsyncSession, principal: Principal | None = None):
        self.db, self.principal = db, principal
        self.repo = ReadOnlyModeRepository(db)

    # ---- reads -------------------------------------------------------------------------------------------------
    async def state(self, institution_id: uuid.UUID | str | None) -> ReadOnlyState:
        """Rule 5 — env switch OR active platform window OR active tenant window."""
        now = datetime.now(UTC)
        platform_row = await self.repo.active_for(None, now)
        inst_uuid = _uuid(institution_id)
        inst_row = await self.repo.active_for(inst_uuid, now) if inst_uuid else None
        platform_on = settings.READ_ONLY_MODE or platform_row is not None
        active = platform_row if platform_on else inst_row
        return ReadOnlyState(
            platform=platform_on,
            institution=inst_row is not None,
            reason=(active.reason if active else ("Maintenance (READ_ONLY_MODE)" if settings.READ_ONLY_MODE else None)),
            ends_at=active.ends_at if active else None,
            institution_id=inst_uuid,
        )

    # ---- writes ------------------------------------------------------------------------------------------------
    async def set(self, body: ReadOnlyModeRequest, request: Request | None = None) -> ReadOnlyState:
        """Rules 1–3."""
        assert self.principal is not None
        if body.scope == "platform":
            if not self.principal.is_super_admin:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Platform read-only mode requires the super admin")
            target: uuid.UUID | None = None
        else:
            if self.principal.is_super_admin and body.institution_id:
                target = body.institution_id
            else:
                target = self.principal.institution_id
            if target is None:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "institution_id is required for a tenant window",
                    {"field": "institution_id"},
                )
            if body.institution_id and not self.principal.is_super_admin and body.institution_id != target:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Cannot set read-only mode for another institution")
        if body.ends_at and body.ends_at <= datetime.now(UTC):
            raise APIError(422, ErrorCode.VALIDATION, "ends_at must be in the future", {"field": "ends_at"})

        closed = await self.repo.deactivate(target)
        row: ReadOnlyMode | None = None
        if body.enabled:
            row = await self.repo.create(target, body.reason, body.ends_at, self.principal.id)
        await self._write_cache(target, row)
        await log_audit(
            self.db,
            principal=self.principal,
            module="settings",
            action="read_only",
            record_type="read_only_mode",
            record_id=row.id if row else None,
            old={"active_windows_closed": closed},
            new={"scope": body.scope, "enabled": body.enabled, "reason": body.reason, "ends_at": body.ends_at},
            request=request,
        )
        await events.emit(
            self.db,
            institution_id=target,
            event_type="platform.read_only_changed",
            payload={
                "scope": body.scope,
                "institution_id": str(target) if target else None,
                "enabled": body.enabled,
                "reason": body.reason,
                "ends_at": body.ends_at.isoformat() if body.ends_at else None,
            },
            aggregate_type="read_only_mode",
            aggregate_id=row.id if row else None,
            actor_user_id=self.principal.id,
        )
        return await self.state(target)

    async def expire(self) -> int:
        """Rule 4 — Beat body."""
        rows = await self.repo.expire(datetime.now(UTC))
        for r in rows:
            await self._clear_cache(r.institution_id)
            await events.emit(
                self.db,
                institution_id=r.institution_id,
                event_type="platform.read_only_changed",
                payload={
                    "scope": "platform" if r.institution_id is None else "institution",
                    "institution_id": str(r.institution_id) if r.institution_id else None,
                    "enabled": False,
                    "reason": "window ended",
                },
                aggregate_type="read_only_mode",
                aggregate_id=r.id,
            )
        if rows:
            log.info("read_only_expired", windows=len(rows))
        return len(rows)

    async def refresh_cache(self) -> int:
        """Rule 3 — rebuild every ``ro:*`` key from the active windows (startup / after a Redis flush)."""
        rows = await self.repo.active(datetime.now(UTC))
        for r in rows:
            await self._write_cache(r.institution_id, r)
        return len(rows)

    # ---- cache -------------------------------------------------------------------------------------------------
    async def _write_cache(self, institution_id: uuid.UUID | None, row: ReadOnlyMode | None) -> None:
        from app.db.session import redis_client

        key = cache_key(institution_id)
        with contextlib.suppress(Exception):  # Redis down → middleware stays permissive (never blocks writes)
            if row is None:
                await redis_client.delete(key)
                return
            payload: dict[str, Any] = {
                "reason": row.reason,
                "ends_at": row.ends_at.isoformat() if row.ends_at else None,
            }
            ttl = int((row.ends_at - datetime.now(UTC)).total_seconds()) if row.ends_at else None
            if ttl is not None and ttl <= 0:
                await redis_client.delete(key)
                return
            await redis_client.set(key, json.dumps(payload), ex=ttl)

    async def _clear_cache(self, institution_id: uuid.UUID | None) -> None:
        await self._write_cache(institution_id, None)


def _uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
