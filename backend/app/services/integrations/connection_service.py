"""Connections — Prompts/41 §41.6 ``connection_service`` (``integrations:manage|connect``; auditors read redacted).

Business rules
1. Create / update: the provider must exist in the catalogue for the capability; required schema fields present;
   secret fields are encrypted (AES-GCM via ``encrypt_secret``) and never returned — reads show ``***``; sending
   ``***`` keeps the stored value. The capability's integration feature (``integrations.sso`` …) must be on (403).
   College admins create / read only ``college:{code}`` connections of their colleges (label forced).
2. ``test``: a capability-specific probe through the real adapter (ping → ``health()``; ``send_test`` → a message to
   the caller; ``create_order`` → ₹1 sandbox order; ``lookup`` → a sample lookup); result recorded as a health row.
   SMS for an IN-pack tenant without an approved DLT template warns.
3. Health: Beat ``integrations.health`` (15 min) records checks; one failure → ``degraded``, three in a row →
   ``failed`` (+ ``integrations.connection_failed`` to the integration admins); success after failure →
   ``healthy`` + ``integrations.connection_recovered``.
4. ``set-default`` marks one connection per capability (``public_config.is_default``); ``disable`` / ``enable``;
   delete. Every change is audited and emits ``integrations.connection_*``.
5. ``capabilities``: per capability the effective provider / status, the gating feature and the module features
   using it (feature flag state included) — the Phase 38 health page and the settings hints read it.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.notifications.notify import notify_event
from app.integrations.catalogue import CAPABILITY_INFO, catalogue_json, provider_info
from app.integrations.hub import build_adapter, decrypt_config, encrypt_config
from app.models.platform import IntegrationConnection, IntegrationHealthCheck
from app.schemas.integrations import (
    CapabilityStatusOut,
    ConnectionIn,
    ConnectionOut,
    ConnectionTestOut,
    ConnectionTestRequest,
)

MASK = "***"


class ConnectionService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst: uuid.UUID = principal.institution_id

    # ---- permissions ------------------------------------------------------------------------------------------------
    def _manager(self) -> bool:
        return bool(self.principal.has("integrations", "manage") or self.principal.has("integrations", "connect"))

    async def _college_labels(self) -> list[str] | None:
        """``None`` = every connection (integration / institution admins, auditors); else the college labels."""
        if self._manager() or self.principal.has("integrations", "view_all"):
            return None
        labels = []
        for st, sid in self.principal.scopes:
            if st == "college" and sid:
                r = (await self.db.execute(text("SELECT code FROM colleges WHERE id = :i"), {"i": sid})).first()
                if r:
                    labels.append(f"college:{r[0]}")
        return labels

    async def _get(self, cid: uuid.UUID) -> IntegrationConnection:
        c = await self.db.get(IntegrationConnection, cid)
        if c is None or c.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Connection not found")
        labels = await self._college_labels()
        if labels is not None and c.label not in labels:
            raise APIError(404, ErrorCode.NOT_FOUND, "Connection not found")
        return c

    def _out(self, c: IntegrationConnection, history: list[dict[str, Any]] | None = None) -> ConnectionOut:
        info = provider_info(c.capability, c.provider)
        secrets = set(info.secret_fields() if info else [])
        stored = decrypt_config(c.config_encrypted)
        redacted = {k: (MASK if k in secrets and v else v) for k, v in stored.items()}
        pub = dict(c.public_config or {})
        return ConnectionOut(
            id=c.id,
            capability=c.capability,
            provider=c.provider,
            label=c.label,
            config_redacted=redacted,
            public_config={k: v for k, v in pub.items() if k != "is_default"},
            is_sandbox=c.is_sandbox,
            is_default=bool(pub.get("is_default")),
            status=c.status,
            last_health_at=c.last_health_at,
            last_error=c.last_error,
            created_at=c.created_at,
            health_history=history or [],
        )

    # ---- reads --------------------------------------------------------------------------------------------------------
    def providers(self) -> list[dict[str, Any]]:
        return catalogue_json()

    async def list(self, capability: str | None) -> list[ConnectionOut]:
        q = select(IntegrationConnection).where(IntegrationConnection.institution_id == self.inst)
        if capability:
            q = q.where(IntegrationConnection.capability == capability)
        labels = await self._college_labels()
        rows = (await self.db.execute(q.order_by(IntegrationConnection.capability, IntegrationConnection.created_at))).scalars()
        return [self._out(c) for c in rows if labels is None or c.label in labels]

    async def get(self, cid: uuid.UUID) -> ConnectionOut:
        c = await self._get(cid)
        hist = (
            await self.db.execute(
                select(IntegrationHealthCheck).where(IntegrationHealthCheck.connection_id == c.id).order_by(IntegrationHealthCheck.checked_at.desc()).limit(50)
            )
        ).scalars()
        return self._out(c, [{"at": h.checked_at, "ok": h.ok, "latency_ms": h.latency_ms, "detail": h.detail} for h in hist])

    async def health(self, cid: uuid.UUID) -> list[dict[str, Any]]:
        return (await self.get(cid)).health_history

    # ---- rule 1 -------------------------------------------------------------------------------------------------------
    async def _check_feature(self, capability: str) -> None:
        info = CAPABILITY_INFO.get(capability)
        if info is None:
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown capability {capability!r}", {"field": "capability"})
        if info.feature and not self.principal.has_feature(info.feature):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{info.feature}' is not enabled", {"feature": info.feature})

    def _merge(self, capability: str, provider: str, incoming: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
        info = provider_info(capability, provider)
        if info is None and provider != "mock":
            raise APIError(422, ErrorCode.VALIDATION, f"Unknown provider {provider!r} for {capability}", {"field": "provider"})
        merged = {k: (stored.get(k) if v == MASK else v) for k, v in incoming.items()}
        for k, v in stored.items():
            merged.setdefault(k, v)
        if info is not None:
            missing = [k for k, f in info.fields.items() if f.get("required") and merged.get(k) in (None, "")]
            if missing:
                raise APIError(422, ErrorCode.VALIDATION, f"Missing fields: {', '.join(missing)}", {"fields": missing})
        return merged

    async def create(self, body: ConnectionIn) -> ConnectionOut:
        await self._check_feature(body.capability)
        label = body.label
        if body.college_id is not None:
            code = (await self.db.execute(text("SELECT code FROM colleges WHERE id = :i AND institution_id = :n"), {"i": body.college_id, "n": self.inst})).scalar_one_or_none()
            if code is None:
                raise APIError(422, ErrorCode.VALIDATION, "Unknown college", {"field": "college_id"})
            label = f"college:{code}"
        labels = await self._college_labels()
        if labels is not None:
            if not self.principal.has("integrations", "connect") and not labels:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")
            if label not in labels:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "College admins manage only their college's connections")
        elif not self._manager():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")
        exists = (
            await self.db.execute(
                select(IntegrationConnection.id).where(
                    IntegrationConnection.institution_id == self.inst,
                    IntegrationConnection.capability == body.capability,
                    IntegrationConnection.provider == body.provider,
                    IntegrationConnection.label.is_(None) if label is None else IntegrationConnection.label == label,
                )
            )
        ).first()
        if exists:
            raise APIError(409, ErrorCode.CONFLICT, "A connection for this provider and label exists")
        cfg = self._merge(body.capability, body.provider, body.config, {})
        c = IntegrationConnection(
            institution_id=self.inst,
            capability=body.capability,
            provider=body.provider,
            label=label,
            config_encrypted=encrypt_config(cfg),
            public_config={**body.public_config, "kid": "v1"},
            is_sandbox=body.is_sandbox,
            status="configured",
            created_by=self.principal.id,
        )
        self.db.add(c)
        await self.db.flush()
        await self._audit("connection_create", c, {"capability": c.capability, "provider": c.provider, "label": label})
        await self._emit("integrations.connection_created", c)
        return self._out(c)

    async def update(self, cid: uuid.UUID, body: ConnectionIn) -> ConnectionOut:
        c = await self._get(cid)
        if not self._manager() and (await self._college_labels()) is not None and c.label is None:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")
        await self._check_feature(c.capability)
        cfg = self._merge(c.capability, body.provider or c.provider, body.config, decrypt_config(c.config_encrypted))
        old_provider = c.provider
        c.provider = body.provider or c.provider
        c.config_encrypted = encrypt_config(cfg)
        pub = dict(c.public_config or {})
        c.public_config = {**body.public_config, "kid": pub.get("kid", "v1"), **({"is_default": True} if pub.get("is_default") else {})}
        c.is_sandbox = body.is_sandbox
        c.status = "configured"
        await self.db.flush()
        await self._audit("connection_update", c, {"provider_from": old_provider, "provider_to": c.provider})
        await self._emit("integrations.connection_updated", c)
        return self._out(c)

    async def delete(self, cid: uuid.UUID) -> None:
        c = await self._get(cid)
        if not self._manager():
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")
        await self._audit("connection_delete", c, {"capability": c.capability, "provider": c.provider})
        await self.db.delete(c)

    async def set_enabled(self, cid: uuid.UUID, enabled: bool) -> ConnectionOut:
        c = await self._get(cid)
        c.status = "configured" if enabled else "disabled"
        await self.db.flush()
        await self._audit("connection_enable" if enabled else "connection_disable", c, {})
        await self._emit("integrations.connection_enabled" if enabled else "integrations.connection_disabled", c)
        return self._out(c)

    async def set_default(self, cid: uuid.UUID) -> ConnectionOut:
        c = await self._get(cid)
        rows = (await self.db.execute(select(IntegrationConnection).where(IntegrationConnection.institution_id == self.inst, IntegrationConnection.capability == c.capability))).scalars()
        for r in rows:
            pub = dict(r.public_config or {})
            pub.pop("is_default", None)
            if r.id == c.id:
                pub["is_default"] = True
            r.public_config = pub
        await self.db.flush()
        await self._audit("connection_default", c, {"capability": c.capability})
        await self._emit("integrations.default_changed", c)
        return self._out(c)

    # ---- rule 2 -------------------------------------------------------------------------------------------------------
    async def test(self, cid: uuid.UUID, body: ConnectionTestRequest) -> ConnectionTestOut:
        c = await self._get(cid)
        cfg = {**{k: v for k, v in (c.public_config or {}).items() if k not in ("is_default", "kid")}, **decrypt_config(c.config_encrypted)}
        adapter = build_adapter(c.capability, c.provider, cfg, connection_id=c.id, sandbox=c.is_sandbox)
        warnings: list[str] = []
        t0 = time.perf_counter()
        sample: dict[str, Any] | None = None
        try:
            if body.action == "send_test" and c.capability in ("sms", "email", "whatsapp", "push"):
                to = body.params.get("to") or (self.principal.user.email if c.capability == "email" else getattr(self.principal.user, "phone", None))
                if c.capability == "sms":
                    pack = (await self.db.execute(text("SELECT regulatory_pack FROM institutions WHERE id = :i"), {"i": self.inst})).scalar_one_or_none()
                    if pack == "IN" and not body.params.get("dlt_template_id"):
                        warnings.append("No approved DLT template id given — live SMS in India will be rejected")
                sample = await adapter.send(to=str(to or "test"), body="SeptronUniverse test message", subject="Test", **{k: v for k, v in body.params.items() if k != "to"})
                ok, detail = True, "sent"
            elif body.action == "create_order" and c.capability == "payment":
                sample = await adapter.create_order(amount_paise=100, receipt=f"test-{uuid.uuid4().hex[:8]}")
                ok, detail = True, "order created"
            elif body.action == "lookup" and hasattr(adapter, "lookup_doi"):
                sample = await adapter.lookup_doi(str(body.params.get("doi") or "10.1038/nature12373"))
                ok, detail = True, "lookup ok"
            else:
                ok, detail = await adapter.health()
        except APIError as exc:
            ok, detail = False, exc.message
        except Exception as exc:  # noqa: BLE001 - the provider's error is the test result
            ok, detail = False, str(exc)[:300]
        latency = int((time.perf_counter() - t0) * 1000)
        await record_health(self.db, c, ok, latency, detail)
        await self._emit("integrations.connection_tested", c, {"ok": ok})
        return ConnectionTestOut(ok=ok, latency_ms=latency, detail=str(detail)[:500], sample=sample if isinstance(sample, dict) else None, warnings=warnings)

    # ---- rule 5 -------------------------------------------------------------------------------------------------------
    async def capabilities(self) -> list[CapabilityStatusOut]:
        rows = (await self.db.execute(select(IntegrationConnection).where(IntegrationConnection.institution_id == self.inst))).scalars().all()
        out = []
        for key, info in CAPABILITY_INFO.items():
            mine = [r for r in rows if r.capability == key and not str(r.label or "").startswith("college:")]
            pick = next((r for r in mine if (r.public_config or {}).get("is_default")), None) or next((r for r in mine if r.status != "disabled"), None)
            out.append(
                CapabilityStatusOut(
                    capability=key,
                    name=info.name,
                    provider=pick.provider if pick else None,
                    status=pick.status if pick else "not_configured",
                    connection_id=pick.id if pick else None,
                    feature=info.feature,
                    feature_enabled=not info.feature or self.principal.has_feature(info.feature),
                    used_by_features=[f for f in info.used_by if self.principal.has_feature(f)] or list(info.used_by),
                    last_error=pick.last_error if pick else None,
                )
            )
        return out

    # ---- helpers ------------------------------------------------------------------------------------------------------
    async def _audit(self, action: str, c: IntegrationConnection, new: dict[str, Any]) -> None:
        await log_audit(self.db, principal=self.principal, module="integrations", action=action, record_type="integration_connection", record_id=c.id, new=new, request=self.request)

    async def _emit(self, event_type: str, c: IntegrationConnection, extra: dict[str, Any] | None = None) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=event_type,
            payload={"connection_id": str(c.id), "capability": c.capability, "provider": c.provider, **(extra or {})},
            aggregate_type="integration_connection",
            aggregate_id=c.id,
            actor_user_id=self.principal.id,
        )


async def record_health(db: Any, c: IntegrationConnection, ok: bool, latency: int, detail: str) -> None:
    """Rule 3 — shared by tests and the Beat probe (platform session)."""
    db.add(IntegrationHealthCheck(institution_id=c.institution_id, connection_id=c.id, ok=ok, latency_ms=latency, detail=str(detail)[:500]))
    previous = c.status
    c.last_health_at = datetime.now(UTC)
    c.last_error = None if ok else str(detail)[:500]
    if c.status == "disabled":
        await db.flush()
        return
    if ok:
        c.status = "healthy"
    else:
        recent = (
            await db.execute(
                select(IntegrationHealthCheck.ok).where(IntegrationHealthCheck.connection_id == c.id).order_by(IntegrationHealthCheck.checked_at.desc()).limit(2)
            )
        ).scalars().all()
        fails = 1 + sum(1 for r in recent if not r)
        c.status = "failed" if fails >= 3 else "degraded"
    await db.flush()
    if c.status == "failed" and previous != "failed":
        await notify_event(db, c.institution_id, "integrations.connection_failed", audience={"roles": ["integration_admin", "institution_admin"]}, context={"capability": c.capability, "provider": c.provider, "error": c.last_error or "", "route": "/admin/integrations"})
        await events.emit(db, institution_id=c.institution_id, event_type="integrations.connection_failed", payload={"connection_id": str(c.id), "capability": c.capability, "provider": c.provider}, aggregate_type="integration_connection", aggregate_id=c.id)
    elif ok and previous in ("failed", "degraded"):
        await notify_event(db, c.institution_id, "integrations.connection_recovered", audience={"roles": ["integration_admin", "institution_admin"]}, context={"capability": c.capability, "provider": c.provider, "route": "/admin/integrations"})
        await events.emit(db, institution_id=c.institution_id, event_type="integrations.connection_recovered", payload={"connection_id": str(c.id)}, aggregate_type="integration_connection", aggregate_id=c.id)


async def reencrypt_all(db: Any, new_kid: str) -> int:
    """Job ``integrations.reencrypt_secrets``: decrypt with the current key and re-encrypt (key rotation, ``kid``)."""
    n = 0
    for c in (await db.execute(select(IntegrationConnection))).scalars():
        cfg = decrypt_config(c.config_encrypted)
        c.config_encrypted = encrypt_config(cfg)
        c.public_config = {**(c.public_config or {}), "kid": new_kid}
        n += 1
    await db.flush()
    return n
