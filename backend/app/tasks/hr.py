"""HR tasks — Prompts/06 §06.7.

Jobs (run as the requesting user through ``load_principal`` so scopes and audit apply as for the API):
``jobs.hr.bulk_import`` (staff CSV, partial-success report), ``jobs.payroll.generate`` (a month for a scope),
``jobs.payroll.payslips`` (render + store payslip PDFs, notify). Beat (per institution with the feature on, in the
institution's local date): ``hr.leave_accrual`` (1st of the month 01:00 UTC), ``hr.leave_carry_forward`` (1st of
January 01:30 UTC — or the ``hr.leave_carry_forward_month`` setting's month), ``hr.document_expiry`` (Mondays 07:00),
``attendance.auto_mark_holidays`` (daily 00:10), ``payroll.reminder`` (25th 06:30).
Consumers: ``search.reindex`` already follows ``staff.*`` (Phase 01); notifications go through ``notify_event``;
Phase 10 subscribes ``timetable.substitutions_from_leave`` to ``leave.approved``.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import text

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery

log = structlog.get_logger()


async def _principal(db: Any, ctx: JobContext) -> Any:
    from app.core.errors import APIError
    from app.services.auth_service import load_principal

    if ctx.requested_by is None:
        raise APIError(422, "VALIDATION", f"{ctx.job_type} needs the requesting user")
    return await load_principal(db, ctx.requested_by)


# ---- jobs ------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.hr.bulk_import", queue="reports")
@job("hr.bulk_import", queue="reports")
async def hr_bulk_import(ctx: JobContext, db: Any, csv: str, **_: Any) -> dict[str, Any]:
    from app.services.staff_service import StaffService

    principal = await _principal(db, ctx)

    async def progress(pct: int, message: str) -> None:
        await ctx.progress(db, pct, message)

    report = await StaffService(db, principal).run_bulk_import(csv, progress)
    await ctx.progress(db, 100, f"{report['succeeded']} imported, {len(report['failed'])} failed")
    return report


@celery.task(name="jobs.payroll.generate", queue="reports")
@job("payroll.generate", queue="reports")
async def payroll_generate(
    ctx: JobContext,
    db: Any,
    month: int,
    year: int,
    college_id: str | None = None,
    staff_ids: list[str] | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.services.payroll_service import PayrollService

    principal = await _principal(db, ctx)

    async def progress(pct: int, message: str) -> None:
        await ctx.progress(db, pct, message)

    report = await PayrollService(db, principal).run_generate(
        int(month),
        int(year),
        uuid.UUID(college_id) if college_id else None,
        [uuid.UUID(s) for s in staff_ids or []] or None,
        progress,
    )
    await ctx.progress(
        db, 100, f"{report['generated']} generated, {report['recomputed']} recomputed, {len(report['skipped'])} skipped"
    )
    return report


@celery.task(name="jobs.payroll.payslips", queue="documents")
@job("payroll.payslips", queue="documents")
async def payroll_payslips(ctx: JobContext, db: Any, payroll_ids: list[str], **_: Any) -> dict[str, Any]:
    from app.services.payroll_service import PayrollService

    principal = await _principal(db, ctx)
    n = await PayrollService(db, principal).store_payslips([uuid.UUID(p) for p in payroll_ids])
    await ctx.progress(db, 100, f"{n} payslip(s) rendered")
    return {"payslips": n}


# ---- Beat ------------------------------------------------------------------------------------------------------------
PerInstitution = Callable[[Any, uuid.UUID, date], Awaitable[int]]


async def _for_institutions(feature: str, fn: PerInstitution, label: str) -> dict[str, int]:
    from app.core.features import is_enabled
    from app.db.session import PlatformSessionLocal, tenant_session
    from app.tasks.institution import _local_today_by_institution

    async with PlatformSessionLocal() as pdb:
        today_by_inst = await _local_today_by_institution(pdb)
        active = {
            iid
            for (iid,) in (
                await pdb.execute(text("SELECT id FROM institutions WHERE status = 'active' AND deleted_at IS NULL"))
            ).all()
        }
    total = 0
    for iid, today in today_by_inst.items():
        if iid not in active or not await is_enabled(iid, feature):
            continue
        db = await tenant_session(iid)
        try:
            total += await fn(db, iid, today)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - one tenant's failure must not stop the others
            await db.rollback()
            log.warning(f"{label}_failed", institution_id=str(iid), error=str(exc)[:300])
        finally:
            await db.close()
    log.info(label, count=total)
    return {"count": total}


@celery.task(name="beat.hr.leave_accrual", queue="scheduled")
def leave_accrual() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.leave_service import LeaveService

        return await LeaveService(db, None, institution_id=iid).accrue_month(today)

    return run_async(_for_institutions("hr.leaves", one, "hr_leave_accrual"))


@celery.task(name="beat.hr.leave_carry_forward", queue="scheduled")
def leave_carry_forward() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.leave_service import LeaveService

        service = LeaveService(db, None, institution_id=iid)
        start_month = await service.setting("hr", "leave_carry_forward_month") or 1
        if today.month != int(start_month) or today.day != 1:
            return 0
        return await service.carry_forward(today.year)

    return run_async(_for_institutions("hr.leaves", one, "hr_leave_carry_forward"))


@celery.task(name="beat.hr.document_expiry", queue="scheduled")
def document_expiry() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.repositories.staff_repository import StaffRecordsRepository
        from app.services.staff_service import StaffService

        service = StaffService(db, None, institution_id=iid)
        days = int(await service.setting("hr", "document_expiry_days") or 30)
        n = 0
        for doc, staff in await StaffRecordsRepository(db).expiring_documents(today, today + timedelta(days=days)):
            if doc.institution_id != iid:
                continue
            await service._notify(
                "hr.document_expiring",
                [staff.user_id],
                {
                    "doc_type": doc.doc_type,
                    "expires_on": doc.expires_on.isoformat() if doc.expires_on else "",
                    "staff_name": staff.full_name,
                },
                audience={"user_ids": [str(staff.user_id)] if staff.user_id else [], "roles": ["hr_officer"]},
            )
            n += 1
        return n

    return run_async(_for_institutions("hr.staff", one, "hr_document_expiry"))


@celery.task(name="beat.attendance.auto_mark_holidays", queue="scheduled")
def auto_mark_holidays() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.staff_attendance_service import StaffAttendanceService

        return await StaffAttendanceService(db, None, institution_id=iid).auto_mark_offs(today)

    return run_async(_for_institutions("attendance.staff", one, "attendance_auto_mark_holidays"))


@celery.task(name="beat.payroll.reminder", queue="scheduled")
def payroll_reminder() -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.payroll_service import PayrollService

        service = PayrollService(db, None, institution_id=iid)
        if today.day != int(await service.setting("payroll", "reminder_day") or 25):
            return 0
        return await service.reminder(today)

    return run_async(_for_institutions("hr.payroll", one, "payroll_reminder"))
