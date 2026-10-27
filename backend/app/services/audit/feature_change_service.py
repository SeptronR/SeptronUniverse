"""Feature-flag change log and platform actions affecting the tenant — Prompts/37 §37.6 ``feature_change_service``.

Read-only for institution admins (``features:view`` or ``audit_logs:view_all``): ``feature_flag_changes`` rows of the
institution (who / when / reason / old → new; ``platform_actor`` when the author is a super admin) and the
``audit_logs`` rows of the tenant written by a platform actor (a super admin, or any write made while impersonating).
"""

from datetime import datetime

from sqlalchemy import or_, select

from app.models.audit import AuditLog, FeatureFlagChange
from app.models.platform import User
from app.schemas.audit import AuditRowOut, AuditUser, FeatureChangeLogOut
from app.services.audit.audit_service import AuditService


class FeatureChangeService(AuditService):
    def require_log(self) -> None:
        self.require("features:view", "audit_logs:view_all", "audit_logs:manage")

    async def feature_changes(self, date_from: datetime | None, date_to: datetime | None) -> list[FeatureChangeLogOut]:
        self.require_log()
        lo, hi = self.bounds(date_from, date_to)
        rows = list(
            (
                await self.db.execute(
                    select(FeatureFlagChange)
                    .where(
                        FeatureFlagChange.institution_id == self.inst,
                        FeatureFlagChange.changed_at >= lo,
                        FeatureFlagChange.changed_at <= hi,
                    )
                    .order_by(FeatureFlagChange.changed_at.desc())
                    .limit(1000)
                )
            ).scalars()
        )
        ids = [r.changed_by for r in rows if r.changed_by]
        supers = set()
        if ids:
            supers = {
                u
                for (u,) in (
                    await self.db.execute(select(User.id).where(User.id.in_(ids), User.is_super_admin.is_(True)))
                ).all()
            }
        names = await self.user_refs(ids)
        return [
            FeatureChangeLogOut(
                id=r.id,
                feature_key=r.feature_key,
                old_value=r.old_value,
                new_value=r.new_value,
                changed_by=AuditUser(id=r.changed_by, name=names.get(r.changed_by)) if r.changed_by else None,
                changed_at=r.changed_at,
                reason=r.reason,
                platform_actor=r.changed_by in supers,
            )
            for r in rows
        ]

    async def platform_actions(self, date_from: datetime | None, date_to: datetime | None) -> list[AuditRowOut]:
        self.require("audit_logs:view_all", "audit_logs:manage")
        lo, hi = self.bounds(date_from, date_to)
        supers = select(User.id).where(User.is_super_admin.is_(True))
        rows = list(
            (
                await self.db.execute(
                    self.filtered({}, lo, hi)
                    .where(or_(AuditLog.user_id.in_(supers), AuditLog.impersonator_id.is_not(None)))
                    .order_by(AuditLog.occurred_at.desc())
                    .limit(1000)
                )
            ).scalars()
        )
        return await self.rows_out(rows)
