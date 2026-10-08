"""Student tasks — Prompts/07 §07.7.

Jobs (run as the requesting user through ``load_principal`` so scopes and audit apply as for the API):
``jobs.students.bulk_import`` (CSV / XLSX stored by the API; one savepoint per row, partial-success report),
``jobs.students.export`` (XLSX → signed ``result_url``), ``jobs.students.id_cards`` (one PDF per student in a ZIP;
the result carries the QR tokens) and ``jobs.students.promote`` (``POST /batches/{id}/promote`` without ``dry_run``).
Beat (per institution with the feature on, in the institution's local date): ``students.document_expiry`` (Mondays
07:10) and ``students.undertaking_reminders`` (daily 07:20 — acts on the academic year's first day and weekly for four
weeks). Consumers: ``search.reindex`` already follows ``student.*``; notifications go through ``notify_event``;
Phase 12 ``fees.assign_on_create``, Phase 19 ``library.member_on_create`` and Phase 18 ``abc.register`` subscribe to
``student.created``.
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal


async def _progress_fn(ctx: JobContext, db: Any) -> Any:
    async def progress(pct: int, message: str) -> None:
        await ctx.progress(db, pct, message)

    return progress


@celery.task(name="jobs.students.bulk_import", queue="reports")
@job("students.bulk_import", queue="reports")
async def students_bulk_import(
    ctx: JobContext, db: Any, key: str, filename: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.core.files import storage
    from app.services.student_service import StudentService

    principal = await _principal(db, ctx)
    content = await storage.get(key)
    report = await StudentService(db, principal).run_import(content, filename, await _progress_fn(ctx, db))
    await ctx.progress(db, 100, f"{report['succeeded']} imported, {len(report['failed'])} failed")
    return report


@celery.task(name="jobs.students.export", queue="reports")
@job("students.export", queue="reports")
async def students_export(
    ctx: JobContext, db: Any, scope: str | None = None, filters: dict[str, Any] | None = None, **_: Any
) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.services.student_service import StudentService

    principal = await _principal(db, ctx)
    clean: dict[str, Any] = {}
    for k, v in (filters or {}).items():
        clean[k] = uuid.UUID(v) if k.endswith("_id") and isinstance(v, str) else v
    content = await StudentService(db, principal).export_xlsx(scope, **clean)
    key = build_key(ctx.institution_id or "platform", "student-exports", "students.xlsx")
    await storage.put(key, content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    await ctx.progress(db, 100, "Export ready")
    return {"result_url": storage.signed_url(key, 24 * 3600), "bytes": len(content)}


@celery.task(name="jobs.students.id_cards", queue="documents")
@job("students.id_cards", queue="documents")
async def students_id_cards(ctx: JobContext, db: Any, student_ids: list[str], **_: Any) -> dict[str, Any]:
    from app.services.student_records_service import StudentRecordsService

    principal = await _principal(db, ctx)
    result = await StudentRecordsService(db, principal).run_id_cards(
        [uuid.UUID(s) for s in student_ids], await _progress_fn(ctx, db)
    )
    await ctx.progress(db, 100, f"{result['count']} ID card(s) ready")
    return result


@celery.task(name="jobs.students.promote", queue="reports")
@job("students.promote", queue="reports")
async def students_promote(
    ctx: JobContext, db: Any, batch_id: str, to_term_number: int, apply_detention_rule: bool = True, **_: Any
) -> dict[str, Any]:
    from app.schemas.students import PromoteBatchRequest
    from app.services.enrollment_service import EnrollmentService

    principal = await _principal(db, ctx)
    preview = await EnrollmentService(db, principal).run_promotion(
        uuid.UUID(batch_id),
        PromoteBatchRequest(to_term_number=int(to_term_number), apply_detention_rule=apply_detention_rule),
        dry_run=False,
        progress=await _progress_fn(ctx, db),
    )
    await ctx.progress(db, 100, f"{len(preview.promoted)} promoted, {len(preview.detained)} detained")
    return {
        "batch_id": batch_id,
        "to_term_number": preview.to_term_number,
        "promoted": len(preview.promoted),
        "detained": len(preview.detained),
        "on_break": len(preview.on_break),
        "already_promoted": preview.already_promoted,
        "detained_students": [r.registration_number for r in preview.detained],
    }


# ---- Beat ------------------------------------------------------------------------------------------------------------
@celery.task(name="beat.students.document_expiry", queue="scheduled")
def document_expiry() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.student_records_service import StudentRecordsService

        return await StudentRecordsService(db, None, institution_id=iid).remind_expiring_documents()

    return run_async(_for_institutions("students.documents", one, "students_document_expiry"))


@celery.task(name="beat.students.undertaking_reminders", queue="scheduled")
def undertaking_reminders() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.student_records_service import StudentRecordsService

        return await StudentRecordsService(db, None, institution_id=iid).remind_pending_undertakings(today)

    return run_async(_for_institutions("students.undertakings", one, "students_undertaking_reminders"))
