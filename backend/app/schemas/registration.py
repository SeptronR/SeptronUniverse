"""Course registration schemas — Prompts/09 §09.4 (catalog, cart, submit, advisor decisions, overrides, bulk
registration, elective choice forms and allocation runs, waitlists, arrears)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums.registration import AdvisorDecisionKind, AllocationMode, RegistrationType
from app.schemas.offerings import WindowResponse


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreditLimits(BaseModel):
    min: float
    max: float
    normal: float
    overridden: bool = False


class FeePreview(BaseModel):
    registration_fee_paise: int = 0
    arrear_fee_paise: int = 0
    late_fee_paise: int = 0
    total_paise: int = 0
    note: str | None = None


class FeeOrder(BaseModel):
    """Mock-payment order standing in for the Phase 12 registration invoice (``fee_invoice_id`` stays NULL)."""

    ref: str
    amount_paise: int
    status: str = "pending"
    provider: str = "mock"
    breakdown: dict[str, int] = Field(default_factory=dict)
    created_at: datetime | None = None


# ---- catalog -----------------------------------------------------------------------------------------------------------
class RequisiteHint(BaseModel):
    relation: str
    course_id: uuid.UUID
    course_code: str | None = None
    met: bool
    is_hard: bool = True


class CatalogOffering(BaseModel):
    offering_id: uuid.UUID
    section_code: str
    faculty: list[str] = Field(default_factory=list)
    max_seats: int | None = None
    enrolled_count: int = 0
    waitlist_count: int = 0
    seats_left: int | None = None
    targeted: bool = False
    status: str
    is_arrear_only: bool = False


class CatalogCourse(BaseModel):
    course_id: uuid.UUID
    code: str
    title: str
    credits: float
    course_type: str | None = None
    mandatory: bool = False
    basket_id: uuid.UUID | None = None
    requisites: list[RequisiteHint] = Field(default_factory=list)
    prerequisites_met: bool = True
    offerings: list[CatalogOffering] = Field(default_factory=list)
    in_cart: str | None = Field(default=None, description="item status when the course is in the cart")


class ChoiceFormResponse(BaseModel):
    id: uuid.UUID
    enrollment_id: uuid.UUID
    basket_id: uuid.UUID
    term_id: uuid.UUID
    choices: list[dict[str, Any]] = Field(default_factory=list)  # [{course_id, code, title, priority}]
    status: str
    allocated_course_id: uuid.UUID | None = None
    allocated_course_code: str | None = None
    allocation_run_id: uuid.UUID | None = None
    submitted_at: datetime | None = None
    student_name: str | None = None
    registration_number: str | None = None


class CatalogBasket(BaseModel):
    basket_id: uuid.UUID
    code: str
    name: str
    basket_type: str
    min_choose: int
    max_choose: int
    allocation_mode: str
    courses: list[CatalogCourse] = Field(default_factory=list)
    choice_form: ChoiceFormResponse | None = None


class CatalogArrear(BaseModel):
    arrear_id: uuid.UUID
    course_id: uuid.UUID
    code: str
    title: str
    credits: float
    attempts: int
    status: str
    offerings: list[CatalogOffering] = Field(default_factory=list)
    in_cart: str | None = None


class HoldBrief(BaseModel):
    id: uuid.UUID
    hold_type: str
    reason: str


class CatalogResponse(BaseModel):
    term: dict[str, Any]
    structure_term: dict[str, Any] | None = None
    limits: CreditLimits
    window: WindowResponse | None = None
    windows: list[WindowResponse] = Field(default_factory=list)
    curriculum: list[CatalogCourse] = Field(default_factory=list)
    baskets: list[CatalogBasket] = Field(default_factory=list)
    arrears: list[CatalogArrear] = Field(default_factory=list)
    holds: list[str] = Field(default_factory=list)
    hold_details: list[HoldBrief] = Field(default_factory=list)
    undertakings_pending: list[str] = Field(default_factory=list)
    fee_preview: FeePreview
    registration_id: uuid.UUID | None = None
    registration_status: str | None = None
    audit_courses_enabled: bool = False


# ---- registration / cart -----------------------------------------------------------------------------------------------
class CartItemAdd(_Strict):
    offering_id: uuid.UUID
    registration_type: RegistrationType = RegistrationType.REGULAR
    priority: int | None = Field(default=None, ge=1, le=20)


class WaitlistBrief(BaseModel):
    id: uuid.UUID
    position: int
    status: str
    offered_until: datetime | None = None


class RegistrationItemOut(BaseModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    course_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    credits: float = 0
    section_code: str | None = None
    registration_type: str
    attempt_number: int = 1
    priority: int | None = None
    status: str
    is_credit_bearing: bool = True
    added_at: datetime | None = None
    dropped_at: datetime | None = None
    drop_reason: str | None = None
    prerequisite_override_by: uuid.UUID | None = None
    waitlist: WaitlistBrief | None = None


class RegistrationResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    enrollment_id: uuid.UUID
    program_code: str | None = None
    batch_code: str | None = None
    section_name: str | None = None
    department_code: str | None = None
    term_id: uuid.UUID
    term_name: str | None = None
    term_number: int | None = None
    window_id: uuid.UUID | None = None
    window_name: str | None = None
    status: str
    total_credits: float = 0
    limits: CreditLimits | None = None
    items: list[RegistrationItemOut] = Field(default_factory=list)
    fee: FeeOrder | None = None
    fee_invoice_id: uuid.UUID | None = None
    submitted_at: datetime | None = None
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    locked_at: datetime | None = None
    workflow_instance_id: uuid.UUID | None = None
    advisor_comment: str | None = None
    overrides: dict[str, Any] | None = None
    checks: list[dict[str, Any]] = Field(default_factory=list)
    version: int = 1
    updated_at: datetime | None = None


class RegistrationListItem(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    program_code: str | None = None
    batch_code: str | None = None
    section_name: str | None = None
    department_code: str | None = None
    term_id: uuid.UUID
    term_name: str | None = None
    status: str
    total_credits: float = 0
    items_count: int = 0
    waitlisted_count: int = 0
    fee_status: str | None = None
    submitted_at: datetime | None = None
    approved_at: datetime | None = None


class SubmitResponse(RegistrationResponse):
    warnings: list[str] = Field(default_factory=list)


class ItemDecision(_Strict):
    item_id: uuid.UUID
    decision: str = Field(pattern=r"^(keep|drop)$")


class AdvisorDecision(_Strict):
    decision: AdvisorDecisionKind
    comment: str | None = Field(default=None, max_length=1000)
    item_decisions: list[ItemDecision] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def _comment(self) -> "AdvisorDecision":
        if self.decision != AdvisorDecisionKind.APPROVE and not (self.comment or "").strip():
            raise ValueError("a comment is required to reject or request changes")
        return self


class OverrideRequest(_Strict):
    reason: str = Field(min_length=5, max_length=1000)
    max_credits: float | None = Field(default=None, ge=0, le=60)
    skip_prerequisites: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    skip_holds: bool = False


class WithdrawItemRequest(_Strict):
    reason: str = Field(min_length=3, max_length=500)


class LockRequest(_Strict):
    reason: str | None = Field(default=None, max_length=500)


class BulkRegisterRequest(_Strict):
    batch_id: uuid.UUID
    section_id: uuid.UUID | None = None
    term_id: uuid.UUID
    include_electives: bool = False


class BulkRegisterResult(BaseModel):
    batch_id: uuid.UUID
    term_id: uuid.UUID
    students: int = 0
    registrations_approved: int = 0
    items_confirmed: int = 0
    activated: int = 0
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    shortfalls: list[dict[str, Any]] = Field(default_factory=list)


# ---- elective choice forms & allocation --------------------------------------------------------------------------------
class Choice(_Strict):
    course_id: uuid.UUID
    priority: int = Field(ge=1, le=20)


class ChoiceFormSubmit(_Strict):
    term_id: uuid.UUID | None = None
    choices: list[Choice] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _unique(self) -> "ChoiceFormSubmit":
        if len({c.priority for c in self.choices}) != len(self.choices):
            raise ValueError("priorities must be unique")
        if len({c.course_id for c in self.choices}) != len(self.choices):
            raise ValueError("a course may be chosen once")
        return self


class AllocationRunRequest(_Strict):
    mode: AllocationMode | None = None
    seed: int | None = Field(default=None, description="lottery seed (defaults to the run's timestamp)")


class AllocationResultRow(BaseModel):
    form_id: uuid.UUID
    enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    rank: int
    sort_key: str | None = None
    allocated_course_id: uuid.UUID | None = None
    allocated_course_code: str | None = None
    choice_number: int | None = None
    status: str


class AllocationSummary(BaseModel):
    run_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    basket_id: uuid.UUID
    basket_code: str | None = None
    term_id: uuid.UUID
    mode: str
    dry_run: bool = True
    candidates: int = 0
    allocated: int = 0
    unallocated: int = 0
    per_course: list[dict[str, Any]] = Field(default_factory=list)
    results: list[AllocationResultRow] = Field(default_factory=list)
    run_at: datetime | None = None


class ManualAllocation(_Strict):
    form_id: uuid.UUID
    course_id: uuid.UUID


# ---- waitlists / arrears -----------------------------------------------------------------------------------------------
class WaitlistResponse(BaseModel):
    id: uuid.UUID
    offering_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    section_code: str | None = None
    enrollment_id: uuid.UUID
    position: int
    status: str
    offered_until: datetime | None = None
    item_id: uuid.UUID | None = None


class ArrearResponse(BaseModel):
    id: uuid.UUID
    enrollment_id: uuid.UUID
    student_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    program_code: str | None = None
    batch_code: str | None = None
    course_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    credits: float = 0
    attempts: int
    status: str
    first_failed_term_id: uuid.UUID | None = None
    last_attempt_term_id: uuid.UUID | None = None
    updated_at: datetime | None = None


class WaiveRequest(_Strict):
    reason: str = Field(min_length=5, max_length=500)


class ConfirmedCourse(BaseModel):
    """A ward's / student's confirmed course of the current term (parent portal)."""

    course_code: str
    course_title: str
    credits: float
    section_code: str | None = None
    registration_type: str = "regular"
    faculty: list[str] = Field(default_factory=list)
