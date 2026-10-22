"""Assessment / LMS tasks — Prompts/13 §13.7.

Jobs (run as the requesting user): ``assessment.import_marks`` (XLSX / CSV: registration_number, marks | absent |
question columns), ``assessment.export`` (marks grid XLSX), ``lms.similarity_check`` (``PlagiarismChecker`` adapter),
``content.paper_generate`` (large blueprints). Consumer: ``assessment.auto_instantiate`` ← ``offering.status_changed``
(to ``open``). Beat: ``assessment.deadline_reminders`` (daily 09:00 IST), ``assessment.auto_lock`` (nightly),
``assignments.close_due`` (hourly), ``quizzes.auto_submit`` (every minute).
"""

import base64
import csv
import io
import uuid
from datetime import date
from typing import Any

import structlog

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer

log = structlog.get_logger()


def _rows_from(filename: str, raw: bytes) -> list[dict[str, str]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(raw), read_only=True, data_only=True).active
        it = ws.iter_rows(values_only=True)
        head = [str(h or "").strip().lower() for h in next(it, [])]
        return [{head[i]: ("" if v is None else str(v)) for i, v in enumerate(row) if i < len(head)} for row in it]
    return [
        {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    ]


@celery.task(name="jobs.assessment.import_marks", queue="reports")
@job("assessment.import_marks", queue="reports")
async def import_marks(
    ctx: JobContext, db: Any, assessment_id: str, filename: str, content_b64: str, **_: Any
) -> dict[str, Any]:
    from app.schemas.assessment import MarkRowIn, MarksBulkUpsert
    from app.services.assessment.assessment_service import AssessmentService

    principal = await _principal(db, ctx)
    svc = AssessmentService(db, principal)
    grid = await svc.grid(uuid.UUID(assessment_id))
    by_reg = {r.registration_number: r.student_program_enrollment_id for r in grid.rows}
    qnos = {q.question_no.lower(): q.question_no for q in grid.questions}
    rows, unknown = [], []
    for rec in _rows_from(filename, base64.b64decode(content_b64)):
        reg = rec.get("registration_number") or rec.get("reg_no") or ""
        eid = by_reg.get(reg)
        if eid is None:
            unknown.append(reg)
            continue
        absent = (rec.get("absent") or rec.get("marks") or "").strip().upper() in (
            "AB",
            "A",
            "TRUE",
            "YES",
            "1",
        ) and not (rec.get("marks") or "").replace(".", "").isdigit()
        qw = {qnos[k]: float(v) for k, v in rec.items() if k in qnos and v not in ("", None)}
        marks = float(rec["marks"]) if (rec.get("marks") or "").replace(".", "", 1).isdigit() else None
        rows.append(
            MarkRowIn(student_program_enrollment_id=eid, marks=marks, is_absent=absent, question_wise=qw or None)
        )
    out = await svc.bulk_upsert(uuid.UUID(assessment_id), MarksBulkUpsert(rows=rows, source="import")) if rows else None
    await ctx.progress(db, 100, f"{out.saved if out else 0} saved")
    return {
        "saved": out.saved if out else 0,
        "rejected": (out.rejected if out else [])
        + [{"registration_number": u, "reason": "unknown registration number"} for u in unknown],
    }


@celery.task(name="jobs.assessment.export", queue="reports")
@job("assessment.export", queue="reports")
async def export_marks(ctx: JobContext, db: Any, assessment_id: str, **_: Any) -> dict[str, Any]:
    from openpyxl import Workbook

    from app.core.files import build_key, storage
    from app.services.assessment.assessment_service import AssessmentService

    principal = await _principal(db, ctx)
    grid = await AssessmentService(db, principal).grid(uuid.UUID(assessment_id))
    wb = Workbook()
    ws = wb.active
    ws.title = grid.assessment.name[:30]
    qs = [q.question_no for q in grid.questions]
    ws.append(["registration_number", "roll_number", "name", *qs, "marks", "absent", "exempt"])
    for r in grid.rows:
        ws.append(
            [
                r.registration_number,
                r.roll_number,
                r.name,
                *[(r.question_wise or {}).get(q) for q in qs],
                r.marks,
                "AB" if r.is_absent else "",
                "EX" if r.is_exempt else "",
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    key = build_key(ctx.institution_id or "platform", "assessment", f"marks-{assessment_id[:8]}.xlsx")
    await storage.put(key, buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    await ctx.progress(db, 100, "Export ready")
    return {"result_url": storage.signed_url(key, 24 * 3600), "rows": len(grid.rows)}


@celery.task(name="jobs.lms.similarity_check", queue="integrations")
@job("lms.similarity_check", queue="integrations")
async def similarity_check(ctx: JobContext, db: Any, assignment_id: str, **_: Any) -> dict[str, Any]:
    from app.services.assessment.lms_service import LmsService

    principal = await _principal(db, ctx)
    n = await LmsService(db, principal).similarity(uuid.UUID(assignment_id))
    await ctx.progress(db, 100, f"{n} submission(s) checked")
    return {"checked": n}


@celery.task(name="jobs.content.paper_generate", queue="reports")
@job("content.paper_generate", queue="reports")
async def paper_generate(ctx: JobContext, db: Any, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.schemas.content import PaperGenerateRequest
    from app.services.assessment.content_service import ContentService

    principal = await _principal(db, ctx)
    out = await ContentService(db, principal).generate(PaperGenerateRequest.model_validate(body))
    await ctx.progress(db, 100, out.title)
    return out.model_dump(mode="json")


# ---- consumer -------------------------------------------------------------------------------------------------------------
@consumer("assessment.auto_instantiate", events=["offering.status_changed"])
async def auto_instantiate(db: Any, event: dict[str, Any]) -> None:
    from app.core.errors import APIError
    from app.core.features import is_enabled
    from app.services.assessment.assessment_service import AssessmentService

    p = event.get("payload") or {}
    iid = event.get("institution_id")
    if (
        p.get("to") != "open"
        or not p.get("offering_id")
        or not iid
        or not await is_enabled(iid, "assessment.internal_marks")
    ):
        return
    try:
        await AssessmentService(db, None, institution_id=uuid.UUID(str(iid))).instantiate(
            uuid.UUID(str(p["offering_id"])), system=True
        )
    except APIError as exc:
        log.info("assessment_auto_instantiate_skipped", offering_id=p["offering_id"], reason=exc.message)


# ---- Beat ---------------------------------------------------------------------------------------------------------------------
def _beat(feature: str, cls_path: str, method: str, label: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        import importlib

        mod, cls = cls_path.rsplit(".", 1)
        svc = getattr(importlib.import_module(mod), cls)(db, None, institution_id=iid)
        return int(await getattr(svc, method)())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.assessment.deadline_reminders", queue="scheduled")
def deadline_reminders() -> dict[str, int]:
    return _beat(
        "assessment.internal_marks",
        "app.services.assessment.assessment_service.AssessmentService",
        "deadline_reminders",
        "assessment_deadline_reminders",
    )


@celery.task(name="beat.assessment.auto_lock", queue="scheduled")
def auto_lock() -> dict[str, int]:
    return _beat(
        "assessment.marks_workflow",
        "app.services.assessment.assessment_service.AssessmentService",
        "auto_lock",
        "assessment_auto_lock",
    )


@celery.task(name="beat.assignments.close_due", queue="scheduled")
def close_due() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import update

        from app.models.lms import LmsAssignment

        # assignments that do not accept late work close at the due time; others a week after it
        now = datetime.now(UTC)
        r1 = await db.execute(
            update(LmsAssignment)
            .where(
                LmsAssignment.institution_id == iid,
                LmsAssignment.status == "published",
                LmsAssignment.allow_late.is_(False),
                LmsAssignment.due_at < now,
            )
            .values(status="closed")
        )
        r2 = await db.execute(
            update(LmsAssignment)
            .where(
                LmsAssignment.institution_id == iid,
                LmsAssignment.status == "published",
                LmsAssignment.allow_late.is_(True),
                LmsAssignment.due_at < now - timedelta(days=7),
            )
            .values(status="closed")
        )
        return int((r1.rowcount or 0) + (r2.rowcount or 0))  # type: ignore[attr-defined]

    return run_async(_for_institutions("lms.assignments", one, "assignments_close_due"))


@celery.task(name="beat.quizzes.auto_submit", queue="scheduled")
def quizzes_auto_submit() -> dict[str, int]:
    return _beat("lms.quizzes", "app.services.assessment.lms_service.LmsService", "auto_submit", "quizzes_auto_submit")
