"""Governance schemas — Prompts/33 §33.4: committees, meetings / minutes / resolutions / ATRs, legal cases, RTI, audit
paras, e-File and policies. Money in paise. ``CommitteeOut`` / ``MemberOut`` supersede the Phase 27 stub shapes
(``GovCommitteeOut`` / ``GovCommitteeMemberOut``) with the same fields plus code, quorum, validity and pendency."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.enums.governance import (
    CommitteeType,
    EfileAction,
    LegalStatus,
    MemberRole,
    MemberType,
    ParaStatus,
    ResolutionStatus,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GovernanceJobQueued(BaseModel):
    job_id: uuid.UUID


class LinkedEntity(BaseModel):
    entity_type: str = Field(min_length=2, max_length=40)
    entity_id: uuid.UUID
    label: str | None = Field(default=None, max_length=200)


class QuorumRule(BaseModel):
    type: Literal["fraction", "count"] = "fraction"
    value: str = Field("1/2", max_length=10)


# ---- committees ---------------------------------------------------------------------------------------------------------
class CommitteeIn(_Strict):
    name: str = Field(min_length=2, max_length=160)
    committee_type: CommitteeType
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    chair_staff_id: uuid.UUID | None = None
    secretary_staff_id: uuid.UUID | None = None
    constituted_on: date | None = None
    valid_to: date | None = None
    quorum_rule: QuorumRule | None = None
    is_active: bool = True


class CommitteeUpdate(_Strict):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    chair_staff_id: uuid.UUID | None = None
    secretary_staff_id: uuid.UUID | None = None
    valid_to: date | None = None
    quorum_rule: QuorumRule | None = None
    is_active: bool | None = None


class CommitteeFromTemplate(_Strict):
    template_key: str = Field(min_length=2, max_length=40)
    department_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    chair_staff_id: uuid.UUID | None = None
    secretary_staff_id: uuid.UUID | None = None
    constituted_on: date | None = None
    valid_to: date | None = None


class CommitteeReconstitute(_Strict):
    constituted_on: date
    valid_to: date | None = None
    chair_staff_id: uuid.UUID | None = None
    secretary_staff_id: uuid.UUID | None = None
    carry_over_member_ids: list[uuid.UUID] = []
    members: list["MemberIn"] = []


class ExternalMember(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    org: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=20)


class MemberIn(_Strict):
    member_type: MemberType = MemberType.STAFF
    staff_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    external: ExternalMember | None = None
    role: MemberRole = MemberRole.MEMBER
    from_on: date | None = None
    to_on: date | None = None


class MemberUpdate(_Strict):
    role: MemberRole | None = None
    from_on: date | None = None
    to_on: date | None = None


class MemberOut(BaseModel):
    id: uuid.UUID
    committee_id: uuid.UUID
    member_type: str
    staff_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    name: str | None = None
    organisation: str | None = None
    role: str
    from_on: date | None = None
    to_on: date | None = None
    active: bool = True


class CommitteeOut(BaseModel):
    id: uuid.UUID
    name: str
    committee_type: str
    code: str
    college_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    chair_staff_id: uuid.UUID | None = None
    chair_name: str | None = None
    secretary_staff_id: uuid.UUID | None = None
    secretary_name: str | None = None
    constituted_on: date | None = None
    valid_to: date | None = None
    valid: bool = True
    quorum_rule: dict[str, Any] | None = None
    is_active: bool
    members: int = 0
    my_role: str | None = None
    next_meeting: datetime | None = None
    open_resolutions: int = 0
    pending_atrs: int = 0


class CommitteeDetail(CommitteeOut):
    member_list: list[MemberOut] = []
    history: list[dict[str, Any]] = []
    meetings: list["MeetingOut"] = []


class CoverageItem(BaseModel):
    committee_type: str
    mandatory: bool
    present: bool
    committee_id: uuid.UUID | None = None
    name: str | None = None
    valid: bool = False
    valid_to: date | None = None
    members: int = 0


class CommitteeTemplateOut(BaseModel):
    template_key: str
    name: str
    committee_type: str
    code: str
    quorum_rule: dict[str, Any]
    per_department: bool


# ---- meetings -----------------------------------------------------------------------------------------------------------
class AgendaItem(BaseModel):
    item: str = Field(min_length=2, max_length=500)
    doc_url: str | None = Field(default=None, max_length=1000)
    presenter: str | None = Field(default=None, max_length=160)
    linked_entity: LinkedEntity | None = None
    source: str | None = Field(default=None, max_length=40)


class MeetingCreate(_Strict):
    committee_id: uuid.UUID
    meeting_no: str | None = Field(default=None, max_length=20)
    held_on: datetime
    venue_or_link: str | None = Field(default=None, max_length=300)
    agenda: list[AgendaItem] = []
    include_atr: bool = True


class MeetingUpdate(_Strict):
    held_on: datetime | None = None
    venue_or_link: str | None = Field(default=None, max_length=300)


class AgendaUpdate(_Strict):
    agenda: list[AgendaItem]
    freeze: bool = False


class NoticeSend(_Strict):
    channels: list[Literal["in_app", "email", "sms", "whatsapp"]] = ["in_app", "email"]


class AttendanceMark(_Strict):
    present_member_ids: list[uuid.UUID] = []
    invitees: list[str] = []
    self_check_in: bool = False


class QuorumOut(BaseModel):
    met: bool
    present: int
    required: int
    total: int


class ResolutionDraft(BaseModel):
    agenda_item: int | None = None
    subject: str = Field(min_length=2, max_length=300)
    text: str = Field(min_length=2, max_length=20000)
    status: Literal["passed", "deferred", "rejected"] = "passed"
    action_owner_staff_id: uuid.UUID | None = None
    due_on: date | None = None
    linked_entity: LinkedEntity | None = None


class MinutesDraft(_Strict):
    minutes_text: str = Field(min_length=2, max_length=200000)
    minutes_url: str | None = Field(default=None, max_length=1000)
    resolutions: list[ResolutionDraft] = []


class MinutesApprove(_Strict):
    comment: str | None = Field(default=None, max_length=2000)
    approve: bool = True


class Corrigendum(_Strict):
    reason: str = Field(min_length=2, max_length=2000)
    minutes_text: str = Field(min_length=2, max_length=200000)


class MeetingCancel(_Strict):
    reason: str = Field(min_length=2, max_length=1000)


class MeetingOut(BaseModel):
    id: uuid.UUID
    committee_id: uuid.UUID
    committee_name: str | None = None
    committee_type: str | None = None
    meeting_no: str | None = None
    held_on: datetime
    venue_or_link: str | None = None
    agenda: list[dict[str, Any]] = []
    agenda_frozen: bool = False
    status: str
    notice_sent_at: datetime | None = None
    short_notice: bool = False
    quorum_met: bool | None = None
    quorum: QuorumOut | None = None
    attendance: dict[str, Any] | None = None
    minutes_text: str | None = None
    minutes_url: str | None = None
    minutes_version: int = 0
    minutes_pdf_document_id: uuid.UUID | None = None
    approval: list[dict[str, Any]] = []
    workflow_instance_id: uuid.UUID | None = None
    resolutions: list["ResolutionOut"] = []
    can_edit: bool = False


class AgendaSuggestion(BaseModel):
    source: str
    item: str
    linked_entity: LinkedEntity | None = None
    detail: str | None = None


# ---- resolutions / ATR --------------------------------------------------------------------------------------------------
class AtrOut(BaseModel):
    id: uuid.UUID
    resolution_id: uuid.UUID
    report_text: str
    attachments: list[Any] = []
    submitted_by: uuid.UUID | None = None
    submitted_by_name: str | None = None
    submitted_at: datetime
    status: str
    decision_remarks: str | None = None


class ResolutionOut(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    committee_id: uuid.UUID | None = None
    committee_name: str | None = None
    number: str
    subject: str
    text: str
    status: str
    action_owner_staff_id: uuid.UUID | None = None
    owner_name: str | None = None
    due_on: date | None = None
    overdue: bool = False
    linked_entity: dict[str, Any] | None = None
    created_at: datetime
    atr: AtrOut | None = None


class ResolutionLink(_Strict):
    entity_type: str = Field(min_length=2, max_length=40)
    entity_id: uuid.UUID
    label: str | None = Field(default=None, max_length=200)


class ResolutionStatusChange(_Strict):
    status: ResolutionStatus
    remarks: str | None = Field(default=None, max_length=2000)


class AtrSubmit(_Strict):
    report_text: str = Field(min_length=2, max_length=20000)
    attachments: list[str] = []


class AtrDecision(_Strict):
    decision: Literal["accepted", "returned"]
    remarks: str | None = Field(default=None, max_length=2000)


class DocumentRef(BaseModel):
    issued_document_id: uuid.UUID | None = None
    url: str | None = None


# ---- legal --------------------------------------------------------------------------------------------------------------
class LegalCaseIn(_Strict):
    case_no: str | None = Field(default=None, max_length=60)
    court: str | None = Field(default=None, max_length=160)
    case_type: str | None = Field(default=None, max_length=60)
    parties: dict[str, Any] | None = None
    institution_role: Literal["petitioner", "respondent", "other"] = "respondent"
    counsel: str | None = Field(default=None, max_length=200)
    counsel_fee_paise: int | None = Field(default=None, ge=0)
    filed_on: date | None = None
    next_hearing: date | None = None
    documents: list[dict[str, Any]] = []
    owner_staff_id: uuid.UUID | None = None
    appeal_of_case_id: uuid.UUID | None = None


class LegalCaseUpdate(_Strict):
    court: str | None = Field(default=None, max_length=160)
    counsel: str | None = Field(default=None, max_length=200)
    parties: dict[str, Any] | None = None
    next_hearing: date | None = None
    documents: list[dict[str, Any]] | None = None
    owner_staff_id: uuid.UUID | None = None


class HearingUpdate(_Strict):
    held_on: date
    notes: str | None = Field(default=None, max_length=10000)
    next_hearing: date | None = None


class LegalOutcome(_Strict):
    outcome: str = Field(min_length=2, max_length=20000)
    status: LegalStatus


class LegalCaseOut(BaseModel):
    id: uuid.UUID
    case_no: str
    court: str | None = None
    case_type: str | None = None
    parties: dict[str, Any] | None = None
    institution_role: str | None = None
    counsel: str | None = None
    filed_on: date | None = None
    next_hearing: date | None = None
    status: str
    outcome: str | None = None
    owner_staff_id: uuid.UUID | None = None
    owner_name: str | None = None
    hearings: list[dict[str, Any]] = []
    appeal_of_case_id: uuid.UUID | None = None
    documents_count: int = 0
    created_at: datetime


# ---- RTI ----------------------------------------------------------------------------------------------------------------
class RtiApplicant(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=200)
    is_bpl: bool = False


class RtiIn(_Strict):
    applicant: RtiApplicant
    received_on: date | None = None
    subject: str = Field(min_length=2, max_length=10000)
    fee_paise: int | None = Field(default=None, ge=0)
    mode: Literal["online", "post", "in_person", "transfer_6_3"] = "in_person"
    fee_mode: Literal["invoice", "cash", "ipo", "dd", "waived"] = "cash"
    transferred_on: date | None = None


class RtiUpdate(_Strict):
    subject: str | None = Field(default=None, max_length=10000)
    applicant: RtiApplicant | None = None


class RtiAssign(_Strict):
    pio_staff_id: uuid.UUID
    departments_consulted: list[uuid.UUID] = []


class RtiConsult(_Strict):
    to_user_id: uuid.UUID | None = None
    to_role: str | None = Field(default=None, max_length=60)
    noting: str = Field(min_length=2, max_length=5000)


class RtiRespond(_Strict):
    response_text: str = Field(min_length=2, max_length=50000)
    response_url: str | None = Field(default=None, max_length=1000)
    fee_additional_paise: int | None = Field(default=None, ge=0)


class RtiAppeal(_Strict):
    grounds: str = Field(min_length=2, max_length=10000)
    appellate_authority_staff_id: uuid.UUID | None = None
    filed_on: date | None = None


class RtiAppealDecision(_Strict):
    decision: Literal["upheld", "allowed", "partly_allowed", "dismissed"]
    remarks: str = Field(min_length=2, max_length=10000)
    second_appeal_note: str | None = Field(default=None, max_length=2000)


class RtiClose(_Strict):
    remarks: str | None = Field(default=None, max_length=2000)


class RtiOut(BaseModel):
    id: uuid.UUID
    request_no: str
    applicant: dict[str, Any]
    masked: bool = False
    received_on: date
    due_on: date
    days_left: int | None = None
    late: bool = False
    subject: str
    mode: str | None = None
    pio_staff_id: uuid.UUID | None = None
    pio_name: str | None = None
    fee_paise: int | None = None
    fee_status: str | None = None
    fee_invoice_id: uuid.UUID | None = None
    response_url: str | None = None
    response_text: str | None = None
    responded_on: date | None = None
    status: str
    first_appeal: dict[str, Any] | None = None
    consultations: list[dict[str, Any]] = []
    created_at: datetime


class RtiReturnOut(BaseModel):
    period: str
    received: int
    disposed: int
    within_time: int
    within_time_pct: float
    appeals: int
    pending: int
    fees_collected_paise: int
    bpl_waivers: int


# ---- audit paras --------------------------------------------------------------------------------------------------------
class AuditParaIn(_Strict):
    audit_register_id: uuid.UUID
    para_no: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=2, max_length=20000)
    amount_paise: int | None = Field(default=None, ge=0)
    owner_staff_id: uuid.UUID | None = None
    due_on: date | None = None


class AuditParaUpdate(_Strict):
    description: str | None = Field(default=None, max_length=20000)
    amount_paise: int | None = Field(default=None, ge=0)
    owner_staff_id: uuid.UUID | None = None
    due_on: date | None = None


class ParaReply(_Strict):
    reply_text: str = Field(min_length=2, max_length=20000)
    attachments: list[str] = []


class ParaStatusUpdate(_Strict):
    status: ParaStatus
    remarks: str | None = Field(default=None, max_length=2000)


class AuditParaOut(BaseModel):
    id: uuid.UUID
    audit_register_id: uuid.UUID
    audit_type: str | None = None
    period_label: str | None = None
    para_no: str
    description: str
    amount_paise: int | None = None
    owner_staff_id: uuid.UUID | None = None
    owner_name: str | None = None
    reply_text: str | None = None
    replies: list[dict[str, Any]] = []
    status: str
    due_on: date | None = None
    age_days: int = 0
    created_at: datetime


class ParaDashboard(BaseModel):
    by_status: dict[str, int]
    ageing: dict[str, int]
    amount_open_paise: int
    by_register: list[dict[str, Any]]


# ---- e-File -------------------------------------------------------------------------------------------------------------
class EfileCreate(_Strict):
    subject: str = Field(min_length=2, max_length=300)
    category: str | None = Field(default=None, max_length=60)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    attachments: list[str] = []
    initial_noting: str = Field(min_length=2, max_length=20000)
    linked_entity: LinkedEntity | None = None


class EfileMove(_Strict):
    to_user_id: uuid.UUID | None = None
    to_role: str | None = Field(default=None, max_length=60)
    action: EfileAction
    noting: str = Field(min_length=2, max_length=20000)
    attachments: list[str] = []
    route_user_ids: list[uuid.UUID] = Field(default=[], max_length=4)


class EfileClose(_Strict):
    summary: str = Field(min_length=2, max_length=5000)


class EfileReopen(_Strict):
    reason: str = Field(min_length=2, max_length=2000)


class EfileMovementOut(BaseModel):
    id: uuid.UUID
    from_user_id: uuid.UUID | None = None
    from_name: str | None = None
    to_user_id: uuid.UUID | None = None
    to_name: str | None = None
    action: str
    noting: str | None = None
    attachments: list[Any] = []
    moved_at: datetime


class EfileOut(BaseModel):
    id: uuid.UUID
    file_no: str
    subject: str
    category: str | None = None
    priority: str
    status: str
    created_by: uuid.UUID
    creator_name: str | None = None
    current_holder_user_id: uuid.UUID | None = None
    holder_name: str | None = None
    pendency_days: int = 0
    over_sla: bool = False
    linked_entity: dict[str, Any] | None = None
    closed_at: datetime | None = None
    summary: str | None = None
    created_at: datetime
    movements: list[EfileMovementOut] = []


class PendencyRow(BaseModel):
    holder_user_id: uuid.UUID | None = None
    holder_name: str | None = None
    department_id: uuid.UUID | None = None
    files: int
    over_sla: int
    max_days: int


# ---- policies -----------------------------------------------------------------------------------------------------------
class PolicyIn(_Strict):
    title: str = Field(min_length=2, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    version: str = Field("1.0", max_length=20)
    effective_from: date | None = None
    file_url: str | None = Field(default=None, max_length=1000)
    summary: str | None = Field(default=None, max_length=5000)
    requires_ack: bool | None = None
    website: bool = False
    supersedes_policy_id: uuid.UUID | None = None


class PolicyUpdate(_Strict):
    title: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    version: str | None = Field(default=None, max_length=20)
    effective_from: date | None = None
    file_url: str | None = Field(default=None, max_length=1000)
    summary: str | None = Field(default=None, max_length=5000)
    requires_ack: bool | None = None
    website: bool | None = None


class PolicyApprove(_Strict):
    resolution_id: uuid.UUID | None = None
    comment: str | None = Field(default=None, max_length=2000)
    approve: bool = True


class PolicyOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None = None
    version: str
    status: str
    stage: str
    effective_from: date | None = None
    file_url: str | None = None
    summary: str | None = None
    requires_ack: bool = False
    website: bool = False
    published: bool = False
    approved_resolution_id: uuid.UUID | None = None
    resolution_number: str | None = None
    owner_user_id: uuid.UUID | None = None
    supersedes_policy_id: uuid.UUID | None = None
    superseded_by_policy_id: uuid.UUID | None = None
    acknowledged: bool = False
    ack_count: int = 0
    ack_pct: float | None = None
    workflow_instance_id: uuid.UUID | None = None
    created_at: datetime


class PolicyAckOut(BaseModel):
    user_id: uuid.UUID
    name: str | None = None
    acknowledged_at: datetime


class GovernanceStats(BaseModel):
    year: int
    meetings_per_committee: list[dict[str, Any]]
    meetings: int
    quorum_compliance_pct: float | None = None
    resolutions: int
    resolutions_implemented_pct: float | None = None
    atr_pending: int
    legal_by_status: dict[str, int]
    rti_received: int
    rti_within_time_pct: float | None = None
    audit_paras_settled_pct: float | None = None
    efile_open: int
    efile_over_sla: int
    policy_ack_pct: float | None = None


class GovernanceMe(BaseModel):
    committees: list[CommitteeOut]
    meetings: list[MeetingOut]
    resolutions: list[ResolutionOut]
    efile_inbox: int
    pending_acks: list[PolicyOut]
    audit_paras: int


CommitteeReconstitute.model_rebuild()
CommitteeDetail.model_rebuild()
MeetingOut.model_rebuild()
