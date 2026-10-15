"""Admissions — section 10 of Database_Schema.sql (Prompts/08 §08.3).

Cycles with programme intakes, the seat matrix (quota × category), applicants with preferences and document
verification, merit lists, counselling rounds, seat allotments, offers and the enquiry CRM. Column names mirror the DDL
exactly (``check_schema_drift.py --phase 08``); relationships are not mapped — repositories load related rows in batches.

DDL notes the services rely on:

* there is no timeline table — the applicant timeline is read from the audit log (``record_type='applicant'``);
* ``seat_matrix.filled`` counts *held* seats (allotted / accepted / float / admitted); rows are locked ``FOR UPDATE``
  while an allotment runs, so two concurrent runs never over-allot;
* ``application_fee_invoice_id`` / ``seat_allotments.fee_invoice_id`` reference ``fee_invoices`` (Phase 12); until
  Phase 12 ships invoices they stay NULL and the mock payment adapter's reference is kept in ``applicants.documents``
  (``_payments``) / the audit log.
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
from app.models.base import TenantMixin, TenantModelMixin, TimestampMixin, UUIDPrimaryKeyMixin


def _fk(target: str, ondelete: str | None = None, nullable: bool = True) -> Any:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdmissionCycle(TenantModelMixin, Base):
    __tablename__ = "admission_cycles"
    __table_args__ = (UniqueConstraint("institution_id", "slug"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id", "CASCADE")
    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    application_fee_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    form_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    required_documents: Mapped[Any | None] = mapped_column(JSONB)
    de_reservation_policy: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AdmissionCycleProgram(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "admission_cycle_programs"
    __table_args__ = (UniqueConstraint("cycle_id", "program_id", "college_id"),)

    cycle_id: Mapped[uuid.UUID] = _fk("admission_cycles.id", "CASCADE", nullable=False)
    program_id: Mapped[uuid.UUID] = _fk("programs.id", nullable=False)
    college_id: Mapped[uuid.UUID] = _fk("colleges.id", nullable=False)
    intake: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lateral_intake: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    entrance_source: Mapped[str] = mapped_column(String(30), nullable=False, default="merit_only")
    eligibility_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    merit_formula: Mapped[Any | None] = mapped_column(JSONB)
    tie_break: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class SeatMatrix(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "seat_matrix"
    __table_args__ = (UniqueConstraint("cycle_id", "program_id", "college_id", "quota", "category"),)

    cycle_id: Mapped[uuid.UUID] = _fk("admission_cycles.id", "CASCADE", nullable=False)
    program_id: Mapped[uuid.UUID] = _fk("programs.id", nullable=False)
    college_id: Mapped[uuid.UUID] = _fk("colleges.id", nullable=False)
    quota: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    seats: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    filled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Applicant(TenantModelMixin, Base):
    __tablename__ = "applicants"
    __table_args__ = (UniqueConstraint("institution_id", "application_number"),)

    cycle_id: Mapped[uuid.UUID] = _fk("admission_cycles.id", "CASCADE", nullable=False)
    application_number: Mapped[str] = mapped_column(String(30), nullable=False)
    user_id: Mapped[uuid.UUID | None] = _fk("users.id", "SET NULL")
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    dob: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(10))
    category: Mapped[str | None] = mapped_column(String(20))
    is_pwd: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quota_claimed: Mapped[str | None] = mapped_column(String(30))
    nationality: Mapped[str | None] = mapped_column(String(60))
    domicile_state: Mapped[str | None] = mapped_column(String(60))
    contact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    entrance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    qualifying_exams: Mapped[Any | None] = mapped_column(JSONB)
    documents: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    merit_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    application_fee_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    admitted_student_id: Mapped[uuid.UUID | None] = _fk("students.id")
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="online")
    remarks: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.middle_name, self.last_name) if p)


class ApplicantPreference(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "applicant_preferences"
    __table_args__ = (UniqueConstraint("applicant_id", "priority"),)

    applicant_id: Mapped[uuid.UUID] = _fk("applicants.id", "CASCADE", nullable=False)
    program_id: Mapped[uuid.UUID] = _fk("programs.id", nullable=False)
    college_id: Mapped[uuid.UUID] = _fk("colleges.id", nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class ApplicantDocumentVerification(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "applicant_document_verifications"
    __table_args__ = (UniqueConstraint("applicant_id", "doc_type"),)

    applicant_id: Mapped[uuid.UUID] = _fk("applicants.id", "CASCADE", nullable=False)
    doc_type: Mapped[str] = mapped_column(String(60), nullable=False)
    file_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)


class MeritList(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "merit_lists"

    cycle_id: Mapped[uuid.UUID] = _fk("admission_cycles.id", "CASCADE", nullable=False)
    program_id: Mapped[uuid.UUID | None] = _fk("programs.id")
    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    quota: Mapped[str | None] = mapped_column(String(30))
    category: Mapped[str | None] = mapped_column(String(20))
    formula_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _now()


class MeritListEntry(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "merit_list_entries"
    __table_args__ = (UniqueConstraint("merit_list_id", "applicant_id"),)

    merit_list_id: Mapped[uuid.UUID] = _fk("merit_lists.id", "CASCADE", nullable=False)
    applicant_id: Mapped[uuid.UUID] = _fk("applicants.id", "CASCADE", nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    category_rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    tie_break: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CounsellingRound(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "counselling_rounds"
    __table_args__ = (UniqueConstraint("cycle_id", "round_number"),)

    cycle_id: Mapped[uuid.UUID] = _fk("admission_cycles.id", "CASCADE", nullable=False)
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str | None] = mapped_column(String(80))
    choice_filling_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    choice_filling_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allotment_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reporting_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")


class SeatAllotment(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "seat_allotments"
    __table_args__ = (UniqueConstraint("round_id", "applicant_id"),)

    round_id: Mapped[uuid.UUID] = _fk("counselling_rounds.id", "CASCADE", nullable=False)
    applicant_id: Mapped[uuid.UUID] = _fk("applicants.id", "CASCADE", nullable=False)
    program_id: Mapped[uuid.UUID] = _fk("programs.id", nullable=False)
    college_id: Mapped[uuid.UUID] = _fk("colleges.id", nullable=False)
    seat_matrix_id: Mapped[uuid.UUID] = _fk("seat_matrix.id", nullable=False)
    quota: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="allotted")
    admission_fee_paise: Mapped[int | None] = mapped_column(Integer)
    fee_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdmissionOffer(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "admission_offers"

    applicant_id: Mapped[uuid.UUID] = _fk("applicants.id", "CASCADE", nullable=False)
    program_id: Mapped[uuid.UUID] = _fk("programs.id", nullable=False)
    college_id: Mapped[uuid.UUID] = _fk("colleges.id", nullable=False)
    offer_type: Mapped[str] = mapped_column(String(20), nullable=False, default="provisional")
    valid_until: Mapped[date | None] = mapped_column(Date)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    letter_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="issued")


class Enquiry(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "enquiries"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(200))
    program_interest: Mapped[Any | None] = mapped_column(JSONB)
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[Any | None] = mapped_column(JSONB)
    applicant_id: Mapped[uuid.UUID | None] = _fk("applicants.id")
