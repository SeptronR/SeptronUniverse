"""Hostel, mess & staff accommodation — Prompts/20 §20.8.

Each route carries its ``hostel.*`` feature; visibility narrows in the services (own / wards / advisees / department /
warden-owned hostels / college / all; 404 otherwise, 403 for operations on a hostel that is not the caller's).
Applications and leaves honour ``Idempotency-Key``; the allotment run, mess bill run and registers answer ``202`` with a
``job_id`` (the allotment dry run answers inline). Fixed paths precede parameterised ones.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.hostel import (
    AllotmentRunRequest,
    AllotmentRunSummary,
    BedStatusChange,
    CheckInRequest,
    ConsentOtpVerify,
    DisciplineCreate,
    DisciplineOut,
    EvictRequest,
    GateScanBatch,
    GateScanRequest,
    GateScanResponse,
    HostelAllocationResponse,
    HostelApplicationCreate,
    HostelApplicationResponse,
    HostelBedOut,
    HostelBlockIn,
    HostelBlockOut,
    HostelComplaintCreate,
    HostelComplaintOut,
    HostelComplaintRate,
    HostelComplaintUpdate,
    HostelFeePlanIn,
    HostelFeePlanOut,
    HostelIn,
    HostelJobAccepted,
    HostelLeaveCreate,
    HostelLeaveDecision,
    HostelLeaveResponse,
    HostelOut,
    HostelRoomIn,
    HostelRoomOut,
    HostelTransferRequest,
    HostelUpdate,
    HostelVisitorIn,
    HostelVisitorOut,
    ManualAllotRequest,
    MarkReturned,
    MessAttendanceBulk,
    MessAttendanceMark,
    MessAttendanceResult,
    MessAttendanceRow,
    MessBillResponse,
    MessBillRunRequest,
    MessPlanIn,
    MessPlanOut,
    MessSubscribe,
    MessSubscriptionOut,
    OccupancyResponse,
    QuarterAllocate,
    QuarterIn,
    QuarterOut,
    QuarterVacate,
    RebateDecision,
    RebateOut,
    RebateRequest,
    RollCallCreate,
    RollCallEntriesUpdate,
    RollCallOut,
    RoomBulkCreate,
    RoomChangeCreate,
    RoomChangeDecision,
    RoomChangeResponse,
    VacateRequest,
    VacateResponse,
)
from app.services.hostel.allocation_service import AllocationService
from app.services.hostel.common import visibility_scopes
from app.services.hostel.leave_service import LeaveService
from app.services.hostel.life_service import HostelLifeService
from app.services.hostel.mess_service import MessService
from app.services.hostel.quarters_service import QuartersService
from app.services.hostel.structure_service import StructureService
from app.utils.response import ok

router = APIRouter(tags=["hostel"])

H = "hostel"
ANY = any_permission_required(
    (H, "view"),
    (H, "view_all"),
    (H, "manage"),
    (H, "self"),
    (H, "warden"),
    (H, "allot"),
    (H, "gate"),
    (H, "mess_manage"),
    (H, "roll_call"),
    (H, "discipline"),
)
READ = any_permission_required((H, "view"), (H, "view_all"), (H, "manage"), (H, "warden"), (H, "allot"))
MANAGE = any_permission_required(
    (H, "manage"),
)
ALLOT = any_permission_required((H, "allot"), (H, "manage"))
WARDEN = any_permission_required((H, "warden"), (H, "allot"), (H, "manage"))
SELF = any_permission_required((H, "self"), (H, "view"), (H, "manage"))
GATE = any_permission_required((H, "gate"), (H, "warden"), (H, "manage"))
ROLL = any_permission_required((H, "roll_call"), (H, "warden"), (H, "manage"))
MESS = any_permission_required((H, "mess_manage"), (H, "self"), (H, "view"), (H, "warden"), (H, "manage"))
DISC = any_permission_required(
    (H, "discipline"), (H, "warden"), (H, "view_all"), (H, "manage"), (H, "self"), (H, "view")
)
QUARTERS_SELF = any_permission_required((H, "self"), (H, "view"), (H, "manage"), ("payroll", "self"))

CORE = [feature_required("hostel.core")]
MESSF = [feature_required("hostel.mess")]
BILL = [feature_required("hostel.mess_billing")]
LEAVE = [feature_required("hostel.leave_outpass")]
GATEF = [feature_required("hostel.gate_qr")]
ROLLF = [feature_required("hostel.night_roll_call")]
RCF = [feature_required("hostel.room_change")]
VIS = [feature_required("hostel.visitors")]
COMP = [feature_required("hostel.complaints")]
DISCF = [feature_required("hostel.discipline")]
QTR = [feature_required("hostel.staff_quarters")]


def _vis(principal: Principal, data: Any) -> dict[str, Any]:
    tabs = visibility_scopes(principal)
    res = ok(data)
    res.setdefault("meta", {})["visibility"] = {"self": True, "scopes": tabs, "default": tabs[0] if tabs else "self"}
    return res


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(HostelJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


async def _idem(request: Request, db: AsyncSession, out: Any, message: str) -> dict[str, Any]:
    response = ok(out.model_dump(mode="json"), message=message)
    await store(request, response, db)
    return response


# ---- structure --------------------------------------------------------------------------------------------------------------
@router.get(
    "/hostels/me/rules", summary="Rules of my hostel", response_model=Envelope[dict[str, Any]], dependencies=CORE
)
async def my_rules(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.hostel import Hostel

    allocs = [a for a in await AllocationService(db, principal, request).me() if a.status in ("allotted", "checked_in")]
    if not allocs:
        raise APIError(404, ErrorCode.NOT_FOUND, "No active hostel allocation")
    h = (await db.execute(select(Hostel).where(Hostel.id == allocs[0].hostel_id))).scalar_one()
    return ok({"hostel": h.name, "rules": await StructureService(db, principal, request).rules_text(h)})


@router.get(
    "/hostels/reports/{kind}",
    status_code=202,
    summary="Register export (job → XLSX)",
    response_model=Envelope[HostelJobAccepted],
    dependencies=CORE,
)
async def reports(
    kind: str,
    request: Request,
    hostel_id: uuid.UUID | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if kind not in ("occupancy", "fees", "roll_call", "leaves", "mess", "visitors", "discipline"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
    return await _job(
        db, principal, "hostel.registers_export", {"kind": kind, "hostel_id": str(hostel_id) if hostel_id else None}
    )


@router.get(
    "/hostels", summary="Hostels (own / college / all)", response_model=Envelope[list[HostelOut]], dependencies=CORE
)
async def hostels(
    request: Request,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(principal, await StructureService(db, principal, request).list_hostels(college_id))


@router.post("/hostels", summary="Create a hostel", response_model=Envelope[HostelOut], dependencies=CORE)
async def hostel_create(
    body: HostelIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).create(body))


@router.get("/hostels/{id}", summary="Hostel", response_model=Envelope[HostelOut], dependencies=CORE)
async def hostel_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).get(id))


@router.put("/hostels/{id}", summary="Edit a hostel", response_model=Envelope[HostelOut], dependencies=CORE)
async def hostel_update(
    id: uuid.UUID,
    body: HostelUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).update(id, body))


@router.delete("/hostels/{id}", summary="Delete a hostel", response_model=Envelope[dict[str, Any]], dependencies=CORE)
async def hostel_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await StructureService(db, principal, request).delete(id)
    return ok({"id": str(id)})


@router.get(
    "/hostels/{id}/occupancy",
    summary="Blocks → rooms → beds with residents",
    response_model=Envelope[OccupancyResponse],
    dependencies=CORE,
)
async def occupancy(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).occupancy(id))


@router.get("/hostels/{id}/rules.pdf", summary="Hostel rules (PDF)", dependencies=CORE)
async def rules_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ANY), db: AsyncSession = Depends(get_db)
) -> Response:
    from sqlalchemy import select

    from app.models.hostel import Hostel
    from app.utils.pdf import simple_pdf

    h = (
        await db.execute(select(Hostel).where(Hostel.id == id, Hostel.institution_id == principal.institution_id))
    ).scalar_one_or_none()
    if h is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Hostel not found")
    lines = await StructureService(db, principal, request).rules_text(h)
    return Response(content=simple_pdf(lines, title=f"{h.name} rules"), media_type="application/pdf")


@router.get("/hostels/{id}/blocks", summary="Blocks", response_model=Envelope[list[HostelBlockOut]], dependencies=CORE)
async def blocks(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).blocks(id))


@router.post("/hostels/{id}/blocks", summary="Add a block", response_model=Envelope[HostelBlockOut], dependencies=CORE)
async def block_create(
    id: uuid.UUID,
    body: HostelBlockIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).create_block(id, body))


@router.post(
    "/hostels/{id}/rooms/bulk",
    summary="Generate rooms + beds",
    response_model=Envelope[dict[str, int]],
    dependencies=CORE,
)
async def rooms_bulk(
    id: uuid.UUID,
    body: RoomBulkCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await StructureService(db, principal, request).bulk_rooms(id, body)
    return ok(out, message=f"{out['rooms']} rooms / {out['beds']} beds")


@router.get("/hostel-rooms/{id}", summary="Room", response_model=Envelope[HostelRoomOut], dependencies=CORE)
async def room_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).get_room(id))


@router.put("/hostel-rooms/{id}", summary="Edit a room", response_model=Envelope[HostelRoomOut], dependencies=CORE)
async def room_update(
    id: uuid.UUID,
    body: HostelRoomIn,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).update_room(id, body))


@router.put(
    "/hostel-beds/{id}/status", summary="Block / free a bed", response_model=Envelope[HostelBedOut], dependencies=CORE
)
async def bed_status(
    id: uuid.UUID,
    body: BedStatusChange,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).bed_status(id, body))


@router.get(
    "/hostel-fee-plans", summary="Fee plans", response_model=Envelope[list[HostelFeePlanOut]], dependencies=CORE
)
async def fee_plans(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    academic_year_id: uuid.UUID | None = None,
    principal: Principal = Depends(ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).fee_plans(hostel_id, academic_year_id))


@router.post(
    "/hostel-fee-plans",
    summary="Create / update a fee plan",
    response_model=Envelope[HostelFeePlanOut],
    dependencies=CORE,
)
async def fee_plan_create(
    body: HostelFeePlanIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).save_fee_plan(body))


@router.put(
    "/hostel-fee-plans/{id}", summary="Edit a fee plan", response_model=Envelope[HostelFeePlanOut], dependencies=CORE
)
async def fee_plan_update(
    id: uuid.UUID,
    body: HostelFeePlanIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).save_fee_plan(body, id))


# ---- applications ---------------------------------------------------------------------------------------------------------
@router.post(
    "/hostel-applications",
    summary="Apply (Idempotency-Key)",
    response_model=Envelope[HostelApplicationResponse],
    dependencies=CORE,
)
async def apply(
    body: HostelApplicationCreate,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await AllocationService(db, principal, request).apply(body), "Applied")


@router.get(
    "/hostel-applications/me",
    summary="My applications",
    response_model=Envelope[list[HostelApplicationResponse]],
    dependencies=CORE,
)
async def my_applications(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).my_applications())


@router.post(
    "/hostel-applications/allot",
    status_code=202,
    summary="Allotment run (job; dry_run inline)",
    response_model=Envelope[AllotmentRunSummary],
    dependencies=CORE,
)
async def allot(
    body: AllotmentRunRequest,
    request: Request,
    principal: Principal = Depends(ALLOT),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    if body.dry_run:
        out = await AllocationService(db, principal, request).run_allotment(body)
        return JSONResponse(status_code=202, content=ok(out.model_dump(mode="json"), message="Dry run"))
    return await _job(db, principal, "hostel.allotment_run", body.model_dump(mode="json"))


@router.get(
    "/hostel-applications",
    summary="Applications",
    response_model=Envelope[list[HostelApplicationResponse]],
    dependencies=CORE,
)
async def applications(
    request: Request,
    year: uuid.UUID | None = None,
    hostel_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).list_applications(year, hostel_id, status))


@router.delete(
    "/hostel-applications/{id}",
    summary="Cancel my application",
    response_model=Envelope[HostelApplicationResponse],
    dependencies=CORE,
)
async def app_cancel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).cancel_application(id))


@router.post(
    "/hostel-applications/{id}/allot-manual",
    summary="Allot a bed manually",
    response_model=Envelope[HostelAllocationResponse],
    dependencies=CORE,
)
async def allot_manual(
    id: uuid.UUID,
    body: ManualAllotRequest,
    request: Request,
    principal: Principal = Depends(ALLOT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).manual_allot(id, body))


@router.post(
    "/hostel-applications/{id}/decline",
    summary="Decline",
    response_model=Envelope[HostelApplicationResponse],
    dependencies=CORE,
)
async def app_decline(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ALLOT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).decline(id))


# ---- allocations ------------------------------------------------------------------------------------------------------------
@router.get(
    "/hostel-allocations/me",
    summary="My allocation(s)",
    response_model=Envelope[list[HostelAllocationResponse]],
    dependencies=CORE,
)
async def alloc_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).me())


@router.get(
    "/hostel-allocations/wards",
    summary="My wards' allocations",
    response_model=Envelope[list[HostelAllocationResponse]],
    dependencies=CORE,
)
async def alloc_wards(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).me(wards=True))


@router.post(
    "/hostel-allocations/me/vacate-request",
    summary="Ask the warden to vacate",
    response_model=Envelope[HostelAllocationResponse],
    dependencies=CORE,
)
async def vacate_request(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).vacate_request(), message="Warden notified")


@router.get(
    "/hostel-allocations",
    summary="Allocations",
    response_model=Envelope[list[HostelAllocationResponse]],
    dependencies=CORE,
)
async def allocations(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    status: str | None = None,
    department_id: uuid.UUID | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(
        principal, await AllocationService(db, principal, request).list_allocations(hostel_id, status, department_id)
    )


@router.get(
    "/hostel-allocations/{id}",
    summary="Allocation",
    response_model=Envelope[HostelAllocationResponse],
    dependencies=CORE,
)
async def alloc_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ANY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).get(id))


@router.post(
    "/hostel-allocations/{id}/check-in",
    summary="Check in",
    response_model=Envelope[HostelAllocationResponse],
    dependencies=CORE,
)
async def check_in(
    id: uuid.UUID,
    body: CheckInRequest,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).check_in(id, body), message="Checked in")


@router.post(
    "/hostel-allocations/{id}/transfer",
    summary="Transfer to another bed",
    response_model=Envelope[HostelAllocationResponse],
    dependencies=CORE,
)
async def transfer(
    id: uuid.UUID,
    body: HostelTransferRequest,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).transfer(id, body), message="Transferred")


@router.post(
    "/hostel-allocations/{id}/vacate",
    summary="Vacate (damages → no-dues → deposit refund)",
    response_model=Envelope[VacateResponse],
    dependencies=CORE,
)
async def vacate(
    id: uuid.UUID,
    body: VacateRequest,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).vacate(id, body), message="Vacated")


@router.post(
    "/hostel-allocations/{id}/evict",
    summary="Propose / apply eviction",
    response_model=Envelope[HostelAllocationResponse],
    dependencies=CORE,
)
async def evict(
    id: uuid.UUID,
    body: EvictRequest,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).evict(id, body))


# ---- room change ------------------------------------------------------------------------------------------------------------
@router.get(
    "/room-change-requests",
    summary="Room change requests",
    response_model=Envelope[list[RoomChangeResponse]],
    dependencies=RCF,
)
async def room_changes(
    request: Request, status: str | None = None, principal: Principal = Depends(ANY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).room_changes(status))


@router.post(
    "/room-change-requests",
    summary="Request a room change",
    response_model=Envelope[RoomChangeResponse],
    dependencies=RCF,
)
async def room_change_create(
    body: RoomChangeCreate, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).request_room_change(body))


@router.post(
    "/room-change-requests/{id}/decide",
    summary="Decide (warden)",
    response_model=Envelope[RoomChangeResponse],
    dependencies=RCF,
)
async def room_change_decide(
    id: uuid.UUID,
    body: RoomChangeDecision,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).decide_room_change(id, body))


# ---- roll call ----------------------------------------------------------------------------------------------------------------
@router.get(
    "/hostel-roll-calls/report",
    summary="Roll-call report",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=ROLLF,
)
async def roll_report(
    hostel_id: uuid.UUID,
    request: Request,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    principal: Principal = Depends(ROLL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = HostelLifeService(db, principal, request)
    today = await svc.today()
    from datetime import timedelta

    return ok(await svc.roll_call_report(hostel_id, from_ or today - timedelta(days=30), to or today))


@router.get("/hostel-roll-calls", summary="Roll-calls", response_model=Envelope[list[RollCallOut]], dependencies=ROLLF)
async def roll_calls(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    on_date: date | None = None,
    principal: Principal = Depends(ROLL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).roll_calls(hostel_id, on_date))


@router.post(
    "/hostel-roll-calls", summary="Start tonight's roll-call", response_model=Envelope[RollCallOut], dependencies=ROLLF
)
async def roll_create(
    body: RollCallCreate, request: Request, principal: Principal = Depends(ROLL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).create_roll_call(body))


@router.put(
    "/hostel-roll-calls/{id}/entries",
    summary="Mark entries (bulk)",
    response_model=Envelope[RollCallOut],
    dependencies=ROLLF,
)
async def roll_mark(
    id: uuid.UUID,
    body: RollCallEntriesUpdate,
    request: Request,
    principal: Principal = Depends(ROLL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).mark(id, body))


# ---- mess -----------------------------------------------------------------------------------------------------------------------
@router.get("/mess-plans", summary="Mess plans", response_model=Envelope[list[MessPlanOut]], dependencies=MESSF)
async def mess_plans(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).plans(hostel_id))


@router.post("/mess-plans", summary="Create a mess plan", response_model=Envelope[MessPlanOut], dependencies=MESSF)
async def mess_plan_create(
    body: MessPlanIn, request: Request, principal: Principal = Depends(MESS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).save_plan(body))


@router.put("/mess-plans/{id}", summary="Edit a mess plan", response_model=Envelope[MessPlanOut], dependencies=MESSF)
async def mess_plan_update(
    id: uuid.UUID,
    body: MessPlanIn,
    request: Request,
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).save_plan(body, id))


@router.get(
    "/mess-subscriptions",
    summary="Subscriptions (own, or the hostel's for the mess office)",
    response_model=Envelope[list[MessSubscriptionOut]],
    dependencies=MESSF,
)
async def mess_subs(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    mine: bool = False,
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).subscriptions(hostel_id, mine=mine))


@router.post(
    "/mess-subscriptions", summary="Subscribe", response_model=Envelope[MessSubscriptionOut], dependencies=MESSF
)
async def mess_subscribe(
    body: MessSubscribe, request: Request, principal: Principal = Depends(MESS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).subscribe(body))


@router.post(
    "/mess-subscriptions/{id}/change",
    summary="Change plan (effective next month)",
    response_model=Envelope[MessSubscriptionOut],
    dependencies=MESSF,
)
async def mess_change(
    id: uuid.UUID,
    body: MessSubscribe,
    request: Request,
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).change(id, body.mess_plan_id))


@router.post(
    "/mess-subscriptions/{id}/close", summary="Close", response_model=Envelope[MessSubscriptionOut], dependencies=MESSF
)
async def mess_close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MESS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).close(id))


@router.post(
    "/mess-attendance",
    summary="Mark meals (single or bulk; qr / rfid / manual)",
    response_model=Envelope[MessAttendanceResult],
    dependencies=MESSF,
)
async def mess_mark(
    body: MessAttendanceBulk | MessAttendanceMark,
    request: Request,
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    items = body.items if isinstance(body, MessAttendanceBulk) else [body]
    return ok(await MessService(db, principal, request).mark(items))


@router.get(
    "/mess-attendance", summary="Meal attendance", response_model=Envelope[list[MessAttendanceRow]], dependencies=MESSF
)
async def mess_attendance(
    request: Request,
    subscription_id: uuid.UUID | None = None,
    date_: date | None = Query(None, alias="date"),
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).attendance(subscription_id, date_))


@router.post("/mess-rebates", summary="Request a rebate", response_model=Envelope[RebateOut], dependencies=MESSF)
async def rebate_create(
    body: RebateRequest, request: Request, principal: Principal = Depends(MESS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).request_rebate(body))


@router.get("/mess-rebates", summary="Rebate requests", response_model=Envelope[list[RebateOut]], dependencies=MESSF)
async def rebates(
    request: Request,
    status: str | None = None,
    mine: bool = False,
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).rebates(status, mine=mine))


@router.post(
    "/mess-rebates/{id}/decide", summary="Decide a rebate", response_model=Envelope[RebateOut], dependencies=MESSF
)
async def rebate_decide(
    id: uuid.UUID,
    body: RebateDecision,
    request: Request,
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).decide_rebate(id, body))


@router.post(
    "/mess-bills/run",
    status_code=202,
    summary="Monthly bill run (job)",
    response_model=Envelope[HostelJobAccepted],
    dependencies=BILL,
)
async def bill_run(
    body: MessBillRunRequest, request: Request, principal: Principal = Depends(MESS), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    if not MessService(db, principal, request).manager():
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "hostel:mess_manage required")
    return await _job(db, principal, "mess.bill_run", body.model_dump(mode="json"))


@router.get(
    "/mess-bills/me", summary="My mess bills", response_model=Envelope[list[MessBillResponse]], dependencies=BILL
)
async def bills_me(
    request: Request, principal: Principal = Depends(MESS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).bills(None, None, mine=True))


@router.get("/mess-bills", summary="Mess bills", response_model=Envelope[list[MessBillResponse]], dependencies=BILL)
async def bills(
    request: Request,
    month: date | None = None,
    hostel_id: uuid.UUID | None = None,
    principal: Principal = Depends(MESS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MessService(db, principal, request).bills(month, hostel_id))


@router.get("/mess-bills/{id}.pdf", summary="Mess bill PDF", dependencies=BILL)
async def bill_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MESS), db: AsyncSession = Depends(get_db)
) -> Response:
    return Response(content=await MessService(db, principal, request).bill_pdf(id), media_type="application/pdf")


# ---- visitors ----------------------------------------------------------------------------------------------------------------------
@router.get(
    "/hostel-visitors/register",
    status_code=202,
    summary="Monthly visitor register (job → XLSX)",
    response_model=Envelope[HostelJobAccepted],
    dependencies=VIS,
)
async def visitor_register(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    month: date | None = None,
    principal: Principal = Depends(GATE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _job(
        db,
        principal,
        "hostel.registers_export",
        {"kind": "visitors", "hostel_id": str(hostel_id) if hostel_id else None},
    )


@router.get("/hostel-visitors", summary="Visitors", response_model=Envelope[list[HostelVisitorOut]], dependencies=VIS)
async def visitors(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    month: date | None = None,
    principal: Principal = Depends(ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).visitors(hostel_id, month))


@router.post(
    "/hostel-visitors", summary="Log a visitor in", response_model=Envelope[HostelVisitorOut], dependencies=VIS
)
async def visitor_in(
    body: HostelVisitorIn, request: Request, principal: Principal = Depends(GATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).log_visitor(body))


@router.post(
    "/hostel-visitors/{id}/out",
    summary="Log a visitor out",
    response_model=Envelope[HostelVisitorOut],
    dependencies=VIS,
)
async def visitor_out(
    id: uuid.UUID, request: Request, principal: Principal = Depends(GATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).visitor_out(id))


# ---- leaves & gate --------------------------------------------------------------------------------------------------------------
@router.post(
    "/hostel-leaves",
    summary="Request leave / out-pass (Idempotency-Key)",
    response_model=Envelope[HostelLeaveResponse],
    dependencies=LEAVE,
)
async def leave_create(
    body: HostelLeaveCreate,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await LeaveService(db, principal, request).create(body), "Requested")


@router.get(
    "/hostel-leaves/me", summary="My leaves", response_model=Envelope[list[HostelLeaveResponse]], dependencies=LEAVE
)
async def leaves_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).me())


@router.get(
    "/hostel-leaves/wards",
    summary="My wards' leaves",
    response_model=Envelope[list[HostelLeaveResponse]],
    dependencies=LEAVE,
)
async def leaves_wards(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).me(wards=True))


@router.get(
    "/hostel-leaves",
    summary="Leaves (warden queue)",
    response_model=Envelope[list[HostelLeaveResponse]],
    dependencies=LEAVE,
)
async def leaves(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    status: str | None = None,
    date_: date | None = Query(None, alias="date"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(principal, await LeaveService(db, principal, request).list_leaves(hostel_id, status, date_))


@router.delete(
    "/hostel-leaves/{id}", summary="Cancel my leave", response_model=Envelope[HostelLeaveResponse], dependencies=LEAVE
)
async def leave_cancel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).cancel(id))


@router.post(
    "/hostel-leaves/{id}/consent/send-otp",
    summary="Send the guardian OTP",
    response_model=Envelope[dict[str, Any]],
    dependencies=LEAVE,
)
async def consent_send(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).send_otp(id))


@router.post(
    "/hostel-leaves/{id}/consent/verify",
    summary="Verify the guardian OTP",
    response_model=Envelope[HostelLeaveResponse],
    dependencies=LEAVE,
)
async def consent_verify(
    id: uuid.UUID,
    body: ConsentOtpVerify,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).verify_otp(id, body.otp))


@router.post(
    "/hostel-leaves/{id}/consent/parent-approve",
    summary="Guardian approves in the app",
    response_model=Envelope[HostelLeaveResponse],
    dependencies=LEAVE,
)
async def consent_parent(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).parent_approve(id))


@router.post(
    "/hostel-leaves/{id}/decide",
    summary="Approve / reject (warden)",
    response_model=Envelope[HostelLeaveResponse],
    dependencies=LEAVE,
)
async def leave_decide(
    id: uuid.UUID,
    body: HostelLeaveDecision,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).decide(id, body))


@router.post(
    "/hostel-leaves/{id}/mark-returned",
    summary="Mark returned manually",
    response_model=Envelope[HostelLeaveResponse],
    dependencies=LEAVE,
)
async def leave_returned(
    id: uuid.UUID,
    body: MarkReturned,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).mark_returned(id, body))


@router.post(
    "/hostel-gate/scan", summary="Gate scan (out / in)", response_model=Envelope[GateScanResponse], dependencies=GATEF
)
async def gate_scan(
    body: GateScanRequest, request: Request, principal: Principal = Depends(GATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).gate_scan(body))


@router.post(
    "/hostel-gate/scan-batch",
    summary="Offline gate scans (device times)",
    response_model=Envelope[list[GateScanResponse]],
    dependencies=GATEF,
)
async def gate_batch(
    body: GateScanBatch, request: Request, principal: Principal = Depends(GATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).gate_batch(body.scans))


@router.get(
    "/hostel-gate/late-list",
    summary="Late / absconding",
    response_model=Envelope[list[HostelLeaveResponse]],
    dependencies=GATEF,
)
async def late_list(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    principal: Principal = Depends(GATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).late_list(hostel_id))


@router.get(
    "/hostel-gate/out-now",
    summary="Residents out now",
    response_model=Envelope[list[HostelLeaveResponse]],
    dependencies=GATEF,
)
async def out_now(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    principal: Principal = Depends(GATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).out_now(hostel_id))


# ---- complaints / discipline ----------------------------------------------------------------------------------------------------
@router.get(
    "/hostel-complaints", summary="Complaints", response_model=Envelope[list[HostelComplaintOut]], dependencies=COMP
)
async def complaints(
    request: Request,
    hostel_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).complaints(hostel_id, status))


@router.post(
    "/hostel-complaints", summary="Raise a complaint", response_model=Envelope[HostelComplaintOut], dependencies=COMP
)
async def complaint_create(
    body: HostelComplaintCreate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).create_complaint(body))


@router.put(
    "/hostel-complaints/{id}",
    summary="Update status (warden)",
    response_model=Envelope[HostelComplaintOut],
    dependencies=COMP,
)
async def complaint_update(
    id: uuid.UUID,
    body: HostelComplaintUpdate,
    request: Request,
    principal: Principal = Depends(WARDEN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).update_complaint(id, body))


@router.post(
    "/hostel-complaints/{id}/rate",
    summary="Rate the resolution",
    response_model=Envelope[HostelComplaintOut],
    dependencies=COMP,
)
async def complaint_rate(
    id: uuid.UUID,
    body: HostelComplaintRate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).rate_complaint(id, body))


@router.get(
    "/hostel-discipline/me",
    summary="My hostel discipline records",
    response_model=Envelope[list[DisciplineOut]],
    dependencies=DISCF,
)
async def discipline_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).discipline(mine=True))


@router.get(
    "/hostel-discipline/wards",
    summary="My wards' records",
    response_model=Envelope[list[DisciplineOut]],
    dependencies=DISCF,
)
async def discipline_wards(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).discipline(wards=True))


@router.get(
    "/hostel-discipline", summary="Discipline records", response_model=Envelope[list[DisciplineOut]], dependencies=DISCF
)
async def discipline(
    request: Request, principal: Principal = Depends(DISC), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).discipline())


@router.post(
    "/hostel-discipline", summary="Record an incident", response_model=Envelope[DisciplineOut], dependencies=DISCF
)
async def discipline_create(
    body: DisciplineCreate, request: Request, principal: Principal = Depends(DISC), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await HostelLifeService(db, principal, request).record(body))


# ---- staff quarters ----------------------------------------------------------------------------------------------------------------
@router.get("/staff-quarters/me", summary="My quarter", response_model=Envelope[list[QuarterOut]], dependencies=QTR)
async def quarters_me(
    request: Request, principal: Principal = Depends(QUARTERS_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await QuartersService(db, principal, request).me())


@router.get("/staff-quarters", summary="Quarters", response_model=Envelope[list[QuarterOut]], dependencies=QTR)
async def quarters(
    request: Request,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QuartersService(db, principal, request).list_quarters(college_id))


@router.post("/staff-quarters", summary="Add a quarter", response_model=Envelope[QuarterOut], dependencies=QTR)
async def quarter_create(
    body: QuarterIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await QuartersService(db, principal, request).save(body))


@router.put("/staff-quarters/{id}", summary="Edit a quarter", response_model=Envelope[QuarterOut], dependencies=QTR)
async def quarter_update(
    id: uuid.UUID,
    body: QuarterIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QuartersService(db, principal, request).save(body, id))


@router.post(
    "/staff-quarters/{id}/allocate",
    summary="Allocate (rent deduction to payroll)",
    response_model=Envelope[QuarterOut],
    dependencies=QTR,
)
async def quarter_allocate(
    id: uuid.UUID,
    body: QuarterAllocate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QuartersService(db, principal, request).allocate(id, body))


@router.post(
    "/staff-quarter-allocations/{id}/vacate",
    summary="Vacate a quarter",
    response_model=Envelope[QuarterOut],
    dependencies=QTR,
)
async def quarter_vacate(
    id: uuid.UUID,
    body: QuarterVacate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QuartersService(db, principal, request).vacate(id, body))
