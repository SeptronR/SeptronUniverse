"""HR — section 9 of Database_Schema.sql (Prompts/06 §06.3).

Staff master (+ encrypted PAN/Aadhaar/bank details), documents, service book, faculty profiles and qualifications,
leave types/requests/balances, attendance devices and staff attendance, payroll components/structures/runs/items,
loans, recruitment (postings, applications, panels, scores), appraisals, CAS applications, workloads and course
allocation proposals. Column names mirror the DDL exactly (``check_schema_drift.py --phase 06``).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import (
    CreatedByMixin,
    EncryptedBytes,
    TenantMixin,
    TenantModelMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


def _fk(target: str, ondelete: str | None = None, nullable: bool = True) -> Any:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _created_at() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---- staff master ---------------------------------------------------------------------------------------------------
class Designation(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "designations"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20))
    cadre: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="teaching")
    level: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Staff(TenantModelMixin, Base):
    __tablename__ = "staff"
    __table_args__ = (UniqueConstraint("institution_id", "employee_id"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id", "SET NULL")
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    employee_id: Mapped[str] = mapped_column(String(30), nullable=False)
    department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    designation_id: Mapped[uuid.UUID | None] = _fk("designations.id")
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    dob: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(10))
    blood_group: Mapped[str | None] = mapped_column(String(5))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    photo_url: Mapped[str | None] = mapped_column(Text)
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    emergency_contact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    employment_type: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    staff_category: Mapped[str] = mapped_column(String(20), nullable=False, default="teaching")
    joining_date: Mapped[date | None] = mapped_column(Date)
    confirmation_date: Mapped[date | None] = mapped_column(Date)
    retirement_date: Mapped[date | None] = mapped_column(Date)
    exit_date: Mapped[date | None] = mapped_column(Date)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    pan_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)
    aadhaar_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)
    bank_details_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)  # JSON text {account_no, ifsc, bank}
    pf_number: Mapped[str | None] = mapped_column(String(30))
    esi_number: Mapped[str | None] = mapped_column(String(30))
    uan: Mapped[str | None] = mapped_column(String(20))
    hourly_rate_paise: Mapped[int | None] = mapped_column(Integer)
    reports_to_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.middle_name, self.last_name) if p)


class StaffDocument(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "staff_documents"

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    doc_type: Mapped[str] = mapped_column(String(60), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime] = _created_at()


class ServiceBookEntry(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "service_book_entries"

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    document_url: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


class FacultyProfile(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "faculty_profiles"

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("staff.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    aicte_faculty_id: Mapped[str | None] = mapped_column(String(30))
    orcid: Mapped[str | None] = mapped_column(String(20))
    scopus_id: Mapped[str | None] = mapped_column(String(20))
    google_scholar_id: Mapped[str | None] = mapped_column(String(30))
    vidwan_id: Mapped[str | None] = mapped_column(String(20))
    highest_qualification: Mapped[str | None] = mapped_column(String(60))
    is_phd: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    phd_year: Mapped[int | None] = mapped_column(SmallInteger)
    is_phd_guide: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    guide_recognition_no: Mapped[str | None] = mapped_column(String(40))
    max_scholars: Mapped[int | None] = mapped_column(SmallInteger)
    experience_teaching_months: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    experience_industry_months: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    experience_research_months: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    specializations: Mapped[list[str] | None] = mapped_column(JSONB)
    api_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    api_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cadre: Mapped[str | None] = mapped_column(String(20))


class FacultyQualification(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "faculty_qualifications"

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    degree: Mapped[str] = mapped_column(String(60), nullable=False)
    discipline: Mapped[str | None] = mapped_column(String(120))
    university: Mapped[str | None] = mapped_column(String(200))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    is_highest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    certificate_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


# ---- leaves ---------------------------------------------------------------------------------------------------------
class LeaveType(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "leave_types"
    __table_args__ = (UniqueConstraint("institution_id", "code"),)

    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    annual_quota: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    accrual: Mapped[str] = mapped_column(String(20), nullable=False, default="yearly")
    carry_forward_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_encashable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_document: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applies_to: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # {staff_categories[], genders[], employment_types[]}
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StaffLeave(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "staff_leaves"

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    leave_type_id: Mapped[uuid.UUID] = _fk("leave_types.id", nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_count: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    half_day: Mapped[str | None] = mapped_column(String(10))
    reason: Mapped[str | None] = mapped_column(Text)
    document_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    workflow_instance_id: Mapped[uuid.UUID | None] = _fk("workflow_instances.id", "SET NULL")


class StaffLeaveBalance(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "staff_leave_balances"
    __table_args__ = (UniqueConstraint("staff_id", "leave_type_id", "year"),)

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    leave_type_id: Mapped[uuid.UUID] = _fk("leave_types.id", nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    opening: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    accrued: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    used: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    encashed: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    balance: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---- staff attendance -----------------------------------------------------------------------------------------------
class AttendanceDevice(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "attendance_devices"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    device_type: Mapped[str] = mapped_column(String(20), nullable=False)
    serial_no: Mapped[str | None] = mapped_column(String(80))
    location: Mapped[str | None] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    applies_to: Mapped[str] = mapped_column(String(20), nullable=False, default="staff")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StaffAttendance(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "staff_attendance"
    __table_args__ = (UniqueConstraint("staff_id", "attendance_date"),)

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    check_in_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    device_id: Mapped[uuid.UUID | None] = _fk("attendance_devices.id")
    geo: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    remarks: Mapped[str | None] = mapped_column(Text)
    marked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


# ---- payroll --------------------------------------------------------------------------------------------------------
class PayrollComponent(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "payroll_components"
    __table_args__ = (UniqueConstraint("institution_id", "code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    component_type: Mapped[str] = mapped_column(String(30), nullable=False)
    calc_type: Mapped[str] = mapped_column(String(20), nullable=False, default="fixed")
    formula: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {amount_paise} | {pct} | {expr}
    is_statutory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    statutory_kind: Mapped[str | None] = mapped_column(String(20))
    is_taxable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StaffSalaryStructure(UUIDPrimaryKeyMixin, TenantMixin, CreatedByMixin, Base):
    __tablename__ = "staff_salary_structures"

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    pay_level: Mapped[str | None] = mapped_column(String(20))
    basic_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # {CODE: {amount_paise}|{pct}}
    ctc_paise: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


class StaffPayroll(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "staff_payrolls"
    __table_args__ = (UniqueConstraint("staff_id", "month", "year"),)

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    working_days: Mapped[int | None] = mapped_column(SmallInteger)
    paid_days: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    lop_days: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    gross_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    deductions_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    employer_contrib_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    net_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_ref: Mapped[str | None] = mapped_column(String(60))
    payslip_url: Mapped[str | None] = mapped_column(Text)


class StaffPayrollItem(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "staff_payroll_items"

    payroll_id: Mapped[uuid.UUID] = _fk("staff_payrolls.id", "CASCADE", nullable=False)
    component_id: Mapped[uuid.UUID | None] = _fk("payroll_components.id")
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    component_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class LoanAdvance(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "loans_advances"

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    loan_type: Mapped[str] = mapped_column(String(30), nullable=False)
    principal_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    emi_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    start_month: Mapped[date] = mapped_column(Date, nullable=False)
    balance_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    workflow_instance_id: Mapped[uuid.UUID | None] = _fk("workflow_instances.id", "SET NULL")


# ---- recruitment ----------------------------------------------------------------------------------------------------
class JobPosting(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "job_postings"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    cadre: Mapped[str | None] = mapped_column(String(30))
    vacancies: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    reservation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {roster, vacancies:{UR:n, SC:n, …}}
    qualifications: Mapped[list[Any] | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")


class JobApplication(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "job_applications"

    posting_id: Mapped[uuid.UUID] = _fk("job_postings.id", "CASCADE", nullable=False)
    applicant: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    documents: Mapped[list[Any] | None] = mapped_column(JSONB)
    category: Mapped[str | None] = mapped_column(String(20))
    api_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    screening_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="applied")


class InterviewPanel(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "interview_panels"

    posting_id: Mapped[uuid.UUID] = _fk("job_postings.id", "CASCADE", nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    venue: Mapped[str | None] = mapped_column(String(200))
    members: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)  # [{user_id, name, role, weight}]
    created_at: Mapped[datetime] = _created_at()


class InterviewScore(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "interview_scores"
    __table_args__ = (UniqueConstraint("panel_id", "application_id"),)

    panel_id: Mapped[uuid.UUID] = _fk("interview_panels.id", "CASCADE", nullable=False)
    application_id: Mapped[uuid.UUID] = _fk("job_applications.id", "CASCADE", nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # {member_user_id: {criterion: score}}
    total: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    remarks: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created_at()


# ---- appraisal / CAS / workload -------------------------------------------------------------------------------------
class Appraisal(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "appraisals"
    __table_args__ = (UniqueConstraint("staff_id", "academic_year_id"),)

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    self_assessment: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    self_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    reviewer_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    reviewer_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    final_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    workflow_instance_id: Mapped[uuid.UUID | None] = _fk("workflow_instances.id", "SET NULL")


class CasApplication(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "cas_applications"

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    from_cadre: Mapped[str] = mapped_column(String(30), nullable=False)
    to_cadre: Mapped[str] = mapped_column(String(30), nullable=False)
    eligibility_date: Mapped[date | None] = mapped_column(Date)
    api_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    documents: Mapped[list[Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    workflow_instance_id: Mapped[uuid.UUID | None] = _fk("workflow_instances.id", "SET NULL")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FacultyWorkload(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "faculty_workloads"
    __table_args__ = (UniqueConstraint("staff_id", "term_id"),)

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    theory_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    tutorial_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    lab_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    project_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    admin_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    research_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    total_hours: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    max_allowed_hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")


class CourseAllocationProposal(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "course_allocation_proposals"
    __table_args__ = (UniqueConstraint("department_id", "term_id"),)

    department_id: Mapped[uuid.UUID] = _fk("departments.id", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    proposals: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)  # [{course_id, staff_id, hours}]
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    workflow_instance_id: Mapped[uuid.UUID | None] = _fk("workflow_instances.id", "SET NULL")
