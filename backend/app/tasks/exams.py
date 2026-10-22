"""Exam administration tasks — Prompts/14 §14.7.

Jobs (run as the requesting user): ``exams.papers_bulk``, ``exams.eligibility_apply``, ``exams.hall_tickets_generate``,
``exams.invigilation_auto_assign``, ``exams.registrations_bulk``. Consumers: ``exams.registration_paid`` ←
``fees.payment_received`` (``source_type='exam_registration'`` → ``confirmed``), ``exams.remuneration`` payroll source
(``exam_duty``; Phase 06 hook registry). Beat: ``exams.session_auto_status`` (daily), ``exams.lapse_fee_pending``
(hourly), ``exams.duty_reminders`` (D-1, 08:00 IST).
"""

import uuid
from datetime import date, timedelta
from typing import Any

import structlog

from app.core.aio import run_async
from app.core.hr_hooks import RemunerationLine, remuneration_source
from app.core.jobs import JobContext, job
from app.tasks.admissions import _progress_fn
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer

log = structlog.get_logger()


@celery.task(name="jobs.exams.papers_bulk", queue="reports")
@job("exams.papers_bulk", queue="reports")
async def papers_bulk(
    ctx: JobContext, db: Any, session_id: str, body: dict[str, Any] | None = None, **_: Any
) -> dict[str, Any]:
    from app.schemas.exams import BulkPapersRequest
    from app.services.exams.session_service import ExamSessionService

    principal = await _principal(db, ctx)
    out = await ExamSessionService(db, principal).papers_bulk(
        uuid.UUID(session_id), BulkPapersRequest.model_validate(body or {})
    )
    await ctx.progress(db, 100, f"{out.created} papers created")
    return out.model_dump()


@celery.task(name="jobs.exams.eligibility_apply", queue="reports")
@job("exams.eligibility_apply", queue="reports")
async def eligibility_apply(
    ctx: JobContext, db: Any, session_id: str, body: dict[str, Any] | None = None, **_: Any
) -> dict[str, Any]:
    from app.schemas.exams import EligibilityApplyRequest
    from app.services.exams.registration_service import ExamRegistrationService

    principal = await _principal(db, ctx)
    out = await ExamRegistrationService(db, principal).apply_eligibility(
        uuid.UUID(session_id), EligibilityApplyRequest.model_validate(body or {}), progress=await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{out.items} items")
    return out.model_dump()


@celery.task(name="jobs.exams.hall_tickets_generate", queue="documents")
@job("exams.hall_tickets_generate", queue="documents")
async def hall_tickets(
    ctx: JobContext, db: Any, session_id: str, body: dict[str, Any] | None = None, **_: Any
) -> dict[str, Any]:
    from app.schemas.exams import HallTicketGenerateRequest
    from app.services.exams.hall_seating_service import HallTicketService

    principal = await _principal(db, ctx)
    out = await HallTicketService(db, principal).generate(
        uuid.UUID(session_id),
        HallTicketGenerateRequest.model_validate(body or {}),
        progress=await _progress_fn(ctx, db),
    )
    await ctx.progress(db, 100, f"{out['issued']} issued, {len(out['skipped'])} skipped")
    return out


@celery.task(name="jobs.exams.invigilation_auto_assign", queue="reports")
@job("exams.invigilation_auto_assign", queue="reports")
async def auto_assign(ctx: JobContext, db: Any, session_id: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.schemas.exams import InvigilationAutoAssignRequest
    from app.services.exams.duty_qp_service import InvigilationService

    principal = await _principal(db, ctx)
    out = await InvigilationService(db, principal).auto_assign(
        uuid.UUID(session_id), InvigilationAutoAssignRequest.model_validate(body), progress=await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{out.duties} duties, {len(out.unfilled)} unfilled")
    return out.model_dump(mode="json")


@celery.task(name="jobs.exams.registrations_bulk", queue="reports")
@job("exams.registrations_bulk", queue="reports")
async def registrations_bulk(ctx: JobContext, db: Any, session_id: str, **_: Any) -> dict[str, Any]:
    from app.services.exams.registration_service import ExamRegistrationService

    principal = await _principal(db, ctx)
    out = await ExamRegistrationService(db, principal).bulk_register(
        uuid.UUID(session_id), progress=await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{out['registrations']} registrations")
    return out


@consumer("exams.registration_paid", events=["fees.payment_received"])
async def registration_paid(db: Any, event: dict[str, Any]) -> None:
    from app.services.exams.registration_service import ExamRegistrationService

    p = event.get("payload") or {}
    if p.get("source_type") != "exam_registration" or not p.get("source_id"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await ExamRegistrationService(db, None, institution_id=iid).on_paid(uuid.UUID(str(p["source_id"])))


@remuneration_source("exam_duty")
async def exam_duty_lines(db: Any, staff: Any, month: int, year: int) -> list[RemunerationLine]:
    """Completed / assigned duties of sessions that reached ``closed`` / ``results_published`` in the month."""
    from sqlalchemy import extract, select

    from app.core.features import is_enabled
    from app.models.exams import ExamSession, InvigilationDuty

    if not await is_enabled(staff.institution_id, "exams.remuneration"):
        return []
    rows = (
        (
            await db.execute(
                select(InvigilationDuty)
                .join(ExamSession, ExamSession.id == InvigilationDuty.exam_session_id)
                .where(
                    InvigilationDuty.staff_id == staff.id,
                    InvigilationDuty.status.notin_(("absent", "swap_requested")),
                    ExamSession.status.in_(("results_published", "closed")),
                    extract("month", InvigilationDuty.exam_date) == month,
                    extract("year", InvigilationDuty.exam_date) == year,
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        RemunerationLine(
            label=f"Exam duty {d.exam_date} {d.session_slot} ({d.role})",
            amount_paise=int(d.remuneration_paise or 0),
            source_type="exam_duty",
            source_id=d.id,
        )
        for d in rows
        if d.remuneration_paise
    ]


def _beat(feature: str, fn_name: str, label: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        if fn_name == "auto_status":
            from app.services.exams.session_service import ExamSessionService

            return int(await ExamSessionService(db, None, institution_id=iid).auto_status())
        if fn_name == "lapse":
            from app.services.exams.registration_service import ExamRegistrationService

            return int(await ExamRegistrationService(db, None, institution_id=iid).lapse_fee_pending())
        from sqlalchemy import select

        from app.core.notifications.notify import notify_event
        from app.models.exams import InvigilationDuty
        from app.models.hr import Staff

        rows = (
            await db.execute(
                select(InvigilationDuty, Staff.user_id)
                .join(Staff, Staff.id == InvigilationDuty.staff_id)
                .where(
                    InvigilationDuty.institution_id == iid,
                    InvigilationDuty.exam_date == today + timedelta(days=1),
                    InvigilationDuty.status.in_(("assigned", "accepted", "swapped")),
                )
            )
        ).all()
        for d, uid in rows:
            if uid:
                await notify_event(
                    db,
                    iid,
                    "exams.duty_reminder",
                    audience={"user_ids": [str(uid)]},
                    context={"date": d.exam_date.isoformat(), "slot": d.session_slot, "role": d.role},
                )
        return len(rows)

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.exams.session_auto_status", queue="scheduled")
def session_auto_status() -> dict[str, int]:
    return _beat("exams.sessions", "auto_status", "exams_session_auto_status")


@celery.task(name="beat.exams.lapse_fee_pending", queue="scheduled")
def lapse_fee_pending() -> dict[str, int]:
    return _beat("exams.registration_fee", "lapse", "exams_lapse_fee_pending")


@celery.task(name="beat.exams.duty_reminders", queue="scheduled")
def duty_reminders() -> dict[str, int]:
    return _beat("exams.invigilation", "duty", "exams_duty_reminders")
