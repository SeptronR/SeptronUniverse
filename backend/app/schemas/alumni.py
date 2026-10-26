"""Alumni, endowments & fundraising schemas (Prompts/29 §29.4).

Names carry an ``Alm`` / ``Fnd`` prefix where a bare name would collide in the OpenAPI components (``EventOut``,
``JobOut``, ``CampaignIn`` …). Money is paise (``int``); PAN is accepted in clear on input and only ever returned
masked (``ABXXXXX12F``).
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

ClaimStatusLit = Literal["unclaimed", "claimed", "verified", "rejected"]
AlumniEventTypeLit = Literal["meet", "webinar", "reunion", "mentorship"]
CampaignStatusLit = Literal["draft", "active", "closed", "archived"]
DonorTypeLit = Literal["alumni", "corporate", "individual"]
DonationModeLit = Literal["online", "bank_transfer", "cheque", "cash", "upi"]
OfflineModeLit = Literal["bank_transfer", "cheque", "cash", "upi"]
JobStatusLit = Literal["pending", "approved", "rejected", "expired"]
DirectoryFieldLit = Literal[
    "name", "batch", "program", "city", "country", "company", "designation", "linkedin_url", "email", "phone"
]

PAN_RE = r"^[A-Z]{5}[0-9]{4}[A-Z]$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- profiles ---------------------------------------------------------------------------------------------------------
class AlmEmploymentIn(_Strict):
    company: str = Field(min_length=1, max_length=200)
    designation: str | None = Field(None, max_length=120)
    from_on: date | None = None
    to_on: date | None = None
    is_current: bool = False

    @model_validator(mode="after")
    def _dates(self) -> "AlmEmploymentIn":
        if self.from_on and self.to_on and self.to_on < self.from_on:
            raise ValueError("to_on must not be before from_on")
        if self.is_current and self.to_on:
            raise ValueError("A current job has no end date")
        return self


class AlmEmploymentOut(BaseModel):
    id: uuid.UUID
    company: str
    designation: str | None = None
    from_on: date | None = None
    to_on: date | None = None
    is_current: bool


class AlmEngagementOut(BaseModel):
    alumni_id: uuid.UUID
    score: int
    breakdown: dict[str, int] = Field(default_factory=dict)
    computed_at: datetime | None = None
    rank_pct: int | None = None


class AlumniProfileOut(BaseModel):
    """Self / coordinator view (full); auditors get masked contacts."""

    id: uuid.UUID
    student_id: uuid.UUID
    user_id: uuid.UUID | None = None
    name: str
    registration_number: str | None = None
    graduation_year: int | None = None
    program_id: uuid.UUID | None = None
    program: str | None = None
    department_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    current_company: str | None = None
    designation: str | None = None
    city: str | None = None
    country: str | None = None
    linkedin_url: str | None = None
    email: str | None = None
    phone: str | None = None
    is_verified: bool
    claim_status: ClaimStatusLit
    legacy: bool = False
    willing_to_mentor: bool
    willing_to_recruit: bool
    consent_contact: bool
    consent_directory_fields: list[str] = Field(default_factory=list)
    higher_studies: dict[str, Any] | None = None
    chapter: str | None = None
    completeness: int = 0
    engagement_score: int = 0
    employment: list[AlmEmploymentOut] = Field(default_factory=list)
    last_updated_by_alumni_at: datetime | None = None
    created_at: datetime | None = None
    masked: bool = False


class AlumniProfileUpdate(_Strict):
    current_company: str | None = Field(None, max_length=200)
    designation: str | None = Field(None, max_length=120)
    city: str | None = Field(None, max_length=80)
    country: str | None = Field(None, max_length=80)
    linkedin_url: str | None = Field(None, max_length=300)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    willing_to_mentor: bool | None = None
    willing_to_recruit: bool | None = None
    consent_contact: bool | None = None
    consent_directory_fields: list[DirectoryFieldLit] | None = None
    higher_studies: dict[str, Any] | None = None
    chapter: str | None = Field(None, max_length=80)


class AlumniImportRow(_Strict):
    registration_number: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    graduation_year: int = Field(ge=1950, le=2100)
    program_code: str | None = Field(None, max_length=40)
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=20)
    city: str | None = Field(None, max_length=80)
    company: str | None = Field(None, max_length=200)


class AlumniImport(_Strict):
    """CSV via ``file_url`` + column ``mapping`` (``{csv_header: field}``), or ``rows`` inline (≤ 5,000)."""

    file_url: str | None = None
    mapping: dict[str, str] | None = None
    rows: list[AlumniImportRow] | None = Field(None, max_length=5000)
    college_id: uuid.UUID | None = None


class AlmImportReport(BaseModel):
    created: int = 0
    linked: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ClaimRequest(_Strict):
    registration_number: str = Field(min_length=1, max_length=30)
    graduation_year: int = Field(ge=1950, le=2100)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    captcha_token: str | None = None

    @model_validator(mode="after")
    def _contact(self) -> "ClaimRequest":
        if not self.email and not self.phone:
            raise ValueError("email or phone is required")
        return self


class ClaimResponse(BaseModel):
    claim_token: str | None = None
    sent: bool = True
    channel: str | None = None
    ttl_seconds: int = 600
    message: str = "If the details match our records, a code has been sent."


class ClaimVerify(_Strict):
    claim_token: str = Field(min_length=8, max_length=80)
    otp: str = Field(min_length=4, max_length=8)


class ClaimVerifyResponse(BaseModel):
    alumni_id: uuid.UUID
    claim_status: ClaimStatusLit
    username: str | None = None
    message: str


class VerifyDecision(_Strict):
    approve: bool
    remarks: str | None = Field(None, max_length=500)
    document_url: str | None = None


class MergeRequest(_Strict):
    keep_id: uuid.UUID
    merge_id: uuid.UUID

    @model_validator(mode="after")
    def _distinct(self) -> "MergeRequest":
        if self.keep_id == self.merge_id:
            raise ValueError("keep_id and merge_id must differ")
        return self


class MergeReport(BaseModel):
    kept_id: uuid.UUID
    merged_id: uuid.UUID
    moved: dict[str, int] = Field(default_factory=dict)


class AlmProfileListItem(BaseModel):
    id: uuid.UUID
    name: str
    registration_number: str | None = None
    graduation_year: int | None = None
    program: str | None = None
    department_id: uuid.UUID | None = None
    city: str | None = None
    current_company: str | None = None
    email: str | None = None
    phone: str | None = None
    is_verified: bool
    claim_status: ClaimStatusLit
    legacy: bool = False
    willing_to_mentor: bool
    willing_to_recruit: bool
    consent_contact: bool
    engagement_score: int = 0


# ---- directory ----------------------------------------------------------------------------------------------------------
class DirectoryEntry(BaseModel):
    """Consented projection — absent keys were not consented (or not visible to the requester class)."""

    id: uuid.UUID
    fields: dict[str, Any] = Field(default_factory=dict)
    willing_to_mentor: bool = False
    willing_to_recruit: bool = False
    contactable: bool = False


class DirectoryFacets(BaseModel):
    batch: dict[str, int] = Field(default_factory=dict)
    program: dict[str, int] = Field(default_factory=dict)
    city: dict[str, int] = Field(default_factory=dict)
    company: dict[str, int] = Field(default_factory=dict)


class DirectoryPage(BaseModel):
    items: list[DirectoryEntry] = Field(default_factory=list)
    total: int = 0
    facets: DirectoryFacets = DirectoryFacets()
    requester: Literal["alumni", "student", "staff"] = "alumni"


class ContactRequest(_Strict):
    message: str = Field(min_length=5, max_length=1000)


class ContactRequestOut(BaseModel):
    id: uuid.UUID
    to_alumni_id: uuid.UUID
    relayed: bool
    channels: list[str] = Field(default_factory=list)


# ---- events -----------------------------------------------------------------------------------------------------------------
class AlmEventIn(_Strict):
    title: str = Field(min_length=3, max_length=200)
    event_type: AlumniEventTypeLit = "meet"
    description: str | None = Field(None, max_length=8000)
    held_on: date
    to_on: date | None = None
    venue: str | None = Field(None, max_length=200)
    webinar_url: str | None = Field(None, max_length=500)
    registration_fee_paise: int = Field(0, ge=0)
    capacity: int | None = Field(None, ge=1)
    college_id: uuid.UUID | None = None


class AlmEventOut(BaseModel):
    id: uuid.UUID
    title: str
    event_type: str
    held_on: date | None = None
    venue: str | None = None
    event_id: uuid.UUID | None = None
    event_status: str | None = None
    registration_fee_paise: int = 0
    registrations_count: int = 0
    attended_count: int = 0
    webinar_url: str | None = None
    invited: int = 0
    photos: list[str] = Field(default_factory=list)
    my_registration_id: uuid.UUID | None = None
    created_at: datetime | None = None


class AlmEventInvite(_Strict):
    graduation_years: list[int] = Field(default_factory=list)
    program_ids: list[uuid.UUID] = Field(default_factory=list)
    chapter: str | None = None
    city: str | None = None
    verified_only: bool = False


class AlmInviteReport(BaseModel):
    invited: int
    campaign_id: uuid.UUID | None = None


# ---- jobs -----------------------------------------------------------------------------------------------------------------------
class AlmJobIn(_Strict):
    title: str = Field(min_length=3, max_length=200)
    company: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=8000)
    apply_url: str | None = Field(None, max_length=500)
    expires_on: date | None = None
    open_to_students: bool = False


class AlmJobOut(BaseModel):
    id: uuid.UUID
    title: str
    company: str | None = None
    location: str | None = None
    description: str | None = None
    apply_url: str | None = None
    expires_on: date | None = None
    is_active: bool
    status: JobStatusLit
    reason: str | None = None
    clicks: int = 0
    open_to_students: bool = False
    posted_by_alumni_id: uuid.UUID | None = None
    posted_by: str | None = None
    lead_company_id: uuid.UUID | None = None
    created_at: datetime | None = None


class JobModeration(_Strict):
    approve: bool
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _reason(self) -> "JobModeration":
        if not self.approve and not self.reason:
            raise ValueError("reason is required when rejecting")
        return self


class AlmJobClick(BaseModel):
    clicks: int
    apply_url: str | None = None


# ---- campaigns / donations --------------------------------------------------------------------------------------------------------
class CampaignIn(_Strict):
    title: str = Field(min_length=3, max_length=200)
    purpose: str | None = Field(None, max_length=8000)
    goal_paise: int = Field(gt=0)
    from_on: date | None = None
    to_on: date | None = None
    is_restricted_fund: bool = False
    ledger_account_id: uuid.UUID | None = None
    status: Literal["draft", "active"] = "active"
    is_public: bool = True


class CampaignUpdate(_Strict):
    title: str | None = Field(None, min_length=3, max_length=200)
    purpose: str | None = Field(None, max_length=8000)
    goal_paise: int | None = Field(None, gt=0)
    from_on: date | None = None
    to_on: date | None = None
    is_restricted_fund: bool | None = None
    ledger_account_id: uuid.UUID | None = None
    status: Literal["draft", "active", "archived"] | None = None
    is_public: bool | None = None


class CampaignOut(BaseModel):
    id: uuid.UUID
    title: str
    purpose: str | None = None
    goal_paise: int | None = None
    raised_paise: int = 0
    donors_count: int = 0
    progress_pct: int = 0
    from_on: date | None = None
    to_on: date | None = None
    status: str
    is_restricted_fund: bool = False
    ledger_account_id: uuid.UUID | None = None
    is_public: bool = True
    milestones_reached: list[int] = Field(default_factory=list)
    donor_mix: dict[str, int] = Field(default_factory=dict)
    created_at: datetime | None = None


class DonorRef(_Strict):
    alumni_id: uuid.UUID | None = None
    name: str | None = Field(None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=500)
    pan: str | None = Field(None, pattern=PAN_RE)
    organisation: str | None = Field(None, max_length=200)
    csr_reference: str | None = Field(None, max_length=120)
    anonymous: bool = False


class DonationCreate(_Strict):
    """Offline record (bank transfer / cheque / cash / UPI) by the coordinator or accountant."""

    donor_type: DonorTypeLit
    donor_ref: DonorRef
    campaign_id: uuid.UUID | None = None
    amount_paise: int = Field(gt=0)
    mode: OfflineModeLit
    on_date: date
    reference: str | None = Field(None, max_length=120)
    wants_80g: bool = False

    @model_validator(mode="after")
    def _donor(self) -> "DonationCreate":
        if self.donor_type == "alumni" and not self.donor_ref.alumni_id and not self.donor_ref.name:
            raise ValueError("donor_ref.alumni_id or donor_ref.name is required")
        if self.donor_type != "alumni" and not self.donor_ref.name:
            raise ValueError("donor_ref.name is required")
        return self


class DonationOut(BaseModel):
    id: uuid.UUID
    donor_type: str
    donor_name: str
    donor_key: str
    anonymous: bool = False
    alumni_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    campaign: str | None = None
    amount_paise: int
    on_date: date
    mode: str | None = None
    reference: str | None = None
    is_80g: bool
    wants_80g: bool = False
    pan_masked: str | None = None
    receipt_no: str | None = None
    receipt_document_id: uuid.UUID | None = None
    receipt_url: str | None = None
    refunded: bool = False
    refund: dict[str, Any] | None = None
    created_at: datetime | None = None


class OnlineDonor(_Strict):
    name: str | None = Field(None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=500)
    pan: str | None = Field(None, pattern=PAN_RE)
    organisation: str | None = Field(None, max_length=200)
    anonymous: bool = False


class OnlineDonateRequest(_Strict):
    campaign_id: uuid.UUID | None = None
    amount_paise: int = Field(gt=0)
    donor_type: DonorTypeLit | None = None
    donor: OnlineDonor = OnlineDonor()
    wants_80g: bool = False
    captcha_token: str | None = None


class OnlineDonateResponse(BaseModel):
    intent_id: uuid.UUID
    order: dict[str, Any]
    checkout: dict[str, Any] = Field(default_factory=dict)
    replayed: bool = False


class DonationRefund(_Strict):
    reason: str = Field(min_length=3, max_length=500)
    amount_paise: int | None = Field(None, gt=0)


class Receipt80GReissue(_Strict):
    donor_name: str | None = Field(None, max_length=200)
    address: str | None = Field(None, max_length=500)
    pan: str | None = Field(None, pattern=PAN_RE)
    reason: str = Field(min_length=3, max_length=500)


class Receipt80GOut(BaseModel):
    donation_id: uuid.UUID
    receipt_no: str
    receipt_document_id: uuid.UUID | None = None
    url: str | None = None
    superseded_document_id: uuid.UUID | None = None


class Register80GRow(BaseModel):
    donation_id: uuid.UUID
    receipt_no: str | None = None
    on_date: date
    donor_name: str
    donor_type: str
    pan_masked: str | None = None
    address: str | None = None
    mode: str | None = None
    amount_paise: int
    campaign: str | None = None


class DonorPage(BaseModel):
    donor_key: str
    donor_type: str
    name: str
    email: str | None = None
    organisation: str | None = None
    csr_references: list[str] = Field(default_factory=list)
    total_paise: int = 0
    donations: list[DonationOut] = Field(default_factory=list)
    campaigns: list[str] = Field(default_factory=list)


class AlmJobQueued(BaseModel):
    job_id: uuid.UUID | None = None
    status: str = "queued"
    result: dict[str, Any] | None = None


# ---- stats ----------------------------------------------------------------------------------------------------------------------
class AlumniStats(BaseModel):
    total: int = 0
    by_batch: dict[str, int] = Field(default_factory=dict)
    verified_pct: float = 0
    claimed_pct: float = 0
    employed_pct: float = 0
    higher_studies_pct: float = 0
    consent_contact_pct: float = 0
    mentors: int = 0
    recruiters: int = 0
    by_city: dict[str, int] = Field(default_factory=dict)
    by_country: dict[str, int] = Field(default_factory=dict)
    donations_total_paise: int = 0
    donations_by_campaign: dict[str, int] = Field(default_factory=dict)
    donations_by_year: dict[str, int] = Field(default_factory=dict)
    events: int = 0
    event_participation: int = 0
    jobs_posted: int = 0
