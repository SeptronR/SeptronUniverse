"""Public website API, edge integration and the server-rendered site — Prompts/40 §40.8.

``router`` (``/api/v1``; every route in ``PUBLIC_ROUTES``): site data / notices / RSS / events / gallery / pages /
disclosures / faculty / colleges / departments, the enquiry form (captcha, honeypot, per-IP limit), the catalogue
(``website.course_catalog``), admissions entry, affiliated colleges / college verification, the gated result lookup,
marketing data / pricing, and the edge endpoints ``/internal/domains`` (``X-Edge-Token``). ``site_router`` is mounted
at the root by ``main.py``: ``/site/{slug}/…`` SSR pages (ETag / 304, page cache, 301 to an active primary custom
domain), ``/sitemap.xml`` and ``/robots.txt`` per host. Tenant resolution: ``?slug=`` → verified custom host → header.
"""

import hmac
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.rate_limit import check_rate, verify_captcha
from app.db.session import get_db, get_platform_db
from app.schemas.common import Envelope
from app.schemas.website import (
    EdgeDomainOut,
    MarketingOut,
    PublicAdmissionsOut,
    PublicEnquiryIn,
    PublicEnquiryOut,
    PublicResultLookupIn,
    PublicSiteOut,
    SslStatusIn,
)
from app.services.website import marketing_service, public_service, seo
from app.services.website.catalogue_service import CatalogueService
from app.services.website.common import WebsiteBase, resolve_public_tenant
from app.services.website.enquiry_service import EnquiryService
from app.services.website.site_service import SiteService, preview_valid
from app.services.website.ssr import error_page
from app.utils.response import ok

router = APIRouter(tags=["website-public"])
site_router = APIRouter(tags=["website-public"])


async def _tenant(request: Request, db: AsyncSession, slug: str | None, feature: str = "website.core") -> WebsiteBase:
    iid, _ = await resolve_public_tenant(db, request, slug)
    if not await is_enabled(iid, feature):
        raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{feature}' is not enabled", {"feature": feature})
    return WebsiteBase(db, None, request, iid)


def _root(request: Request, slug: str) -> str:
    host = request.headers.get("host", "")
    return f"{request.url.scheme}://{host}/site/{slug}" if host else f"/site/{slug}"


# ---- site data --------------------------------------------------------------------------------------------------------
@router.get("/public/site", summary="Published site (sections + data)", response_model=Envelope[PublicSiteOut])
async def public_site(
    request: Request,
    slug: str | None = Query(None, max_length=60),
    preview: str | None = Query(None, max_length=80),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    return ok(await SiteService(db, None, request, b.inst).public(preview_valid(b.inst, preview)))


@router.get(
    "/public/site/notices", summary="Live notices (category filter)", response_model=Envelope[list[dict[str, Any]]]
)
async def public_notices(
    request: Request,
    slug: str | None = Query(None, max_length=60),
    category: str | None = Query(None, max_length=40),
    page: int = Query(1, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    rows = await db.execute(
        text(
            "SELECT title, slug, category, publish_at, expires_at, attachments FROM website_notices WHERE institution_id = :i "
            "AND is_published AND (publish_at IS NULL OR publish_at <= NOW()) AND (expires_at IS NULL OR expires_at > NOW()) "
            + ("AND category = :c " if category else "")
            + "ORDER BY publish_at DESC NULLS LAST LIMIT 20 OFFSET :o"
        ),
        {"i": b.inst, "c": category, "o": (page - 1) * 20},
    )
    return ok([dict(r) for r in rows.mappings().all()])


@router.get("/public/site/notices.rss", summary="Notices RSS feed", response_model=None)
async def public_rss(
    request: Request,
    slug: str | None = Query(None, max_length=60),
    category: str | None = Query(None, max_length=40),
    db: AsyncSession = Depends(get_db),
) -> Response:
    b = await _tenant(request, db, slug)
    name = (await db.execute(text("SELECT name, slug FROM institutions WHERE id = :i"), {"i": b.inst})).first()
    body = await seo.rss(b, _root(request, str(name[1]) if name else ""), category, str(name[0]) if name else "")
    return Response(body, media_type="application/rss+xml")


@router.get(
    "/public/site/notices/{notice_slug}",
    summary="One notice (410 once expired)",
    response_model=Envelope[dict[str, Any]],
)
async def public_notice(
    notice_slug: str,
    request: Request,
    slug: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    r = (
        (
            await db.execute(
                text(
                    "SELECT title, slug, body, category, publish_at, expires_at, attachments, NOW() AS now FROM website_notices "
                    "WHERE institution_id = :i AND slug = :s AND is_published AND (publish_at IS NULL OR publish_at <= NOW())"
                ),
                {"i": b.inst, "s": notice_slug[:120]},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Notice not found")
    if r["expires_at"] and r["expires_at"] <= r["now"]:
        raise APIError(410, ErrorCode.GONE, "This notice has expired", {"archive": "notices"})
    return ok({k: v for k, v in dict(r).items() if k != "now"})


@router.get("/public/site/events", summary="Published events", response_model=Envelope[list[dict[str, Any]]])
async def public_events(
    request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    rows = await db.execute(
        text(
            "SELECT title, slug, description, starts_at, ends_at, image_url, event_id FROM website_events WHERE institution_id = :i AND is_published ORDER BY starts_at DESC NULLS LAST LIMIT 100"
        ),
        {"i": b.inst},
    )
    return ok(
        [
            {
                **dict(r),
                "registration_url": f"/api/v1/events/public/{r['event_id']}/register" if r["event_id"] else None,
            }
            for r in rows.mappings().all()
        ]
    )


@router.get("/public/site/gallery", summary="Published albums", response_model=Envelope[list[dict[str, Any]]])
async def public_gallery(
    request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    rows = await db.execute(
        text(
            "SELECT id, title, description, cover_url FROM gallery_albums WHERE institution_id = :i AND is_published ORDER BY sequence"
        ),
        {"i": b.inst},
    )
    return ok([dict(r) for r in rows.mappings().all()])


@router.get("/public/site/gallery/{album}", summary="Album images", response_model=Envelope[dict[str, Any]])
async def public_album(
    album: uuid.UUID,
    request: Request,
    slug: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    a = (
        (
            await db.execute(
                text(
                    "SELECT id, title, description FROM gallery_albums WHERE institution_id = :i AND id = :a AND is_published"
                ),
                {"i": b.inst, "a": album},
            )
        )
        .mappings()
        .first()
    )
    if a is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Album not found")
    imgs = await db.execute(
        text("SELECT image_url, caption FROM gallery_images WHERE album_id = :a ORDER BY sequence"), {"a": album}
    )
    return ok({**dict(a), "images": [dict(r) for r in imgs.mappings().all()]})


@router.get(
    "/public/site/pages/{section}/{page_slug}",
    summary="A published content page",
    response_model=Envelope[dict[str, Any]],
)
async def public_page(
    section: str,
    page_slug: str,
    request: Request,
    slug: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    r = (
        (
            await db.execute(
                text(
                    "SELECT section, slug, title, body, media FROM website_content_items WHERE institution_id = :i AND section = :s AND slug = :g AND is_published"
                ),
                {"i": b.inst, "s": section[:60], "g": page_slug[:120]},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Page not found")
    return ok(dict(r))


@router.get(
    "/public/site/disclosures", summary="Published mandatory disclosures", response_model=Envelope[list[dict[str, Any]]]
)
async def public_disclosures(
    request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await public_service.disclosures(await _tenant(request, db, slug)))


@router.get(
    "/public/site/faculty",
    summary="Faculty directory (allow-listed fields)",
    response_model=Envelope[list[dict[str, Any]]],
)
async def public_faculty(
    request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await public_service.faculty_directory(await _tenant(request, db, slug)))


@router.get(
    "/public/site/colleges", summary="Colleges (university sites)", response_model=Envelope[list[dict[str, Any]]]
)
async def public_colleges(
    request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    rows = await db.execute(
        text(
            "SELECT code, name FROM colleges WHERE institution_id = :i AND deleted_at IS NULL AND is_active ORDER BY name"
        ),
        {"i": b.inst},
    )
    return ok([dict(r) for r in rows.mappings().all()])


@router.get("/public/site/departments/{code}", summary="Department sub-site", response_model=Envelope[dict[str, Any]])
async def public_department(
    code: str, request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    d = (
        (
            await db.execute(
                text(
                    "SELECT code, name, description FROM departments WHERE institution_id = :i AND code = :c AND deleted_at IS NULL"
                ),
                {"i": b.inst, "c": code.upper()[:20]},
            )
        )
        .mappings()
        .first()
    )
    if d is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Department not found")
    pages = await db.execute(
        text(
            "SELECT slug, title, body FROM website_content_items WHERE institution_id = :i AND section = :s AND is_published ORDER BY sequence"
        ),
        {"i": b.inst, "s": f"department:{d['code']}"},
    )
    return ok({**dict(d), "pages": [dict(r) for r in pages.mappings().all()]})


@router.post(
    "/public/site/enquiries",
    status_code=201,
    summary="Website enquiry (captcha, honeypot, rate-limited)",
    response_model=Envelope[PublicEnquiryOut],
)
async def public_enquiry(
    body: PublicEnquiryIn,
    request: Request,
    slug: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    b = await _tenant(request, db, slug, "website.enquiry")
    return ok(
        await EnquiryService(db, None, request, b.inst).submit(body, request),
        message="Thank you — we will get back to you",
    )


# ---- catalogue / admissions / verification -----------------------------------------------------------------------------
@router.get("/public/catalogue", summary="Public programme catalogue", response_model=Envelope[list[dict[str, Any]]])
async def public_catalogue(
    request: Request,
    slug: str | None = Query(None, max_length=60),
    level: str | None = Query(None, max_length=20),
    mode: str | None = Query(None, max_length=20),
    department: str | None = Query(None, max_length=20),
    q: str | None = Query(None, max_length=80),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    b = await _tenant(request, db, slug, "website.course_catalog")
    return ok(await CatalogueService(db, None, request, b.inst).list_programmes(level, mode, department, q))


@router.get("/public/catalogue/programmes/{code}", summary="Programme page", response_model=Envelope[dict[str, Any]])
async def public_programme(
    code: str, request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    b = await _tenant(request, db, slug, "website.course_catalog")
    return ok(await CatalogueService(db, None, request, b.inst).programme(code[:30]))


@router.get("/public/catalogue/courses/{code}", summary="Course page", response_model=Envelope[dict[str, Any]])
async def public_course(
    code: str, request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    b = await _tenant(request, db, slug, "website.course_catalog")
    return ok(await CatalogueService(db, None, request, b.inst).course(code[:30]))


@router.get(
    "/public/site/admissions",
    summary="Admission cycles (open / upcoming / closed)",
    response_model=Envelope[PublicAdmissionsOut],
)
async def public_admissions(
    request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await public_service.admissions(await _tenant(request, db, slug)))


@router.get(
    "/public/site/affiliated-colleges",
    summary="Affiliated colleges with approved programmes",
    response_model=Envelope[list[dict[str, Any]]],
)
async def public_affiliated(
    request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await public_service.affiliated_colleges(await _tenant(request, db, slug)))


@router.get(
    "/public/site/verify/college/{code}",
    summary="Affiliated-college programme verification",
    response_model=Envelope[list[dict[str, Any]]],
)
async def public_verify_college(
    code: str, request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await public_service.affiliated_colleges(await _tenant(request, db, slug), code[:20]))


@router.post(
    "/public/site/results/lookup",
    summary="Result lookup (settings-gated; captcha; 10 / 10 min per IP)",
    response_model=Envelope[dict[str, Any]],
)
async def public_result_lookup(
    body: PublicResultLookupIn,
    request: Request,
    slug: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    b = await _tenant(request, db, slug)
    ip = request.client.host if request.client else "unknown"
    await check_rate(f"site_results:{b.inst}", ip, 10, 600)
    await verify_captcha(body.captcha_token, ip)
    from app.services.settings_service import SettingsService

    sett = SettingsService(db)
    if (
        not (
            await sett.value(b.inst, "website", "results_public_lookup")
            and await sett.value(b.inst, "exams", "result_public_lookup")
        )
        or body.dob is None
    ):
        raise APIError(404, ErrorCode.NOT_FOUND, "No published result for these details")
    from app.services.results.query_service import public_lookup

    out = await public_lookup(db, b.inst, body.registration_number, body.dob)
    data = out.model_dump(mode="json")
    if not await sett.value(b.inst, "website", "results_public_show_marks"):
        data.pop("courses", None)
        data.pop("marks", None)
    from app.core.audit import log_audit

    await log_audit(
        db,
        principal=None,
        module="results",
        action="public_lookup",
        record_type="student_term_result",
        record_id=None,
        new={"reg": body.registration_number[-4:]},
        request=request,
    )
    return ok({"result": data})


# ---- marketing (platform host) -------------------------------------------------------------------------------------------
@router.get("/public/marketing", summary="Marketing site content (published)", response_model=Envelope[MarketingOut])
async def public_marketing(db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await marketing_service.public(db))


@router.get("/public/pricing", summary="Active plans with public prices", response_model=Envelope[list[dict[str, Any]]])
async def public_pricing(db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await marketing_service.pricing(db))


# ---- edge (Phase 44 Traefik provider / ACME callback) ---------------------------------------------------------------------
def _edge(token: str | None) -> None:
    if not settings.EDGE_TOKEN or not token or not hmac.compare_digest(token, settings.EDGE_TOKEN):
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Edge token required")


@router.get(
    "/internal/domains",
    summary="Verified domains for the edge (X-Edge-Token)",
    response_model=Envelope[list[EdgeDomainOut]],
)
async def internal_domains(
    x_edge_token: str | None = Header(None), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    from app.services.website.domain_service import edge_list

    _edge(x_edge_token)
    return ok(await edge_list(db))


@router.post(
    "/internal/domains/{id}/ssl-status",
    summary="Edge certificate status callback (X-Edge-Token)",
    response_model=Envelope[dict[str, Any]],
)
async def internal_ssl(
    id: uuid.UUID,
    body: SslStatusIn,
    x_edge_token: str | None = Header(None),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    from app.services.website.domain_service import edge_ssl_status

    _edge(x_edge_token)
    return ok(await edge_ssl_status(db, id, body.status, body.reason))


# ---- server-rendered site (root) ------------------------------------------------------------------------------------------
@site_router.get("/site/{slug}", include_in_schema=False)
@site_router.get("/site/{slug}/{path:path}", include_in_schema=False)
async def ssr_site(
    slug: str,
    request: Request,
    path: str = "",
    preview: str | None = Query(None, max_length=80),
    db: AsyncSession = Depends(get_db),
) -> Response:
    base = f"/site/{slug}/"
    try:
        b = await _tenant(request, db, slug)
    except APIError as exc:
        status = 404 if exc.status_code == 404 else 503
        return HTMLResponse(
            error_page(status, "This website is not enabled." if exc.status_code == 403 else exc.message, "/"),
            status_code=status,
        )
    svc = SiteService(db, None, request, b.inst)
    is_preview = preview_valid(b.inst, preview)
    if not is_preview:
        primary = (
            await db.execute(
                text(
                    "SELECT hostname FROM institution_domains WHERE institution_id = :i AND is_primary AND ssl_status = 'active'"
                ),
                {"i": b.inst},
            )
        ).first()
        host = request.headers.get("host", "").split(":")[0]
        if primary and host != primary[0] and not request.headers.get("x-site-host"):
            return RedirectResponse(f"https://{primary[0]}/{path}", status_code=301)
    try:
        html, etag, max_age = await svc.ssr(path, is_preview, "")
    except APIError as exc:
        return HTMLResponse(
            error_page(exc.status_code, exc.message, base),
            status_code=exc.status_code if exc.status_code in (404, 410) else 500,
        )
    await svc.hit("/" + path, request.client.host if request.client else "")
    headers = {
        "ETag": etag,
        "Cache-Control": f"public, max-age={max_age}, stale-while-revalidate=600" if max_age else "no-store",
    }
    if request.headers.get("x-site-host"):
        headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.headers.get("if-none-match") == etag and max_age:
        return Response(status_code=304, headers=headers)
    await db.commit()
    return HTMLResponse(html, headers=headers)


@site_router.get("/sitemap.xml", include_in_schema=False)
async def sitemap(
    request: Request, slug: str | None = Query(None, max_length=60), db: AsyncSession = Depends(get_db)
) -> Response:
    try:
        iid, s = await resolve_public_tenant(db, request, slug)
    except APIError:
        root = f"{request.url.scheme}://{request.headers.get('host', '')}"
        body = (
            '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join(f"<url><loc>{root}/{p}</loc></url>" for p in ("", "pricing", "features", "demo", "signup"))
            + "</urlset>"
        )
        return Response(body, media_type="application/xml")
    return Response(
        await seo.sitemap(WebsiteBase(db, None, request, iid), _root(request, s)), media_type="application/xml"
    )


@site_router.get("/robots.txt", include_in_schema=False)
async def robots(request: Request) -> Response:
    return Response(seo.robots(f"{request.url.scheme}://{request.headers.get('host', '')}"), media_type="text/plain")
