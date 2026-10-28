"""Shell banners in ``/auth/me`` — Prompts/38 §38.9 (``SubscriptionBanner``, ``OutageBanner``, API-cap banner,
``PlatformAnnouncementBanner`` count, impersonation notice). Cheap reads only (one subscription row, Redis keys);
any failure drops the banner instead of failing ``/auth/me``."""

import contextlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def banners(db: AsyncSession, principal: Any) -> dict[str, Any]:
    from app.db.session import redis_client

    out: dict[str, Any] = {
        "subscription": None,
        "outage": [],
        "api_cap": None,
        "impersonated": bool(principal.impersonator_id),
        "announcements": 0,
    }
    inst = principal.institution_id
    if inst is None:
        return out
    with contextlib.suppress(Exception):
        row = (
            await db.execute(
                text(
                    "SELECT status, ends_on, grace_until FROM institution_subscriptions WHERE institution_id = :i "
                    "ORDER BY starts_on DESC, created_at DESC LIMIT 1"
                ),
                {"i": inst},
            )
        ).first()
        if row is not None:
            status, ends_on, grace_until = row
            today = datetime.now(UTC).date()
            if status == "trial" and ends_on and (ends_on - today).days <= 7:
                out["subscription"] = {"state": "trial_ending", "ends_on": str(ends_on), "days": (ends_on - today).days}
            elif status in ("grace", "expired", "cancelled"):
                out["subscription"] = {
                    "state": status,
                    "grace_until": str(grace_until) if grace_until else None,
                    "pay_url": "/admin/billing",
                }
    with contextlib.suppress(Exception):
        raw = await redis_client.get(f"outage:{inst}")
        if raw:
            out["outage"] = json.loads(raw)
    with contextlib.suppress(Exception):
        cap = await redis_client.get(f"apicap:{inst}")
        if cap:
            used = int(await redis_client.get(f"api:{inst}:{datetime.now(UTC):%Y%m%d}") or 0)
            if used >= int(cap) * 0.9:
                out["api_cap"] = {"cap": int(cap), "used": used, "exceeded": used > int(cap)}
    with contextlib.suppress(Exception):
        from app.services.saas.announcement_service import AnnouncementService

        out["announcements"] = len(await AnnouncementService(db, principal).active())
    return out
