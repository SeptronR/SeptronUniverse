"""Timetable tasks — Prompts/10 §10.7.

Jobs (run as the requesting user): ``jobs.timetable.generate_sessions`` (publication above the inline limit),
``jobs.timetable.auto_generate`` ({timetable.auto_generate}), ``jobs.timetable.export`` (CSV of a timetable's entries).
Consumers: ``substitution.auto_request`` ← ``leave.approved`` and ``substitution.leave_withdraw`` ← ``leave.cancelled``
({timetable.substitutions}); ``sessions.regenerate_future`` ← ``holiday.changed``. Phase 11 subscribes to
``timetable.published`` (``attendance.sessions_ready``). Beat: ``sessions.mark_missed`` (nightly 23:40).
"""

import csv
import io
import uuid
from datetime import date
from typing import Any

import structlog

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.admissions import _progress_fn
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer

log = structlog.get_logger()


# ---- jobs --------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.timetable.generate_sessions", queue="reports")
@job("timetable.generate_sessions", queue="reports")
async def generate_sessions(
    ctx: JobContext, db: Any, timetable_id: str, effective_from: str, old_entry_ids: list[str] | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.timetable.timetable_service import TimetableService

    principal = await _principal(db, ctx)
    svc = TimetableService(db, principal)
    tt = await svc.tts.get_one(uuid.UUID(timetable_id))
    created, removed, kept = await svc.generate_sessions(
        tt,
        date.fromisoformat(effective_from),
        [uuid.UUID(i) for i in old_entry_ids or []],
        progress=await _progress_fn(ctx, db),
    )
    await ctx.progress(db, 100, f"{created} session(s) generated")
    return {"created": created, "removed": removed, "preserved": kept}


@celery.task(name="jobs.timetable.auto_generate", queue="reports")
@job("timetable.auto_generate", queue="reports")
async def auto_generate(ctx: JobContext, db: Any, timetable_id: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.schemas.timetable import AutoGenerateRequest
    from app.services.timetable.auto_generate_service import AutoGenerateService

    principal = await _principal(db, ctx)
    out = await AutoGenerateService(db, principal).run(
        uuid.UUID(timetable_id),
        AutoGenerateRequest.model_validate(body),
        dry_run=False,
        progress=await _progress_fn(ctx, db),
    )
    await ctx.progress(db, 100, f"{out['placed']} placed, {len(out['unplaced'])} offering(s) short")
    return {k: v for k, v in out.items() if k != "entries"}


@celery.task(name="jobs.timetable.export", queue="reports")
@job("timetable.export", queue="reports")
async def export(ctx: JobContext, db: Any, timetable_id: str, **_: Any) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.timetable.timetable_service import TimetableService

    principal = await _principal(db, ctx)
    tt = await TimetableService(db, principal).get(uuid.UUID(timetable_id))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["day", "slot", "start", "end", "course", "title", "section", "room", "faculty", "type", "weeks", "span"]
    )
    for e in sorted(tt.entries, key=lambda e: (e.day_of_week, e.start_time or 0)):
        w.writerow(
            [
                e.day_of_week,
                e.slot_name,
                e.start_time,
                e.end_time,
                e.course_code,
                e.course_title,
                e.section_name,
                e.room_code,
                e.staff_name,
                e.session_type,
                e.week_pattern,
                e.slot_span,
            ]
        )
    content = buf.getvalue().encode("utf-8-sig")
    key = build_key(ctx.institution_id or "platform", "timetables", f"timetable-{timetable_id[:8]}-v{tt.version}.csv")
    await storage.put(key, content, "text/csv")
    await ctx.progress(db, 100, "Timetable export ready")
    return {"result_url": storage.signed_url(key, 24 * 3600), "bytes": len(content), "entries": len(tt.entries)}


# ---- consumers ------------------------------------------------------------------------------------------------------------
async def _feature_on(event: dict[str, Any], key: str) -> bool:
    from app.core.features import is_enabled

    iid = event.get("institution_id")
    return bool(iid) and await is_enabled(iid, key)


@consumer("substitution.auto_request", events=["leave.approved"])
async def substitution_auto_request(db: Any, event: dict[str, Any]) -> None:
    from app.services.timetable.substitution_service import SubstitutionService

    if not await _feature_on(event, "timetable.substitutions"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    n = await SubstitutionService(db, None, institution_id=iid).from_leave(event.get("payload") or {})
    log.info("substitution_auto_requested", institution_id=str(iid), created=n)


@consumer("substitution.leave_withdraw", events=["leave.cancelled"])
async def substitution_leave_withdraw(db: Any, event: dict[str, Any]) -> None:
    from app.services.timetable.substitution_service import SubstitutionService

    if not await _feature_on(event, "timetable.substitutions"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    n = await SubstitutionService(db, None, institution_id=iid).leave_cancelled(event.get("payload") or {})
    log.info("substitution_leave_withdrawn", institution_id=str(iid), withdrawn=n)


@consumer("sessions.regenerate_future", events=["holiday.changed"])
async def sessions_regenerate_future(db: Any, event: dict[str, Any]) -> None:
    from app.services.timetable.timetable_service import TimetableService

    if not await _feature_on(event, "timetable.core"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    dates = [date.fromisoformat(d) for d in (event.get("payload") or {}).get("dates", [])]
    out = await TimetableService(db, None, institution_id=iid).resync_dates(dates)
    log.info("sessions_regenerated", institution_id=str(iid), **out)


# ---- Beat ---------------------------------------------------------------------------------------------------------------------
@celery.task(name="beat.sessions.mark_missed", queue="scheduled")
def mark_missed() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.timetable.session_service import SessionService

        return await SessionService(db, None, institution_id=iid).mark_missed()

    return run_async(_for_institutions("timetable.core", one, "sessions_mark_missed"))
