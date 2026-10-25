"""Clubs, activity hours, achievements, committee stub and student-support stats — Prompts/27 §27.4 (OpenAPI names
prefixed ``Club`` / ``Act`` / ``Ach`` / ``GovCommittee`` / ``Support``)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


ClubTypeLit = Literal["technical", "cultural", "sports", "social", "professional_chapter", "nss", "ncc", "extension"]
ClubRoleLit = Literal["member", "president", "vice_president", "secretary", "treasurer", "coordinator"]
ActivityTypeLit = Literal["nss", "ncc", "community_service", "club", "sports"]
AchCategoryLit = Literal["sports", "cultural", "technical", "research", "hackathon", "other"]


class ClubIn(_Strict):
    name: str = Field(min_length=2, max_length=120)
    club_type: ClubTypeLit
    college_id: uuid.UUID | None = None
    faculty_advisor_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=5000)
    budget_paise: int | None = Field(None, ge=0)
    is_active: bool = True


class ClubOut(BaseModel):
    id: uuid.UUID
    name: str
    club_type: str
    college_id: uuid.UUID | None = None
    faculty_advisor_id: uuid.UUID | None = None
    advisor_name: str | None = None
    description: str | None = None
    budget_paise: int | None = None
    is_active: bool
    members: int = 0
    pending: int = 0
    events: int = 0
    my_role: str | None = None
    is_advisor: bool = False


class ClubMemberIn(_Strict):
    enrollment_id: uuid.UUID
    role: ClubRoleLit = "member"
    from_on: date | None = None


class ClubMemberDecide(_Strict):
    approve: bool
    remarks: str | None = Field(None, max_length=500)


class ClubMemberRole(_Strict):
    role: ClubRoleLit
    from_on: date | None = None
    to_on: date | None = None


class ClubMemberOut(BaseModel):
    id: uuid.UUID
    club_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    role: str
    from_on: date | None = None
    to_on: date | None = None


class ClubEventIn(_Strict):
    title: str = Field(min_length=2, max_length=200)
    held_on: date | None = None
    venue: str | None = Field(None, max_length=200)
    participants_count: int | None = Field(None, ge=0)
    budget_paise: int | None = Field(None, ge=0)
    report_url: str | None = None
    images: list[str] = []
    event_id: uuid.UUID | None = None
    log_hours: float | None = Field(None, gt=0, le=24)


class ClubEventOut(BaseModel):
    id: uuid.UUID
    club_id: uuid.UUID
    title: str
    held_on: date | None = None
    venue: str | None = None
    participants_count: int | None = None
    budget_paise: int | None = None
    report_url: str | None = None
    images: list[Any] = []
    event_id: uuid.UUID | None = None
    event_title: str | None = None
    created_at: datetime | None = None


class ActHourCreate(_Strict):
    activity_type: ActivityTypeLit
    hours: float = Field(gt=0, le=24)
    on_date: date
    description: str | None = Field(None, max_length=200)
    evidence_url: str | None = Field(None, max_length=1000)
    club_id: uuid.UUID | None = None
    enrollment_id: uuid.UUID | None = None


class ActHourBulk(_Strict):
    rows: list[ActHourCreate] = Field(min_length=1, max_length=5000)
    auto_verify: bool = False


class ActHourOut(BaseModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    activity_type: str
    hours: float
    on_date: date
    description: str | None = None
    evidence_url: str | None = None
    status: str
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    credits_course_id: uuid.UUID | None = None
    created_at: datetime | None = None


class ActVerify(_Strict):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    approve: bool = True
    remarks: str | None = Field(None, max_length=200)


class ActVerifyResult(BaseModel):
    verified: int
    rejected: int
    skipped: int
    credit_eligible: int = 0


class ActLedger(BaseModel):
    enrollment_id: uuid.UUID
    by_type: dict[str, float]
    total: float
    verified: float
    pending: float
    credits_eligible: list[dict[str, Any]] = []
    entries: list[ActHourOut] = []


class ActCreditEligible(BaseModel):
    enrollment_id: uuid.UUID
    student_name: str | None = None
    course_id: uuid.UUID
    course_code: str | None = None
    verified_hours: float
    min_hours: float
    mapped: bool


class AchCreate(_Strict):
    category: AchCategoryLit
    title: str = Field(min_length=2, max_length=200)
    level: Literal["college", "university", "state", "national", "international"] | None = None
    position: str | None = Field(None, max_length=20)
    held_on: date | None = None
    evidence_url: str | None = Field(None, max_length=1000)
    enrollment_id: uuid.UUID | None = None


class AchVerify(_Strict):
    approve: bool = True
    remarks: str | None = Field(None, max_length=300)


class AchOut(BaseModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    department_id: uuid.UUID | None = None
    category: str
    title: str
    level: str | None = None
    position: str | None = None
    held_on: date | None = None
    evidence_url: str | None = None
    verified: bool
    verified_at: datetime | None = None
    created_at: datetime | None = None


class GovCommitteeIn(_Strict):
    name: str = Field(min_length=2, max_length=160)
    committee_type: str = Field(min_length=2, max_length=30)
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    chair_staff_id: uuid.UUID | None = None
    secretary_staff_id: uuid.UUID | None = None
    constituted_on: date | None = None
    valid_to: date | None = None
    is_active: bool = True


class GovCommitteeOut(BaseModel):
    id: uuid.UUID
    name: str
    committee_type: str
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    chair_staff_id: uuid.UUID | None = None
    chair_name: str | None = None
    secretary_staff_id: uuid.UUID | None = None
    constituted_on: date | None = None
    valid_to: date | None = None
    is_active: bool
    members: int = 0


class GovCommitteeMemberIn(_Strict):
    member_type: Literal["staff", "student", "external"] = "staff"
    staff_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    external: dict[str, Any] | None = None
    role: str = Field("member", max_length=40)
    from_on: date | None = None
    to_on: date | None = None


class GovCommitteeMemberOut(BaseModel):
    id: uuid.UUID
    committee_id: uuid.UUID
    member_type: str
    staff_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    name: str | None = None
    role: str
    from_on: date | None = None
    to_on: date | None = None


class SupportStats(BaseModel):
    term_id: uuid.UUID | None = None
    mentoring: dict[str, Any]
    risk: dict[str, int]
    grievances: dict[str, Any]
    discipline: dict[str, Any]
    surveys: dict[str, Any]
    clubs: dict[str, Any]
    achievements: dict[str, Any]
