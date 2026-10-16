"""Student, guardian, document, undertaking, enrolment, hold, transfer and credit-transfer schemas — Prompts/07 §07.4.

PII (Aadhaar, bank details, phone, e-mail, guardian contacts) is declared through the ``Masked*`` annotated types:
``mask_pii(obj, principal, "students")`` masks them unless the reader holds ``students:view_pii`` (a student reading
the own record sees it unmasked). Writing PII needs ``students:manage``. Request bodies forbid unknown keys, so a
student sending ``{first_name}`` to ``PUT /students/me`` gets ``422`` (not self-editable).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.authz.masking import Masked, MaskedAmount, MaskedEmail, MaskedPhone, MaskedSecret
from app.enums.students import (
    CreditTransferSource,
    EntryType,
    Gender,
    GuardianRelation,
    HoldType,
    StudentStatus,
    TransferType,
    UndertakingType,
)
from app.schemas.common import ORMModel

PHONE = r"^\+?[0-9 -]{8,20}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- guardians ------------------------------------------------------------------------------------------------------
class GuardianIn(_Strict):
    relation: GuardianRelation
    name: str = Field(min_length=2, max_length=200)
    phone: str | None = Field(default=None, pattern=PHONE)
    email: EmailStr | None = None
    occupation: str | None = Field(default=None, max_length=100)
    annual_income_paise: int | None = Field(default=None, ge=0)
    address: dict[str, Any] | None = None
    is_primary: bool = False
    portal_access: bool = True
    create_portal_user: bool = Field(
        default=True,
        description="create (or reuse by phone/e-mail) a parent-portal user when students.guardians_portal",
    )


class GuardianUpdate(_Strict):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    phone: str | None = Field(default=None, pattern=PHONE)
    email: EmailStr | None = None
    occupation: str | None = Field(default=None, max_length=100)
    annual_income_paise: int | None = Field(default=None, ge=0)
    address: dict[str, Any] | None = None
    is_primary: bool | None = None
    portal_access: bool | None = None


class GuardianOut(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    user_id: uuid.UUID | None = None
    username: str | None = None
    relation: str
    name: str
    phone: MaskedPhone = None
    email: MaskedEmail = None
    occupation: str | None = None
    annual_income_paise: MaskedAmount = None
    address: dict[str, Any] | None = None
    is_primary: bool
    portal_access: bool
    created_at: datetime | None = None


class GuardianPortalConsentUpdate(_Strict):
    guardian_portal_consent: bool


# ---- student master ---------------------------------------------------------------------------------------------------
class StudentBankDetails(_Strict):
    account_no: str = Field(min_length=6, max_length=20, pattern=r"^[0-9]+$")
    ifsc: str = Field(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")
    bank: str | None = Field(default=None, max_length=120)
    branch: str | None = Field(default=None, max_length=120)


class EmergencyContact(_Strict):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(pattern=PHONE)
    relation: str | None = Field(default=None, max_length=40)


class _StudentPersonal(_Strict):
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    blood_group: str | None = Field(default=None, pattern=r"^(A|B|AB|O)[+-]$")
    category: str | None = Field(default=None, max_length=20, description="pack category code (IN: GEN, EWS, OBC-NCL…)")
    sub_category: str | None = Field(default=None, max_length=40)
    is_pwd: bool = False
    pwd_pct: int | None = Field(default=None, ge=0, le=100)
    pwd_type: str | None = Field(default=None, max_length=60)
    is_minority: bool = False
    minority_type: str | None = Field(default=None, max_length=40)
    religion: str | None = Field(default=None, max_length=40)
    nationality: str = Field(default="Indian", max_length=60)
    mother_tongue: str | None = Field(default=None, max_length=40)
    domicile_state: str | None = Field(default=None, max_length=60)
    phone: str | None = Field(default=None, pattern=PHONE)
    email: EmailStr | None = None
    permanent_address: dict[str, Any] | None = None
    current_address: dict[str, Any] | None = None
    emergency_contact: EmergencyContact | None = None
    aadhaar: str | None = Field(default=None, description="12 digits (Verhoeff check in the IN pack); stored encrypted")
    apaar_id: str | None = Field(default=None, max_length=20)
    abc_id: str | None = Field(default=None, max_length=20)
    bank_details: StudentBankDetails | None = None
    is_international: bool = False
    passport: dict[str, Any] | None = None
    visa: dict[str, Any] | None = None
    frro: dict[str, Any] | None = None


class StudentCreate(_StudentPersonal):
    """``student_service.create`` input — the registrar's wizard, bulk import and (Phase 08) admissions."""

    first_name: str = Field(min_length=1, max_length=100)
    dob: date
    gender: Gender
    # academic placement: the batch is created when missing (college / programme / admission year / entry type)
    program_id: uuid.UUID
    batch_id: uuid.UUID | None = None
    admission_year: int | None = Field(default=None, ge=1990, le=2100)
    program_regulation_id: uuid.UUID | None = Field(
        default=None, description="default: the batch's / active regulation"
    )
    section_id: uuid.UUID | None = None
    section: str | None = Field(default=None, max_length=10, description="section name when section_id is not given")
    entry_type: EntryType = EntryType.REGULAR
    entry_term_number: int | None = Field(default=None, ge=1, le=20)
    roll_number: str | None = Field(default=None, max_length=20)
    specialization: str | None = Field(default=None, max_length=120)
    minor_program_id: uuid.UUID | None = None
    is_honours: bool = False
    admission_date: date | None = None
    admission_mode: str | None = Field(default=None, max_length=30)
    admission_quota: str | None = Field(default=None, max_length=30)
    registration_number: str | None = Field(
        default=None, max_length=30, pattern=r"^[A-Za-z0-9/-]+$", description="manual (affiliating university) — unique"
    )
    enrolment_number: str | None = Field(default=None, max_length=30)
    status: Literal["provisional", "admitted", "active"] = "admitted"
    guardians: list[GuardianIn] = Field(default_factory=list, max_length=6)
    create_user: bool = True


class StudentUpdate(_Strict):
    """Registrar edits (optimistic ``version``); PII needs ``students:manage``."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    dob: date | None = None
    gender: Gender | None = None
    blood_group: str | None = Field(default=None, pattern=r"^(A|B|AB|O)[+-]$")
    category: str | None = Field(default=None, max_length=20)
    sub_category: str | None = Field(default=None, max_length=40)
    is_pwd: bool | None = None
    pwd_pct: int | None = Field(default=None, ge=0, le=100)
    pwd_type: str | None = Field(default=None, max_length=60)
    is_minority: bool | None = None
    minority_type: str | None = Field(default=None, max_length=40)
    religion: str | None = Field(default=None, max_length=40)
    nationality: str | None = Field(default=None, max_length=60)
    mother_tongue: str | None = Field(default=None, max_length=40)
    domicile_state: str | None = Field(default=None, max_length=60)
    phone: str | None = Field(default=None, pattern=PHONE)
    email: EmailStr | None = None
    permanent_address: dict[str, Any] | None = None
    current_address: dict[str, Any] | None = None
    emergency_contact: EmergencyContact | None = None
    aadhaar: str | None = None
    apaar_id: str | None = Field(default=None, max_length=20)
    abc_id: str | None = Field(default=None, max_length=20)
    bank_details: StudentBankDetails | None = None
    is_international: bool | None = None
    passport: dict[str, Any] | None = None
    visa: dict[str, Any] | None = None
    frro: dict[str, Any] | None = None
    enrolment_number: str | None = Field(default=None, max_length=30)
    admission_quota: str | None = Field(default=None, max_length=30)
    admission_mode: str | None = Field(default=None, max_length=30)
    admission_date: date | None = None
    version: int | None = None


class StudentSelfUpdate(_Strict):
    """What a student may change on the own profile (setting ``students.self_service_fields``)."""

    phone: str | None = Field(default=None, pattern=PHONE)
    email: EmailStr | None = None
    current_address: dict[str, Any] | None = None
    emergency_contact: EmergencyContact | None = None


class StatusChangeRequest(_Strict):
    status: StudentStatus
    reason: str = Field(min_length=3, max_length=1000)
    effective_date: date | None = None


class StudentListItem(ORMModel):
    id: uuid.UUID
    registration_number: str
    first_name: str
    last_name: str | None = None
    full_name: str = ""
    college_id: uuid.UUID
    college_code: str | None = None
    department_code: str | None = None
    program_id: uuid.UUID | None = None
    program_code: str | None = None
    batch_id: uuid.UUID | None = None
    batch_code: str | None = None
    section_name: str | None = None
    term_number: int | None = None
    enrollment_status: str | None = None
    status: str
    academic_standing: str | None = None
    open_holds: int = 0
    category: str | None = None
    gender: str | None = None
    phone: MaskedPhone = None
    email: MaskedEmail = None
    photo_url: str | None = None
    apaar_id: Masked = None
    is_self: bool = False
    is_ward: bool = False


class StudentResponse(StudentListItem):
    pass


class EnrollmentResponse(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    college_id: uuid.UUID
    program_id: uuid.UUID
    program_code: str | None = None
    program_name: str | None = None
    total_terms: int | None = None
    batch_id: uuid.UUID
    batch_code: str | None = None
    program_regulation_id: uuid.UUID
    regulation_code: str | None = None
    department_id: uuid.UUID
    department_code: str | None = None
    admission_date: date
    entry_type: str
    entry_term_number: int
    specialization: str | None = None
    minor_program_id: uuid.UUID | None = None
    is_honours: bool
    expected_exit_term: int | None = None
    status: str
    exit_award: str | None = None
    exit_date: date | None = None
    credits_earned: Decimal
    cgpa: Decimal | None = None
    academic_standing: str
    current_term_number: int | None = None
    section_id: uuid.UUID | None = None
    section_name: str | None = None
    open_holds: int = 0
    version: int


class TermRecordResponse(ORMModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    term_id: uuid.UUID
    term_name: str | None = None
    academic_year_name: str | None = None
    term_number: int
    section_id: uuid.UUID | None = None
    section_name: str | None = None
    roll_number: str | None = None
    status: str
    credits_registered: Decimal
    credits_earned: Decimal
    sgpa: Decimal | None = None
    cgpa: Decimal | None = None
    attendance_pct: Decimal | None = None
    result_status: str | None = None
    created_at: datetime | None = None


class HoldResponse(ORMModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_id: uuid.UUID | None = None
    registration_number: str | None = None
    student_name: str | None = None
    hold_type: str
    reason: str
    placed_by: uuid.UUID
    placed_by_name: str | None = None
    placed_at: datetime
    released_by: uuid.UUID | None = None
    released_by_name: str | None = None
    released_at: datetime | None = None
    release_reason: str | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    is_open: bool = True
    can_release: bool = False


class DocumentOut(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    doc_type: str
    file_url: str
    verified_by: uuid.UUID | None = None
    verified_at: datetime | None = None
    expires_on: date | None = None
    remarks: str | None = None
    uploaded_at: datetime
    is_verified: bool = False
    is_expired: bool = False


class DocumentVerifyRequest(_Strict):
    remarks: str | None = Field(default=None, max_length=1000)


class UndertakingAccept(_Strict):
    undertaking_type: UndertakingType
    template_id: uuid.UUID | None = None
    signature_data_url: str | None = Field(
        default=None, max_length=300_000, description="optional drawn signature (data:image/png;base64,…)"
    )

    @field_validator("signature_data_url")
    @classmethod
    def _png(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("data:image/png;base64,", "data:image/jpeg;base64,")):
            raise ValueError("signature must be a PNG/JPEG data URL")
        return v


class UndertakingOut(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    undertaking_type: str
    template_id: uuid.UUID | None = None
    accepted_at: datetime
    ip: str | None = None
    user_agent: str | None = None
    signature_url: str | None = None


class UndertakingStatus(BaseModel):
    undertaking_type: str
    name: str
    template_id: uuid.UUID | None = None
    version: str | None = None
    required: bool = False
    accepted: bool = False
    accepted_at: datetime | None = None
    body: str | None = Field(default=None, description="rendered text (pending items)")


class StandingHistoryItem(BaseModel):
    at: datetime
    from_standing: str | None = None
    to_standing: str
    cgpa: float | None = None
    sgpa: float | None = None
    term_number: int | None = None
    rule: dict[str, Any] | None = None
    by: str | None = None


class StandingResponse(BaseModel):
    enrollment_id: uuid.UUID
    standing: str
    cgpa: Decimal | None = None
    rules: list[dict[str, Any]] = Field(default_factory=list)
    history: list[StandingHistoryItem] = Field(default_factory=list)


class StudentDetailResponse(StudentResponse):
    middle_name: str | None = None
    dob: date | None = None
    blood_group: str | None = None
    sub_category: str | None = None
    is_pwd: bool = False
    pwd_pct: int | None = None
    pwd_type: str | None = None
    is_minority: bool = False
    minority_type: str | None = None
    religion: str | None = None
    nationality: str | None = None
    mother_tongue: str | None = None
    domicile_state: str | None = None
    permanent_address: dict[str, Any] | None = None
    current_address: dict[str, Any] | None = None
    emergency_contact: dict[str, Any] | None = None
    aadhaar: Masked = None
    bank_details: MaskedSecret = None
    abc_id: Masked = None
    enrolment_number: str | None = None
    is_international: bool = False
    passport: dict[str, Any] | None = None
    visa: dict[str, Any] | None = None
    frro: dict[str, Any] | None = None
    guardian_portal_consent: bool = True
    admission_quota: str | None = None
    admission_mode: str | None = None
    admission_date: date | None = None
    user_id: uuid.UUID | None = None
    username: str | None = None
    is_adult: bool = True
    version: int = 1
    created_at: datetime | None = None
    enrollment: EnrollmentResponse | None = None
    current_term: TermRecordResponse | None = None
    holds: list[HoldResponse] = Field(default_factory=list)
    guardians: list[GuardianOut] = Field(default_factory=list)
    documents: list[DocumentOut] = Field(default_factory=list)
    undertakings: list[UndertakingStatus] = Field(default_factory=list)
    allowed_transitions: list[str] = Field(default_factory=list)


class StudentCreateResult(BaseModel):
    student: StudentDetailResponse
    username: str | None = None
    temp_password: str | None = Field(default=None, description="shown once; the student changes it on sign-in")
    guardian_accounts: list[dict[str, Any]] = Field(
        default_factory=list, description="[{guardian_id, username, temp_password|null, reused}] — passwords shown once"
    )


# ---- enrolment operations --------------------------------------------------------------------------------------------
class PromoteBatchRequest(_Strict):
    batch_id: uuid.UUID | None = Field(default=None, description="optional — must match the path")
    to_term_number: int | None = Field(default=None, ge=2, le=20, description="default: current term + 1")
    apply_detention_rule: bool = True
    dry_run: bool = False


class PromotionRow(BaseModel):
    student_id: uuid.UUID
    enrollment_id: uuid.UUID
    registration_number: str
    name: str
    section_name: str | None = None
    backlogs: int = 0


class PromotionPreview(BaseModel):
    batch_id: uuid.UUID
    batch_code: str
    from_term_number: int
    to_term_number: int
    from_term: dict[str, Any] | None = None
    to_term: dict[str, Any] | None = None
    max_backlogs: int
    dry_run: bool = True
    promoted: list[PromotionRow] = Field(default_factory=list)
    detained: list[PromotionRow] = Field(default_factory=list)
    on_break: list[PromotionRow] = Field(default_factory=list)
    already_promoted: int = 0
    blocking: str | None = None
    job_id: uuid.UUID | None = None


class SectionChange(_Strict):
    section_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=500)


class RegulationChange(_Strict):
    program_regulation_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=1000)


class ExitRequest(_Strict):
    exit_award: str = Field(min_length=2, max_length=30)
    exit_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ReentryRequest(_Strict):
    program_id: uuid.UUID
    batch_id: uuid.UUID
    entry_term_number: int = Field(ge=1, le=20)
    section_id: uuid.UUID | None = None
    carried_credit_transfer_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


# ---- holds ----------------------------------------------------------------------------------------------------------
class HoldCreate(_Strict):
    hold_type: HoldType
    reason: str = Field(min_length=3, max_length=1000)
    source_type: str | None = Field(default=None, max_length=40)
    source_id: uuid.UUID | None = None
    enrollment_id: uuid.UUID | None = Field(default=None, description="default: the open enrolment")


class HoldReleaseRequest(_Strict):
    reason: str = Field(min_length=3, max_length=1000)


# ---- transfers ------------------------------------------------------------------------------------------------------
class TransferCreate(_Strict):
    transfer_type: TransferType
    to_ref: dict[str, Any] | None = Field(default=None, description="destination: institution / college / programme")
    reason: str | None = Field(default=None, max_length=2000)
    effective_date: date | None = None


class TransferDecision(_Strict):
    comment: str | None = Field(default=None, max_length=1000)


class TransferComplete(_Strict):
    effective_date: date | None = None


class TransferResponse(ORMModel):
    id: uuid.UUID
    student_id: uuid.UUID
    registration_number: str | None = None
    student_name: str | None = None
    transfer_type: str
    from_ref: dict[str, Any] | None = None
    to_ref: dict[str, Any] | None = None
    migration_certificate_no: str | None = None
    tc_no: str | None = None
    reason: str | None = None
    requested_at: datetime
    approved_by: uuid.UUID | None = None
    effective_date: date | None = None
    status: str
    workflow_instance_id: uuid.UUID | None = None
    workflow_status: str | None = None
    current_step: int | None = None
    can_act: bool = False
    created_at: datetime | None = None


# ---- credit transfers -----------------------------------------------------------------------------------------------
class CreditTransferCreate(_Strict):
    student_id: uuid.UUID | None = Field(default=None, description="office submission on behalf of a student")
    source: CreditTransferSource
    source_course_code: str | None = Field(default=None, max_length=40)
    source_title: str = Field(min_length=2, max_length=200)
    source_institution: str | None = Field(default=None, max_length=200)
    credits: Decimal = Field(gt=0, le=30)
    source_grade: str | None = Field(default=None, max_length=10)
    source_score_pct: Decimal | None = Field(default=None, ge=0, le=100)
    term_id: uuid.UUID | None = None
    certificate_url: str | None = Field(default=None, max_length=2000)
    abc_credit_ref: str | None = Field(default=None, max_length=60)
    elective_basket_id: uuid.UUID | None = None

    @field_validator("source")
    @classmethod
    def _not_internal(cls, v: CreditTransferSource) -> CreditTransferSource:
        if v == CreditTransferSource.INTERNAL_PRIOR:
            raise ValueError("internal_prior transfers are created by re-entry / regulation change")
        return v


class CreditTransferDecision(_Strict):
    equivalent_course_id: uuid.UUID | None = None
    elective_basket_id: uuid.UUID | None = None
    comment: str | None = Field(default=None, max_length=1000)


class CreditTransferResponse(ORMModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_id: uuid.UUID | None = None
    registration_number: str | None = None
    student_name: str | None = None
    department_code: str | None = None
    term_id: uuid.UUID | None = None
    source: str
    source_course_code: str | None = None
    source_title: str
    source_institution: str | None = None
    credits: Decimal
    source_grade: str | None = None
    source_score_pct: Decimal | None = None
    letter_grade: str | None = None
    equivalent_course_id: uuid.UUID | None = None
    equivalent_course: str | None = None
    elective_basket_id: uuid.UUID | None = None
    certificate_url: str | None = None
    abc_credit_ref: str | None = None
    status: str
    approved_by: uuid.UUID | None = None
    approved_at: datetime | None = None
    result_id: uuid.UUID | None = None
    workflow_instance_id: uuid.UUID | None = None
    workflow_status: str | None = None
    current_step: int | None = None
    can_act: bool = False
    created_at: datetime | None = None


# ---- bulk import / export / ID cards / stats / portals --------------------------------------------------------------
class BulkImportFailure(BaseModel):
    row: int
    reason: str
    field: str | None = None


class BulkImportResult(BaseModel):
    dry_run: bool
    total: int
    succeeded: int
    failed: list[BulkImportFailure] = Field(default_factory=list)
    created: list[dict[str, Any]] = Field(default_factory=list, description="[{row, student_id, registration_number}]")
    job_id: uuid.UUID | None = None


class IdCardRequest(_Strict):
    student_ids: list[uuid.UUID] = Field(min_length=1, max_length=2000)


class IdCardResponse(BaseModel):
    student_id: uuid.UUID
    registration_number: str
    name: str
    program: str | None = None
    batch: str | None = None
    college: str | None = None
    institution: str | None = None
    blood_group: str | None = None
    photo_url: str | None = None
    emergency_phone: str | None = None
    valid_until: date | None = None
    token: str
    verify_url: str


class StatBucket(BaseModel):
    key: str
    label: str
    count: int


class StudentStats(BaseModel):
    total: int
    by_status: list[StatBucket] = Field(default_factory=list)
    by_program: list[StatBucket] = Field(default_factory=list)
    by_batch: list[StatBucket] = Field(default_factory=list)
    by_category: list[StatBucket] = Field(default_factory=list)
    by_gender: list[StatBucket] = Field(default_factory=list)
    by_standing: list[StatBucket] = Field(default_factory=list)


class QuickLink(BaseModel):
    key: str
    label: str
    route: str
    feature: str | None = None


class StudentDashboard(BaseModel):
    student: StudentDetailResponse
    enrollment: EnrollmentResponse | None = None
    current_term: TermRecordResponse | None = None
    holds: list[HoldResponse] = Field(default_factory=list)
    undertakings_pending: list[UndertakingStatus] = Field(default_factory=list)
    standing: str | None = None
    credit_transfers_pending: int = 0
    quick_links: list[QuickLink] = Field(default_factory=list)
    # Phase 09: confirmed courses of the current term (parents read their ward's confirmed items)
    confirmed_courses: list[dict[str, Any]] = Field(default_factory=list)


class WardSummary(BaseModel):
    student_id: uuid.UUID
    registration_number: str
    name: str
    relation: str | None = None
    program_code: str | None = None
    batch_code: str | None = None
    term_number: int | None = None
    status: str
    academic_standing: str | None = None
    open_holds: int = 0
    photo_url: str | None = None


class VerifyResponse(BaseModel):
    valid: bool
    document_type: str
    holder_name: str | None = None
    registration_number: str | None = None
    program: str | None = None
    status: str | None = None
    institution: str | None = None
    college: str | None = None
    valid_until: date | None = None
    message: str | None = None


class DevTermResult(_Strict):
    term_number: int = Field(ge=1, le=20)
    sgpa: Decimal | None = Field(default=None, ge=0, le=10)
    cgpa: Decimal | None = Field(default=None, ge=0, le=10)
    credits_earned: Decimal | None = Field(default=None, ge=0, le=60)


class DevTermResults(_Strict):
    """``POST /_dev/students/{id}/term-results`` (dev fixture until Phase 15 publishes results)."""

    terms: list[DevTermResult] = Field(min_length=1, max_length=20)
    credits_earned: Decimal | None = Field(default=None, ge=0, le=400)
