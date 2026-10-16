"""Course offering schemas — Prompts/09 §09.4 (offerings, faculty allocation, targets, bulk generation, rosters,
registration windows)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums.registration import DeliveryMode, FacultyRole, OfferingStatus, WindowStatus, WindowType
from app.schemas.common import ORMModel


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- offerings ------------------------------------------------------------------------------------------------------
class TargetIn(_Strict):
    batch_id: uuid.UUID
    section_id: uuid.UUID | None = None
    term_number: int | None = Field(default=None, ge=1, le=20, description="defaults to the batch's current term")


class TargetOut(BaseModel):
    id: uuid.UUID | None = None
    batch_id: uuid.UUID
    batch_code: str | None = None
    section_id: uuid.UUID | None = None
    section_name: str | None = None
    term_number: int


class FacultyIn(_Strict):
    staff_id: uuid.UUID
    role: FacultyRole = FacultyRole.INSTRUCTOR
    hours_per_week: int = Field(default=0, ge=0, le=40)


class FacultyOut(BaseModel):
    staff_id: uuid.UUID
    name: str | None = None
    employee_id: str | None = None
    department_id: uuid.UUID | None = None
    role: str
    hours_per_week: int
    # Phase 06 workload of the term (hours vs the cadre norm) — the badge of the faculty assignment
    total_hours: float | None = None
    norm_hours: float | None = None
    load_status: str | None = None


class OfferingCreate(_Strict):
    term_id: uuid.UUID
    course_id: uuid.UUID
    section_code: str = Field(default="A", min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    department_id: uuid.UUID | None = Field(default=None, description="defaults to the course's department")
    college_id: uuid.UUID | None = Field(default=None, description="defaults to the department's college")
    coordinator_staff_id: uuid.UUID | None = None
    max_seats: int | None = Field(default=None, ge=1, le=2000)
    delivery_mode: DeliveryMode = DeliveryMode.OFFLINE
    online_class_link: str | None = Field(default=None, max_length=500)
    assessment_scheme_id: uuid.UUID | None = None
    is_arrear_only: bool = False
    targets: list[TargetIn] = Field(default_factory=list, max_length=50)


class OfferingUpdate(_Strict):
    section_code: str | None = Field(default=None, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    coordinator_staff_id: uuid.UUID | None = None
    max_seats: int | None = Field(default=None, ge=1, le=2000)
    delivery_mode: DeliveryMode | None = None
    online_class_link: str | None = Field(default=None, max_length=500)
    assessment_scheme_id: uuid.UUID | None = None
    is_arrear_only: bool | None = None
    version: int | None = None


class OfferingStatusChange(_Strict):
    status: OfferingStatus
    reason: str | None = Field(default=None, max_length=500)


class OfferingFacultyReplace(_Strict):
    items: list[FacultyIn] = Field(max_length=20)
    allow_cross_department: bool = Field(
        default=False, description="staff of another department (dean / registrar only — the dean approval flag)"
    )


class OfferingTargetsReplace(_Strict):
    items: list[TargetIn] = Field(max_length=50)


class OfferingResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID
    college_code: str | None = None
    term_id: uuid.UUID
    term_name: str | None = None
    course_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    course_type: str | None = None
    credits: float = 0
    regulation_id: uuid.UUID | None = None
    department_id: uuid.UUID
    department_code: str | None = None
    section_code: str
    coordinator_staff_id: uuid.UUID | None = None
    coordinator_name: str | None = None
    faculty: list[FacultyOut] = Field(default_factory=list)
    max_seats: int | None = None
    enrolled_count: int = 0
    waitlist_count: int = 0
    seats_left: int | None = None
    delivery_mode: str
    online_class_link: str | None = None
    assessment_scheme_id: uuid.UUID | None = None
    is_arrear_only: bool = False
    targets: list[TargetOut] = Field(default_factory=list)
    status: str
    version: int = 1
    created_at: datetime | None = None
    is_mine: bool = False


class OfferingFacultyResult(BaseModel):
    offering: OfferingResponse
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class BulkFromCurriculumRequest(_Strict):
    term_id: uuid.UUID
    batch_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    sections_per_course: int = Field(default=1, ge=1, le=10)
    default_seats: int | None = Field(default=None, ge=1, le=2000)
    include_baskets: bool = False


class BulkPreviewItem(BaseModel):
    course_id: uuid.UUID
    course_code: str
    course_title: str
    department_code: str | None = None
    section_code: str
    batch_codes: list[str] = Field(default_factory=list)
    term_number: int
    mandatory: bool = True
    basket_code: str | None = None
    exists: bool = False


class BulkPreview(BaseModel):
    term_id: uuid.UUID
    dry_run: bool = True
    total: int = 0
    to_create: int = 0
    existing: int = 0
    targets_added: int = 0
    items: list[BulkPreviewItem] = Field(default_factory=list)
    job_id: uuid.UUID | None = None
    warnings: list[str] = Field(default_factory=list)


class RosterItem(BaseModel):
    item_id: uuid.UUID
    registration_id: uuid.UUID
    student_id: uuid.UUID
    registration_number: str | None = None
    name: str | None = None
    program_code: str | None = None
    batch_code: str | None = None
    section_name: str | None = None
    registration_type: str
    attempt_number: int = 1
    status: str
    added_at: datetime | None = None


# ---- registration windows ---------------------------------------------------------------------------------------------
class AppliesTo(_Strict):
    program_ids: list[uuid.UUID] | None = None
    batch_ids: list[uuid.UUID] | None = None
    section_ids: list[uuid.UUID] | None = None
    department_ids: list[uuid.UUID] | None = None
    term_numbers: list[int] | None = None
    entry_types: list[str] | None = None


class WindowCreate(_Strict):
    term_id: uuid.UUID
    college_id: uuid.UUID | None = None
    name: str = Field(min_length=3, max_length=120)
    window_type: WindowType
    applies_to: AppliesTo | None = None
    starts_at: datetime
    ends_at: datetime
    late_fee_paise: int = Field(default=0, ge=0)
    requires_advisor_approval: bool = True
    requires_fee_clearance: bool = False
    max_credits_override: float | None = Field(default=None, ge=0, le=60)

    @model_validator(mode="after")
    def _order(self) -> "WindowCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class WindowUpdate(_Strict):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    applies_to: AppliesTo | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    late_fee_paise: int | None = Field(default=None, ge=0)
    requires_advisor_approval: bool | None = None
    requires_fee_clearance: bool | None = None
    max_credits_override: float | None = Field(default=None, ge=0, le=60)


class WindowStatusChange(_Strict):
    status: WindowStatus


class WindowResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    term_id: uuid.UUID
    term_name: str | None = None
    name: str
    window_type: str
    applies_to: dict[str, Any] | None = None
    starts_at: datetime
    ends_at: datetime
    late_fee_paise: int = 0
    requires_advisor_approval: bool = True
    requires_fee_clearance: bool = False
    max_credits_override: float | None = None
    status: str
    is_open_now: bool = False
    created_at: datetime | None = None
