"""PhD & research-scholar tasks — Prompts/31 §31.7.

Jobs: ``phd.fellowship_run`` (monthly disbursements), ``phd.plagiarism_check``, ``phd.examiner_dispatch``,
``phd.etd_upload``, ``phd.reports_export`` (xlsx), ``phd.progress_periods_generate``. Beat:
``phd.progress_due_reminders`` (weekly), ``phd.duration_scan`` (weekly), ``phd.examiner_report_reminders`` (weekly),
``phd.etd_deadline_reminders`` (weekly), ``phd.fellowship_upgrade_check`` (monthly), ``phd.coursework_deadline_scan``
(monthly). Consumers: ``student.created`` / ``student.admitted`` (PhD programme → scholar shell), ``results.published``
(coursework credits), ``fees.payment_received(source_type=thesis_submission)``, ``accounting.expense_paid`` /
``payroll.paid`` (``source_type=fellowship`` → disbursement paid), ``degrees.issued(award_type=phd)`` (timeline).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.services.phd import (  # noqa: F401  (workflow hooks / document resolvers register on import in the worker)
    award_service,
    examiner_service,
    request_service,
    scholar_service,
    thesis_service,
)
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer
from app.tasks.research import XLSX, _upload, xlsx_bytes


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.phd.fellowship_run", queue="reports")
@job("phd.fellowship_run", queue="reports")
async def fellowship_run(ctx: JobContext, db: Any, month: str, **_: Any) -> dict[str, Any]:
    from app.services.phd.fellowship_service import FellowshipService

    principal = await _principal(db, ctx)
    out = await FellowshipService(db, principal).run(date.fromisoformat(month))
    await ctx.progress(db, 100, f"{out.created} pending, {out.held} held")
    return out.model_dump(mode="json")


@celery.task(name="jobs.phd.plagiarism_check", queue="reports")
@job("phd.plagiarism_check", queue="reports")
async def plagiarism_check(ctx: JobContext, db: Any, thesis_id: str, **_: Any) -> dict[str, Any]:
    from app.services.phd.thesis_service import ThesisService

    principal = await _principal(db, ctx)
    out = await ThesisService(db, principal).check(uuid.UUID(thesis_id))
    return {"status": out.status, "similarity_pct": str(out.similarity_pct)}


@celery.task(name="jobs.phd.examiner_dispatch", queue="reports")
@job("phd.examiner_dispatch", queue="reports")
async def examiner_dispatch(ctx: JobContext, db: Any, examiner_id: str, **_: Any) -> dict[str, Any]:
    from app.services.phd.examiner_service import ExaminerService

    principal = await _principal(db, ctx)
    out = await ExaminerService(db, principal).dispatch(uuid.UUID(examiner_id))
    return {"status": out.status}


@celery.task(name="jobs.phd.etd_upload", queue="reports")
@job("phd.etd_upload", queue="reports")
async def etd_upload(ctx: JobContext, db: Any, etd_id: str, **_: Any) -> dict[str, Any]:
    from app.services.phd.etd_service import EtdService

    principal = await _principal(db, ctx)
    out = await EtdService(db, principal).upload(uuid.UUID(etd_id), job_id=ctx.job_id)
    return {"status": out.status, "handle": out.handle}


@celery.task(name="jobs.phd.reports_export", queue="reports")
@job("phd.reports_export", queue="reports")
async def reports_export(ctx: JobContext, db: Any, kind: str, year: int | None = None, **_: Any) -> dict[str, Any]:
    from app.services.phd.stats_service import StatsService

    principal = await _principal(db, ctx)
    rows = await StatsService(db, principal).report_rows(kind, int(year) if year else None)
    url = await _upload(principal, f"phd-{kind}.xlsx", xlsx_bytes(kind, rows), XLSX)
    await ctx.progress(db, 100, f"{len(rows)} rows")
    return {"result_url": url, "rows": len(rows)}


@celery.task(name="jobs.phd.progress_periods_generate", queue="reports")
@job("phd.progress_periods_generate", queue="reports")
async def progress_periods_generate(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.phd.progress_service import ProgressService

    principal = await _principal(db, ctx)
    return {"periods_due": await ProgressService(db, principal).generate_periods()}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, path: str, cls: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.phd.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.phd.progress_due_reminders", queue="scheduled")
def progress_due_reminders() -> dict[str, int]:
    return _beat("phd_progress_due", "phd.progress_reports", "progress_service", "ProgressService", "due_reminders")


@celery.task(name="beat.phd.duration_scan", queue="scheduled")
def duration_scan() -> dict[str, int]:
    return _beat("phd_duration_scan", "phd.core", "scholar_service", "ScholarService", "duration_scan")


@celery.task(name="beat.phd.examiner_report_reminders", queue="scheduled")
def examiner_report_reminders() -> dict[str, int]:
    return _beat(
        "phd_examiner_reminders", "phd.external_examiners", "examiner_service", "ExaminerService", "report_reminders"
    )


@celery.task(name="beat.phd.etd_deadline_reminders", queue="scheduled")
def etd_deadline_reminders() -> dict[str, int]:
    return _beat("phd_etd_reminders", "phd.etd_upload", "etd_service", "EtdService", "deadline_reminders")


@celery.task(name="beat.phd.fellowship_upgrade_check", queue="scheduled")
def fellowship_upgrade_check() -> dict[str, int]:
    return _beat(
        "phd_fellowship_upgrade", "phd.fellowships", "fellowship_service", "FellowshipService", "upgrade_check"
    )


@celery.task(name="beat.phd.coursework_deadline_scan", queue="scheduled")
def coursework_deadline_scan() -> dict[str, int]:
    return _beat(
        "phd_coursework_deadline", "phd.coursework", "coursework_service", "CourseworkService", "deadline_scan"
    )


# ---- consumers ------------------------------------------------------------------------------------------------------------
async def _enabled(event: dict[str, Any], key: str) -> uuid.UUID | None:
    from app.core.features import is_enabled

    inst = event.get("institution_id")
    if not inst:
        return None
    iid = uuid.UUID(str(inst))
    return iid if await is_enabled(iid, key) else None


@consumer("phd.scholar_shell", events=["student.created", "student.admitted"])
async def on_admitted(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "phd.core")
    p = event.get("payload") or {}
    eid = p.get("enrollment_id")
    if iid is None or not eid:
        return
    from app.services.phd.scholar_service import ScholarService

    await ScholarService(db, None, institution_id=iid).on_admitted(uuid.UUID(str(eid)))


@consumer("phd.coursework_results", events=["results.published"])
async def on_results(db: Any, event: dict[str, Any]) -> None:
    iid = await _enabled(event, "phd.coursework")
    ids = (event.get("payload") or {}).get("enrollment_ids") or []
    if iid is None or not ids:
        return
    from app.services.phd.coursework_service import CourseworkService

    await CourseworkService(db, None, institution_id=iid).on_results_published([uuid.UUID(str(i)) for i in ids])


@consumer("phd.fellowship_paid", events=["accounting.expense_paid", "payroll.paid"])
async def on_fellowship_paid(db: Any, event: dict[str, Any]) -> None:
    p = event.get("payload") or {}
    if p.get("source_type") != "fellowship" or not p.get("source_id"):
        return
    iid = await _enabled(event, "phd.fellowships")
    if iid is None:
        return
    from app.services.phd.fellowship_service import FellowshipService

    await FellowshipService(db, None, institution_id=iid).on_paid(uuid.UUID(str(p["source_id"])))


@consumer("phd.thesis_fee_paid", events=["fees.payment_received"])
async def on_thesis_fee(db: Any, event: dict[str, Any]) -> None:
    p = event.get("payload") or {}
    if p.get("source_type") != "thesis_submission" or not p.get("source_id"):
        return
    iid = await _enabled(event, "phd.thesis_plagiarism")
    if iid is None:
        return
    from app.services.phd.common import PhdBase

    svc = PhdBase(db, None, institution_id=iid)
    m = await svc.meta("thesis", p["source_id"])
    m["fee_paid"] = True
    await svc.put_meta("thesis", p["source_id"], m)


@consumer("phd.degree_issued", events=["degrees.issued"])
async def on_degree_issued(db: Any, event: dict[str, Any]) -> None:
    p = event.get("payload") or {}
    if p.get("award_type") not in (None, "phd") or not p.get("enrollment_id"):
        return
    iid = await _enabled(event, "phd.core")
    if iid is None:
        return
    from sqlalchemy import select

    from app.models.phd import ResearchScholar
    from app.services.phd.common import PhdBase

    s = (
        await db.execute(
            select(ResearchScholar).where(
                ResearchScholar.student_program_enrollment_id == uuid.UUID(str(p["enrollment_id"]))
            )
        )
    ).scalar_one_or_none()
    if s is not None:
        await PhdBase(db, None, institution_id=iid).scholar_timeline(s, "degree_issued", award_id=p.get("award_id"))
