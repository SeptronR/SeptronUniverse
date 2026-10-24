"""Hostel, mess & staff accommodation schemas — Prompts/20 §20.4 (OpenAPI names prefixed ``Hostel`` / ``Mess`` where a
generic name already exists)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


RoomTypeLit = Literal["single", "double", "triple", "dorm"]


# ---- structure -------------------------------------------------------------------------------------------------------------
class HostelIn(_Strict):
    college_id: uuid.UUID
    name: str = Field(min_length=2, max_length=120)
    hostel_type: Literal["boys", "girls", "coed", "pg", "international", "staff"]
    warden_staff_id: uuid.UUID | None = None
    address: dict[str, Any] | None = None
    is_active: bool = True


class HostelUpdate(_Strict):
    name: str | None = Field(None, min_length=2, max_length=120)
    hostel_type: Literal["boys", "girls", "coed", "pg", "international", "staff"] | None = None
    warden_staff_id: uuid.UUID | None = None
    address: dict[str, Any] | None = None
    mess_id: uuid.UUID | None = None
    is_active: bool | None = None


class HostelOut(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID
    name: str
    hostel_type: str
    warden_staff_id: uuid.UUID | None = None
    warden_name: str | None = None
    capacity: int
    occupied: int = 0
    allotted: int = 0
    vacant: int = 0
    blocks: int = 0
    mess_id: uuid.UUID | None = None
    is_active: bool


class HostelBlockIn(_Strict):
    name: str = Field(min_length=1, max_length=40)
    floors: int = Field(1, ge=1, le=50)


class HostelBlockOut(BaseModel):
    id: uuid.UUID
    hostel_id: uuid.UUID
    name: str
    floors: int
    rooms: int = 0


class RoomBulkCreate(_Strict):
    block_id: uuid.UUID
    floor_from: int = Field(ge=0, le=50)
    floor_to: int = Field(ge=0, le=50)
    rooms_per_floor: int = Field(ge=1, le=100)
    room_type: RoomTypeLit = "double"
    capacity: int | None = Field(None, ge=1, le=20)
    number_pattern: str = Field("{floor}{seq:02}", max_length=40)
    has_ac: bool = False


class HostelRoomIn(_Strict):
    room_type: RoomTypeLit | None = None
    has_ac: bool | None = None
    amenities: list[str] | None = None
    status: Literal["available", "full", "maintenance", "blocked"] | None = None


class HostelBedOut(BaseModel):
    id: uuid.UUID
    bed_label: str
    status: str
    allocation_id: uuid.UUID | None = None
    resident: str | None = None
    registration_number: str | None = None


class HostelRoomOut(BaseModel):
    id: uuid.UUID
    block_id: uuid.UUID
    room_number: str
    floor: int | None = None
    capacity: int
    room_type: str
    has_ac: bool
    status: str
    beds: list[HostelBedOut] = []


class BedStatusChange(_Strict):
    status: Literal["vacant", "blocked"]


class OccupancyBlock(BaseModel):
    id: uuid.UUID
    name: str
    rooms: list[HostelRoomOut]


class OccupancyResponse(BaseModel):
    hostel: HostelOut
    blocks: list[OccupancyBlock]
    totals: dict[str, int]


class HostelFeePlanIn(_Strict):
    hostel_id: uuid.UUID
    room_type: RoomTypeLit
    academic_year_id: uuid.UUID
    fee_per_term_paise: int = Field(ge=0)
    caution_deposit_paise: int = Field(0, ge=0)
    mess_advance_paise: int = Field(0, ge=0)


class HostelFeePlanOut(BaseModel):
    id: uuid.UUID
    hostel_id: uuid.UUID
    room_type: str
    academic_year_id: uuid.UUID
    fee_per_term_paise: int
    caution_deposit_paise: int
    mess_advance_paise: int


# ---- applications / allocations ---------------------------------------------------------------------------------------------
class HostelStudentRef(BaseModel):
    enrollment_id: uuid.UUID
    student_id: uuid.UUID | None = None
    name: str | None = None
    registration_number: str | None = None
    gender: str | None = None
    program_code: str | None = None


class HostelApplicationCreate(_Strict):
    academic_year_id: uuid.UUID | None = None
    hostel_preference: list[uuid.UUID] = Field(min_length=1, max_length=5)
    room_type_pref: RoomTypeLit | None = None
    distance_km: float | None = Field(None, ge=0, le=20000)
    enrollment_id: uuid.UUID | None = None


class HostelApplicationResponse(BaseModel):
    id: uuid.UUID
    student: HostelStudentRef
    academic_year_id: uuid.UUID
    hostel_preference: list[uuid.UUID] = []
    room_type_pref: str | None = None
    distance_km: float | None = None
    priority_score: float | None = None
    status: str
    position: int | None = None
    allocation_id: uuid.UUID | None = None
    created_at: datetime


class AllotmentRunRequest(_Strict):
    hostel_ids: list[uuid.UUID] | None = None
    college_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID | None = None
    dry_run: bool = False


class AllotmentRunSummary(BaseModel):
    dry_run: bool
    considered: int = 0
    allotted: int = 0
    waitlisted: int = 0
    by_hostel: dict[str, int] = {}
    job_id: uuid.UUID | None = None


class ManualAllotRequest(_Strict):
    bed_id: uuid.UUID


class HostelAllocationResponse(BaseModel):
    id: uuid.UUID
    student: HostelStudentRef
    hostel_id: uuid.UUID
    hostel: str | None = None
    room_number: str | None = None
    bed_label: str | None = None
    bed_id: uuid.UUID
    academic_year_id: uuid.UUID
    from_on: date
    to_on: date | None = None
    status: str
    fee_invoice_id: uuid.UUID | None = None
    fee_status: str | None = None
    caution_deposit_invoice_id: uuid.UUID | None = None
    deposit_status: str | None = None
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    room_condition: dict[str, Any] | None = None


class CheckInRequest(_Strict):
    room_condition: dict[str, Any] = Field(default_factory=dict)
    inventory: list[str] = Field(default_factory=list, max_length=50)


class HostelTransferRequest(_Strict):
    new_bed_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)


class DamageItem(BaseModel):
    item: str = Field(min_length=1, max_length=120)
    amount_paise: int = Field(ge=0)


class VacateRequest(_Strict):
    room_condition: dict[str, Any] = Field(default_factory=dict)
    damages: list[DamageItem] = Field(default_factory=list, max_length=30)
    vacate_on: date | None = None


class VacateResponse(BaseModel):
    allocation: HostelAllocationResponse
    no_dues_request_id: uuid.UUID | None = None
    damages_invoice_id: uuid.UUID | None = None


class EvictRequest(_Strict):
    reason: str = Field(min_length=5, max_length=1000)
    disciplinary_record_id: uuid.UUID | None = None


class RoomChangeCreate(_Strict):
    requested_bed_id: uuid.UUID | None = None
    reason: str = Field(min_length=3, max_length=1000)


class RoomChangeDecision(_Strict):
    approve: bool = True
    bed_id: uuid.UUID | None = None
    remarks: str | None = Field(None, max_length=500)


class RoomChangeResponse(BaseModel):
    id: uuid.UUID
    allocation_id: uuid.UUID
    student: HostelStudentRef | None = None
    requested_bed_id: uuid.UUID | None = None
    reason: str | None = None
    status: str
    created_at: datetime


# ---- roll call ---------------------------------------------------------------------------------------------------------------
class RollCallCreate(_Strict):
    hostel_id: uuid.UUID
    on_date: date | None = None


class RollCallEntryMark(BaseModel):
    allocation_id: uuid.UUID
    status: Literal["present", "absent", "on_leave"]


class RollCallEntriesUpdate(_Strict):
    entries: list[RollCallEntryMark] = Field(min_length=1, max_length=2000)


class RollCallEntryOut(BaseModel):
    allocation_id: uuid.UUID
    student: HostelStudentRef
    room_number: str | None = None
    status: str


class RollCallOut(BaseModel):
    id: uuid.UUID
    hostel_id: uuid.UUID
    on_date: date
    taken_at: datetime
    counts: dict[str, int] = {}
    entries: list[RollCallEntryOut] = []


# ---- mess -----------------------------------------------------------------------------------------------------------------------
class MessPlanIn(_Strict):
    hostel_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=80)
    diet: Literal["veg", "nonveg", "jain", "special"] = "veg"
    monthly_fee_paise: int = Field(ge=0)
    menu: dict[str, Any] | None = None
    is_active: bool = True


class MessPlanOut(BaseModel):
    id: uuid.UUID
    hostel_id: uuid.UUID | None = None
    name: str
    diet: str
    monthly_fee_paise: int
    menu: dict[str, Any] | None = None
    is_active: bool
    subscribers: int = 0


class MessSubscribe(_Strict):
    mess_plan_id: uuid.UUID
    from_on: date | None = None
    enrollment_id: uuid.UUID | None = None


class MessSubscriptionOut(BaseModel):
    id: uuid.UUID
    student: HostelStudentRef
    mess_plan_id: uuid.UUID
    plan: str | None = None
    from_on: date
    to_on: date | None = None
    status: str
    fee_invoice_id: uuid.UUID | None = None
    qr_token: str | None = None


class MessAttendanceMark(BaseModel):
    subscription_id: uuid.UUID | None = None
    qr: str | None = None
    meal: Literal["breakfast", "lunch", "snacks", "dinner"]
    on_date: date | None = None
    source: Literal["qr", "rfid", "manual"] = "manual"


class MessAttendanceBulk(_Strict):
    items: list[MessAttendanceMark] = Field(min_length=1, max_length=2000)


class MessAttendanceResult(BaseModel):
    recorded: int
    duplicates: int
    errors: list[dict[str, Any]] = []


class MessAttendanceRow(BaseModel):
    on_date: date
    meal: str
    status: str
    source: str


class RebateRequest(_Strict):
    from_on: date
    to_on: date
    reason: str = Field(min_length=3, max_length=500)


class RebateDecision(_Strict):
    approve: bool = True
    remarks: str | None = Field(None, max_length=500)


class RebateOut(BaseModel):
    id: uuid.UUID
    subscription_id: uuid.UUID
    student: HostelStudentRef | None = None
    from_on: date
    to_on: date
    days: int
    reason: str | None = None
    status: str
    leave_id: uuid.UUID | None = None


class MessBillRunRequest(_Strict):
    month: date
    hostel_id: uuid.UUID | None = None


class BillRunSummary(BaseModel):
    month: date
    bills: int = 0
    amount_paise: int = 0
    skipped: int = 0
    job_id: uuid.UUID | None = None


class MessBillResponse(BaseModel):
    id: uuid.UUID
    subscription_id: uuid.UUID
    student: HostelStudentRef | None = None
    plan: str | None = None
    month: date
    days_billed: int
    rebate_days: int
    amount_paise: int
    fee_invoice_id: uuid.UUID | None = None
    invoice_status: str | None = None


# ---- visitors / leaves / gate ---------------------------------------------------------------------------------------------
class HostelVisitorIn(_Strict):
    enrollment_id: uuid.UUID
    visitor_name: str = Field(min_length=2, max_length=160)
    relation: str | None = Field(None, max_length=40)
    phone: str | None = Field(None, max_length=20)
    id_proof_type: str | None = Field(None, max_length=30)
    id_proof_no: str | None = Field(None, max_length=40)


class HostelVisitorOut(BaseModel):
    id: uuid.UUID
    hostel_id: uuid.UUID
    student: HostelStudentRef | None = None
    visitor_name: str
    relation: str | None = None
    phone: str | None = None
    id_proof_type: str | None = None
    id_proof_no: str | None = None
    in_at: datetime
    out_at: datetime | None = None


class HostelLeaveCreate(_Strict):
    leave_type: Literal["out_pass", "day_leave", "home_leave", "medical"]
    from_at: datetime
    to_at: datetime
    destination: str | None = Field(None, max_length=200)
    reason: str | None = Field(None, max_length=1000)


class HostelLeaveResponse(BaseModel):
    id: uuid.UUID
    student: HostelStudentRef
    hostel_id: uuid.UUID
    hostel: str | None = None
    leave_type: str
    from_at: datetime
    to_at: datetime
    destination: str | None = None
    reason: str | None = None
    guardian_consent: str
    status: str
    qr_token: str | None = None
    actual_out_at: datetime | None = None
    actual_return_at: datetime | None = None
    late_minutes: int | None = None
    created_at: datetime


class ConsentOtpVerify(_Strict):
    otp: str = Field(min_length=4, max_length=8)


class HostelLeaveDecision(_Strict):
    action: Literal["approve", "reject"]
    remarks: str | None = Field(None, max_length=500)


class MarkReturned(_Strict):
    remarks: str = Field(min_length=3, max_length=500)
    returned_at: datetime | None = None


class GateScanRequest(BaseModel):
    qr_token: str = Field(min_length=10, max_length=80)
    direction: Literal["out", "in"]
    scanned_at: datetime | None = None  # offline scans carry the device time


class GateScanBatch(_Strict):
    scans: list[GateScanRequest] = Field(min_length=1, max_length=500)


class GateScanResponse(BaseModel):
    student: HostelStudentRef | None = None
    leave: HostelLeaveResponse | None = None
    result: str
    late_minutes: int | None = None
    message: str | None = None


# ---- complaints / discipline / quarters ---------------------------------------------------------------------------------------
class HostelComplaintCreate(_Strict):
    category: Literal["electrical", "plumbing", "cleaning", "wifi", "food", "furniture", "other"]
    description: str = Field(min_length=5, max_length=4000)
    room_id: uuid.UUID | None = None


class HostelComplaintUpdate(_Strict):
    status: Literal["assigned", "in_progress", "resolved", "closed"]
    remarks: str | None = Field(None, max_length=1000)


class HostelComplaintRate(_Strict):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=500)


class HostelComplaintOut(BaseModel):
    id: uuid.UUID
    hostel_id: uuid.UUID
    room_id: uuid.UUID | None = None
    room_number: str | None = None
    student: HostelStudentRef | None = None
    category: str
    description: str
    status: str
    service_request_id: uuid.UUID | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class DisciplineCreate(_Strict):
    enrollment_id: uuid.UUID
    incident_on: date
    description: str = Field(min_length=5, max_length=4000)
    action: Literal["warning", "fine", "suspension", "eviction"]
    fine_paise: int | None = Field(None, ge=0)


class DisciplineOut(BaseModel):
    id: uuid.UUID
    student: HostelStudentRef
    hostel_id: uuid.UUID
    incident_on: date
    description: str
    action: str
    fine_paise: int | None = None
    fee_invoice_id: uuid.UUID | None = None
    created_at: datetime


class QuarterIn(_Strict):
    college_id: uuid.UUID
    unit_code: str = Field(min_length=1, max_length=20)
    quarter_type: str | None = Field(None, max_length=20)
    rent_paise: int = Field(0, ge=0)
    status: Literal["vacant", "maintenance"] | None = None


class QuarterOut(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID
    unit_code: str
    quarter_type: str | None = None
    rent_paise: int
    status: str
    allocation_id: uuid.UUID | None = None
    occupant: str | None = None
    occupant_staff_id: uuid.UUID | None = None
    from_on: date | None = None
    rent_deduction: bool | None = None


class QuarterAllocate(_Strict):
    staff_id: uuid.UUID
    from_on: date | None = None
    rent_deduction: bool = True


class QuarterVacate(_Strict):
    to_on: date | None = None


class HostelJobAccepted(BaseModel):
    job_id: uuid.UUID
    status: str = "queued"
