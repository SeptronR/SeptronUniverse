"""Tasks on the ``notifications`` queue (names ``notifications.<task>`` route here via ``task_routes``).

Phase 02 adds the three auth messages the login flows need: OTP by SMS, OTP by email and the password-reset link.
They go through the **adapter registry** (``app/integrations/registry.py``), which answers with the ``mock`` provider
unless a real one is configured (Phase 41 wires the live providers).

Phase 04 adds the communication core: consumer ``notifications.dispatch`` (``notification.requested``), task
``notifications.deliver`` (one message log), consumer ``notifications.workflow`` (``workflow.*`` → WebSocket inbox
refresh signal) and the Beat bodies ``notifications.retry_failed`` (10 min), ``notifications.digest`` (daily 08:00
institution-agnostic UTC; weekly digests on Mondays) and ``workflow.escalate`` (15 min). The monthly
``message_logs`` partitions come from ``partitions.ensure_next_month`` (Phase 01).
"""

from typing import Any

import structlog

from app.core.aio import run_async
from app.core.config import settings
from app.tasks.celery_app import celery

log = structlog.get_logger()


@celery.task(name="notifications.send_sms_otp", queue="notifications")
def send_sms_otp(
    institution_id: str | None = None, destination: str = "", code: str = "", ttl: int = 300
) -> dict[str, Any]:
    return run_async(_send("sms", settings.SMS_PROVIDER, destination, _otp_text(code, ttl)))


@celery.task(name="notifications.send_email_otp", queue="emails")
def send_email_otp(
    institution_id: str | None = None, destination: str = "", code: str = "", ttl: int = 300
) -> dict[str, Any]:
    return run_async(
        _send("email", settings.EMAIL_PROVIDER, destination, _otp_text(code, ttl), subject="Your sign-in code")
    )


@celery.task(name="notifications.send_password_reset", queue="emails")
def send_password_reset(
    institution_id: str | None = None,
    user_id: str | None = None,
    email: str = "",
    reset_url: str = "",
    ttl_minutes: int = 60,
) -> dict[str, Any]:
    body = (
        f"Someone asked to reset the password of your SeptronUniverse account.\n\n{reset_url}\n\n"
        f"The link is valid for {ttl_minutes} minutes and can be used once. If this was not you, ignore this message."
    )
    return run_async(_send("email", settings.EMAIL_PROVIDER, email, body, subject="Reset your password"))


def _otp_text(code: str, ttl: int) -> str:
    return f"Your SeptronUniverse sign-in code is {code}. It expires in {ttl // 60} minutes."


async def _send(
    capability: str, provider: str, destination: str, body: str, subject: str | None = None
) -> dict[str, Any]:
    from app.integrations.registry import get_adapter

    if not destination:
        return {"status": "skipped", "reason": "no destination"}
    adapter = get_adapter(capability, provider)
    result = await adapter.send(to=destination, body=body, subject=subject)
    log.info("notification_sent", capability=capability, provider=provider, to=destination[:3] + "…")
    return dict(result) if isinstance(result, dict) else {"status": "sent"}


# ---- Phase 04: communication core ----------------------------------------------------------------------------------
from app.tasks.outbox import consumer  # noqa: E402


@consumer("notifications.dispatch", events=["notification.requested"], queue="notifications")
async def dispatch_notification(db: Any, event: dict[str, Any]) -> None:
    """Outbox consumer: recipients → templates → preferences → in-app rows + queued channel messages."""
    from app.services.notifications.dispatcher import Dispatcher

    await Dispatcher(db).dispatch(event)


@celery.task(name="notifications.deliver", queue="notifications", acks_late=True)
def deliver(log_id: str) -> str:
    return run_async(_deliver(log_id))


async def _deliver(log_id: str) -> str:
    import uuid

    from app.db.session import PlatformSessionLocal
    from app.services.notifications.delivery import deliver as deliver_body

    async with PlatformSessionLocal() as db:
        status = await deliver_body(db, uuid.UUID(log_id))
        await db.commit()
    return status


@consumer("notifications.workflow", events=["workflow.*"], queue="notifications")
async def workflow_signal(db: Any, event: dict[str, Any]) -> None:
    """Push an ``approvals`` refresh signal to the requester and the approvers of the instance (inbox badges);
    the human-readable notifications themselves are written by the engine through ``notify_event``."""
    from sqlalchemy import text

    from app.core.ws import publish

    payload = event.get("payload") or {}
    instance_id = payload.get("instance_id")
    if not instance_id:
        return
    rows = (
        await db.execute(
            text(
                "SELECT started_by AS u FROM workflow_instances WHERE id = :i UNION "
                "SELECT approver_user_id FROM workflow_steps WHERE instance_id = :i AND approver_user_id IS NOT NULL UNION "
                "SELECT escalated_to FROM workflow_steps WHERE instance_id = :i AND escalated_to IS NOT NULL"
            ),
            {"i": instance_id},
        )
    ).all()
    for (user_id,) in rows:
        if user_id:
            await publish(
                f"notifications:{user_id}",
                {
                    "type": "approvals.changed",
                    "instance_id": instance_id,
                    "event_type": event.get("event_type"),
                    "status": payload.get("status"),
                },
            )


@celery.task(name="beat.notifications.retry_failed", queue="scheduled")
def retry_failed() -> dict[str, int]:
    return run_async(_platform_job("retry"))


@celery.task(name="beat.notifications.digest", queue="scheduled")
def digest(period: str = "daily") -> dict[str, int]:
    return run_async(_platform_job("digest", period))


@celery.task(name="beat.workflow.escalate", queue="scheduled")
def workflow_escalate() -> dict[str, int]:
    return run_async(_platform_job("escalate"))


async def _platform_job(kind: str, period: str = "daily") -> dict[str, int]:
    from datetime import UTC, datetime

    from app.core.workflow import engine
    from app.db.session import PlatformSessionLocal
    from app.services.notifications.delivery import retry_due, send_digests

    async with PlatformSessionLocal() as db:
        if kind == "retry":
            result = await retry_due(db)
        elif kind == "digest":
            if period == "weekly" and datetime.now(UTC).weekday() != 0:
                return {"digests": 0}
            result = {"digests": await send_digests(db, period)}
        else:
            result = {"escalated": await engine.escalate_due(db)}
        await db.commit()
    log.info(f"beat_{kind}", **result)
    return result
