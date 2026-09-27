"""Tasks on the ``notifications`` queue (names ``notifications.<task>`` route here via ``task_routes``).

Phase 02 adds the three auth messages the login flows need: OTP by SMS, OTP by email and the password-reset link.
They go through the **adapter registry** (``app/integrations/registry.py``), which answers with the ``mock`` provider
unless a real one is configured — Phase 04 replaces the bodies with the templated notification pipeline
(``notification_templates`` + ``message_logs``) and Phase 41 wires the live providers.
"""

import asyncio
from typing import Any

import structlog

from app.core.config import settings
from app.tasks.celery_app import celery

log = structlog.get_logger()


@celery.task(name="notifications.send_sms_otp", queue="notifications")
def send_sms_otp(
    institution_id: str | None = None, destination: str = "", code: str = "", ttl: int = 300
) -> dict[str, Any]:
    return asyncio.run(_send("sms", settings.SMS_PROVIDER, destination, _otp_text(code, ttl)))


@celery.task(name="notifications.send_email_otp", queue="emails")
def send_email_otp(
    institution_id: str | None = None, destination: str = "", code: str = "", ttl: int = 300
) -> dict[str, Any]:
    return asyncio.run(
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
    return asyncio.run(_send("email", settings.EMAIL_PROVIDER, email, body, subject="Reset your password"))


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
