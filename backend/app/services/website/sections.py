"""Section data builders for the public site — Prompts/40 §40.6 ``site_service`` rule 2.

Each builder returns JSON-able data or ``None`` (section hidden). Only published rows and explicit, non-personal
columns are selected; module data comes from the owning phase's public method where one exists (Phase 08 cycles,
Phase 33 policies, Phase 34 colleges, Phase 35 counters) so the website never widens what those modules publish.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text

from app.core.features import is_enabled

Builder = Callable[[Any, dict[str, Any], dict[str, Any], Any, dict[str, Any]], Awaitable[Any]]
BUILDERS: dict[str, Builder] = {}


def builder(*types: str) -> Callable[[Builder], Builder]:
    def deco(fn: Builder) -> Builder:
        for t in types:
            BUILDERS[t] = fn
        return fn

    return deco


async def build_section(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    fn = BUILDERS.get(s.get("type", ""))
    return await fn(svc, s, cfg, inst, profile) if fn else None


async def _rows(svc: Any, sql: str, **p: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in (await svc.db.execute(text(sql), {"i": svc.inst, **p})).mappings().all()]


@builder("hero")
async def _hero(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return cfg.get("hero") or {"title": inst.name}


@builder("about")
async def _about(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    items = await _rows(
        svc,
        "SELECT slug, title, body FROM website_content_items WHERE institution_id = :i AND section = 'about' "
        "AND is_published ORDER BY sequence LIMIT 5",
    )
    return {
        "vision": profile.get("vision"),
        "mission": profile.get("mission"),
        "pages": items,
        "text": profile.get("vision"),
    }


@builder("leadership")
async def _leadership(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    if not profile.get("head_name"):
        return None
    return [{"name": profile.get("head_name"), "title": profile.get("head_title") or "Head of the institution"}]


@builder("programmes")
async def _programmes(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    if not cfg.get("show_catalog", True):
        return None
    from app.services.website.catalogue_service import CatalogueService

    return (await CatalogueService(svc.db, None, svc.request, svc.inst).list_programmes(None, None, None, None))[:12]


@builder("admissions_cta")
async def _admissions(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    if not cfg.get("show_apply", True) or not await is_enabled(svc.inst, "admissions.cycles"):
        return None
    from app.services.admissions.cycle_service import CycleService

    cycles = await CycleService(svc.db, None, institution_id=svc.inst).public_cycles()
    return [{**c, "apply_url": f"/apply/{c.get('slug')}"} for c in cycles][:6]


@builder("notices")
async def _notices(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return await _rows(
        svc,
        "SELECT title, slug, category, publish_at FROM website_notices WHERE institution_id = :i AND is_published "
        "AND (publish_at IS NULL OR publish_at <= NOW()) AND (expires_at IS NULL OR expires_at > NOW()) "
        "ORDER BY publish_at DESC NULLS LAST, created_at DESC LIMIT 10",
    )


@builder("events")
async def _events(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return await _rows(
        svc,
        "SELECT title, slug, starts_at, ends_at, image_url FROM website_events WHERE institution_id = :i AND is_published "
        "AND (ends_at IS NULL OR ends_at >= NOW() - INTERVAL '1 day') ORDER BY starts_at NULLS LAST LIMIT 8",
    )


@builder("gallery")
async def _gallery(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return await _rows(
        svc,
        "SELECT a.id, a.title, a.cover_url, (SELECT count(*) FROM gallery_images g WHERE g.album_id = a.id) AS images "
        "FROM gallery_albums a WHERE a.institution_id = :i AND a.is_published ORDER BY a.sequence LIMIT 6",
    )


@builder("stats")
async def _stats(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    if not await is_enabled(svc.inst, "analytics.core"):
        return None
    from app.services.analytics.kpi_service import KpiService

    return await KpiService(svc.db, None, svc.request, svc.inst).public_counters()


@builder("accreditation")
async def _accreditation(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return profile.get("accreditations") or None


@builder("placements")
async def _placements(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    rows = await _rows(
        svc,
        "SELECT count(*) AS offers, count(DISTINCT application_id) AS students_placed, "
        "max(ctc_paise) AS highest_ctc_paise, percentile_cont(0.5) WITHIN GROUP (ORDER BY ctc_paise) AS median_ctc_paise "
        "FROM placement_offers WHERE institution_id = :i AND status IN ('accepted', 'joined')",
    )
    return rows[0] if rows and rows[0]["offers"] else None


@builder("research")
async def _research(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    rows = await _rows(
        svc,
        "SELECT (SELECT count(*) FROM publications WHERE institution_id = :i) AS publications, "
        "(SELECT count(*) FROM patents WHERE institution_id = :i) AS patents, "
        "(SELECT count(*) FROM research_projects WHERE institution_id = :i) AS projects",
    )
    return rows[0] if rows else None


@builder("departments")
async def _departments(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return await _rows(
        svc,
        "SELECT code, name, description FROM departments WHERE institution_id = :i AND deleted_at IS NULL "
        "AND is_active ORDER BY name",
    )


@builder("colleges")
async def _colleges(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return await _rows(
        svc,
        "SELECT code, name FROM colleges WHERE institution_id = :i AND deleted_at IS NULL AND is_active ORDER BY name",
    )


@builder("faculty_directory")
async def _faculty(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    from app.services.website.public_service import faculty_directory

    return (await faculty_directory(svc))[:24]


@builder("disclosures")
async def _disclosures(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    from app.services.website.public_service import disclosures

    return await disclosures(svc)


@builder("policies")
async def _policies(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    if not await is_enabled(svc.inst, "governance.policies"):
        return None
    from app.services.governance.policy_service import PolicyService

    return [
        {"title": p.title, "code": getattr(p, "code", None), "version": getattr(p, "version", None)}
        for p in await PolicyService(svc.db, None, svc.request, svc.inst).public()
    ]


@builder("committees")
async def _committees(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return await _rows(
        svc,
        "SELECT name, committee_type FROM committees WHERE institution_id = :i AND is_active ORDER BY name LIMIT 40",
    )


@builder("contact")
async def _contact(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return {**(cfg.get("contact") or {}), "enquiry": await is_enabled(svc.inst, "website.enquiry")}


@builder("footer")
async def _footer(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    return {"social": cfg.get("social") or {}, "name": inst.name}


@builder("custom_html")
async def _custom(svc: Any, s: dict[str, Any], cfg: dict[str, Any], inst: Any, profile: dict[str, Any]) -> Any:
    from app.services.website.common import sanitise

    return {"html": sanitise(str((s.get("config") or {}).get("html") or ""))}
