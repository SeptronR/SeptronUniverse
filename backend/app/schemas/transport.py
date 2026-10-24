"""Transport schemas — Prompts/21 §21.4 (OpenAPI names prefixed ``Transport`` / ``Vehicle`` where a generic name could
collide with another module)."""

import uuid
from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


PersonLit = Literal["student", "staff"]
DirectionLit = Literal["pickup", "drop"]


# ---- fleet ----------------------------------------------------------------------------------------------------------------
class VehicleIn(_Strict):
    college_id: uuid.UUID | None = None
    registration_no: str = Field(min_length=4, max_length=20)
    vehicle_type: Literal["bus", "minibus", "van", "car"] = "bus"
    capacity: int | None = Field(None, ge=1, le=120)
    make_model: str | None = Field(None, max_length=80)
    year: int | None = Field(None, ge=1980, le=2100)
    driver_staff_id: uuid.UUID | None = None
    insurance_expiry: date | None = None
    fitness_expiry: date | None = None
    permit_expiry: date | None = None
    puc_expiry: date | None = None


class VehicleUpdate(_Strict):
    college_id: uuid.UUID | None = None
    vehicle_type: Literal["bus", "minibus", "van", "car"] | None = None
    capacity: int | None = Field(None, ge=1, le=120)
    make_model: str | None = Field(None, max_length=80)
    year: int | None = Field(None, ge=1980, le=2100)
    driver_staff_id: uuid.UUID | None = None
    insurance_expiry: date | None = None
    fitness_expiry: date | None = None
    permit_expiry: date | None = None
    puc_expiry: date | None = None
    status: Literal["active", "maintenance"] | None = None
    version: int | None = None


class ComplianceChip(BaseModel):
    document: str
    expiry: date | None = None
    state: Literal["ok", "expiring", "expired", "missing"]
    days_left: int | None = None


class VehicleOut(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    registration_no: str
    vehicle_type: str
    capacity: int | None = None
    make_model: str | None = None
    year: int | None = None
    driver_staff_id: uuid.UUID | None = None
    driver_name: str | None = None
    insurance_expiry: date | None = None
    fitness_expiry: date | None = None
    permit_expiry: date | None = None
    puc_expiry: date | None = None
    gps_device_id: uuid.UUID | None = None
    status: str
    version: int
    compliance: list[ComplianceChip] = []
    chips: list[str] = []  # e.g. insurance_expiring, fitness_expired


class VehicleMaintenanceIn(_Strict):
    maintenance_type: str | None = Field(None, max_length=40)
    service_date: date
    odometer: int | None = Field(None, ge=0)
    cost_paise: int | None = Field(None, ge=0)
    vendor: str | None = Field(None, max_length=120)
    next_due_date: date | None = None
    notes: str | None = Field(None, max_length=2000)


class VehicleMaintenanceOut(BaseModel):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    maintenance_type: str | None = None
    service_date: date
    odometer: int | None = None
    cost_paise: int | None = None
    vendor: str | None = None
    next_due_date: date | None = None
    notes: str | None = None


class VehicleFuelIn(_Strict):
    filled_on: date
    litres: float = Field(gt=0, le=2000)
    cost_paise: int = Field(ge=0)
    odometer: int | None = Field(None, ge=0)


class VehicleFuelOut(BaseModel):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    filled_on: date
    litres: float | None = None
    cost_paise: int | None = None
    odometer: int | None = None
    filled_by: uuid.UUID | None = None


# ---- routes -----------------------------------------------------------------------------------------------------------------
class StopIn(_Strict):
    name: str = Field(min_length=1, max_length=120)
    sequence: int | None = Field(None, ge=1, le=200)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    pickup_time: time | None = None
    drop_time: time | None = None
    fee_paise: int | None = Field(None, ge=0)


class StopOut(BaseModel):
    id: uuid.UUID
    route_id: uuid.UUID
    name: str
    sequence: int
    lat: float | None = None
    lng: float | None = None
    pickup_time: time | None = None
    drop_time: time | None = None
    fee_paise: int | None = None
    effective_fee_paise: int = 0
    passengers: int = 0


class StopsReorder(_Strict):
    stop_ids: list[uuid.UUID] = Field(min_length=1)


class RouteIn(_Strict):
    college_id: uuid.UUID | None = None
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    vehicle_id: uuid.UUID | None = None
    distance_km: float | None = Field(None, ge=0, le=9999)
    fee_paise: int | None = Field(None, ge=0)
    stops: list[StopIn] = []


class RouteUpdate(_Strict):
    name: str | None = Field(None, min_length=2, max_length=120)
    vehicle_id: uuid.UUID | None = None
    distance_km: float | None = Field(None, ge=0, le=9999)
    fee_paise: int | None = Field(None, ge=0)
    is_active: bool | None = None


class RouteOut(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    code: str
    name: str
    vehicle_id: uuid.UUID | None = None
    vehicle_registration: str | None = None
    driver_name: str | None = None
    distance_km: float | None = None
    fee_paise: int | None = None
    is_active: bool
    capacity: int | None = None
    capacity_used: int = 0
    stops: list[StopOut] = []


class PublicRouteOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    stops: list[dict[str, Any]] = []


# ---- allocations ------------------------------------------------------------------------------------------------------------
class AllocationCreate(_Strict):
    person_type: PersonLit = "student"
    person_id: uuid.UUID
    route_id: uuid.UUID
    stop_id: uuid.UUID
    academic_year_id: uuid.UUID | None = None
    from_on: date | None = None
    to_on: date | None = None
    payroll_deduction: bool = False


class AllocationResponse(BaseModel):
    id: uuid.UUID
    person_type: str
    person_id: uuid.UUID
    person_name: str | None = None
    person_code: str | None = None
    department_code: str | None = None
    route_id: uuid.UUID
    route_code: str | None = None
    stop_id: uuid.UUID | None = None
    stop_name: str | None = None
    academic_year_id: uuid.UUID | None = None
    from_on: date | None = None
    to_on: date | None = None
    fee_paise: int = 0
    invoice_id: uuid.UUID | None = None
    fee_status: str | None = None
    status: str
    warning: str | None = None


class AllocationBulk(_Strict):
    route_id: uuid.UUID
    stop_id: uuid.UUID
    person_type: PersonLit = "student"
    person_ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)
    academic_year_id: uuid.UUID | None = None


class AllocationBulkReport(BaseModel):
    allocated: int = 0
    failed: list[dict[str, Any]] = []


class AllocationChange(_Strict):
    new_route_id: uuid.UUID
    new_stop_id: uuid.UUID
    effective_on: date


class AllocationAction(_Strict):
    reason: str | None = Field(None, max_length=500)


class TransportRequestCreate(_Strict):
    route_id: uuid.UUID
    stop_id: uuid.UUID


class TransportRequestDecision(_Strict):
    decision: Literal["approve", "reject"]
    remarks: str | None = Field(None, max_length=500)


class TripBrief(BaseModel):
    id: uuid.UUID
    direction: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None


class MyTransportResponse(BaseModel):
    allocation: AllocationResponse | None = None
    route: RouteOut | None = None
    stop: StopOut | None = None
    pickup_time: time | None = None
    drop_time: time | None = None
    vehicle: str | None = None
    driver_name: str | None = None
    live_available: bool = False
    today_trips: list[TripBrief] = []


# ---- trips --------------------------------------------------------------------------------------------------------------------
class TripScheduleRequest(_Strict):
    date_from: date
    date_to: date
    route_ids: list[uuid.UUID] | None = None


class TripScheduleSummary(BaseModel):
    created: int = 0
    skipped_days: list[date] = []
    blocked_vehicles: list[str] = []


class TripCreate(_Strict):
    route_id: uuid.UUID
    trip_date: date
    direction: DirectionLit = "pickup"
    vehicle_id: uuid.UUID | None = None
    driver_staff_id: uuid.UUID | None = None


class TripCancel(_Strict):
    reason: str = Field(min_length=2, max_length=500)


class TripOut(BaseModel):
    id: uuid.UUID
    route_id: uuid.UUID
    route_code: str | None = None
    vehicle_id: uuid.UUID
    vehicle_registration: str | None = None
    driver_staff_id: uuid.UUID | None = None
    driver_name: str | None = None
    trip_date: date
    direction: str
    status: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    stops_total: int = 0
    stops_done: int = 0
    progress_pct: int = 0
    next_stop: str | None = None
    delay_minutes: int | None = None
    boarded: int = 0
    manifest: int = 0
    km: float | None = None


class TripStartRequest(_Strict):
    odometer: int | None = Field(None, ge=0)
    vehicle_id: uuid.UUID | None = None


class TripEndRequest(_Strict):
    odometer: int | None = Field(None, ge=0)


class StopEventIn(_Strict):
    stop_id: uuid.UUID
    event: Literal["arrived", "departed"]
    at: datetime | None = None


class ManifestPassenger(BaseModel):
    person_type: str
    person_id: uuid.UUID
    name: str
    phone: str | None = None  # masked
    boarded: bool = False
    alighted: bool = False
    suspended: bool = False


class ManifestStop(BaseModel):
    stop_id: uuid.UUID
    stop: str
    sequence: int
    arrived_at: datetime | None = None
    departed_at: datetime | None = None
    passengers: list[ManifestPassenger] = []


class ManifestResponse(BaseModel):
    trip_id: uuid.UUID
    stops: list[ManifestStop] = []
    boarded: int = 0
    total: int = 0


class PassengerScanRequest(_Strict):
    qr: str | None = Field(None, max_length=500)
    person_id: uuid.UUID | None = None
    person_type: PersonLit = "student"
    event: Literal["board", "alight"] = "board"
    stop_id: uuid.UUID | None = None


class PassengerScanResponse(BaseModel):
    event_id: uuid.UUID
    person_name: str | None = None
    event: str
    stop_id: uuid.UUID | None = None
    occurred_at: datetime
    warning: str | None = None


# ---- GPS ----------------------------------------------------------------------------------------------------------------------
class GpsPing(_Strict):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    speed_kmh: float | None = Field(None, ge=0, le=250)
    heading: int | None = Field(None, ge=0, le=360)
    recorded_at: datetime


class GpsBatch(_Strict):
    trip_id: uuid.UUID | None = None
    pings: list[GpsPing] = Field(min_length=1, max_length=500)


class GpsIngestResult(BaseModel):
    accepted: int = 0
    duplicates: int = 0
    rate_limited: int = 0
    stop_events: int = 0
    alerts: list[str] = []


class LiveVehicle(BaseModel):
    vehicle_id: uuid.UUID
    registration_no: str | None = None
    route: str | None = None
    route_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    lat: float
    lng: float
    speed: float | None = None
    heading: int | None = None
    at: datetime
    next_stop: str | None = None
    eta_min: int | None = None
    deviation: bool = False


class TracePoint(BaseModel):
    lat: float
    lng: float
    at: datetime
    speed: float | None = None


class TraceResponse(BaseModel):
    trip_id: uuid.UUID
    points: list[TracePoint] = []
    total_points: int = 0
    km: float = 0.0


class GpsDeviceIn(_Strict):
    device_id: str = Field(min_length=2, max_length=60)
    vehicle_id: uuid.UUID | None = None


class GpsDeviceOut(BaseModel):
    id: uuid.UUID
    device_id: str
    vehicle_id: uuid.UUID | None = None
    vehicle_registration: str | None = None
    is_active: bool
    last_seen_at: datetime | None = None
    token: str | None = None  # returned once, on create / rotate


# ---- reports ----------------------------------------------------------------------------------------------------------------
class TransportJobAccepted(BaseModel):
    job_id: uuid.UUID


class RouteStatsResponse(BaseModel):
    vehicles: int = 0
    vehicles_active: int = 0
    routes: int = 0
    students: int = 0
    staff: int = 0
    occupancy_pct: float = 0.0
    cost_per_km: float | None = None
    on_time_pct: float | None = None
    trips_today: int = 0
    in_progress: int = 0
    delayed: int = 0
    compliance_alerts: int = 0


class TransportReport(BaseModel):
    kind: str
    columns: list[str] = []
    rows: list[dict[str, Any]] = []
