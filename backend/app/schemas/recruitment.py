"""Recruitment, appraisal (PBAS) and CAS schemas — Prompts/06 §06.4 (``recruitment.py``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.authz.masking import MaskedEmail, MaskedPhone
from app.enums.hr import Cadre, EmploymentType
from app.schemas.common import ORMModel


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- postings -------------------------------------------------------------------------------------------------------
class ReservationIn(_Strict):
    roster: str = Field(default="100_point", pattern=r"^(100_point|200_point|none)$")
    vacancies: dict[str, int] = Field(default_factory=dict, description="category code → posts (GEN = unreserved)")
    backlog: dict[str, int] = Field(default_factory=dict)


class JobPostingIn(_Strict):
    title: str = Field(min_length=3, max_length=200)
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    cadre: Cadre | None = None
    vacancies: int = Field(default=1, ge=1, le=500)
    reservation: ReservationIn | None = None
    qualifications: list[str] | None = None
    description: str | None = Field(default=None, max_length=20000)
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class JobPostingOut(ORMModel):
    id: uuid.UUID
    title: str
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    department_code: str | None = None
    cadre: str | None = None
    vacancies: int
    reservation: dict[str, Any] | None = None
    qualifications: list[Any] | None = None
    description: str | None = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    status: str
    created_at: datetime
    pipeline: dict[str, int] = Field(default_factory=dict)


class PublicPostingOut(BaseModel):
    id: uuid.UUID
    title: str
    department: str | None = None
    cadre: str | None = None
    vacancies: int
    reservation: dict[str, Any] | None = None
    qualifications: list[Any] | None = None
    description: str | None = None
    closes_at: datetime | None = None


class ApplicantIn(_Strict):
    name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str = Field(pattern=r"^\+?[0-9 -]{8,20}$")
    dob: date | None = None
    gender: str | None = Field(default=None, pattern=r"^(M|F|O)$")
    highest_qualification: str | None = Field(default=None, max_length=120)
    experience_months: int = Field(default=0, ge=0, le=900)
    publications: int = Field(default=0, ge=0, le=1000)
    address: str | None = Field(default=None, max_length=500)


class JobApplicationIn(_Strict):
    applicant: ApplicantIn
    category: str | None = Field(default=None, max_length=20)
    api_score: Decimal | None = Field(default=None, ge=0, le=1000)
    documents: list[dict[str, Any]] | None = Field(default=None, max_length=20)


class JobApplicationOut(ORMModel):
    id: uuid.UUID
    posting_id: uuid.UUID
    name: str | None = None
    email: MaskedEmail = None
    phone: MaskedPhone = None
    applicant: dict[str, Any] | None = None
    category: str | None = None
    api_score: Decimal | None = None
    screening_score: Decimal | None = None
    interview_total: Decimal | None = None
    status: str
    staff_id: uuid.UUID | None = None
    created_at: datetime


class PublicApplicationResult(BaseModel):
    reference: str
    status: str


class ScreenIn(_Strict):
    screening_score: Decimal = Field(ge=0, le=1000)
    remarks: str | None = Field(default=None, max_length=1000)


class ShortlistIn(_Strict):
    application_ids: list[uuid.UUID] | None = None  # manual pick
    min_screening_score: Decimal | None = Field(default=None, ge=0)  # rule
    limit: int | None = Field(default=None, ge=1, le=1000)


class OfferIn(_Strict):
    designation_id: uuid.UUID | None = None
    basic_paise: int | None = Field(default=None, gt=0)
    joining_by: date | None = None
    remarks: str | None = Field(default=None, max_length=1000)


class JoinIn(_Strict):
    joining_date: date
    designation_id: uuid.UUID | None = None
    employment_type: EmploymentType = EmploymentType.REGULAR


class StatusChangeResult(BaseModel):
    id: uuid.UUID
    status: str
    changed: int = 1
    staff_id: uuid.UUID | None = None


class PanelMember(_Strict):
    user_id: uuid.UUID
    role: str = Field(default="member", max_length=40)
    weight: float = Field(default=1.0, gt=0, le=10)


class PanelIn(_Strict):
    scheduled_at: datetime
    venue: str | None = Field(default=None, max_length=200)
    members: list[PanelMember] = Field(min_length=1, max_length=20)


class PanelOut(ORMModel):
    id: uuid.UUID
    posting_id: uuid.UUID
    scheduled_at: datetime
    venue: str | None = None
    members: list[dict[str, Any]]
    created_at: datetime


class ScoreIn(_Strict):
    application_id: uuid.UUID
    scores: dict[str, float] = Field(min_length=1, description="criterion → score (0–100)")
    remarks: str | None = Field(default=None, max_length=1000)


class ScoreOut(BaseModel):
    panel_id: uuid.UUID
    application_id: uuid.UUID
    scores: dict[str, Any]
    total: Decimal | None = None
    members_scored: int


# ---- appraisal (PBAS) / CAS ------------------------------------------------------------------------------------------
class AppraisalSelfIn(_Strict):
    academic_year_id: uuid.UUID | None = None  # default: the current academic year
    self_assessment: dict[str, dict[str, float]] = Field(default_factory=dict)  # {category: {item: value}}


class AppraisalReviewIn(_Strict):
    decision: str = Field(default="approve", pattern=r"^(approve|reject)$")
    reviewer_score: Decimal | None = Field(default=None, ge=0, le=1000)
    comment: str | None = Field(default=None, max_length=2000)


class AppraisalOut(ORMModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    employee_id: str | None = None
    academic_year_id: uuid.UUID
    academic_year: str | None = None
    self_assessment: dict[str, Any] | None = None
    self_score: Decimal | None = None
    reviewer_staff_id: uuid.UUID | None = None
    reviewer_score: Decimal | None = None
    final_score: Decimal | None = None
    status: str
    workflow_instance_id: uuid.UUID | None = None
    breakdown: dict[str, float] = Field(default_factory=dict)
    auto_filled: dict[str, int] = Field(default_factory=dict)
    updated_at: datetime | None = None


class CasApplicationIn(_Strict):
    to_cadre: Cadre | None = None  # default: the pack's next cadre
    documents: list[dict[str, Any]] | None = Field(default=None, max_length=30)


class CasScreenIn(_Strict):
    status: str = Field(default="screened", pattern=r"^(screened|interviewed)$")
    remarks: str | None = Field(default=None, max_length=1000)


class CasDecideIn(_Strict):
    decision: str = Field(pattern=r"^(approve|reject)$")
    new_designation_id: uuid.UUID | None = None
    new_basic_paise: int | None = Field(default=None, gt=0)
    effective_date: date | None = None
    comment: str | None = Field(default=None, max_length=1000)


class CasApplicationOut(ORMModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    employee_id: str | None = None
    from_cadre: str
    to_cadre: str
    eligibility_date: date | None = None
    eligible_now: bool = False
    api_breakdown: dict[str, Any] | None = None
    documents: list[Any] | None = None
    status: str
    workflow_instance_id: uuid.UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime
