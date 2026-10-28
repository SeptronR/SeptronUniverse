"""Shared plumbing of the Phase 38 services — the ``platform_repository`` contract of Prompts/38 §38.5.

* **Sessions**: platform routes run on the ``universe_platform`` session (``get_platform_db``, BYPASSRLS); tenant-facing
  routes (``/billing/*``, ``/support/tickets`` as a tenant, ``/help/admin`` for institution articles) run on the RLS
  tenant session, so a tenant can only ever touch its own rows even if a predicate were missed.
* **Platform principal**: :meth:`PlatformBase.require_platform` accepts the super admin or a support agent holding the
  ``module:action``; every cross-tenant write is audited with ``institution_id`` = the target tenant
  (:class:`TargetActor`), and every support-agent read of tenant data writes a ``support:view`` row
  (:meth:`audit_read`). Support agents always receive masked PII (:func:`mask_email` / :func:`mask_phone`).
* **Side stores**: ``platform_settings`` (platform-only rows: typed settings, ``reg:<id>`` registration extras,
  ``demo_req:<id>`` CRM notes, ``feedback:<id>`` triage notes, ``alert:<id>`` platform alerts, ``seq:<name>``
  invoice / ticket sequences) and ``institution_settings`` category ``saas_meta`` (tenant-readable facts:
  ``invoice:<number>``, ``caps``, ``usage:<yyyy-mm>``, ``export:<id>``, ``erase_request``, ``status_log``,
  ``scheduled_change``).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.authz.masking import mask_value
from app.core.errors import APIError, ErrorCode
from app.core.notifications.notify import notify_event
from app.enums.saas import PLATFORM_DEFAULTS, SAAS_META
from app.models.platform import Institution, InstitutionSetting, User
from app.models.saas import PlatformSetting

__all__ = [
    "PlatformBase",
    "TargetActor",
    "conflict",
    "forbidden",
    "mask_email",
    "mask_phone",
    "not_found",
    "now_utc",
    "rule",
    "today_utc",
    "unprocessable",
]


def now_utc() -> datetime:
    return datetime.now(UTC)


def today_utc() -> date:
    return now_utc().date()


def forbidden(message: str, **details: Any) -> APIError:
    return APIError(403, ErrorCode.PERMISSION_DENIED, message, details or None)


def not_found(what: str) -> APIError:
    return APIError(404, ErrorCode.NOT_FOUND, f"{what} not found")


def conflict(message: str, **details: Any) -> APIError:
    return APIError(409, ErrorCode.CONFLICT, message, details or None)


def rule(message: str, **details: Any) -> APIError:
    return APIError(409, ErrorCode.RULE_VIOLATION, message, details or None)


def unprocessable(message: str, **details: Any) -> APIError:
    return APIError(422, ErrorCode.VALIDATION, message, details or None)


def mask_email(v: str | None) -> str | None:
    return mask_value(v, "email") if v else v


def mask_phone(v: str | None) -> str | None:
    return mask_value(v, "phone") if v else v


class TargetActor:
    """Audit actor of a cross-tenant action: the platform user, recorded on the *target* tenant's chain."""

    def __init__(self, principal: Any, institution_id: uuid.UUID | None):
        self.id = getattr(principal, "id", None)
        self.institution_id = institution_id
        self.impersonator_id = getattr(principal, "impersonator_id", None)
        self.is_super_admin = bool(getattr(principal, "is_super_admin", False))


class PlatformBase:
    audit_module = "platform"

    def __init__(self, db: AsyncSession, principal: Any = None, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request

    # ---- principal ----------------------------------------------------------------------------------------------
    @property
    def actor_id(self) -> uuid.UUID | None:
        return getattr(self.principal, "id", None)

    @property
    def is_super(self) -> bool:
        return self.principal is None or bool(getattr(self.principal, "is_super_admin", False))

    @property
    def is_support(self) -> bool:
        p = self.principal
        return (
            p is not None
            and not self.is_super
            and "support_agent" in (getattr(p, "roles", None) or [])
            and getattr(p, "institution_id", None) is None
        )

    @property
    def is_platform(self) -> bool:
        return self.is_super or self.is_support

    @property
    def tenant_id(self) -> uuid.UUID | None:
        return None if self.is_platform else getattr(self.principal, "institution_id", None)

    def can(self, module: str, action: str) -> bool:
        p = self.principal
        return p is None or bool(getattr(p, "is_super_admin", False)) or bool(p.has(module, action))

    def require_super(self, what: str = "This action") -> None:
        if not self.is_super:
            raise forbidden(f"{what} needs the super admin")

    def require_platform(self, module: str = "platform", action: str = "view") -> None:
        if self.is_super:
            return
        if self.is_support and self.can(module, action):
            return
        raise forbidden("Platform console only", module=module, action=action)

    def mask(self, value: str | None, kind: str) -> str | None:
        """Support agents read masked PII regardless of module permissions (§38.5)."""
        if not self.is_support or not value:
            return value
        return str(mask_value(value, kind))

    # ---- side effects -------------------------------------------------------------------------------------------
    async def audit(
        self,
        action: str,
        record_type: str,
        record_id: uuid.UUID | None,
        new: dict[str, Any] | None = None,
        old: dict[str, Any] | None = None,
        *,
        institution_id: uuid.UUID | None = None,
        module: str | None = None,
    ) -> None:
        """Audit row on the target tenant's chain (``institution_id``) — or the caller's own tenant."""
        actor: Any = (
            TargetActor(self.principal, institution_id)
            if (self.principal is None or self.is_platform)
            else self.principal
        )
        if self.principal is None:
            actor.id = None
        await log_audit(
            self.db,
            principal=actor,
            module=module or self.audit_module,
            action=action,
            record_type=record_type,
            record_id=record_id,
            old=_json(old),
            new=_json(new),
            request=self.request,
        )

    async def audit_read(self, institution_id: uuid.UUID | None, what: str, record_id: uuid.UUID | None = None) -> None:
        """Support-agent reads of tenant data leave a ``support:view`` row on the tenant's chain (§38.11 step 17)."""
        if not self.is_support or institution_id is None:
            return
        await self.audit("view", what, record_id, {"read": what}, institution_id=institution_id, module="support")

    async def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        institution_id: uuid.UUID | None = None,
        aggregate_type: str | None = None,
        aggregate_id: uuid.UUID | None = None,
    ) -> None:
        await events.emit(
            self.db,
            institution_id=institution_id,
            event_type=event_type,
            payload=_json(payload) or {},
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            actor_user_id=self.actor_id,
        )

    async def notify(
        self,
        event_type: str,
        institution_id: uuid.UUID | None,
        audience: dict[str, Any],
        context: dict[str, Any],
        channels: list[str] | None = None,
    ) -> None:
        if not (audience.get("user_ids") or audience.get("roles") or audience.get("direct_contacts")):
            return
        await notify_event(
            self.db,
            institution_id,
            event_type,
            audience=audience,
            context=_json(context) or {},
            channels=channels,
            actor_user_id=self.actor_id,
        )

    async def super_admin_ids(self) -> list[str]:
        rows = await self.db.execute(
            select(User.id).where(User.is_super_admin.is_(True), User.is_active.is_(True), User.deleted_at.is_(None))
        )
        return [str(r[0]) for r in rows.all()]

    async def notify_platform(
        self, event_type: str, context: dict[str, Any], channels: list[str] | None = None
    ) -> None:
        """Platform-level notification to every super admin (in-app + e-mail by template)."""
        await self.notify(event_type, None, {"user_ids": await self.super_admin_ids()}, context, channels)

    async def notify_tenant_admins(
        self, institution_id: uuid.UUID, event_type: str, context: dict[str, Any], channels: list[str] | None = None
    ) -> None:
        await self.notify(event_type, institution_id, {"roles": ["institution_admin"]}, context, channels)

    # ---- platform_settings ----------------------------------------------------------------------------------------
    async def pget(self, key: str, default: Any = None) -> Any:
        row = (await self.db.execute(select(PlatformSetting.value).where(PlatformSetting.key == key))).first()
        if row is None or row[0] is None:
            return PLATFORM_DEFAULTS.get(key, default) if default is None else default
        return row[0]

    async def setting(self, key: str, sub: str | None = None) -> Any:
        """Typed platform setting merged over :data:`PLATFORM_DEFAULTS` (dict values merge key by key)."""
        default = PLATFORM_DEFAULTS.get(key)
        value = await self.pget(key, default)
        if isinstance(default, dict) and isinstance(value, dict):
            value = {**default, **value}
        return value.get(sub) if sub and isinstance(value, dict) else value

    async def pput(self, key: str, value: Any) -> None:
        await self.db.execute(
            text(
                "INSERT INTO platform_settings (key, value, updated_by, updated_at) "
                "VALUES (:k, CAST(:v AS jsonb), :u, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                "updated_at = NOW()"
            ),
            {"k": key, "v": _dumps(value), "u": self.actor_id},
        )

    async def plist(self, prefix: str) -> dict[str, Any]:
        rows = await self.db.execute(
            select(PlatformSetting.key, PlatformSetting.value).where(PlatformSetting.key.like(f"{prefix}%"))
        )
        return {k[len(prefix) :]: v for k, v in rows.all()}

    async def pdelete(self, key: str) -> None:
        await self.db.execute(text("DELETE FROM platform_settings WHERE key = :k"), {"k": key})

    async def next_sequence(self, name: str, width: int = 4) -> str:
        """Platform number sequence (``seq:<name>`` row, locked) → zero-padded next value."""
        key = f"seq:{name}"
        await self.db.execute(
            text("INSERT INTO platform_settings (key, value) VALUES (:k, '0'::jsonb) ON CONFLICT (key) DO NOTHING"),
            {"k": key},
        )
        cur = (
            await self.db.execute(text("SELECT value FROM platform_settings WHERE key = :k FOR UPDATE"), {"k": key})
        ).scalar_one()
        nxt = int(cur or 0) + 1
        await self.db.execute(
            text("UPDATE platform_settings SET value = CAST(:v AS jsonb), updated_at = NOW() WHERE key = :k"),
            {"k": key, "v": str(nxt)},
        )
        return str(nxt).zfill(width)

    # ---- institution_settings (saas_meta) -------------------------------------------------------------------------
    async def _trow(self, institution_id: uuid.UUID, key: str) -> InstitutionSetting | None:
        return (
            await self.db.execute(
                select(InstitutionSetting).where(
                    InstitutionSetting.institution_id == institution_id,
                    InstitutionSetting.college_id.is_(None),
                    InstitutionSetting.category == SAAS_META,
                    InstitutionSetting.key == key,
                )
            )
        ).scalar_one_or_none()

    async def tget(self, institution_id: uuid.UUID, key: str, default: Any = None) -> Any:
        row = await self._trow(institution_id, key)
        return row.value if row is not None and row.value is not None else default

    async def tput(self, institution_id: uuid.UUID, key: str, value: Any) -> None:
        row = await self._trow(institution_id, key)
        if row is None:
            self.db.add(
                InstitutionSetting(
                    institution_id=institution_id,
                    college_id=None,
                    category=SAAS_META,
                    key=key,
                    value=_json(value),
                    value_type="json",
                    updated_by=self.actor_id,
                )
            )
        else:
            row.value, row.updated_by = _json(value), self.actor_id
        await self.db.flush()

    async def tdelete(self, institution_id: uuid.UUID, key: str) -> None:
        row = await self._trow(institution_id, key)
        if row is not None:
            await self.db.delete(row)
            await self.db.flush()

    async def tlist(self, prefix: str, institution_id: uuid.UUID | None = None) -> list[tuple[uuid.UUID, str, Any]]:
        """``(institution_id, key suffix, value)`` of ``saas_meta`` rows — one tenant, or every tenant (platform)."""
        q = select(InstitutionSetting.institution_id, InstitutionSetting.key, InstitutionSetting.value).where(
            InstitutionSetting.category == SAAS_META,
            InstitutionSetting.college_id.is_(None),
            InstitutionSetting.key.like(f"{prefix}%"),
        )
        if institution_id is not None:
            q = q.where(InstitutionSetting.institution_id == institution_id)
        return [(i, k[len(prefix) :], v) for i, k, v in (await self.db.execute(q)).all()]

    async def tenant_setting(self, institution_id: uuid.UUID, category: str, key: str) -> Any:
        from app.services.settings_service import SettingsService

        return await SettingsService(self.db).value(institution_id, category, key)

    # ---- lookups ------------------------------------------------------------------------------------------------
    async def institution(self, institution_id: uuid.UUID, *, lock: bool = False) -> Institution:
        q = select(Institution).where(Institution.id == institution_id, Institution.deleted_at.is_(None))
        if lock:
            q = q.with_for_update()
        inst = (await self.db.execute(q)).scalar_one_or_none()
        if inst is None:
            raise not_found("Institution")
        return inst

    async def institution_refs(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, dict[str, Any]]:
        clean = list({i for i in ids if i})
        if not clean:
            return {}
        rows = await self.db.execute(
            select(Institution.id, Institution.name, Institution.slug, Institution.status).where(
                Institution.id.in_(clean)
            )
        )
        return {r[0]: {"id": str(r[0]), "name": r[1], "slug": r[2], "status": r[3]} for r in rows.all()}

    async def user_refs(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, dict[str, Any]]:
        clean = list({i for i in ids if i})
        if not clean:
            return {}
        rows = await self.db.execute(
            select(User.id, User.display_name, User.username, User.email, User.is_super_admin).where(User.id.in_(clean))
        )
        return {
            r[0]: {
                "id": str(r[0]),
                "name": r[1] or r[2],
                "email": self.mask(r[3], "email"),
                "platform": bool(r[4]),
            }
            for r in rows.all()
        }

    def institution_scope(self, institution_id: uuid.UUID | None) -> uuid.UUID:
        """Tenant-facing calls: the caller's own institution (platform callers must name one)."""
        if self.is_platform:
            if institution_id is None:
                raise unprocessable("institution_id is required", field="institution_id")
            return institution_id
        inst = getattr(self.principal, "institution_id", None)
        if inst is None:
            raise forbidden("An institution context is required")
        if institution_id is not None and institution_id != inst:
            raise not_found("Institution")
        return inst  # type: ignore[no-any-return]


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


def _json(value: Any) -> Any:
    """JSON-safe copy (UUIDs / dates as strings) for JSONB columns and audit payloads."""
    import json

    if value is None:
        return None
    return json.loads(json.dumps(value, default=str))
