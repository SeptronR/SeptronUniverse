"""Scheduled read-only / maintenance windows — Prompts/38 §38.6 ``read_only_service`` (Phase 01 extended).

Business rules
1. A window is a ``read_only_modes`` row with a future ``starts_at`` and an ``ends_at`` (platform: ``institution_id``
   NULL, super admin only; tenant: the institution admin's own tenant — ``settings:manage`` — e.g. exam-day windows;
   super admins may target any tenant). ``ends_at`` > ``starts_at`` and ≥ now; overlapping windows of the same scope
   are refused (409).
2. Scheduling auto-creates a ``maintenance`` platform announcement (banner, shown ``notice_hours`` before the start,
   audience = the tenant or everyone) and emits ``platform.read_only_scheduled``.
3. Activation: Beat (every minute, with the Phase 01 ``read_only.expire``) writes the Redis key read by
   ``ReadOnlyModeMiddleware`` once ``starts_at`` passes (503 ``READ_ONLY`` for writes of that tenant / everyone);
   expiry is Phase 01's. ``cancel`` deactivates the window and clears the cache immediately.
"""

import uuid
from datetime import timedelta

from sqlalchemy import or_, select

from app.models.platform import ReadOnlyMode
from app.schemas.saas import AnnouncementAudience, AnnouncementIn, ReadOnlyScheduleIn, ReadOnlyWindowOut
from app.services.read_only_service import ReadOnlyService
from app.services.saas.common import PlatformBase, conflict, forbidden, not_found, now_utc, unprocessable


class ReadOnlyScheduleService(PlatformBase):
    def _target(self, body: ReadOnlyScheduleIn) -> uuid.UUID | None:
        if body.scope == "platform":
            self.require_super("A platform read-only window")
            return None
        if self.is_platform:
            self.require_super("Scheduling a tenant window")
            if body.institution_id is None:
                raise unprocessable("institution_id is required for a tenant window", field="institution_id")
            return body.institution_id
        if not self.can("settings", "manage"):
            raise forbidden("settings:manage required")
        own = getattr(self.principal, "institution_id", None)
        if body.institution_id and body.institution_id != own:
            raise forbidden("Windows are scheduled for your own institution")
        if own is None:
            raise forbidden("An institution context is required")
        return own  # type: ignore[no-any-return]

    def out(self, r: ReadOnlyMode, insts: dict[uuid.UUID, dict]) -> ReadOnlyWindowOut:  # type: ignore[type-arg]
        now = now_utc()
        if not r.is_active:
            state = "cancelled" if (r.ends_at is None or r.ends_at > now) else "ended"
        elif r.starts_at > now:
            state = "upcoming"
        elif r.ends_at is not None and r.ends_at <= now:
            state = "ended"
        else:
            state = "active"
        return ReadOnlyWindowOut(
            id=r.id,
            institution=insts.get(r.institution_id) if r.institution_id else None,
            scope="platform" if r.institution_id is None else "institution",
            reason=r.reason,
            starts_at=r.starts_at,
            ends_at=r.ends_at,
            is_active=r.is_active,
            state=state,
            set_by=r.set_by,
        )

    async def list_windows(
        self, institution_id: uuid.UUID | None = None, include_past: bool = False
    ) -> list[ReadOnlyWindowOut]:
        q = select(ReadOnlyMode).order_by(ReadOnlyMode.starts_at.desc()).limit(500)
        if self.is_platform:
            self.require_platform("platform", "view")
            if institution_id:
                q = q.where(or_(ReadOnlyMode.institution_id == institution_id, ReadOnlyMode.institution_id.is_(None)))
        else:
            if not self.can("settings", "view"):
                raise forbidden("settings:view required")
            own = getattr(self.principal, "institution_id", None)
            q = q.where(or_(ReadOnlyMode.institution_id == own, ReadOnlyMode.institution_id.is_(None)))
        if not include_past:
            q = q.where(or_(ReadOnlyMode.ends_at.is_(None), ReadOnlyMode.ends_at > now_utc() - timedelta(days=1)))
        rows = list((await self.db.execute(q)).scalars())
        insts = await self.institution_refs([r.institution_id for r in rows])
        return [self.out(r, insts) for r in rows]

    async def schedule(self, body: ReadOnlyScheduleIn) -> ReadOnlyWindowOut:
        target = self._target(body)
        now = now_utc()
        if body.ends_at <= body.starts_at or body.ends_at <= now:
            raise unprocessable("The window must end after it starts and in the future", field="ends_at")
        overlap = (
            await self.db.execute(
                select(ReadOnlyMode.id).where(
                    ReadOnlyMode.is_active.is_(True),
                    ReadOnlyMode.institution_id.is_(None) if target is None else ReadOnlyMode.institution_id == target,
                    ReadOnlyMode.starts_at < body.ends_at,
                    or_(ReadOnlyMode.ends_at.is_(None), ReadOnlyMode.ends_at > body.starts_at),
                )
            )
        ).first()
        if overlap:
            raise conflict("Another window overlaps this one")
        row = ReadOnlyMode(
            institution_id=target,
            reason=body.reason,
            starts_at=max(body.starts_at, now - timedelta(minutes=1)),
            ends_at=body.ends_at,
            is_active=True,
            set_by=self.actor_id,
        )
        self.db.add(row)
        await self.db.flush()
        if row.starts_at <= now:
            await ReadOnlyService(self.db)._write_cache(target, row)
        from app.services.saas.announcement_service import AnnouncementService

        await AnnouncementService(self.db, self.principal, self.request).create(
            AnnouncementIn(
                title="Scheduled maintenance (read-only)",
                body=f"{body.reason}. The workspace is read-only from {body.starts_at:%d %b %Y %H:%M} UTC to {body.ends_at:%d %b %Y %H:%M} UTC.",
                audience=AnnouncementAudience(type="all")
                if target is None
                else AnnouncementAudience(type="institution_ids", values=[str(target)]),
                channels=["banner"],
                kind="maintenance",
                starts_at=body.starts_at - timedelta(hours=body.notice_hours),
                ends_at=body.ends_at,
            ),
            system=True,
        )
        await self.audit(
            "read_only_schedule",
            "read_only_mode",
            row.id,
            {"scope": body.scope, "starts_at": row.starts_at, "ends_at": row.ends_at, "reason": body.reason},
            institution_id=target,
            module="settings",
        )
        await self.emit(
            "platform.read_only_scheduled",
            {"window_id": str(row.id), "scope": body.scope, "starts_at": row.starts_at, "ends_at": row.ends_at},
            institution_id=target,
            aggregate_type="read_only_mode",
            aggregate_id=row.id,
        )
        return self.out(row, await self.institution_refs([target]))

    async def cancel(self, window_id: uuid.UUID) -> ReadOnlyWindowOut:
        row = (
            await self.db.execute(select(ReadOnlyMode).where(ReadOnlyMode.id == window_id).with_for_update())
        ).scalar_one_or_none()
        if row is None:
            raise not_found("Read-only window")
        if row.institution_id is None or self.is_platform:
            self.require_super("Cancelling this window")
        else:
            if not self.can("settings", "manage") or row.institution_id != getattr(
                self.principal, "institution_id", None
            ):
                raise not_found("Read-only window")
        if not row.is_active:
            raise conflict("The window is not active")
        row.is_active = False
        await self.db.flush()
        await ReadOnlyService(self.db)._clear_cache(row.institution_id)
        await ReadOnlyService(self.db).refresh_cache()
        await self.audit(
            "read_only_cancel",
            "read_only_mode",
            row.id,
            {"reason": row.reason},
            institution_id=row.institution_id,
            module="settings",
        )
        await self.emit(
            "platform.read_only_changed",
            {"window_id": str(row.id), "enabled": False, "reason": "cancelled"},
            institution_id=row.institution_id,
            aggregate_type="read_only_mode",
            aggregate_id=row.id,
        )
        return self.out(row, await self.institution_refs([row.institution_id]))

    async def activate_due(self) -> int:
        """Beat: windows whose start passed get their cache key (idempotent; a Redis flush is repaired here too)."""
        return await ReadOnlyService(self.db).refresh_cache()

    async def active_now(self) -> list[ReadOnlyWindowOut]:
        now = now_utc()
        rows = list(
            (
                await self.db.execute(
                    select(ReadOnlyMode).where(
                        ReadOnlyMode.is_active.is_(True),
                        ReadOnlyMode.starts_at <= now,
                        or_(ReadOnlyMode.ends_at.is_(None), ReadOnlyMode.ends_at > now),
                    )
                )
            ).scalars()
        )
        insts = await self.institution_refs([r.institution_id for r in rows])
        return [self.out(r, insts) for r in rows]
