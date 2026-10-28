"""``website`` demo seeder (Prompts/40 §40.2) — ``seed_demo_institution.py --only website``.

For the profile tenant: a published site config (hero, sections by institution type, SEO, contact, social) with one
version entry; 12 content items (about pages + 3 department pages + 1 college page); 40 notices across categories
(attachments, some scheduled / expired / pinned); up to 15 Phase 25 events mirrored + manual ones; 6 albums with 60
images; disclosure items (Phase 32 metrics where present + text items) published; catalogue settings (every programme
visible, two hidden when more than three exist, fees shown for one); one verified custom domain
``demo-uni.example.test`` (``ssl_status='active'``) and one pending; 80 website enquiries (≈ 10 % spam) linked to
Phase 08 ``enquiries(source='web')``. Idempotent via the marker ``website_meta seed:phase40``.
"""

import json
import random
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from seed_demo_institution import SeedContext, seeder
from sqlalchemy import select, text

CATEGORIES = ["general", "admissions", "examinations", "tenders", "recruitment", "events", "scholarships", "results"]


@seeder("website", after=["base", "academics", "admissions", "student_support"])
async def seed_website(ctx: SeedContext) -> None:  # noqa: C901, PLR0912, PLR0915 - one linear demo script
    import app.features  # noqa: F401
    from app.db.session import bind_tenant, set_tenant
    from app.models.platform import Institution
    from app.services.website.site_service import default_config

    db = ctx.db
    rng = random.Random(40)
    inst = (await db.execute(select(Institution).where(Institution.slug == ctx.profile["slug"]))).scalar_one()
    iid = inst.id
    bind_tenant(db, iid)
    await set_tenant(db, iid)

    async def meta(key: str, value: Any) -> None:
        await db.execute(
            text(
                "INSERT INTO institution_settings (id, institution_id, college_id, category, key, value, value_type, is_public, "
                "created_at, updated_at) VALUES (:id, :i, NULL, 'website_meta', :k, CAST(:v AS jsonb), 'json', FALSE, NOW(), NOW()) "
                "ON CONFLICT (institution_id, college_id, category, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"id": uuid.uuid4(), "i": iid, "k": key, "v": json.dumps(value, default=str)},
        )

    done = (
        await db.execute(
            text(
                "SELECT 1 FROM institution_settings WHERE institution_id = :i AND category = 'website_meta' AND key = 'seed:phase40'"
            ),
            {"i": iid},
        )
    ).first()
    if done:
        print("   website: already seeded (marker website_meta/seed:phase40)")
        return
    now = datetime.now(UTC)

    # ---- config (published) + one version ------------------------------------------------------------------------
    cfg = default_config(inst)
    cfg["hero"] = {
        "title": inst.name,
        "subtitle": "Excellence in teaching, research and service — admissions open for the new academic year",
        "image_url": None,
        "cta": [{"label": "Apply now", "href": "admissions"}, {"label": "Explore programmes", "href": "catalogue"}],
    }
    cfg["seo"] = {
        "title": f"{inst.name} — official website",
        "description": f"Programmes, admissions, notices and events of {inst.name}.",
        "keywords": ["university", "admissions", "programmes"],
        "robots": "index,follow",
    }
    cfg["contact"] = {
        "address": "University Road, Demo City 600001",
        "phone": "+91 44 0000 0000",
        "email": "info@demo-uni.example.test",
    }
    cfg["social"] = {"twitter": "https://twitter.com/example", "youtube": "https://youtube.com/@example"}
    await db.execute(
        text(
            "INSERT INTO institution_website_config (institution_id, is_enabled, theme, hero, sections, seo, contact, social, show_catalog, show_apply, updated_at) "
            "VALUES (:i, TRUE, CAST(:t AS jsonb), CAST(:h AS jsonb), CAST(:s AS jsonb), CAST(:seo AS jsonb), CAST(:c AS jsonb), CAST(:so AS jsonb), TRUE, TRUE, NOW()) "
            "ON CONFLICT (institution_id) DO UPDATE SET hero = EXCLUDED.hero, sections = EXCLUDED.sections, seo = EXCLUDED.seo, "
            "contact = EXCLUDED.contact, social = EXCLUDED.social, updated_at = NOW()"
        ),
        {
            "i": iid,
            "t": json.dumps(cfg["theme"]),
            "h": json.dumps(cfg["hero"]),
            "s": json.dumps(cfg["sections"]),
            "seo": json.dumps(cfg["seo"]),
            "c": json.dumps(cfg["contact"]),
            "so": json.dumps(cfg["social"]),
        },
    )
    await meta(
        "config:versions",
        [{"version": 1, "published_at": now.isoformat(), "published_by": None, "notes": "demo seed", "config": cfg}],
    )
    ctx.count("website_configs")

    # ---- content items ------------------------------------------------------------------------------------------
    depts = (
        await db.execute(
            text(
                "SELECT code, name FROM departments WHERE institution_id = :i AND deleted_at IS NULL ORDER BY code LIMIT 3"
            ),
            {"i": iid},
        )
    ).all()
    colleges = (
        await db.execute(
            text(
                "SELECT code, name FROM colleges WHERE institution_id = :i AND deleted_at IS NULL ORDER BY code LIMIT 1"
            ),
            {"i": iid},
        )
    ).all()
    items: list[tuple[str, str, str, str]] = [
        (
            "about",
            "history",
            "Our history",
            "<p>Founded to serve the region, the institution has grown into a multi-disciplinary centre of learning.</p>",
        ),
        (
            "about",
            "vision",
            "Vision & mission",
            "<p>To be a globally recognised institution that nurtures innovation and character.</p>",
        ),
        (
            "about",
            "governance",
            "Governance",
            "<p>The Board of Management, Academic Council and statutory committees guide the institution.</p>",
        ),
        (
            "about",
            "campus",
            "Campus",
            "<p>A 120-acre green campus with hostels, library, labs and sports facilities.</p>",
        ),
        ("about", "research", "Research", "<p>Funded projects, patents and an incubation centre.</p>"),
        ("about", "iqac", "IQAC", "<p>The Internal Quality Assurance Cell coordinates NAAC / NIRF submissions.</p>"),
        ("about", "anti-ragging", "Anti-ragging", "<p>Ragging is a criminal offence. Helpline: 1800-180-5522.</p>"),
        ("about", "rti", "RTI", "<p>Public Information Officer: the Registrar.</p>"),
    ]
    items += [
        (
            f"department:{c}",
            "about",
            f"Department of {n}",
            f'<p>Welcome to the Department of {n}.</p><iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>',
        )
        for c, n in depts
    ]
    items += [(f"college:{c}", "about", n, f"<p>{n} — a constituent college.</p>") for c, n in colleges]
    for n, (section, slug, title, body) in enumerate(items[:12]):
        await db.execute(
            text(
                "INSERT INTO website_content_items (id, institution_id, section, slug, title, body, media, sequence, is_published, created_at, updated_at) "
                "VALUES (:id, :i, :s, :g, :t, :b, '[]'::jsonb, :q, TRUE, NOW(), NOW()) ON CONFLICT (institution_id, section, slug) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "i": iid, "s": section, "g": slug, "t": title, "b": body, "q": n + 1},
        )
    ctx.count("website_content_items", min(12, len(items)))

    # ---- notices ------------------------------------------------------------------------------------------------
    for n in range(40):
        cat = CATEGORIES[n % len(CATEGORIES)]
        publish = now - timedelta(days=rng.randint(0, 120))
        expires = None
        if n % 9 == 0:
            expires = now - timedelta(days=1)  # expired → 410
        elif n % 11 == 0:
            publish = now + timedelta(days=2)  # scheduled
        nid = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO website_notices (id, institution_id, title, slug, body, attachments, category, publish_at, expires_at, is_published, created_at, updated_at) "
                "VALUES (:id, :i, :t, :s, :b, CAST(:a AS jsonb), :c, :p, :e, TRUE, :p, NOW()) ON CONFLICT (institution_id, slug) DO NOTHING"
            ),
            {
                "id": nid,
                "i": iid,
                "t": f"{cat.title()} notice {n + 1}",
                "s": f"{cat}-notice-{n + 1}",
                "b": f"<p>Details of the {cat} notice {n + 1}.</p>",
                "a": json.dumps(
                    [{"name": f"notice-{n + 1}.pdf", "url": f"/files/public/notices/notice-{n + 1}.pdf"}]
                    if n % 3 == 0
                    else []
                ),
                "c": cat,
                "p": publish,
                "e": expires,
            },
        )
        if n < 3:
            await meta(f"notice:{nid}", {"pin": True, "live_emitted": True})
    ctx.count("website_notices", 40)

    # ---- events (mirror Phase 25) --------------------------------------------------------------------------------
    evs = (
        await db.execute(
            text(
                "SELECT id, title, description, from_on, to_on FROM events WHERE institution_id = :i AND deleted_at IS NULL AND status IN ('scheduled', 'approved', 'completed', 'published') ORDER BY from_on DESC LIMIT 15"
            ),
            {"i": iid},
        )
    ).all()
    for eid, title, desc, f, t in evs:
        await db.execute(
            text(
                "INSERT INTO website_events (id, institution_id, event_id, title, slug, description, starts_at, ends_at, is_published, created_at) "
                "VALUES (:id, :i, :e, :t, :s, :d, :f, :to, TRUE, NOW()) ON CONFLICT (institution_id, slug) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "i": iid,
                "e": eid,
                "t": title[:200],
                "s": f"event-{str(eid)[:8]}",
                "d": desc,
                "f": datetime.combine(f, datetime.min.time(), UTC) if f else None,
                "to": datetime.combine(t or f, datetime.min.time(), UTC) if f else None,
            },
        )
    for n in range(max(0, 15 - len(evs))):
        await db.execute(
            text(
                "INSERT INTO website_events (id, institution_id, title, slug, starts_at, is_published, created_at) VALUES (:id, :i, :t, :s, :f, TRUE, NOW()) ON CONFLICT (institution_id, slug) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "i": iid,
                "t": f"Open day {n + 1}",
                "s": f"open-day-{n + 1}",
                "f": now + timedelta(days=7 * (n + 1)),
            },
        )
    ctx.count("website_events", 15)

    # ---- gallery ------------------------------------------------------------------------------------------------
    for a in range(6):
        aid = uuid.uuid4()
        await db.execute(
            text(
                "INSERT INTO gallery_albums (id, institution_id, title, description, cover_url, is_published, sequence, created_at) VALUES (:id, :i, :t, :d, :c, TRUE, :q, NOW())"
            ),
            {
                "id": aid,
                "i": iid,
                "t": ["Convocation", "Sports day", "Cultural fest", "Campus", "Labs", "Hostel life"][a],
                "d": "Photos",
                "c": f"https://picsum.photos/seed/album{a}/640/400",
                "q": a + 1,
            },
        )
        for g in range(10):
            await db.execute(
                text(
                    "INSERT INTO gallery_images (id, institution_id, album_id, image_url, caption, sequence, created_at) VALUES (:id, :i, :a, :u, :c, :q, NOW())"
                ),
                {
                    "id": uuid.uuid4(),
                    "i": iid,
                    "a": aid,
                    "u": f"https://picsum.photos/seed/a{a}g{g}/1280/800",
                    "c": f"Photo {g + 1}",
                    "q": g + 1,
                },
            )
    ctx.count("gallery_albums", 6)
    ctx.count("gallery_images", 60)

    # ---- disclosures / catalogue -----------------------------------------------------------------------------------
    metrics = [
        r[0]
        for r in (
            await db.execute(
                text("SELECT DISTINCT metric_key FROM metric_values WHERE institution_id = :i LIMIT 6"), {"i": iid}
            )
        ).all()
    ]
    disclosure_items = [
        {
            "key": k,
            "title": k.replace(".", " ").replace("_", " ").title(),
            "source": "metric",
            "ref": k,
            "is_published": True,
        }
        for k in metrics
    ]
    disclosure_items += [
        {
            "key": "aicte_approval",
            "title": "AICTE approval letter",
            "source": "document",
            "ref": "/files/public/disclosures/aicte.pdf",
            "is_published": True,
        },
        {
            "key": "fee_regulatory",
            "title": "Fee approved by the fee regulatory committee",
            "source": "text",
            "text": "As per G.O. 123 / 2026",
            "is_published": True,
        },
        {"key": "draft_item", "title": "Draft item", "source": "text", "text": "not yet public", "is_published": False},
    ]
    await meta("disclosures", {"items": disclosure_items})
    progs = (
        await db.execute(
            text("SELECT id FROM programs WHERE institution_id = :i AND deleted_at IS NULL ORDER BY code"), {"i": iid}
        )
    ).all()
    cat_items = [
        {
            "program_id": str(p[0]),
            "visible": not (len(progs) > 3 and n >= len(progs) - 2),
            "show_fees": n == 0,
            "highlight": n == 0,
        }
        for n, p in enumerate(progs)
    ]
    await meta(
        "catalogue", {"programmes": cat_items, "courses_hidden": [], "show_electives": True, "show_outcomes": True}
    )

    # ---- domains ------------------------------------------------------------------------------------------------
    for host, active in (("demo-uni.example.test", True), (f"www.{ctx.profile['slug']}-pending.example.test", False)):
        await db.execute(
            text(
                "INSERT INTO institution_domains (id, institution_id, hostname, is_primary, verification_token, verified_at, ssl_status, created_at) "
                "VALUES (:id, :i, :h, FALSE, :t, :v, :s, NOW()) ON CONFLICT (hostname) DO NOTHING"
            ),
            {
                "id": uuid.uuid4(),
                "i": iid,
                "h": host,
                "t": secrets.token_hex(16),
                "v": now if active else None,
                "s": "active" if active else "pending",
            },
        )
    ctx.count("institution_domains", 2)

    # ---- enquiries ----------------------------------------------------------------------------------------------
    for n in range(80):
        spam = n % 10 == 0
        enq_id = None
        if not spam:
            enq_id = uuid.uuid4()
            await db.execute(
                text(
                    "INSERT INTO enquiries (id, institution_id, source, name, phone, email, program_interest, stage, notes, created_at, updated_at) "
                    "VALUES (:id, :i, 'web', :n, :p, :e, CAST(:pi AS jsonb), :st, '[]'::jsonb, NOW(), NOW())"
                ),
                {
                    "id": enq_id,
                    "i": iid,
                    "n": f"Enquirer {n + 1}",
                    "p": f"+9190000{n:05d}",
                    "e": f"enquirer{n + 1}@example.test",
                    "pi": json.dumps(["BTECH"]),
                    "st": rng.choice(["new", "contacted", "counselled", "applied"]),
                },
            )
        await db.execute(
            text(
                "INSERT INTO website_enquiries (id, institution_id, name, email, phone, subject, message, source_page, enquiry_id, status, created_at) "
                "VALUES (:id, :i, :n, :e, :p, :s, :m, :sp, :q, :st, NOW() - make_interval(days => :d))"
            ),
            {
                "id": uuid.uuid4(),
                "i": iid,
                "n": f"Enquirer {n + 1}",
                "e": f"enquirer{n + 1}@example.test",
                "p": f"+9190000{n:05d}",
                "s": "Admission enquiry" if not spam else "BUY CHEAP http://spam.test",
                "m": "Please share the fee structure and eligibility."
                if not spam
                else "http://spam.test http://spam.test",
                "sp": "/site/demo-uni/contact",
                "q": enq_id,
                "st": "spam" if spam else rng.choice(["new", "contacted", "converted"]),
                "d": rng.randint(0, 60),
            },
        )
    ctx.count("website_enquiries", 80)
    await meta("seed:phase40", {"at": now.isoformat()})
    await db.commit()
