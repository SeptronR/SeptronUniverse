"""Site configuration, rendering and analytics — Prompts/40 §40.6 ``site_service``.

Business rules
1. Draft → preview → publish: ``PUT /website/config`` (``website:update|manage``) stores the draft in ``website_meta
   config:draft``; the ``institution_website_config`` row is the **published** copy. A signed preview token (HMAC,
   2 h) renders the draft on ``/site/:slug?preview=<token>``. ``publish`` (``website:publish``) copies the draft into
   the row, appends ``config:versions`` (≤ 50, each with the full published copy), bumps the cache version and emits
   ``website.published``; ``rollback/{version}`` republishes an older copy as a new version.
2. Rendering assembles every visible section from the owning modules (profile, programmes, admission cycles,
   notices, events, gallery, Phase 35 public counters, accreditations, Phase 28 placement aggregates, Phase 30
   research counts, colleges / departments, the allow-listed faculty directory, disclosures, Phase 33 policies /
   committees, contact) — each source in a SAVEPOINT so one module never breaks the page; personal data is never
   selected (explicit columns).
3. SSR: ``GET /site/{slug}/…`` returns server-rendered HTML (``<title>``, meta / OG / Twitter, canonical, JSON-LD
   ``CollegeOrUniversity``) with the section data embedded for the client (``window.__SITE__``), cached in Redis per
   (institution, path, version) with an ETag (``304`` on ``If-None-Match``) and
   ``Cache-Control: public, max-age=<ttl>, stale-while-revalidate=600``; preview responses are never cached.
4. Analytics: page views per day (``site:pv:{inst}:{day}`` hash path → count) and visitors (HyperLogLog
   ``site:uv:{inst}:{day}`` over a salted IP hash; no raw IPs stored).
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from html import escape
from typing import Any

import structlog
from sqlalchemy import select, text

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.db.session import redis_client
from app.enums.website import SECTION_TYPES, TEMPLATES
from app.models.website import InstitutionWebsiteConfig
from app.schemas.website import (
    PublicSiteOut,
    SiteAnalyticsOut,
    SiteConfigIn,
    SiteConfigOut,
    SitePreviewToken,
    SiteVersionOut,
)
from app.services.website.common import WebsiteBase, etag_of, invalidate, site_version

log = structlog.get_logger()
CONFIG_FIELDS = ("is_enabled", "theme", "hero", "sections", "seo", "contact", "social", "show_catalog", "show_apply")
PREVIEW_TTL = 7200


def default_config(institution: Any) -> dict[str, Any]:
    kind = getattr(institution, "institution_type", None) or "autonomous_college"
    names = TEMPLATES.get(kind) or TEMPLATES["autonomous_college"]
    return {
        "is_enabled": True,
        "theme": {"name": "indigo"},
        "hero": {
            "title": getattr(institution, "name", "Welcome"),
            "subtitle": "Admissions open — explore our programmes",
            "cta": [{"label": "Apply now", "href": "admissions"}, {"label": "Programmes", "href": "catalogue"}],
        },
        "sections": [
            {"type": t, "key": t, "title": None, "config": {}, "is_visible": True, "sequence": n}
            for n, t in enumerate(names, 1)
        ],
        "seo": {"title": getattr(institution, "name", ""), "description": "", "keywords": [], "robots": "index,follow"},
        "contact": {},
        "social": {},
        "show_catalog": True,
        "show_apply": True,
    }


def _sign(inst: uuid.UUID, exp: int) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"site-preview:{inst}:{exp}".encode(), hashlib.sha256).hexdigest()[
        :40
    ]


def preview_valid(inst: uuid.UUID, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp_s, sig = token.split(".", 1)
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    return exp > time.time() and hmac.compare_digest(_sign(inst, exp), sig)


class SiteService(WebsiteBase):
    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def _row(self) -> InstitutionWebsiteConfig:
        row = (
            await self.db.execute(
                select(InstitutionWebsiteConfig).where(InstitutionWebsiteConfig.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if row is None:
            from app.models.platform import Institution

            inst = await self.db.get(Institution, self.inst)
            row = InstitutionWebsiteConfig(institution_id=self.inst, **default_config(inst))
            self.db.add(row)
            await self.db.flush()
        return row

    @staticmethod
    def _published(row: InstitutionWebsiteConfig) -> dict[str, Any]:
        return {f: getattr(row, f) for f in CONFIG_FIELDS}

    async def get(self) -> SiteConfigOut:
        self.require("view", "update", "manage")
        row = await self._row()
        draft = await self.meta("config:draft")
        versions = await self.meta("config:versions", [])
        data = draft or self._published(row)
        return SiteConfigOut(
            **{**data, "sections": data.get("sections") or []},
            has_unpublished_changes=bool(draft) and draft != json.loads(json.dumps(self._published(row), default=str)),
            published_at=row.updated_at,
            version=len(versions),
        )

    async def save_draft(self, body: SiteConfigIn) -> SiteConfigOut:
        self.require("update", "manage")
        for s in body.sections:
            if s.type not in SECTION_TYPES:
                raise APIError(422, ErrorCode.VALIDATION, f"Unknown section type {s.type!r}", {"field": "sections"})
        data = body.model_dump(mode="json")
        data["sections"] = sorted(data["sections"], key=lambda s: s["sequence"])
        await self.put_meta("config:draft", data)
        await self.audit("config_saved", "website_config", None, {"sections": len(data["sections"])})
        await self.emit("website.config_saved", {"sections": len(data["sections"])})
        return await self.get()

    async def preview_token(self, base_slug: str) -> SitePreviewToken:
        self.require("update", "manage", "publish")
        exp = int(time.time()) + PREVIEW_TTL
        token = f"{exp}.{_sign(self.inst, exp)}"
        return SitePreviewToken(
            token=token, url=f"/site/{base_slug}/?preview={token}", expires_at=datetime.fromtimestamp(exp, UTC)
        )

    async def publish(self, notes: str | None, data: dict[str, Any] | None = None) -> SiteConfigOut:
        self.require("publish")
        row = await self._row()
        payload = data or await self.meta("config:draft") or self._published(row)
        for f in CONFIG_FIELDS:
            if f in payload:
                setattr(row, f, payload[f])
        row.updated_at = datetime.now(UTC)
        versions: list[dict[str, Any]] = list(await self.meta("config:versions", []))
        versions.append(
            {
                "version": len(versions) + 1,
                "published_at": row.updated_at.isoformat(),
                "published_by": str(getattr(self.principal, "id", "")) or None,
                "notes": notes,
                "config": json.loads(json.dumps(self._published(row), default=str)),
            }
        )
        await self.put_meta("config:versions", versions[-50:])
        await self.put_meta("config:draft", None)
        await self.db.flush()
        await invalidate(self.inst)
        await self.audit("publish", "website_config", row.id, {"version": len(versions), "notes": notes})
        await self.emit("website.published", {"version": len(versions)}, row.id)
        return await self.get()

    async def versions(self) -> list[SiteVersionOut]:
        self.require("view", "manage")
        return [
            SiteVersionOut(
                version=v["version"],
                published_at=v["published_at"],
                published_by=v.get("published_by") or None,
                notes=v.get("notes"),
            )
            for v in reversed(await self.meta("config:versions", []))
        ]

    async def rollback(self, version: int) -> SiteConfigOut:
        self.require("publish")
        found = next((v for v in await self.meta("config:versions", []) if v["version"] == version), None)
        if found is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Version not found")
        out = await self.publish(f"rollback to v{version}", found["config"])
        await self.emit("website.rolled_back", {"to": version})
        return out

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def public(self, preview: bool = False, base: str = "") -> PublicSiteOut:
        from app.models.platform import Institution
        from app.services.website.sections import build_section

        inst = await self.db.get(Institution, self.inst)
        if inst is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Website not found")
        row = await self._row()
        cfg = (await self.meta("config:draft") if preview else None) or self._published(row)
        if not cfg.get("is_enabled", True):
            raise APIError(404, ErrorCode.NOT_FOUND, "This website is not enabled")
        profile = (
            (
                await self.db.execute(
                    text(
                        "SELECT vision, mission, accreditations, head_title, head_name FROM institution_profile "
                        "WHERE institution_id = :i"
                    ),
                    {"i": self.inst},
                )
            )
            .mappings()
            .first()
        )
        sections: list[dict[str, Any]] = []
        for s in sorted(cfg.get("sections") or [], key=lambda x: x.get("sequence", 0)):
            if not s.get("is_visible", True):
                continue
            try:
                async with self.db.begin_nested():
                    data = await build_section(self, s, cfg, inst, dict(profile or {}))
            except Exception as exc:  # noqa: BLE001 - one module never breaks the site
                log.warning("site_section_failed", section=s.get("type"), error=str(exc)[:200])
                data = None
            if data is not None:
                sections.append({"type": s["type"], "key": s.get("key"), "title": s.get("title"), "data": data})
        primary = (
            await self.db.execute(
                text(
                    "SELECT hostname FROM institution_domains WHERE institution_id = :i AND is_primary "
                    "AND ssl_status = 'active' LIMIT 1"
                ),
                {"i": self.inst},
            )
        ).first()
        return PublicSiteOut(
            institution={
                "name": inst.name,
                "short_name": inst.short_name,
                "slug": inst.slug,
                "logo_url": inst.logo_url,
                "type": inst.institution_type,
                "accreditations": dict(profile or {}).get("accreditations") or [],
            },
            config={k: cfg.get(k) for k in ("theme", "hero", "seo", "contact", "social", "show_catalog", "show_apply")},
            sections=sections,
            canonical=f"https://{primary[0]}/" if primary else f"{base}/site/{inst.slug}/",
            preview=preview,
        )

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def ssr(self, path: str, preview: bool, base: str) -> tuple[str, str, int]:
        """→ (html, etag, max_age)."""
        ttl = int(await self.setting("cache_ttl_seconds") or 300)
        ver = await site_version(self.inst)
        key = f"site:{self.inst}:{ver}:{path}"
        if not preview:
            cached = await redis_client.get(key)
            if cached:
                body = str(cached)
                return body, etag_of(body), ttl
        from app.services.website.ssr import render_page

        site = await self.public(preview, base)
        body = await render_page(self, site, path, await self._analytics_snippet())
        if not preview and ttl > 0:
            await redis_client.set(key, body, ex=ttl)
        return body, etag_of(body), 0 if preview else ttl

    async def _analytics_snippet(self) -> str:
        provider = await self.setting("analytics_provider")
        site_id = await self.setting("analytics_site_id")
        if provider == "plausible" and site_id:
            return (
                f'<script defer data-domain="{escape(str(site_id))}" src="https://plausible.io/js/script.js"></script>'
            )
        if provider == "ga4" and site_id:  # loaded only after the Phase 43 cookie consent
            return f'<meta name="ga4-id" content="{escape(str(site_id))}">'
        return ""

    # ---- rule 4 ---------------------------------------------------------------------------------------------------
    async def hit(self, path: str, client_ip: str) -> None:
        day = date.today().isoformat()
        try:
            await redis_client.hincrby(f"site:pv:{self.inst}:{day}", path[:120], 1)  # type: ignore[misc]
            salt = hashlib.sha256(f"{settings.SECRET_KEY}:{day}".encode()).hexdigest()[:16]
            await redis_client.pfadd(
                f"site:uv:{self.inst}:{day}", hashlib.sha256(f"{salt}{client_ip}".encode()).hexdigest()
            )
            await redis_client.expire(f"site:pv:{self.inst}:{day}", 100 * 86400)
            await redis_client.expire(f"site:uv:{self.inst}:{day}", 100 * 86400)
        except Exception:  # noqa: BLE001 - analytics never break a page
            pass

    async def analytics(self, date_from: date | None, date_to: date | None) -> SiteAnalyticsOut:
        self.require("view", "manage")
        t = date_to or date.today()
        f = date_from or (t - timedelta(days=29))
        pv: dict[str, int] = {}
        uv: dict[str, int] = {}
        pages: dict[str, int] = {}
        d = f
        while d <= t:
            k = d.isoformat()
            h = await redis_client.hgetall(f"site:pv:{self.inst}:{k}")  # type: ignore[misc]
            pv[k] = sum(int(v) for v in (h or {}).values())
            for p, v in (h or {}).items():
                pages[p] = pages.get(p, 0) + int(v)
            uv[k] = int(await redis_client.pfcount(f"site:uv:{self.inst}:{k}"))
            d += timedelta(days=1)
        conv = {
            r[0]: int(r[1])
            for r in (
                await self.db.execute(
                    text(
                        "SELECT status, count(*) FROM website_enquiries WHERE institution_id = :i "
                        "AND created_at::date BETWEEN :f AND :t GROUP BY 1"
                    ),
                    {"i": self.inst, "f": f, "t": t},
                )
            ).all()
        }
        top = sorted(({"path": p, "views": v} for p, v in pages.items()), key=lambda x: -int(str(x["views"])))[:20]
        return SiteAnalyticsOut(pageviews_by_day=pv, top_pages=top, visitors_by_day=uv, enquiry_conversions=conv)
