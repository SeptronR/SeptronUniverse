"""Research & faculty development schemas — Prompts/30 §30.4. Money in paise; OpenAPI names that would collide with
earlier phases carry an ``Rsch`` prefix (``RschProjectIn``, ``RschVerifyRequest``)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums.research import (
    AwardLevel,
    CollaborationType,
    EthicsCategory,
    EthicsDecision,
    EthicsType,
    FdpEventType,
    FdpRole,
    IncentiveType,
    Indexing,
    MouType,
    PartnerType,
    PatentStatus,
    PubType,
    StartupStage,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RschJobQueued(BaseModel):
    job_id: uuid.UUID


# ---- publications -------------------------------------------------------------------------------------------------------
class AuthorTag(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    staff_id: uuid.UUID | None = None
    scholar_id: uuid.UUID | None = None
    is_corresponding: bool = False


class PublicationIn(_Strict):
    pub_type: PubType = PubType.JOURNAL
    title: str = Field(min_length=3, max_length=500)
    venue: str | None = Field(None, max_length=300)
    year: int | None = Field(None, ge=1950, le=2100)
    doi: str | None = Field(None, max_length=120)
    issn_isbn: str | None = Field(None, max_length=30)
    indexing: Indexing = Indexing.NONE
    impact_factor: Decimal | None = Field(None, ge=0, le=999)
    authors: list[AuthorTag] = Field(default_factory=list, max_length=100)
    author_position: int | None = Field(None, ge=1, le=100)
    citations: int | None = Field(None, ge=0)
    evidence_url: str | None = None
    staff_id: uuid.UUID | None = Field(None, description="Research cell records for another faculty member")
    scholar_id: uuid.UUID | None = None


class PublicationUpdate(_Strict):
    pub_type: PubType | None = None
    title: str | None = Field(None, min_length=3, max_length=500)
    venue: str | None = Field(None, max_length=300)
    year: int | None = Field(None, ge=1950, le=2100)
    doi: str | None = Field(None, max_length=120)
    issn_isbn: str | None = Field(None, max_length=30)
    indexing: Indexing | None = None
    impact_factor: Decimal | None = Field(None, ge=0, le=999)
    authors: list[AuthorTag] | None = None
    author_position: int | None = Field(None, ge=1, le=100)
    citations: int | None = Field(None, ge=0)
    evidence_url: str | None = None


class PublicationOut(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID | None = None
    staff_name: str | None = None
    department_id: uuid.UUID | None = None
    scholar_id: uuid.UUID | None = None
    pub_type: str
    title: str
    venue: str | None = None
    year: int | None = None
    doi: str | None = None
    issn_isbn: str | None = None
    indexing: str | None = None
    impact_factor: Decimal | None = None
    authors: list[dict[str, Any]] = Field(default_factory=list)
    author_position: int | None = None
    citations: int | None = None
    evidence_url: str | None = None
    is_verified: bool = False
    verification_level: Literal["none", "department", "final", "rejected"] = "none"
    remarks: str | None = None
    source: str | None = None
    is_mine: bool = False
    can_edit: bool = False
    duplicates: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime | None = None


class PublicationImport(_Strict):
    source: Literal["crossref", "scopus", "orcid", "bibtex", "csv"]
    identifier: str | None = Field(None, max_length=200, description="DOI / ORCID iD / Scopus author id")
    file_url: str | None = None
    content: str | None = Field(None, max_length=2_000_000, description="BibTeX / CSV text (instead of file_url)")
    staff_id: uuid.UUID | None = None


class ImportCandidate(BaseModel):
    key: str
    title: str
    venue: str | None = None
    year: int | None = None
    doi: str | None = None
    indexing: str | None = None
    impact_factor: Decimal | None = None
    pub_type: str = "journal"
    authors: list[dict[str, Any]] = Field(default_factory=list)
    citations: int | None = None
    existing_id: uuid.UUID | None = None
    similarity: float | None = None


class ImportPreview(BaseModel):
    token: str
    source: str
    matches: list[ImportCandidate] = Field(default_factory=list)
    duplicates: list[ImportCandidate] = Field(default_factory=list)
    new: list[ImportCandidate] = Field(default_factory=list)


class ImportApply(_Strict):
    token: str = Field(min_length=8, max_length=64)
    keys: list[str] | None = Field(None, description="Subset of the new / match keys to apply (default: every new row)")
    claim_matches: bool = True


class ImportResult(BaseModel):
    created: int = 0
    claimed: int = 0
    skipped: int = 0


class RschVerifyRequest(_Strict):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    approve: bool = True
    remarks: str | None = Field(None, max_length=1000)


class RschVerifyResult(BaseModel):
    verified: int = 0
    department_level: int = 0
    rejected: int = 0
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class ClaimCoauthor(_Strict):
    author_position: int | None = Field(None, ge=1, le=100)
    is_corresponding: bool = False


# ---- patents ------------------------------------------------------------------------------------------------------------
class PatentIn(_Strict):
    title: str = Field(min_length=3, max_length=500)
    application_no: str | None = Field(None, max_length=60)
    country: str | None = Field("India", max_length=60)
    filed_on: date | None = None
    published_on: date | None = None
    granted_on: date | None = None
    status: PatentStatus = PatentStatus.FILED
    co_inventors: list[AuthorTag] = Field(default_factory=list)
    evidence_url: str | None = None
    staff_id: uuid.UUID | None = None


class PatentUpdate(_Strict):
    title: str | None = Field(None, min_length=3, max_length=500)
    application_no: str | None = Field(None, max_length=60)
    country: str | None = Field(None, max_length=60)
    filed_on: date | None = None
    published_on: date | None = None
    granted_on: date | None = None
    status: PatentStatus | None = None
    co_inventors: list[AuthorTag] | None = None
    evidence_url: str | None = None


class PatentOut(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID | None = None
    staff_name: str | None = None
    title: str
    application_no: str | None = None
    country: str | None = None
    filed_on: date | None = None
    published_on: date | None = None
    granted_on: date | None = None
    status: str
    co_inventors: list[dict[str, Any]] = Field(default_factory=list)
    evidence_url: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


# ---- projects -----------------------------------------------------------------------------------------------------------
class BudgetHeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    allocated_paise: int = Field(ge=0)


class CoPi(BaseModel):
    staff_id: uuid.UUID | None = None
    name: str | None = Field(None, max_length=200)
    institution: str | None = Field(None, max_length=200)


class RschProjectIn(_Strict):
    title: str = Field(min_length=3, max_length=500)
    pi_staff_id: uuid.UUID | None = Field(None, description="Defaults to the caller")
    co_pi: list[CoPi] = Field(default_factory=list)
    funding_agency: str = Field(min_length=2, max_length=200)
    scheme: str | None = Field(None, max_length=160)
    sanctioned_paise: int | None = Field(None, ge=0, description="Requested amount while applied")
    start_on: date | None = None
    end_on: date | None = None
    budget_heads: list[BudgetHeadIn] = Field(default_factory=list, max_length=20)
    ethics_approval_id: uuid.UUID | None = None
    ethics_category: str | None = Field(None, max_length=40, description="clinical / animal / biosafety / none …")
    sanction_letter_url: str | None = None
    report_periodicity_months: int = Field(6, ge=1, le=24)


class RschProjectUpdate(_Strict):
    title: str | None = Field(None, min_length=3, max_length=500)
    co_pi: list[CoPi] | None = None
    scheme: str | None = Field(None, max_length=160)
    start_on: date | None = None
    end_on: date | None = None
    budget_heads: list[BudgetHeadIn] | None = None
    ethics_approval_id: uuid.UUID | None = None
    ethics_category: str | None = Field(None, max_length=40)
    sanction_letter_url: str | None = None


class ProjectAction(_Strict):
    action: Literal["submit", "sanction", "start", "complete", "close"]
    sanctioned_paise: int | None = Field(None, gt=0)
    budget_heads: list[BudgetHeadIn] | None = None
    sanction_letter_url: str | None = None
    start_on: date | None = None
    end_on: date | None = None
    remarks: str | None = Field(None, max_length=1000)
    final_report_url: str | None = None


class ProjectExpenseRequest(_Strict):
    head: str = Field(min_length=2, max_length=60)
    amount_paise: int = Field(gt=0)
    description: str = Field(min_length=2, max_length=255)
    via: Literal["indent", "direct"] = "direct"
    spent_on: date | None = None
    payee: str | None = Field(None, max_length=200)
    attachments: list[str] = Field(default_factory=list, max_length=10)
    qty: float = Field(1, gt=0)


class ProjectReport(_Strict):
    period: str = Field(min_length=2, max_length=40)
    report_url: str | None = None
    summary: str | None = Field(None, max_length=4000)


class ProjectStaffIn(_Strict):
    name: str = Field(min_length=2, max_length=200)
    role: str = Field("JRF", max_length=40)
    staff_id: uuid.UUID | None = None
    scholar_id: uuid.UUID | None = None
    monthly_paise: int | None = Field(None, ge=0)
    from_on: date | None = None
    to_on: date | None = None


class RschProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    pi_staff_id: uuid.UUID
    pi_name: str | None = None
    department_id: uuid.UUID | None = None
    co_pi: list[dict[str, Any]] = Field(default_factory=list)
    funding_agency: str | None = None
    scheme: str | None = None
    sanctioned_paise: int | None = None
    received_paise: int = 0
    utilised_paise: int = 0
    utilisation_pct: float = 0.0
    start_on: date | None = None
    end_on: date | None = None
    status: str
    budget_heads: list[dict[str, Any]] = Field(default_factory=list)
    ethics_approval_id: uuid.UUID | None = None
    grant_ledger_id: uuid.UUID | None = None
    sanction_letter_url: str | None = None
    sanction_document_id: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    reports: list[dict[str, Any]] = Field(default_factory=list)
    reports_due: list[dict[str, Any]] = Field(default_factory=list)
    staff: list[dict[str, Any]] = Field(default_factory=list)
    expense_requests: list[dict[str, Any]] = Field(default_factory=list)
    is_pi: bool = False


class ProjectLedgerOut(BaseModel):
    project_id: uuid.UUID
    grant_ledger_id: uuid.UUID | None = None
    sanctioned_paise: int = 0
    received_paise: int = 0
    utilised_paise: int = 0
    balance_paise: int = 0
    heads: list[dict[str, Any]] = Field(default_factory=list)


# ---- consultancy --------------------------------------------------------------------------------------------------------
class ConsultancyIn(_Strict):
    client: str = Field(min_length=2, max_length=200)
    title: str | None = Field(None, max_length=300)
    amount_paise: int = Field(gt=0)
    institution_share_paise: int | None = Field(None, ge=0, description="Override (research cell / approval)")
    start_on: date | None = None
    end_on: date | None = None
    agreement_url: str | None = None
    client_gstin: str | None = Field(None, max_length=20)
    staff_id: uuid.UUID | None = None


class ConsultancyUpdate(_Strict):
    client: str | None = Field(None, min_length=2, max_length=200)
    title: str | None = Field(None, max_length=300)
    amount_paise: int | None = Field(None, gt=0)
    institution_share_paise: int | None = Field(None, ge=0)
    start_on: date | None = None
    end_on: date | None = None
    agreement_url: str | None = None
    status: Literal["ongoing", "completed", "cancelled"] | None = None


class ConsultancyReceipt(_Strict):
    amount_paise: int = Field(gt=0)
    mode: Literal["online", "bank_transfer", "cheque", "upi", "cash"] = "bank_transfer"
    reference: str | None = Field(None, max_length=80)


class ConsultancyOut(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    client: str
    title: str | None = None
    amount_paise: int | None = None
    institution_share_paise: int | None = None
    faculty_share_paise: int | None = None
    share_overridden: bool = False
    received_paise: int = 0
    start_on: date | None = None
    end_on: date | None = None
    status: str
    agreement_url: str | None = None
    receipts: list[dict[str, Any]] = Field(default_factory=list)


class ConsultancyShares(BaseModel):
    consultancy_id: uuid.UUID
    amount_paise: int
    institution_pct: float
    institution_share_paise: int
    faculty_share_paise: int
    received_paise: int
    institution_received_paise: int
    faculty_paid_paise: int


# ---- ethics -------------------------------------------------------------------------------------------------------------
class EthicsMember(BaseModel):
    staff_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=200)
    role: str = Field("member", max_length=40)


class EthicsCommitteeIn(_Strict):
    committee_type: EthicsType
    committee_id: uuid.UUID | None = Field(
        None, description="Phase 33 committee (stub) the ethics committee is bound to"
    )
    name: str | None = Field(None, max_length=160)
    registration_no: str | None = Field(None, max_length=60)
    members: list[EthicsMember] = Field(default_factory=list, max_length=40)
    is_active: bool = True


class EthicsCommitteeOut(BaseModel):
    id: uuid.UUID
    committee_type: str
    committee_id: uuid.UUID | None = None
    registration_no: str | None = None
    members: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool
    applications: int = 0


class EthicsApplication(_Strict):
    committee_id: uuid.UUID
    project_title: str = Field(min_length=3, max_length=500)
    pi_staff_id: uuid.UUID | None = None
    protocol_url: str | None = None
    category: EthicsCategory = EthicsCategory.EXPEDITED
    project_id: uuid.UUID | None = None
    reviewer_staff_id: uuid.UUID | None = None
    scholar_id: uuid.UUID | None = None  # Phase 31: PhD work of a research scholar


class EthicsReview(_Strict):
    decision: EthicsDecision
    approval_no: str | None = Field(None, max_length=60)
    valid_to: date | None = None
    conditions: str | None = Field(None, max_length=4000)
    comments: str | None = Field(None, max_length=4000)


class EthicsAmend(_Strict):
    kind: Literal["amend", "renew", "adverse-event"]
    description: str = Field(min_length=3, max_length=4000)
    valid_to: date | None = None
    document_url: str | None = None


class EthicsApplicationOut(BaseModel):
    id: uuid.UUID
    ethics_committee_id: uuid.UUID
    committee_type: str | None = None
    project_title: str
    pi_staff_id: uuid.UUID | None = None
    pi_name: str | None = None
    submitted_on: date | None = None
    category: str | None = None
    scholar_id: uuid.UUID | None = None
    decision: str | None = None
    status: str = "under_review"
    approval_no: str | None = None
    valid_to: date | None = None
    is_valid: bool = False
    document_url: str | None = None
    conditions: str | None = None
    reviews: list[dict[str, Any]] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    workflow_instance_id: uuid.UUID | None = None


# ---- incentives ---------------------------------------------------------------------------------------------------------
class LinkedEntity(BaseModel):
    type: Literal["publication", "patent", "conference", "proposal", "project"]
    id: uuid.UUID | None = None
    title: str | None = Field(None, max_length=300)


class IncentiveRequest(_Strict):
    incentive_type: IncentiveType
    linked_entity: LinkedEntity | None = None
    amount_paise: int | None = Field(None, gt=0, description="Required for seed / travel / patent support")
    justification: str | None = Field(None, max_length=4000)
    attachments: list[str] = Field(default_factory=list, max_length=10)


class IncentiveDecision(_Strict):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(None, max_length=1000)
    amount_paise: int | None = Field(None, gt=0, description="Approved amount (research cell may reduce)")


class IncentiveDisburse(_Strict):
    via: Literal["payroll", "grant_expense"] = "payroll"
    reference: str | None = Field(None, max_length=80)


class IncentiveOut(BaseModel):
    id: uuid.UUID
    incentive_type: str
    staff_id: uuid.UUID
    staff_name: str | None = None
    amount_paise: int
    eligible_paise: int | None = None
    justification: str | None = None
    linked_entity: dict[str, Any] | None = None
    status: str
    workflow_instance_id: uuid.UUID | None = None
    workflow_status: str | None = None
    current_step: int | None = None
    can_act: bool = False
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None


class IncentiveSlabs(BaseModel):
    slabs: list[dict[str, Any]]
    seed_grant_max_paise: int
    travel_grant_max_paise: int
    annual_cap_paise: int
    dean_threshold_paise: int


# ---- FDP / awards -------------------------------------------------------------------------------------------------------
class FdpIn(_Strict):
    event_type: FdpEventType = FdpEventType.FDP
    title: str = Field(min_length=3, max_length=300)
    organiser: str | None = Field(None, max_length=200)
    from_on: date | None = None
    to_on: date | None = None
    role: FdpRole = FdpRole.ATTENDED
    hours: Decimal | None = Field(None, ge=0, le=9999)
    certificate_url: str | None = None
    event_id: uuid.UUID | None = None
    staff_id: uuid.UUID | None = None


class FdpUpdate(_Strict):
    event_type: FdpEventType | None = None
    title: str | None = Field(None, min_length=3, max_length=300)
    organiser: str | None = Field(None, max_length=200)
    from_on: date | None = None
    to_on: date | None = None
    role: FdpRole | None = None
    hours: Decimal | None = Field(None, ge=0, le=9999)
    certificate_url: str | None = None


class FdpOut(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    event_type: str
    title: str
    organiser: str | None = None
    from_on: date | None = None
    to_on: date | None = None
    role: str
    hours: Decimal | None = None
    certificate_url: str | None = None
    event_id: uuid.UUID | None = None
    auto_created: bool = False


class FdpComplianceRow(BaseModel):
    staff_id: uuid.UUID
    name: str
    department_id: uuid.UUID | None = None
    hours: float
    target: int
    records: int
    compliant: bool


class AwardIn(_Strict):
    title: str = Field(min_length=3, max_length=300)
    agency: str | None = Field(None, max_length=200)
    year: int | None = Field(None, ge=1950, le=2100)
    level: AwardLevel = AwardLevel.NATIONAL
    evidence_url: str | None = None
    staff_id: uuid.UUID | None = None


class AwardOut(BaseModel):
    id: uuid.UUID
    staff_id: uuid.UUID
    staff_name: str | None = None
    title: str
    agency: str | None = None
    year: int | None = None
    level: str | None = None
    evidence_url: str | None = None
    is_verified: bool = False


# ---- MoUs / collaborations / start-ups ---------------------------------------------------------------------------------------
class MouIn(_Strict):
    partner: str = Field(min_length=2, max_length=200)
    partner_type: PartnerType
    country: str | None = Field("India", max_length=60)
    mou_type: MouType
    signed_on: date | None = None
    valid_to: date | None = None
    activities: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    document_url: str | None = None
    coordinator_staff_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = Field(None, description="Phase 28 company (industry partners)")


class MouUpdate(_Strict):
    partner: str | None = Field(None, min_length=2, max_length=200)
    country: str | None = Field(None, max_length=60)
    valid_to: date | None = None
    activities: list[dict[str, Any]] | None = None
    document_url: str | None = None
    coordinator_staff_id: uuid.UUID | None = None


class MouSign(_Strict):
    signed_on: date
    valid_to: date
    document_url: str | None = None


class MouOut(BaseModel):
    id: uuid.UUID
    partner: str
    partner_type: str
    country: str | None = None
    mou_type: str
    signed_on: date | None = None
    valid_to: date | None = None
    activities: list[dict[str, Any]] = Field(default_factory=list)
    document_url: str | None = None
    coordinator_staff_id: uuid.UUID | None = None
    coordinator_name: str | None = None
    status: str
    collaborations: int = 0
    expiry: Literal["active", "expiring", "expired", "none"] = "none"
    days_to_expiry: int | None = None
    version: int = 1
    previous_id: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None


class CollaborationIn(_Strict):
    mou_id: uuid.UUID | None = None
    title: str = Field(min_length=3, max_length=300)
    collaboration_type: CollaborationType
    participants: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    from_on: date | None = None
    to_on: date | None = None
    outcomes: list[str] = Field(default_factory=list, max_length=50)


class CollaborationOut(BaseModel):
    id: uuid.UUID
    mou_id: uuid.UUID | None = None
    partner: str | None = None
    title: str
    collaboration_type: str
    participants: list[dict[str, Any]] = Field(default_factory=list)
    from_on: date | None = None
    to_on: date | None = None
    outcomes: list[Any] = Field(default_factory=list)


class MouActivityRow(BaseModel):
    mou_id: uuid.UUID
    partner: str
    mou_type: str
    status: str
    collaborations: int
    functional: bool


class StartupIn(_Strict):
    name: str = Field(min_length=2, max_length=200)
    founders: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    sector: str | None = Field(None, max_length=80)
    stage: StartupStage = StartupStage.IDEA
    funding_paise: int | None = Field(None, ge=0)
    mentor_staff_id: uuid.UUID | None = None
    registered_on: date | None = None


class StartupUpdate(_Strict):
    name: str | None = Field(None, min_length=2, max_length=200)
    founders: list[dict[str, Any]] | None = None
    sector: str | None = Field(None, max_length=80)
    funding_paise: int | None = Field(None, ge=0)
    mentor_staff_id: uuid.UUID | None = None
    status: Literal["active", "closed", "graduated"] | None = None


class StartupStageIn(_Strict):
    stage: StartupStage
    funding_paise: int | None = Field(None, ge=0, description="Funding raised at this stage (added)")
    note: str | None = Field(None, max_length=1000)


class StartupOut(BaseModel):
    id: uuid.UUID
    name: str
    founders: list[dict[str, Any]] = Field(default_factory=list)
    sector: str | None = None
    stage: str
    funding_paise: int | None = None
    mentor_staff_id: uuid.UUID | None = None
    mentor_name: str | None = None
    registered_on: date | None = None
    status: str
    history: list[dict[str, Any]] = Field(default_factory=list)


# ---- API score / profile / stats -------------------------------------------------------------------------------------------
class ApiScoreRequest(_Strict):
    staff_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    period_from: date
    period_to: date


class ApiScoreOut(BaseModel):
    staff_id: uuid.UUID
    staff_name: str | None = None
    department_id: uuid.UUID | None = None
    period: str
    total: float
    breakdown: dict[str, Any]
    scheme: str
    computed_at: datetime | None = None


class ApiRankingRow(BaseModel):
    rank: int
    staff_id: uuid.UUID
    name: str
    department_id: uuid.UUID | None = None
    total: float
    period: str


class ResearchProfileOut(BaseModel):
    staff_id: uuid.UUID
    name: str | None = None
    department_id: uuid.UUID | None = None
    orcid: str | None = None
    scopus_id: str | None = None
    publications: int = 0
    verified_publications: int = 0
    by_indexing: dict[str, int] = Field(default_factory=dict)
    citations: int = 0
    h_index: int = 0
    projects: int = 0
    ongoing_projects: int = 0
    funding_paise: int = 0
    consultancy_paise: int = 0
    patents: int = 0
    patents_granted: int = 0
    fdp_hours: float = 0.0
    awards: int = 0
    api_score: float | None = None
    api_updated_at: datetime | None = None


class ResearchStats(BaseModel):
    year: int | None = None
    teachers: int = 0
    publications: int = 0
    publications_by_indexing: dict[str, int] = Field(default_factory=dict)
    per_teacher: float = 0.0
    grants_amount_paise: int = 0
    projects_by_status: dict[str, int] = Field(default_factory=dict)
    consultancy_revenue_paise: int = 0
    patents: dict[str, int] = Field(default_factory=dict)
    fdp: dict[str, Any] = Field(default_factory=dict)
    mous: dict[str, int] = Field(default_factory=dict)
    startups: int = 0
    by_department: list[dict[str, Any]] = Field(default_factory=list)
    nirf_rp: dict[str, Any] = Field(default_factory=dict)
