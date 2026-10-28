"""SEO — Prompts/40 §40.6 ``seo_service``: ``sitemap.xml`` (home, notices, events, catalogue programmes / courses,
departments, disclosures — institution host; marketing pages on the platform host), ``robots.txt`` (disallows
``/admin``, ``/api``, ``?preview=``), the notices RSS feed (``application/rss+xml``, per category)."""

from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import text


async def sitemap(svc: Any, root: str) -> str:
    async def rows(sql: str) -> list[Any]:
        return list((await svc.db.execute(text(sql), {"i": svc.inst})).all())

    urls: list[tuple[str, Any]] = [
        ("", None),
        ("notices", None),
        ("events", None),
        ("catalogue", None),
        ("admissions", None),
        ("disclosures", None),
        ("faculty", None),
        ("gallery", None),
    ]
    urls += [
        (f"notices/{s}", u)
        for s, u in await rows(
            "SELECT slug, updated_at FROM website_notices WHERE institution_id = :i AND is_published AND (expires_at IS NULL OR expires_at > NOW())"
        )
    ]
    urls += [
        (f"departments/{c}", None)
        for (c,) in await rows("SELECT code FROM departments WHERE institution_id = :i AND deleted_at IS NULL")
    ]
    urls += [
        (f"pages/{s}/{g}", u)
        for s, g, u in await rows(
            "SELECT section, slug, updated_at FROM website_content_items WHERE institution_id = :i AND is_published"
        )
    ]
    try:
        from app.services.website.catalogue_service import CatalogueService

        for p in await CatalogueService(svc.db, None, svc.request, svc.inst).list_programmes(None, None, None, None):
            urls.append((f"catalogue/{p['code']}", None))
    except Exception:  # noqa: BLE001 - catalogue off
        pass
    body = "".join(
        f"<url><loc>{escape(root.rstrip('/') + '/' + u)}</loc>"
        + (f"<lastmod>{m.date().isoformat()}</lastmod>" if m else "")
        + "</url>"
        for u, m in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'


def robots(root: str) -> str:
    return f"User-agent: *\nDisallow: /admin\nDisallow: /api/\nDisallow: /*?preview=\nAllow: /\nSitemap: {root.rstrip('/')}/sitemap.xml\n"


async def rss(svc: Any, root: str, category: str | None, title: str) -> str:
    sql = (
        "SELECT title, slug, body, category, coalesce(publish_at, created_at) AS at FROM website_notices WHERE institution_id = :i "
        "AND is_published AND (publish_at IS NULL OR publish_at <= NOW()) AND (expires_at IS NULL OR expires_at > NOW())"
        + (" AND category = :c" if category else "")
        + " ORDER BY at DESC LIMIT 50"
    )
    items = (await svc.db.execute(text(sql), {"i": svc.inst, "c": category})).mappings().all()
    entries = "".join(
        f"<item><title>{escape(r['title'])}</title><link>{escape(root.rstrip('/'))}/notices/{escape(r['slug'])}</link>"
        f"<guid>{escape(root.rstrip('/'))}/notices/{escape(r['slug'])}</guid><category>{escape(r['category'] or 'general')}</category>"
        f"<pubDate>{format_datetime(r['at'])}</pubDate></item>"
        for r in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{escape(title)} — notices</title><link>{escape(root)}</link><description>Latest notices</description>"
        f"<lastBuildDate>{format_datetime(datetime.now(UTC))}</lastBuildDate>{entries}</channel></rss>"
    )
