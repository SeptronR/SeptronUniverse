"""Transport — Prompts/21 §21.8.

Each route carries its ``transport.*`` feature (``transport.gps_live`` for ingestion, live map, trace and devices);
visibility narrows in the services (own / wards / advisees / department / college / driver-owned / all; 404 otherwise,
403 for driver actions on trips that are not theirs). Passenger scans honour ``Idempotency-Key``; bulk allocation,
trip scheduling and XLSX reports answer ``202`` with a ``job_id``. ``public_router`` holds the GPS device ingest
(``X-Device-Token``; ``PUBLIC_ROUTES``; the feature is checked inside). Fixed paths precede parameterised ones.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.transport import (
    AllocationAction,
    AllocationBulk,
    AllocationChange,
    AllocationCreate,
    AllocationResponse,
    GpsBatch,
    GpsDeviceIn,
    GpsDeviceOut,
    GpsIngestResult,
    LiveVehicle,
    ManifestResponse,
    MyTransportResponse,
    PassengerScanRequest,
    PassengerScanResponse,
    PublicRouteOut,
    RouteIn,
    RouteOut,
    RouteStatsResponse,
    RouteUpdate,
    StopEventIn,
    StopIn,
    StopOut,
    StopsReorder,
    TraceResponse,
    TransportJobAccepted,
    TransportReport,
    TransportRequestCreate,
    TransportRequestDecision,
    TripCancel,
    TripCreate,
    TripEndRequest,
    TripOut,
    TripScheduleRequest,
    TripStartRequest,
    VehicleFuelIn,
    VehicleFuelOut,
    VehicleIn,
    VehicleMaintenanceIn,
    VehicleMaintenanceOut,
    VehicleOut,
    VehicleUpdate,
)
from app.services.transport.allocation_service import AllocationService
from app.services.transport.common import visibility_scopes
from app.services.transport.fleet_service import FleetService
from app.services.transport.gps_service import GpsService
from app.services.transport.reports_service import KINDS, TransportReportsService
from app.services.transport.route_service import RouteService
from app.services.transport.trip_service import TripService
from app.utils.response import ok

router = APIRouter(tags=["transport"])
public_router = APIRouter(tags=["transport"])

T = "transport"
MANAGE = any_permission_required((T, "manage"))
READ = any_permission_required((T, "manage"), (T, "view_all"))
FLEET = any_permission_required((T, "manage"), (T, "view_all"), (T, "driver"))
ALLOC = any_permission_required((T, "manage"), (T, "view_all"), (T, "view"))
SELF = any_permission_required((T, "view"), (T, "manage"))
DRIVER = any_permission_required((T, "driver"), (T, "manage"))
LIVE = any_permission_required((T, "view"), (T, "view_all"), (T, "manage"), (T, "driver"))
EXPORT = any_permission_required((T, "manage"), (T, "view_all"), ("reports", "export"))
INGEST = any_permission_required((T, "driver"), (T, "gps_ingest"))

CORE = [feature_required("transport.core")]
GPS = [feature_required("transport.gps_live")]


def _vis(principal: Principal, data: Any) -> dict[str, Any]:
    tabs = visibility_scopes(principal)
    res = ok(data)
    res.setdefault("meta", {})["visibility"] = {"self": True, "scopes": tabs, "default": tabs[-1] if tabs else "self"}
    return res


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(TransportJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


# ---- fleet ------------------------------------------------------------------------------------------------------------------
@router.get(
    "/transport/vehicles/compliance",
    summary="Expiring / expired vehicle documents",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=CORE,
)
async def compliance(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).compliance())


@router.get(
    "/transport/vehicles",
    summary="Vehicles (+ compliance chips)",
    response_model=Envelope[list[VehicleOut]],
    dependencies=CORE,
)
async def vehicles(
    request: Request,
    status: str | None = None,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(FLEET),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(principal, await FleetService(db, principal, request).list_vehicles(status, college_id))


@router.post("/transport/vehicles", summary="Add a vehicle", response_model=Envelope[VehicleOut], dependencies=CORE)
async def vehicle_create(
    body: VehicleIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).create(body))


@router.get("/transport/vehicles/{id}", summary="Vehicle", response_model=Envelope[VehicleOut], dependencies=CORE)
async def vehicle_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).get(id))


@router.put(
    "/transport/vehicles/{id}", summary="Edit a vehicle", response_model=Envelope[VehicleOut], dependencies=CORE
)
async def vehicle_update(
    id: uuid.UUID,
    body: VehicleUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).update(id, body))


@router.delete(
    "/transport/vehicles/{id}",
    summary="Delete a vehicle (no trips yet)",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def vehicle_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await FleetService(db, principal, request).delete(id)
    return ok({"id": str(id)})


@router.post(
    "/transport/vehicles/{id}/retire",
    summary="Retire a vehicle",
    response_model=Envelope[VehicleOut],
    dependencies=CORE,
)
async def vehicle_retire(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).retire(id))


@router.get(
    "/transport/vehicles/{id}/maintenance",
    summary="Maintenance log",
    response_model=Envelope[list[VehicleMaintenanceOut]],
    dependencies=CORE,
)
async def maintenance(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).maintenance(id))


@router.post(
    "/transport/vehicles/{id}/maintenance",
    summary="Add a maintenance entry",
    response_model=Envelope[VehicleMaintenanceOut],
    dependencies=CORE,
)
async def maintenance_add(
    id: uuid.UUID,
    body: VehicleMaintenanceIn,
    request: Request,
    principal: Principal = Depends(DRIVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).add_maintenance(id, body))


@router.get(
    "/transport/vehicles/{id}/fuel",
    summary="Fuel log",
    response_model=Envelope[list[VehicleFuelOut]],
    dependencies=CORE,
)
async def fuel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).fuel(id))


@router.post(
    "/transport/vehicles/{id}/fuel",
    summary="Add a fuel entry",
    response_model=Envelope[VehicleFuelOut],
    dependencies=CORE,
)
async def fuel_add(
    id: uuid.UUID,
    body: VehicleFuelIn,
    request: Request,
    principal: Principal = Depends(DRIVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FleetService(db, principal, request).add_fuel(id, body))


@router.get(
    "/transport/vehicles/{id}/costs",
    summary="Cost per km / km per litre",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def vehicle_costs(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = FleetService(db, principal, request)
    await svc.vehicle(id)
    return ok(await svc.cost_stats(id))


# ---- routes -------------------------------------------------------------------------------------------------------------------
@router.get(
    "/transport/routes/public",
    summary="Routes, stops and times (no vehicles)",
    response_model=Envelope[list[PublicRouteOut]],
    dependencies=CORE,
)
async def routes_public(
    request: Request, principal: Principal = Depends(LIVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RouteService(db, principal, request).public_routes())


@router.get(
    "/transport/routes", summary="Routes with stops", response_model=Envelope[list[RouteOut]], dependencies=CORE
)
async def routes(
    request: Request,
    college_id: uuid.UUID | None = None,
    active: bool | None = None,
    principal: Principal = Depends(FLEET),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(principal, await RouteService(db, principal, request).list_routes(college_id, active))


@router.post(
    "/transport/routes", summary="Create a route (+ stops)", response_model=Envelope[RouteOut], dependencies=CORE
)
async def route_create(
    body: RouteIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RouteService(db, principal, request).create(body))


@router.get("/transport/routes/{id}", summary="Route", response_model=Envelope[RouteOut], dependencies=CORE)
async def route_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RouteService(db, principal, request).get(id))


@router.put("/transport/routes/{id}", summary="Edit a route", response_model=Envelope[RouteOut], dependencies=CORE)
async def route_update(
    id: uuid.UUID,
    body: RouteUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RouteService(db, principal, request).update(id, body))


@router.delete(
    "/transport/routes/{id}", summary="Deactivate a route", response_model=Envelope[dict[str, Any]], dependencies=CORE
)
async def route_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await RouteService(db, principal, request).delete(id)
    return ok({"id": str(id)})


@router.get(
    "/transport/routes/{id}/stops",
    summary="Stops of a route",
    response_model=Envelope[list[StopOut]],
    dependencies=CORE,
)
async def stops(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RouteService(db, principal, request).stops(id))


@router.post(
    "/transport/routes/{id}/stops", summary="Add / insert a stop", response_model=Envelope[StopOut], dependencies=CORE
)
async def stop_add(
    id: uuid.UUID,
    body: StopIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RouteService(db, principal, request).add_stop(id, body))


@router.post(
    "/transport/routes/{id}/stops/reorder",
    summary="Reorder stops (renumbers 1..n)",
    response_model=Envelope[list[StopOut]],
    dependencies=CORE,
)
async def stops_reorder(
    id: uuid.UUID,
    body: StopsReorder,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RouteService(db, principal, request).reorder(id, body))


@router.get("/transport/routes/{id}/sheet.pdf", summary="Route sheet (PDF)", dependencies=CORE)
async def route_sheet(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> Response:
    from app.utils.pdf import simple_pdf

    title, lines = await RouteService(db, principal, request).sheet_lines(id)
    return Response(content=simple_pdf(lines, title=title), media_type="application/pdf")


@router.put("/transport/stops/{id}", summary="Edit a stop", response_model=Envelope[StopOut], dependencies=CORE)
async def stop_update(
    id: uuid.UUID,
    body: StopIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RouteService(db, principal, request).update_stop(id, body))


# ---- allocations --------------------------------------------------------------------------------------------------------------
async def _staff_gate(person_type: str | None, institution_id: Any) -> None:
    if person_type == "staff" and not await is_enabled(institution_id, "transport.staff"):
        raise APIError(403, ErrorCode.FEATURE_DISABLED, "Staff transport is disabled", {"feature": "transport.staff"})


@router.get(
    "/transport/allocations",
    summary="Allocations (scoped)",
    response_model=Envelope[list[AllocationResponse]],
    dependencies=CORE,
)
async def allocations(
    request: Request,
    route_id: uuid.UUID | None = None,
    status: str | None = None,
    person_type: str | None = Query(None, pattern="^(student|staff)$"),
    department_id: uuid.UUID | None = None,
    scope: str | None = Query(None, pattern="^(own|department|college|all)$"),
    principal: Principal = Depends(ALLOC),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _staff_gate(person_type, principal.institution_id)
    return _vis(
        principal,
        await AllocationService(db, principal, request).list_allocations(
            route_id, status, person_type, department_id, scope
        ),
    )


@router.post(
    "/transport/allocations",
    status_code=201,
    summary="Allocate a person to a route / stop",
    response_model=Envelope[AllocationResponse],
    dependencies=CORE,
)
async def allocate(
    body: AllocationCreate, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).allocate(body))


@router.post(
    "/transport/allocations/bulk",
    status_code=202,
    summary="Bulk allocation (job; partial-success report)",
    response_model=Envelope[TransportJobAccepted],
    dependencies=CORE,
)
async def allocate_bulk(
    body: AllocationBulk, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    await _staff_gate(body.person_type, principal.institution_id)
    return await _job(db, principal, "transport.bulk_allocate", body.model_dump(mode="json"))


@router.post(
    "/transport/allocations/{id}/change",
    summary="Change route / stop from a date",
    response_model=Envelope[AllocationResponse],
    dependencies=CORE,
)
async def allocation_change(
    id: uuid.UUID,
    body: AllocationChange,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).change(id, body))


@router.post(
    "/transport/allocations/{id}/{action}",
    summary="Suspend / close / reactivate",
    response_model=Envelope[AllocationResponse],
    dependencies=CORE,
)
async def allocation_status(
    id: uuid.UUID,
    action: str,
    request: Request,
    body: AllocationAction | None = None,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    status = {"suspend": "suspended", "close": "closed", "reactivate": "active"}.get(action)
    if status is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown action")
    return ok(await AllocationService(db, principal, request).set_status(id, status, body.reason if body else None))


@router.get(
    "/transport/me",
    summary="My route, stop, times and today's trips",
    response_model=Envelope[MyTransportResponse],
    dependencies=CORE,
)
async def me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).me())


@router.get(
    "/transport/wards",
    summary="My wards' transport",
    response_model=Envelope[list[MyTransportResponse]],
    dependencies=CORE,
)
async def wards(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).wards())


@router.post(
    "/transport/me/request",
    status_code=201,
    summary="Request an allocation / change",
    response_model=Envelope[AllocationResponse],
    dependencies=CORE,
)
async def me_request(
    body: TransportRequestCreate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).request_allocation(body))


@router.get(
    "/transport/me/requests",
    summary="My requests",
    response_model=Envelope[list[AllocationResponse]],
    dependencies=CORE,
)
async def me_requests(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).my_requests())


@router.get(
    "/transport/requests",
    summary="Allocation request queue",
    response_model=Envelope[list[AllocationResponse]],
    dependencies=CORE,
)
async def requests_queue(
    request: Request,
    status: str | None = "pending",
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).requests(status))


@router.post(
    "/transport/requests/{id}/decide",
    summary="Approve / reject a request",
    response_model=Envelope[AllocationResponse],
    dependencies=CORE,
)
async def request_decide(
    id: uuid.UUID,
    body: TransportRequestDecision,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AllocationService(db, principal, request).decide(id, body))


# ---- trips -----------------------------------------------------------------------------------------------------------------------
@router.post(
    "/transport/trips/schedule",
    status_code=202,
    summary="Schedule trips for working days (job)",
    response_model=Envelope[TransportJobAccepted],
    dependencies=CORE,
)
async def trips_schedule(
    body: TripScheduleRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _job(db, principal, "transport.schedule_trips", body.model_dump(mode="json"))


@router.get("/transport/trips", summary="Trips of a day", response_model=Envelope[list[TripOut]], dependencies=CORE)
async def trips(
    request: Request,
    on: date | None = Query(None, alias="date"),
    route_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).list_trips(on, route_id, status))


@router.post(
    "/transport/trips", status_code=201, summary="Ad-hoc trip", response_model=Envelope[TripOut], dependencies=CORE
)
async def trip_create(
    body: TripCreate, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).create(body))


@router.get(
    "/transport/driver/trips", summary="My trips (driver)", response_model=Envelope[list[TripOut]], dependencies=CORE
)
async def driver_trips(
    request: Request,
    on: date | None = Query(None, alias="date"),
    principal: Principal = Depends(DRIVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).driver_trips(on))


@router.get("/transport/trips/{id}", summary="Trip", response_model=Envelope[TripOut], dependencies=CORE)
async def trip_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).get(id))


@router.post(
    "/transport/trips/{id}/cancel",
    summary="Cancel a trip (notifies passengers)",
    response_model=Envelope[TripOut],
    dependencies=CORE,
)
async def trip_cancel(
    id: uuid.UUID,
    body: TripCancel,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).cancel(id, body))


@router.post(
    "/transport/trips/{id}/start", summary="Start a trip (driver)", response_model=Envelope[TripOut], dependencies=CORE
)
async def trip_start(
    id: uuid.UUID,
    body: TripStartRequest,
    request: Request,
    principal: Principal = Depends(DRIVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).start(id, body))


@router.post(
    "/transport/trips/{id}/end", summary="End a trip (driver)", response_model=Envelope[TripOut], dependencies=CORE
)
async def trip_end(
    id: uuid.UUID,
    body: TripEndRequest,
    request: Request,
    principal: Principal = Depends(DRIVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).end(id, body))


@router.post(
    "/transport/trips/{id}/stop-event",
    summary="Stop arrived / departed (driver)",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def trip_stop_event(
    id: uuid.UUID,
    body: StopEventIn,
    request: Request,
    principal: Principal = Depends(DRIVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).stop_event(id, body))


@router.get(
    "/transport/trips/{id}/manifest",
    summary="Passenger manifest per stop (masked phones)",
    response_model=Envelope[ManifestResponse],
    dependencies=CORE,
)
async def trip_manifest(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FLEET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TripService(db, principal, request).manifest(id))


@router.post(
    "/transport/trips/{id}/passenger-scan",
    summary="Board / alight scan (Idempotency-Key)",
    response_model=Envelope[PassengerScanResponse],
    dependencies=CORE,
)
async def trip_scan(
    id: uuid.UUID,
    body: PassengerScanRequest,
    request: Request,
    _key: str | None = Depends(idempotency_key),
    principal: Principal = Depends(DRIVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await TripService(db, principal, request).passenger_scan(id, body)
    response = ok(out.model_dump(mode="json"), message="Recorded")
    await store(request, response, db)
    return response


@router.get(
    "/transport/trips/{id}/trace",
    summary="Trip trace (JSON or GPX)",
    response_model=Envelope[TraceResponse],
    dependencies=GPS,
)
async def trip_trace(
    id: uuid.UUID,
    request: Request,
    format: str = Query("json", pattern="^(json|gpx)$"),
    principal: Principal = Depends(LIVE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = GpsService(db, principal, request)
    tr = await svc.trace(id)
    if format == "gpx":
        return Response(
            content=svc.gpx(tr),
            media_type="application/gpx+xml",
            headers={"Content-Disposition": f'attachment; filename="trip-{id}.gpx"'},
        )
    return ok(tr)


# ---- GPS / live ----------------------------------------------------------------------------------------------------------------
@router.post(
    "/transport/gps/ingest",
    summary="GPS batch from the driver app (JWT)",
    response_model=Envelope[GpsIngestResult],
    dependencies=GPS,
)
async def gps_ingest(
    body: GpsBatch, request: Request, principal: Principal = Depends(INGEST), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GpsService(db, principal, request).ingest_driver(body))


@public_router.post(
    "/transport/gps/device-ingest",
    summary="GPS batch from a fitted device (X-Device-Token)",
    response_model=Envelope[GpsIngestResult],
)
async def gps_device_ingest(
    body: GpsBatch, x_device_token: str = Header(..., alias="X-Device-Token"), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.db.session import bind_tenant, set_tenant
    from app.services.transport.gps_service import token_institution

    iid = await token_institution(x_device_token)
    if iid is None:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid device token")
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "transport.gps_live"):
        raise APIError(
            403,
            ErrorCode.FEATURE_DISABLED,
            "Feature 'transport.gps_live' is not enabled",
            {"feature": "transport.gps_live"},
        )
    svc = GpsService(db, None, None, iid)
    device = await svc.device_for_token(db, x_device_token)
    if device is None:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid device token")
    return ok(await svc.ingest_device(device, body))


@router.get(
    "/transport/live",
    summary="Live vehicle positions (scoped)",
    response_model=Envelope[list[LiveVehicle]],
    dependencies=GPS,
)
async def live(
    request: Request,
    route_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    principal: Principal = Depends(LIVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GpsService(db, principal, request).live(route_id, vehicle_id))


@router.get(
    "/transport/gps-devices", summary="GPS devices", response_model=Envelope[list[GpsDeviceOut]], dependencies=GPS
)
async def devices(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GpsService(db, principal, request).devices())


@router.post(
    "/transport/gps-devices",
    status_code=201,
    summary="Register a GPS device (token shown once)",
    response_model=Envelope[GpsDeviceOut],
    dependencies=GPS,
)
async def device_create(
    body: GpsDeviceIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GpsService(db, principal, request).create_device(body))


@router.post(
    "/transport/gps-devices/{id}/rotate-token",
    summary="Rotate a device token",
    response_model=Envelope[GpsDeviceOut],
    dependencies=GPS,
)
async def device_rotate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GpsService(db, principal, request).rotate(id))


@router.delete(
    "/transport/gps-devices/{id}",
    summary="Deactivate a device",
    response_model=Envelope[dict[str, Any]],
    dependencies=GPS,
)
async def device_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await GpsService(db, principal, request).delete_device(id)
    return ok({"id": str(id)})


# ---- reports -----------------------------------------------------------------------------------------------------------------------
@router.get(
    "/transport/stats", summary="Transport dashboard", response_model=Envelope[RouteStatsResponse], dependencies=CORE
)
async def stats(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TransportReportsService(db, principal, request).stats())


@router.get(
    "/transport/reports/{kind}",
    summary="Transport report (JSON inline, XLSX job)",
    response_model=Envelope[TransportReport],
    dependencies=CORE,
)
async def report(
    kind: str,
    request: Request,
    format: str = Query("json", pattern="^(json|xlsx)$"),
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if kind not in KINDS:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
    if format == "xlsx":
        return await _job(db, principal, "transport.reports_export", {"kind": kind})
    return ok(await TransportReportsService(db, principal, request).report(kind))
