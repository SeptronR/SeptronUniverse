"""Staff, designations, faculty profiles, staff records, attendance and workload schemas — Prompts/06 §06.4.

PII (PAN, Aadhaar, bank details, statutory numbers, phone, e-mail, date of birth) is declared through the ``Masked*``
annotated types: ``mask_pii(obj, principal, "hr")`` masks them unless the reader holds ``hr:view_pii`` (the service
also leaves a member's own record unmasked). Writing PII needs ``hr:manage``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.authz.masking import Masked, MaskedEmail, MaskedPhone, MaskedSecret
from app.enums.hr import (
    AttendanceStatus,
    Cadre,
    DeviceType,
    EmploymentType,
    ServiceBookEntryType,
    StaffCategory,
    StaffStatus,
)
from app.schemas.common import ORMModel

_PAN = r"^[A-Z]{5}[0-9]{4}[A-Z]$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- designations -------------------------------------------------------------------------------------------------
class DesignationIn(_Strict):
    name: str = Field(min_length=2, max_length=100)
    code: str | None = Field(default=None, max_length=20)
    cadre: Cadre | None = None
    category: StaffCategory = StaffCategory.TEACHING
    level: int | None = Field(default=None, ge=1, le=20)
    is_active: bool = True


class DesignationOut(ORMModel):
    id: uuid.UUID
    name: str
    code: str | None = None
    cadre: str | None = None
    category: str
    level: int | None = None
    is_active: bool
    staff_count: int = 0


# ---- staff ----------------------------------------------------------------------------------------------------------
class BankDetails(_Strict):
    account_no: str = Field(min_length=6, max_length=20, pattern=r"^[0-9]+$")
    ifsc: str = Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    bank: str | None = Field(default=None, max_length=120)
    branch: str | None = Field(default=None, max_length=120)


class StaffCreate(_Strict):
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    designation_id: uuid.UUID | None = None
    employment_type: EmploymentType = EmploymentType.REGULAR
    staff_category: StaffCategory | None = None  # defaults from the designation
    dob: date | None = None
    gender: str | None = Field(default=None, pattern=r"^(M|F|O)$")
    blood_group: str | None = Field(default=None, max_length=5)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 -]{8,20}$")
    email: EmailStr | None = None
    address: dict[str, Any] | None = None
    emergency_contact: dict[str, Any] | None = None
    joining_date: date | None = None
    confirmation_date: date | None = None
    retirement_date: date | None = None
    pan: str | None = Field(default=None, pattern=_PAN)
    aadhaar: str | None = Field(default=None, pattern=r"^[0-9]{12}$")
    bank_details: BankDetails | None = None
    pf_number: str | None = Field(default=None, max_length=30)
    esi_number: str | None = Field(default=None, max_length=30)
    uan: str | None = Field(default=None, pattern=r"^[0-9]{12}$")
    hourly_rate_paise: int | None = Field(default=None, ge=0)
    reports_to_staff_id: uuid.UUID | None = None
    employee_id: str | None = Field(default=None, max_length=30, description="leave empty to draw from 'employee_id'")
    # link an existing user instead of creating one (demo users, a user created by admissions/SSO …)
    user_id: uuid.UUID | None = None
    create_user: bool = True
    role_slug: str | None = Field(default=None, max_length=60, description="overrides the role from the category")

    @field_validator("pan", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v


class StaffUpdate(_Strict):
    version: int | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    designation_id: uuid.UUID | None = None
    employment_type: EmploymentType | None = None
    staff_category: StaffCategory | None = None
    dob: date | None = None
    gender: str | None = Field(default=None, pattern=r"^(M|F|O)$")
    blood_group: str | None = Field(default=None, max_length=5)
    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 -]{8,20}$")
    email: EmailStr | None = None
    address: dict[str, Any] | None = None
    emergency_contact: dict[str, Any] | None = None
    joining_date: date | None = None
    confirmation_date: date | None = None
    retirement_date: date | None = None
    pan: str | None = Field(default=None, pattern=_PAN)
    aadhaar: str | None = Field(default=None, pattern=r"^[0-9]{12}$")
    bank_details: BankDetails | None = None
    pf_number: str | None = Field(default=None, max_length=30)
    esi_number: str | None = Field(default=None, max_length=30)
    uan: str | None = Field(default=None, pattern=r"^[0-9]{12}$")
    hourly_rate_paise: int | None = Field(default=None, ge=0)
    reports_to_staff_id: uuid.UUID | None = None
    status: StaffStatus | None = None

    @field_validator("pan", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> Any:
        return v.strip().upper() if isinstance(v, str) else v


class StaffSelfUpdate(_Strict):
    """What a member may change on their own profile (contact, photo, emergency contact)."""

    phone: str | None = Field(default=None, pattern=r"^\+?[0-9 -]{8,20}$")
    email: EmailStr | None = None
    address: dict[str, Any] | None = None
    emergency_contact: dict[str, Any] | None = None
    photo_url: str | None = Field(default=None, max_length=2000)
    blood_group: str | None = Field(default=None, max_length=5)


class StaffExitRequest(_Strict):
    exit_date: date
    exit_reason: str = Field(min_length=3, max_length=2000)


class StaffResponse(ORMModel):
    id: uuid.UUID
    employee_id: str
    full_name: str
    first_name: str
    middle_name: str | None = None
    last_name: str | None = None
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    department_code: str | None = None
    designation_id: uuid.UUID | None = None
    designation_name: str | None = None
    cadre: str | None = None
    employment_type: str
    staff_category: str
    status: str
    user_id: uuid.UUID | None = None
    username: str | None = None
    photo_url: str | None = None
    joining_date: date | None = None
    phone: MaskedPhone = None
    email: MaskedEmail = None
    hourly_rate_paise: int | None = None
    version: int
    is_self: bool = False


class StaffDetailResponse(StaffResponse):
    dob: Masked = None
    gender: str | None = None
    blood_group: str | None = None
    address: dict[str, Any] | None = None
    emergency_contact: dict[str, Any] | None = None
    confirmation_date: date | None = None
    retirement_date: date | None = None
    exit_date: date | None = None
    exit_reason: str | None = None
    pan: Masked = None
    aadhaar: Masked = None
    bank_details: MaskedSecret = None  # JSON text when unmasked
    pf_number: Masked = None
    esi_number: Masked = None
    uan: Masked = None
    reports_to_staff_id: uuid.UUID | None = None
    reports_to_name: str | None = None
    has_faculty_profile: bool = False
    created_at: datetime | None = None


class StaffCreateResult(BaseModel):
    staff: StaffDetailResponse
    username: str | None = None
    temp_password: str | None = Field(default=None, description="shown once; the member must change it on sign-in")


class StaffBulkImportRequest(_Strict):
    csv: str = Field(min_length=10, max_length=2_000_000)


class StaffBulkImportResult(BaseModel):
    total: int
    succeeded: int
    failed: list[dict[str, Any]]


# ---- faculty profile / qualifications / documents / service book --------------------------------------------------
class FacultyProfileIn(_Strict):
    aicte_faculty_id: str | None = Field(default=None, max_length=30)
    orcid: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
    scopus_id: str | None = Field(default=None, max_length=20)
    google_scholar_id: str | None = Field(default=None, max_length=30)
    vidwan_id: str | None = Field(default=None, max_length=20)
    highest_qualification: str | None = Field(default=None, max_length=60)
    is_phd: bool = False
    phd_year: int | None = Field(default=None, ge=1950, le=2100)
    is_phd_guide: bool = False
    guide_recognition_no: str | None = Field(default=None, max_length=40)
    max_scholars: int | None = Field(default=None, ge=0, le=20)
    experience_teaching_months: int = Field(default=0, ge=0, le=900)
    experience_industry_months: int = Field(default=0, ge=0, le=900)
    experience_research_months: int = Field(default=0, ge=0, le=900)
    specializations: list[str] | None = None
    cadre: Cadre | None = None


class FacultyProfileOut(ORMModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    aicte_faculty_id: str | None = None
    orcid: str | None = None
    scopus_id: str | None = None
    google_scholar_id: str | None = None
    vidwan_id: str | None = None
    highest_qualification: str | None = None
    is_phd: bool
    phd_year: int | None = None
    is_phd_guide: bool
    guide_recognition_no: str | None = None
    max_scholars: int | None = None
    experience_teaching_months: int
    experience_industry_months: int
    experience_research_months: int
    specializations: list[str] | None = None
    api_score: Decimal | None = None
    api_updated_at: datetime | None = None
    cadre: str | None = None


class QualificationIn(_Strict):
    degree: str = Field(min_length=2, max_length=60)
    discipline: str | None = Field(default=None, max_length=120)
    university: str | None = Field(default=None, max_length=200)
    year: int | None = Field(default=None, ge=1950, le=2100)
    is_highest: bool = False
    certificate_url: str | None = Field(default=None, max_length=2000)


class QualificationOut(ORMModel):
    id: uuid.UUID
    degree: str
    discipline: str | None = None
    university: str | None = None
    year: int | None = None
    is_highest: bool
    certificate_url: str | None = None


class StaffDocumentIn(_Strict):
    doc_type: str = Field(min_length=2, max_length=60)
    file_url: str = Field(min_length=3, max_length=2000)
    expires_on: date | None = None


class StaffDocumentOut(ORMModel):
    id: uuid.UUID
    doc_type: str
    file_url: str
    expires_on: date | None = None
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    uploaded_at: datetime


class ServiceBookEntryIn(_Strict):
    entry_type: ServiceBookEntryType
    effective_date: date
    details: dict[str, Any] | None = None
    document_url: str | None = Field(default=None, max_length=2000)


class ServiceBookEntryOut(ORMModel):
    id: uuid.UUID
    entry_type: str
    effective_date: date
    details: dict[str, Any] | None = None
    document_url: str | None = None
    recorded_by: uuid.UUID | None = None
    created_at: datetime


# ---- staff attendance ----------------------------------------------------------------------------------------------
class GeoPoint(_Strict):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0)


class StaffAttendanceMark(_Strict):
    staff_id: uuid.UUID
    date: date
    status: AttendanceStatus
    check_in: datetime | None = None
    check_out: datetime | None = None
    remarks: str | None = Field(default=None, max_length=500)


class SelfCheckinRequest(_Strict):
    geo: GeoPoint | None = None


class RegulariseRequest(_Strict):
    date: date
    status: AttendanceStatus = AttendanceStatus.PRESENT
    check_in: datetime | None = None
    check_out: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class PunchIn(_Strict):
    employee_code: str = Field(min_length=1, max_length=30)
    at: datetime
    direction: str | None = Field(default=None, pattern=r"^(in|out)$")


class PunchIngest(_Strict):
    device_token: str = Field(min_length=16, max_length=200)
    punches: list[PunchIn] = Field(min_length=1, max_length=5000)


class PunchIngestResult(BaseModel):
    received: int
    days_updated: int
    unknown_codes: list[str]


class StaffAttendanceOut(ORMModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    employee_id: str | None = None
    attendance_date: date
    status: str
    check_in_time: datetime | None = None
    check_out_time: datetime | None = None
    source: str
    device_id: uuid.UUID | None = None
    geo: dict[str, Any] | None = None
    remarks: str | None = None


class AttendanceSummaryRow(BaseModel):
    staff_id: uuid.UUID
    staff_name: str
    employee_id: str
    days_in_month: int
    present: float
    absent: float
    half_day: int
    on_leave: float
    on_duty: float
    holiday: int
    week_off: int
    lop_days: float
    unmarked: int


class AttendanceDeviceIn(_Strict):
    name: str = Field(min_length=2, max_length=100)
    device_type: DeviceType = DeviceType.BIOMETRIC
    college_id: uuid.UUID | None = None
    serial_no: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=120)
    applies_to: str = Field(default="staff", pattern=r"^(staff|students|both)$")


class AttendanceDeviceOut(ORMModel):
    id: uuid.UUID
    name: str
    device_type: str
    college_id: uuid.UUID | None = None
    serial_no: str | None = None
    location: str | None = None
    applies_to: str
    last_seen_at: datetime | None = None
    is_active: bool
    token: str | None = Field(default=None, description="returned once on creation; only its SHA-256 is stored")


# ---- workload -------------------------------------------------------------------------------------------------------
class WorkloadResponse(BaseModel):
    staff_id: uuid.UUID
    staff_name: str
    employee_id: str
    cadre: str | None = None
    term_id: uuid.UUID
    theory_hours: float
    tutorial_hours: float
    lab_hours: float
    project_hours: float
    admin_hours: float
    research_hours: float
    total_hours: float
    max_allowed_hours: float | None = None
    norm_hours: float | None = None
    load_status: str  # under | within | over | no_norm
    status: str
    note: str | None = None


class AllocationItem(_Strict):
    course_id: uuid.UUID
    staff_id: uuid.UUID
    hours: float = Field(ge=0, le=40)
    role: str = Field(default="instructor", pattern=r"^(coordinator|instructor|lab_instructor|teaching_assistant)$")


class AllocationProposalIn(_Strict):
    proposals: list[AllocationItem] = Field(max_length=500)


class AllocationProposalOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    term_id: uuid.UUID
    proposals: list[dict[str, Any]]
    status: str
    submitted_by: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    updated_at: datetime | None = None
    note: str | None = None
