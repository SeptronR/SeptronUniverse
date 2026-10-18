"""Evaluation & results tasks — Prompts/15 §15.7.

Jobs (run as the requesting user): ``results.compute_run``, ``results.grade_cards``. Payroll source
``exam_valuation`` (Phase 06 hook registry; ``exams.remuneration``): submitted valuation assignments of sessions that
reached ``results_published`` / ``closed`` in the month. Beat: ``valuation.due_reminders`` (daily),
``results.publish_notifications_retry`` (10 min), ``scripts.retention_check`` (weekly).
"""

import uuid
from datetime import date
from typing import Any

import structlog

from app.core.aio import run_async
from app.core.hr_hooks import RemunerationLine, remuneration_source
from app.core.jobs import JobContext, job
from app.tasks.admissions import _progress_fn
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal

log = structlog.get_logger()

DEFAULT_PER_SCRIPT = {"1": 3000, "2": 3000, "3": 4000}  # paise per script per round


@celery.task(name="jobs.results.compute_run", queue="reports")
@job("results.compute_run", queue="reports")
async def compute_run(ctx: JobContext, db: Any, run_id: str, **_: Any) -> dict[str, Any]:
    from app.services.results.result_service import ResultRunService

    principal = await _principal(db, ctx)
    out = await ResultRunService(db, principal).compute(uuid.UUID(run_id), progress=await _progress_fn(ctx, db))
    await ctx.progress(db, 100, f"{(out.stats or {}).get('rows', 0)} rows, {out.anomalies_count} anomalies")
    return {"run_id": run_id, "status": out.status, "anomalies": out.anomalies_count}


@celery.task(name="jobs.results.grade_cards", queue="documents")
@job("results.grade_cards", queue="documents")
async def grade_cards(ctx: JobContext, db: Any, run_id: str, **_: Any) -> dict[str, Any]:
    from app.services.results.grade_card_service import GradeCardService

    principal = await _principal(db, ctx)
    out = await GradeCardService(db, principal).generate_for_run(
        uuid.UUID(run_id), progress=await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{out['generated']} grade cards")
    return out


@remuneration_source("exam_valuation")
async def valuation_lines(db: Any, staff: Any, month: int, year: int) -> list[RemunerationLine]:
    """Submitted valuation rounds of sessions published / closed, paid in the month of submission."""
    from sqlalchemy import extract, func, select

    from app.core.features import is_enabled
    from app.models.exams import ExamPaper, ExamSession
    from app.models.valuation import AnswerScript, ValuationAssignment
    from app.services.settings_service import SettingsService

    if not await is_enabled(staff.institution_id, "exams.remuneration"):
        return []
    rates = {
        **DEFAULT_PER_SCRIPT,
        **(await SettingsService(db).value(staff.institution_id, "exams", "valuation_remuneration") or {}),
    }
    rows = (
        await db.execute(
            select(ValuationAssignment, ExamPaper.paper_code, func.count(AnswerScript.id))
            .join(ExamPaper, ExamPaper.id == ValuationAssignment.exam_paper_id)
            .join(ExamSession, ExamSession.id == ExamPaper.exam_session_id)
            .join(AnswerScript, AnswerScript.bundle_id == ValuationAssignment.bundle_id)
            .where(
                ValuationAssignment.evaluator_staff_id == staff.id,
                ValuationAssignment.status.in_(("submitted", "verified")),
                ExamSession.status.in_(("results_published", "closed")),
                extract("month", ValuationAssignment.submitted_at) == month,
                extract("year", ValuationAssignment.submitted_at) == year,
            )
            .group_by(ValuationAssignment.id, ExamPaper.paper_code)
        )
    ).all()
    out = []
    for a, code, n in rows:
        amount = (
            a.remuneration_paise
            if a.remuneration_paise is not None
            else int(rates.get(str(a.valuation_round), 0)) * int(n)
        )
        if amount:
            out.append(
                RemunerationLine(
                    label=f"Valuation {code or ''} round {a.valuation_round} ({n} scripts)",
                    amount_paise=int(amount),
                    source_type="exam_valuation",
                    source_id=a.id,
                )
            )
    return out


def _beat(feature: str, fn_name: str, label: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        if fn_name == "reminders":
            from app.services.results.valuation_service import ValuationService

            return int(await ValuationService(db, None, institution_id=iid).due_reminders())
        if fn_name == "notify_retry":
            from app.services.results.result_service import ResultRunService

            return int(await ResultRunService(db, None, institution_id=iid).retry_notifications())
        from app.services.results.coding_service import CodingService

        return int(await CodingService(db, None, institution_id=iid).retention_check())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.valuation.due_reminders", queue="scheduled")
def due_reminders() -> dict[str, int]:
    return _beat("exams.coding_dummy", "reminders", "valuation_due_reminders")


@celery.task(name="beat.results.publish_notifications_retry", queue="scheduled")
def publish_notifications_retry() -> dict[str, int]:
    return _beat("results.processing", "notify_retry", "results_publish_notifications_retry")


@celery.task(name="beat.scripts.retention_check", queue="scheduled")
def retention_check() -> dict[str, int]:
    return _beat("exams.script_custody", "retention", "scripts_retention_check")
