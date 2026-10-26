"""Affiliation schemas — Prompts/34 §34.4: college registry profile, applications (checklist, fees, scrutiny,
inspection, deficiencies, decision / order), programme approvals, fee schedules and dues, college data submissions
(windows, validation, review actions), exam centres (allocation, dashboards), college dashboard, university portfolio,
statutory returns and the public list. Money in paise."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums.affiliation import (
    ApplicationStatus,
    ApplicationType,
    ApprovalStatus,
    FeeType,
    PerUnit,
    SubmissionStatus,
    SubmissionType,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AffiliationJobQueued(BaseModel):
    job_id: uuid.UUID


class DocumentRef(BaseModel):
    issued_document_id: uuid.UUID | None = None
    document_number: str | None = None
    url: str | None = None


# ---- college registry --------------------------------------------------------------------------------------------------
class VaultDocument(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=200)
    file_url: str = Field(min_length=1, max_length=1000)
    issued_by: str | None = Field(default=None, max_length=160)
    valid_to: date | None = None
    uploaded_at: datetime | None = None
    expired: bool = False


class ApprovalsSummary(BaseModel):
    programmes: int = 0
    sanctioned_intake: int = 0
    lateral_intake: int = 0
    expiring: int = 0
    withdrawn: int = 0


class ComplianceFlags(BaseModel):
    approvals_valid: bool = True
    dues_clear: bool = True
    submissions_on_time_pct: float | None = None
    deficiencies_open: int = 0
    documents_expired: int = 0
    score: int = 100


class CollegeAffiliationProfile(BaseModel):
    college_id: uuid.UUID
    code: str
    name: str
    college_type: str
    affiliation_number: str | None = None
    affiliated_since: date | None = None
    principal_staff_id: uuid.UUID | None = None
    principal_name: str | None = None
    aishe_code: str | None = None
    aicte_pid: str | None = None
    is_exam_centre: bool = False
    exam_centre_code: str | None = None
    is_active: bool = True
    last_inspection_on: date | None = None
    documents: list[VaultDocument] = Field(default_factory=list)
    approvals: ApprovalsSummary = Field(default_factory=ApprovalsSummary)
    compliance: ComplianceFlags = Field(default_factory=ComplianceFlags)


class CollegeProfileUpdate(_Strict):
    """Affiliation office edits every field; a college admin only ``principal_staff_id`` / ``aishe_code`` /
    ``aicte_pid`` (other fields → 403)."""

    college_type: Literal["constituent", "affiliated", "autonomous", "campus", "study_centre"] | None = None
    affiliation_number: str | None = Field(default=None, max_length=40)
    affiliated_since: date | None = None
    principal_staff_id: uuid.UUID | None = None
    aishe_code: str | None = Field(default=None, max_length=20)
    aicte_pid: str | None = Field(default=None, max_length=30)
    is_exam_centre: bool | None = None
    exam_centre_code: str | None = Field(default=None, max_length=20)
    effective_year_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class CollegeRow(BaseModel):
    college_id: uuid.UUID
    code: str
    name: str
    college_type: str
    affiliation_number: str | None = None
    affiliated_since: date | None = None
    is_exam_centre: bool = False
    programmes: int = 0
    sanctioned_intake: int = 0
    open_applications: int = 0
    dues_paise: int = 0
    compliance_score: int = 100


# ---- applications ------------------------------------------------------------------------------------------------------
class NewProgram(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=2, max_length=200)
    level: str = Field("ug", max_length=20)
    degree_name: str | None = Field(default=None, max_length=80)
    duration_years: float = Field(4, gt=0, le=8)
    total_terms: int = Field(8, ge=1, le=16)
    department_id: uuid.UUID | None = None
    intake: int | None = Field(default=None, ge=1, le=5000)


class ApplicationProgram(BaseModel):
    program_id: uuid.UUID | None = None
    new: NewProgram | None = None
    requested_intake: int | None = Field(default=None, ge=0, le=5000)
    lateral_intake: int = Field(0, ge=0, le=1000)
    current_intake: int | None = None
    program_code: str | None = None
    program_name: str | None = None


class ApplicationCreate(_Strict):
    college_id: uuid.UUID
    academic_year_id: uuid.UUID
    application_type: ApplicationType
    programs: list[ApplicationProgram] = Field(default_factory=list, max_length=60)
    documents: dict[str, str] = Field(default_factory=dict)
    remarks: str | None = Field(default=None, max_length=4000)
    reference_application_id: uuid.UUID | None = None


class ApplicationUpdate(_Strict):
    programs: list[ApplicationProgram] | None = Field(default=None, max_length=60)
    documents: dict[str, str] | None = None
    remarks: str | None = Field(default=None, max_length=4000)


class ApplicationAction(_Strict):
    action: Literal["submit", "withdraw"]
    remarks: str | None = Field(default=None, max_length=2000)


class ChecklistItem(BaseModel):
    key: str
    label: str
    file_url: str | None = None
    provided: bool = False


class Checklist(BaseModel):
    application_type: str
    items: list[ChecklistItem]
    complete: bool
    missing: list[str] = Field(default_factory=list)


class FeeLine(BaseModel):
    fee_type: str
    per_unit: str
    units: int
    rate_paise: int
    amount_paise: int
    label: str


class FeeComputePreview(BaseModel):
    application_id: uuid.UUID
    lines: list[FeeLine]
    total_paise: int
    inspection_required: bool


class Deficiency(BaseModel):
    id: str
    area: str
    observation: str
    severity: Literal["minor", "major", "critical"] = "minor"
    status: Literal["open", "responded", "closed"] = "open"
    due_on: date | None = None
    response_text: str | None = None
    evidence_url: str | None = None
    responded_at: datetime | None = None
    closed_by: uuid.UUID | None = None
    closed_at: datetime | None = None
    round: int = 1


class InspectionOut(BaseModel):
    committee: dict[str, Any] | None = None
    inspection_on: date | None = None
    mode: str | None = None
    report_url: str | None = None
    recommendation: str | None = None
    rounds: int = 0
    required: bool = True


class DecisionOut(BaseModel):
    decision: str
    conditions: list[str] = Field(default_factory=list)
    resolution_id: uuid.UUID | None = None
    resolution_number: str | None = None
    order_no: str | None = None
    order_date: date | None = None
    order_url: str | None = None
    issued_document_id: uuid.UUID | None = None
    decided_by: uuid.UUID | None = None


class ApplicationOut(BaseModel):
    id: uuid.UUID
    number: str | None = None
    college_id: uuid.UUID
    college_code: str | None = None
    college_name: str | None = None
    academic_year_id: uuid.UUID
    academic_year: str | None = None
    application_type: str
    status: ApplicationStatus | str
    programs: list[ApplicationProgram] = Field(default_factory=list)
    documents: dict[str, str] = Field(default_factory=dict)
    remarks: str | None = None
    checklist_complete: bool = False
    missing_documents: list[str] = Field(default_factory=list)
    fee_invoice_id: uuid.UUID | None = None
    fee_status: str | None = None
    fee_total_paise: int | None = None
    workflow_instance_id: uuid.UUID | None = None
    workflow_state: str | None = None
    inspection: InspectionOut | None = None
    deficiencies: list[Deficiency] = Field(default_factory=list)
    decision: DecisionOut | None = None
    order_no: str | None = None
    order_url: str | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScrutinyDecision(_Strict):
    action: Literal["proceed", "return"]
    remarks: str | None = Field(default=None, max_length=4000)
    missing_documents: list[str] = Field(default_factory=list)


class ExternalExpert(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    designation: str | None = Field(default=None, max_length=160)
    organisation: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)


class InspectionCommittee(BaseModel):
    staff_ids: list[uuid.UUID] = Field(default_factory=list, max_length=12)
    external: list[ExternalExpert] = Field(default_factory=list, max_length=8)
    committee_id: uuid.UUID | None = None
    convenor_staff_id: uuid.UUID | None = None


class InspectionSchedule(_Strict):
    committee: InspectionCommittee
    inspection_on: date
    mode: Literal["physical", "virtual", "hybrid"] = "physical"


class Finding(BaseModel):
    area: str = Field(min_length=2, max_length=120)
    observation: str = Field(min_length=2, max_length=2000)
    is_deficiency: bool = False
    severity: Literal["minor", "major", "critical"] = "minor"


class InspectionReportIn(_Strict):
    report_url: str = Field(min_length=1, max_length=1000)
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    recommendation: Literal["approve", "conditional", "reject", "reinspect"] = "approve"


class DeficiencyResponse(_Strict):
    response_text: str = Field(min_length=2, max_length=4000)
    evidence_url: str | None = Field(default=None, max_length=1000)


class DeficiencyClose(_Strict):
    remarks: str | None = Field(default=None, max_length=2000)
    accept: bool = True


class ReinspectRequest(_Strict):
    inspection_on: date | None = None
    remarks: str | None = Field(default=None, max_length=2000)


class DecisionProgram(BaseModel):
    program_id: uuid.UUID | None = None
    new_code: str | None = Field(default=None, max_length=30)
    sanctioned_intake: int = Field(ge=0, le=5000)
    lateral_intake: int = Field(0, ge=0, le=1000)
    approval_status: ApprovalStatus = ApprovalStatus.PROVISIONAL
    valid_from: date | None = None
    valid_to: date | None = None


class DecisionIn(_Strict):
    decision: Literal["approved", "conditional", "rejected"]
    conditions: list[str] = Field(default_factory=list, max_length=30)
    programs: list[DecisionProgram] = Field(default_factory=list, max_length=60)
    resolution_id: uuid.UUID | None = None
    order_date: date | None = None
    remarks: str | None = Field(default=None, max_length=4000)


class InspectionRow(BaseModel):
    application_id: uuid.UUID
    number: str | None = None
    college_id: uuid.UUID
    college_name: str | None = None
    application_type: str
    status: str
    inspection_on: date | None = None
    mode: str | None = None
    committee: dict[str, Any] | None = None
    report_submitted: bool = False
    open_deficiencies: int = 0


# ---- programme approvals -----------------------------------------------------------------------------------------------
class ProgramApprovalOut(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID
    college_code: str | None = None
    program_id: uuid.UUID
    program_code: str | None = None
    program_name: str | None = None
    academic_year_id: uuid.UUID
    academic_year: str | None = None
    sanctioned_intake: int
    lateral_intake: int
    approval_status: str
    order_no: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    conditions: dict[str, Any] | None = None
    validity: Literal["valid", "expiring", "expired", "withdrawn"] = "valid"
    admitted: int = 0


class ProgramApprovalUpdate(_Strict):
    approval_status: ApprovalStatus | None = None
    sanctioned_intake: int | None = Field(default=None, ge=0, le=5000)
    lateral_intake: int | None = Field(default=None, ge=0, le=1000)
    conditions: list[str] | None = Field(default=None, max_length=30)
    valid_to: date | None = None
    reason: str = Field(min_length=3, max_length=2000)


class ProgramApprovalCheck(BaseModel):
    college_id: uuid.UUID
    program_id: uuid.UUID
    academic_year_id: uuid.UUID | None = None
    approved: bool
    closed: bool = False
    approval_status: str | None = None
    sanctioned_intake: int | None = None
    lateral_intake: int | None = None
    total_intake: int | None = None
    valid_to: date | None = None
    reason: str | None = None


class CarryForwardIn(_Strict):
    academic_year_id: uuid.UUID


class CarryForwardOut(BaseModel):
    academic_year_id: uuid.UUID
    created: int
    skipped: int


# ---- fee schedules / dues ----------------------------------------------------------------------------------------------
class FeeScheduleIn(_Strict):
    academic_year_id: uuid.UUID
    fee_type: FeeType
    amount_paise: int = Field(ge=0)
    per_unit: PerUnit = PerUnit.FLAT


class FeeScheduleUpdate(_Strict):
    amount_paise: int | None = Field(default=None, ge=0)
    per_unit: PerUnit | None = None


class FeeScheduleOut(BaseModel):
    id: uuid.UUID
    academic_year_id: uuid.UUID
    academic_year: str | None = None
    fee_type: str
    amount_paise: int
    per_unit: str


class DuesRow(BaseModel):
    college_id: uuid.UUID
    college_code: str | None = None
    college_name: str | None = None
    invoices: int = 0
    billed_paise: int = 0
    paid_paise: int = 0
    outstanding_paise: int = 0
    overdue_paise: int = 0
    exam_processing_estimate_paise: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)


# ---- data submissions --------------------------------------------------------------------------------------------------
class SubmissionCreate(_Strict):
    college_id: uuid.UUID
    term_id: uuid.UUID
    submission_type: SubmissionType
    exam_session_id: uuid.UUID | None = None
    file_url: str | None = Field(default=None, max_length=1000)


class SubmissionImport(_Strict):
    file_url: str = Field(min_length=1, max_length=1000)
    mapping: dict[str, str] = Field(default_factory=dict)


class ValidationIssue(BaseModel):
    code: str
    message: str
    row: int | None = None
    ref: str | None = None


class ValidationReport(BaseModel):
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    validated_at: datetime | None = None


class SubmissionAction(_Strict):
    action: Literal["submit", "verify", "return", "accept", "lock", "unlock"]
    remarks: str | None = Field(default=None, max_length=4000)


class SubmissionOut(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID
    college_code: str | None = None
    college_name: str | None = None
    term_id: uuid.UUID
    exam_session_id: uuid.UUID | None = None
    submission_type: str
    status: SubmissionStatus | str
    version: int = 1
    source: Literal["system", "file"] = "system"
    record_count: int | None = None
    file_url: str | None = None
    submitted_by: uuid.UUID | None = None
    submitted_at: datetime | None = None
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    remarks: str | None = None
    locked_at: datetime | None = None
    due_on: date | None = None
    late: bool = False
    validation: ValidationReport | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    versions: list[dict[str, Any]] = Field(default_factory=list)


class SubmissionWindowOut(BaseModel):
    submission_type: str
    applies: bool = True
    opens_on: date | None = None
    due_on: date | None = None
    status: Literal["upcoming", "open", "due", "overdue", "closed"] = "open"
    submission_id: uuid.UUID | None = None
    submission_status: str | None = None
    exam_related: bool = False


class ComplianceRow(BaseModel):
    college_id: uuid.UUID
    college_code: str | None = None
    college_name: str | None = None
    by_type: dict[str, str] = Field(default_factory=dict)
    on_time_pct: float | None = None
    returns: int = 0
    accepted: int = 0
    pending: int = 0


class CollegeGatingStatus(BaseModel):
    college_id: uuid.UUID
    college_code: str | None = None
    college_name: str | None = None
    status: Literal["ready", "gated", "not_applicable"]
    missing: list[str] = Field(default_factory=list)
    by_type: dict[str, str] = Field(default_factory=dict)
    registrations: int = 0


# ---- exam centres ------------------------------------------------------------------------------------------------------
class ExamCentreIn(_Strict):
    exam_session_id: uuid.UUID | None = None
    college_id: uuid.UUID
    centre_code: str = Field(min_length=1, max_length=20)
    chief_superintendent_staff_id: uuid.UUID | None = None
    capacity: int | None = Field(default=None, ge=1, le=30000)
    assigned_colleges: list[uuid.UUID] = Field(default_factory=list)


class ExamCentreOut(BaseModel):
    id: uuid.UUID
    exam_session_id: uuid.UUID
    college_id: uuid.UUID
    college_code: str | None = None
    college_name: str | None = None
    centre_code: str
    chief_superintendent_staff_id: uuid.UUID | None = None
    chief_superintendent_name: str | None = None
    capacity: int | None = None
    effective_capacity: int | None = None
    assigned_colleges: list[str] = Field(default_factory=list)
    registrations_routed: int = 0
    seating_status: str | None = None
    bundles: dict[str, int] = Field(default_factory=dict)
    appointment_document_id: uuid.UUID | None = None


class CentreAllocationRun(_Strict):
    exam_session_id: uuid.UUID
    strategy: Literal["nearest", "capacity", "manual"] = "nearest"
    manual: dict[str, list[uuid.UUID]] = Field(default_factory=dict)


class AllocationSummary(BaseModel):
    exam_session_id: uuid.UUID
    strategy: str
    centres: int
    colleges_assigned: int
    unassigned: list[str] = Field(default_factory=list)
    over_capacity: list[str] = Field(default_factory=list)


class CentreDashboard(BaseModel):
    centre: ExamCentreOut
    registrations_by_college: dict[str, int] = Field(default_factory=dict)
    seating_allocated: int = 0
    attendance_marked: int = 0
    bundles: dict[str, int] = Field(default_factory=dict)


# ---- dashboards / portfolio / returns ----------------------------------------------------------------------------------
class CollegeDashboard(BaseModel):
    profile: CollegeAffiliationProfile
    approvals: list[ProgramApprovalOut] = Field(default_factory=list)
    applications: list[ApplicationOut] = Field(default_factory=list)
    dues: DuesRow | None = None
    submissions_by_term: dict[str, dict[str, str]] = Field(default_factory=dict)
    results_release: list[dict[str, Any]] = Field(default_factory=list)
    inspections: list[InspectionRow] = Field(default_factory=list)
    compliance_score: int = 100


class UniversityPortfolio(BaseModel):
    colleges_by_type: dict[str, int] = Field(default_factory=dict)
    applications_by_status: dict[str, int] = Field(default_factory=dict)
    applications_by_type: dict[str, int] = Field(default_factory=dict)
    inspections_due: int = 0
    deficiencies_open: int = 0
    dues_outstanding_paise: int = 0
    dues_by_college: list[DuesRow] = Field(default_factory=list)
    submissions_compliance_pct: float | None = None
    results_gating: list[dict[str, Any]] = Field(default_factory=list)
    expiring_approvals: int = 0
    sanctioned_intake: int = 0


class PublicCollege(BaseModel):
    code: str
    name: str
    college_type: str
    affiliation_number: str | None = None
    affiliated_since: date | None = None
    programmes: list[dict[str, Any]] = Field(default_factory=list)


class AffiliationReturn(BaseModel):
    kind: str
    year: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
