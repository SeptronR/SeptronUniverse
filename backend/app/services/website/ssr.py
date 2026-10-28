"""Server-side rendering of the public site — Prompts/40 §40.6 ``site_service`` rule 2 / 3 and §40.9.

Decision (PROGRESS.md Phase 40): pages are rendered by the API from the same section data the JSON endpoints serve
(semantic HTML, no client JavaScript required; one small inline script posts the enquiry / result-lookup forms to
the public API) instead of a separate Vite-SSR Node process — one process less to operate, identical output for
crawlers and visitors, WCAG-friendly markup (landmarks, skip link, labelled forms), print styles and the five theme
colours. ``window.__SITE__`` carries the data for progressive enhancement.
"""

import json
from datetime import UTC, datetime
from html import escape as e
from typing import Any

from sqlalchemy import text

from app.core.errors import APIError, ErrorCode
from app.schemas.website import PublicSiteOut

THEMES = {"indigo": "#4f46e5", "ocean": "#0369a1", "grove": "#15803d", "sunset": "#c2410c", "plum": "#7e22ce"}
NAV = (
    ("", "Home"),
    ("catalogue", "Programmes"),
    ("admissions", "Admissions"),
    ("notices", "Notices"),
    ("events", "Events"),
    ("gallery", "Gallery"),
    ("disclosures", "Disclosures"),
    ("contact", "Contact"),
)


def _txt(v: Any) -> str:
    return e(str(v)) if v not in (None, "") else ""


def _date(v: Any) -> str:
    if not v:
        return ""
    try:
        return datetime.fromisoformat(str(v)).strftime("%d %b %Y")
    except ValueError:
        return _txt(v)


def _list(items: list[Any], fn: Any) -> str:
    return (
        '<ul class="cards">' + "".join(f"<li>{fn(i)}</li>" for i in items) + "</ul>"
        if items
        else "<p>Nothing to show yet.</p>"
    )


def _section_html(base: str, s: dict[str, Any]) -> str:
    t = s["type"]
    d: Any = s.get("data") or ({} if s["type"] in ("about", "contact", "hero") else [])
    title = s.get("title") or t.replace("_", " ").title()
    inner = ""
    if t == "hero":
        cta = "".join(
            f'<a class="btn" href="{base}{_txt(c.get("href", ""))}">{_txt(c.get("label"))}</a>'
            for c in (d or {}).get("cta") or []
        )
        return f'<section class="hero"><h1>{_txt((d or {}).get("title"))}</h1><p>{_txt((d or {}).get("subtitle"))}</p><p>{cta}</p></section>'
    if t == "about":
        inner = f"<p>{_txt(d.get('vision'))}</p><p>{_txt(d.get('mission'))}</p>"
    elif t in ("notices",):
        inner = _list(
            d,
            lambda n: f'<a href="{base}notices/{_txt(n["slug"])}">{_txt(n["title"])}</a> <small>{_txt(n.get("category"))} · {_date(n.get("publish_at"))}</small>',
        )
    elif t == "events":
        inner = _list(
            d,
            lambda n: f'<a href="{base}events#{_txt(n["slug"])}">{_txt(n["title"])}</a> <small>{_date(n.get("starts_at"))}</small>',
        )
    elif t == "programmes":
        inner = _list(
            d,
            lambda p: f'<a href="{base}catalogue/{_txt(p["code"])}">{_txt(p["name"])}</a> <small>{_txt(p.get("level"))}</small>',
        )
    elif t == "admissions_cta":
        inner = _list(
            d, lambda c: f'{_txt(c.get("name"))} <a class="btn" href="{_txt(c.get("apply_url"))}">Apply now</a>'
        )
    elif t == "gallery":
        inner = _list(
            d,
            lambda a: f'<a href="{base}gallery/{_txt(a["id"])}">{_txt(a["title"])}</a> <small>{_txt(a.get("images"))} photos</small>',
        )
    elif t == "stats" and isinstance(d, dict):
        inner = (
            '<dl class="stats">'
            + "".join(
                f"<div><dt>{_txt(k.replace('_', ' '))}</dt><dd>{_txt(v if not isinstance(v, dict) else v.get('value'))}</dd></div>"
                for k, v in d.items()
            )
            + "</dl>"
        )
    elif t in ("departments", "colleges"):
        seg = "departments" if t == "departments" else "colleges"
        inner = _list(d, lambda x: f'<a href="{base}{seg}/{_txt(x["code"])}">{_txt(x["name"])}</a>')
    elif t == "disclosures":
        inner = _list(
            d,
            lambda x: f"{_txt(x.get('title'))}: {_txt((x.get('value') or {}).get('value') if isinstance(x.get('value'), dict) else x.get('value'))}",
        )
    elif t == "contact":
        inner = f"<address>{_txt(d.get('address'))}<br>{_txt(d.get('phone'))} {_txt(d.get('email'))}</address>" + (
            enquiry_form(base) if d.get("enquiry") else ""
        )
    elif t == "custom_html":
        inner = (d or {}).get("html") or ""
    elif t == "footer":
        return ""
    elif isinstance(d, list):
        inner = _list(d, lambda x: _txt(x.get("title") or x.get("name") or x) if isinstance(x, dict) else _txt(x))
    elif isinstance(d, dict):
        inner = (
            "<dl>"
            + "".join(
                f"<dt>{_txt(k.replace('_', ' '))}</dt><dd>{_txt(v)}</dd>"
                for k, v in d.items()
                if not isinstance(v, (list, dict))
            )
            + "</dl>"
        )
    return f'<section id="{_txt(t)}" aria-labelledby="h-{_txt(t)}"><h2 id="h-{_txt(t)}">{_txt(title)}</h2>{inner}</section>'


def enquiry_form(base: str) -> str:
    return (
        '<form class="enquiry" data-endpoint="/api/v1/public/site/enquiries" data-slug="'
        + base.strip("/").split("/")[-1]
        + '">'
        '<h3>Send an enquiry</h3><label>Name <input name="name" required minlength="2"></label>'
        '<label>E-mail <input name="email" type="email"></label><label>Phone <input name="phone" inputmode="tel"></label>'
        '<label>Message <textarea name="message" required minlength="3"></textarea></label>'
        '<label class="hp" aria-hidden="true">Website <input name="website" tabindex="-1" autocomplete="off"></label>'
        "<p><small>We use these details only to answer your enquiry (DPDP notice).</small></p>"
        '<button class="btn" type="submit">Send</button><p role="status" class="out"></p></form>'
    )


FORM_JS = """
document.querySelectorAll('form[data-endpoint]').forEach(function(f){f.addEventListener('submit',async function(ev){
ev.preventDefault();var d=Object.fromEntries(new FormData(f).entries());d.source_page=location.pathname;
var r=await fetch(f.dataset.endpoint+'?slug='+encodeURIComponent(f.dataset.slug),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)});
var j=await r.json().catch(function(){return{}});f.querySelector('.out').textContent=r.ok?('Thank you — reference '+((j.data||{}).reference||((j.data||{}).sgpa!==undefined?'':'')||'received')):((j.error||{}).message||'Please try again');
if(r.ok&&j.data&&j.data.result){f.querySelector('.out').textContent=JSON.stringify(j.data.result);}});});
"""


def layout(
    site: PublicSiteOut,
    path: str,
    body: str,
    title: str,
    description: str,
    extra_head: str = "",
    json_ld: dict[str, Any] | None = None,
) -> str:
    inst = site.institution
    theme = site.config.get("theme") or {}
    color = theme.get("primary") or THEMES.get(str(theme.get("name") or "indigo"), "#4f46e5")
    base = f"/site/{inst['slug']}/"
    canonical = (site.canonical or base).rstrip("/") + "/" + path.strip("/")
    ld = json_ld or {
        "@context": "https://schema.org",
        "@type": "CollegeOrUniversity",
        "name": inst["name"],
        "url": site.canonical,
        "logo": inst.get("logo_url"),
    }
    robots = (
        "noindex,nofollow" if site.preview else _txt((site.config.get("seo") or {}).get("robots") or "index,follow")
    )
    nav = "".join(
        f'<a href="{base}{p}"{' aria-current="page"' if path.strip("/") == p else ""}>{label}</a>' for p, label in NAV
    )
    social = "".join(
        f'<a href="{_txt(u)}" rel="noopener">{_txt(k)}</a> ' for k, u in (site.config.get("social") or {}).items()
    )
    data_json = json.dumps(site.model_dump(mode="json"), default=str).replace("</", "<\\/")
    ld_json = json.dumps(ld, default=str).replace("</", "<\\/")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{_txt(title)}</title><meta name="description" content="{_txt(description)}"><meta name="robots" content="{robots}">'
        f'<link rel="canonical" href="{_txt(canonical)}"><meta name="theme-color" content="{_txt(color)}">'
        f'<meta property="og:type" content="website"><meta property="og:title" content="{_txt(title)}"><meta property="og:description" content="{_txt(description)}">'
        f'<meta property="og:url" content="{_txt(canonical)}"><meta property="og:image" content="{_txt((site.config.get("seo") or {}).get("og_image_url") or inst.get("logo_url"))}">'
        '<meta name="twitter:card" content="summary_large_image">'
        f'<link rel="manifest" href="/api/v1/public/manifest.json?institution={_txt(inst["slug"])}">'
        f'<link rel="alternate" type="application/rss+xml" title="Notices" href="/api/v1/public/site/notices.rss?slug={_txt(inst["slug"])}">'
        f'<script type="application/ld+json">{ld_json}</script>{extra_head}<style>'
        f":root{{--brand:{color}}}*{{box-sizing:border-box}}body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;color:#111827;line-height:1.55}}"
        "a{color:var(--brand)}header.site,footer.site{background:#f8fafc;border-bottom:1px solid #e5e7eb;padding:.75rem 1rem}"
        "header.site nav a{margin-right:1rem;text-decoration:none;font-weight:500}header.site nav a[aria-current]{text-decoration:underline}"
        "main{max-width:72rem;margin:0 auto;padding:1rem}section{margin:2rem 0}h1,h2{color:var(--brand)}"
        ".hero{padding:3rem 1rem;background:linear-gradient(135deg,var(--brand),#111827);color:#fff;border-radius:1rem}.hero h1{color:#fff}"
        ".btn{display:inline-block;background:var(--brand);color:#fff;padding:.5rem 1rem;border-radius:.5rem;text-decoration:none;margin-right:.5rem;border:0}"
        ".cards{list-style:none;padding:0;display:grid;gap:.75rem;grid-template-columns:repeat(auto-fill,minmax(16rem,1fr))}"
        ".cards li{border:1px solid #e5e7eb;border-radius:.75rem;padding:.75rem}.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(10rem,1fr));gap:1rem}"
        ".stats dd{font-size:1.75rem;font-weight:700;margin:0}form label{display:block;margin:.5rem 0}form input,form textarea{width:100%;padding:.5rem;border:1px solid #d1d5db;border-radius:.375rem}"
        ".hp{position:absolute;left:-9999px}.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;top:1rem;background:#fff;padding:.5rem}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #e5e7eb;padding:.375rem;text-align:left}"
        "@media print{header.site nav,footer.site,form{display:none}.hero{background:none;color:#000}}"
        "@media (prefers-reduced-motion:reduce){*{transition:none!important}}</style></head><body>"
        f'<a class="skip" href="#main">Skip to content</a><header class="site"><strong><a href="{base}">{_txt(inst["name"])}</a></strong>'
        f'{" <em>(preview)</em>" if site.preview else ""}<nav aria-label="Main">{nav}</nav></header>'
        f'<main id="main" tabindex="-1">{body}</main><footer class="site"><p>© {datetime.now(UTC).year} {_txt(inst["name"])} · '
        f'<a href="{base}disclosures">Mandatory disclosures</a> · <a href="/api/v1/public/site/notices.rss?slug={_txt(inst["slug"])}">RSS</a> {social}</p></footer>'
        f"<script>window.__SITE__={data_json};{FORM_JS}</script></body></html>"
    )


async def render_page(svc: Any, site: PublicSiteOut, path: str, extra_head: str = "") -> str:  # noqa: C901, PLR0912
    from app.services.website import public_service
    from app.services.website.catalogue_service import CatalogueService

    inst = site.institution
    base = f"/site/{inst['slug']}/"
    parts = [p for p in path.strip("/").split("/") if p]
    seo = site.config.get("seo") or {}
    name = str(inst["name"])
    title, desc, ld = (
        str(seo.get("title") or name),
        str(seo.get("description") or (site.config.get("hero") or {}).get("subtitle") or name),
        None,
    )

    async def rows(sql: str, **p: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in (await svc.db.execute(text(sql), {"i": svc.inst, **p})).mappings().all()]

    if not parts:
        body = "".join(_section_html(base, s) for s in site.sections)
    elif parts[0] == "notices" and len(parts) == 1:
        items = await rows(
            "SELECT title, slug, category, publish_at, expires_at FROM website_notices WHERE institution_id = :i AND is_published "
            "AND (publish_at IS NULL OR publish_at <= NOW()) ORDER BY publish_at DESC NULLS LAST LIMIT 200"
        )
        now = datetime.now(UTC)
        live = [n for n in items if not n["expires_at"] or n["expires_at"] > now]
        archive = [n for n in items if n["expires_at"] and n["expires_at"] <= now]
        body = "<h1>Notices</h1>" + _list(
            live,
            lambda n: f'<a href="{base}notices/{_txt(n["slug"])}">{_txt(n["title"])}</a> <small>{_txt(n["category"])} · {_date(n["publish_at"])}</small>',
        )
        body += "<h2>Archive</h2>" + _list(
            archive[:50], lambda n: f"{_txt(n['title'])} <small>{_date(n['publish_at'])}</small>"
        )
        title = f"Notices · {name}"
    elif parts[0] == "notices":
        r = await rows(
            "SELECT title, body, category, publish_at, expires_at, attachments FROM website_notices WHERE institution_id = :i AND slug = :s AND is_published",
            s=parts[1],
        )
        if not r or (r[0]["publish_at"] and r[0]["publish_at"] > datetime.now(UTC)):
            raise APIError(404, ErrorCode.NOT_FOUND, "Notice not found")
        n = r[0]
        if n["expires_at"] and n["expires_at"] <= datetime.now(UTC):
            raise APIError(410, ErrorCode.GONE, "This notice has expired", {"archive": f"{base}notices"})
        att = "".join(
            f'<li><a href="{_txt(a.get("url"))}">{_txt(a.get("name") or "Attachment")}</a></li>'
            for a in (n["attachments"] or [])
        )
        body = f"<article><h1>{_txt(n['title'])}</h1><p><small>{_txt(n['category'])} · {_date(n['publish_at'])}</small></p>{n['body'] or ''}<ul>{att}</ul></article>"
        title = f"{n['title']} · {name}"
    elif parts[0] == "events":
        items = await rows(
            "SELECT title, slug, description, starts_at, ends_at, image_url, event_id FROM website_events WHERE institution_id = :i AND is_published ORDER BY starts_at DESC NULLS LAST LIMIT 100"
        )
        body = "<h1>Events</h1>" + _list(
            items,
            lambda x: f'<span id="{_txt(x["slug"])}"></span><strong>{_txt(x["title"])}</strong> <small>{_date(x["starts_at"])}</small>'
            + (f' <a href="/api/v1/events/public/{x["event_id"]}/register">Register</a>' if x.get("event_id") else ""),
        )
        ld = {
            "@context": "https://schema.org",
            "@graph": [{"@type": "Event", "name": x["title"], "startDate": str(x["starts_at"])} for x in items[:20]],
        }
    elif parts[0] == "gallery":
        if len(parts) == 1:
            items = await rows(
                "SELECT id, title, cover_url FROM gallery_albums WHERE institution_id = :i AND is_published ORDER BY sequence"
            )
            body = "<h1>Gallery</h1>" + _list(
                items,
                lambda a: f'<a href="{base}gallery/{a["id"]}">'
                + (
                    f'<img src="{_txt(a["cover_url"])}" alt="" loading="lazy" width="320">'
                    if a.get("cover_url")
                    else ""
                )
                + f"<br>{_txt(a['title'])}</a>",
            )
        else:
            imgs = await rows(
                "SELECT g.image_url, g.caption FROM gallery_images g JOIN gallery_albums a ON a.id = g.album_id WHERE a.institution_id = :i AND CAST(a.id AS text) = :a AND a.is_published ORDER BY g.sequence",
                a=parts[1],
            )
            body = "<h1>Album</h1>" + _list(
                imgs,
                lambda g: f'<figure><img src="{_txt(g["image_url"])}" alt="{_txt(g.get("caption"))}" loading="lazy" width="320"><figcaption>{_txt(g.get("caption"))}</figcaption></figure>',
            )
    elif parts[0] == "pages" and len(parts) == 3:
        r = await rows(
            "SELECT title, body FROM website_content_items WHERE institution_id = :i AND section = :s AND slug = :g AND is_published",
            s=parts[1],
            g=parts[2],
        )
        if not r:
            raise APIError(404, ErrorCode.NOT_FOUND, "Page not found")
        body, title = (
            f"<article><h1>{_txt(r[0]['title'])}</h1>{r[0]['body'] or ''}</article>",
            f"{r[0]['title']} · {name}",
        )
    elif parts[0] in ("colleges", "departments") and len(parts) == 2:
        kind = "college" if parts[0] == "colleges" else "department"
        table = "colleges" if kind == "college" else "departments"
        info = await rows(
            f"SELECT name FROM {table} WHERE institution_id = :i AND code = :c AND deleted_at IS NULL",
            c=parts[1].upper(),
        )  # noqa: S608 - fixed table names
        if not info:
            raise APIError(404, ErrorCode.NOT_FOUND, "Not found")
        pages = await rows(
            "SELECT slug, title, body FROM website_content_items WHERE institution_id = :i AND section = :s AND is_published ORDER BY sequence",
            s=f"{kind}:{parts[1].upper()}",
        )
        body = f"<h1>{_txt(info[0]['name'])}</h1>" + "".join(
            f"<section><h2>{_txt(p['title'])}</h2>{p['body'] or ''}</section>" for p in pages
        )
    elif parts[0] == "faculty":
        people = await public_service.faculty_directory(svc)
        body = "<h1>Faculty</h1>" + _list(
            people, lambda p: "<br>".join(_txt(v) for v in p.values() if v and not str(v).startswith("http"))
        )
    elif parts[0] == "disclosures":
        items = await public_service.disclosures(svc)
        body = (
            "<h1>Mandatory disclosures</h1><table><thead><tr><th>Item</th><th>Details</th></tr></thead><tbody>"
            + "".join(
                f"<tr><td>{_txt(i['title'])}</td><td>"
                + (
                    f'<a href="{_txt(i["value"].get("url"))}">Open</a>'
                    if isinstance(i.get("value"), dict) and i["value"].get("url")
                    else _txt(
                        (i.get("value") or {}).get("value") if isinstance(i.get("value"), dict) else i.get("value")
                    )
                )
                + "</td></tr>"
                for i in items
            )
            + "</tbody></table>"
        )
    elif parts[0] == "admissions":
        a = await public_service.admissions(svc)
        body = "<h1>Admissions</h1><h2>Open</h2>" + _list(
            a.open,
            lambda c: f'<strong>{_txt(c["name"])}</strong> — closes {_date(c.get("closes_at"))} <a class="btn" href="{_txt(c["apply_url"])}">Apply now</a> <a href="/apply/{_txt(c["slug"])}/status">Track status</a>',
        )
        body += (
            "<h2>Upcoming</h2>"
            + _list(a.upcoming, lambda c: f"{_txt(c['name'])} — opens {_date(c.get('opens_at'))}")
            + "<h2>Closed</h2>"
            + _list(a.closed[:10], lambda c: _txt(c["name"]))
        )
    elif parts[0] == "catalogue" and len(parts) == 1:
        items = await CatalogueService(svc.db, None, svc.request, svc.inst).list_programmes(None, None, None, None)
        body = "<h1>Programmes</h1>" + _list(
            items,
            lambda p: f'<a href="{base}catalogue/{_txt(p["code"])}">{_txt(p["name"])}</a><br><small>{_txt(p.get("level"))} · {_txt(p.get("department"))} · intake {_txt(p.get("intake"))}</small>',
        )
    elif parts[0] == "catalogue" and len(parts) == 3 and parts[1] == "course":
        c = await CatalogueService(svc.db, None, svc.request, svc.inst).course(parts[2])
        body, ld = (
            f"<article><h1>{_txt(c.get('code'))} — {_txt(c.get('title'))}</h1><p>Credits {_txt(c.get('credits'))}</p><pre>{_txt(json.dumps(c.get('syllabus'), default=str, indent=1) if c.get('syllabus') else '')}</pre></article>",
            c.get("json_ld"),
        )
    elif parts[0] == "catalogue" and len(parts) == 2:
        p = await CatalogueService(svc.db, None, svc.request, svc.inst).programme(parts[1])
        terms = "".join(
            f"<h3>Term {t['number']}</h3><table><thead><tr><th>Code</th><th>Course</th><th>Credits</th></tr></thead><tbody>"
            + "".join(
                f'<tr><td><a href="{base}catalogue/course/{_txt(c.get("code"))}">{_txt(c.get("code"))}</a></td><td>{_txt(c.get("title"))}</td><td>{_txt(c.get("credits"))}</td></tr>'
                for c in t["courses"]
            )
            + "</tbody></table>"
            for t in p.get("terms") or []
        )
        fees = f"<p><strong>Indicative fees:</strong> {_txt(p['fees_summary'])}</p>" if p.get("fees_summary") else ""
        apply = f'<p><a class="btn" href="{_txt(p["apply_url"])}">Apply now</a></p>' if p.get("apply_url") else ""
        body, ld, title = (
            f"<article><h1>{_txt(p.get('name'))}</h1><p>{_txt(p.get('degree_name'))} · {_txt(p.get('duration_years'))} years · intake {_txt(p.get('intake'))}</p>{apply}{fees}{terms}</article>",
            p.get("json_ld"),
            f"{p.get('name')} · {name}",
        )
    elif parts[0] == "affiliated-colleges":
        cols = await public_service.affiliated_colleges(svc)
        body = "<h1>Affiliated colleges</h1>" + _list(
            cols,
            lambda c: f"<strong>{_txt(c['name'])}</strong> ({_txt(c['code'])})<br>"
            + ", ".join(_txt(p.get("name")) for p in c.get("programmes") or []),
        )
    elif parts[0] == "verify" and len(parts) == 2:
        body = f'<h1>Verify a document</h1><p><a class="btn" href="/verify/{_txt(parts[1])}">Open the verification page</a></p>'
    elif parts[0] == "results":
        if not await svc.setting("results_public_lookup"):
            raise APIError(404, ErrorCode.NOT_FOUND, "Not available")
        body = (
            '<h1>Result lookup</h1><form data-endpoint="/api/v1/public/site/results/lookup" data-slug="'
            + _txt(inst["slug"])
            + '">'
            '<label>Registration number <input name="registration_number" required></label><label>Date of birth <input name="dob" type="date"></label>'
            '<button class="btn" type="submit">Look up</button><p role="status" class="out"></p></form>'
        )
    elif parts[0] == "contact":
        contact = next(
            (s for s in site.sections if s["type"] == "contact"),
            {"type": "contact", "data": {**(site.config.get("contact") or {}), "enquiry": True}},
        )
        body = _section_html(base, contact)
    else:
        raise APIError(404, ErrorCode.NOT_FOUND, "Page not found")
    return layout(site, path, body, title, desc, extra_head, ld)


def error_page(status: int, message: str, base: str = "/") -> str:
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{status}</title><meta name="robots" content="noindex">'
        "<style>body{font-family:system-ui;max-width:40rem;margin:4rem auto;padding:1rem}</style></head><body>"
        f"<h1>{'Gone' if status == 410 else 'Not found' if status == 404 else 'Unavailable'}</h1><p>{e(message)}</p>"
        f'<p><a href="{e(base)}">Back to the home page</a></p></body></html>'
    )
