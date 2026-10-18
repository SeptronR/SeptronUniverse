"""Exam administration schemas — Prompts/14 §14.4."""

import uuid
from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

Slot = Literal["FN", "AN", "EVE"]


class ExamSessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    term_id: uuid.UUID
    college_id: uuid.UUID | None = None
    exam_kind: Literal["regular", "supplementary", "arrear", "improvement", "special", "summer", "practical"] = (
        "regular"
    )
    coe_staff_id: uuid.UUID | None = None
    registration_start: datetime | None = None
    registration_end: datetime | None = None
    late_fee_until: datetime | None = None
    fee_rules: dict[str, Any] | None = Field(
        None, description="{per_course_paise, per_arrear_paise, practical_paise, max_paise, late_fee_paise}"
    )
    hall_ticket_release_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    valuation_mode: Literal["single", "double"] | None = None
    discrepancy_pct: float | None = Field(None, ge=0, le=100)
    grading_scale_id: uuid.UUID | None = None


class ExamSessionUpdate(BaseModel):
    name: str | None = Field(None, max_length=120)
    registration_start: datetime | None = None
    registration_end: datetime | None = None
    late_fee_until: datetime | None = None
    fee_rules: dict[str, Any] | None = None
    hall_ticket_release_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    valuation_mode: Literal["single", "double"] | None = None
    discrepancy_pct: float | None = None
    coe_staff_id: uuid.UUID | None = None
    version: int | None = None


class ExamSessionResponse(ORMModel):
    id: uuid.UUID
    name: str
    term_id: uuid.UUID
    college_id: uuid.UUID | None = None
    exam_kind: str
    coe_staff_id: uuid.UUID | None = None
    registration_start: datetime | None = None
    registration_end: datetime | None = None
    late_fee_until: datetime | None = None
    fee_rules: dict[str, Any] | None = None
    hall_ticket_release_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    valuation_mode: str
    discrepancy_pct: float
    grading_scale_id: uuid.UUID | None = None
    status: str
    is_locked: bool
    version: int
    counts: dict[str, int] = Field(default_factory=dict)


class SessionStatusChange(BaseModel):
    status: str
    reason: str | None = None


class ExamPaperCreate(BaseModel):
    course_id: uuid.UUID
    paper_type: Literal["theory", "practical", "project_viva", "dissertation", "online"] = "theory"
    paper_code: str | None = Field(None, max_length=30)
    exam_date: date | None = None
    session_slot: Slot | None = None
    start_time: time | None = None
    duration_minutes: int | None = Field(None, ge=10, le=600)
    max_marks: float = Field(100, gt=0)
    qp_pattern: dict[str, Any] | None = None
    quiz_id: uuid.UUID | None = None


class ExamPaperUpdate(BaseModel):
    exam_date: date | None = None
    session_slot: Slot | None = None
    start_time: time | None = None
    duration_minutes: int | None = None
    max_marks: float | None = None
    qp_pattern: dict[str, Any] | None = None
    status: str | None = None


class ExamPaperResponse(ORMModel):
    id: uuid.UUID
    exam_session_id: uuid.UUID
    course_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    paper_code: str | None = None
    paper_type: str
    exam_date: date | None = None
    session_slot: str | None = None
    start_time: time | None = None
    duration_minutes: int | None = None
    max_marks: float
    qp_pattern: dict[str, Any] | None = None
    quiz_id: uuid.UUID | None = None
    status: str
    registered: int = 0


class BulkPapersRequest(BaseModel):
    from_offerings: bool = True
    include_arrears: bool = True
    dry_run: bool = False


class BulkPapersPreview(BaseModel):
    theory: int = 0
    practical: int = 0
    project_viva: int = 0
    arrear_only: int = 0
    existing: int = 0
    created: int = 0
    dry_run: bool = False


class DateSheetEntry(BaseModel):
    paper_id: uuid.UUID
    exam_date: date
    session_slot: Slot
    start_time: time | None = None
    duration_minutes: int | None = None


class DateSheetUpdate(BaseModel):
    entries: list[DateSheetEntry]


class ClashItem(BaseModel):
    student_program_enrollment_id: uuid.UUID
    registration_number: str | None = None
    exam_date: date
    session_slot: str
    papers: list[str] = Field(default_factory=list)


class ClashReport(BaseModel):
    items: list[ClashItem] = Field(default_factory=list)
    holidays: list[dict[str, Any]] = Field(default_factory=list)
    unscheduled: list[str] = Field(default_factory=list)


class ExamRegistrationItemOut(ORMModel):
    id: uuid.UUID
    exam_paper_id: uuid.UUID
    course_id: uuid.UUID
    course_code: str | None = None
    course_title: str | None = None
    paper_type: str | None = None
    exam_date: date | None = None
    session_slot: str | None = None
    attempt_type: str
    attempt_number: int
    fee_paise: int
    eligibility: str
    status: str
    seat: dict[str, Any] | None = None


class ExamRegistrationResponse(ORMModel):
    id: uuid.UUID
    exam_session_id: uuid.UUID
    session_name: str | None = None
    student_program_enrollment_id: uuid.UUID
    registration_number: str | None = None
    student_name: str | None = None
    college_id: uuid.UUID
    status: str
    fee_invoice_id: uuid.UUID | None = None
    invoice_status: str | None = None
    total_fee_paise: int
    late_fee_paise: int = 0
    hall_ticket_number: str | None = None
    hall_ticket_issued_at: datetime | None = None
    hall_ticket_available: bool = False
    eligibility_snapshot: dict[str, Any] | None = None
    holds: list[str] = Field(default_factory=list)
    items: list[ExamRegistrationItemOut] = Field(default_factory=list)
    version: int


class RegistrationSubmit(BaseModel):
    item_ids: list[uuid.UUID] | None = None


class RegistrationAdminCreate(BaseModel):
    enrollment_id: uuid.UUID
    paper_ids: list[uuid.UUID] = Field(min_length=1)
    attempt_types: dict[str, str] | None = None
    confirm: bool = False


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class EligibilityApplyRequest(BaseModel):
    version: int | None = None
    recompute: bool = False


class EligibilityApplySummary(BaseModel):
    registrations: int = 0
    items: int = 0
    by_decision: dict[str, int] = Field(default_factory=dict)
    version: int | None = None


class HallTicketGenerateRequest(BaseModel):
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    only_missing: bool = True


class HallTicketVerifyResponse(BaseModel):
    valid: bool
    student_masked: str | None = None
    hall_ticket_number: str | None = None
    session: str | None = None
    papers: list[dict[str, Any]] = Field(default_factory=list)
    issued_at: datetime | None = None
    reason: str | None = None


class SeatingGenerateRequest(BaseModel):
    exam_date: date
    session_slot: Slot
    room_ids: list[uuid.UUID] = Field(min_length=1)
    strategy: Literal["mixed_course", "by_course"] = "mixed_course"
    seats_per_row: int = Field(6, ge=1, le=20)
    dry_run: bool = False


class SeatingSummary(BaseModel):
    candidates: int = 0
    seats: int = 0
    allocated: int = 0
    rooms: list[dict[str, Any]] = Field(default_factory=list)
    adjacency_same_paper: int = 0
    dry_run: bool = False


class SeatAllocationRow(BaseModel):
    id: uuid.UUID
    seating_plan_id: uuid.UUID
    room_code: str | None = None
    seat_number: str
    row_no: int | None = None
    col_no: int | None = None
    exam_registration_item_id: uuid.UUID
    hall_ticket_number: str | None = None
    registration_number: str | None = None
    paper_code: str | None = None
    status: str | None = None


class SeatMove(BaseModel):
    seating_plan_id: uuid.UUID | None = None
    seat_number: str = Field(min_length=1, max_length=10)


class InvigilationAutoAssignRequest(BaseModel):
    date_from: date
    date_to: date
    roles_per_room: dict[str, int] = Field(default_factory=lambda: {"invigilator": 2, "hall_superintendent": 1})
    exclude_staff_ids: list[uuid.UUID] = Field(default_factory=list)
    max_duties_per_staff: int = Field(6, ge=1, le=60)
    dry_run: bool = False


class RosterSummary(BaseModel):
    slots: int = 0
    rooms: int = 0
    duties: int = 0
    unfilled: list[dict[str, Any]] = Field(default_factory=list)
    per_staff_max: int = 0
    dry_run: bool = False


class DutyCreate(BaseModel):
    exam_session_id: uuid.UUID
    exam_date: date
    session_slot: Slot
    room_id: uuid.UUID | None = None
    staff_id: uuid.UUID
    role: str = "invigilator"


class DutyUpdate(BaseModel):
    room_id: uuid.UUID | None = None
    role: str | None = None
    status: str | None = None


class DutyResponse(ORMModel):
    id: uuid.UUID
    exam_session_id: uuid.UUID
    exam_date: date
    session_slot: str
    room_id: uuid.UUID | None = None
    room_code: str | None = None
    staff_id: uuid.UUID
    staff_name: str | None = None
    role: str
    status: str
    swap_with_staff_id: uuid.UUID | None = None
    remuneration_paise: int | None = None


class SwapRequest(BaseModel):
    with_staff_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=500)


class HallAttendanceRow(BaseModel):
    exam_registration_item_id: uuid.UUID
    status: Literal["present", "absent", "late", "malpractice"]
    answer_booklet_number: str | None = Field(None, max_length=30)
    face_match_score: float | None = None


class HallAttendanceMark(BaseModel):
    items: list[HallAttendanceRow] = Field(min_length=1)


class HallAttendanceRowOut(BaseModel):
    exam_registration_item_id: uuid.UUID
    hall_ticket_number: str | None = None
    registration_number: str | None = None
    student_name: str | None = None
    room_code: str | None = None
    seat_number: str | None = None
    status: str | None = None
    answer_booklet_number: str | None = None
    face_match_score: float | None = None


class MalpracticeReportCreate(BaseModel):
    exam_registration_item_id: uuid.UUID
    category: Literal["copying", "impersonation", "device", "material", "misconduct", "tampering", "other"]
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    invigilator_report: str = Field(min_length=3)


class MalpracticeOut(ORMModel):
    id: uuid.UUID
    case_number: str
    exam_registration_item_id: uuid.UUID
    category: str
    status: str
    reported_at: datetime


class QpAssignmentCreate(BaseModel):
    setter_staff_id: uuid.UUID | None = None
    external_setter: dict[str, Any] | None = Field(None, description="{name, email, phone, institution, user_id?}")
    set_label: str = Field("A", max_length=5)
    blueprint_id: uuid.UUID | None = None
    due_at: datetime | None = None
    remuneration_paise: int | None = Field(None, ge=0)


class QpAssignmentResponse(ORMModel):
    id: uuid.UUID
    exam_paper_id: uuid.UUID
    paper_code: str | None = None
    course_code: str | None = None
    setter_staff_id: uuid.UUID | None = None
    setter_name: str | None = None
    external_setter: dict[str, Any] | None = None
    set_label: str
    blueprint_id: uuid.UUID | None = None
    status: str
    has_file: bool = False
    submitted_at: datetime | None = None
    scrutiny_remarks: str | None = None
    remuneration_paise: int | None = None
    due_at: str | None = None


class QpScrutinyRequest(BaseModel):
    decision: Literal["approve", "reject"]
    remarks: str | None = None


class QpPrintRequest(BaseModel):
    copies: int = Field(ge=1, le=5000)
    watermark_text: str | None = Field(None, max_length=120)


class QpPrintResponse(BaseModel):
    download_token: str
    expires_in: int = 600
    copies: int


class OnlinePaperSetup(BaseModel):
    quiz_id: uuid.UUID
    proctoring: dict[str, Any] | None = None


class ExamCentreIn(BaseModel):
    college_id: uuid.UUID
    centre_code: str = Field(min_length=1, max_length=20)
    chief_superintendent_staff_id: uuid.UUID | None = None
    capacity: int | None = Field(None, ge=1)
    assigned_colleges: list[uuid.UUID] = Field(default_factory=list)


class ExamCentreOut(ORMModel):
    id: uuid.UUID
    exam_session_id: uuid.UUID
    college_id: uuid.UUID
    centre_code: str
    chief_superintendent_staff_id: uuid.UUID | None = None
    capacity: int | None = None
    assigned_colleges: list[str] | None = None


class RemunerationSummary(BaseModel):
    by_role: dict[str, int] = Field(default_factory=dict)
    by_staff: list[dict[str, Any]] = Field(default_factory=list)
    qp: int = 0
    total_paise: int = 0
