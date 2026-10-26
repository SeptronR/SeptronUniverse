"""Accreditation & compliance (IQAC) schemas — Prompts/32 §32.4. Money in paise; metric values are decimals (``value /
numerator / denominator``) with a JSON ``breakdown``. Names that would collide with earlier phases carry an
``Accreditation`` / ``Iqac`` prefix (``AccreditationJobQueued``, ``IqacDashboardOut``, ``AuditRegisterOut``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums.accreditation import AuditStatus, AuditType, CycleStatus, ExportFormat, SubmissionType


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccreditationJobQueued(BaseModel):
    job_id: uuid.UUID


# ---- frameworks -----------------------------------------------------------------------------------------------------------
class CriterionOut(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    metric_type: str
    max_score: Decimal | None = None
    period_type: str
    metric_key: str | None = None
    custom: bool = False
    children: list["CriterionOut"] = []


class FrameworkOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    version: str | None = None
    active: bool
    feature: str | None = None
    criteria_count: int = 0
    criteria: list[CriterionOut] = []


class MetricDefinitionOut(BaseModel):
    key: str
    name: str
    unit: str | None = None
    source_module: str | None = None
    computation_key: str
    is_derived: bool = False
    depends_on: list[str] = []
    params_schema: dict[str, Any] | None = None
    frameworks_using: list[str] = []
    registered: bool = True
    kind: Literal["computed", "event_fed", "manual", "derived"] = "computed"


# ---- metrics ----------------------------------------------------------------------------------------------------------------
class MetricComputeRequest(_Strict):
    period_label: str = Field(min_length=4, max_length=20)
    framework_code: str | None = Field(default=None, max_length=30)
    metric_keys: list[str] = []
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    params: dict[str, Any] = {}


class ComputeFailure(BaseModel):
    key: str
    error: str


class ComputeSummary(BaseModel):
    period_label: str
    computed: int
    skipped: list[str] = []
    failed: list[ComputeFailure] = []
    duration_ms: int
    consistency: list[dict[str, Any]] = []


class MetricValueOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str | None = None
    unit: str | None = None
    period: str
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    value: Decimal | None = None
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    breakdown: dict[str, Any] = {}
    source: str
    computed_at: datetime | None = None
    verified: bool = False
    verified_at: datetime | None = None
    override_reason: str | None = None
    pending_override: dict[str, Any] | None = None
    stale_auto: dict[str, Any] | None = None


class DrilldownRows(BaseModel):
    key: str
    period: str
    query: str | None = None
    value: Decimal | None = None
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    rows: list[dict[str, Any]] = []
    total: int = 0


class MetricOverride(_Strict):
    period_label: str = Field(min_length=4, max_length=20)
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    value: Decimal
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    reason: str = Field(min_length=5, max_length=2000)
    evidence_ids: list[uuid.UUID] = []


class OverrideVerify(_Strict):
    period_label: str = Field(min_length=4, max_length=20)
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    action: Literal["verify", "reject", "unverify"] = "verify"
    remarks: str | None = Field(default=None, max_length=1000)


class ManualMetricInput(_Strict):
    period_label: str = Field(min_length=4, max_length=20)
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    value: Decimal
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    breakdown: dict[str, Any] | None = None


class MetricTrend(BaseModel):
    key: str
    periods: list[str]
    values: list[Decimal | None]
    sources: list[str | None] = []


# ---- evidence ---------------------------------------------------------------------------------------------------------------
class EvidenceIn(_Strict):
    framework_criterion_id: uuid.UUID | None = None
    criterion_code: str | None = Field(default=None, max_length=20)
    framework_code: str | None = Field(default=None, max_length=30)
    metric_key: str | None = Field(default=None, max_length=80)
    period_label: str | None = Field(default=None, max_length=20)
    title: str = Field(min_length=2, max_length=200)
    doc_type: str | None = Field(default=None, max_length=40)
    file_url: str = Field(min_length=3, max_length=2000)
    size_bytes: int | None = Field(default=None, ge=0)
    tags: list[str] = []


class EvidenceUpdate(_Strict):
    title: str | None = Field(default=None, max_length=200)
    doc_type: str | None = Field(default=None, max_length=40)
    period_label: str | None = Field(default=None, max_length=20)
    metric_key: str | None = Field(default=None, max_length=80)
    file_url: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None


class EvidenceOut(BaseModel):
    id: uuid.UUID
    framework_criterion_id: uuid.UUID | None = None
    criterion_code: str | None = None
    metric_key: str | None = None
    period_label: str | None = None
    title: str
    doc_type: str | None = None
    file_url: str
    uploaded_by: uuid.UUID | None = None
    uploaded_by_name: str | None = None
    verified: bool = False
    verified_at: datetime | None = None
    tags: list[str] = []
    version: int = 1
    source: dict[str, Any] | None = None
    created_at: datetime


class EvidenceVerify(_Strict):
    action: Literal["verify", "unverify"] = "verify"


class EvidenceSuggestion(BaseModel):
    id: str
    module: str
    entity: str
    entity_id: str | None = None
    title: str
    criterion_code: str | None = None
    period_label: str | None = None
    file_url: str | None = None
    status: Literal["pending", "accepted", "dismissed"] = "pending"
    created_at: str | None = None


# ---- cycles & responses -----------------------------------------------------------------------------------------------------
class CycleIn(_Strict):
    framework_id: uuid.UUID | None = None
    framework_code: str | None = Field(default=None, max_length=30)
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    name: str = Field(min_length=3, max_length=160)
    period_from: date | None = None
    period_to: date | None = None
    submission_due_on: date | None = None
    coordinator_staff_id: uuid.UUID | None = None


class CycleUpdate(_Strict):
    name: str | None = Field(default=None, max_length=160)
    period_from: date | None = None
    period_to: date | None = None
    submission_due_on: date | None = None
    coordinator_staff_id: uuid.UUID | None = None


class CycleOut(BaseModel):
    id: uuid.UUID
    framework_id: uuid.UUID
    framework_code: str | None = None
    college_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    name: str
    period_from: date | None = None
    period_to: date | None = None
    submission_due_on: date | None = None
    coordinator_staff_id: uuid.UUID | None = None
    status: CycleStatus
    score: Decimal | None = None
    grade: str | None = None
    completion_pct: float = 0
    criteria_progress: dict[str, int] = {}
    created_at: datetime


class CycleStatusChange(_Strict):
    status: CycleStatus
    score: Decimal | None = None
    grade: str | None = Field(default=None, max_length=5)
    remarks: str | None = Field(default=None, max_length=1000)


class CriterionResponseIn(_Strict):
    narrative: str | None = Field(default=None, max_length=200_000)
    metric_value_ids: list[uuid.UUID] | None = None
    evidence_ids: list[uuid.UUID] | None = None
    owner_staff_id: uuid.UUID | None = None


class CriterionResponseOut(BaseModel):
    id: uuid.UUID | None = None
    cycle_id: uuid.UUID
    criterion_id: uuid.UUID
    code: str
    title: str
    metric_type: str
    max_score: Decimal | None = None
    narrative: str | None = None
    word_count: int = 0
    word_limit: int | None = None
    metric_value_ids: list[str] = []
    metric_values: list[MetricValueOut] = []
    evidence_ids: list[str] = []
    owner_staff_id: uuid.UUID | None = None
    owner_name: str | None = None
    due_on: date | None = None
    status: str = "draft"
    reviewed_by: uuid.UUID | None = None
    last_reviewed_at: str | None = None
    review_trail: list[dict[str, Any]] = []
    updated_at: datetime | None = None


class ResponseAssign(_Strict):
    criterion_codes: list[str] = Field(min_length=1)
    owner_staff_id: uuid.UUID
    due_on: date | None = None


class ResponseReview(_Strict):
    action: Literal["approve", "reject"]
    remarks: str | None = Field(default=None, max_length=2000)


class BestPracticeIn(_Strict):
    title: str = Field(min_length=3, max_length=200)
    objectives: str | None = None
    context: str | None = None
    practice: str = Field(min_length=10)
    evidence_of_success: str | None = None
    problems: str | None = None


class DistinctivenessIn(_Strict):
    area: str = Field(min_length=3, max_length=200)
    narrative: str = Field(min_length=10)


class ResponseVersion(BaseModel):
    version: int
    at: str
    by: str | None = None
    status: str
    word_count: int
    narrative: str | None = None


class CycleExportRequest(_Strict):
    format: ExportFormat
    period_label: str | None = Field(default=None, max_length=20)


class ExportOut(BaseModel):
    id: str
    format: str
    status: str
    file_url: str | None = None
    issued_document_id: str | None = None
    created_at: str | None = None
    rows: int | None = None


# ---- submissions ------------------------------------------------------------------------------------------------------------
class SubmissionIn(_Strict):
    framework_id: uuid.UUID | None = None
    period_label: str = Field(min_length=4, max_length=20)
    submission_type: SubmissionType


class SubmissionOut(BaseModel):
    id: uuid.UUID
    framework_id: uuid.UUID | None = None
    period_label: str
    submission_type: str
    payload: dict[str, Any] | None = None
    file_url: str | None = None
    status: str
    submitted_on: date | None = None
    ack_ref: str | None = None
    supersedes_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SubmissionMarkSubmitted(_Strict):
    submitted_on: date
    ack_ref: str | None = Field(default=None, max_length=80)
    file_url: str | None = Field(default=None, max_length=2000)
    acknowledged: bool = False


class SubmissionDiff(BaseModel):
    id: uuid.UUID
    vs_id: uuid.UUID | None = None
    vs_period: str | None = None
    rows: list[dict[str, Any]] = []


# ---- audits --------------------------------------------------------------------------------------------------------------
class AuditFinding(BaseModel):
    no: int
    text: str
    owner_staff_id: uuid.UUID | None = None
    due_on: date | None = None
    status: AuditStatus = AuditStatus.OPEN
    action_taken: str | None = None


class AuditFindingIn(_Strict):
    text: str = Field(min_length=3, max_length=4000)
    owner_staff_id: uuid.UUID | None = None
    due_on: date | None = None


class AuditRegisterIn(_Strict):
    audit_type: AuditType
    period_label: str = Field(min_length=4, max_length=20)
    auditor: str | None = Field(default=None, max_length=200)
    report_url: str | None = Field(default=None, max_length=2000)
    findings: list[AuditFindingIn] = []


class AuditRegisterUpdate(_Strict):
    auditor: str | None = Field(default=None, max_length=200)
    report_url: str | None = Field(default=None, max_length=2000)
    status: AuditStatus | None = None
    add_findings: list[AuditFindingIn] = []


class AuditRegisterOut(BaseModel):
    id: uuid.UUID
    audit_type: str
    period_label: str
    auditor: str | None = None
    report_url: str | None = None
    findings: list[AuditFinding] = []
    status: str
    open_findings: int = 0
    created_at: datetime
    updated_at: datetime


class FindingUpdate(_Strict):
    status: AuditStatus | None = None
    action_taken: str | None = Field(default=None, max_length=4000)
    owner_staff_id: uuid.UUID | None = None
    due_on: date | None = None


class AuditDashboardOut(BaseModel):
    registers: int
    by_type: dict[str, int]
    findings_open: int
    findings_overdue: int
    findings_closed: int


# ---- consistency / disclosures / dashboard -----------------------------------------------------------------------------------
class ConsistencyCheck(BaseModel):
    name: str
    status: Literal["pass", "fail", "skip"]
    details: dict[str, Any] = {}
    fix_link: str | None = None


class ConsistencyCheckOut(BaseModel):
    period_label: str
    checked_at: str | None = None
    checks: list[ConsistencyCheck] = []


class DisclosureItem(BaseModel):
    key: str
    title: str
    metric_key: str | None = None
    value: Decimal | None = None
    unit: str | None = None
    period_label: str | None = None
    evidence_url: str | None = None


class DisclosureFeedOut(BaseModel):
    refreshed_at: str | None = None
    period_label: str | None = None
    items: list[DisclosureItem] = []


class IqacDashboardOut(BaseModel):
    period_label: str
    cycles: list[CycleOut] = []
    criteria_completion: dict[str, float] = {}
    metrics_total: int = 0
    metrics_verified_pct: float = 0
    overrides_pending: int = 0
    evidence_counts: dict[str, int] = {}
    submissions_due: list[dict[str, Any]] = []
    audits_open: int = 0
    consistency_alerts: int = 0
    score_simulation: dict[str, Any] = {}
    top_gaps: list[dict[str, Any]] = []
