"""Impersonation oversight — Prompts/38 §38.6 ``impersonation_service`` (Phase 02 impersonation extended).

Business rules
1. List / filter across tenants (``platform:view`` or ``users:impersonate``): impersonator, target, tenant, reason,
   start / end, ``writes_count`` (audit rows written under the session: ``impersonator_id`` = the platform user,
   ``user_id`` = the target, inside the window) and ``read_only`` (support agents impersonate read-only).
2. ``force_stop`` (super admin): ends the log and marks the session revoked in Redis (``imp_revoked:{log}``) — the
   impersonation token answers 401 from then on (checked in ``core/authz/dependencies._resolve``).
3. ``auto_stop`` (Beat every minute): sessions older than 60 minutes are ended the same way.
4. ``started`` (called by Phase 02 ``UserService.impersonate``): when ``saas.notify_impersonation`` is on, the
   tenant's institution admins receive ``platform.impersonation_started`` (they also see the session under
   Phase 37 ``/settings/platform-actions``).
"""

import contextlib
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.enums.saas import IMPERSONATION_MAX_MINUTES
from app.models.audit import AuditLog
from app.models.saas import ImpersonationLog
from app.schemas.saas import ImpersonationForceStop, ImpersonationOut
from app.services.saas.common import PlatformBase, conflict, not_found, now_utc

REVOKED_TTL = 2 * 86400


async def mark_revoked(log_id: uuid.UUID) -> None:
    from app.db.session import redis_client

    with contextlib.suppress(Exception):
        await redis_client.set(f"imp_revoked:{log_id}", "1", ex=REVOKED_TTL)


class ImpersonationService(PlatformBase):
    async def list_sessions(
        self,
        institution_id: uuid.UUID | None = None,
        active: bool | None = None,
        limit: int = 200,
        log_id: uuid.UUID | None = None,
    ) -> list[ImpersonationOut]:
        if not (self.is_platform and (self.can("platform", "view") or self.can("users", "impersonate"))):
            self.require_platform("platform", "view")
        q = select(ImpersonationLog).order_by(ImpersonationLog.started_at.desc()).limit(limit)
        if institution_id:
            q = q.where(ImpersonationLog.institution_id == institution_id)
        if log_id:
            q = q.where(ImpersonationLog.id == log_id)
        if active is True:
            q = q.where(ImpersonationLog.ended_at.is_(None))
        elif active is False:
            q = q.where(ImpersonationLog.ended_at.is_not(None))
        rows = list((await self.db.execute(q)).scalars())
        users = await self.user_refs([r.impersonator_id for r in rows] + [r.target_user_id for r in rows])
        insts = await self.institution_refs([r.institution_id for r in rows])
        writes = await self.writes(rows)
        meta = await self.plist("imp:")
        return [
            ImpersonationOut(
                id=r.id,
                impersonator=users.get(r.impersonator_id, {"id": str(r.impersonator_id)}),
                target=users.get(r.target_user_id, {"id": str(r.target_user_id)}),
                institution=insts.get(r.institution_id) if r.institution_id else None,
                reason=r.reason,
                started_at=r.started_at,
                ended_at=r.ended_at,
                active=r.ended_at is None,
                read_only=not users.get(r.impersonator_id, {}).get("platform", False),
                writes_count=writes.get(r.id, 0),
                ended_by=(meta.get(str(r.id)) or {}).get("ended_by"),
            )
            for r in rows
        ]

    async def writes(self, rows: list[ImpersonationLog]) -> dict[uuid.UUID, int]:
        out: dict[uuid.UUID, int] = {}
        for r in rows:
            end = r.ended_at or now_utc()
            n = (
                await self.db.execute(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.impersonator_id == r.impersonator_id,
                        AuditLog.user_id == r.target_user_id,
                        AuditLog.occurred_at >= r.started_at,
                        AuditLog.occurred_at <= end,
                        AuditLog.action.notin_(("view", "impersonation_stop")),
                    )
                )
            ).scalar_one()
            out[r.id] = int(n)
        return out

    async def force_stop(self, log_id: uuid.UUID, body: ImpersonationForceStop) -> ImpersonationOut:
        self.require_super("Force-stopping an impersonation")
        row = (
            await self.db.execute(select(ImpersonationLog).where(ImpersonationLog.id == log_id).with_for_update())
        ).scalar_one_or_none()
        if row is None:
            raise not_found("Impersonation")
        if row.ended_at is not None:
            raise conflict("The impersonation already ended")
        await self._end(row, f"force_stop by {self.actor_id}", body.reason)
        await self.audit(
            "impersonation_force_stop",
            "impersonation_log",
            row.id,
            {
                "reason": body.reason,
                "impersonator_id": str(row.impersonator_id),
                "target_user_id": str(row.target_user_id),
            },
            institution_id=row.institution_id,
        )
        await self.emit(
            "impersonation.force_stopped",
            {"log_id": str(row.id), "reason": body.reason},
            institution_id=row.institution_id,
            aggregate_type="impersonation_log",
            aggregate_id=row.id,
        )
        return (await self.list_sessions(log_id=row.id))[0]

    async def _end(self, row: ImpersonationLog, ended_by: str, reason: str | None) -> None:
        row.ended_at = now_utc()
        await self.db.flush()
        await mark_revoked(row.id)
        await self.pput(f"imp:{row.id}", {"ended_by": ended_by, "reason": reason, "at": row.ended_at.isoformat()})

    async def auto_stop(self) -> int:
        cutoff = now_utc() - timedelta(minutes=IMPERSONATION_MAX_MINUTES)
        rows = list(
            (
                await self.db.execute(
                    select(ImpersonationLog)
                    .where(ImpersonationLog.ended_at.is_(None), ImpersonationLog.started_at < cutoff)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for r in rows:
            await self._end(r, "auto_stop", f"exceeded {IMPERSONATION_MAX_MINUTES} minutes")
            await self.audit(
                "impersonation_auto_stop",
                "impersonation_log",
                r.id,
                {"minutes": IMPERSONATION_MAX_MINUTES},
                institution_id=r.institution_id,
            )
        return len(rows)

    async def started(self, row: ImpersonationLog, impersonator: Any, target: Any) -> None:
        if row.institution_id is None or not await self.setting("saas.notify_impersonation"):
            return
        await self.notify_tenant_admins(
            row.institution_id,
            "platform.impersonation_started",
            {
                "impersonator": getattr(impersonator, "display_name", None)
                or getattr(impersonator, "username", "platform"),
                "target": getattr(target, "display_name", None) or getattr(target, "username", ""),
                "reason": row.reason or "",
            },
        )

    async def active_for(self, institution_id: uuid.UUID) -> int:
        n = (
            await self.db.execute(
                select(func.count())
                .select_from(ImpersonationLog)
                .where(
                    ImpersonationLog.institution_id == institution_id,
                    ImpersonationLog.ended_at.is_(None),
                    ImpersonationLog.started_at >= now_utc() - timedelta(minutes=IMPERSONATION_MAX_MINUTES),
                )
            )
        ).scalar_one()
        return int(n)
