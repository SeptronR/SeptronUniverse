"""Facilities schemas — Prompts/25 §25.4: bookings, service desk, AMC, lost & found, visitors, SOS, health,
counselling, sports, canteen wallet (OpenAPI names prefixed ``Fac`` / ``Sos`` / ``Health`` / ``Counselling`` /
``Sports`` / ``Wallet`` / ``Canteen`` to stay unique)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


ServiceCategoryLit = Literal[
    "electrical", "plumbing", "it", "network", "furniture", "cleaning", "civil", "security", "asset", "other"
]
PriorityLit = Literal["low", "normal", "high", "urgent"]
PersonTypeLit = Literal["student", "staff"]


# ---- room / equipment bookings ------------------------------------------------------------------------------------------
class FacRoomBookingCreate(_Strict):
    room_id: uuid.UUID
    from_at: datetime
    to_at: datetime
    purpose: str = Field(min_length=3, max_length=200)
    expected_headcount: int | None = Field(None, ge=1, le=10000)
    event_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _range(self) -> "FacRoomBookingCreate":
        if self.to_at <= self.from_at:
            raise ValueError("to_at must be after from_at")
        return self


class FacRecurringBooking(_Strict):
    room_id: uuid.UUID
    from_at: datetime
    to_at: datetime
    purpose: str = Field(min_length=3, max_length=200)
    expected_headcount: int | None = Field(None, ge=1, le=10000)
    weeks: int = Field(4, ge=2, le=26)


class FacConflict(BaseModel):
    kind: str  # booking | timetable | class_session | exam | room_status
    source_id: uuid.UUID | None = None
    title: str
    from_at: datetime | None = None
    to_at: datetime | None = None


class FacRoomBookingOut(_Orm):
    id: uuid.UUID
    room_id: uuid.UUID
    room_code: str | None = None
    room_name: str | None = None
    requested_by: uuid.UUID
    requester_name: str | None = None
    purpose: str
    from_at: datetime
    to_at: datetime
    expected_headcount: int | None = None
    event_id: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    status: str
    created_at: datetime
    conflicts: list[FacConflict] = []
    auto_approved: bool = False


class FacRecurringResult(BaseModel):
    created: list[FacRoomBookingOut]
    conflicts: list[dict[str, Any]]


class FacAvailabilitySlot(BaseModel):
    room_id: uuid.UUID
    room_code: str
    room_name: str
    capacity: int
    building_id: uuid.UUID | None = None
    available: bool
    conflicts: list[FacConflict] = []


class FacAvailabilityOut(BaseModel):
    from_at: datetime
    to_at: datetime
    rooms: list[FacAvailabilitySlot]


class FacBookingDecision(_Strict):
    action: Literal["approve", "reject"]
    remarks: str | None = Field(None, max_length=500)


class FacEquipmentBookingCreate(_Strict):
    asset_id: uuid.UUID
    from_at: datetime
    to_at: datetime
    purpose: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _range(self) -> "FacEquipmentBookingCreate":
        if self.to_at <= self.from_at:
            raise ValueError("to_at must be after from_at")
        return self


class FacHandover(_Strict):
    condition: Literal["good", "fair", "damaged", "missing_parts"] = "good"
    remarks: str | None = Field(None, max_length=500)


class FacEquipmentBookingOut(_Orm):
    id: uuid.UUID
    asset_id: uuid.UUID
    asset_tag: str | None = None
    asset_name: str | None = None
    requested_by: uuid.UUID
    requester_name: str | None = None
    from_at: datetime
    to_at: datetime
    purpose: str | None = None
    status: str
    approved_by: uuid.UUID | None = None
    created_at: datetime
    handover: dict[str, Any] | None = None
    returned: dict[str, Any] | None = None
    overdue: bool = False


# ---- service desk ---------------------------------------------------------------------------------------------------------
class FacServiceRequestCreate(_Strict):
    category: ServiceCategoryLit
    college_id: uuid.UUID | None = None
    location_room_id: uuid.UUID | None = None
    location_text: str | None = Field(None, max_length=200)
    description: str = Field(min_length=5, max_length=4000)
    attachments: list[str] = []
    priority: PriorityLit = "normal"
    asset_id: uuid.UUID | None = None
    hostel_complaint_id: uuid.UUID | None = None


class FacServiceAssign(_Strict):
    assigned_to: uuid.UUID | None = None
    vendor_id: uuid.UUID | None = None
    amc_contract_id: uuid.UUID | None = None
    remarks: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _one(self) -> "FacServiceAssign":
        if not self.assigned_to and not self.vendor_id:
            raise ValueError("assigned_to or vendor_id is required")
        return self


class FacServiceUpdate(_Strict):
    status: Literal["in_progress", "resolved"] = "in_progress"
    resolution: str | None = Field(None, max_length=4000)
    cost_paise: int | None = Field(None, ge=0)
    remarks: str | None = Field(None, max_length=500)


class FacServiceRate(_Strict):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=1000)


class FacServiceNote(_Strict):
    remarks: str | None = Field(None, max_length=1000)


class FacServiceRequestOut(_Orm):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    ticket_number: str
    category: str
    location_room_id: uuid.UUID | None = None
    location_text: str | None = None
    room_code: str | None = None
    description: str
    attachments: list[Any] | None = None
    priority: str
    requested_by: uuid.UUID
    requester_name: str | None = None
    assigned_to: uuid.UUID | None = None
    assignee_name: str | None = None
    vendor_id: uuid.UUID | None = None
    vendor_name: str | None = None
    sla_due_at: datetime | None = None
    sla_breached: bool = False
    status: str
    resolution: str | None = None
    rating: int | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    amc_contract_id: uuid.UUID | None = None
    cost_paise: int | None = None
    timeline: list[dict[str, Any]] = []
    is_mine: bool = False


class FacServiceDashboard(BaseModel):
    open: int
    by_status: dict[str, int]
    by_category: dict[str, int]
    breached: int
    due_24h: int
    mttr_hours: float | None = None
    csat: float | None = None
    rated: int
    backlog_by_age: dict[str, int]


class FacAmcContractIn(_Strict):
    supplier_id: uuid.UUID
    asset_category: str | None = Field(None, max_length=60)
    asset_ids: list[uuid.UUID] = []
    from_on: date
    to_on: date
    value_paise: int | None = Field(None, ge=0)
    sla: dict[str, int] | None = None  # category → hours
    document_url: str | None = None
    status: Literal["active", "expired", "terminated"] = "active"


class FacAmcContractOut(_Orm):
    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    asset_category: str | None = None
    asset_ids: list[Any] | None = None
    from_on: date
    to_on: date
    value_paise: int | None = None
    sla: dict[str, Any] | None = None
    document_url: str | None = None
    status: str
    days_left: int | None = None
    created_at: datetime


class FacAmcPerformance(BaseModel):
    contract_id: uuid.UUID
    tickets: int
    resolved: int
    breached: int
    mttr_hours: float | None = None
    csat: float | None = None


class FacLostFoundIn(_Strict):
    description: str = Field(min_length=3, max_length=2000)
    found_at: datetime | None = None
    location: str | None = Field(None, max_length=200)
    image_url: str | None = None


class FacLostFoundClaim(_Strict):
    name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(None, max_length=20)
    id_proof: str = Field(min_length=3, max_length=120)
    user_id: uuid.UUID | None = None
    remarks: str | None = Field(None, max_length=500)


class FacLostFoundOut(_Orm):
    id: uuid.UUID
    description: str
    found_at: datetime | None = None
    location: str | None = None
    image_url: str | None = None
    reported_by: uuid.UUID | None = None
    status: str
    claimant: dict[str, Any] | None = None
    created_at: datetime


# ---- visitors -------------------------------------------------------------------------------------------------------------
class FacVisitor(_Strict):
    name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=6, max_length=20)
    organisation: str | None = Field(None, max_length=200)
    photo_url: str | None = None


class FacVisitorPassCreate(_Strict):
    visitor: FacVisitor
    host_user_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    purpose: str | None = Field(None, max_length=200)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    vehicle_no: str | None = Field(None, max_length=20)
    id_proof: dict[str, Any] | None = None


class FacGateScan(_Strict):
    pass_code: str = Field(min_length=4, max_length=120)
    direction: Literal["in", "out"]
    photo_url: str | None = None


class FacVisitorPassOut(_Orm):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    visitor: dict[str, Any]
    host_user_id: uuid.UUID | None = None
    host_name: str | None = None
    purpose: str | None = None
    valid_from: datetime
    valid_to: datetime
    gate_in_at: datetime | None = None
    gate_out_at: datetime | None = None
    vehicle_no: str | None = None
    pass_code: str | None = None
    qr: str | None = None
    status: str
    created_by: uuid.UUID | None = None
    created_at: datetime


# ---- emergency / SOS ---------------------------------------------------------------------------------------------------
class SosLocation(_Strict):
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    accuracy: float | None = Field(None, ge=0)
    text: str | None = Field(None, max_length=200)


class SosRaise(_Strict):
    alert_type: Literal["sos", "fire", "medical", "security"] = "sos"
    location: SosLocation = SosLocation()
    message: str | None = Field(None, max_length=1000)
    drill: bool = False


class SosNotes(_Strict):
    notes: str | None = Field(None, max_length=2000)


class SosBroadcast(_Strict):
    message: str | None = Field(None, max_length=1000)
    confirm: str = Field(description="type BROADCAST to confirm")


class SosOut(_Orm):
    id: uuid.UUID
    raised_by_user_id: uuid.UUID
    raised_by_name: str | None = None
    alert_type: str
    location: dict[str, Any] | None = None
    map_url: str | None = None
    message: str | None = None
    status: str
    responders: dict[str, Any] | None = None
    acknowledged_by: uuid.UUID | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    timeline: list[dict[str, Any]] = []
    false_alarm: bool = False
    drill: bool = False


# ---- health ---------------------------------------------------------------------------------------------------------------
class HealthVisitIn(_Strict):
    person_type: PersonTypeLit = "student"
    person_id: uuid.UUID
    visited_at: datetime | None = None
    complaint: str | None = Field(None, max_length=4000)
    diagnosis: str | None = Field(None, max_length=4000)
    treatment: str | None = Field(None, max_length=4000)
    referred_to: str | None = Field(None, max_length=200)
    is_confidential: bool = True


class HealthVisitOut(_Orm):
    id: uuid.UUID
    person_type: str
    person_id: uuid.UUID
    person_name: str | None = None
    visited_at: datetime
    complaint: str | None = None
    diagnosis: str | None = None
    treatment: str | None = None
    referred_to: str | None = None
    attended_by: uuid.UUID | None = None
    is_confidential: bool
    created_at: datetime
    certificate_issued: bool = False


class HealthCertificateRequest(_Strict):
    from_on: date
    to_on: date
    remarks: str | None = Field(None, max_length=500)


class InsurancePolicyIn(_Strict):
    person_type: PersonTypeLit = "student"
    person_id: uuid.UUID
    provider: str = Field(min_length=2, max_length=120)
    policy_no: str = Field(min_length=2, max_length=60)
    coverage_paise: int | None = Field(None, ge=0)
    valid_from: date | None = None
    valid_to: date | None = None
    document_url: str | None = None


class InsurancePolicyOut(_Orm):
    id: uuid.UUID
    person_type: str
    person_id: uuid.UUID
    person_name: str | None = None
    provider: str
    policy_no: str
    coverage_paise: int | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    document_url: str | None = None
    created_at: datetime


class HealthStats(BaseModel):
    visits: int
    by_month: dict[str, int]
    referrals: int
    certificates: int
    insured: int
    counselling: dict[str, int] = {}


# ---- counselling ----------------------------------------------------------------------------------------------------------
class CounsellingSlotSpec(_Strict):
    at: datetime
    duration: int = Field(30, ge=10, le=180)


class CounsellingSlotCreate(_Strict):
    counsellor_staff_id: uuid.UUID | None = None
    slots: list[CounsellingSlotSpec] = Field(min_length=1, max_length=100)


class CounsellingBook(_Strict):
    person_type: PersonTypeLit | None = None
    reschedule_from: uuid.UUID | None = None


class CounsellingNotes(_Strict):
    notes: str = Field(min_length=1, max_length=8000)


class CounsellingAppointmentOut(_Orm):
    id: uuid.UUID
    counsellor_staff_id: uuid.UUID
    counsellor_name: str | None = None
    slot_at: datetime
    duration_minutes: int
    person_type: str | None = None
    person_id: uuid.UUID | None = None
    person_name: str | None = None
    status: str
    is_confidential: bool
    notes: str | None = None
    has_notes: bool = False


class CounsellingUtilisation(BaseModel):
    slots: int
    booked: int
    completed: int
    no_show: int
    cancelled: int
    counsellors: int


# ---- sports ---------------------------------------------------------------------------------------------------------------
class SportsTeamIn(_Strict):
    sport: str = Field(min_length=2, max_length=60)
    name: str | None = Field(None, max_length=120)
    college_id: uuid.UUID | None = None
    level: str = Field("institution", max_length=20)
    coach_staff_id: uuid.UUID | None = None
    members: list[uuid.UUID] = []  # student_program_enrollment ids
    is_active: bool = True


class SportsTeamOut(_Orm):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    sport: str
    name: str | None = None
    level: str
    coach_staff_id: uuid.UUID | None = None
    coach_name: str | None = None
    members: list[Any] | None = None
    is_active: bool
    created_at: datetime


class SportsEventIn(_Strict):
    title: str = Field(min_length=3, max_length=200)
    sport: str | None = Field(None, max_length=60)
    level: Literal["institution", "inter_college", "university", "state", "national", "international"]
    from_on: date
    to_on: date | None = None
    venue: str | None = Field(None, max_length=200)
    organiser: str | None = Field(None, max_length=200)
    event_id: uuid.UUID | None = None
    create_event: bool = False


class SportsEventOut(_Orm):
    id: uuid.UUID
    title: str
    sport: str | None = None
    level: str
    from_on: date
    to_on: date | None = None
    venue: str | None = None
    organiser: str | None = None
    event_id: uuid.UUID | None = None
    created_at: datetime
    participants: int = 0


class SportsParticipationIn(_Strict):
    event_id: uuid.UUID
    enrollment_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    team_id: uuid.UUID | None = None
    result: str | None = Field(None, max_length=60)
    position: str | None = Field(None, max_length=20)
    evidence_url: str | None = None


class SportsParticipationOut(_Orm):
    id: uuid.UUID
    sports_event_id: uuid.UUID
    event_title: str | None = None
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    team_id: uuid.UUID | None = None
    result: str | None = None
    position: str | None = None
    evidence_url: str | None = None
    verified_by: uuid.UUID | None = None
    created_at: datetime


# ---- canteen & wallet -----------------------------------------------------------------------------------------------------
class CanteenIn(_Strict):
    name: str = Field(min_length=2, max_length=120)
    college_id: uuid.UUID | None = None
    location: str | None = Field(None, max_length=200)
    vendor_id: uuid.UUID | None = None
    menu: list[dict[str, Any]] = []
    is_active: bool = True


class CanteenOut(_Orm):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    name: str
    location: str | None = None
    vendor_id: uuid.UUID | None = None
    menu: list[Any] | None = None
    is_active: bool


class WalletOut(BaseModel):
    account_id: uuid.UUID | None = None
    person_type: str
    person_id: uuid.UUID
    name: str | None = None
    balance_paise: int
    status: str
    pay_qr: str | None = None
    recent: list[dict[str, Any]] = []


class WalletTopupRequest(_Strict):
    amount_paise: int = Field(gt=0)
    ward_student_id: uuid.UUID | None = None


class WalletTopupResponse(BaseModel):
    order: dict[str, Any]
    credited: bool
    balance_paise: int | None = None
    transaction_id: uuid.UUID | None = None


class WalletCounterTopup(_Strict):
    person_type: PersonTypeLit = "student"
    person_id: uuid.UUID
    amount_paise: int = Field(gt=0)
    reference: str | None = Field(None, max_length=80)


class WalletDebit(_Strict):
    account_id: uuid.UUID | None = None
    qr: str | None = Field(None, max_length=200)
    amount_paise: int = Field(gt=0)
    merchant: str | None = Field(None, max_length=120)
    canteen_id: uuid.UUID | None = None
    reference: str | None = Field(None, max_length=80)


class WalletRefund(_Strict):
    transaction_id: uuid.UUID
    amount_paise: int | None = Field(None, gt=0)
    reason: str | None = Field(None, max_length=200)


class WalletTxnOut(_Orm):
    id: uuid.UUID
    account_id: uuid.UUID
    txn_type: str
    amount_paise: int
    merchant: str | None = None
    reference: str | None = None
    created_at: datetime
    balance_after_paise: int | None = None


class WalletStatement(BaseModel):
    account_id: uuid.UUID
    opening_paise: int
    closing_paise: int
    credits_paise: int
    debits_paise: int
    transactions: list[WalletTxnOut]


class WalletSettlement(BaseModel):
    canteen_id: uuid.UUID | None = None
    merchant: str | None = None
    on: date
    debits: int
    debit_paise: int
    refunds: int
    refund_paise: int
    net_paise: int


class FacJobAccepted(BaseModel):
    job_id: uuid.UUID
