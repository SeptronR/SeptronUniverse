"""Alumni, endowments & fundraising tasks — Prompts/29 §29.7.

Jobs: ``alumni.import``, ``alumni.claim_links_batch``, ``alumni.engagement_recompute``, ``donation.receipt_80g``,
``fundraising.10bd_statement``, ``alumni.directory_export``, ``alumni.profile_update_campaign``. Beat:
``alumni.engagement_nightly``, ``alumni.jobs_expiry`` (daily), ``campaign.milestone_check`` (hourly),
``alumni.pledge_reminders`` (weekly), ``alumni.annual_update_campaign`` (yearly). Consumers: ``student.graduated``
(profile auto-create + ``alumni`` role), ``placement.alumni_employment`` (Phase 28 accepted / joined offer → current
employment), ``fees.payment_received(source_type=donation)`` (online donation settled), ``event.registered`` /
``event.attended`` / ``event.completed`` (registrations count sync), ``survey.closed`` (alumni survey engagement).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _upload(principal: Any, name: str, content: bytes, mime: str = XLSX) -> str:
    from app.core.files import build_key, get_storage

    key = build_key(principal.institution_id, "alumni", name)
    storage = get_storage()
    await storage.put(key, content, mime)
    return storage.signed_url(key)


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.alumni.import", queue="reports")
@job("alumni.import", queue="reports")
async def alumni_import(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.alumni import AlumniImport
    from app.services.alumni.profile_service import ProfileService

    principal = await _principal(db, ctx)
    body = AlumniImport.model_validate({k: v for k, v in params.items() if k in AlumniImport.model_fields})
    out = await ProfileService(db, principal).import_rows(body)
    await ctx.progress(db, 100, f"{out.created + out.linked} imported")
    return out.model_dump(mode="json")


@celery.task(name="jobs.alumni.claim_links_batch", queue="reports")
@job("alumni.claim_links_batch", queue="reports")
async def claim_links_batch(ctx: JobContext, db: Any, ids: list[str] | None = None, **_: Any) -> dict[str, Any]:
    from app.services.alumni.profile_service import ProfileService

    principal = await _principal(db, ctx)
    n = await ProfileService(db, principal).claim_links([uuid.UUID(i) for i in ids or []] or None)
    await ctx.progress(db, 100, f"{n} links sent")
    return {"sent": n}


@celery.task(name="jobs.alumni.engagement_recompute", queue="reports")
@job("alumni.engagement_recompute", queue="reports")
async def engagement_recompute(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.alumni.profile_service import ProfileService

    principal = await _principal(db, ctx)
    return {"profiles": await ProfileService(db, principal).recompute_all()}


@celery.task(name="jobs.donation.receipt_80g", queue="reports")
@job("donation.receipt_80g", queue="reports")
async def receipt_80g(ctx: JobContext, db: Any, donation_ids: list[str], **_: Any) -> dict[str, Any]:
    from app.core.errors import APIError
    from app.services.alumni.fundraising_service import FundraisingService

    principal = await _principal(db, ctx)
    svc = FundraisingService(db, principal)
    issued, failed = 0, []
    for did in donation_ids:
        try:
            await svc.issue_receipt(uuid.UUID(did))
            issued += 1
        except APIError as exc:
            failed.append({"donation_id": did, "error": getattr(exc, "message", str(exc))})
    return {"issued": issued, "failed": failed}


@celery.task(name="jobs.fundraising.10bd_statement", queue="reports")
@job("fundraising.10bd_statement", queue="reports")
async def statement_10bd(ctx: JobContext, db: Any, fy: str, **_: Any) -> dict[str, Any]:
    from app.services.alumni.fundraising_service import FundraisingService

    principal = await _principal(db, ctx)
    content = await FundraisingService(db, principal).statement_10bd(fy)
    url = await _upload(principal, f"10bd-{fy}.xlsx", content)
    await ctx.progress(db, 100, "exported")
    return {"result_url": url}


@celery.task(name="jobs.alumni.directory_export", queue="reports")
@job("alumni.directory_export", queue="reports")
async def directory_export(ctx: JobContext, db: Any, scope: str | None = None, **_: Any) -> dict[str, Any]:
    import io

    from openpyxl import Workbook

    from app.services.alumni.profile_service import ProfileService

    principal = await _principal(db, ctx)
    rows = await ProfileService(db, principal).export_rows(scope)
    wb = Workbook()
    ws = wb.active
    ws.title = "Alumni"
    cols = list(rows[0].keys()) if rows else ["registration_number", "name"]
    ws.append(cols)
    for r in rows:
        ws.append([r.get(c) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    url = await _upload(principal, "alumni-export.xlsx", buf.getvalue())
    await ctx.progress(db, 100, f"{len(rows)} rows")
    return {"result_url": url, "rows": len(rows)}


@celery.task(name="jobs.alumni.profile_update_campaign", queue="reports")
@job("alumni.profile_update_campaign", queue="reports")
async def profile_update_campaign(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.alumni.profile_service import ProfileService

    principal = await _principal(db, ctx)
    return {"notified": await ProfileService(db, principal).update_campaign()}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, path: str, cls: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.alumni.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.alumni.engagement_nightly", queue="scheduled")
def engagement_nightly() -> dict[str, int]:
    return _beat("alumni_engagement_nightly", "alumni.core", "profile_service", "ProfileService", "recompute_all")


@celery.task(name="beat.alumni.jobs_expiry", queue="scheduled")
def jobs_expiry() -> dict[str, int]:
    return _beat("alumni_jobs_expiry", "alumni.jobs_board", "jobs_service", "JobsService", "expire")


@celery.task(name="beat.campaign.milestone_check", queue="scheduled")
def milestone_check() -> dict[str, int]:
    return _beat(
        "campaign_milestone_check", "alumni.fundraising", "fundraising_service", "FundraisingService", "milestone_check"
    )


@celery.task(name="beat.alumni.pledge_reminders", queue="scheduled")
def pledge_reminders() -> dict[str, int]:
    return _beat(
        "alumni_pledge_reminders", "alumni.fundraising", "fundraising_service", "FundraisingService", "pledge_reminders"
    )


@celery.task(name="beat.alumni.annual_update_campaign", queue="scheduled")
def annual_update_campaign() -> dict[str, int]:
    return _beat("alumni_annual_update", "alumni.portal", "profile_service", "ProfileService", "update_campaign")


# ---- consumers ------------------------------------------------------------------------------------------------------------
async def _enabled(event: dict[str, Any], key: str) -> uuid.UUID | None:
    from app.core.features import is_enabled

    inst = event.get("institution_id")
    if not inst:
        return None
    iid = uuid.UUID(str(inst))
    return iid if await is_enabled(iid, key) else None


@consumer("alumni.profile_on_graduation", events=["student.graduated"])
async def on_graduated(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "alumni.core")
    p = event.get("payload") or {}
    if iid is None or not p.get("student_id"):
        return
    from app.services.alumni.profile_service import ProfileService

    eid = p.get("enrollment_id")
    await ProfileService(db, None, institution_id=iid).on_graduated(
        uuid.UUID(str(p["student_id"])), uuid.UUID(str(eid)) if eid else None
    )


@consumer("alumni.employment_from_placement", events=["placement.alumni_employment"])
async def on_employment(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "alumni.core")
    p = event.get("payload") or {}
    if iid is None or not p.get("enrollment_id"):
        return
    from app.services.alumni.profile_service import ProfileService

    await ProfileService(db, None, institution_id=iid).on_employment(uuid.UUID(str(p["enrollment_id"])), p)


@consumer("alumni.donation_settled", events=["fees.payment_received"])
async def on_payment(db: Any, event: dict[str, Any]) -> None:
    p = event.get("payload") or {}
    if p.get("source_type") != "donation":
        return
    iid = await _enabled(event, "alumni.fundraising")
    if iid is None:
        return
    from app.services.alumni.fundraising_service import FundraisingService

    await FundraisingService(db, None, institution_id=iid).on_payment(p)


@consumer("alumni.event_counts", events=["event.registered", "event.attended", "event.completed"])
async def on_event(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "alumni.core")
    p = event.get("payload") or {}
    if iid is None or not p.get("event_id"):
        return
    from app.services.alumni.event_service import AlumniEventService

    await AlumniEventService(db, None, institution_id=iid).sync_counts(uuid.UUID(str(p["event_id"])))


@consumer("alumni.survey_engagement", events=["survey.closed"])
async def on_survey(db: Any, event: dict[str, Any]) -> None:
    """Closed alumni surveys count towards engagement (responses are anonymous, so invited alumni are credited)."""
    iid = await _enabled(event, "alumni.core")
    p = event.get("payload") or {}
    if iid is None or not p.get("survey_id"):
        return
    from sqlalchemy import select

    from app.models.obe_attainment import FeedbackSurvey

    s = (
        await db.execute(select(FeedbackSurvey).where(FeedbackSurvey.id == uuid.UUID(str(p["survey_id"]))))
    ).scalar_one_or_none()
    if s is None or s.survey_type != "alumni":
        return
    from app.services.alumni.profile_service import ProfileService

    await ProfileService(db, None, institution_id=iid).survey_credit()
