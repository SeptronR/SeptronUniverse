"""Admission cycles, seat matrix, applicants, merit lists, counselling, offers and enquiries — Prompts/08 §08.4.

Applicant PII (phone, e-mail, the contact JSON, guardian contacts) is declared through the ``Masked*`` types and
masked by the service unless the reader holds ``admissions:view_pii`` (the applicant reading the own application sees
it unmasked). PII stored inside JSON columns (``contact``) is masked key by key with ``mask_value``. Request bodies
forbid unknown keys.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.authz.masking import MaskedEmail, MaskedPhone
from app.enums.admissions import (
    AllotmentAction,
    ApplicantEntryType,
    ApplicantStatus,
    CycleLevel,
    CycleStatus,
    EnquirySource,
    EnquiryStage,
    EntranceSource,
    OfferType,
    RoundStatus,
)
from app.schemas.common import ORMModel

PHONE = r"^\+?[0-9 -]{8,20}$"
SLUG = r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- cycles -----------------------------------------------------------------------------------------------------------
class RequiredDocument(BaseModel):
    doc_type: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9_]+$")
    label: str | None = Field(default=None, max_length=120)
    required: bool = True
    entry_types: list[ApplicantEntryType] | None = Field(default=None, description="null = every entry type")


class CycleCreate(_Strict):
    name: str = Field(min_length=3, max_length=120)
    slug: str = Field(pattern=SLUG)
    level: CycleLevel
    academic_year_id: uuid.UUID
    college_id: uuid.UUID | None = None
    application_fee_paise: int = Field(default=0, ge=0)
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    form_config: dict[str, Any] | None = Field(
        default=None, description="steps / fields / refund_policy / strict_eligibility / max_preferences"
    )
    required_documents: list[RequiredDocument] | None = None
    de_reservation_policy: dict[str, Any] | None = Field(
        default=None,
        description='{"convert": {"SC": "GEN", "ST": "SC"}, "final_round_number": 2} — vacant reserved seats convert '
        "in the final round only",
    )


class CycleUpdate(_Strict):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    application_fee_paise: int | None = Field(default=None, ge=0)
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    form_config: dict[str, Any] | None = None
    required_documents: list[RequiredDocument] | None = None
    de_reservation_policy: dict[str, Any] | None = None
    version: int | None = None


class CycleStatusChange(_Strict):
    status: CycleStatus
    reason: str | None = Field(default=None, max_length=500)


class CycleResponse(ORMModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    academic_year_id: uuid.UUID
    name: str
    slug: str
    level: str
    application_fee_paise: int
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    status: str
    form_config: dict[str, Any] | None = None
    required_documents: list[dict[str, Any]] | None = None
    de_reservation_policy: dict[str, Any] | None = None
    version: int
    created_at: datetime
    programs_count: int = 0
    applicants_count: int = 0
    intake_total: int = 0


class CycleProgramIn(_Strict):
    program_id: uuid.UUID
    college_id: uuid.UUID | None = Field(default=None, description="default: the programme's college")
    intake: int = Field(ge=1, le=5000)
    lateral_intake: int = Field(default=0, ge=0, le=1000)
    entrance_source: EntranceSource = EntranceSource.MERIT_ONLY
    eligibility_rules: dict[str, Any] | None = Field(
        default=None,
        description='{"min_qualifying_pct": 60, "qualifying_level": "12", "subjects": ["PHY","MAT"], "max_age": 25, '
        '"entrance_required": true, "category_relaxation_pct": {"SC": 5}}',
    )
    merit_formula: list[dict[str, Any]] | None = Field(
        default=None,
        description='[{"field": "entrance_score", "weight": 60, "max": 300}, {"field": "qualifying_pct", "weight": 40}]',
    )
    tie_break: list[str] | None = Field(default=None, description='["entrance_score", "dob_asc", "submitted_at"]')


class CycleProgramsReplace(_Strict):
    programs: list[CycleProgramIn] = Field(min_length=1, max_length=200)


class CycleProgramOut(ORMModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    program_id: uuid.UUID
    college_id: uuid.UUID
    program_code: str | None = None
    program_name: str | None = None
    college_name: str | None = None
    department_id: uuid.UUID | None = None
    intake: int
    lateral_intake: int
    entrance_source: str
    eligibility_rules: dict[str, Any] | None = None
    merit_formula: list[dict[str, Any]] | None = None
    tie_break: list[str] | None = None


class SeatRow(_Strict):
    program_id: uuid.UUID
    college_id: uuid.UUID | None = None
    quota: str = Field(min_length=2, max_length=30)
    category: str = Field(min_length=2, max_length=20)
    seats: int = Field(ge=0, le=5000)


class SeatMatrixReplace(_Strict):
    rows: list[SeatRow] = Field(max_length=2000)


class SeatRowOut(ORMModel):
    id: uuid.UUID
    program_id: uuid.UUID
    college_id: uuid.UUID
    program_code: str | None = None
    quota: str
    category: str
    seats: int
    filled: int
    vacant: int = 0


class ProgramSeatTotal(BaseModel):
    program_id: uuid.UUID
    college_id: uuid.UUID
    program_code: str | None = None
    intake: int
    lateral_intake: int
    seats: int
    filled: int
    balanced: bool


class SeatStatusResponse(BaseModel):
    cycle_id: uuid.UUID
    rows: list[SeatRowOut]
    programs: list[ProgramSeatTotal]
    quotas: list[str]
    categories: list[str]


class PublicCycleProgram(BaseModel):
    program_id: uuid.UUID
    college_id: uuid.UUID
    code: str | None = None
    name: str | None = None
    college_name: str | None = None
    intake: int
    lateral_intake: int
    entrance_source: str
    eligibility_rules: dict[str, Any] | None = None


class PublicCycleInfo(BaseModel):
    name: str
    slug: str
    level: str
    status: str
    application_fee_paise: int
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    is_open: bool
    institution: dict[str, Any]
    programs: list[PublicCycleProgram] = Field(default_factory=list)
    required_documents: list[dict[str, Any]] = Field(default_factory=list)
    form_config: dict[str, Any] | None = None
    categories: list[dict[str, Any]] = Field(default_factory=list)
    quotas: list[dict[str, Any]] = Field(default_factory=list)
    published_merit_lists: list[dict[str, Any]] = Field(default_factory=list)


# ---- public application ------------------------------------------------------------------------------------------------
class PublicStartRequest(_Strict):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    phone: str = Field(pattern=PHONE)
    email: EmailStr | None = None
    password: str = Field(min_length=8, max_length=128)
    otp_code: str | None = Field(default=None, pattern=r"^\d{6}$", description="omit to receive the code")
    entry_type: ApplicantEntryType = ApplicantEntryType.REGULAR
    captcha_token: str | None = None


class PublicStartResult(BaseModel):
    otp_sent: bool = False
    ttl_seconds: int | None = None
    dev_otp: str | None = Field(default=None, description="development only (mock SMS)")
    applicant_id: uuid.UUID | None = None
    application_number: str | None = None
    username: str | None = None


class PublicApplicationCreate(_Strict):
    """The full form in one body (offline desk entry / the import mapping); the portal fills it step by step."""

    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    dob: date | None = None
    gender: Literal["M", "F", "O"] | None = None
    category: str | None = Field(default=None, max_length=20)
    is_pwd: bool = False
    quota_claimed: str | None = Field(default=None, max_length=30)
    nationality: str | None = Field(default="Indian", max_length=60)
    domicile_state: str | None = Field(default=None, max_length=60)
    contact: dict[str, Any] | None = None
    entrance: dict[str, Any] | None = None
    qualifying_exams: list[dict[str, Any]] | None = None
    entry_type: ApplicantEntryType = ApplicantEntryType.REGULAR
    preferences: list["PreferenceIn"] = Field(default_factory=list, max_length=20)


class ApplicantUpdate(_Strict):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    dob: date | None = None
    gender: Literal["M", "F", "O"] | None = None
    category: str | None = Field(default=None, max_length=20)
    is_pwd: bool | None = None
    quota_claimed: str | None = Field(default=None, max_length=30)
    nationality: str | None = Field(default=None, max_length=60)
    domicile_state: str | None = Field(default=None, max_length=60)
    contact: dict[str, Any] | None = Field(
        default=None, description="{phone, email, address, guardian_name, guardian_phone, guardian_relation}"
    )
    entrance: dict[str, Any] | None = Field(default=None, description="{exam, roll_no, score, max_score, rank, year}")
    qualifying_exams: list[dict[str, Any]] | None = Field(
        default=None, description="[{level, board, year, pct, subjects}]"
    )
    entry_type: ApplicantEntryType | None = None
    remarks: str | None = Field(default=None, max_length=2000)
    version: int | None = None


class PreferenceIn(_Strict):
    program_id: uuid.UUID
    college_id: uuid.UUID | None = None


class PreferencesReplace(_Strict):
    preferences: list[PreferenceIn] = Field(min_length=1, max_length=20)


ChoiceFillingRequest = PreferencesReplace


class PreferenceOut(BaseModel):
    priority: int
    program_id: uuid.UUID
    college_id: uuid.UUID
    program_code: str | None = None
    program_name: str | None = None
    eligible: bool | None = None
    reasons: list[str] = Field(default_factory=list)


class ApplicantDocumentOut(ORMModel):
    doc_type: str
    file_url: str | None = None
    status: str
    remarks: str | None = None
    verified_at: datetime | None = None


class ApplicantListItem(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    application_number: str
    name: str
    category: str | None = None
    is_pwd: bool = False
    quota_claimed: str | None = None
    entry_type: str
    source: str
    status: str
    merit_score: Decimal | None = None
    phone: MaskedPhone = None
    email: MaskedEmail = None
    first_preference: str | None = None
    submitted_at: datetime | None = None
    docs_pending: int = 0


class ApplicantResponse(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    cycle_name: str | None = None
    cycle_slug: str | None = None
    application_number: str
    user_id: uuid.UUID | None = None
    first_name: str
    middle_name: str | None = None
    last_name: str | None = None
    name: str
    dob: date | None = None
    gender: str | None = None
    category: str | None = None
    is_pwd: bool = False
    quota_claimed: str | None = None
    nationality: str | None = None
    domicile_state: str | None = None
    phone: MaskedPhone = None
    email: MaskedEmail = None
    contact: dict[str, Any] | None = None
    entrance: dict[str, Any] | None = None
    qualifying_exams: list[dict[str, Any]] | None = None
    merit_score: Decimal | None = None
    status: str
    entry_type: str
    source: str
    remarks: str | None = None
    submitted_at: datetime | None = None
    admitted_student_id: uuid.UUID | None = None
    preferences: list[PreferenceOut] = Field(default_factory=list)
    documents: list[ApplicantDocumentOut] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    payments: dict[str, Any] = Field(default_factory=dict)
    allotment: "AllotmentResponse | None" = None
    allowed_transitions: list[str] = Field(default_factory=list)
    version: int
    created_at: datetime


class ApplicantSelfResponse(ApplicantResponse):
    """The applicant's own application (never masked)."""


class TimelineEntry(BaseModel):
    at: datetime
    action: str
    status_from: str | None = None
    status_to: str | None = None
    by: str | None = None
    remarks: str | None = None


class DocumentVerifyRequest(_Strict):
    status: Literal["verified", "rejected", "resubmit"]
    remarks: str | None = Field(default=None, max_length=1000)


class ApplicantStatusChange(_Strict):
    status: ApplicantStatus
    reason: str = Field(min_length=3, max_length=1000)


class PaymentResult(BaseModel):
    purpose: Literal["application", "admission"]
    ref: str
    amount_paise: int
    status: str
    provider: str = "mock"
    paid_at: datetime | None = None


# ---- merit -------------------------------------------------------------------------------------------------------------
class MeritGenerateRequest(_Strict):
    name: str = Field(min_length=3, max_length=160)
    program_ids: list[uuid.UUID] | None = None
    quota: str | None = Field(default=None, max_length=30)
    category: str | None = Field(default=None, max_length=20)


class MeritListResponse(ORMModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    program_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    name: str
    quota: str | None = None
    category: str | None = None
    formula_snapshot: dict[str, Any] | None = None
    status: str
    generated_at: datetime | None = None
    published_at: datetime | None = None
    job_id: uuid.UUID | None = None
    created_at: datetime
    entries_count: int = 0


class MeritEntry(BaseModel):
    rank: int
    category_rank: int | None = None
    score: Decimal | None = None
    applicant_id: uuid.UUID
    application_number: str
    name: str
    category: str | None = None
    is_pwd: bool = False
    tie_break: dict[str, Any] | None = None


class MeritListDetail(MeritListResponse):
    entries: list[MeritEntry] = Field(default_factory=list)


class PublicMeritEntry(BaseModel):
    rank: int
    application_number: str


class PublicMeritList(BaseModel):
    name: str
    cycle: str
    published_at: datetime | None = None
    entries: list[PublicMeritEntry]


# ---- counselling -------------------------------------------------------------------------------------------------------
class RoundCreate(_Strict):
    round_number: int = Field(ge=1, le=20)
    name: str | None = Field(default=None, max_length=80)
    choice_filling_start: datetime | None = None
    choice_filling_end: datetime | None = None
    allotment_at: datetime | None = None
    reporting_deadline: datetime | None = None
    is_final: bool = False


class RoundUpdate(_Strict):
    name: str | None = Field(default=None, max_length=80)
    choice_filling_start: datetime | None = None
    choice_filling_end: datetime | None = None
    allotment_at: datetime | None = None
    reporting_deadline: datetime | None = None
    is_final: bool | None = None


class RoundStatusChange(_Strict):
    status: RoundStatus


class RoundResponse(ORMModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    round_number: int
    name: str | None = None
    choice_filling_start: datetime | None = None
    choice_filling_end: datetime | None = None
    allotment_at: datetime | None = None
    reporting_deadline: datetime | None = None
    status: str
    is_final: bool = False
    allotments_count: int = 0


class SummaryRow(BaseModel):
    program_id: uuid.UUID
    program_code: str | None = None
    college_id: uuid.UUID
    quota: str
    category: str
    seats: int
    filled: int
    allotted_now: int = 0


class Conversion(BaseModel):
    program_id: uuid.UUID
    program_code: str | None = None
    quota: str
    from_category: str
    to_category: str
    seats: int


class AllotmentPreviewRow(BaseModel):
    application_number: str
    applicant_id: uuid.UUID
    program_code: str | None = None
    program_id: uuid.UUID
    quota: str
    category: str
    priority: int
    kind: Literal["new", "upgrade"] = "new"


class AllotmentSummary(BaseModel):
    round_id: uuid.UUID
    round_number: int
    dry_run: bool
    is_final: bool = False
    considered: int = 0
    allotted: int = 0
    upgraded: int = 0
    retained: int = 0
    unallotted: int = 0
    rows: list[SummaryRow] = Field(default_factory=list)
    conversions: list[Conversion] = Field(default_factory=list)
    allotments: list[AllotmentPreviewRow] = Field(default_factory=list)
    job_id: uuid.UUID | None = None


class AllotmentResponse(BaseModel):
    id: uuid.UUID
    round_id: uuid.UUID
    round_number: int | None = None
    applicant_id: uuid.UUID
    application_number: str | None = None
    applicant_name: str | None = None
    program_id: uuid.UUID
    program_code: str | None = None
    program_name: str | None = None
    college_id: uuid.UUID
    quota: str
    category: str
    priority: int | None = None
    status: str
    admission_fee_paise: int | None = None
    accepted_at: datetime | None = None
    reporting_deadline: datetime | None = None
    payment: dict[str, Any] | None = None
    created_at: datetime


class AllotmentDecision(_Strict):
    action: AllotmentAction


# ---- offers / admit ------------------------------------------------------------------------------------------------------
class OfferCreate(_Strict):
    offer_type: OfferType = OfferType.PROVISIONAL
    program_id: uuid.UUID | None = Field(default=None, description="default: the held allotment's programme")
    valid_until: date | None = None
    conditions: dict[str, Any] | None = None


class OfferResponse(ORMModel):
    id: uuid.UUID
    applicant_id: uuid.UUID
    application_number: str | None = None
    applicant_name: str | None = None
    program_id: uuid.UUID
    program_code: str | None = None
    college_id: uuid.UUID
    offer_type: str
    valid_until: date | None = None
    conditions: dict[str, Any] | None = None
    letter_url: str | None = None
    letter_html: str | None = None
    status: str
    created_at: datetime


class AdmitRequest(_Strict):
    section_id: uuid.UUID | None = None
    registration_number: str | None = Field(default=None, max_length=30, pattern=r"^[A-Za-z0-9/-]+$")


class AdmitResult(BaseModel):
    student_id: uuid.UUID
    registration_number: str
    username: str | None = None
    temp_password: str | None = Field(default=None, description="shown once")
    applicant: ApplicantResponse


# ---- import / withdrawal ---------------------------------------------------------------------------------------------------
class ImportRequest(_Strict):
    """Mapping JSON for the counselling CSV: ``{"application_number": "Roll No", "first_name": "Name", ...}``."""

    mapping: dict[str, str] | None = None
    dry_run: bool = True


class ImportFailure(BaseModel):
    row: int
    error: str


class ImportResult(BaseModel):
    dry_run: bool
    total: int
    succeeded: int
    allotted: int = 0
    failed: list[ImportFailure] = Field(default_factory=list)
    job_id: uuid.UUID | None = None


class WithdrawalRequest(_Strict):
    reason: str = Field(min_length=3, max_length=1000)


class RefundOut(BaseModel):
    amount_paise: int
    paid_paise: int
    policy: str
    status: str
    workflow_instance_id: uuid.UUID | None = None


class WithdrawalResult(BaseModel):
    applicant: ApplicantResponse
    refund: RefundOut | None = None


# ---- enquiries --------------------------------------------------------------------------------------------------------------
class EnquiryCreate(_Strict):
    name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, pattern=PHONE)
    email: EmailStr | None = None
    source: EnquirySource = EnquirySource.WALK_IN
    college_id: uuid.UUID | None = None
    program_interest: list[str] | None = Field(default=None, description="programme codes / ids")
    follow_up_on: date | None = None
    note: str | None = Field(default=None, max_length=2000)
    assigned_to: uuid.UUID | None = None


class EnquiryUpdate(_Strict):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = Field(default=None, pattern=PHONE)
    email: EmailStr | None = None
    stage: EnquiryStage | None = None
    follow_up_on: date | None = None
    program_interest: list[str] | None = None
    note: str | None = Field(default=None, max_length=2000, description="appended to the notes log")


class EnquiryAssign(_Strict):
    user_id: uuid.UUID


class EnquiryConvert(_Strict):
    applicant_id: uuid.UUID | None = Field(default=None, description="link an existing applicant")
    application_number: str | None = Field(default=None, max_length=30)


class EnquiryResponse(BaseModel):
    id: uuid.UUID
    college_id: uuid.UUID | None = None
    source: str
    name: str
    phone: MaskedPhone = None
    email: MaskedEmail = None
    program_interest: list[str] | None = None
    stage: str
    assigned_to: uuid.UUID | None = None
    assigned_name: str | None = None
    follow_up_on: date | None = None
    notes: list[dict[str, Any]] = Field(default_factory=list)
    applicant_id: uuid.UUID | None = None
    application_number: str | None = None
    created_at: datetime
    updated_at: datetime


class EnquiryStats(BaseModel):
    total: int
    by_stage: dict[str, int]
    by_source: dict[str, int]
    funnel: list[dict[str, Any]]


class PublicEnquiryCreate(_Strict):
    institution: str | None = Field(default=None, max_length=60, description="institution slug")
    name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, pattern=PHONE)
    email: EmailStr | None = None
    message: str | None = Field(default=None, max_length=2000)
    program_interest: list[str] | None = None
    source_page: str | None = Field(default=None, max_length=200)
    captcha_token: str | None = None


class DevPayRequest(_Strict):
    status: Literal["paid", "failed"] = "paid"


PublicApplicationCreate.model_rebuild()
ApplicantResponse.model_rebuild()
ApplicantSelfResponse.model_rebuild()
