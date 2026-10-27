"""Facilities — Prompts/25 §25.8: room bookings {facilities.room_booking}, equipment {facilities.equipment_booking},
service desk {facilities.service_desk}, AMC {facilities.amc}, lost & found {facilities.lost_found}, visitor passes
{facilities.visitor_gate} and the facilities reports (XLSX jobs). Visibility is narrowed by the services.
"""

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.facilities import (
    FacAmcContractIn,
    FacAmcContractOut,
    FacAmcPerformance,
    FacAvailabilityOut,
    FacBookingDecision,
    FacEquipmentBookingCreate,
    FacEquipmentBookingOut,
    FacGateScan,
    FacHandover,
    FacJobAccepted,
    FacLostFoundClaim,
    FacLostFoundIn,
    FacLostFoundOut,
    FacRecurringBooking,
    FacRecurringResult,
    FacRoomBookingCreate,
    FacRoomBookingOut,
    FacServiceAssign,
    FacServiceDashboard,
    FacServiceNote,
    FacServiceRate,
    FacServiceRequestCreate,
    FacServiceRequestOut,
    FacServiceUpdate,
    FacVisitorPassCreate,
    FacVisitorPassOut,
)
from app.services.facilities.booking_service import BookingService
from app.services.facilities.common import visibility_scopes
from app.services.facilities.service_desk_service import ServiceDeskService
from app.services.facilities.visitor_service import VisitorService
from app.utils.response import ok

router = APIRouter(tags=["facilities"])

F = "facilities"
SELF = any_permission_required((F, "view"), (F, "book"), (F, "view_all"), (F, "manage"))
BOOK = any_permission_required((F, "book"), (F, "approve_booking"), (F, "manage"))
APPROVE = any_permission_required((F, "approve_booking"), (F, "manage"))
ASSIGN = any_permission_required((F, "service_assign"), (F, "manage"))
MANAGE = any_permission_required((F, "manage"))
READ_ALL = any_permission_required((F, "manage"), (F, "view_all"))
REPORTS = any_permission_required((F, "view_all"), (F, "manage"), ("events", "view_all"), ("reports", "export"))

ROOMS = [feature_required("facilities.room_booking")]
EQUIP = [feature_required("facilities.equipment_booking")]
DESK = [feature_required("facilities.service_desk")]
AMC = [feature_required("facilities.amc")]
LOST = [feature_required("facilities.lost_found")]
GATE = [feature_required("facilities.visitor_gate")]
CORE = [feature_required("facilities.service_desk")]


def _vis(principal: Principal, data: Any) -> dict[str, Any]:
    tabs = ["mine" if t == "self" else t for t in visibility_scopes(principal, "facilities")]
    res = ok(data)
    res["meta"]["visibility"] = {"self": True, "scopes": tabs, "default": tabs[-1] if tabs else "mine"}
    return res


# ---- rooms ----------------------------------------------------------------------------------------------------------------
@router.get(
    "/facilities/rooms/availability",
    summary="Room availability / conflicts",
    response_model=Envelope[FacAvailabilityOut],
    dependencies=ROOMS,
)
async def availability(
    request: Request,
    from_at: datetime,
    to_at: datetime,
    room_id: uuid.UUID | None = None,
    building_id: uuid.UUID | None = None,
    capacity_min: int | None = None,
    features: list[str] | None = Query(None),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await BookingService(db, principal, request).availability(
            from_at, to_at, room_id=room_id, building_id=building_id, capacity_min=capacity_min, features=features or []
        )
    )


@router.get(
    "/facilities/room-bookings",
    summary="Room bookings (scoped)",
    response_model=Envelope[list[FacRoomBookingOut]],
    dependencies=ROOMS,
)
async def bookings(
    request: Request,
    status: str | None = None,
    room_id: uuid.UUID | None = None,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(
        principal,
        await BookingService(db, principal, request).list_bookings(
            status=status, room_id=room_id, date_from=date_from, date_to=date_to
        ),
    )


@router.get(
    "/facilities/room-bookings/me",
    summary="My room bookings",
    response_model=Envelope[list[FacRoomBookingOut]],
    dependencies=ROOMS,
)
async def bookings_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).list_bookings(mine=True))


@router.post(
    "/facilities/room-bookings",
    status_code=201,
    summary="Request a room",
    response_model=Envelope[FacRoomBookingOut],
    dependencies=ROOMS,
)
async def booking_create(
    body: FacRoomBookingCreate,
    request: Request,
    principal: Principal = Depends(BOOK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).request_room(body), message="Requested")


@router.post(
    "/facilities/room-bookings/recurring",
    summary="Weekly recurring booking",
    response_model=Envelope[FacRecurringResult],
    dependencies=ROOMS,
)
async def booking_recurring(
    body: FacRecurringBooking,
    request: Request,
    principal: Principal = Depends(BOOK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).recurring(body))


@router.get(
    "/facilities/room-bookings/{id}", summary="Booking", response_model=Envelope[FacRoomBookingOut], dependencies=ROOMS
)
async def booking_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).get_booking(id))


@router.post(
    "/facilities/room-bookings/{id}/decide",
    summary="Approve / reject a booking",
    response_model=Envelope[FacRoomBookingOut],
    dependencies=ROOMS,
)
async def booking_decide(
    id: uuid.UUID,
    body: FacBookingDecision,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).decide(id, body))


@router.post(
    "/facilities/room-bookings/{id}/cancel",
    summary="Cancel a booking",
    response_model=Envelope[FacRoomBookingOut],
    dependencies=ROOMS,
)
async def booking_cancel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(BOOK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).cancel(id))


# ---- equipment ----------------------------------------------------------------------------------------------------------
@router.get(
    "/facilities/equipment-bookings",
    summary="Equipment bookings (scoped)",
    response_model=Envelope[list[FacEquipmentBookingOut]],
    dependencies=EQUIP,
)
async def eq_list(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(principal, await BookingService(db, principal, request).eq_list(status=status))


@router.get(
    "/facilities/equipment-bookings/me",
    summary="My equipment bookings",
    response_model=Envelope[list[FacEquipmentBookingOut]],
    dependencies=EQUIP,
)
async def eq_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).eq_list(mine=True))


@router.post(
    "/facilities/equipment-bookings",
    status_code=201,
    summary="Book equipment",
    response_model=Envelope[FacEquipmentBookingOut],
    dependencies=EQUIP,
)
async def eq_create(
    body: FacEquipmentBookingCreate,
    request: Request,
    principal: Principal = Depends(BOOK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).eq_request(body), message="Requested")


@router.post(
    "/facilities/equipment-bookings/{id}/decide",
    summary="Approve / reject",
    response_model=Envelope[FacEquipmentBookingOut],
    dependencies=EQUIP,
)
async def eq_decide(
    id: uuid.UUID,
    body: FacBookingDecision,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).eq_decide(id, body))


@router.post(
    "/facilities/equipment-bookings/{id}/handover",
    summary="Hand over",
    response_model=Envelope[FacEquipmentBookingOut],
    dependencies=EQUIP,
)
async def eq_handover(
    id: uuid.UUID,
    body: FacHandover,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).eq_handover(id, body, returning=False))


@router.post(
    "/facilities/equipment-bookings/{id}/return",
    summary="Return with condition",
    response_model=Envelope[FacEquipmentBookingOut],
    dependencies=EQUIP,
)
async def eq_return(
    id: uuid.UUID,
    body: FacHandover,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BookingService(db, principal, request).eq_handover(id, body, returning=True))


# ---- service desk -------------------------------------------------------------------------------------------------------
@router.get(
    "/facilities/service-requests",
    summary="Service requests (scoped)",
    response_model=Envelope[list[FacServiceRequestOut]],
    dependencies=DESK,
)
async def sr_list(
    request: Request,
    status: str | None = None,
    category: str | None = None,
    scope: str | None = None,
    breached: bool | None = None,
    q: str | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(
        principal,
        await ServiceDeskService(db, principal, request).list_requests(
            status=status, category=category, scope=scope, breached=breached, q=q
        ),
    )


@router.get(
    "/facilities/service-requests/me",
    summary="My tickets",
    response_model=Envelope[list[FacServiceRequestOut]],
    dependencies=DESK,
)
async def sr_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).list_requests(scope="mine"))


@router.post(
    "/facilities/service-requests",
    status_code=201,
    summary="Raise a ticket",
    response_model=Envelope[FacServiceRequestOut],
    dependencies=DESK,
)
async def sr_create(
    body: FacServiceRequestCreate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).create(body), message="Ticket raised")


@router.get(
    "/facilities/service-desk/dashboard",
    summary="Service desk dashboard",
    response_model=Envelope[FacServiceDashboard],
    dependencies=DESK,
)
async def sr_dashboard(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).dashboard())


@router.get(
    "/facilities/service-requests/{id}",
    summary="Ticket",
    response_model=Envelope[FacServiceRequestOut],
    dependencies=DESK,
)
async def sr_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).get(id))


@router.post(
    "/facilities/service-requests/{id}/assign",
    summary="Assign staff / vendor / AMC",
    response_model=Envelope[FacServiceRequestOut],
    dependencies=DESK,
)
async def sr_assign(
    id: uuid.UUID,
    body: FacServiceAssign,
    request: Request,
    principal: Principal = Depends(ASSIGN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).assign(id, body))


@router.post(
    "/facilities/service-requests/{id}/update",
    summary="Progress / cost",
    response_model=Envelope[FacServiceRequestOut],
    dependencies=DESK,
)
async def sr_update(
    id: uuid.UUID,
    body: FacServiceUpdate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).update(id, body))


@router.post(
    "/facilities/service-requests/{id}/resolve",
    summary="Resolve",
    response_model=Envelope[FacServiceRequestOut],
    dependencies=DESK,
)
async def sr_resolve(
    id: uuid.UUID,
    body: FacServiceUpdate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).resolve(id, body))


@router.post(
    "/facilities/service-requests/{id}/close",
    summary="Close (requester)",
    response_model=Envelope[FacServiceRequestOut],
    dependencies=DESK,
)
async def sr_close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).close(id))


@router.post(
    "/facilities/service-requests/{id}/reopen",
    summary="Reopen (requester, within the window)",
    response_model=Envelope[FacServiceRequestOut],
    dependencies=DESK,
)
async def sr_reopen(
    id: uuid.UUID,
    body: FacServiceNote,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).reopen(id, body.remarks))


@router.post(
    "/facilities/service-requests/{id}/rate",
    summary="Rate and close",
    response_model=Envelope[FacServiceRequestOut],
    dependencies=DESK,
)
async def sr_rate(
    id: uuid.UUID,
    body: FacServiceRate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).rate(id, body))


# ---- AMC -------------------------------------------------------------------------------------------------------------------
@router.get(
    "/facilities/amc-contracts",
    summary="AMC contracts",
    response_model=Envelope[list[FacAmcContractOut]],
    dependencies=AMC,
)
async def amc_list(
    request: Request, principal: Principal = Depends(READ_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).amc_list())


@router.post(
    "/facilities/amc-contracts",
    status_code=201,
    summary="Register an AMC contract",
    response_model=Envelope[FacAmcContractOut],
    dependencies=AMC,
)
async def amc_create(
    body: FacAmcContractIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).amc_save(body), message="Saved")


@router.put(
    "/facilities/amc-contracts/{id}",
    summary="Edit an AMC contract",
    response_model=Envelope[FacAmcContractOut],
    dependencies=AMC,
)
async def amc_update(
    id: uuid.UUID,
    body: FacAmcContractIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).amc_save(body, id))


@router.get(
    "/facilities/amc-contracts/{id}/performance",
    summary="Vendor performance under the contract",
    response_model=Envelope[FacAmcPerformance],
    dependencies=AMC,
)
async def amc_performance(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).amc_performance(id))


# ---- lost & found --------------------------------------------------------------------------------------------------------
@router.get(
    "/facilities/lost-found",
    summary="Lost & found register",
    response_model=Envelope[list[FacLostFoundOut]],
    dependencies=LOST,
)
async def lf_list(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).lf_list(status))


@router.post(
    "/facilities/lost-found",
    status_code=201,
    summary="Report a found item",
    response_model=Envelope[FacLostFoundOut],
    dependencies=LOST,
)
async def lf_report(
    body: FacLostFoundIn, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).lf_report(body), message="Reported")


@router.post(
    "/facilities/lost-found/{id}/claim",
    summary="Hand over to the claimant",
    response_model=Envelope[FacLostFoundOut],
    dependencies=LOST,
)
async def lf_claim(
    id: uuid.UUID,
    body: FacLostFoundClaim,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).lf_claim(id, body))


@router.post(
    "/facilities/lost-found/{id}/dispose",
    summary="Dispose after retention",
    response_model=Envelope[FacLostFoundOut],
    dependencies=LOST,
)
async def lf_dispose(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ServiceDeskService(db, principal, request).lf_dispose(id))


# ---- visitors ------------------------------------------------------------------------------------------------------------
@router.get(
    "/facilities/visitor-passes",
    summary="Visitor passes (host / gate)",
    response_model=Envelope[list[FacVisitorPassOut]],
    dependencies=GATE,
)
async def vp_list(
    request: Request,
    status: str | None = None,
    on: date | None = None,
    mine: bool = False,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await VisitorService(db, principal, request).list_passes(status=status, on=on, mine=mine))


@router.post(
    "/facilities/visitor-passes",
    status_code=201,
    summary="Pre-register / issue a pass",
    response_model=Envelope[FacVisitorPassOut],
    dependencies=GATE,
)
async def vp_create(
    body: FacVisitorPassCreate,
    request: Request,
    principal: Principal = Depends(BOOK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await VisitorService(db, principal, request).issue(body), message="Pass issued")


@router.post(
    "/facilities/visitor-passes/scan",
    summary="Gate scan in / out",
    response_model=Envelope[FacVisitorPassOut],
    dependencies=GATE,
)
async def vp_scan(
    body: FacGateScan, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VisitorService(db, principal, request).scan(body))


@router.get(
    "/facilities/visitor-passes/inside",
    summary="Visitors on campus now",
    response_model=Envelope[list[FacVisitorPassOut]],
    dependencies=GATE,
)
async def vp_inside(
    request: Request, principal: Principal = Depends(READ_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VisitorService(db, principal, request).inside())


@router.get(
    "/facilities/visitor-passes/register",
    summary="Daily visitor register",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=GATE,
)
async def vp_register(
    request: Request,
    on: date | None = Query(None, alias="date"),
    principal: Principal = Depends(READ_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = VisitorService(db, principal, request)
    return ok(await svc.register(on or await svc.today()))


@router.get(
    "/facilities/visitor-passes/{id}",
    summary="Visitor pass",
    response_model=Envelope[FacVisitorPassOut],
    dependencies=GATE,
)
async def vp_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VisitorService(db, principal, request).get(id))


# ---- reports -------------------------------------------------------------------------------------------------------------
REPORT_KINDS = ("events", "bookings", "service_desk", "visitors", "sports", "wallet")


@router.get(
    "/facilities/reports/{kind}",
    status_code=202,
    summary="Facilities report (XLSX job)",
    response_model=Envelope[FacJobAccepted],
    dependencies=CORE,
)
async def facilities_report(
    kind: str,
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(REPORTS),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    if kind not in REPORT_KINDS:
        raise APIError(404, ErrorCode.NOT_FOUND, f"Unknown report {kind!r}", {"kinds": list(REPORT_KINDS)})
    from app.services.reports.report_service import alias_params  # Phase 36: alias of POST /reports/run

    j = await enqueue(
        db,
        principal,
        "report.run",
        await alias_params(db, principal, f"facilities.{kind}", {"from": date_from, "to": date_to}),
    )
    return JSONResponse(
        status_code=202, content=ok(FacJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )
