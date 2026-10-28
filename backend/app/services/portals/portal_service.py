"""Portal shell — Prompts/39 §39.6 ``portal_service`` rules 1 / 4 and the branding repository of §39.5.

Business rules
1. ``config``: persona from role slugs (priority order, last wins); tabs / more from the registry
   (``app/core/portals.py``) with entries whose feature is off or permission missing removed and listed in
   ``features_missing``; persona feature off → 403 ``FEATURE_DISABLED`` (the client redirects to the next home);
   ``admin_switch`` when the user holds any admin-shell permission (``*:view_all`` / ``*:manage`` outside the
   portal modules) and ``portals.faculty_show_admin_switch`` is on. Users without a persona get ``persona=null``.
2. Branding: ``portals.branding`` setting over ``institutions`` (name / short name / logo) — cached 10 minutes in
   ``portal_brand:{inst}`` and dropped on ``institution.updated`` / ``settings.changed``.
3. Wards: consented wards only (``portals.parent_require_consent``); the switch persists in Redis per user (30 days)
   and a foreign student id is 404.
4. ``update_me``: locale (must be one of ``i18n.web_locales`` while ``i18n.web`` is on, else ``en``), timezone,
   theme (``users.preferences['portal']``); audited ``users:update_self``.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.core.portals import PORTALS
from app.db.session import redis_client
from app.enums.portals import PERSONA_FEATURE, PERSONA_HOME
from app.schemas.portals import (
    BrandingOut,
    MeUpdateIn,
    MeUpdateOut,
    PortalConfigOut,
    PortalNavEntry,
    TermChip,
    WardOut,
)
from app.services.portals.common import WARD_KEY, PortalBase, persona_of, personas_of

BRAND_KEY = "portal_brand:{inst}"
BRAND_TTL = 600
PORTAL_MODULES = frozenset({"dashboard", "notifications", "communication", "students", "attendance", "marks", "lms"})


async def branding_for(db: Any, institution_id: uuid.UUID) -> BrandingOut:
    """Rule 2 — also used by the public manifest (platform session, no principal)."""
    cached = await redis_client.get(BRAND_KEY.format(inst=institution_id))
    if cached:
        return BrandingOut.model_validate_json(cached)
    inst = (
        await db.execute(
            text("SELECT name, short_name, logo_url FROM institutions WHERE id = :i"), {"i": institution_id}
        )
    ).first()
    row = (
        await db.execute(
            text(
                "SELECT value FROM institution_settings WHERE institution_id = :i AND category = 'portals' "
                "AND key = 'branding' AND college_id IS NULL LIMIT 1"
            ),
            {"i": institution_id},
        )
    ).first()
    b: dict[str, Any] = dict(row[0]) if row and isinstance(row[0], dict) else {}
    name = b.get("app_name") or (inst.name if inst else "SeptronUniverse")
    short = b.get("short_name") or (inst.short_name if inst and inst.short_name else name[:12])
    logo = b.get("icon_url") or (inst.logo_url if inst else None)
    icons = [
        {"src": f"/api/v1/public/pwa-icons/{institution_id}/{s}.png", "sizes": f"{s}x{s}", "type": "image/png"}
        for s in (192, 512)
    ]
    icons.append(
        {
            "src": f"/api/v1/public/pwa-icons/{institution_id}/512.png",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        }
    )
    out = BrandingOut(
        app_name=name,
        short_name=short,
        theme_color=b.get("theme_color") or "#4f46e5",
        background_color=b.get("background_color") or "#f8fafc",
        logo_url=logo,
        icons=icons if logo else [{"src": "/icons/icon.svg", "sizes": "any", "type": "image/svg+xml"}],
        splash=b.get("splash_url"),
    )
    await redis_client.set(BRAND_KEY.format(inst=institution_id), out.model_dump_json(), ex=BRAND_TTL)
    return out


async def drop_branding(institution_id: Any) -> None:
    await redis_client.delete(BRAND_KEY.format(inst=institution_id))


class PortalService(PortalBase):
    # ---- rule 1 -------------------------------------------------------------------------------------------------
    def _admin_grants(self) -> bool:
        for perm in self.principal.permissions:
            module, _, action = perm.partition(":")
            if action in ("view_all", "manage") and module not in PORTAL_MODULES:
                return True
        return False

    async def config(self) -> PortalConfigOut:
        persona = persona_of(self.principal)
        branding = await branding_for(self.db, self.inst)
        language = (self.principal.user.locale or "en").split("-")[0]
        locales = ["en"]
        if self.principal.has_feature("i18n.web"):
            locales = list(await self.setting("i18n", "web_locales") or ["en"])
        if language not in locales:
            language = "en"
        base = PortalConfigOut(
            persona=persona,
            personas=personas_of(self.principal),
            branding=branding,
            language=language,
            locales=locales,
            tours_enabled=self.principal.has_feature("platform.guided_tours"),
            push_enabled=self.principal.has_feature("portals.pwa_push") and self.principal.has_feature("comms.push"),
        )
        if persona is None:
            return base
        feature = PERSONA_FEATURE[persona]
        if not self.principal.has_feature(feature):
            raise APIError(
                403,
                ErrorCode.FEATURE_DISABLED,
                f"The {persona} portal is not enabled",
                {"feature": feature, "redirect": self._fallback_home(persona)},
            )
        d = PORTALS[persona]
        missing: list[str] = []

        def keep(entries: Any) -> list[PortalNavEntry]:
            out = []
            for e in entries:
                if e.feature and not self.principal.has_feature(e.feature):
                    missing.append(e.feature)
                    continue
                if e.permission and not self.principal.has(*e.permission.split(":", 1)):
                    continue
                out.append(PortalNavEntry(**e.as_dict()))
            return out

        base.tabs, base.more = keep(d.tabs), keep(d.more)
        widgets = list(d.home_widgets)
        if persona == "student":
            widgets = list(await self.setting("portals", "student_home_widgets") or widgets)
        base.home_widgets, base.unified = widgets, list(d.unified)
        base.home = PERSONA_HOME[persona]
        base.features_missing = sorted(set(missing))
        base.admin_switch = (
            persona == "faculty"
            and self._admin_grants()
            and bool(await self.setting("portals", "faculty_show_admin_switch"))
        )
        if persona in ("student", "faculty"):
            base.term = await self._term()
        if persona == "parent":
            base.ward_id = await self.active_ward()
        return base

    def _fallback_home(self, persona: str) -> str:
        for p in reversed(personas_of(self.principal)):
            if p != persona and self.principal.has_feature(PERSONA_FEATURE[p]):
                return PERSONA_HOME[p]
        return "/access-denied"

    async def _term(self) -> TermChip | None:
        rows = await self.rows(
            "SELECT id, name FROM academic_terms WHERE institution_id = :i AND is_current ORDER BY start_date DESC LIMIT 1"
        )
        return TermChip(id=rows[0]["id"], name=rows[0]["name"]) if rows else None

    # ---- rule 3 -------------------------------------------------------------------------------------------------
    async def ward_list(self) -> list[WardOut]:
        active = await self.active_ward()
        return [WardOut(**w, active=w["student_id"] == active) for w in await self.wards()]

    async def switch_ward(self, student_id: uuid.UUID) -> list[WardOut]:
        if student_id not in await self.ward_ids():
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        await redis_client.set(WARD_KEY.format(user=self.principal.id), str(student_id), ex=30 * 86400)
        return await self.ward_list()

    # ---- rule 4 -------------------------------------------------------------------------------------------------
    async def update_me(self, body: MeUpdateIn) -> MeUpdateOut:
        user = self.principal.user
        old = {"locale": user.locale, "timezone": user.timezone}
        if body.locale is not None:
            allowed = ["en"]
            if self.principal.has_feature("i18n.web"):
                allowed = list(await self.setting("i18n", "web_locales") or ["en"])
            if body.locale.split("-")[0] not in allowed:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"Language {body.locale!r} is not offered", {"field": "locale"}
                )
            user.locale = body.locale
        if body.timezone is not None:
            user.timezone = body.timezone
        prefs = dict(user.preferences or {})
        if body.theme is not None:
            prefs["portal"] = {**(prefs.get("portal") or {}), "theme": body.theme}
            user.preferences = prefs
        await self.db.execute(
            text("UPDATE users SET locale = :l, timezone = :t, preferences = CAST(:p AS jsonb) WHERE id = :u"),
            {"l": user.locale, "t": user.timezone, "p": json.dumps(prefs), "u": user.id},
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="update_self",
            record_type="user",
            record_id=user.id,
            old=old,
            new=body.model_dump(exclude_none=True),
            request=self.request,
        )
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="preferences.updated",
            payload={"user_id": str(user.id), "fields": sorted(body.model_dump(exclude_none=True))},
            aggregate_type="user",
            aggregate_id=user.id,
            actor_user_id=user.id,
        )
        return MeUpdateOut(locale=user.locale, timezone=user.timezone, theme=(prefs.get("portal") or {}).get("theme"))
