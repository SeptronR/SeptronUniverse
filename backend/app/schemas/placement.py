"""Placement, internships & training schemas — Prompts/28 §28.4 (OpenAPI names prefixed ``Plc`` / ``Intern`` /
``Trn`` / ``Recruiter``). Inputs forbid unknown fields, so a profile PUT carrying ``cgpa`` is a 422 (academics are
read-only and computed)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


TierLit = Literal["dream", "super_dream", "core", "mass"]
JobTypeLit = Literal["full_time", "internship", "intern_ppo", "part_time"]
ModeLit = Literal["on_campus", "off_campus", "virtual", "pooled"]
RoundTypeLit = Literal["pre_placement_talk", "aptitude", "coding", "gd", "technical", "hr", "final"]
OptOutLit = Literal["higher_studies", "entrepreneurship", "family_business", "govt_exams", "other"]
TrainingTypeLit = Literal["aptitude", "soft_skills", "technical", "mock_interview"]


# ---- companies ------------------------------------------------------------------------------------------------------
class PlcContact(BaseModel):
    name: str = Field(max_length=160)
    designation: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=20)


class PlcCompanyIn(_Strict):
    name: str = Field(min_length=1, max_length=200)
    sector: str | None = Field(None, max_length=80)
    website: str | None = Field(None, max_length=500)
    hq_city: str | None = Field(None, max_length=80)
    tier: TierLit | None = None
    contacts: list[PlcContact] = Field(default_factory=list)
    notes: str | None = Field(None, max_length=4000)
    logo_url: str | None = Field(None, max_length=1000)
    mou_id: uuid.UUID | None = None
    is_active: bool = True


class PlcCompanyOut(BaseModel):
    id: uuid.UUID
    name: str
    sector: str | None = None
    website: str | None = None
    hq_city: str | None = None
    tier: str | None = None
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    recruiter_user_ids: list[str] = Field(default_factory=list)
    is_blacklisted: bool = False
    notes: str | None = None
    logo_url: str | None = None
    is_active: bool = True
    drives: int = 0
    hires: int = 0
    feedback_avg: float | None = None
    history: list[dict[str, Any]] | None = None


class PlcCompanyBlacklist(_Strict):
    blacklisted: bool = True
    reason: str = Field(min_length=3, max_length=2000)


class PlcRecruiterInvite(_Strict):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(None, max_length=20)


class PlcRecruiterInviteOut(BaseModel):
    user_id: uuid.UUID
    username: str
    company_id: uuid.UUID
    created: bool


# ---- policies -------------------------------------------------------------------------------------------------------
class PlcPolicyIn(_Strict):
    batch_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    max_offers: int = Field(1, ge=1, le=10)
    dream_ctc_threshold_paise: int | None = Field(None, ge=0)
    allow_upgrade_if_dream: bool = True
    opt_out_allowed: bool = True
    rules: dict[str, Any] | None = None


class PlcPolicyOut(BaseModel):
    id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    max_offers: int = 1
    dream_ctc_threshold_paise: int | None = None
    allow_upgrade_if_dream: bool = True
    opt_out_allowed: bool = True
    rules: dict[str, Any] | None = None
    source: str = "policy"  # policy | program | batch | defaults


# ---- drives ---------------------------------------------------------------------------------------------------------
class PlcEligibilityRules(BaseModel):
    min_cgpa: float | None = Field(None, ge=0, le=10)
    max_active_backlogs: int | None = Field(None, ge=0)
    max_history_backlogs: int | None = Field(None, ge=0)
    programs: list[uuid.UUID] = Field(default_factory=list)
    batches: list[uuid.UUID] = Field(default_factory=list)
    min_10th_pct: float | None = Field(None, ge=0, le=100)
    min_12th_pct: float | None = Field(None, ge=0, le=100)
    max_gap_years: int | None = Field(None, ge=0)
    allowed_if_already_placed: bool | None = None
    min_attendance_pct: float | None = Field(None, ge=0, le=100)
    skills_any: list[str] = Field(default_factory=list)
    colleges: list[uuid.UUID] = Field(default_factory=list)  # pooled drives


class PlcDriveCreate(_Strict):
    company_id: uuid.UUID
    college_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    job_role: str | None = Field(None, max_length=120)
    job_type: JobTypeLit = "full_time"
    ctc_min_paise: int | None = Field(None, ge=0)
    ctc_max_paise: int | None = Field(None, ge=0)
    stipend_paise: int | None = Field(None, ge=0)
    locations: list[str] = Field(default_factory=list)
    bond: dict[str, Any] | None = None
    eligibility_rules: PlcEligibilityRules = Field(default_factory=PlcEligibilityRules)
    registration_deadline: datetime | None = None
    drive_on: date | None = None
    mode: ModeLit = "on_campus"
    jd_url: str | None = Field(None, max_length=1000)
    owner_staff_id: uuid.UUID | None = None


class PlcDriveUpdate(_Strict):
    title: str | None = Field(None, max_length=200)
    job_role: str | None = Field(None, max_length=120)
    job_type: JobTypeLit | None = None
    ctc_min_paise: int | None = Field(None, ge=0)
    ctc_max_paise: int | None = Field(None, ge=0)
    stipend_paise: int | None = Field(None, ge=0)
    locations: list[str] | None = None
    bond: dict[str, Any] | None = None
    eligibility_rules: PlcEligibilityRules | None = None
    registration_deadline: datetime | None = None
    drive_on: date | None = None
    mode: ModeLit | None = None
    jd_url: str | None = Field(None, max_length=1000)
    owner_staff_id: uuid.UUID | None = None


class PlcEligibilitySnapshot(BaseModel):
    is_eligible: bool = False
    cgpa: float | None = None
    active_backlogs: int = 0
    history_backlogs: int = 0
    pct_10: float | None = None
    pct_12: float | None = None
    pct_verified: bool = True
    gap_years: int | None = None
    placed_status: str = "unplaced"
    attendance_pct: float | None = None
    reasons: list[str] = Field(default_factory=list)
    evaluated_at: datetime | None = None


class PlcDriveOut(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str | None = None
    company_tier: str | None = None
    college_id: uuid.UUID | None = None
    title: str
    job_role: str | None = None
    job_type: str
    ctc_min_paise: int | None = None
    ctc_max_paise: int | None = None
    stipend_paise: int | None = None
    locations: list[str] = Field(default_factory=list)
    bond: dict[str, Any] | None = None
    eligibility_rules: dict[str, Any] = Field(default_factory=dict)
    registration_deadline: datetime | None = None
    drive_on: date | None = None
    mode: str
    status: str
    jd_url: str | None = None
    owner_staff_id: uuid.UUID | None = None
    applications: int = 0
    funnel: list[dict[str, Any]] | None = None
    my_eligibility: PlcEligibilitySnapshot | None = None
    my_application_id: uuid.UUID | None = None
    my_application_status: str | None = None
    created_at: datetime | None = None


class PlcDriveAction(_Strict):
    action: Literal["publish", "close", "start", "complete", "cancel"]
    reason: str | None = Field(None, max_length=2000)


class PlcEligibilityPreview(BaseModel):
    total: int = 0
    eligible_count: int = 0
    ineligible_by_reason: dict[str, int] = Field(default_factory=dict)
    sample: list[dict[str, Any]] = Field(default_factory=list)


# ---- applications ---------------------------------------------------------------------------------------------------
class PlcApplyRequest(_Strict):
    resume_url: str | None = Field(None, max_length=1000)


class PlcApplicationOut(BaseModel):
    id: uuid.UUID
    drive_id: uuid.UUID
    drive_title: str | None = None
    company_name: str | None = None
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    department_code: str | None = None
    eligibility_snapshot: dict[str, Any] | None = None
    is_eligible: bool = True
    override_reason: str | None = None
    resume_url: str | None = None
    status: str
    applied_at: datetime | None = None
    rounds: list[dict[str, Any]] = Field(default_factory=list)
    offer: dict[str, Any] | None = None


class PlcOverrideEligibility(_Strict):
    application_id: uuid.UUID | None = None
    drive_id: uuid.UUID | None = None
    enrollment_id: uuid.UUID | None = None
    reason: str = Field(min_length=5, max_length=2000)


class PlcShortlistRow(BaseModel):
    application_id: uuid.UUID | None = None
    registration_number: str | None = Field(None, max_length=30)


class PlcShortlistBulk(_Strict):
    rows: list[PlcShortlistRow] = Field(min_length=1, max_length=5000)


class PlcBulkReport(BaseModel):
    processed: int = 0
    succeeded: int = 0
    failed: list[dict[str, Any]] = Field(default_factory=list)
    blacklisted: list[str] = Field(default_factory=list)


# ---- rounds ---------------------------------------------------------------------------------------------------------
class PlcRoundIn(_Strict):
    round_no: int = Field(ge=1, le=20)
    name: str = Field(min_length=1, max_length=80)
    round_type: RoundTypeLit
    scheduled_at: datetime | None = None
    venue: str | None = Field(None, max_length=200)


class PlcRoundUpdate(_Strict):
    name: str | None = Field(None, max_length=80)
    round_type: RoundTypeLit | None = None
    scheduled_at: datetime | None = None
    venue: str | None = Field(None, max_length=200)


class PlcRoundOut(BaseModel):
    id: uuid.UUID
    drive_id: uuid.UUID
    round_no: int
    name: str
    round_type: str
    scheduled_at: datetime | None = None
    venue: str | None = None
    results: dict[str, int] = Field(default_factory=dict)


class PlcRoundResultRow(BaseModel):
    application_id: uuid.UUID | None = None
    registration_number: str | None = Field(None, max_length=30)
    status: Literal["cleared", "not_cleared", "absent", "pending"]
    score: Decimal | None = None
    remarks: str | None = Field(None, max_length=2000)


class PlcRoundResultsBulk(_Strict):
    rows: list[PlcRoundResultRow] = Field(min_length=1, max_length=5000)
    final: bool = False  # mark cleared candidates ``selected`` (also implied by the last / ``final`` round)


class PlcFunnel(BaseModel):
    drive_id: uuid.UUID
    applied: int = 0
    shortlisted: int = 0
    rounds: list[dict[str, Any]] = Field(default_factory=list)
    selected: int = 0
    offers: int = 0
    accepted: int = 0


# ---- offers ---------------------------------------------------------------------------------------------------------
class PlcOfferCreate(_Strict):
    application_id: uuid.UUID
    role: str | None = Field(None, max_length=120)
    ctc_paise: int = Field(ge=0)
    ctc_breakup: dict[str, Any] | None = None
    location: str | None = Field(None, max_length=120)
    offer_letter_url: str | None = Field(None, max_length=1000)
    offered_on: date | None = None
    joining_on: date | None = None
    is_ppo: bool = False


class PlcOfferOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    drive_id: uuid.UUID | None = None
    company_id: uuid.UUID
    company_name: str | None = None
    company_tier: str | None = None
    student_program_enrollment_id: uuid.UUID | None = None
    student_name: str | None = None
    registration_number: str | None = None
    role: str | None = None
    ctc_paise: int
    ctc_breakup: dict[str, Any] | None = None
    location: str | None = None
    offer_letter_url: str | None = None
    offered_on: date | None = None
    joining_on: date | None = None
    status: str
    is_ppo: bool = False
    is_dream: bool = False
    document_id: uuid.UUID | None = None
    policy_warning: str | None = None
    created_at: datetime | None = None


class PlcOfferDecision(_Strict):
    action: Literal["accept", "decline"]
    reason: str | None = Field(None, max_length=2000)


class PlcOfferStatusUpdate(_Strict):
    status: Literal["joined", "not_joined", "revoked"]
    reason: str | None = Field(None, max_length=2000)


class PlcPendingOffer(BaseModel):
    application_id: uuid.UUID
    drive_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    submitted_by: uuid.UUID | None = None
    submitted_at: str | None = None
    offer: dict[str, Any] = Field(default_factory=dict)


# ---- profiles -------------------------------------------------------------------------------------------------------
class PlcHigherStudies(BaseModel):
    exam: str | None = Field(None, max_length=60)
    score: str | None = Field(None, max_length=40)
    institution: str | None = Field(None, max_length=200)
    country: str | None = Field(None, max_length=80)
    program: str | None = Field(None, max_length=120)


class PlcProfileIn(_Strict):
    resume_json: dict[str, Any] | None = None
    resume_url: str | None = Field(None, max_length=1000)
    skills: list[str] | None = Field(None, max_length=100)
    consent_share_profile: bool | None = None
    pct_10: float | None = Field(None, ge=0, le=100)  # used only when no applicant record exists (flagged unverified)
    pct_12: float | None = Field(None, ge=0, le=100)
    year_12: int | None = Field(None, ge=1950, le=2100)


class PlcOptOut(_Strict):
    opt_out: bool = True
    reason: OptOutLit | None = None
    higher_studies: PlcHigherStudies | None = None


class PlcProfileOut(BaseModel):
    id: uuid.UUID | None = None
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    program_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    department_code: str | None = None
    email: str | None = None
    phone: str | None = None
    resume_url: str | None = None
    resume_json: dict[str, Any] | None = None
    skills: list[str] = Field(default_factory=list)
    is_opted_out: bool = False
    opt_out_reason: str | None = None
    higher_studies: dict[str, Any] | None = None
    placement_status: str = "unplaced"
    is_blacklisted: bool = False
    blacklist_reason: str | None = None
    blacklist_until: str | None = None
    consent_share_profile: bool = True
    academics: dict[str, Any] = Field(default_factory=dict)
    achievements: list[dict[str, Any]] = Field(default_factory=list)
    internships: list[dict[str, Any]] = Field(default_factory=list)
    training: dict[str, Any] = Field(default_factory=dict)
    completeness: int = 0


class PlcResumeRender(_Strict):
    template_key: Literal["resume_classic", "resume_modern", "resume_compact"] = "resume_classic"


class PlcBlacklistRequest(_Strict):
    enrollment_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=2000)
    until: date | None = None
    open_discipline_case: bool = False


class PlcBlacklistOut(BaseModel):
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    reason: str | None = None
    until: str | None = None
    source: str | None = None
    at: str | None = None


class PlcFeedbackIn(_Strict):
    ratings: dict[str, int] = Field(default_factory=dict)  # candidates / process / infrastructure / coordination 1-5
    remarks: str | None = Field(None, max_length=4000)


class PlcFeedbackOut(BaseModel):
    id: uuid.UUID
    drive_id: uuid.UUID
    drive_title: str | None = None
    ratings: dict[str, Any] = Field(default_factory=dict)
    remarks: str | None = None
    submitted_by: uuid.UUID | None = None
    submitted_at: datetime | None = None


# ---- internships ----------------------------------------------------------------------------------------------------
class InternshipIn(_Strict):
    enrollment_id: uuid.UUID | None = None  # officer records for a student; students omit it
    company_id: uuid.UUID | None = None
    company_name: str | None = Field(None, max_length=200)
    role: str | None = Field(None, max_length=120)
    from_on: date
    to_on: date | None = None
    stipend_paise: int | None = Field(None, ge=0)
    mentor: str | None = Field(None, max_length=160)
    credits_course_id: uuid.UUID | None = None
    status: Literal["planned", "ongoing", "completed", "cancelled"] = "ongoing"
    certificate_url: str | None = Field(None, max_length=1000)


class InternshipUpdate(_Strict):
    role: str | None = Field(None, max_length=120)
    to_on: date | None = None
    stipend_paise: int | None = Field(None, ge=0)
    mentor: str | None = Field(None, max_length=160)
    credits_course_id: uuid.UUID | None = None
    status: Literal["planned", "ongoing", "completed", "cancelled"] | None = None
    certificate_url: str | None = Field(None, max_length=1000)


class InternshipNocRequest(_Strict):
    addressed_to: str | None = Field(None, max_length=200)
    purpose: str | None = Field(None, max_length=500)


class InternshipEvaluation(_Strict):
    rubric_scores: dict[str, float] = Field(default_factory=dict)
    marks: Decimal = Field(ge=0)
    max_marks: Decimal = Field(Decimal(100), gt=0)
    remarks: str | None = Field(None, max_length=4000)
    certificate_url: str | None = Field(None, max_length=1000)


class InternshipOut(BaseModel):
    id: uuid.UUID
    student_program_enrollment_id: uuid.UUID
    student_name: str | None = None
    registration_number: str | None = None
    department_code: str | None = None
    company_id: uuid.UUID | None = None
    company_name: str | None = None
    role: str | None = None
    from_on: date
    to_on: date | None = None
    weeks: int | None = None
    stipend_paise: int | None = None
    mentor: str | None = None
    evaluation: dict[str, Any] | None = None
    certificate_url: str | None = None
    noc_document_id: uuid.UUID | None = None
    credits_course_id: uuid.UUID | None = None
    status: str
    created_at: datetime | None = None


# ---- training -------------------------------------------------------------------------------------------------------
class TrnSession(BaseModel):
    at: datetime
    topic: str = Field(max_length=200)


class TrnProgramIn(_Strict):
    training_type: TrainingTypeLit
    title: str = Field(min_length=1, max_length=200)
    trainer: str | None = Field(None, max_length=160)
    from_on: date | None = None
    to_on: date | None = None
    batches: list[uuid.UUID] = Field(default_factory=list)
    sessions: list[TrnSession] = Field(default_factory=list)
    vendor_cost_paise: int | None = Field(None, ge=0)


class TrnProgramUpdate(_Strict):
    title: str | None = Field(None, max_length=200)
    trainer: str | None = Field(None, max_length=160)
    from_on: date | None = None
    to_on: date | None = None
    batches: list[uuid.UUID] | None = None
    sessions: list[TrnSession] | None = None
    vendor_cost_paise: int | None = Field(None, ge=0)


class TrnProgramOut(BaseModel):
    id: uuid.UUID
    training_type: str
    title: str
    trainer: str | None = None
    from_on: date | None = None
    to_on: date | None = None
    batches: list[str] = Field(default_factory=list)
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    participants: int = 0
    avg_score: float | None = None
    vendor_cost_paise: int | None = None
    created_at: datetime | None = None


class TrnAttendanceRow(BaseModel):
    enrollment_id: uuid.UUID | None = None
    registration_number: str | None = Field(None, max_length=30)
    sessions_attended: int = Field(ge=0, le=500)


class TrnAttendanceBulk(_Strict):
    rows: list[TrnAttendanceRow] = Field(min_length=1, max_length=5000)


class TrnScoreRow(BaseModel):
    enrollment_id: uuid.UUID | None = None
    registration_number: str | None = Field(None, max_length=30)
    score: Decimal = Field(ge=0, le=1000)


class TrnScoresBulk(_Strict):
    rows: list[TrnScoreRow] = Field(min_length=1, max_length=5000)


class TrnMyRow(BaseModel):
    program_id: uuid.UUID
    title: str
    training_type: str
    from_on: date | None = None
    to_on: date | None = None
    sessions: list[dict[str, Any]] = Field(default_factory=list)
    sessions_attended: int = 0
    score: float | None = None


# ---- stats ----------------------------------------------------------------------------------------------------------
class PlcStats(BaseModel):
    batch_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    college_id: uuid.UUID | None = None
    eligible: int = 0
    opted_out: int = 0
    placed: int = 0
    placed_pct: float = 0.0
    multiple: int = 0
    offers: int = 0
    ppo: int = 0
    median_ctc_paise: int | None = None
    avg_ctc_paise: int | None = None
    highest_ctc_paise: int | None = None
    higher_studies: int = 0
    higher_studies_pct: float = 0.0
    internships_pct: float = 0.0
    by_program: list[dict[str, Any]] = Field(default_factory=list)
    by_company: list[dict[str, Any]] = Field(default_factory=list)
    by_tier: list[dict[str, Any]] = Field(default_factory=list)
    nirf_rows: list[dict[str, Any]] = Field(default_factory=list)


class PlcJobOut(BaseModel):
    job_id: uuid.UUID
    status: str = "queued"


# ---- recruiter portal -----------------------------------------------------------------------------------------------
class RecruiterMe(BaseModel):
    user_id: uuid.UUID
    companies: list[PlcCompanyOut] = Field(default_factory=list)


class RecruiterDriveIn(_Strict):
    title: str = Field(min_length=1, max_length=200)
    job_role: str | None = Field(None, max_length=120)
    job_type: JobTypeLit = "full_time"
    ctc_min_paise: int | None = Field(None, ge=0)
    ctc_max_paise: int | None = Field(None, ge=0)
    stipend_paise: int | None = Field(None, ge=0)
    locations: list[str] = Field(default_factory=list)
    bond: dict[str, Any] | None = None
    eligibility_rules: PlcEligibilityRules = Field(default_factory=PlcEligibilityRules)
    registration_deadline: datetime | None = None
    drive_on: date | None = None
    mode: ModeLit = "on_campus"
    jd_url: str | None = Field(None, max_length=1000)
    company_id: uuid.UUID | None = None  # needed only when the recruiter represents several companies


class RecruiterApplicantOut(BaseModel):
    application_id: uuid.UUID
    status: str
    fields: dict[str, Any] = Field(default_factory=dict)
    rounds: list[dict[str, Any]] = Field(default_factory=list)


class RecruiterOfferIn(_Strict):
    application_id: uuid.UUID
    role: str | None = Field(None, max_length=120)
    ctc_paise: int = Field(ge=0)
    ctc_breakup: dict[str, Any] | None = None
    location: str | None = Field(None, max_length=120)
    offer_letter_url: str | None = Field(None, max_length=1000)
    offered_on: date | None = None
    joining_on: date | None = None
