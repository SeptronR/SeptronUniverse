"""Document engine schemas — Prompts/26 §26.4 (OpenAPI names prefixed ``Doc`` / ``CertReq`` to stay unique)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


PageSizeLit = Literal["A4", "A5", "Letter", "ID_CR80", "custom"]
DeliveryLit = Literal["digital", "pickup", "post"]
PersonTypeLit = Literal["student", "staff", "alumni"]


# ---- templates ---------------------------------------------------------------------------------------------------------
class DocLayoutBlock(BaseModel):
    """One builder block: ``header | title | paragraph | table | photo | qr | barcode | signatures | seal | footer |
    watermark | secondary`` (``secondary`` = the bilingual block)."""

    model_config = ConfigDict(extra="allow")
    type: str
    text: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)


class DocTemplateIn(_Strict):
    template_type: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    layout: dict[str, Any] | None = Field(None, description="{blocks: [DocLayoutBlock], ...}")
    html_template: str | None = None
    css: str | None = None
    page_size: PageSizeLit = "A4"
    is_bilingual: bool = False
    secondary_language: str | None = Field(None, max_length=10)
    variables: list[dict[str, Any]] | None = None
    is_default: bool = False
    from_template_id: uuid.UUID | None = Field(None, description="clone this template (platform default or override)")
    college_id: uuid.UUID | None = Field(None, description="college override (when the institution permits)")


class DocTemplateUpdate(_Strict):
    name: str | None = Field(None, min_length=2, max_length=120)
    layout: dict[str, Any] | None = None
    html_template: str | None = None
    css: str | None = None
    page_size: PageSizeLit | None = None
    is_bilingual: bool | None = None
    secondary_language: str | None = Field(None, max_length=10)
    is_default: bool | None = None


class DocTemplateOut(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID | None = None
    template_type: str
    name: str
    layout: dict[str, Any] | None = None
    html_template: str | None = None
    css: str | None = None
    page_size: str
    is_bilingual: bool
    secondary_language: str | None = None
    variables: Any | None = None
    is_default: bool
    is_active: bool
    version: int
    source: Literal["platform", "institution"]
    status: Literal["draft", "published"] = "published"
    college_id: uuid.UUID | None = None
    change_note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocTemplateClone(_Strict):
    from_template_id: uuid.UUID


class DocTemplatePublish(_Strict):
    change_note: str = Field(min_length=2, max_length=500)


class DocTemplatePreview(_Strict):
    draft: DocTemplateUpdate | None = None
    sample_entity_type: str | None = None
    sample_entity_id: uuid.UUID | None = None
    variables: dict[str, Any] | None = None
    language: str | None = None
    format: Literal["pdf", "html"] = "pdf"


class DocLintIssue(BaseModel):
    level: Literal["error", "warning"]
    message: str
    variable: str | None = None


class DocTemplateLint(BaseModel):
    ok: bool
    issues: list[DocLintIssue] = Field(default_factory=list)


class DocVariable(BaseModel):
    key: str
    label: str
    source: str
    example: str | None = None


class DocVariablesCatalogue(BaseModel):
    template_type: str
    variables: list[DocVariable]


class DocTemplateUsage(BaseModel):
    template_id: uuid.UUID
    issued_count: int
    by_entity_type: dict[str, int]
    flows: list[str]
    last_issued_at: datetime | None = None


# ---- render / issued -----------------------------------------------------------------------------------------------------
class DocRenderRequest(_Strict):
    template_type: str
    template_id: uuid.UUID | None = None
    entity_type: str
    entity_id: uuid.UUID
    variables_override: dict[str, Any] | None = None
    register_: str | None = Field(None, alias="register", description="serial register (statutory book)")
    watermark: str | None = Field(None, max_length=120)
    language: str | None = None
    allow_multiple: bool = False
    document_number: str | None = Field(None, max_length=40, description="explicit number (e.g. degree certificates)")


class DocRenderResult(BaseModel):
    issued_document_id: uuid.UUID
    document_number: str
    serial_no: str | None = None
    pdf_url: str | None = None
    verification_token: str
    content_hash: str
    reused: bool = False


class IssuedDocumentOut(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID | None = None
    template_version: int | None = None
    template_type: str
    person_type: str | None = None
    person_id: uuid.UUID | None = None
    person_name: str | None = None
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
    document_number: str
    serial_no: str | None = None
    verification_token: str | None = None
    content_hash: str
    watermark_text: str | None = None
    issued_by: uuid.UUID | None = None
    issued_by_name: str | None = None
    issued_at: datetime
    revoked: bool = False
    revoked_at: datetime | None = None
    revoke_reason: str | None = None
    superseded_by: uuid.UUID | None = None
    supersedes: uuid.UUID | None = None
    downloads: int = 0
    job_id: uuid.UUID | None = None
    download_log: list[dict[str, Any]] | None = None


class DocRevokeRequest(_Strict):
    reason: str = Field(min_length=3, max_length=1000)


class DocReissueRequest(_Strict):
    reason: str = Field(min_length=3, max_length=1000)
    variables_override: dict[str, Any] | None = None


class DocSignedLinkRequest(_Strict):
    ttl_minutes: int | None = Field(None, ge=1, le=1440)
    watermark_text: str | None = Field(None, max_length=120)
    purpose: str | None = Field(None, max_length=120)
    single_use: bool = False


class DocSignedLinkOut(BaseModel):
    url: str
    expires_at: datetime
    watermarked: bool = True


# ---- bulk -----------------------------------------------------------------------------------------------------------------
class DocBulkScope(_Strict):
    batch_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None
    enrollment_ids: list[uuid.UUID] | None = None
    staff_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def _one(self) -> "DocBulkScope":
        if not any((self.batch_id, self.section_id, self.enrollment_ids, self.staff_ids)):
            raise ValueError("scope needs batch_id, section_id, enrollment_ids or staff_ids")
        return self


class DocBulkGenerateRequest(_Strict):
    template_type: str
    template_id: uuid.UUID | None = None
    scope: DocBulkScope
    variables_override: dict[str, Any] | None = None
    register_: str | None = Field(None, alias="register", description="serial register (statutory book)")
    zip: bool = True
    print_order: Literal["roll", "serial", "name"] = "roll"


class DocBulkJobOut(BaseModel):
    job_id: uuid.UUID
    status: str
    progress: int = 0
    message: str | None = None
    result: dict[str, Any] | None = None
    zip_url: str | None = None


# ---- serial registers ---------------------------------------------------------------------------------------------------
class DocSerialRegisterOut(BaseModel):
    register_: str = Field(alias="register")
    next: str | None = None
    reserved: int = 0
    used: int = 0
    void: int = 0
    book: dict[str, Any] | None = None


class DocSerialRow(BaseModel):
    id: uuid.UUID
    register_: str = Field(alias="register")
    serial_no: str
    status: str
    issued_document_id: uuid.UUID | None = None
    document_number: str | None = None
    reason: str | None = None
    created_at: datetime


class DocSerialReserve(_Strict):
    count: int = Field(1, ge=1, le=500)


class DocSerialVoid(_Strict):
    serial_no: str = Field(max_length=40)
    reason: str = Field(min_length=3, max_length=500)


class DocReconcileOut(BaseModel):
    register_: str = Field(alias="register")
    issued: int
    used: int
    reserved: int
    void: int
    issued_without_serial: list[str]
    used_without_document: list[str]
    gaps: list[str]


# ---- certificate requests -----------------------------------------------------------------------------------------------
class CertReqCreate(_Strict):
    template_type: str
    person_type: PersonTypeLit | None = None
    person_id: uuid.UUID | None = Field(None, description="ward student id when a guardian requests on behalf")
    purpose: str | None = Field(None, max_length=200)
    copies: int = Field(1, ge=1, le=10)
    delivery: DeliveryLit = "digital"
    address: str | None = Field(None, max_length=500)
    registration_number: str | None = Field(None, max_length=40, description="alumni identity check")

    @model_validator(mode="after")
    def _addr(self) -> "CertReqCreate":
        if self.delivery == "post" and not self.address:
            raise ValueError("address is required for postal delivery")
        return self


class CertReqTypeOut(BaseModel):
    template_type: str
    label: str
    fee_paise: int
    copies_fee_paise: int
    sla_days: int
    approver: str
    requires_no_dues: bool = False
    allowed: bool = True
    reason: str | None = None


class CertReqOut(BaseModel):
    id: uuid.UUID
    requester_user_id: uuid.UUID
    requester_name: str | None = None
    person_type: str
    person_id: uuid.UUID
    person_name: str | None = None
    template_type: str
    purpose: str | None = None
    copies: int
    delivery: str
    status: str
    stage: str | None = Field(None, description="finer state: awaiting_no_dues | blocked | pickup_ready | collected …")
    fee_invoice_id: uuid.UUID | None = None
    fee_paise: int = 0
    fee_status: str | None = None
    workflow: dict[str, Any] | None = None
    issued_document_id: uuid.UUID | None = None
    document_number: str | None = None
    sla_due_on: str | None = None
    sla_breached: bool = False
    checks: dict[str, Any] | None = None
    pickup: dict[str, Any] | None = None
    courier_ref: str | None = None
    address: str | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None


class CertReqDecision(_Strict):
    action: Literal["approve", "reject", "recommend"]
    remarks: str | None = Field(None, max_length=1000)


class CertReqGenerate(_Strict):
    template_id: uuid.UUID | None = None


class CertReqIssue(_Strict):
    delivery_note: str | None = Field(None, max_length=500)
    courier_ref: str | None = Field(None, max_length=80)
    pickup_on: str | None = Field(None, description="pickup slot (ISO date / datetime)")


class CertReqCollected(_Strict):
    collected_by: str = Field(min_length=2, max_length=120)
    signature_url: str | None = None


# ---- verification -------------------------------------------------------------------------------------------------------
class DocVerifyOut(BaseModel):
    valid: bool
    template_type: str | None = None
    document_number: str | None = None
    issued_at: datetime | None = None
    holder_masked: str | None = None
    institution: str | None = None
    revoked: bool = False
    revoke_reason: str | None = None
    content_hash: str | None = None
    superseded_by: str | None = None
    message: str | None = None
    details: dict[str, Any] | None = None
    pdf_url: str | None = None


class DocHashVerifyOut(BaseModel):
    valid: bool
    document_number: str | None = None
    template_type: str | None = None
    institution: str | None = None
    revoked: bool = False
    hint: str | None = None


class DocBulkVerifyRequest(_Strict):
    tokens: list[str] = Field(min_length=1, max_length=100)
    captcha_token: str | None = None


# ---- stats / settings ---------------------------------------------------------------------------------------------------
class DocumentStatsOut(BaseModel):
    issued_by_type: dict[str, int]
    issued_by_month: dict[str, int]
    revoked: int
    requests_by_status: dict[str, int]
    sla_compliance_pct: float | None = None
    fee_revenue_paise: int = 0
    pending_pickups: int = 0


class DocSettingsOut(BaseModel):
    request_rules: dict[str, Any]
    signatories: dict[str, Any]
    watermark: dict[str, Any]
    verify_shows_pdf: bool = False
    allow_parent_requests: bool = False
    college_overrides: bool = False
    signed_link_ttl_minutes: int = 15
    preview_retention_days: int = 1
