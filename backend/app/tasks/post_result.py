"""Post-result tasks — Prompts/16 §16.7.

Jobs (run as the requesting user): ``reval.photocopy_scan`` (re-render a photocopy once the exam cell attached the
scan), ``transcripts.generate``, ``malpractice.notice_pdf``. Revaluation runs reuse ``results.compute_run``.
Consumers on ``fees.payment_received``: ``reval.fee_paid`` (``source_type='reval_request'`` → ``fee_paid``; photocopies
are produced at once) and ``transcripts.fee_paid`` (``source_type='transcript'`` → ``requested`` + the
``transcripts.issue`` workflow). Beat: ``reval.window_close`` (daily), ``reval.due_reminders`` (daily),
``malpractice.hearing_reminders`` (daily), ``withheld.auto_release`` (hourly), ``transcripts.reminders`` (daily).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer


@celery.task(name="jobs.reval.photocopy_scan", queue="documents")
@job("reval.photocopy_scan", queue="documents")
async def photocopy_scan(ctx: JobContext, db: Any, request_id: str, **_: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.post_result import RevalRequest
    from app.services.post_result.reval_service import RevalService

    principal = await _principal(db, ctx)
    r = (await db.execute(select(RevalRequest).where(RevalRequest.id == uuid.UUID(request_id)))).scalar_one()
    await RevalService(db, principal).render_photocopy(r)
    await ctx.progress(db, 100, "photocopy ready")
    return {"request_id": request_id}


@celery.task(name="jobs.transcripts.generate", queue="documents")
@job("transcripts.generate", queue="documents")
async def transcripts_generate(ctx: JobContext, db: Any, transcript_id: str, **_: Any) -> dict[str, Any]:
    from app.services.post_result.transcript_service import TranscriptService

    principal = await _principal(db, ctx)
    out = await TranscriptService(db, principal).generate(uuid.UUID(transcript_id))
    await ctx.progress(db, 100, f"transcript {out.document_number}")
    return {"transcript_id": transcript_id, "document_number": out.document_number}


@celery.task(name="jobs.malpractice.notice_pdf", queue="documents")
@job("malpractice.notice_pdf", queue="documents")
async def malpractice_notice(ctx: JobContext, db: Any, case_id: str, **_: Any) -> dict[str, Any]:
    from app.services.post_result.malpractice_service import MalpracticeService

    principal = await _principal(db, ctx)
    out = await MalpracticeService(db, principal).notice(uuid.UUID(case_id))
    await ctx.progress(db, 100, f"notice for {out.case_number}")
    return {"case_id": case_id}


@consumer("reval.fee_paid", events=["fees.payment_received"])
async def reval_fee_paid(db: Any, event: dict[str, Any]) -> None:
    from app.services.post_result.reval_service import RevalService

    p = event.get("payload") or {}
    if (
        p.get("source_type") != "reval_request"
        or not p.get("source_id")
        or p.get("invoice_status") not in (None, "paid")
    ):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await RevalService(db, None, institution_id=iid).on_paid(uuid.UUID(str(p["source_id"])))


@consumer("transcripts.fee_paid", events=["fees.payment_received"])
async def transcript_fee_paid(db: Any, event: dict[str, Any]) -> None:
    from app.services.post_result.transcript_service import TranscriptService

    p = event.get("payload") or {}
    if p.get("source_type") != "transcript" or not p.get("source_id") or p.get("invoice_status") not in (None, "paid"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await TranscriptService(db, None, institution_id=iid).on_paid(uuid.UUID(str(p["source_id"])))


def _beat(feature: str, fn_name: str, label: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        if fn_name == "window_close":
            from app.services.post_result.reval_service import RevalService

            return int(await RevalService(db, None, institution_id=iid).window_close())
        if fn_name == "due_reminders":
            from app.services.post_result.reval_service import RevalService

            return int(await RevalService(db, None, institution_id=iid).due_reminders())
        if fn_name == "hearings":
            from app.services.post_result.malpractice_service import MalpracticeService

            return int(await MalpracticeService(db, None, institution_id=iid).hearing_reminders())
        if fn_name == "auto_release":
            from app.services.post_result.withheld_service import WithheldService

            return int(await WithheldService(db, None, institution_id=iid).auto_release())
        from app.services.post_result.transcript_service import TranscriptService

        return int(await TranscriptService(db, None, institution_id=iid).reminders())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.reval.window_close", queue="scheduled")
def reval_window_close() -> dict[str, int]:
    return _beat("results.revaluation", "window_close", "reval_window_close")


@celery.task(name="beat.reval.due_reminders", queue="scheduled")
def reval_due_reminders() -> dict[str, int]:
    return _beat("results.revaluation", "due_reminders", "reval_due_reminders")


@celery.task(name="beat.malpractice.hearing_reminders", queue="scheduled")
def hearing_reminders() -> dict[str, int]:
    return _beat("results.malpractice", "hearings", "malpractice_hearing_reminders")


@celery.task(name="beat.withheld.auto_release", queue="scheduled")
def withheld_auto_release() -> dict[str, int]:
    return _beat("results.processing", "auto_release", "withheld_auto_release")


@celery.task(name="beat.transcripts.reminders", queue="scheduled")
def transcript_reminders() -> dict[str, int]:
    return _beat("results.transcripts", "reminders", "transcripts_reminders")
