"""Placement, internships & training tasks — Prompts/28 §28.7.

Jobs: ``placement.publish_drive`` (eligible list + notifications), ``placement.shortlist_import``,
``placement.round_results_import``, ``placement.resume_render``, ``placement.stats_export``, ``placement.nirf_sheet``,
``internship.noc_batch``, ``training.attendance_import``. Beat: ``placement.deadline_close`` (hourly),
``placement.joining_followup`` (weekly), ``placement.offer_reminders`` (daily), ``placement.blacklist_expiry`` (daily),
``training.session_reminders`` (daily). Consumers: ``discipline.sanction_applied`` (``debar_placement`` → blacklist the
student's placement profile), ``achievement.verified`` (make sure the profile exists — achievements are read live),
``results.published`` (re-evaluate open drives when ``placement.reevaluate_on_results``), ``student.graduated``
(accepted offer → ``placement.alumni_employment`` for Phase 29).
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

    key = build_key(principal.institution_id, "placement", name)
    storage = get_storage()
    await storage.put(key, content, mime)
    return storage.signed_url(key)


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.placement.publish_drive", queue="reports")
@job("placement.publish_drive", queue="reports")
async def publish_drive(ctx: JobContext, db: Any, drive_id: str, **_: Any) -> dict[str, Any]:
    from app.services.placement.drive_service import DriveService

    principal = await _principal(db, ctx)
    svc = DriveService(db, principal)
    n = await svc.publish_effects(await svc.drive(uuid.UUID(drive_id)))
    await ctx.progress(db, 100, f"{n} notified")
    return {"notified": n}


@celery.task(name="jobs.placement.shortlist_import", queue="reports")
@job("placement.shortlist_import", queue="reports")
async def shortlist_import(
    ctx: JobContext, db: Any, drive_id: str, rows: list[dict[str, Any]], **_: Any
) -> dict[str, Any]:
    from app.schemas.placement import PlcShortlistBulk
    from app.services.placement.drive_service import DriveService

    principal = await _principal(db, ctx)
    out = await DriveService(db, principal).shortlist(
        uuid.UUID(drive_id), PlcShortlistBulk.model_validate({"rows": rows})
    )
    return out.model_dump(mode="json")


@celery.task(name="jobs.placement.round_results_import", queue="reports")
@job("placement.round_results_import", queue="reports")
async def round_results_import(
    ctx: JobContext, db: Any, round_id: str, rows: list[dict[str, Any]], final: bool = False, **_: Any
) -> dict[str, Any]:
    from app.schemas.placement import PlcRoundResultsBulk
    from app.services.placement.drive_service import DriveService

    principal = await _principal(db, ctx)
    out = await DriveService(db, principal).round_results(
        uuid.UUID(round_id), PlcRoundResultsBulk.model_validate({"rows": rows, "final": final})
    )
    return out.model_dump(mode="json")


@celery.task(name="jobs.placement.resume_render", queue="reports")
@job("placement.resume_render", queue="reports")
async def resume_render(ctx: JobContext, db: Any, template_key: str = "resume_classic", **_: Any) -> dict[str, Any]:
    from app.schemas.placement import PlcResumeRender
    from app.services.placement.profile_service import ProfileService

    principal = await _principal(db, ctx)
    return await ProfileService(db, principal).render_resume(PlcResumeRender(template_key=template_key))  # type: ignore[arg-type]


@celery.task(name="jobs.placement.stats_export", queue="reports")
@job("placement.stats_export", queue="reports")
async def stats_export(ctx: JobContext, db: Any, kind: str = "offers", **_: Any) -> dict[str, Any]:
    from app.services.placement.stats_service import StatsService

    principal = await _principal(db, ctx)
    content = await StatsService(db, principal).report(kind)
    url = await _upload(principal, f"placement-{kind}.xlsx", content)
    await ctx.progress(db, 100, "exported")
    return {"result_url": url}


@celery.task(name="jobs.placement.nirf_sheet", queue="reports")
@job("placement.nirf_sheet", queue="reports")
async def nirf_sheet(
    ctx: JobContext, db: Any, batch_id: str | None = None, year: int | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.placement.stats_service import StatsService

    principal = await _principal(db, ctx)
    svc = StatsService(db, principal)
    content = await svc.nirf_sheet(uuid.UUID(batch_id) if batch_id else None)
    await svc.publish(uuid.UUID(batch_id) if batch_id else None)
    url = await _upload(principal, f"nirf-placement-{year or date.today().year}.xlsx", content)
    await ctx.progress(db, 100, "exported")
    return {"result_url": url}


@celery.task(name="jobs.internship.noc_batch", queue="reports")
@job("internship.noc_batch", queue="reports")
async def noc_batch(ctx: JobContext, db: Any, internship_ids: list[str], **_: Any) -> dict[str, Any]:
    from app.services.placement.internship_service import InternshipService

    principal = await _principal(db, ctx)
    n = await InternshipService(db, principal).noc_batch([uuid.UUID(i) for i in internship_ids])
    await ctx.progress(db, 100, f"{n} NOC issued")
    return {"issued": n}


@celery.task(name="jobs.training.attendance_import", queue="reports")
@job("training.attendance_import", queue="reports")
async def attendance_import(
    ctx: JobContext, db: Any, program_id: str, rows: list[dict[str, Any]], **_: Any
) -> dict[str, Any]:
    from app.schemas.placement import TrnAttendanceBulk
    from app.services.placement.training_service import TrainingService

    principal = await _principal(db, ctx)
    out = await TrainingService(db, principal).attendance(
        uuid.UUID(program_id), TrnAttendanceBulk.model_validate({"rows": rows})
    )
    return out.model_dump(mode="json")


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, path: str, cls: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.placement.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.placement.deadline_close", queue="scheduled")
def deadline_close() -> dict[str, int]:
    return _beat("placement_deadline_close", "placement.core", "drive_service", "DriveService", "deadline_close")


@celery.task(name="beat.placement.joining_followup", queue="scheduled")
def joining_followup() -> dict[str, int]:
    return _beat("placement_joining_followup", "placement.core", "offer_service", "OfferService", "joining_followup")


@celery.task(name="beat.placement.offer_reminders", queue="scheduled")
def offer_reminders() -> dict[str, int]:
    return _beat("placement_offer_reminders", "placement.core", "offer_service", "OfferService", "offer_reminders")


@celery.task(name="beat.placement.blacklist_expiry", queue="scheduled")
def blacklist_expiry() -> dict[str, int]:
    return _beat("placement_blacklist_expiry", "placement.core", "offer_service", "OfferService", "blacklist_expiry")


@celery.task(name="beat.training.session_reminders", queue="scheduled")
def session_reminders() -> dict[str, int]:
    return _beat(
        "training_session_reminders", "placement.training", "training_service", "TrainingService", "session_reminders"
    )


# ---- consumers ------------------------------------------------------------------------------------------------------------
async def _enabled(event: dict[str, Any], key: str) -> uuid.UUID | None:
    from app.core.features import is_enabled

    inst = event.get("institution_id")
    if not inst:
        return None
    iid = uuid.UUID(str(inst))
    return iid if await is_enabled(iid, key) else None


@consumer("placement.debar_from_discipline", events=["discipline.sanction_applied"])
async def debar_from_discipline(db: Any, event: dict[str, Any]) -> None:
    p = event.get("payload") or {}
    if p.get("type") != "debar_placement" or p.get("subject_type") != "student" or p.get("status") == "failed":
        return
    iid = await _enabled(event, "placement.core")
    if iid is None or not p.get("subject_id"):
        return
    from app.services.placement.offer_service import OfferService

    await OfferService(db, None, institution_id=iid).debar_from_discipline(
        uuid.UUID(str(p["subject_id"])), p.get("case_id"), p.get("to_on") or p.get("until")
    )


@consumer("placement.achievement_profile", events=["achievement.verified"])
async def achievement_profile(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "placement.core")
    p = event.get("payload") or {}
    eid = p.get("enrollment_id") or p.get("student_program_enrollment_id")
    if iid is None or not eid:
        return
    from app.services.placement.profile_service import ProfileService

    await ProfileService(db, None, institution_id=iid).ensure_profiles([uuid.UUID(str(eid))])


@consumer("placement.reevaluate_on_results", events=["results.published"])
async def reevaluate_on_results(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "placement.core")
    if iid is None:
        return
    from sqlalchemy import select

    from app.models.placement import PlacementDrive
    from app.services.placement.drive_service import DriveService

    svc = DriveService(db, None, institution_id=iid)
    if not await svc.setting("placement", "reevaluate_on_results"):
        return
    for d in (
        await db.execute(
            select(PlacementDrive).where(
                PlacementDrive.institution_id == iid, PlacementDrive.status.in_(("open", "closed"))
            )
        )
    ).scalars():
        await svc.re_evaluate(d.id)


@consumer("placement.alumni_employment", events=["student.graduated"])
async def alumni_employment(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "placement.core")
    p = event.get("payload") or {}
    eid = p.get("enrollment_id") or p.get("student_program_enrollment_id")
    if iid is None or not eid:
        return
    from sqlalchemy import select

    from app.models.placement import Company, DriveApplication, PlacementOffer
    from app.services.placement.common import PlacementBase

    rows = (
        await db.execute(
            select(PlacementOffer, Company.name)
            .join(DriveApplication, DriveApplication.id == PlacementOffer.application_id)
            .join(Company, Company.id == PlacementOffer.company_id)
            .where(
                DriveApplication.student_program_enrollment_id == uuid.UUID(str(eid)),
                PlacementOffer.status.in_(("accepted", "joined")),
            )
            .order_by(PlacementOffer.ctc_paise.desc())
        )
    ).all()
    if not rows:
        return
    o, company = rows[0]
    await PlacementBase(db, None, institution_id=iid)._emit(
        "placement.alumni_employment",
        {
            "enrollment_id": str(eid),
            "company": company,
            "role": o.role,
            "ctc_paise": o.ctc_paise,
            "offer_id": str(o.id),
        },
        "placement_offer",
        o.id,
    )
