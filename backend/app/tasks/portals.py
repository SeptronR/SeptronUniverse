"""Tasks of Phase 39 — Prompts/39 §39.7 (portals, PWA, notification centre).

Beat (UTC crontabs; IST in ``beat.py``): ``notifications.digest_daily`` (02:00 UTC = 07:30 IST — bundles the Phase 04
deferred digest rows and sends the unread-by-category summary), ``notifications.digest_weekly`` (Mondays 02:00 UTC),
``push.prune_expired`` (daily 21:40 UTC = 03:10 IST). Consumers: ``institution.updated`` / ``settings.changed`` →
branding / manifest cache drop + ``pwa.icons_generate``; ``feature_flag.changed`` → portal counts cache untouched
(config is computed per request from the principal's features).
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from app.core.aio import run_async
from app.tasks.celery_app import celery
from app.tasks.outbox import consumer

log = structlog.get_logger()


async def _platform(fn: Any) -> Any:
    from app.db.session import PlatformSessionLocal

    async with PlatformSessionLocal() as db:
        try:
            out = await fn(db)
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            raise


@celery.task(name="beat.notifications.digest_portal", queue="scheduled")
def digest_portal(period: str = "daily") -> dict[str, int]:
    from app.services.notifications.delivery import send_digests
    from app.services.portals.notification_center_service import send_unread_digests

    if period == "weekly" and datetime.now(UTC).weekday() != 0:
        return {"bundled": 0, "summaries": 0}

    async def fn(db: Any) -> dict[str, int]:
        return {"bundled": await send_digests(db, period), "summaries": await send_unread_digests(db, period)}

    out: dict[str, int] = run_async(_platform(fn))
    log.info("beat_notifications_digest_portal", period=period, **out)
    return out


@celery.task(name="beat.push.prune_expired", queue="scheduled")
def push_prune_expired() -> dict[str, int]:
    from app.services.portals.pwa_service import prune_expired

    out = {"pruned": run_async(_platform(prune_expired))}
    log.info("beat_push_prune_expired", **out)
    return out


@celery.task(name="jobs.pwa.icons_generate", queue="default")
def pwa_icons_generate(institution_id: str) -> dict[str, str]:
    """Marks the institution's icon set as generated (the icon route serves the logo; resizing is a Phase 41 item)."""
    from app.services.portals.pwa_service import mark_icons_generated

    run_async(mark_icons_generated(uuid.UUID(institution_id)))
    return {"institution_id": institution_id}


@consumer("portals.branding_cache", events=["institution.updated", "settings.changed"])
async def branding_cache(db: Any, event: dict[str, Any]) -> None:
    from app.services.portals.portal_service import drop_branding

    inst = event.get("institution_id")
    if not inst:
        return
    await drop_branding(inst)
    if event.get("event_type") == "institution.updated":
        pwa_icons_generate.delay(str(inst))
