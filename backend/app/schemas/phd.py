"""PhD & research-scholar management schemas — Prompts/31 §31.4. Money in paise; OpenAPI names that would collide with
earlier phases carry a ``Phd`` prefix (``PhdAwardOut``, ``PhdDisbursementOut``, ``PhdStats``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.enums.phd import (
    DcRating,
    DcRole,
    EtdRepository,
    FellowshipType,
    Recommendation,
    RequestType,
    ScholarMode,
    ThesisStage,
    VivaResult,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhdJobQueued(BaseModel):
    job_id: uuid.UUID


class Chip(BaseModel):
    label: str
    tone: Literal["ok", "warn", "danger", "info"] = "info"


# ---- scholars -----------------------------------------------------------------------------------------------------------
class ExternalPerson(_Strict):
    name: str = Field(min_length=1, max_length=200)
    affiliation: str | None = Field(default=None, max_length=300)
    email: EmailStr | None = None


class ScholarCreate(_Strict):
    enrollment_id: uuid.UUID
    guide_staff_id: uuid.UUID
    co_guide_staff_id: uuid.UUID | None = None
    external_co_guide: ExternalPerson | None = None
    mode: ScholarMode = ScholarMode.FULL_TIME
    fellowship_type: FellowshipType = FellowshipType.NONE
    research_area: str | None = Field(default=None, max_length=300)
    registration_date: date | None = None


class ScholarUpdate(_Strict):
    research_area: str | None = Field(default=None, max_length=300)
    co_guide_staff_id: uuid.UUID | None = None
    external_co_guide: ExternalPerson | None = None
    fellowship_type: FellowshipType | None = None
    relaxation: Literal["women", "pwd", "none"] | None = None
    ethics_approval_id: uuid.UUID | None = None


class GuideAllocate(_Strict):
    guide_staff_id: uuid.UUID
    co_guide_staff_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class GuideChange(_Strict):
    new_guide_staff_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)


class Discontinue(_Strict):
    reason: Literal["unsatisfactory_progress", "max_duration_exceeded", "voluntary", "other"]
    remarks: str | None = Field(default=None, max_length=1000)


class GuideLoadOut(BaseModel):
    staff_id: uuid.UUID
    name: str | None = None
    department_id: uuid.UUID | None = None
    cadre: str | None = None
    max: int
    current: int
    available: int


class CourseworkSummary(BaseModel):
    status: str
    credits_required: int
    credits_earned: float
    methodology_done: bool
    deadline: date | None = None


class ScholarOut(BaseModel):
    id: uuid.UUID
    enrollment_id: uuid.UUID
    student_id: uuid.UUID | None = None
    name: str | None = None
    registration_number: str | None = None
    department_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    guide_staff_id: uuid.UUID
    guide_name: str | None = None
    co_guide_staff_id: uuid.UUID | None = None
    co_guide_name: str | None = None
    external_co_guide: dict[str, Any] | None = None
    mode: str
    fellowship_type: str
    research_area: str | None = None
    registration_date: date | None = None
    max_duration_end: date | None = None
    coursework_status: str
    coursework_exemption_reason: str | None = None
    status: str
    months_elapsed: int | None = None
    months_left: int | None = None
    chips: list[Chip] = Field(default_factory=list)
    cancellation_review: bool = False
    relation: list[str] = Field(default_factory=list)
    created_at: datetime


class TimelineEntry(BaseModel):
    at: str
    action: str
    by: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class Scholar360(ScholarOut):
    timeline: list[TimelineEntry] = Field(default_factory=list)
    coursework: CourseworkSummary | None = None
    committee: "DcOut | None" = None
    fellowship: "FellowshipOut | None" = None
    thesis: "ThesisOut | None" = None
    publications: list[dict[str, Any]] = Field(default_factory=list)
    ethics_approval: dict[str, Any] | None = None
    documents: list[dict[str, Any]] = Field(default_factory=list)


# ---- coursework ---------------------------------------------------------------------------------------------------------
class CourseworkPlan(_Strict):
    course_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


class CourseworkExemption(_Strict):
    reason: str = Field(min_length=3, max_length=1000)
    evidence_url: str | None = Field(default=None, max_length=1000)


class CourseworkCourse(BaseModel):
    course_id: uuid.UUID
    code: str
    title: str
    credits: float
    is_methodology: bool
    result: str | None = None


class CourseworkStatusOut(BaseModel):
    scholar_id: uuid.UUID
    status: str
    credits_required: int
    credits_earned: float
    methodology_done: bool
    deadline: date | None = None
    courses: list[CourseworkCourse] = Field(default_factory=list)
    exemption: dict[str, Any] | None = None


# ---- doctoral committee -------------------------------------------------------------------------------------------------
class DcMemberIn(_Strict):
    staff_id: uuid.UUID | None = None
    external: ExternalPerson | None = None
    role: DcRole = DcRole.MEMBER

    @model_validator(mode="after")
    def _one(self) -> "DcMemberIn":
        if (self.staff_id is None) == (self.external is None):
            raise ValueError("a member is either a staff_id or an external person")
        return self


class DcConstitute(_Strict):
    members: list[DcMemberIn] = Field(min_length=2, max_length=8)
    committee_id: uuid.UUID | None = None


class DcOut(BaseModel):
    id: uuid.UUID
    scholar_id: uuid.UUID
    members: list[dict[str, Any]]
    constituted_on: date | None = None
    committee_id: str | None = None
    meetings: int = 0


class DcMeetingCreate(_Strict):
    meeting_no: int = Field(ge=1, le=99)
    held_on: date
    agenda: str | None = Field(default=None, max_length=4000)
    kind: Literal["regular", "pre_synopsis"] = "regular"


class DcRecommendationIn(_Strict):
    text: str = Field(min_length=1, max_length=1000)
    due_on: date | None = None


class DcMeetingMinutes(_Strict):
    minutes: str = Field(min_length=1, max_length=20000)
    recommendations: list[DcRecommendationIn] = Field(default_factory=list, max_length=30)
    attendance: list[str] = Field(default_factory=list, max_length=20)
    minutes_url: str | None = Field(default=None, max_length=1000)


class DcMeetingApprove(_Strict):
    remarks: str | None = Field(default=None, max_length=1000)


class DcMeetingOut(BaseModel):
    id: uuid.UUID
    scholar_id: uuid.UUID
    meeting_no: int
    held_on: date | None = None
    status: str
    kind: str = "regular"
    agenda: str | None = None
    minutes: str | None = None
    minutes_url: str | None = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    attendance: list[str] = Field(default_factory=list)


# ---- progress reports ---------------------------------------------------------------------------------------------------
class ProgressReportSubmit(_Strict):
    period_label: str = Field(pattern=r"^\d{4}-H[12]$")
    report_url: str = Field(min_length=1, max_length=1000)
    summary: str = Field(min_length=1, max_length=8000)


class GuideReview(_Strict):
    remarks: str = Field(min_length=1, max_length=4000)


class DcReview(_Strict):
    rating: DcRating
    remarks: str | None = Field(default=None, max_length=4000)
    meeting_id: uuid.UUID | None = None


class ProgressReportOut(BaseModel):
    id: uuid.UUID
    scholar_id: uuid.UUID
    period_label: str
    report_url: str | None = None
    summary: str | None = None
    guide_remarks: str | None = None
    dc_rating: str | None = None
    dc_remarks: str | None = None
    status: str
    submitted_at: datetime
    reviewed_at: datetime | None = None


class ProgressPeriod(BaseModel):
    period_label: str
    due_on: date
    report_id: uuid.UUID | None = None
    status: str


class ComplianceRow(BaseModel):
    scholar_id: uuid.UUID
    name: str | None = None
    guide_name: str | None = None
    department_id: uuid.UUID | None = None
    due: int
    submitted: int
    overdue: list[str] = Field(default_factory=list)
    unsatisfactory_streak: int = 0


class CancellationDecision(_Strict):
    decision: Literal["warning", "discontinue"]
    remarks: str | None = Field(default=None, max_length=1000)


# ---- fellowships --------------------------------------------------------------------------------------------------------
class FellowshipCreate(_Strict):
    fellowship_type: FellowshipType
    monthly_paise: int | None = Field(default=None, ge=0)
    from_on: date
    to_on: date | None = None
    contingency_paise: int | None = Field(default=None, ge=0)
    hra_applicable: bool = False
    funding_source: str | None = Field(default=None, max_length=120)


class FellowshipUpdate(_Strict):
    monthly_paise: int | None = Field(default=None, ge=0)
    to_on: date | None = None
    contingency_paise: int | None = Field(default=None, ge=0)
    hra_applicable: bool | None = None
    funding_source: str | None = Field(default=None, max_length=120)
    status: Literal["active", "held", "closed"] | None = None


class FellowshipOut(BaseModel):
    id: uuid.UUID
    scholar_id: uuid.UUID
    fellowship_type: str
    monthly_paise: int
    hra_paise: int = 0
    from_on: date
    to_on: date | None = None
    contingency_paise: int | None = None
    contingency_used_paise: int = 0
    hra_applicable: bool
    funding_source: str | None = None
    status: str


class DisbursementRun(_Strict):
    month: date


class DisbursementRunResult(BaseModel):
    month: date
    created: int
    held: int
    skipped: int
    arrears_paise: int = 0


class DisbursementHold(_Strict):
    reason: str = Field(min_length=3, max_length=500)


class DisbursementPay(_Strict):
    disbursement_ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    reference: str = Field(min_length=1, max_length=60)
    paid_on: date | None = None


class ContingencyClaim(_Strict):
    amount_paise: int = Field(gt=0)
    description: str = Field(min_length=3, max_length=500)
    bills: list[str] = Field(default_factory=list, max_length=20)


class PhdDisbursementOut(BaseModel):
    id: uuid.UUID
    fellowship_id: uuid.UUID
    scholar_id: uuid.UUID | None = None
    scholar_name: str | None = None
    fellowship_type: str | None = None
    month: date
    amount_paise: int
    kind: str = "stipend"
    status: str
    hold_reason: str | None = None
    payroll_ref: str | None = None
    paid_at: datetime | None = None


# ---- requests -----------------------------------------------------------------------------------------------------------
class RequestDetails(_Strict):
    months: int | None = Field(default=None, ge=1, le=60)
    new_guide_staff_id: uuid.UUID | None = None
    new_mode: ScholarMode | None = None
    leave_type: Literal["maternity", "medical", "other"] | None = None
    from_on: date | None = None
    to_on: date | None = None
    reason: str = Field(min_length=3, max_length=2000)


class ScholarRequestCreate(_Strict):
    request_type: RequestType
    details: RequestDetails
    attachments: list[str] = Field(default_factory=list, max_length=10)


class GuideNoc(_Strict):
    granted: bool = True
    remarks: str | None = Field(default=None, max_length=1000)


class RequestDecision(_Strict):
    approve: bool
    remarks: str | None = Field(default=None, max_length=1000)


class ScholarRequestOut(BaseModel):
    id: uuid.UUID
    scholar_id: uuid.UUID
    scholar_name: str | None = None
    request_type: str
    details: dict[str, Any] = Field(default_factory=dict)
    status: str
    workflow_instance_id: uuid.UUID | None = None
    workflow_status: str | None = None
    current_step: int | None = None
    actionable: bool = False
    implications: list[str] = Field(default_factory=list)
    decided_at: datetime | None = None
    created_at: datetime


# ---- thesis -------------------------------------------------------------------------------------------------------------
class ThesisSubmit(_Strict):
    stage: ThesisStage
    title: str = Field(min_length=3, max_length=500)
    file_url: str = Field(min_length=1, max_length=1000)
    ai_declaration: bool
    ai_generated_pct: Decimal | None = Field(default=None, ge=0, le=100)
    abstract: str | None = Field(default=None, max_length=8000)
    keywords: list[str] = Field(default_factory=list, max_length=20)


class PlagiarismResult(BaseModel):
    """Adapter callback (``POST /webhooks/plagiarism/{connection_id}``)."""

    thesis_id: uuid.UUID
    similarity_pct: Decimal = Field(ge=0, le=100)
    report_url: str | None = None
    ai_generated_pct: Decimal | None = Field(default=None, ge=0, le=100)
    reference: str | None = None


class ThesisReject(_Strict):
    reason: str = Field(min_length=3, max_length=1000)


class ThesisOut(BaseModel):
    id: uuid.UUID
    scholar_id: uuid.UUID
    stage: str
    title: str | None = None
    file_url: str
    submitted_at: datetime
    similarity_pct: Decimal | None = None
    similarity_limit_pct: float | None = None
    plagiarism_report_url: str | None = None
    ai_generated_pct: Decimal | None = None
    ai_declaration: bool = False
    status: str
    flags: list[str] = Field(default_factory=list)
    workflow_instance_id: uuid.UUID | None = None
    certificate_document_id: uuid.UUID | None = None
    consolidated: str | None = None


# ---- examiners ----------------------------------------------------------------------------------------------------------
class ExaminerIn(_Strict):
    name: str = Field(min_length=1, max_length=200)
    affiliation: str = Field(min_length=1, max_length=300)
    email: EmailStr
    is_external: bool = True
    state: str | None = Field(default=None, max_length=60)
    country: str = Field(default="India", max_length=60)
    coi_declaration: bool = True


class ExaminerPanelPropose(_Strict):
    examiners: list[ExaminerIn] = Field(min_length=1, max_length=10)


class PanelDecision(_Strict):
    approve: bool
    remarks: str | None = Field(default=None, max_length=1000)


class ExaminerInvite(_Strict):
    due_days: int | None = Field(default=None, ge=7, le=180)


class ExaminerResponse(_Strict):
    accept: bool
    remarks: str | None = Field(default=None, max_length=1000)


class ExaminerReportUpload(_Strict):
    report_url: str = Field(min_length=1, max_length=1000)
    recommendation: Recommendation
    remarks: str | None = Field(default=None, max_length=8000)


class ExaminerReplace(_Strict):
    replacement: ExaminerIn


class ExaminerRemuneration(_Strict):
    amount_paise: int = Field(gt=0)
    via: Literal["payroll", "payout"] = "payout"


class ExaminerOut(BaseModel):
    id: uuid.UUID
    thesis_id: uuid.UUID
    name: str | None = None
    affiliation: str | None = None
    email: str | None = None
    is_external: bool
    state: str | None = None
    country: str | None = None
    status: str
    invited_at: datetime | None = None
    accepted_at: datetime | None = None
    report_url: str | None = None
    report_received_at: datetime | None = None
    recommendation: str | None = None
    remuneration_paise: int | None = None
    due_on: date | None = None
    replaced_by: str | None = None
    hidden: bool = False


class ExaminerTokenView(BaseModel):
    examiner_id: uuid.UUID
    name: str
    thesis_title: str | None = None
    institution: str | None = None
    status: str
    due_on: date | None = None
    download_url: str | None = None


class RecommendationsOut(BaseModel):
    thesis_id: uuid.UUID
    received: int
    total: int
    recommendations: list[str]
    consolidated: Literal["pending", "viva_eligible", "revise", "board_decision"]


# ---- viva ---------------------------------------------------------------------------------------------------------------
class VivaPanelMember(_Strict):
    name: str = Field(min_length=1, max_length=200)
    role: Literal["guide", "external_examiner", "dc_member", "chair", "observer"]
    staff_id: uuid.UUID | None = None
    examiner_id: uuid.UUID | None = None


class VivaSchedule(_Strict):
    scheduled_at: datetime
    venue_or_link: str = Field(min_length=1, max_length=300)
    panel: list[VivaPanelMember] = Field(min_length=2, max_length=12)
    open_defence: bool = True


class VivaUpdate(_Strict):
    scheduled_at: datetime | None = None
    venue_or_link: str | None = Field(default=None, max_length=300)
    panel: list[VivaPanelMember] | None = Field(default=None, min_length=2, max_length=12)


class VivaResultIn(_Strict):
    result: VivaResult
    report_url: str = Field(min_length=1, max_length=1000)
    held_at: datetime
    attendance: list[str] = Field(default_factory=list, max_length=200)


class VivaOut(BaseModel):
    id: uuid.UUID
    thesis_id: uuid.UUID
    scholar_id: uuid.UUID | None = None
    scholar_name: str | None = None
    title: str | None = None
    scheduled_at: datetime | None = None
    venue_or_link: str | None = None
    panel: list[dict[str, Any]] = Field(default_factory=list)
    held_at: datetime | None = None
    result: str | None = None
    report_url: str | None = None
    re_viva_count: int = 0
    open_defence: bool = True


class VivaNotice(BaseModel):
    scholar_name: str | None = None
    department: str | None = None
    title: str | None = None
    scheduled_at: datetime | None = None
    venue_or_link: str | None = None


# ---- award / ETD --------------------------------------------------------------------------------------------------------
class PhdAwardRequest(_Strict):
    date_of_award: date
    resolution_id: uuid.UUID | None = None


class PhdAwardOut(BaseModel):
    scholar_id: uuid.UUID
    thesis_id: uuid.UUID
    scholar_name: str | None = None
    title: str | None = None
    status: Literal["requested", "awarded", "rejected"]
    date_of_award: date | None = None
    degree_awarded_id: uuid.UUID | None = None
    certificate_document_id: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    etd_due_on: date | None = None


class EtdUploadRequest(_Strict):
    repository: EtdRepository = EtdRepository.SHODHGANGA


class EtdEmbargo(_Strict):
    months: int = Field(ge=1, le=60)
    reason: Literal["patent", "publication", "other"] = "patent"
    remarks: str | None = Field(default=None, max_length=1000)
    approve: bool | None = None


class EtdOut(BaseModel):
    id: uuid.UUID
    thesis_id: uuid.UUID
    repository: str
    handle: str | None = None
    uploaded_at: datetime | None = None
    status: str
    job_id: uuid.UUID | None = None
    due_on: date | None = None
    embargo: dict[str, Any] | None = None
    error: str | None = None


# ---- portal / stats -----------------------------------------------------------------------------------------------------
class Deadline(BaseModel):
    label: str
    due_on: date
    kind: str


class ScholarPortalDashboard(BaseModel):
    scholar: ScholarOut
    coursework: CourseworkSummary | None = None
    deadlines: list[Deadline] = Field(default_factory=list)
    duration_pct: int | None = None
    latest_report: ProgressReportOut | None = None
    open_recommendations: list[dict[str, Any]] = Field(default_factory=list)
    fellowship: FellowshipOut | None = None
    thesis: ThesisOut | None = None
    viva: VivaOut | None = None
    open_requests: int = 0


class PhdStats(BaseModel):
    by_status: dict[str, int]
    by_guide: list[dict[str, Any]]
    by_department: dict[str, int]
    avg_duration_months: float | None = None
    awarded_by_year: dict[str, int]
    gphd: int
    guide_utilisation_pct: float | None = None
    fellowship_spend_paise: int = 0
    plagiarism: dict[str, Any] = Field(default_factory=dict)
    examiner_turnaround_days: float | None = None


Scholar360.model_rebuild()
