"""Shared helpers of the Phase 40 website services — Prompts/40 "Visibility rules" / §40.5.

* Editing is institution scoped: ``website:manage`` (or ``update``) edits, ``website:publish`` goes live; college
  admins are limited to ``college:{code}`` sections of their colleges and HODs to ``department:{code}`` of their
  departments (checked by :meth:`WebsiteBase.require_section`); auditors read only.
* Public reads resolve the tenant from ``?slug=`` / ``?institution=`` / a verified custom host / the header and only
  ever return published rows, aggregates and token documents.
* Column-less facts live in ``institution_settings`` category ``website_meta`` (``config:draft``, ``config:versions``,
  ``catalogue``, ``disclosures``, ``notice:<id>``, ``enquiry:<id>``, ``domain:<id>``, ``event:<id>``, ``marketing``…).
* Page cache: Redis ``site:{inst}:{path}:{locale}`` (HTML / JSON + ETag) with ``site_ver:{inst}`` bumped by every
  publish so stale keys miss without a scan.
"""

import hashlib
import html
import json
import re
import uuid
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.db.session import bind_tenant, redis_client, set_tenant
from app.enums.website import ALLOWED_TAGS, EMBED_HOSTS

META = "website_meta"
_DROP_CONTENT = {"script", "style", "object", "embed", "form", "input", "button", "textarea", "select"}
_ALLOWED_ATTRS = {"href", "src", "alt", "title", "width", "height", "colspan", "rowspan", "class", "allowfullscreen"}


class _Sanitiser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED_TAGS:
            return
        kept: list[str] = []
        for k, v in attrs:
            if k not in _ALLOWED_ATTRS or v is None:
                continue
            if k in ("href", "src"):
                p = urlparse(v.strip())
                if p.scheme not in ("http", "https", "") or v.strip().lower().startswith(("javascript:", "data:")):
                    continue
                if tag == "iframe" and p.hostname not in EMBED_HOSTS:
                    return  # only allow-listed embeds (YouTube / Maps)
            kept.append(f'{k}="{html.escape(v, quote=True)}"')
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if urlparse(href).scheme in ("http", "https"):
                kept.append('rel="nofollow noopener" target="_blank"')
        if tag == "iframe" and not any(a.startswith("src=") for a in kept):
            return
        self.out.append(f"<{tag}{' ' + ' '.join(kept) if kept else ''}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if not self.skip and tag in ALLOWED_TAGS and tag not in ("br", "hr", "img"):
            self.out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(html.escape(data, quote=False))


def sanitise(body: str | None) -> str | None:
    """Allow-list HTML sanitiser (§40.6 rule 4): headings, lists, links (external → nofollow), images, tables and
    YouTube / Maps embeds; scripts, event handlers, ``javascript:`` URLs and forms are removed."""
    if body is None:
        return None
    p = _Sanitiser()
    p.feed(body)
    p.close()
    return "".join(p.out)


def slugify(value: str, max_len: int = 120) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (s or uuid.uuid4().hex[:8])[:max_len]


def etag_of(payload: str) -> str:
    return '"' + hashlib.sha256(payload.encode()).hexdigest()[:32] + '"'


async def site_version(inst: Any) -> int:
    v = await redis_client.get(f"site_ver:{inst}")
    return int(v or 0)


async def invalidate(inst: Any) -> None:
    """Every publish / content change bumps the version; cached pages of the old version simply miss."""
    await redis_client.incr(f"site_ver:{inst}")


async def resolve_public_tenant(
    db: AsyncSession, request: Request | None, slug: str | None = None, host: str | None = None
) -> tuple[uuid.UUID, str]:
    """Tenant of a public website call: ``slug`` → institution; else a verified custom host; else the header."""
    from app.db.session import PlatformSessionLocal

    row: Any = None
    async with PlatformSessionLocal() as pdb:
        if slug:
            row = (
                await pdb.execute(
                    text("SELECT id, slug FROM institutions WHERE slug = :s AND deleted_at IS NULL"), {"s": slug[:60]}
                )
            ).first()
        if row is None:
            hostname = (host or (request.headers.get("host") if request else "") or "").split(":")[0].lower()
            if hostname:
                cached = await redis_client.get(f"host:{hostname}")
                if cached and cached != "-":
                    c_iid, c_slug = str(cached).split("|", 1)
                    row = (uuid.UUID(c_iid), c_slug)
                elif not cached:
                    r = (
                        await pdb.execute(
                            text(
                                "SELECT i.id, i.slug FROM institution_domains d JOIN institutions i ON i.id = d.institution_id "
                                "WHERE d.hostname = :h AND d.verified_at IS NOT NULL AND i.deleted_at IS NULL"
                            ),
                            {"h": hostname},
                        )
                    ).first()
                    if r is not None:
                        await redis_client.set(f"host:{hostname}", f"{r[0]}|{r[1]}", ex=300)
                        row = (r[0], r[1])
        if row is None and request is not None and getattr(request.state, "institution_id", None):
            r = (
                await pdb.execute(
                    text("SELECT id, slug FROM institutions WHERE id = :i"), {"i": str(request.state.institution_id)}
                )
            ).first()
            row = (r[0], r[1]) if r else None
    if row is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Website not found")
    tenant = uuid.UUID(str(row[0]))
    bind_tenant(db, tenant)
    await set_tenant(db, tenant)
    return tenant, str(row[1])


class WebsiteBase:
    def __init__(
        self, db: AsyncSession, principal: Any, request: Request | None = None, institution_id: uuid.UUID | None = None
    ):
        self.db, self.principal, self.request = db, principal, request
        inst = institution_id or (getattr(principal, "institution_id", None) if principal else None)
        if inst is None and request is not None and getattr(principal, "is_super_admin", False):
            raw = getattr(request.state, "institution_id", None)
            inst = uuid.UUID(str(raw)) if raw else None
        if inst is None:
            raise APIError(422, ErrorCode.VALIDATION, "An institution context is required")
        self.inst: uuid.UUID = uuid.UUID(str(inst))

    # ---- permissions ------------------------------------------------------------------------------------------------
    def can(self, action: str) -> bool:
        return bool(self.principal is not None and self.principal.has("website", action))

    def require(self, *actions: str) -> None:
        if not any(self.can(a) for a in actions):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")

    def full_editor(self) -> bool:
        return self.can("manage") or bool(self.principal and self.principal.is_super_admin)

    async def section_scopes(self) -> list[str] | None:
        """``None`` = every section; else the ``college:{code}`` / ``department:{code}`` prefixes the caller may edit."""
        if self.full_editor():
            return None
        out: list[str] = []
        for st, sid in getattr(self.principal, "scopes", []):
            if st == "college" and sid:
                r = (await self.db.execute(text("SELECT code FROM colleges WHERE id = :i"), {"i": sid})).first()
                if r:
                    out.append(f"college:{r[0]}")
            if st == "department" and sid:
                r = (await self.db.execute(text("SELECT code FROM departments WHERE id = :i"), {"i": sid})).first()
                if r:
                    out.append(f"department:{r[0]}")
        return out

    async def require_section(self, section: str) -> None:
        scopes = await self.section_scopes()
        if scopes is None:
            return
        if section not in scopes:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, f"You may edit only {', '.join(scopes) or 'no'} sections")

    # ---- settings / meta ------------------------------------------------------------------------------------------
    async def setting(self, key: str, category: str = "website") -> Any:
        from app.services.settings_service import SettingsService

        return await SettingsService(self.db).value(self.inst, category, key)

    async def meta(self, key: str, default: Any = None) -> Any:
        r = (
            await self.db.execute(
                text(
                    "SELECT value FROM institution_settings WHERE institution_id = :i AND category = :c AND key = :k "
                    "AND college_id IS NULL"
                ),
                {"i": self.inst, "c": META, "k": key},
            )
        ).first()
        return r[0] if r and r[0] is not None else default

    async def put_meta(self, key: str, value: Any) -> None:
        await self.db.execute(
            text(
                "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, "
                "is_public, created_at, updated_at) VALUES (:id, :i, NULL, :c, :k, CAST(:v AS jsonb), 'json', FALSE, "
                "NOW(), NOW()) ON CONFLICT (institution_id, college_id, category, key) DO UPDATE SET "
                "value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"id": uuid.uuid4(), "i": self.inst, "c": META, "k": key, "v": json.dumps(value, default=str)},
        )

    async def audit(self, action: str, record_type: str, record_id: Any, new: dict[str, Any] | None = None) -> None:
        if self.principal is None:
            return
        await log_audit(
            self.db,
            principal=self.principal,
            module="website",
            action=action,
            record_type=record_type,
            record_id=record_id if isinstance(record_id, uuid.UUID) else None,
            new=new,
            request=self.request,
        )

    async def emit(self, event_type: str, payload: dict[str, Any], aggregate_id: Any = None) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type=event_type,
            payload=payload,
            aggregate_type="website",
            aggregate_id=aggregate_id if isinstance(aggregate_id, uuid.UUID) else None,
            actor_user_id=getattr(self.principal, "id", None),
        )
