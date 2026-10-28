"""API keys — Prompts/41 §41.6 ``api_key_service`` (``integrations.api_keys_webhooks``; ``integrations:api_keys``).

Business rules
1. Create: secret ``su_<prefix>_<random>`` shown once; stored as ``key_prefix`` + sha256 ``hashed_key``; scopes ⊆
   permission modules (``students`` = read, ``students:write`` = read + create / update, ``students:view_pii``);
   ``api_keys.max_per_institution`` (20) active keys → 409; IP allow-list and rotation grace live in
   ``institution_settings`` category ``integrations_meta`` (``apikey:<id>``).
2. Rotate: a new secret on a new row; the old key keeps working for 24 h (``grace_until``) then is revoked. Revoke →
   ``is_active=false``.
3. Auth (:func:`principal_from_api_key`): ``X-API-Key`` → hash lookup (platform session) → active, not expired,
   IP allowed → per-key rate limit (``apikey:{id}:{minute}``) → a service principal acting as the key's creator with
   permissions = scopes × read actions (+ writes / ``view_pii`` when scoped), visibility ``all`` within the scopes;
   usage counters ``apikey:{id}:{day}``; ``last_used_at`` refreshed at most once a minute.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client
from app.models.platform import ApiKey
from app.schemas.integrations import ApiKeyCreate, ApiKeyCreatedOut, ApiKeyOut

META = "integrations_meta"
MAX_KEYS = 20
READ_ACTIONS = ("view", "view_all")
WRITE_ACTIONS = ("create", "update")


def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def scope_permissions(scopes: list[str]) -> set[str]:
    perms: set[str] = set()
    for s in scopes:
        module, _, mode = s.partition(":")
        perms |= {f"{module}:{a}" for a in READ_ACTIONS}
        if mode == "write":
            perms |= {f"{module}:{a}" for a in WRITE_ACTIONS}
        if mode == "view_pii":
            perms.add(f"{module}:view_pii")
    return perms


async def _meta(db: Any, inst: Any, key_id: Any) -> dict[str, Any]:
    r = (
        await db.execute(
            text(
                "SELECT value FROM institution_settings WHERE institution_id = :i AND category = :c AND key = :k AND college_id IS NULL"
            ),
            {"i": inst, "c": META, "k": f"apikey:{key_id}"},
        )
    ).first()
    return dict(r[0]) if r and isinstance(r[0], dict) else {}


async def _put_meta(db: Any, inst: Any, key_id: Any, value: dict[str, Any]) -> None:
    await db.execute(
        text(
            "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, is_public, created_at, updated_at) "
            "VALUES (:id, :i, NULL, :c, :k, CAST(:v AS jsonb), 'json', FALSE, NOW(), NOW()) "
            "ON CONFLICT (institution_id, college_id, category, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"id": uuid.uuid4(), "i": inst, "c": META, "k": f"apikey:{key_id}", "v": json.dumps(value, default=str)},
    )


class ApiKeyService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = principal.institution_id

    def _writer(self) -> None:
        if not (self.principal.has("integrations", "api_keys") or self.principal.has("integrations", "manage")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")

    async def _out(self, k: ApiKey) -> ApiKeyOut:
        meta = await _meta(self.db, self.inst, k.id)
        usage = await redis_client.get(f"apikey:{k.id}:{date.today().isoformat()}")
        return ApiKeyOut(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=list(k.scopes or []),
            rate_limit_per_minute=k.rate_limit_per_minute,
            expires_at=k.expires_at,
            last_used_at=k.last_used_at,
            is_active=k.is_active,
            created_at=k.created_at,
            revoked_at=k.revoked_at,
            ip_allowlist=list(meta.get("ip_allowlist") or []),
            usage_today=int(usage or 0),
        )

    async def list(self) -> list[ApiKeyOut]:
        rows = (
            await self.db.execute(
                select(ApiKey).where(ApiKey.institution_id == self.inst).order_by(ApiKey.created_at.desc())
            )
        ).scalars()
        return [await self._out(k) for k in rows]

    async def create(self, body: ApiKeyCreate, *, rotated_from: uuid.UUID | None = None) -> ApiKeyCreatedOut:
        self._writer()
        from app.core.rbac.registry import MODULES

        bad = [
            s
            for s in body.scopes
            if s.partition(":")[0] not in MODULES or s.partition(":")[2] not in ("", "read", "write", "view_pii")
        ]
        if bad:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown scopes: {', '.join(bad)}", {"field": "scopes"})
        active = (
            await self.db.execute(
                text("SELECT count(*) FROM api_keys WHERE institution_id = :i AND is_active"), {"i": self.inst}
            )
        ).scalar_one()
        if active >= MAX_KEYS and rotated_from is None:
            raise APIError(409, ErrorCode.CONFLICT, f"At most {MAX_KEYS} active API keys")
        prefix = secrets.token_hex(4)
        secret = f"su_{prefix}_{secrets.token_urlsafe(32)}"
        k = ApiKey(
            institution_id=self.inst,
            name=body.name,
            key_prefix=prefix,
            hashed_key=hash_key(secret),
            scopes=body.scopes,
            rate_limit_per_minute=body.rate_limit_per_minute or 600,
            expires_at=body.expires_at,
            is_active=True,
            created_by=self.principal.id,
        )
        self.db.add(k)
        await self.db.flush()
        await _put_meta(
            self.db,
            self.inst,
            k.id,
            {"ip_allowlist": body.ip_allowlist, "rotated_from": str(rotated_from) if rotated_from else None},
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="api_key_create",
            record_type="api_key",
            record_id=k.id,
            new={"name": k.name, "scopes": k.scopes},
            request=self.request,
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="integrations.api_key_created",
            payload={"id": str(k.id), "prefix": prefix},
            aggregate_type="api_key",
            aggregate_id=k.id,
            actor_user_id=self.principal.id,
        )
        return ApiKeyCreatedOut(**(await self._out(k)).model_dump(), secret=secret)

    async def _get(self, kid: uuid.UUID) -> ApiKey:
        k = await self.db.get(ApiKey, kid)
        if k is None or k.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "API key not found")
        return k

    async def rotate(self, kid: uuid.UUID) -> ApiKeyCreatedOut:
        self._writer()
        old = await self._get(kid)
        meta = await _meta(self.db, self.inst, old.id)
        new = await self.create(
            ApiKeyCreate(
                name=old.name,
                scopes=list(old.scopes or []),
                rate_limit_per_minute=old.rate_limit_per_minute,
                expires_at=old.expires_at,
                ip_allowlist=list(meta.get("ip_allowlist") or []),
            ),
            rotated_from=old.id,
        )
        await _put_meta(
            self.db,
            self.inst,
            old.id,
            {**meta, "grace_until": (datetime.now(UTC) + timedelta(hours=24)).isoformat(), "rotated_to": str(new.id)},
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="integrations.api_key_rotated",
            payload={"id": str(old.id), "new_id": str(new.id)},
            aggregate_type="api_key",
            aggregate_id=old.id,
        )
        return new

    async def revoke(self, kid: uuid.UUID) -> None:
        self._writer()
        k = await self._get(kid)
        k.is_active, k.revoked_at = False, datetime.now(UTC)
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="integrations",
            action="api_key_revoke",
            record_type="api_key",
            record_id=k.id,
            request=self.request,
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="integrations.api_key_revoked",
            payload={"id": str(k.id)},
            aggregate_type="api_key",
            aggregate_id=k.id,
        )

    async def usage(self, kid: uuid.UUID) -> dict[str, int]:
        await self._get(kid)
        out = {}
        for n in range(14):
            d = (date.today() - timedelta(days=n)).isoformat()
            out[d] = int(await redis_client.get(f"apikey:{kid}:{d}") or 0)
        return out


class _ServiceUser:
    """The key creator's row seen through an API key: never a super admin, never asked to change a password."""

    def __init__(self, user: Any):
        self._u = user

    is_super_admin = False
    must_change_password = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._u, name)


# ---- rule 3 -----------------------------------------------------------------------------------------------------------------
async def principal_from_api_key(request: Request, secret: str, db: AsyncSession) -> Any:
    from app.core.authz.dependencies import Principal
    from app.core.features import effective_features
    from app.db.session import PlatformSessionLocal, bind_tenant, set_tenant
    from app.models.platform import User

    async with PlatformSessionLocal() as pdb:
        k = (await pdb.execute(select(ApiKey).where(ApiKey.hashed_key == hash_key(secret)))).scalar_one_or_none()
        meta = await _meta(pdb, k.institution_id, k.id) if k else {}
        now = datetime.now(UTC)
        grace = meta.get("grace_until")
        if (
            k is None
            or not k.is_active
            or (k.expires_at and k.expires_at <= now)
            or (grace and datetime.fromisoformat(grace) <= now)
        ):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid or expired API key")
        ip = request.client.host if request.client else ""
        allow = list(meta.get("ip_allowlist") or [])
        if allow and ip not in allow:
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "This API key is not allowed from this address")
        minute = int(time.time() // 60)
        n = int(await redis_client.incr(f"apikey:{k.id}:m{minute}"))
        if n == 1:
            await redis_client.expire(f"apikey:{k.id}:m{minute}", 61)
        if n > k.rate_limit_per_minute:
            raise APIError(
                429, ErrorCode.RATE_LIMITED, "API key rate limit exceeded", {"limit": k.rate_limit_per_minute}
            )
        await redis_client.incr(f"apikey:{k.id}:{date.today().isoformat()}")
        if not k.last_used_at or (now - k.last_used_at).total_seconds() > 60:
            k.last_used_at = now
            await pdb.commit()
        inst, creator, scopes, kid = k.institution_id, k.created_by, list(k.scopes or []), k.id
    bind_tenant(db, inst)
    await set_tenant(db, inst)
    user = await db.get(User, creator) if creator else None
    if user is None:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "API key owner no longer exists")
    request.state.institution_id, request.state.user_id = inst, user.id
    request.state.api_key_id = kid
    p = Principal(
        _ServiceUser(user),
        ["api_key"],
        scope_permissions(scopes),
        [("institution", None)],
        await effective_features(inst),
        claims={"api_key": str(kid)},
    )
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        await log_audit(
            db,
            principal=p,
            module="integrations",
            action="api_key_use",
            record_type="api_key",
            record_id=kid,
            new={"path": request.url.path, "method": request.method},
            request=request,
        )
    return p
