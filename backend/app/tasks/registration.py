"""Registration tasks — Prompts/09 §09.7.

Jobs (run as the requesting user): ``jobs.offerings.bulk_from_curriculum``, ``jobs.offerings.roster_export``,
``jobs.registration.bulk_register``, ``jobs.elective.allocate``. Beat (per institution with the feature on):
``registration.window_status`` (5 min), ``registration.lock_windows`` (hourly), ``waitlist.expire`` (hourly) and
``registration.reminders`` (daily 08:30).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.admissions import _progress_fn
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal


@celery.task(name="jobs.offerings.bulk_from_curriculum", queue="reports")
@job("offerings.bulk_from_curriculum", queue="reports")
async def offerings_bulk(ctx: JobContext, db: Any, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.schemas.offerings import BulkFromCurriculumRequest
    from app.services.registration.offering_service import OfferingService

    principal = await _principal(db, ctx)
    out = await OfferingService(db, principal).bulk_from_curriculum(
        BulkFromCurriculumRequest.model_validate(body), dry_run=False, progress=await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{out.to_create} offering(s) created")
    return out.model_dump(mode="json", exclude={"items"})


@celery.task(name="jobs.offerings.roster_export", queue="reports")
@job("offerings.roster_export", queue="reports")
async def offerings_roster_export(ctx: JobContext, db: Any, offering_id: str, **_: Any) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.registration.offering_service import OfferingService

    principal = await _principal(db, ctx)
    content = await OfferingService(db, principal).roster_xlsx(uuid.UUID(offering_id))
    key = build_key(ctx.institution_id or "platform", "rosters", f"roster-{offering_id[:8]}.xlsx")
    await storage.put(key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    await ctx.progress(db, 100, "Roster ready")
    return {"result_url": storage.signed_url(key, 24 * 3600), "bytes": len(content)}


@celery.task(name="jobs.registration.bulk_register", queue="reports")
@job("registration.bulk_register", queue="reports")
async def registration_bulk(ctx: JobContext, db: Any, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.schemas.registration import BulkRegisterRequest
    from app.services.registration.registration_service import RegistrationService

    principal = await _principal(db, ctx)
    out = await RegistrationService(db, principal).bulk_register(
        BulkRegisterRequest.model_validate(body), await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{out.registrations_approved} registered, {len(out.shortfalls)} shortfall(s)")
    return out.model_dump(mode="json")


@celery.task(name="jobs.elective.allocate", queue="reports")
@job("elective.allocate", queue="reports")
async def elective_allocate(
    ctx: JobContext, db: Any, basket_id: str, term_id: str, mode: str | None = None, seed: int | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.registration.elective_service import ElectiveService

    principal = await _principal(db, ctx)
    out = await ElectiveService(db, principal).allocate(
        uuid.UUID(basket_id),
        uuid.UUID(term_id),
        mode,
        dry_run=False,
        seed=seed,
        job_id=ctx.job_id,
        progress=await _progress_fn(ctx, db),
    )
    await ctx.progress(db, 100, f"{out.allocated} allocated, {out.unallocated} manual")
    return out.model_dump(mode="json", exclude={"results"})


# ---- Beat ------------------------------------------------------------------------------------------------------------
def _beat(feature: str, label: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.registration.offering_service import WindowService
        from app.services.registration.registration_service import RegistrationService

        if method == "tick":
            return await WindowService(db, None, institution_id=iid).tick()
        svc = RegistrationService(db, None, institution_id=iid)
        return int(await getattr(svc, method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.registration.window_status", queue="scheduled")
def window_status() -> dict[str, int]:
    return _beat("registration.core", "registration_window_status", "tick")


@celery.task(name="beat.registration.lock_windows", queue="scheduled")
def lock_windows() -> dict[str, int]:
    return _beat("registration.core", "registration_lock_windows", "lock_due")


@celery.task(name="beat.waitlist.expire", queue="scheduled")
def waitlist_expire() -> dict[str, int]:
    return _beat("registration.waitlist", "waitlist_expire", "expire_waitlists")


@celery.task(name="beat.registration.reminders", queue="scheduled")
def reminders() -> dict[str, int]:
    return _beat("registration.core", "registration_reminders", "reminders")
