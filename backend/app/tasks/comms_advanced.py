"""Communication-advanced tasks — Prompts/24 §24.7.

Jobs: ``campaign.send`` (materialise recipients × channels, release the first throttle batch; resumable — rerunning
only flushes), ``comms.analytics_export``. Beat: ``campaign.scheduler`` (every minute — due scheduled campaigns),
``campaign.deferred_quiet_hours_flush`` (every 5 min — next throttle batch / quiet-hours releases, completion),
``bot.session_expiry`` (hourly — 24 h window close, 90-day transcript retention), ``assistant.conversation_retention``
(daily — 30 days), ``comms.provider_health_probe`` (every 5 min).
"""

import uuid
from datetime import date, datetime
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal


@celery.task(name="jobs.campaign.send", queue="notifications")
@job("campaign.send", queue="notifications")
async def campaign_send(ctx: JobContext, db: Any, campaign_id: str, **_: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.comms_advanced import BulkCampaign
    from app.services.comms_advanced.campaign_service import CampaignService

    principal = await _principal(db, ctx)
    c = (
        await db.execute(select(BulkCampaign).where(BulkCampaign.id == uuid.UUID(campaign_id)).with_for_update())
    ).scalar_one()
    out = await CampaignService(db, principal, institution_id=c.institution_id).materialise(c)
    await ctx.progress(db, 100, f"{out.get('rows', 0)} message(s) queued")
    return out


@celery.task(name="jobs.comms.analytics_export", queue="reports")
@job("comms.analytics_export", queue="reports")
async def analytics_export(
    ctx: JobContext, db: Any, date_from: str | None = None, date_to: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.comms_advanced.analytics_service import CommsAnalyticsService

    principal = await _principal(db, ctx)
    out = await CommsAnalyticsService(db, principal).export(
        datetime.fromisoformat(date_from) if date_from else None, datetime.fromisoformat(date_to) if date_to else None
    )
    await ctx.progress(db, 100, "Export ready")
    return out


def _beat(label: str, feature: str, fn: Any) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        return int(await fn(db, iid))

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.campaign.scheduler", queue="scheduled")
def scheduler() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.comms_advanced.campaign_service import CampaignService

        return await CampaignService(db, None, institution_id=iid).scheduler_tick()

    return _beat("campaign_scheduler", "comms.scheduled_sends", fn)


@celery.task(name="beat.campaign.deferred_flush", queue="scheduled")
def deferred_flush() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.comms_advanced.campaign_service import CampaignService

        return await CampaignService(db, None, institution_id=iid).flush_tick()

    return _beat("campaign_deferred_flush", "comms.bulk_campaigns", fn)


@celery.task(name="beat.bot.session_expiry", queue="scheduled")
def bot_session_expiry() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.comms_advanced.bot_service import BotService

        return await BotService(db, None, institution_id=iid).expire_sessions()

    return _beat("bot_session_expiry", "comms.whatsapp_bot", fn)


@celery.task(name="beat.assistant.conversation_retention", queue="scheduled")
def assistant_retention() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.comms_advanced.assistant_service import AssistantService

        return await AssistantService(db, None, institution_id=iid).retention()

    return _beat("assistant_conversation_retention", "comms.ai_assistant", fn)


@celery.task(name="beat.comms.provider_health_probe", queue="scheduled")
def provider_health_probe() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.comms_advanced.analytics_service import CommsAnalyticsService

        return await CommsAnalyticsService(db, None, institution_id=iid).health_probe()

    return _beat("comms_provider_health_probe", "comms.bulk_campaigns", fn)
