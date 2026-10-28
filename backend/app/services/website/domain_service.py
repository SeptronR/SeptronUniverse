"""Custom domains — Prompts/40 §40.6 ``domain_service`` (``website.custom_domain``).

Business rules
1. Add: hostname validated (pattern, not a reserved / platform host, unique platform-wide → 409), a random
   ``verification_token`` and DNS instructions (TXT ``_universe-verify.<host>`` = token; CNAME to ``EDGE_HOSTNAME``).
2. Verify: TXT lookup through ``dnspython`` when installed, else the development resolver (Redis ``dns:txt:<name>``,
   set by the seeder / ``/_dev``); success → ``verified_at`` + ``ssl_status='provisioning'``; Beat
   ``website.domain_verify_retry`` (15 min) retries unverified domains for 72 h; the check log in ``domain:<id>``.
3. Edge: ``GET /internal/domains`` (``X-Edge-Token`` = ``EDGE_TOKEN``) lists verified domains for the Phase 44
   Traefik provider; ``POST /internal/domains/{id}/ssl-status`` records ``active`` / ``failed`` (reason) and notifies
   the institution admins (``website.domain_ssl_ready|failed``).
4. Primary: one per institution; ``/site/:slug`` redirects (301) to an active primary host; remove = delete + edge
   drop + host cache flush. Login on a custom host only after ``active`` (``host_login_allowed``).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.notifications.notify import notify_event
from app.db.session import redis_client
from app.enums.website import RESERVED_HOSTS
from app.models.website import InstitutionDomain
from app.schemas.website import DomainIn, DomainOut, DomainVerifyResult
from app.services.website.common import WebsiteBase, invalidate

EDGE_HOSTNAME = settings.EDGE_HOSTNAME
TXT_PREFIX = "_universe-verify"
RETRY_WINDOW = timedelta(hours=72)


async def lookup_txt(name: str) -> list[str]:
    try:
        import dns.asyncresolver  # type: ignore[import-not-found]

        answers = await dns.asyncresolver.resolve(name, "TXT", lifetime=5)
        return [b"".join(r.strings).decode() for r in answers]
    except ImportError:
        v = await redis_client.get(f"dns:txt:{name}")
        return [str(v)] if v else []
    except Exception:  # noqa: BLE001 - NXDOMAIN / timeout = not verified yet
        return []


class DomainService(WebsiteBase):
    def _out(self, d: InstitutionDomain, check: dict[str, Any] | None = None) -> DomainOut:
        o = DomainOut.model_validate(d)
        o.dns_instructions = {
            "txt_name": f"{TXT_PREFIX}.{d.hostname}",
            "txt_value": d.verification_token or "",
            "cname_target": EDGE_HOSTNAME,
        }
        o.last_check = check
        return o

    async def list(self) -> list[DomainOut]:
        self.require("view", "manage")
        rows = (
            await self.db.execute(
                select(InstitutionDomain)
                .where(InstitutionDomain.institution_id == self.inst)
                .order_by(InstitutionDomain.created_at)
            )
        ).scalars()
        return [self._out(d, await self.meta(f"domain:{d.id}")) for d in rows]

    async def add(self, body: DomainIn) -> DomainOut:
        self.require("manage")
        host = body.hostname.lower().strip(".")
        reserved = [str(x) for x in (await self.setting("reserved_slugs") or [])]
        if host.startswith(RESERVED_HOSTS) or host.split(".")[0] in reserved or host.endswith(".septron.in"):
            raise APIError(422, ErrorCode.VALIDATION, "This hostname is reserved", {"field": "hostname"})
        taken = (
            await self.db.execute(text("SELECT 1 FROM institution_domains WHERE hostname = :h"), {"h": host})
        ).first()
        if taken:
            raise APIError(409, ErrorCode.CONFLICT, "This hostname is already in use", {"field": "hostname"})
        d = InstitutionDomain(
            institution_id=self.inst, hostname=host, verification_token=secrets.token_hex(16), ssl_status="pending"
        )
        self.db.add(d)
        await self.db.flush()
        await self.put_meta(
            f"domain:{d.id}", {"added_at": datetime.now(UTC).isoformat(), "make_primary": body.make_primary}
        )
        await self.audit("domain_add", "institution_domain", d.id, {"hostname": host})
        await self.emit("website.domain_added", {"id": str(d.id), "hostname": host}, d.id)
        return self._out(d)

    async def _get(self, did: uuid.UUID) -> InstitutionDomain:
        d = await self.db.get(InstitutionDomain, did)
        if d is None or d.institution_id != self.inst:
            raise APIError(404, ErrorCode.NOT_FOUND, "Domain not found")
        return d

    async def verify(self, did: uuid.UUID) -> DomainVerifyResult:
        self.require("manage")
        d = await self._get(did)
        await self.audit("domain_verify", "institution_domain", d.id, {"hostname": d.hostname})
        return await verify_domain(self.db, d, self)

    async def make_primary(self, did: uuid.UUID) -> DomainOut:
        self.require("manage")
        d = await self._get(did)
        if d.verified_at is None:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Verify the domain first")
        await self.db.execute(
            update(InstitutionDomain).where(InstitutionDomain.institution_id == self.inst).values(is_primary=False)
        )
        d.is_primary = True
        await self.db.flush()
        await invalidate(self.inst)
        await self.audit("domain_primary", "institution_domain", d.id, {"hostname": d.hostname})
        await self.emit("website.domain_primary_changed", {"id": str(d.id), "hostname": d.hostname}, d.id)
        return self._out(d)

    async def remove(self, did: uuid.UUID) -> None:
        self.require("manage")
        d = await self._get(did)
        host = d.hostname
        await self.db.delete(d)
        await redis_client.delete(f"host:{host}")
        await invalidate(self.inst)
        await self.audit("domain_remove", "institution_domain", did, {"hostname": host})
        await self.emit("website.domain_removed", {"hostname": host})


async def verify_domain(db: Any, d: InstitutionDomain, svc: Any | None = None) -> DomainVerifyResult:
    found = await lookup_txt(f"{TXT_PREFIX}.{d.hostname}")
    ok = bool(d.verification_token and d.verification_token in found)
    if ok and d.verified_at is None:
        d.verified_at = datetime.now(UTC)
        d.ssl_status = "provisioning"
        await db.flush()
        await notify_event(
            db,
            d.institution_id,
            "website.domain_verified",
            audience={"roles": ["institution_admin"]},
            context={"hostname": d.hostname, "route": "/admin/website/domains"},
        )
    if svc is not None:
        meta = await svc.meta(f"domain:{d.id}", {}) or {}
        await svc.put_meta(
            f"domain:{d.id}", {**meta, "checked_at": datetime.now(UTC).isoformat(), "found": found[:5], "ok": ok}
        )
        if ok:
            await svc.emit("website.domain_verified", {"id": str(d.id), "hostname": d.hostname}, d.id)
            if meta.get("make_primary"):
                await svc.make_primary(d.id)
    return DomainVerifyResult(
        ok=ok or d.verified_at is not None,
        hostname=d.hostname,
        found=found[:5],
        ssl_status=d.ssl_status,
        message="Verified — the certificate is being issued"
        if ok
        else ("Already verified" if d.verified_at else "TXT record not found yet"),
    )


async def retry_unverified(db: Any) -> int:
    """Beat ``website.domain_verify_retry`` (platform session): unverified domains younger than 72 h."""
    rows = (
        await db.execute(
            select(InstitutionDomain).where(
                InstitutionDomain.verified_at.is_(None), InstitutionDomain.created_at > datetime.now(UTC) - RETRY_WINDOW
            )
        )
    ).scalars()
    n = 0
    for d in rows:
        if (await verify_domain(db, d)).ok:
            n += 1
    return n


async def edge_list(db: Any) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                text(
                    "SELECT d.id, d.hostname, i.slug AS institution_slug, d.is_primary, d.ssl_status FROM institution_domains d "
                    "JOIN institutions i ON i.id = d.institution_id WHERE d.verified_at IS NOT NULL AND i.deleted_at IS NULL "
                    "ORDER BY d.hostname"
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def edge_ssl_status(db: Any, did: uuid.UUID, status: str, reason: str | None) -> dict[str, Any]:
    d = await db.get(InstitutionDomain, did)
    if d is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Domain not found")
    d.ssl_status = status
    await db.flush()
    await redis_client.delete(f"host:{d.hostname}")
    event = {"active": "website.domain_ssl_ready", "failed": "website.domain_ssl_failed"}.get(status)
    if event:
        await notify_event(
            db,
            d.institution_id,
            event,
            audience={"roles": ["institution_admin"]},
            context={"hostname": d.hostname, "reason": reason or "", "route": "/admin/website/domains"},
        )
    from app.core import events

    await events.emit(
        db,
        institution_id=d.institution_id,
        event_type=f"website.ssl_{status}",
        payload={"id": str(d.id), "reason": reason},
        aggregate_type="institution_domain",
        aggregate_id=d.id,
    )
    return {"id": str(d.id), "ssl_status": status}


async def host_login_allowed(db: Any, host: str) -> bool:
    r = (
        await db.execute(
            text("SELECT ssl_status FROM institution_domains WHERE hostname = :h"), {"h": host.split(":")[0].lower()}
        )
    ).first()
    return r is None or r[0] == "active"
