"""Affiliation tasks — Prompts/34 §34.7.

Jobs: ``affiliation.fee_compute`` (fee preview for an application), ``affiliation.order_pdf``,
``affiliation.submission_extract`` / ``submission_validate`` / ``submission_import``, ``affiliation.centre_allocation``,
``affiliation.centre_appointment``, ``affiliation.carry_forward``, ``affiliation.returns_export`` (xlsx),
``affiliation.portfolio_refresh`` (compliance scores + Phase 32 ``metrics.publish``).
Beat: ``affiliation.submission_windows`` (daily: open / due / escalate), ``affiliation.approval_expiry_scan`` (weekly),
``affiliation.deficiency_deadline_scan`` (daily), ``affiliation.inspection_reminders`` (daily),
``affiliation.dues_reminders`` (weekly), ``affiliation.portfolio_refresh`` (weekly).
Consumers: ``fees.payment_received`` (``source_type=affiliation_application`` → ``fee_paid``), ``academic_year.rolled_over``
(carry permanent approvals forward), ``cia.submitted_to_university`` / ``eligibility.decided`` /
``exams.registration_closed`` (refresh the draft submission's record count), ``results.published`` (college release
notifications), ``governance.resolution_passed`` (a resolution linked to an application is recorded on its timeline).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer
from app.tasks.research import XLSX, xlsx_bytes


async def _upload(principal: Any, name: str, content: bytes, mime: str) -> str:
    from app.core.files import build_key, get_storage

    key = build_key(principal.institution_id, "affiliation", name)
    storage = get_storage()
    await storage.put(key, content, mime)
    return storage.signed_url(key)


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.affiliation.fee_compute", queue="reports")
@job("affiliation.fee_compute", queue="reports")
async def fee_compute(ctx: JobContext, db: Any, application_id: str, **_: Any) -> dict[str, Any]:
    from app.services.affiliation.application_service import ApplicationService

    principal = await _principal(db, ctx)
    out = await ApplicationService(db, principal).fee_preview(uuid.UUID(application_id))
    return out.model_dump(mode="json")


@celery.task(name="jobs.affiliation.order_pdf", queue="reports")
@job("affiliation.order_pdf", queue="reports")
async def order_pdf(ctx: JobContext, db: Any, application_id: str, **_: Any) -> dict[str, Any]:
    from app.services.affiliation.application_service import ApplicationService
    from app.utils.pdf import simple_pdf

    principal = await _principal(db, ctx)
    name, lines = await ApplicationService(db, principal).order_lines(uuid.UUID(application_id))
    url = await _upload(principal, f"{name}.pdf", simple_pdf(lines, title="Affiliation order"), "application/pdf")
    return {"result_url": url}


@celery.task(name="jobs.affiliation.submission_extract", queue="reports")
@job("affiliation.submission_extract", queue="reports")
async def submission_extract(ctx: JobContext, db: Any, submission_id: str, **_: Any) -> dict[str, Any]:
    from app.services.affiliation.submission_service import SubmissionService

    principal = await _principal(db, ctx)
    out = await SubmissionService(db, principal).extract(uuid.UUID(submission_id))
    return {"submission_id": submission_id, "record_count": out.record_count}


@celery.task(name="jobs.affiliation.submission_validate", queue="reports")
@job("affiliation.submission_validate", queue="reports")
async def submission_validate(ctx: JobContext, db: Any, submission_id: str, **_: Any) -> dict[str, Any]:
    from app.services.affiliation.submission_service import SubmissionService

    principal = await _principal(db, ctx)
    report = await SubmissionService(db, principal).validate(uuid.UUID(submission_id))
    return report.model_dump(mode="json")


@celery.task(name="jobs.affiliation.submission_import", queue="reports")
@job("affiliation.submission_import", queue="reports")
async def submission_import(
    ctx: JobContext, db: Any, submission_id: str, file_url: str, mapping: dict[str, str] | None = None, **_: Any
) -> dict[str, Any]:
    from app.schemas.affiliation import SubmissionImport
    from app.services.affiliation.submission_service import SubmissionService

    principal = await _principal(db, ctx)
    out = await SubmissionService(db, principal).import_file(
        uuid.UUID(submission_id), SubmissionImport(file_url=file_url, mapping=mapping or {})
    )
    return {"submission_id": submission_id, "record_count": out.record_count}


@celery.task(name="jobs.affiliation.centre_allocation", queue="reports")
@job("affiliation.centre_allocation", queue="reports")
async def centre_allocation(
    ctx: JobContext,
    db: Any,
    exam_session_id: str,
    strategy: str = "nearest",
    manual: dict[str, list[str]] | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.schemas.affiliation import CentreAllocationRun
    from app.services.affiliation.exam_centre_service import ExamCentreService

    principal = await _principal(db, ctx)
    out = await ExamCentreService(db, principal).allocate(
        CentreAllocationRun(
            exam_session_id=uuid.UUID(exam_session_id),
            strategy=strategy,  # type: ignore[arg-type]
            manual={k: [uuid.UUID(x) for x in v] for k, v in (manual or {}).items()},
        )
    )
    return out.model_dump(mode="json")


@celery.task(name="jobs.affiliation.centre_appointment", queue="reports")
@job("affiliation.centre_appointment", queue="reports")
async def centre_appointment(ctx: JobContext, db: Any, centre_id: str, **_: Any) -> dict[str, Any]:
    from app.services.affiliation.exam_centre_service import ExamCentreService

    principal = await _principal(db, ctx)
    out = await ExamCentreService(db, principal).appointment(uuid.UUID(centre_id))
    return {
        "result_url": out.url,
        "issued_document_id": str(out.issued_document_id) if out.issued_document_id else None,
    }


@celery.task(name="jobs.affiliation.carry_forward", queue="reports")
@job("affiliation.carry_forward", queue="reports")
async def carry_forward(ctx: JobContext, db: Any, academic_year_id: str, **_: Any) -> dict[str, Any]:
    from app.services.affiliation.program_approval_service import ProgramApprovalService

    principal = await _principal(db, ctx)
    out = await ProgramApprovalService(db, principal).carry_forward(uuid.UUID(academic_year_id))
    return out.model_dump(mode="json")


@celery.task(name="jobs.affiliation.returns_export", queue="reports")
@job("affiliation.returns_export", queue="reports")
async def returns_export(ctx: JobContext, db: Any, kind: str, year: str | None = None, **_: Any) -> dict[str, Any]:
    from app.services.affiliation.dashboard_service import DashboardService

    principal = await _principal(db, ctx)
    out = await DashboardService(db, principal).returns(kind, uuid.UUID(year) if year else None)
    url = await _upload(principal, f"affiliation-{kind}.xlsx", xlsx_bytes(kind, out.rows), XLSX)
    return {"result_url": url, "rows": len(out.rows)}


@celery.task(name="jobs.affiliation.portfolio_refresh", queue="reports")
@job("affiliation.portfolio_refresh", queue="reports")
async def portfolio_refresh_job(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from app.services.affiliation.college_registry_service import CollegeRegistryService
    from app.services.affiliation.dashboard_service import DashboardService

    principal = await _principal(db, ctx)
    n = await CollegeRegistryService(db, principal).refresh_scores()
    payload = await DashboardService(db, principal).publish_metrics()
    return {"colleges": n, "metrics": payload.get("metrics")}


# ---- Beat -----------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, path: str, cls: str, method: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod = importlib.import_module(f"app.services.affiliation.{path}")
        return int(await getattr(getattr(mod, cls)(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.affiliation.submission_windows", queue="scheduled")
def submission_windows() -> dict[str, int]:
    return _beat(
        "affiliation_submission_windows",
        "affiliation.data_submissions",
        "submission_service",
        "SubmissionService",
        "window_scan",
    )


@celery.task(name="beat.affiliation.approval_expiry_scan", queue="scheduled")
def approval_expiry_scan() -> dict[str, int]:
    return _beat(
        "affiliation_expiry_scan",
        "affiliation.core",
        "program_approval_service",
        "ProgramApprovalService",
        "expiry_scan",
    )


@celery.task(name="beat.affiliation.deficiency_deadline_scan", queue="scheduled")
def deficiency_deadline_scan() -> dict[str, int]:
    return _beat(
        "affiliation_deficiency_scan",
        "affiliation.inspections",
        "application_service",
        "ApplicationService",
        "deficiency_deadline_scan",
    )


@celery.task(name="beat.affiliation.inspection_reminders", queue="scheduled")
def inspection_reminders() -> dict[str, int]:
    return _beat(
        "affiliation_inspection_reminders",
        "affiliation.inspections",
        "application_service",
        "ApplicationService",
        "inspection_reminders",
    )


@celery.task(name="beat.affiliation.dues_reminders", queue="scheduled")
def dues_reminders() -> dict[str, int]:
    return _beat(
        "affiliation_dues_reminders",
        "affiliation.fees",
        "program_approval_service",
        "ProgramApprovalService",
        "dues_reminders",
    )


@celery.task(name="beat.affiliation.portfolio_refresh", queue="scheduled")
def portfolio_refresh() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.affiliation.college_registry_service import CollegeRegistryService
        from app.services.affiliation.dashboard_service import DashboardService

        n = await CollegeRegistryService(db, None, institution_id=iid).refresh_scores()
        await DashboardService(db, None, institution_id=iid).publish_metrics()
        return n

    return run_async(_for_institutions("affiliation.core", one, "affiliation_portfolio_refresh"))


# ---- consumers ------------------------------------------------------------------------------------------------------------
def _iid(event: dict[str, Any]) -> uuid.UUID | None:
    inst = event.get("institution_id")
    return uuid.UUID(str(inst)) if inst else None


async def _on(iid: uuid.UUID, key: str) -> bool:
    from app.core.features import is_enabled

    try:
        return await is_enabled(iid, key)
    except KeyError:
        return False


@consumer("affiliation.fee_paid", events=["fees.payment_received"])
async def on_payment(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    p = event.get("payload") or {}
    if iid is None or p.get("source_type") != "affiliation_application" or not p.get("source_id"):
        return
    from app.services.affiliation.application_service import ApplicationService

    await ApplicationService(db, None, institution_id=iid).on_payment(
        uuid.UUID(str(p["source_id"])), p.get("invoice_status")
    )


@consumer("affiliation.year_rollover", events=["academic_year.rolled_over"])
async def on_rollover(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    p = event.get("payload") or {}
    year = p.get("new_year_id") or p.get("academic_year_id") or p.get("to_year_id")
    if iid is None or not year or not await _on(iid, "affiliation.core"):
        return
    from app.services.affiliation.program_approval_service import ProgramApprovalService

    await ProgramApprovalService(db, None, institution_id=iid).carry_forward(uuid.UUID(str(year)))


@consumer(
    "affiliation.submission_refresh",
    events=["cia.submitted_to_university", "eligibility.decided", "exams.registration_closed"],
)
async def on_source_data(db: Any, event: dict[str, Any]) -> None:
    """Refresh record counts of draft / returned system-data submissions the event touches (the college still submits)."""
    iid = _iid(event)
    if iid is None or not await _on(iid, "affiliation.data_submissions"):
        return
    from sqlalchemy import select

    from app.models.affiliation import CollegeDataSubmission
    from app.services.affiliation.submission_service import SubmissionService

    et = str(event.get("event_type"))
    stype = {
        "cia.submitted_to_university": "cia_marks",
        "eligibility.decided": "attendance_eligibility",
        "exams.registration_closed": "exam_registrations",
    }[et]
    svc = SubmissionService(db, None, institution_id=iid)
    for s in (
        await db.execute(
            select(CollegeDataSubmission).where(
                CollegeDataSubmission.institution_id == iid,
                CollegeDataSubmission.submission_type == stype,
                CollegeDataSubmission.status.in_(("draft", "returned")),
            )
        )
    ).scalars():
        if (await svc.meta("sub", s.id)).get("source") == "file":
            continue
        s.record_count, _ = await svc.extract_count(s)
    await db.flush()


@consumer("affiliation.results_release", events=["results.published"])
async def on_results_published(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    if iid is None or not await _on(iid, "affiliation.core"):
        return
    p = event.get("payload") or {}
    sid = p.get("session_id") or p.get("exam_session_id")
    if not sid:
        return
    from sqlalchemy import func, select

    from app.models.exams import ExamRegistration
    from app.services.affiliation.common import AffiliationBase

    base = AffiliationBase(db, None, institution_id=iid)
    rows = (
        await db.execute(
            select(ExamRegistration.college_id, func.count())
            .where(ExamRegistration.exam_session_id == uuid.UUID(str(sid)))
            .group_by(ExamRegistration.college_id)
        )
    ).all()
    for cid, _n in rows:
        c = (await base.colleges_map([cid])).get(cid)
        if c is None or c.college_type != "affiliated":
            continue
        await base.timeline("college", cid, "results_released", session_id=str(sid))


@consumer("affiliation.resolution_linked", events=["governance.resolution_linked", "governance.resolution_passed"])
async def on_resolution(db: Any, event: dict[str, Any]) -> None:
    iid = _iid(event)
    p = event.get("payload") or {}
    if iid is None or p.get("entity_type") != "affiliation_application" or not p.get("entity_id"):
        return
    from app.services.affiliation.common import AffiliationBase

    await AffiliationBase(db, None, institution_id=iid).timeline(
        "app", p["entity_id"], "resolution_linked", resolution_id=p.get("resolution_id")
    )
