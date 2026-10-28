"""Platform marketing site — Prompts/40 §40.6 ``marketing_service`` (platform-level; ``platform:manage``).

``platform_settings['marketing.site']`` = ``{draft, published, published_at}``; the super admin edits the draft and
publishes; ``GET /public/marketing`` serves the published copy with pricing from the active plans (Phase 38
``SubscriptionService.plans(public=True)``). Demo requests / sign-up post to the Phase 38 public endpoints.
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.website import MarketingOut, MarketingSiteIO

KEY = "marketing.site"

DEFAULT_MARKETING: dict[str, Any] = {
    "hero": {
        "title": "One ERP for colleges and universities",
        "subtitle": "Admissions to alumni — academics, exams, fees, hostel, accreditation and governance on one platform.",
        "cta": [{"label": "Book a demo", "href": "#demo"}, {"label": "Start free trial", "href": "#signup"}],
    },
    "features": [
        {
            "title": "Academics & OBE",
            "body": "Programmes, regulations, timetable, attendance, marks and CO/PO attainment.",
        },
        {"title": "Examinations", "body": "Registration, hall tickets, coding, valuation, results and transcripts."},
        {"title": "Fees & finance", "body": "Fee structures, online payments, scholarships, accounting and GST."},
        {"title": "Campus life", "body": "Hostel, transport, library, placement, alumni and grievances."},
        {"title": "Quality & governance", "body": "NAAC / NIRF / AISHE, committees, RTI and affiliation."},
        {"title": "Portals & mobile", "body": "Branded student, parent and faculty portals with an installable app."},
    ],
    "testimonials": [],
    "faq": [
        {"q": "Is our data isolated?", "a": "Every institution is a separate tenant protected by row-level security."},
        {
            "q": "Do you support affiliated colleges?",
            "a": "Yes — universities manage affiliation, centres and data submissions.",
        },
    ],
    "legal": {"privacy": "/legal/privacy", "terms": "/legal/terms", "dpdp": "/legal/dpdp"},
    "links": {"status": "https://status.septron.in", "docs": "/help"},
}


async def _get(db: AsyncSession) -> dict[str, Any]:
    r = (await db.execute(text("SELECT value FROM platform_settings WHERE key = :k"), {"k": KEY})).first()
    return (
        dict(r[0])
        if r and isinstance(r[0], dict)
        else {"draft": None, "published": DEFAULT_MARKETING, "published_at": None}
    )


async def _put(db: AsyncSession, value: dict[str, Any], actor: Any) -> None:
    await db.execute(
        text(
            "INSERT INTO platform_settings (key, value, updated_by, updated_at) VALUES (:k, CAST(:v AS jsonb), :u, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = NOW()"
        ),
        {"k": KEY, "v": json.dumps(value, default=str), "u": getattr(actor, "id", None)},
    )


async def pricing(db: AsyncSession) -> list[dict[str, Any]]:
    from app.services.saas.subscription_service import SubscriptionService

    return [
        p.model_dump(mode="json") if hasattr(p, "model_dump") else dict(p)
        for p in await SubscriptionService(db, None).plans(public=True)
    ]


async def admin_get(db: AsyncSession) -> MarketingOut:
    v = await _get(db)
    body = v.get("draft") or v.get("published") or DEFAULT_MARKETING
    return MarketingOut(
        **body,
        published_at=v.get("published_at"),
        has_unpublished_changes=bool(v.get("draft")),
        pricing=await pricing(db),
    )


async def save_draft(db: AsyncSession, body: MarketingSiteIO, actor: Any) -> MarketingOut:
    v = await _get(db)
    v["draft"] = body.model_dump(mode="json")
    await _put(db, v, actor)
    return await admin_get(db)


async def publish(db: AsyncSession, actor: Any) -> MarketingOut:
    v = await _get(db)
    if v.get("draft"):
        v["published"], v["draft"] = v["draft"], None
    v["published_at"] = datetime.now(UTC).isoformat()
    await _put(db, v, actor)
    from app.core import events

    await events.emit(
        db,
        institution_id=None,
        event_type="marketing.published",
        payload={"at": v["published_at"]},
        aggregate_type="marketing",
    )
    return await admin_get(db)


async def public(db: AsyncSession) -> MarketingOut:
    v = await _get(db)
    return MarketingOut(
        **(v.get("published") or DEFAULT_MARKETING), published_at=v.get("published_at"), pricing=await pricing(db)
    )
