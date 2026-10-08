"""Students — section 8 of Database_Schema.sql (Prompts/07 §07.3).

Student master (+ encrypted Aadhaar / bank details), guardians, documents, undertakings, programme enrolments, term
records, holds, transfers and credit transfers. Column names mirror the DDL exactly (``check_schema_drift.py --phase
07``). Relationships are not mapped (``lazy="noload"`` in spirit): repositories load related rows explicitly in batches.

DDL notes the services rely on:

* ``one_active_enrollment`` — partial unique index ``(student_id) WHERE status IN ('active','break','detained')``: a
  second open enrolment of the same student fails with an integrity error (→ 409);
* ``student_holds`` has no ``updated_at`` / release-reason column — the release reason lives in the audit row;
* ``student_undertakings`` is unique per (student, type, template): a yearly re-acceptance updates the row in place
  (every acceptance is audited);
* ``credit_transfers`` has no workflow column — the ``students.credit_transfer`` instance is found by entity.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import BigInteger

from app.db.session import Base
from app.models.base import EncryptedBytes, TenantMixin, TenantModelMixin, TimestampMixin, UUIDPrimaryKeyMixin


def _fk(target: str, ondelete: str | None = None, nullable: bool = True) -> Any:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Student(TenantModelMixin, Base):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("institution_id", "registration_number"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    registration_number: Mapped[str] = mapped_column(String(30), nullable=False)
    enrolment_number: Mapped[str | None] = mapped_column(String(30))
    apaar_id: Mapped[str | None] = mapped_column(String(20))
    abc_id: Mapped[str | None] = mapped_column(String(20))
    aadhaar_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    dob: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)
    blood_group: Mapped[str | None] = mapped_column(String(5))
    category: Mapped[str | None] = mapped_column(String(20))
    sub_category: Mapped[str | None] = mapped_column(String(40))
    is_pwd: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pwd_pct: Mapped[int | None] = mapped_column(SmallInteger)
    pwd_type: Mapped[str | None] = mapped_column(String(60))
    is_minority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    minority_type: Mapped[str | None] = mapped_column(String(40))
    religion: Mapped[str | None] = mapped_column(String(40))
    nationality: Mapped[str] = mapped_column(String(60), nullable=False, default="Indian")
    is_international: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    passport: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    visa: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    frro: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    domicile_state: Mapped[str | None] = mapped_column(String(60))
    mother_tongue: Mapped[str | None] = mapped_column(String(40))
    photo_url: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    permanent_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    current_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    bank_details_encrypted: Mapped[str | None] = mapped_column(EncryptedBytes)  # JSON text {account_no, ifsc, bank}
    guardian_portal_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    admission_quota: Mapped[str | None] = mapped_column(String(30))
    admission_mode: Mapped[str | None] = mapped_column(String(30))
    admission_date: Mapped[date | None] = mapped_column(Date)
    # provisional | admitted | active | on_break | detained | dropped_out | transferred | exited | graduated | alumni |
    # expelled | deceased
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="provisional")

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.middle_name, self.last_name) if p)


class StudentGuardian(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "student_guardians"
    __table_args__ = (UniqueConstraint("student_id", "relation", "name"),)

    student_id: Mapped[uuid.UUID] = _fk("students.id", "CASCADE", nullable=False)
    user_id: Mapped[uuid.UUID | None] = _fk("users.id", "SET NULL")
    relation: Mapped[str] = mapped_column(String(20), nullable=False)  # father | mother | guardian | spouse | other
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    occupation: Mapped[str | None] = mapped_column(String(100))
    annual_income_paise: Mapped[int | None] = mapped_column(BigInteger)
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    portal_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class StudentDocument(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_documents"

    student_id: Mapped[uuid.UUID] = _fk("students.id", "CASCADE", nullable=False)
    doc_type: Mapped[str] = mapped_column(String(60), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_on: Mapped[date | None] = mapped_column(Date)
    remarks: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = _now()


class StudentUndertaking(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_undertakings"
    __table_args__ = (UniqueConstraint("student_id", "undertaking_type", "template_id"),)

    student_id: Mapped[uuid.UUID] = _fk("students.id", "CASCADE", nullable=False)
    # anti_ragging | conduct | hostel_rules | data_consent | photo_consent | custom
    undertaking_type: Mapped[str] = mapped_column(String(30), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK → document_templates (Phase 26)
    accepted_at: Mapped[datetime] = _now()
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    signature_url: Mapped[str | None] = mapped_column(Text)


class StudentProgramEnrollment(TenantModelMixin, Base):
    __tablename__ = "student_program_enrollments"
    __table_args__ = (UniqueConstraint("student_id", "program_id", "batch_id"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    student_id: Mapped[uuid.UUID] = _fk("students.id", "CASCADE", nullable=False)
    program_id: Mapped[uuid.UUID] = _fk("programs.id", nullable=False)
    batch_id: Mapped[uuid.UUID] = _fk("batches.id", nullable=False)
    program_regulation_id: Mapped[uuid.UUID] = _fk("program_regulations.id", nullable=False)
    department_id: Mapped[uuid.UUID] = _fk("departments.id", nullable=False)
    admission_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    entry_term_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    specialization: Mapped[str | None] = mapped_column(String(120))
    minor_program_id: Mapped[uuid.UUID | None] = _fk("programs.id")
    is_honours: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expected_exit_term: Mapped[int | None] = mapped_column(SmallInteger)
    # active | break | detained | completed | exited_early | withdrawn | transferred | expelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    exit_award: Mapped[str | None] = mapped_column(String(30))
    exit_date: Mapped[date | None] = mapped_column(Date)
    credits_earned: Mapped[Decimal] = mapped_column(Numeric(6, 1), nullable=False, default=0)
    cgpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    academic_standing: Mapped[str] = mapped_column(String(20), nullable=False, default="good")


class StudentTermRecord(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "student_term_records"
    __table_args__ = (UniqueConstraint("student_program_enrollment_id", "term_id"),)

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    term_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    section_id: Mapped[uuid.UUID | None] = _fk("batch_sections.id", "SET NULL")
    roll_number: Mapped[str | None] = mapped_column(String(20))
    # pending_registration | registered | in_progress | exam_pending | completed | detained | on_break | withdrawn
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_registration")
    credits_registered: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    credits_earned: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    sgpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    cgpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    attendance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    result_status: Mapped[str | None] = mapped_column(String(20))


class StudentHold(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_holds"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    hold_type: Mapped[str] = mapped_column(String(20), nullable=False)  # registration|exam|transcript|graduation|…|all
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    placed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    placed_at: Mapped[datetime] = _now()
    released_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class StudentTransfer(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "student_transfers"

    student_id: Mapped[uuid.UUID] = _fk("students.id", "CASCADE", nullable=False)
    # migration_in | migration_out | inter_college | program_change | inter_university
    transfer_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    to_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    migration_certificate_no: Mapped[str | None] = mapped_column(String(50))
    tc_no: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = _now()
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    effective_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    fee_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class CreditTransfer(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "credit_transfers"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    # swayam | nptel | coursera | other_mooc | abc | other_university | prior_learning | internal_prior
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    source_course_code: Mapped[str | None] = mapped_column(String(40))
    source_title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_institution: Mapped[str | None] = mapped_column(String(200))
    credits: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    source_grade: Mapped[str | None] = mapped_column(String(10))
    source_score_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    equivalent_course_id: Mapped[uuid.UUID | None] = _fk("courses.id")
    elective_basket_id: Mapped[uuid.UUID | None] = _fk("elective_baskets.id")
    certificate_url: Mapped[str | None] = mapped_column(Text)
    abc_credit_ref: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # → student_course_results (Phase 15)
