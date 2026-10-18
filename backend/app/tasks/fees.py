"""Fees tasks — Prompts/12 §12.7.

Jobs (run as the requesting user): ``fees.receipt_pdf`` (stored, ``receipt_url`` set), ``fees.bulk_invoice`` (a
structure assignment above 200 enrolments, or term invoices for a batch from each enrolment's applicable structure),
``fees.reconcile_upload`` (statement rows → auto-match proposals), ``fees.reports_export`` (CSV),
``fees.accounting_export`` (Tally XML / CSV), ``scholarships.nsp_sync`` (adapter mock).

Consumers: ``fees.condonation_invoice`` ← ``fees.condonation_invoice`` (Phase 11), ``fees.applicant_paid`` ←
``fees.payment_received`` (Phase 08 ``application_fee`` / ``admission_fee`` → ``ApplicationService.mark_paid``),
``fees.registration_paid`` ← ``fees.payment_received`` (Phase 09 — a ``fee_order`` audit row with status ``paid``),
``fees.auto_assign`` ← ``student.created`` (applicable structure + staff-ward concession), ``no_dues.on_transfer`` ←
``transfer.requested`` (Phase 07). Phase 11's ``attendance.condonation_paid`` already listens for
``source_type='condonation'``.

Beat (UTC crontab, institution-local dates inside): ``fees.late_fees`` (nightly 00:40 IST), ``fees.due_reminders``
(08:00 IST), ``fees.overdue_holds`` (nightly), ``fees.day_book_close_reminder`` (18:00 IST),
``fees.gateway_status_poll`` (every 10 min).
"""

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


async def bulk_by_batch(
    db: Any,
    principal: Any,
    batch_id: uuid.UUID,
    term_id: uuid.UUID | None,
    *,
    dry_run: bool = False,
    progress: Any = None,
) -> dict[str, Any]:
    """Term invoices for every active enrolment of a batch from its applicable structure (idempotent)."""
    from sqlalchemy import select

    from app.models.academic import AcademicTerm
    from app.models.students import Student, StudentProgramEnrollment
    from app.schemas.fees import FeeAssignRequest
    from app.services.fees.invoice_service import InvoiceService
    from app.services.fees.structure_service import StructureService

    svc = StructureService(db, principal)
    inv = InvoiceService(db, principal, institution_id=svc.inst)
    term = (
        (await db.execute(select(AcademicTerm).where(AcademicTerm.id == term_id))).scalar_one_or_none()
        if term_id
        else None
    )
    rows = (
        await db.execute(
            select(StudentProgramEnrollment, Student)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(
                StudentProgramEnrollment.batch_id == batch_id,
                StudentProgramEnrollment.deleted_at.is_(None),
                StudentProgramEnrollment.status.in_(("active", "provisional", "admitted")),
            )
        )
    ).all()
    out = {"enrolments": len(rows), "invoices_created": 0, "already": 0, "no_structure": 0, "dry_run": dry_run}
    for n, (e, st) in enumerate(rows):
        t = term or await svc.current_term(e.college_id)
        tn = await inv.term_number_of(e, t)
        s, _, _ = await svc.structures.applicable(e, st, tn, await svc.today())
        if s is None:
            out["no_structure"] += 1
            continue
        if await inv.structure_invoice_exists(s, e.id, t.id if t else None):
            out["already"] += 1
            continue
        if not dry_run:
            await svc.assign(s.id, FeeAssignRequest(enrollment_ids=[e.id], term_id=t.id if t else None))
        out["invoices_created"] += 1
        if progress and n % 25 == 0:
            await progress(int(n * 100 / max(1, len(rows))), f"{n}/{len(rows)}")
    return out


# ---- jobs ------------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.fees.receipt_pdf", queue="reports")
@job("fees.receipt_pdf", queue="reports")
async def receipt_pdf(ctx: JobContext, db: Any, payment_id: str, **_: Any) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.fees.payment_service import PaymentService

    principal = await _principal(db, ctx)
    svc = PaymentService(db, principal)
    pdf, number = await svc.receipt_pdf(uuid.UUID(payment_id))
    key = build_key(ctx.institution_id or "platform", "fees/receipts", f"{number.replace('/', '-')}.pdf")
    await storage.put(key, pdf, "application/pdf")
    url = storage.signed_url(key, 7 * 24 * 3600)
    p = await svc.fees.payment(uuid.UUID(payment_id), for_update=True)
    p.receipt_url = url
    await db.flush()
    await ctx.progress(db, 100, f"Receipt {number}")
    return {"result_url": url, "receipt_number": number}


@celery.task(name="jobs.fees.bulk_invoice", queue="reports")
@job("fees.bulk_invoice", queue="reports")
async def bulk_invoice(
    ctx: JobContext,
    db: Any,
    structure_id: str | None = None,
    body: dict[str, Any] | None = None,
    batch_id: str | None = None,
    term_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.schemas.fees import FeeAssignRequest
    from app.services.fees.structure_service import StructureService

    principal = await _principal(db, ctx)
    progress = await _progress_fn(ctx, db)
    if structure_id:
        out = (
            await StructureService(db, principal).assign(
                uuid.UUID(structure_id), FeeAssignRequest.model_validate(body or {}), progress=progress
            )
        ).model_dump(mode="json")
    else:
        out = await bulk_by_batch(
            db, principal, uuid.UUID(str(batch_id)), uuid.UUID(term_id) if term_id else None, progress=progress
        )
    await ctx.progress(db, 100, f"{out.get('invoices_created', 0)} invoices")
    return out


@celery.task(name="jobs.fees.reconcile_upload", queue="reports")
@job("fees.reconcile_upload", queue="reports")
async def reconcile_upload(
    ctx: JobContext, db: Any, rows: list[dict[str, Any]], file_url: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.schemas.fees import ReconcileRowIn
    from app.services.fees.payment_service import PaymentService

    principal = await _principal(db, ctx)
    out = await PaymentService(db, principal).reconcile_rows([ReconcileRowIn.model_validate(r) for r in rows], file_url)
    await ctx.progress(db, 100, f"{out.auto_matched} proposed, {out.unmatched} unmatched")
    return out.model_dump(mode="json")


@celery.task(name="jobs.fees.reports_export", queue="reports")
@job("fees.reports_export", queue="reports")
async def reports_export(
    ctx: JobContext, db: Any, report: str, params: dict[str, Any] | None = None, **_: Any
) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.fees.report_service import FeeReportService

    principal = await _principal(db, ctx)
    p = dict(params or {})
    for k in ("date_from", "date_to"):
        if p.get(k):
            p[k] = date.fromisoformat(p[k])
    svc = FeeReportService(db, principal)
    rep = await svc.run(report, p)
    key = build_key(ctx.institution_id or "platform", "fees/reports", f"{report}.csv")
    await storage.put(key, svc.to_csv(rep), "text/csv")
    await ctx.progress(db, 100, f"{len(rep.rows)} rows")
    return {"result_url": storage.signed_url(key, 24 * 3600), "rows": len(rep.rows)}


@celery.task(name="jobs.fees.accounting_export", queue="reports")
@job("fees.accounting_export", queue="reports")
async def accounting_export(
    ctx: JobContext, db: Any, date_from: str, date_to: str, format: str = "tally_xml", **_: Any
) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.fees.report_service import FeeReportService

    principal = await _principal(db, ctx)
    data, ctype, ext = await FeeReportService(db, principal).accounting_export(
        date.fromisoformat(date_from), date.fromisoformat(date_to), format
    )
    key = build_key(ctx.institution_id or "platform", "fees/exports", f"vouchers-{date_from}-{date_to}.{ext}")
    await storage.put(key, data, ctype)
    await ctx.progress(db, 100, "Export ready")
    return {"result_url": storage.signed_url(key, 24 * 3600), "bytes": len(data)}


@celery.task(name="jobs.scholarships.nsp_sync", queue="reports")
@job("scholarships.nsp_sync", queue="reports")
async def nsp_sync(ctx: JobContext, db: Any, **_: Any) -> dict[str, Any]:
    from sqlalchemy import select

    from app.integrations.registry import get_adapter
    from app.models.fees import ScholarshipApplication

    rows = (
        (
            await db.execute(
                select(ScholarshipApplication).where(
                    ScholarshipApplication.institution_id == ctx.institution_id,
                    ScholarshipApplication.disbursement_mode == "external_portal",
                )
            )
        )
        .scalars()
        .all()
    )
    nsp = get_adapter("nsp", "mock")
    for r in rows:
        await nsp.send(reference=r.external_ref, status=r.status)
    await ctx.progress(db, 100, f"{len(rows)} synced")
    return {"synced": len(rows)}


# ---- consumers ---------------------------------------------------------------------------------------------------------------
async def _on(event: dict[str, Any], key: str) -> bool:
    from app.core.features import is_enabled

    iid = event.get("institution_id")
    return bool(iid) and await is_enabled(iid, key)


@consumer("fees.condonation_invoice", events=["fees.condonation_invoice"])
async def condonation_invoice(db: Any, event: dict[str, Any]) -> None:
    from app.services.fees.invoice_service import InvoiceService

    if not await _on(event, "fees.core"):
        return
    p = event.get("payload") or {}
    iid = uuid.UUID(str(event["institution_id"]))
    await InvoiceService(db, None, institution_id=iid).link(
        "condonation",
        uuid.UUID(str(p["source_id"])),
        int(p["amount_paise"]),
        uuid.UUID(str(p["student_program_enrollment_id"])) if p.get("student_program_enrollment_id") else None,
        "Condonation fee",
        "condonation",
    )


@consumer("fees.applicant_paid", events=["fees.payment_received"])
async def applicant_paid(db: Any, event: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.models.admissions import Applicant
    from app.services.admissions.application_service import ApplicationService

    p = event.get("payload") or {}
    st = p.get("source_type") or ""
    if st not in ("application_fee", "admission_fee") or p.get("invoice_status") != "paid" or not p.get("source_id"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    a = (
        await db.execute(select(Applicant).where(Applicant.id == uuid.UUID(str(p["source_id"]))).with_for_update())
    ).scalar_one_or_none()
    if a is not None:
        await ApplicationService(db, None, None, iid).mark_paid(a, st.removesuffix("_fee"))


@consumer("fees.registration_paid", events=["fees.payment_received"])
async def registration_paid(db: Any, event: dict[str, Any]) -> None:
    from app.core.audit import log_audit
    from app.services.students.common import SystemActor

    p = event.get("payload") or {}
    if p.get("source_type") != "course_registration" or not p.get("source_id"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    status = "paid" if p.get("invoice_status") == "paid" else "partial"
    await log_audit(
        db,
        principal=SystemActor(iid),
        module="registration",
        action="fee_order",
        record_type="course_registration",
        record_id=uuid.UUID(str(p["source_id"])),
        old=None,
        new={
            "status": status,
            "receipt_no": p.get("receipt_no"),
            "invoice_id": p.get("invoice_id"),
            "amount_paise": p.get("amount_paise"),
            "provider": "fees",
        },
        request=None,
    )


@consumer("fees.auto_assign", events=["student.created"])
async def auto_assign(db: Any, event: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.models.students import StudentProgramEnrollment
    from app.services.fees.structure_service import StructureService

    if not await _on(event, "fees.core"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    sid = (event.get("payload") or {}).get("student_id") or event.get("aggregate_id")
    if not sid:
        return
    svc = StructureService(db, None, institution_id=iid)
    for eid in (
        await db.execute(
            select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.student_id == uuid.UUID(str(sid)))
        )
    ).scalars():
        await svc.staff_ward_concession(eid)
        await svc.auto_assign(eid)


@consumer("no_dues.on_transfer", events=["transfer.requested"])
async def no_dues_on_transfer(db: Any, event: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.models.students import StudentProgramEnrollment
    from app.schemas.no_dues import NoDuesCreate
    from app.services.fees.no_dues_service import NoDuesService

    if not await _on(event, "fees.no_dues"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    p = event.get("payload") or {}
    eid = p.get("student_program_enrollment_id") or p.get("enrollment_id")
    if not eid and p.get("student_id"):
        eid = (
            await db.execute(
                select(StudentProgramEnrollment.id)
                .where(StudentProgramEnrollment.student_id == uuid.UUID(str(p["student_id"])))
                .limit(1)
            )
        ).scalar_one_or_none()
    if eid:
        await NoDuesService(db, None, institution_id=iid).create(
            NoDuesCreate(purpose="transfer", enrollment_id=uuid.UUID(str(eid))), system=True
        )


# ---- Beat -------------------------------------------------------------------------------------------------------------------
def _beat(feature: str, method: str, label: str, svc_path: str = "invoice") -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        if svc_path == "invoice":
            from app.services.fees.invoice_service import InvoiceService as S
        else:
            from app.services.fees.payment_service import PaymentService as S  # type: ignore[assignment]
        return int(await getattr(S(db, None, institution_id=iid), method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.fees.late_fees", queue="scheduled")
def late_fees() -> dict[str, int]:
    return _beat("fees.auto_late_fee", "late_fees", "fees_late_fees")


@celery.task(name="beat.fees.due_reminders", queue="scheduled")
def due_reminders() -> dict[str, int]:
    return _beat("fees.core", "due_reminders", "fees_due_reminders")


@celery.task(name="beat.fees.overdue_holds", queue="scheduled")
def overdue_holds() -> dict[str, int]:
    return _beat("fees.core", "overdue_holds", "fees_overdue_holds")


@celery.task(name="beat.fees.day_book_close_reminder", queue="scheduled")
def day_book_close_reminder() -> dict[str, int]:
    return _beat("fees.core", "day_book_close_reminder", "fees_day_book_reminder", "payment")


@celery.task(name="beat.fees.gateway_status_poll", queue="scheduled")
def gateway_status_poll() -> dict[str, int]:
    return _beat("fees.online_payment", "poll_initiated", "fees_gateway_poll", "payment")
