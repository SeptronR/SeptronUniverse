"""Institution structure schemas — Prompts/03 §03.4 (profile, colleges, faculties, departments, holidays, sequences,
onboarding). Column names are copied from Database_Schema.sql §2; enums from ``app/enums/institution.py``."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.enums.institution import (
    CollegeType,
    DepartmentType,
    HolidayAppliesTo,
    HolidayType,
    InstitutionStatus,
    InstitutionType,
    ResetPolicy,
)
from app.schemas.common import BulkFailure, ORMModel

CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,19}$"
SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,59}$"


def _tz(value: str | None) -> str | None:
    if value is None:
        return value
    from zoneinfo import available_timezones

    if value not in available_timezones():
        raise ValueError(f"unknown timezone {value!r}")
    return value


# ---- profile --------------------------------------------------------------------------------------------------------
class StatutoryIds(BaseModel):
    aishe_code: str | None = Field(default=None, max_length=20)
    aicte_pid: str | None = Field(default=None, max_length=30)
    naac_id: str | None = Field(default=None, max_length=30)
    ugc_status: str | None = Field(default=None, max_length=40)
    gstin: str | None = Field(default=None, max_length=20)


class InstitutionProfileResponse(ORMModel):
    id: uuid.UUID
    name: str
    short_name: str | None = None
    slug: str
    code: str | None = None
    institution_type: InstitutionType
    regulatory_pack: str
    pack_version: str | None = None
    timezone: str
    locale: str
    currency: str
    parent_university_name: str | None = None
    aishe_code: str | None = None
    aicte_pid: str | None = None
    naac_id: str | None = None
    ugc_status: str | None = None
    gstin: str | None = None
    address: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    logo_url: str | None = None
    website_url: str | None = None
    status: InstitutionStatus
    version: int
    # institution_profile (1:1)
    established_year: int | None = None
    vision: str | None = None
    mission: str | None = None
    accreditations: list[dict[str, Any]] | None = None
    recognitions: list[dict[str, Any]] | None = None
    social_links: dict[str, Any] | None = None
    head_title: str | None = None
    head_name: str | None = None
    head_signature_url: str | None = None
    seal_url: str | None = None
    letterhead_url: str | None = None
    updated_at: datetime


class InstitutionProfileUpdate(BaseModel):
    """Partial update; ``version`` enables optimistic locking (409 STALE_VERSION)."""

    name: str | None = Field(default=None, min_length=2, max_length=200)
    short_name: str | None = Field(default=None, max_length=60)
    code: str | None = Field(default=None, max_length=20)
    regulatory_pack: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=60)
    locale: str | None = Field(default=None, max_length=10)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    parent_university_name: str | None = Field(default=None, max_length=200)
    aishe_code: str | None = Field(default=None, max_length=20)
    aicte_pid: str | None = Field(default=None, max_length=30)
    naac_id: str | None = Field(default=None, max_length=30)
    ugc_status: str | None = Field(default=None, max_length=40)
    gstin: str | None = Field(default=None, max_length=20)
    statutory_ids: StatutoryIds | None = Field(default=None, description="alternative grouping of the statutory ids")
    address: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    website_url: str | None = Field(default=None, max_length=500)
    established_year: int | None = Field(default=None, ge=1800, le=2100)
    vision: str | None = None
    mission: str | None = None
    accreditations: list[dict[str, Any]] | None = None
    recognitions: list[dict[str, Any]] | None = None
    social_links: dict[str, Any] | None = None
    head_title: str | None = Field(default=None, max_length=60)
    head_name: str | None = Field(default=None, max_length=200)
    head_signature_url: str | None = None
    seal_url: str | None = None
    letterhead_url: str | None = None
    version: int | None = None

    _check_tz = field_validator("timezone")(_tz)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class LogoUploadResponse(BaseModel):
    logo_url: str
    key: str
    content_type: str


# ---- colleges -------------------------------------------------------------------------------------------------------
class CollegeBase(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    college_type: CollegeType = CollegeType.CONSTITUENT
    affiliation_number: str | None = Field(default=None, max_length=40)
    affiliated_since: date | None = None
    principal_staff_id: uuid.UUID | None = None
    exam_centre_code: str | None = Field(default=None, max_length=20)
    is_exam_centre: bool = False
    aishe_code: str | None = Field(default=None, max_length=20)
    aicte_pid: str | None = Field(default=None, max_length=30)
    gstin: str | None = Field(default=None, max_length=20)
    address: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, max_length=60)

    _check_tz = field_validator("timezone")(_tz)


class CollegeCreate(CollegeBase):
    code: str = Field(pattern=CODE_PATTERN)
    is_main: bool = False


class CollegeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    slug: str | None = Field(default=None, pattern=SLUG_PATTERN)
    college_type: CollegeType | None = None
    affiliation_number: str | None = Field(default=None, max_length=40)
    affiliated_since: date | None = None
    principal_staff_id: uuid.UUID | None = None
    exam_centre_code: str | None = Field(default=None, max_length=20)
    is_exam_centre: bool | None = None
    aishe_code: str | None = Field(default=None, max_length=20)
    aicte_pid: str | None = Field(default=None, max_length=30)
    gstin: str | None = Field(default=None, max_length=20)
    address: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, max_length=60)
    is_main: bool | None = None
    version: int | None = None

    _check_tz = field_validator("timezone")(_tz)


class CollegeResponse(ORMModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    code: str
    name: str
    slug: str | None = None
    college_type: str
    affiliation_number: str | None = None
    affiliated_since: date | None = None
    principal_staff_id: uuid.UUID | None = None
    exam_centre_code: str | None = None
    is_exam_centre: bool
    aishe_code: str | None = None
    aicte_pid: str | None = None
    gstin: str | None = None
    address: dict[str, Any] | None = None
    contact: dict[str, Any] | None = None
    logo_url: str | None = None
    timezone: str | None = None
    is_main: bool
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime
    department_count: int = 0
    can_edit: bool = False


# ---- faculties ------------------------------------------------------------------------------------------------------
class FacultyCreate(BaseModel):
    college_id: uuid.UUID
    code: str = Field(pattern=CODE_PATTERN)
    name: str = Field(min_length=2, max_length=200)
    dean_user_id: uuid.UUID | None = Field(default=None, description="staff user; grants the dean role @faculty")


class FacultyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    dean_user_id: uuid.UUID | None = None
    version: int | None = None


class FacultyResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID
    code: str
    name: str
    dean_staff_id: uuid.UUID | None = None
    dean_user_id: uuid.UUID | None = None
    dean_name: str | None = None
    version: int
    department_count: int = 0


# ---- departments ----------------------------------------------------------------------------------------------------
class DepartmentCreate(BaseModel):
    college_id: uuid.UUID
    faculty_id: uuid.UUID | None = None
    code: str = Field(pattern=CODE_PATTERN)
    name: str = Field(min_length=2, max_length=200)
    department_type: DepartmentType = DepartmentType.ACADEMIC
    established_year: int | None = Field(default=None, ge=1800, le=2100)
    description: str | None = None


class DepartmentUpdate(BaseModel):
    faculty_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=200)
    department_type: DepartmentType | None = None
    established_year: int | None = Field(default=None, ge=1800, le=2100)
    description: str | None = None
    version: int | None = None


class HodAssign(BaseModel):
    """``staff_id`` may be a ``staff`` row (Phase 06) or — until staff records exist — the staff **user** id."""

    staff_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one(self) -> "HodAssign":
        if not (self.staff_id or self.user_id):
            raise ValueError("staff_id or user_id is required")
        return self


class DepartmentResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID
    faculty_id: uuid.UUID | None = None
    code: str
    name: str
    department_type: str
    hod_staff_id: uuid.UUID | None = None
    hod_user_id: uuid.UUID | None = None
    hod_name: str | None = None
    established_year: int | None = None
    description: str | None = None
    is_active: bool
    version: int
    college_code: str | None = None
    faculty_code: str | None = None


# ---- holidays -------------------------------------------------------------------------------------------------------
class HolidayCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    holiday_date: date
    end_date: date | None = None
    holiday_type: HolidayType = HolidayType.PUBLIC
    applies_to: HolidayAppliesTo = HolidayAppliesTo.ALL
    college_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _range(self) -> "HolidayCreate":
        if self.end_date and self.end_date < self.holiday_date:
            raise ValueError("end_date must be on or after holiday_date")
        return self


class HolidayUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    holiday_date: date | None = None
    end_date: date | None = None
    holiday_type: HolidayType | None = None
    applies_to: HolidayAppliesTo | None = None


class HolidayResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    name: str
    holiday_date: date
    end_date: date | None = None
    holiday_type: str
    applies_to: str
    created_at: datetime


class HolidayBulkImport(BaseModel):
    """CSV ``name,date,end_date,type,applies_to`` (header optional) or pre-parsed ``rows``."""

    csv: str | None = Field(default=None, max_length=500_000)
    rows: list[dict[str, Any]] | None = None
    college_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _one(self) -> "HolidayBulkImport":
        if not (self.csv or self.rows):
            raise ValueError("csv or rows is required")
        return self


# ---- number sequences -----------------------------------------------------------------------------------------------
class NumberSequenceCreate(BaseModel):
    scope_key: str = Field(min_length=2, max_length=120)
    pattern: str = Field(min_length=1, max_length=120)
    next_value: int = Field(default=1, ge=1)
    padding: int = Field(default=4, ge=1, le=12)
    reset_policy: ResetPolicy = ResetPolicy.NEVER
    college_id: uuid.UUID | None = None


class NumberSequenceUpdate(BaseModel):
    pattern: str | None = Field(default=None, min_length=1, max_length=120)
    next_value: int | None = Field(default=None, ge=1)
    padding: int | None = Field(default=None, ge=1, le=12)
    reset_policy: ResetPolicy | None = None


class NumberSequenceResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    scope_key: str
    pattern: str
    next_value: int
    padding: int
    reset_policy: str
    updated_at: datetime
    sample: str | None = None


class NumberSequencePreviewRequest(BaseModel):
    prog_code: str | None = Field(default=None, max_length=30)
    term: str | None = Field(default=None, max_length=20)
    count: int = Field(default=1, ge=1, le=10)


class NumberSequencePreview(BaseModel):
    scope_key: str
    pattern: str
    values: list[str]
    tokens: dict[str, str]


class NumberSequenceNext(BaseModel):
    scope_key: str
    value: int
    rendered: str


# ---- onboarding / platform institutions -----------------------------------------------------------------------------
class OnboardingInstitution(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    short_name: str | None = Field(default=None, max_length=60)
    slug: str = Field(pattern=SLUG_PATTERN)
    code: str | None = Field(default=None, max_length=20)
    institution_type: InstitutionType
    timezone: str = "Asia/Kolkata"
    locale: str = "en-IN"
    currency: str = "INR"
    parent_university_name: str | None = Field(default=None, max_length=200)
    website_url: str | None = None
    contact: dict[str, Any] | None = None
    address: dict[str, Any] | None = None

    _check_tz = field_validator("timezone")(_tz)


class OnboardingAdmin(BaseModel):
    username: str = Field(min_length=3, max_length=60, pattern=r"^[A-Za-z0-9._@-]+$")
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, max_length=20)


class OnboardingRequest(BaseModel):
    institution: OnboardingInstitution
    admin: OnboardingAdmin
    plan_code: str = Field(default="standard", max_length=30)
    pack: str = Field(default="IN", max_length=10)
    seed_demo: bool = False
    # Phase 38 wizard: the template decides the type defaults and forced features; trial without an invoice; pending
    # until activated; the custom domain is recorded for Phase 40 verification
    template: Literal["university", "autonomous", "affiliated", "standalone"] | None = None
    trial: bool = False
    trial_days: int | None = Field(default=None, ge=1, le=365)
    billing_cycle: Literal["monthly", "yearly"] = "yearly"
    activate: bool = True
    custom_domain: str | None = Field(default=None, max_length=255, pattern=r"^[a-z0-9.-]+\.[a-z]{2,}$")


class OnboardingResponse(BaseModel):
    institution: InstitutionProfileResponse
    main_college_id: uuid.UUID | None = None
    roles_created: int
    defaults: dict[str, Any]
    plan_code: str
    features_enabled: int
    admin_user_id: uuid.UUID
    admin_username: str
    admin_temp_password: str = Field(description="shown once; the admin must change it at first sign-in")
    demo_job_id: uuid.UUID | None = None
    template: str | None = None
    status: str = "active"
    subscription_status: str | None = None
    subscription_ends_on: date | None = None
    forced_features: dict[str, list[str]] = Field(default_factory=dict)


class PlatformInstitutionResponse(ORMModel):
    id: uuid.UUID
    name: str
    short_name: str | None = None
    slug: str
    code: str | None = None
    institution_type: str
    regulatory_pack: str
    timezone: str
    status: str
    is_active: bool
    created_at: datetime
    college_count: int = 0
    user_count: int = 0
    plan_code: str | None = None
    subscription_status: str | None = None


class PlatformInstitutionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    short_name: str | None = Field(default=None, max_length=60)
    code: str | None = Field(default=None, max_length=20)
    regulatory_pack: str | None = Field(default=None, max_length=10)
    status: Literal["pending", "active", "archived"] | None = None
    version: int | None = None


class SuspendRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class HolidayBulkResult(BaseModel):
    """Partial-success report of ``POST /holidays/bulk-import`` (``index`` = 0-based data row)."""

    succeeded: int
    created: list[HolidayResponse] = Field(default_factory=list)
    failed: list[BulkFailure] = Field(default_factory=list)
