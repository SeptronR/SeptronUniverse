"""Attendance tasks — Prompts/11 §11.7.

Jobs (run as the requesting user): ``jobs.attendance.recompute_summaries`` (a whole term), ``jobs.eligibility.compute``
(versioned snapshot), ``jobs.attendance.export`` (session × student register CSV), ``jobs.attendance.detention_export``
(XLSX). Consumers: ``attendance.sessions_ready`` ← ``timetable.published`` and ``attendance.session_od`` ←
``session.created`` (approved OD marks reach newly generated sessions), ``attendance.condonation_paid`` ←
``fees.payment_received`` (Phase 12, ``source_type='condonation'``). Beat: ``attendance.auto_finalize`` (nightly
00:30), ``attendance.missing_sessions_digest`` (18:00), ``attendance.checkpoints`` (07:00), ``attendance.streak_alerts``
(nightly 23:55 — term summaries recomputed after the day's marking, ``student_term_records.attendance_pct`` refreshed).
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
@celery.task(name="jobs.attendance.recompute_summaries", queue="reports")
@job("attendance.recompute_summaries", queue="reports")
async def recompute_summaries(ctx: JobContext, db: Any, term_id: str, **_: Any) -> dict[str, Any]:
    from app.services.attendance.summary_service import SummaryService

    principal = await _principal(db, ctx)
    out = await SummaryService(db, principal).recompute_term(uuid.UUID(term_id), progress=await _progress_fn(ctx, db))
    await ctx.progress(db, 100, f"{out['rows']} summaries across {out['offerings']} offerings")
    return out


@celery.task(name="jobs.eligibility.compute", queue="reports")
@job("eligibility.compute", queue="reports")
async def eligibility_compute(
    ctx: JobContext, db: Any, term_id: str, body: dict[str, Any] | None = None, **_: Any
) -> dict[str, Any]:
    from app.schemas.attendance import EligibilityComputeRequest
    from app.services.attendance.eligibility_service import EligibilityService

    principal = await _principal(db, ctx)
    svc = EligibilityService(db, principal)
    term = await svc.get_term(uuid.UUID(term_id))
    out = await svc.run(
        term, EligibilityComputeRequest.model_validate(body or {}), progress=await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"Version {out.version}: {out.rows} rows")
    return out.model_dump(mode="json")


@celery.task(name="jobs.attendance.export", queue="reports")
@job("attendance.export", queue="reports")
async def register_export(ctx: JobContext, db: Any, offering_id: str, **params: Any) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.attendance.summary_service import SummaryService

    principal = await _principal(db, ctx)
    d_from = date.fromisoformat(params["from"]) if params.get("from") else None
    d_to = date.fromisoformat(params["to"]) if params.get("to") else None
    grid = await SummaryService(db, principal).register(uuid.UUID(offering_id), d_from, d_to)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "registration_number",
            "roll_number",
            "name",
            *[f"{s['date']} {s['start']}" for s in grid.sessions],
            "attended",
            "counted",
            "pct",
        ]
    )
    for st in grid.students:
        marks = grid.marks.get(st["id"], {})
        cells = [marks.get(s["id"], "") for s in grid.sessions]
        attended = sum(1 for c in cells if c in ("present", "late", "on_duty"))
        counted = sum(1 for c in cells if c and c != "exempt")
        w.writerow(
            [
                st["registration_number"],
                st["roll_number"],
                st["name"],
                *[c[:1].upper() if c else "" for c in cells],
                attended,
                counted,
                round(attended * 100 / counted, 2) if counted else "",
            ]
        )
    content = buf.getvalue().encode("utf-8-sig")
    key = build_key(ctx.institution_id or "platform", "attendance", f"register-{offering_id[:8]}.csv")
    await storage.put(key, content, "text/csv")
    await ctx.progress(db, 100, "Register ready")
    return {
        "result_url": storage.signed_url(key, 24 * 3600),
        "students": len(grid.students),
        "sessions": len(grid.sessions),
    }


@celery.task(name="jobs.attendance.detention_export", queue="reports")
@job("attendance.detention_export", queue="reports")
async def detention_export(
    ctx: JobContext, db: Any, term_id: str, college_id: str | None = None, program_id: str | None = None, **_: Any
) -> dict[str, Any]:
    from openpyxl import Workbook

    from app.core.files import build_key, storage
    from app.services.attendance.eligibility_service import EligibilityService

    principal = await _principal(db, ctx)
    rows = await EligibilityService(db, principal).detention_list(
        uuid.UUID(term_id), uuid.UUID(college_id) if college_id else None, uuid.UUID(program_id) if program_id else None
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Detention list"
    ws.append(["Programme", "Registration no.", "Student", "Course", "Attendance %", "Reasons", "Version"])
    for r in rows:
        ws.append(
            [
                r.program_code,
                r.registration_number,
                r.student_name,
                r.course_code,
                r.attendance_pct,
                ", ".join(r.reason_codes),
                r.version,
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    key = build_key(ctx.institution_id or "platform", "attendance", f"detention-{term_id[:8]}.xlsx")
    await storage.put(key, buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    await ctx.progress(db, 100, f"{len(rows)} detained course registrations")
    return {"result_url": storage.signed_url(key, 24 * 3600), "rows": len(rows)}


# ---- consumers ------------------------------------------------------------------------------------------------------------
async def _feature_on(event: dict[str, Any], key: str) -> bool:
    from app.core.features import is_enabled

    iid = event.get("institution_id")
    return bool(iid) and await is_enabled(iid, key)


@consumer("attendance.sessions_ready", events=["timetable.published"])
async def sessions_ready(db: Any, event: dict[str, Any]) -> None:
    """A newly published timetable generated sessions: approved OD from today on reaches them."""
    from app.services.attendance.od_service import OdService

    if not await _feature_on(event, "attendance.on_duty"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    n = await OdService(db, None, institution_id=iid).apply_to_sessions()
    log.info("attendance_sessions_ready", institution_id=str(iid), od_marks=n)


@consumer("attendance.session_od", events=["session.created"])
async def session_od(db: Any, event: dict[str, Any]) -> None:
    from app.services.attendance.od_service import OdService

    if not await _feature_on(event, "attendance.on_duty"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    sid = (event.get("payload") or {}).get("session_id") or event.get("aggregate_id")
    if not sid:
        return
    n = await OdService(db, None, institution_id=iid).apply_to_sessions([uuid.UUID(str(sid))], date(1970, 1, 1))
    log.info("attendance_session_od", institution_id=str(iid), od_marks=n)


@consumer("attendance.condonation_paid", events=["fees.payment_received"])
async def condonation_paid(db: Any, event: dict[str, Any]) -> None:
    from app.services.attendance.condonation_service import CondonationService

    payload = event.get("payload") or {}
    if payload.get("source_type") != "condonation" or not payload.get("source_id"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await CondonationService(db, None, institution_id=iid).mark_paid(
        uuid.UUID(str(payload["source_id"])), payload.get("receipt_no")
    )


# ---- Beat -----------------------------------------------------------------------------------------------------------------
@celery.task(name="beat.attendance.auto_finalize", queue="scheduled")
def auto_finalize() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.attendance.marking_service import MarkingService

        return await MarkingService(db, None, institution_id=iid).auto_finalize()

    return run_async(_for_institutions("attendance.core", one, "attendance_auto_finalize"))


@celery.task(name="beat.attendance.missing_sessions_digest", queue="scheduled")
def missing_sessions_digest() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.attendance.marking_service import MarkingService

        return await MarkingService(db, None, institution_id=iid).missing_digest()

    return run_async(_for_institutions("attendance.core", one, "attendance_missing_digest"))


@celery.task(name="beat.attendance.checkpoints", queue="scheduled")
def checkpoints() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.attendance.summary_service import SummaryService

        return await SummaryService(db, None, institution_id=iid).checkpoints()

    return run_async(_for_institutions("attendance.guardian_alerts", one, "attendance_checkpoints"))


@celery.task(name="beat.attendance.streak_alerts", queue="scheduled")
def streak_alerts() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from sqlalchemy import select

        from app.models.academic import AcademicTerm
        from app.services.attendance.summary_service import SummaryService

        svc = SummaryService(db, None, institution_id=iid)
        terms = (
            (
                await db.execute(
                    select(AcademicTerm.id).where(
                        AcademicTerm.institution_id == iid,
                        AcademicTerm.is_current.is_(True),
                        AcademicTerm.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for tid in terms:
            n += (await svc.recompute_term(tid))["rows"]
        return n

    return run_async(_for_institutions("attendance.core", one, "attendance_streak_alerts"))
