"""Attendance & eligibility schemas — Prompts/11 §11.4.

Names that would collide with earlier OpenAPI schemas are prefixed (``StudentPunchIngest`` — Phase 06 owns
``PunchIngest``, ``GeoPoint`` and ``AttendanceSummaryRow``: ``CheckinGeo`` / ``StudentAttendanceSummary``).
"""

import uuid
from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums.attendance import (
    AttendanceMark,
    AttendanceSource,
    CondonationReason,
    EligibilityDecision,
    OdReasonType,
)

MarkLiteral = Literal["present", "absent", "late", "on_duty", "leave", "medical", "exempt"]


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- marking ----------------------------------------------------------------------------------------------------------
class RosterRow(BaseModel):
    student_program_enrollment_id: uuid.UUID
    student_id: uuid.UUID
    name: str
    registration_number: str | None = None
    roll_number: str | None = None
    photo_url: str | None = None
    status: str | None = None
    source: str | None = None
    remarks: str | None = None
    marked_at: datetime | None = None
    prefill: str | None = Field(default=None, description="on_duty when an approved OD covers the date")


class SessionForAttendance(BaseModel):
    session_id: uuid.UUID
    offering_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    section_name: str | None = None
    session_date: date
    start_time: time
    end_time: time
    room_code: str | None = None
    staff_id: uuid.UUID | None = None
    status: str
    attendance_status: str
    finalized_at: datetime | None = None
    can_mark: bool = False
    can_edit_finalized: bool = False
    counts: dict[str, int] = Field(default_factory=dict)
    roster: list[RosterRow] = Field(default_factory=list)


class MarkItem(BaseModel):
    student_program_enrollment_id: uuid.UUID
    status: AttendanceMark
    remarks: str | None = Field(default=None, max_length=255)


class BulkMarkRequest(BaseModel):
    marks: list[MarkItem] = Field(default_factory=list, max_length=500)
    mark_rest_as: Literal["present", "absent"] | None = None
    source: AttendanceSource = AttendanceSource.MANUAL
    topic: str | None = Field(default=None, max_length=255)


class RejectedMark(BaseModel):
    student_program_enrollment_id: uuid.UUID
    reason: str


class MarkResult(BaseModel):
    session_id: uuid.UUID
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: list[RejectedMark] = Field(default_factory=list)
    attendance_status: str = "taken"


class FinalizeRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class EditFinalizedRequest(BaseModel):
    marks: list[MarkItem] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=3, max_length=500)


# ---- QR / geo / devices ------------------------------------------------------------------------------------------------
class QrIssueResponse(BaseModel):
    session_id: uuid.UUID
    token: str
    expires_at: datetime
    ttl_seconds: int
    png_base64: str | None = None
    checked_in: int = 0


class CheckinGeo(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None


class QrCheckinRequest(BaseModel):
    token: str = Field(min_length=8, max_length=64)
    geo: CheckinGeo | None = None


class GeoCheckinRequest(BaseModel):
    session_id: uuid.UUID
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None


class CheckinResult(BaseModel):
    session_id: uuid.UUID
    status: str
    source: str
    duplicate: bool = False
    course_code: str | None = None


class StudentPunch(BaseModel):
    identifier: str = Field(min_length=1, max_length=60, description="registration / enrolment number or card id")
    at: datetime
    direction: Literal["in", "out"] | None = None


class StudentPunchIngest(BaseModel):
    device_token: str = Field(min_length=8)
    punches: list[StudentPunch] = Field(min_length=1, max_length=2000)


class UnmatchedPunch(BaseModel):
    identifier: str
    at: datetime
    reason: str
    device_id: uuid.UUID | None = None
    candidates: int = 0


class StudentPunchResult(BaseModel):
    marked: int = 0
    duplicates: int = 0
    unmatched: list[UnmatchedPunch] = Field(default_factory=list)


# ---- offline -------------------------------------------------------------------------------------------------------------
class OfflineItem(BulkMarkRequest):
    client_id: str = Field(min_length=1, max_length=64)
    session_id: uuid.UUID


class OfflineBatch(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80)
    items: list[OfflineItem] = Field(min_length=1, max_length=50)


class OfflineItemResult(BaseModel):
    client_id: str
    session_id: uuid.UUID
    ok: bool
    code: str | None = None
    message: str | None = None
    result: MarkResult | None = None


class OfflineBatchResult(BaseModel):
    idempotency_key: str
    replayed: bool = False
    items: list[OfflineItemResult] = Field(default_factory=list)


# ---- summaries -----------------------------------------------------------------------------------------------------------
class Totals(BaseModel):
    total_sessions: int = 0
    present: int = 0
    absent: int = 0
    on_duty: int = 0
    late: int = 0
    exempt: int = 0


class StudentAttendanceSummary(Totals):
    offering_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    course_code: str | None = None
    course_title: str | None = None
    credits: float | None = None
    pct: float = 0
    eligibility: str = "eligible"
    min_pct: float = 75
    floor_pct: float = 65
    sessions_needed_for_threshold: int = 0
    sessions_can_miss: int = 0
    computed_at: datetime | None = None


class SummaryResponse(BaseModel):
    offering_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    totals: Totals
    pct: float = 0
    eligibility: dict[str, int] = Field(default_factory=dict)
    rows: list[StudentAttendanceSummary] = Field(default_factory=list)


class MySummaryResponse(BaseModel):
    term_id: uuid.UUID | None = None
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    overall_pct: float = 0
    attendance_mode: str = "course_wise"
    per_offering: list[StudentAttendanceSummary] = Field(default_factory=list)


class RegisterGrid(BaseModel):
    offering_id: uuid.UUID
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    students: list[dict[str, Any]] = Field(default_factory=list)
    marks: dict[str, dict[str, str]] = Field(default_factory=dict, description="{enrolment_id: {session_id: status}}")


class StudentHistoryRow(BaseModel):
    session_id: uuid.UUID
    session_date: date
    start_time: time
    course_code: str | None = None
    status: str | None = None
    source: str | None = None


class MissingSessionRow(BaseModel):
    session_id: uuid.UUID
    session_date: date
    start_time: time
    course_code: str | None = None
    staff_name: str | None = None
    department_id: uuid.UUID | None = None


# ---- on duty ------------------------------------------------------------------------------------------------------------
class OdCreate(BaseModel):
    from_date: date
    to_date: date
    reason_type: OdReasonType
    reason: str | None = Field(default=None, max_length=2000)
    documents: list[dict[str, Any]] | None = None
    student_program_enrollment_id: uuid.UUID | None = Field(default=None, description="staff filing for a student")

    @model_validator(mode="after")
    def _range(self) -> "OdCreate":
        if self.to_date < self.from_date:
            raise ValueError("to_date must not be before from_date")
        if (self.to_date - self.from_date).days > 30:
            raise ValueError("an OD request spans at most 31 days")
        return self


class OdDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


class OdResponse(_Out):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    from_date: date
    to_date: date
    reason_type: str
    reason: str | None = None
    documents: list[dict[str, Any]] | None = None
    status: str
    recommended_by: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    sessions_applied: list[str] | None = None
    workflow_instance_id: uuid.UUID | None = None
    created_at: datetime | None = None
    can_recommend: bool = False
    can_approve: bool = False


# ---- condonation ---------------------------------------------------------------------------------------------------------
class CondonationCreate(BaseModel):
    offering_id: uuid.UUID | None = Field(default=None, description="omit for aggregate mode")
    term_id: uuid.UUID | None = None
    reason_type: CondonationReason
    reason: str | None = Field(default=None, max_length=2000)
    documents: list[dict[str, Any]] | None = None
    student_program_enrollment_id: uuid.UUID | None = Field(default=None, description="advisor filing for a student")


class CondonationDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=1000)


class CondonationResponse(_Out):
    id: uuid.UUID
    college_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    term_id: uuid.UUID
    offering_id: uuid.UUID | None = None
    course_code: str | None = None
    actual_pct: float
    reason_type: str
    reason: str | None = None
    documents: list[dict[str, Any]] | None = None
    fee_invoice_id: uuid.UUID | None = None
    fee_paise: int = 0
    fee_status: str | None = None
    workflow_instance_id: uuid.UUID | None = None
    status: str
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None
    can_act: bool = False


# ---- eligibility ---------------------------------------------------------------------------------------------------------
class EligibilityComputeRequest(BaseModel):
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    offering_ids: list[uuid.UUID] | None = None
    dry_run: bool = False


class EligibilityRunSummary(BaseModel):
    term_id: uuid.UUID
    version: int
    rows: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    job_id: uuid.UUID | None = None
    dry_run: bool = False


class EligibilityRow(_Out):
    id: uuid.UUID
    student_term_record_id: uuid.UUID
    student_program_enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    offering_id: uuid.UUID
    course_code: str | None = None
    attendance_pct: float | None = None
    cia_marks: float | None = None
    cia_max: float | None = None
    is_attendance_ok: bool
    is_cia_ok: bool
    is_fee_ok: bool
    is_hold_ok: bool
    decision: str
    reason_codes: list[str] | None = None
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None
    version: int
    created_at: datetime | None = None


class DecideRequest(BaseModel):
    decision: EligibilityDecision
    reason: str = Field(min_length=3, max_length=500)


class DetentionListRow(BaseModel):
    student_program_enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    program_code: str | None = None
    offering_id: uuid.UUID
    course_code: str | None = None
    attendance_pct: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    version: int


# ---- alert config ---------------------------------------------------------------------------------------------------------
class AlertConfig(BaseModel):
    consecutive_absences: int = Field(default=3, ge=1, le=20)
    checkpoints: list[int] = Field(default_factory=lambda: [25, 50, 75])
    notify_guardians: bool = True
    notify_mentor: bool = True


__all__ = [
    "AlertConfig",
    "StudentAttendanceSummary",
    "BulkMarkRequest",
    "CheckinResult",
    "CondonationCreate",
    "CondonationDecision",
    "CondonationResponse",
    "DecideRequest",
    "DetentionListRow",
    "EditFinalizedRequest",
    "EligibilityComputeRequest",
    "EligibilityRow",
    "EligibilityRunSummary",
    "FinalizeRequest",
    "GeoCheckinRequest",
    "MarkItem",
    "MarkLiteral",
    "MarkResult",
    "MissingSessionRow",
    "MySummaryResponse",
    "OdCreate",
    "OdDecision",
    "OdResponse",
    "OfflineBatch",
    "OfflineBatchResult",
    "OfflineItemResult",
    "QrCheckinRequest",
    "QrIssueResponse",
    "RegisterGrid",
    "RejectedMark",
    "RosterRow",
    "SessionForAttendance",
    "StudentHistoryRow",
    "StudentPunchIngest",
    "StudentPunchResult",
    "SummaryResponse",
    "Totals",
    "UnmatchedPunch",
]
