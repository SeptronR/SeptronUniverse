"""Public platform configuration, mobile remote config and readiness — Prompts/01 §01.8.

Business rules
1. ``GET /public/config`` is unauthenticated: it exposes only what a login page or app bootstrap needs — the
   registered regulatory packs (categories, quotas, id formats, locales), the theme/table-style names, the captcha
   provider + site key, minimum app versions and — when the request resolves a tenant (``X-Institution-Slug`` /
   sub-domain / ``?institution=``) — the institution summary and its active colleges. Nothing tenant-private.
2. ``/mobile/config`` (public) merges ``platform_settings['mobile']`` (seeded by Phase 42; defaults here) with the
   caller's ``platform``/``app_version``: ``force_update`` when the version is below ``force_update_below``,
   ``update_available`` when below ``min_versions``; the maintenance banner and read-only flag come from the read-only
   service so the app can disable writes before its first authenticated call.
3. ``readiness()`` backs ``GET /ready``: DB, Redis, storage directory writable, Alembic revision at head, outbox lag
   (age of the oldest pending event) — ``degraded`` (503) when DB/Redis fail or the DB is not at head.
"""

import time
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.packs import get_pack, pack_codes
from app.repositories.platform_repository import PlatformConfigRepository
from app.schemas.platform import (
    CollegeSummary,
    InstitutionSummary,
    MobileConfigRequest,
    MobileConfigResponse,
    PublicConfig,
)
from app.services.read_only_service import ReadOnlyService

API_VERSION = "0.1.0"
THEMES = ["indigo", "ocean", "grove", "sunset", "plum"]
TABLE_STYLES = ["default", "striped", "bordered", "compact", "card", "minimal"]
MOBILE_DEFAULTS: dict[str, Any] = {
    "min_versions": {"android": "1.0.0", "ios": "1.0.0"},
    "force_update_below": {"android": "0.0.0", "ios": "0.0.0"},
    "store_urls": {
        "android": "https://play.google.com/store/apps/details?id=com.septronr.universe",
        "ios": "https://apps.apple.com/app/septron-universe/id0000000000",
    },
    "maintenance_banner": None,
    "feature_hints": {},
    "cache_ttl": 300,
}


def version_tuple(v: str | None) -> tuple[int, ...]:
    if not v:
        return (0,)
    parts: list[int] = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts) or (0,)


class PlatformService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PlatformConfigRepository(db)

    async def public_config(self, institution_slug: str | None) -> PublicConfig:
        """Rule 1."""
        institution = None
        colleges: list[CollegeSummary] = []
        default_pack = "IN"
        if institution_slug:
            row = await self.repo.institution_by_slug(institution_slug)
            if row is not None:
                institution = InstitutionSummary.model_validate(row)
                default_pack = row.regulatory_pack or default_pack
                colleges = [CollegeSummary.model_validate(c) for c in await self.repo.colleges_of(row.id)]
        mobile = await self._mobile_settings()
        return PublicConfig(
            environment=settings.APP_ENV,
            api_version=API_VERSION,
            packs={code: get_pack(code).public_config() for code in pack_codes()},
            default_pack=default_pack if default_pack in pack_codes() else "GENERIC",
            themes=THEMES,
            table_styles=TABLE_STYLES,
            captcha={"provider": settings.CAPTCHA_PROVIDER, "site_key": settings.CAPTCHA_SITE_KEY},
            min_app_versions=dict(mobile["min_versions"]),
            features_public=["platform.help_center", "platform.in_app_feedback", "search.global"],
            institution=institution,
            colleges=colleges,
        )

    async def mobile_config(self, body: MobileConfigRequest) -> MobileConfigResponse:
        """Rule 2."""
        mobile = await self._mobile_settings()
        platform = body.platform
        current = version_tuple(body.app_version)
        minimum = version_tuple(mobile["min_versions"].get(platform))
        force_below = version_tuple(mobile["force_update_below"].get(platform))
        institution_id: uuid.UUID | None = None
        if body.institution_slug:
            inst = await self.repo.institution_by_slug(body.institution_slug)
            institution_id = inst.id if inst else None
        ro = await ReadOnlyService(self.db).state(institution_id)
        banner = mobile.get("maintenance_banner") or (ro.reason if (ro.platform or ro.institution) else None)
        return MobileConfigResponse(
            min_versions=dict(mobile["min_versions"]),
            force_update_below=dict(mobile["force_update_below"]),
            force_update=bool(body.app_version) and current < force_below,
            update_available=bool(body.app_version) and current < minimum,
            store_urls=dict(mobile["store_urls"]),
            maintenance_banner=banner,
            read_only=bool(ro.platform or ro.institution),
            feature_hints=dict(mobile.get("feature_hints") or {}),
            cache_ttl_seconds=int(mobile.get("cache_ttl") or 300),
        )

    async def _mobile_settings(self) -> dict[str, Any]:
        stored = await self.repo.platform_setting("mobile")
        merged = {**MOBILE_DEFAULTS}
        if isinstance(stored, dict):
            for k, v in stored.items():
                if isinstance(v, dict) and isinstance(merged.get(k), dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
        # Phase 38: the typed platform key ``mobile.min_versions`` ({android, ios, force_update}) edited on the
        # super-admin settings page wins; force_update raises the hard floor to the same versions
        typed = await self.repo.platform_setting("mobile.min_versions")
        if isinstance(typed, dict):
            versions = {p: str(typed[p]) for p in ("android", "ios") if typed.get(p)}
            merged["min_versions"] = {**merged["min_versions"], **versions}
            if typed.get("force_update"):
                merged["force_update_below"] = {**merged["force_update_below"], **versions}
        return merged

    async def readiness(self) -> tuple[bool, dict[str, Any]]:
        """Rule 3 — every check is reported; ``ok`` is False when a hard dependency fails."""
        checks: dict[str, Any] = {}
        ok = True
        # database + migration head
        try:
            t0 = time.perf_counter()
            await self.db.execute(text("SELECT 1"))
            checks["database"] = {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
            current = (await self.db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
            head = _alembic_head()
            at_head = head is None or current == head
            checks["migrations"] = {"ok": at_head, "current": current, "head": head}
            ok = ok and at_head
        except Exception as exc:  # noqa: BLE001
            checks["database"] = {"ok": False, "error": str(exc)[:200]}
            ok = False
        # redis (required)
        from app.db.session import redis_client

        try:
            t0 = time.perf_counter()
            await cast(Awaitable[bool], redis_client.ping())
            checks["redis"] = {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 1)}
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = {"ok": False, "error": str(exc)[:200]}
            ok = False
        # storage
        checks["storage"] = await _storage_check()
        # outbox lag
        try:
            oldest = (
                await self.db.execute(text("SELECT MIN(created_at) FROM domain_events WHERE status = 'pending'"))
            ).scalar_one_or_none()
            lag = int((datetime.now(UTC) - oldest).total_seconds()) if oldest else 0
            checks["outbox"] = {"ok": lag < 300, "lag_seconds": lag}
        except Exception as exc:  # noqa: BLE001
            checks["outbox"] = {"ok": False, "error": str(exc)[:200]}
        return ok, checks


def _alembic_head() -> str | None:
    """Head revision from the script directory (no DB access); None when Alembic is not configured."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        heads = ScriptDirectory.from_config(cfg).get_heads()
        return heads[0] if len(heads) == 1 else ",".join(sorted(heads))
    except Exception:  # noqa: BLE001
        return None


async def _storage_check() -> dict[str, Any]:
    import os
    import tempfile

    if settings.STORAGE_BACKEND == "s3":
        return {"ok": bool(settings.S3_BUCKET), "backend": "s3", "bucket": settings.S3_BUCKET}
    try:
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=settings.UPLOAD_DIR, prefix=".ready-", delete=True) as f:
            f.write(b"ok")
        return {"ok": True, "backend": "local", "path": settings.UPLOAD_DIR}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "backend": "local", "error": str(exc)[:200]}
