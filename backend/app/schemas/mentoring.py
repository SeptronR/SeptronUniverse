"""Mentoring & early-warning schemas — Prompts/27 §27.4 (OpenAPI names prefixed ``Ment`` / ``Risk``)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


AllocationRuleLit = Literal["section_advisor", "round_robin", "department"]
SessionModeLit = Literal["in_person", "online", "phone", "group"]
ConcernLit = Literal["academic", "personal", "financial", "health", "career"]


# ---- assignments ----------------------------------------------------------------------------------------------------------
class MentAssignmentCreate(_Strict):
    mentor_staff_id: uuid.UUID
    enrollment_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    term_id: uuid.UUID


class MentScope(_Strict):
    department_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None


class MentBulkAssign(_Strict):
    term_id: uuid.UUID
    scope: MentScope = Field(default_factory=MentScope)
    rule: AllocationRuleLit = "round_robin"
    ratio: int | None = Field(None, ge=1, le=200)
    mentor_staff_ids: list[uuid.UUID] | None = None
    preview: bool = False
    carry_forward_from_term_id: uuid.UUID | None = None


class MentAssignSummary(BaseModel):
    term_id: uuid.UUID
    rule: str
    students: int
    assigned: int
    skipped_existing: int
    mentors: int
    unassigned: int
    preview: bool = False
    per_mentor: dict[str, int] = {}


class MentReassign(_Strict):
    mentor_staff_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=500)


class MentAssignmentOut(BaseModel):
    id: uuid.UUID
    mentor_staff_id: uuid.UUID
    mentor_name: str | None = None
    student_program_enrollment_id: uuid.UUID
    student_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    department_id: uuid.UUID | None = None
    term_id: uuid.UUID
    from_on: date | None = None
    to_on: date | None = None
    status: str
    risk_level: str | None = None
    sessions: int = 0
    history: list[dict[str, Any]] = []


class MentLoadRow(BaseModel):
    mentor_staff_id: uuid.UUID
    mentor_name: str | None = None
    department_id: uuid.UUID | None = None
    mentees: int
    sessions: int
    compliant_mentees: int
    over_ratio: bool


class MentLoadReport(BaseModel):
    term_id: uuid.UUID
    default_ratio: int
    min_sessions: int
    rows: list[MentLoadRow]
    coverage_pct: float
    compliance_pct: float


class MentMyMentor(BaseModel):
    assignment_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    mentor_staff_id: uuid.UUID | None = None
    mentor_name: str | None = None
    mentor_email: str | None = None
    mentor_phone: str | None = None
    next_slots: list["MentSlotOut"] = []
    open_action_items: list[dict[str, Any]] = []


class MentProfile360(BaseModel):
    enrollment_id: uuid.UUID
    student: dict[str, Any]
    attendance_pct: float | None = None
    attendance: list[dict[str, Any]] = []
    cia_summary: dict[str, Any] = {}
    dues: dict[str, Any] = {}
    holds: list[dict[str, Any]] = []
    standing: str | None = None
    hostel: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    sessions: list["MentSessionOut"] = []
    referrals: list["MentReferralOut"] = []
    achievements: list[dict[str, Any]] = []
    access: str = "mentor"


# ---- slots / bookings ------------------------------------------------------------------------------------------------------
class MentSlotCreate(_Strict):
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(1, ge=1, le=50)
    location: str | None = Field(None, max_length=120)
    repeat_weeks: int = Field(0, ge=0, le=26)

    @model_validator(mode="after")
    def _range(self) -> "MentSlotCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class MentSlotOut(BaseModel):
    id: uuid.UUID
    mentor_staff_id: uuid.UUID
    mentor_name: str | None = None
    starts_at: datetime
    ends_at: datetime
    capacity: int
    booked: int = 0
    location: str | None = None
    bookings: list["MentBookingOut"] = []


class MentSlotBook(_Strict):
    enrollment_id: uuid.UUID | None = None
    note: str | None = Field(None, max_length=300)


class MentBookingOut(BaseModel):
    id: uuid.UUID
    slot_id: uuid.UUID
    starts_at: datetime | None = None
    student_program_enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    guardian_user_id: uuid.UUID | None = None
    guardian_name: str | None = None
    status: str
    created_at: datetime | None = None


# ---- sessions --------------------------------------------------------------------------------------------------------------
class MentActionItem(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    owner: Literal["student", "mentor", "guardian", "other"] = "student"
    due_on: date | None = None
    done: bool = False


class MentSessionCreate(_Strict):
    assignment_id: uuid.UUID
    held_on: date
    mode: SessionModeLit = "in_person"
    notes: str | None = Field(None, max_length=10000)
    concerns: list[ConcernLit] = []
    action_items: list[MentActionItem] = []
    follow_up_on: date | None = None
    is_confidential: bool = False
    share_with_guardian: bool = False
    guardian_summary: str | None = Field(None, max_length=2000)
    booking_id: uuid.UUID | None = None


class MentSessionUpdate(_Strict):
    held_on: date | None = None
    mode: SessionModeLit | None = None
    notes: str | None = Field(None, max_length=10000)
    concerns: list[ConcernLit] | None = None
    action_items: list[MentActionItem] | None = None
    follow_up_on: date | None = None
    is_confidential: bool | None = None
    share_with_guardian: bool | None = None
    guardian_summary: str | None = Field(None, max_length=2000)


class MentActionItemUpdate(_Strict):
    done: bool


class MentSessionOut(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    mentor_name: str | None = None
    held_on: date
    mode: str
    is_confidential: bool
    notes: str | None = None
    concerns: list[str] = []
    action_items: list[dict[str, Any]] = []
    follow_up_on: date | None = None
    share_with_guardian: bool = False
    guardian_summary: str | None = None
    redacted: bool = False


# ---- referrals -------------------------------------------------------------------------------------------------------------
class MentReferralCreate(_Strict):
    enrollment_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=2000)
    counsellor_staff_id: uuid.UUID | None = None


class MentReferralUpdate(_Strict):
    status: Literal["scheduled", "in_progress", "closed"] | None = None
    counsellor_staff_id: uuid.UUID | None = None
    appointment_slot_id: uuid.UUID | None = None
    student_consent: bool = False
    note: str | None = Field(None, max_length=1000)


class MentReferralOut(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime | None = None
    student_program_enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    counsellor_staff_id: uuid.UUID | None = None
    counsellor_name: str | None = None
    reason: str | None = None
    referred_by: uuid.UUID | None = None
    appointment_id: uuid.UUID | None = None


class MentReferralCounts(BaseModel):
    by_status: dict[str, int]
    total: int


# ---- risk ------------------------------------------------------------------------------------------------------------------
class RiskRunRequest(_Strict):
    term_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    enrollment_ids: list[uuid.UUID] | None = None


class RiskFlagOut(BaseModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    department_id: uuid.UUID | None = None
    term_id: uuid.UUID | None = None
    score: float | None = None
    level: str
    factors: dict[str, Any] = {}
    computed_at: datetime | None = None
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    action: str | None = None


class RiskAcknowledge(_Strict):
    action: str = Field(min_length=3, max_length=500)


class RiskComputeSummary(BaseModel):
    term_id: uuid.UUID | None = None
    computed: int
    by_level: dict[str, int]
    new_high: int


class RiskHeatCell(BaseModel):
    department_id: uuid.UUID | None = None
    department_code: str | None = None
    low: int = 0
    medium: int = 0
    high: int = 0


MentMyMentor.model_rebuild()
MentProfile360.model_rebuild()
MentSlotOut.model_rebuild()
