"""Auth / entitlement tasks — Prompts/02 §02.7.

Beat: ``auth.cleanup_sessions`` (hourly — expire and purge sessions, drop used reset tokens),
``auth.expire_time_boxed_accounts`` (daily — revoke the sessions of accounts past ``valid_to`` and emit
``user.deactivated``), ``subscriptions.reminders`` (daily — ``subscription.expiring`` 30/7/1/0 days ahead),
``usage.meter`` (monthly — upsert ``usage_meters`` per tenant).
Consumers: ``features.invalidate_cache`` ← ``feature_flag.changed`` (drops the Redis set in **this** process so
workers see toggles immediately).
Jobs: ``jobs.users.credential_sheet`` — generates temporary passwords for the listed users, sets
``must_change_password``, writes an XLSX to the tenant's storage and records ``credential_sheets.file_url``.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select, text

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.outbox import consumer

log = structlog.get_logger()


# ---- Beat jobs -----------------------------------------------------------------------------------------------
@celery.task(name="beat.auth.cleanup_sessions", queue="scheduled")
def cleanup_sessions() -> dict[str, int]:
    return run_async(_cleanup_sessions())


async def _cleanup_sessions() -> dict[str, int]:
    from app.db.session import PlatformSessionLocal
    from app.repositories.session_repository import PasswordResetRepository, SessionRepository

    now = datetime.now(UTC)
    async with PlatformSessionLocal() as db:
        expired, purged = await SessionRepository(db).cleanup(now, now - timedelta(days=30))
        tokens = await PasswordResetRepository(db).purge_expired(now)
        await db.commit()
    result = {"expired": expired, "purged": purged, "reset_tokens_purged": tokens}
    if any(result.values()):
        log.info("auth_cleanup_sessions", **result)
    return result


@celery.task(name="beat.auth.expire_time_boxed_accounts", queue="scheduled")
def expire_time_boxed_accounts() -> dict[str, int]:
    return run_async(_expire_time_boxed_accounts())


async def _expire_time_boxed_accounts() -> dict[str, int]:
    from app.core import events
    from app.db.session import PlatformSessionLocal
    from app.models.platform import User
    from app.repositories.session_repository import SessionRepository

    now = datetime.now(UTC)
    async with PlatformSessionLocal() as db:
        revoked = await SessionRepository(db).revoke_expired_accounts(now)
        rows = (
            await db.execute(
                select(User.id, User.institution_id).where(
                    User.valid_to.is_not(None), User.valid_to < now, User.is_active.is_(True)
                )
            )
        ).all()
        for user_id, institution_id in rows:
            await events.emit(
                db,
                institution_id=institution_id,
                event_type="user.deactivated",
                payload={"user_id": str(user_id), "reason": "valid_to_passed"},
                aggregate_type="user",
                aggregate_id=user_id,
            )
        await db.commit()
    return {"sessions_revoked": revoked, "accounts_expired": len(rows)}


@celery.task(name="beat.subscriptions.reminders", queue="scheduled")
def subscription_reminders() -> int:
    return run_async(_subscription_reminders())


async def _subscription_reminders() -> int:
    from app.db.session import PlatformSessionLocal
    from app.services.entitlement_service import EntitlementService

    async with PlatformSessionLocal() as db:
        n = await EntitlementService(db).reminders(date.today())
        await db.commit()
    return n


@celery.task(name="beat.usage.meter", queue="scheduled")
def usage_meter() -> dict[str, Any]:
    return run_async(_usage_meter())


async def _usage_meter() -> dict[str, Any]:
    from app.db.session import PlatformSessionLocal
    from app.services.entitlement_service import EntitlementService

    today = date.today()
    period = today.replace(day=1)
    async with PlatformSessionLocal() as db:
        ids = (await db.execute(text("SELECT id FROM institutions WHERE deleted_at IS NULL"))).scalars().all()
        service = EntitlementService(db)
        for institution_id in ids:
            await service.meter(uuid.UUID(str(institution_id)), period)
        await db.commit()
    return {"institutions": len(ids), "period": period.isoformat()}


# ---- consumers ----------------------------------------------------------------------------------------------
@consumer("features.invalidate_cache", events=["feature_flag.changed"])
async def invalidate_feature_cache(db: Any, event: dict[str, Any]) -> None:
    """Drop the cached effective-feature set of the tenant in this process (Redis key ``features:{institution}``)."""
    from app.core.features import invalidate_features_cache

    institution_id = event.get("institution_id") or (event.get("payload") or {}).get("institution_id")
    if institution_id:
        await invalidate_features_cache(institution_id)
        log.info("features_cache_invalidated", institution_id=str(institution_id))


# ---- jobs ---------------------------------------------------------------------------------------------------
@celery.task(name="jobs.users.credential_sheet", queue="documents")
@job("users.credential_sheet", queue="documents")
async def credential_sheet_job(
    ctx: JobContext, db: Any, sheet_id: str, user_ids: list[str], audience: str = "staff", **_: Any
) -> dict[str, Any]:
    """Temporary passwords + XLSX for a batch of users (Prompts/02 §02.6 rule 5)."""
    from app.core.files import build_key, storage
    from app.core.security import generate_temp_password, hash_password
    from app.models.platform import CredentialSheet, User

    rows: list[tuple[str, str, str]] = []
    total = max(len(user_ids), 1)
    for i, raw_id in enumerate(user_ids, start=1):
        user = (await db.execute(select(User).where(User.id == uuid.UUID(raw_id)))).scalar_one_or_none()
        if user is None:
            continue
        password = generate_temp_password()
        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.password_changed_at = datetime.now(UTC)
        rows.append((user.display_name or user.username, user.username, password))
        if i % 25 == 0 or i == total:
            await ctx.progress(db, int(i * 90 / total), f"{i}/{total} credentials generated")
    await db.flush()
    content = _xlsx(rows, audience)
    key = build_key(ctx.institution_id or "platform", "credential-sheets", f"{audience}.xlsx")
    await storage.put(key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    url = storage.signed_url(key)
    sheet = (
        await db.execute(select(CredentialSheet).where(CredentialSheet.id == uuid.UUID(sheet_id)))
    ).scalar_one_or_none()
    if sheet is not None:
        sheet.file_url = url
    await ctx.progress(db, 100, f"{len(rows)} credentials ready")
    return {"result_url": url, "count": len(rows), "audience": audience}


def _xlsx(rows: list[tuple[str, str, str]], audience: str) -> bytes:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = audience[:30]
    ws.append(["Name", "Username", "Temporary password"])
    for name, username, password in rows:
        ws.append([name, username, password])
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 20
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
