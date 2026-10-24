"""Library tasks — Prompts/19 §19.7.

Jobs (run as the requesting user): ``library.import_catalogue``, ``library.stock_verification``, ``library.koha_sync``,
``library.reports_export``. Consumers: ``library.provision_student`` / ``library.provision_staff`` on
``student.created`` / ``staff.created`` (member card with the type's rules), ``library.no_dues`` on
``no_dues.requested`` (auto sign-off of the library step), ``library.fine_paid`` on ``fees.payment_received``
(``source_type='library_fine'`` → re-evaluate the member's no-dues). Beat: ``library.overdue_scan`` (nightly 01:00 IST),
``library.reservation_expiry`` (hourly), ``library.eresource_expiry_reminders`` / ``library.membership_expiry``
(daily).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer


@celery.task(name="jobs.library.import_catalogue", queue="reports")
@job("library.import_catalogue", queue="reports")
async def import_catalogue(
    ctx: JobContext,
    db: Any,
    csv: str,
    mapping: dict[str, str] | None = None,
    copies_column: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    from app.services.library.catalogue_service import CatalogueService

    principal = await _principal(db, ctx)
    out = await CatalogueService(db, principal).import_csv(csv, mapping, copies_column)
    await ctx.progress(db, 100, f"{out.created} created / {out.updated} updated")
    return out.model_dump(mode="json")


@celery.task(name="jobs.library.stock_verification", queue="reports")
@job("library.stock_verification", queue="reports")
async def stock_verification(
    ctx: JobContext, db: Any, scanned_barcodes: list[str], location: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.library.operations_service import LibraryOpsService

    principal = await _principal(db, ctx)
    out = await LibraryOpsService(db, principal).stock_verification(location, scanned_barcodes)
    await ctx.progress(db, 100, f"{len(out.missing)} missing / {len(out.unexpected)} unexpected")
    return out.model_dump(mode="json")


@celery.task(name="jobs.library.koha_sync", queue="reports")
@job("library.koha_sync", queue="reports")
async def koha_sync(
    ctx: JobContext, db: Any, source: str = "koha", since: str | None = None, **_: Any
) -> dict[str, Any]:
    from app.services.library.operations_service import LibraryOpsService

    principal = await _principal(db, ctx)
    out = await LibraryOpsService(db, principal).sync(source, date.fromisoformat(since) if since else None)
    await ctx.progress(db, 100, f"{out.created} created / {out.updated} updated")
    return out.model_dump(mode="json")


@celery.task(name="jobs.library.reports_export", queue="reports")
@job("library.reports_export", queue="reports")
async def reports_export(ctx: JobContext, db: Any, kind: str, **_: Any) -> dict[str, Any]:
    from app.services.library.operations_service import LibraryOpsService

    principal = await _principal(db, ctx)
    out = await LibraryOpsService(db, principal).report_xlsx(kind)
    await ctx.progress(db, 100, f"{out['rows']} rows")
    return out


async def _on(iid: uuid.UUID) -> bool:
    from app.core.features import is_enabled

    return await is_enabled(iid, "library.core")


@consumer("library.provision_student", events=["student.created"])
async def provision_student(db: Any, event: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.models.students import Student
    from app.services.library.catalogue_service import MemberService

    iid = uuid.UUID(str(event["institution_id"]))
    sid = (event.get("payload") or {}).get("student_id")
    if not sid or not await _on(iid):
        return
    uid = (await db.execute(select(Student.user_id).where(Student.id == uuid.UUID(str(sid))))).scalar_one_or_none()
    if uid:
        await MemberService(db, None, institution_id=iid).provision(uid, "student")


@consumer("library.provision_staff", events=["staff.created"])
async def provision_staff(db: Any, event: dict[str, Any]) -> None:
    from sqlalchemy import select

    from app.models.hr import Staff
    from app.services.library.catalogue_service import MemberService

    iid = uuid.UUID(str(event["institution_id"]))
    sid = (event.get("payload") or {}).get("staff_id")
    if not sid or not await _on(iid):
        return
    row = (await db.execute(select(Staff.user_id, Staff.staff_category).where(Staff.id == uuid.UUID(str(sid))))).first()
    if row and row[0]:
        await MemberService(db, None, institution_id=iid).provision(
            row[0], "faculty" if (row[1] or "") == "teaching" else "staff"
        )


@consumer("library.no_dues", events=["no_dues.requested"])
async def no_dues(db: Any, event: dict[str, Any]) -> None:
    from app.services.library.circulation_service import CirculationService

    iid = uuid.UUID(str(event["institution_id"]))
    rid = (event.get("payload") or {}).get("request_id")
    if rid and await _on(iid):
        await CirculationService(db, None, institution_id=iid).sign_no_dues(uuid.UUID(str(rid)))


@consumer("library.fine_paid", events=["fees.payment_received"])
async def fine_paid(db: Any, event: dict[str, Any]) -> None:
    from app.services.library.circulation_service import CirculationService

    p = event.get("payload") or {}
    if p.get("source_type") != "library_fine" or not p.get("source_id"):
        return
    iid = uuid.UUID(str(event["institution_id"]))
    await CirculationService(db, None, institution_id=iid).member_fine_paid(uuid.UUID(str(p["source_id"])))


def _beat(fn_name: str, feature: str, label: str) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        from app.services.library.catalogue_service import MemberService
        from app.services.library.circulation_service import CirculationService
        from app.services.library.operations_service import LibraryOpsService

        if fn_name == "overdue":
            out = await CirculationService(db, None, institution_id=iid).overdue_scan()
            return int(out["marked"] + out["holds"])
        if fn_name == "reservations":
            return int(await CirculationService(db, None, institution_id=iid).expire_reservations())
        if fn_name == "eresources":
            return int(await LibraryOpsService(db, None, institution_id=iid).eresource_expiry_reminders())
        return int(await MemberService(db, None, institution_id=iid).membership_expiry())

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.library.overdue_scan", queue="scheduled")
def overdue_scan() -> dict[str, int]:
    return _beat("overdue", "library.core", "library_overdue_scan")


@celery.task(name="beat.library.reservation_expiry", queue="scheduled")
def reservation_expiry() -> dict[str, int]:
    return _beat("reservations", "library.core", "library_reservation_expiry")


@celery.task(name="beat.library.eresource_expiry_reminders", queue="scheduled")
def eresource_expiry_reminders() -> dict[str, int]:
    return _beat("eresources", "library.eresources", "library_eresource_expiry")


@celery.task(name="beat.library.membership_expiry", queue="scheduled")
def membership_expiry() -> dict[str, int]:
    return _beat("membership", "library.core", "library_membership_expiry")
