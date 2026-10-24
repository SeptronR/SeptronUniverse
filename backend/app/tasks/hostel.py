"""Hostel tasks — Prompts/20 §20.7.

Jobs (run as the requesting user): ``hostel.allotment_run``, ``mess.bill_run``, ``hostel.registers_export``.
Consumers: ``hostel.no_dues`` on ``no_dues.requested`` (auto sign-off of the hostel step), ``hostel.payment`` on
``fees.payment_received`` (hostel / mess / fine invoices → re-evaluate open no-dues). Payroll: remuneration hook
``staff_quarter`` adds a monthly rent ``deduction`` line for open quarter allocations with ``rent_deduction``. Beat:
``hostel.roll_call_autoclose`` (nightly), ``hostel.absconding_scan`` (hourly), ``hostel.allotment_lapse`` /
``hostel.waitlist_promote`` (nightly), ``mess.bill_run`` (1st of the month, previous month), ``hostel.leave_reminders``
(every 30 min).
"""

import uuid
from datetime import date, timedelta
from typing import Any

from app.core.aio import run_async
from app.core.hr_hooks import RemunerationLine, remuneration_source
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer

HOSTEL_SOURCES = ("hostel_allocation", "hostel_caution_deposit", "mess_subscription", "hostel_disciplinary")


@celery.task(name="jobs.hostel.allotment_run", queue="reports")
@job("hostel.allotment_run", queue="reports")
async def allotment_run(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.schemas.hostel import AllotmentRunRequest
    from app.services.hostel.allocation_service import AllocationService

    principal = await _principal(db, ctx)
    body = AllotmentRunRequest(**{k: v for k, v in params.items() if k in AllotmentRunRequest.model_fields})
    out = await AllocationService(db, principal).run_allotment(body)
    await ctx.progress(db, 100, f"{out.allotted} allotted / {out.waitlisted} waitlisted")
    return out.model_dump(mode="json")


@celery.task(name="jobs.mess.bill_run", queue="reports")
@job("mess.bill_run", queue="reports")
async def bill_run(ctx: JobContext, db: Any, month: str, hostel_id: str | None = None, **_: Any) -> dict[str, Any]:
    from app.services.hostel.mess_service import MessService

    principal = await _principal(db, ctx)
    out = await MessService(db, principal).bill_run(
        date.fromisoformat(month), uuid.UUID(hostel_id) if hostel_id else None
    )
    await ctx.progress(db, 100, f"{out.bills} bill(s)")
    return out.model_dump(mode="json")


@celery.task(name="jobs.hostel.registers_export", queue="reports")
@job("hostel.registers_export", queue="reports")
async def registers_export(
    ctx: JobContext, db: Any, kind: str, hostel_id: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.hostel.life_service import HostelLifeService

    principal = await _principal(db, ctx)
    out = await HostelLifeService(db, principal).report_xlsx(kind, uuid.UUID(hostel_id) if hostel_id else None)
    await ctx.progress(db, 100, f"{out['rows']} rows")
    return out


async def _on(iid: uuid.UUID) -> bool:
    from app.core.features import is_enabled

    return await is_enabled(iid, "hostel.core")


@consumer("hostel.no_dues", events=["no_dues.requested"])
async def no_dues(db: Any, event: dict[str, Any]) -> None:
    from app.services.hostel.allocation_service import AllocationService

    iid = uuid.UUID(str(event["institution_id"]))
    rid = (event.get("payload") or {}).get("request_id")
    if rid and await _on(iid):
        await AllocationService(db, None, institution_id=iid).sign_no_dues(uuid.UUID(str(rid)))


@consumer("hostel.payment", events=["fees.payment_received"])
async def payment(db: Any, event: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.models.fees import FeeInvoice
    from app.services.hostel.allocation_service import AllocationService

    p = event.get("payload") or {}
    if p.get("source_type") not in HOSTEL_SOURCES or not p.get("invoice_id"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    enrol = (
        await db.execute(
            select(FeeInvoice.student_program_enrollment_id).where(FeeInvoice.id == uuid.UUID(str(p["invoice_id"])))
        )
    ).scalar_one_or_none()
    if enrol:
        await AllocationService(db, None, institution_id=iid).reevaluate(enrol)


@remuneration_source("staff_quarter")
async def staff_quarter_lines(db: Any, staff: Any, month: int, year: int) -> list[RemunerationLine]:
    """Rent deduction for every open (or month-overlapping) quarter allocation with ``rent_deduction``."""
    from sqlalchemy import select

    from app.core.features import is_enabled
    from app.models.hostel import StaffQuarter, StaffQuarterAllocation

    if not await is_enabled(staff.institution_id, "hostel.staff_quarters"):
        return []
    first = date(year, month, 1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    rows = (
        await db.execute(
            select(StaffQuarterAllocation, StaffQuarter)
            .join(StaffQuarter, StaffQuarter.id == StaffQuarterAllocation.quarter_id)
            .where(
                StaffQuarterAllocation.staff_id == staff.id,
                StaffQuarterAllocation.rent_deduction.is_(True),
                StaffQuarterAllocation.from_on <= last,
                (StaffQuarterAllocation.to_on.is_(None)) | (StaffQuarterAllocation.to_on >= first),
            )
        )
    ).all()
    return [
        RemunerationLine(
            label=f"Quarter rent {q.unit_code} ({first:%b %Y})",
            amount_paise=int(q.rent_paise),
            source_type="staff_quarter",
            source_id=a.id,
            component_type="deduction",
        )
        for a, q in rows
        if q.rent_paise
    ]


def _beat(fn_name: str, feature: str, label: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.hostel.allocation_service import AllocationService
        from app.services.hostel.leave_service import LeaveService
        from app.services.hostel.life_service import HostelLifeService
        from app.services.hostel.mess_service import MessService

        if fn_name == "rollcall":
            return int(await HostelLifeService(db, None, institution_id=iid).autoclose())
        if fn_name == "absconding":
            return int(await LeaveService(db, None, institution_id=iid).absconding_scan())
        if fn_name == "lapse":
            return int(await AllocationService(db, None, institution_id=iid).lapse_unpaid())
        if fn_name == "promote":
            return int(await AllocationService(db, None, institution_id=iid).promote_waitlist())
        if fn_name == "bills":
            prev = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            return int((await MessService(db, None, institution_id=iid).bill_run(prev)).bills)
        return int(await LeaveService(db, None, institution_id=iid).return_reminders())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.hostel.roll_call_autoclose", queue="scheduled")
def roll_call_autoclose() -> dict[str, int]:
    return _beat("rollcall", "hostel.night_roll_call", "hostel_roll_call_autoclose")


@celery.task(name="beat.hostel.absconding_scan", queue="scheduled")
def absconding_scan() -> dict[str, int]:
    return _beat("absconding", "hostel.leave_outpass", "hostel_absconding_scan")


@celery.task(name="beat.hostel.allotment_lapse", queue="scheduled")
def allotment_lapse() -> dict[str, int]:
    return _beat("lapse", "hostel.core", "hostel_allotment_lapse")


@celery.task(name="beat.hostel.waitlist_promote", queue="scheduled")
def waitlist_promote() -> dict[str, int]:
    return _beat("promote", "hostel.core", "hostel_waitlist_promote")


@celery.task(name="beat.mess.bill_run", queue="scheduled")
def mess_bill_run() -> dict[str, int]:
    return _beat("bills", "hostel.mess_billing", "mess_bill_run")


@celery.task(name="beat.hostel.leave_reminders", queue="scheduled")
def leave_reminders() -> dict[str, int]:
    return _beat("reminders", "hostel.leave_outpass", "hostel_leave_reminders")
