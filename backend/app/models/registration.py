"""Course registration — section 11 of Database_Schema.sql (Prompts/09 §09.3).

Registration windows, one registration per enrolment × term with its items (the cart), elective choice forms and
allocation runs, offering waitlists and the arrears register. Column names mirror the DDL exactly
(``check_schema_drift.py --phase 09``).

DDL notes the services rely on:

* ``course_registrations`` is ``UNIQUE (student_program_enrollment_id, term_id)`` and carries the optimistic
  ``version`` (bump trigger) and the ``workflow_instance_id`` of ``registration.advisor``;
* ``fee_invoice_id`` references ``fee_invoices`` (Phase 12) — NULL until Phase 12; the mock payment order of the
  registration / late fee is kept in the audit log (Phase 08 approach);
* ``student_arrears`` feeds the Phase 07 backlog counts (``status IN ('open','registered')``) and is maintained
  transactionally by the Phase 15 result publication.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
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
from app.models.base import OptimisticLockMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


def _fk(target: str, ondelete: str | None = None, nullable: bool = True) -> Any:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _now() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Any:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class RegistrationWindow(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "registration_windows"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id", "CASCADE")
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    window_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # {program_ids?, batch_ids?, section_ids?, term_numbers?, department_ids?, entry_types?} — every present key must match
    applies_to: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    late_fee_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_advisor_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_fee_clearance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_credits_override: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class CourseRegistration(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, OptimisticLockMixin, Base):
    __tablename__ = "course_registrations"
    __table_args__ = (UniqueConstraint("student_program_enrollment_id", "term_id"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    student_term_record_id: Mapped[uuid.UUID] = _fk("student_term_records.id", nullable=False)
    window_id: Mapped[uuid.UUID | None] = _fk("registration_windows.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    total_credits: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    fee_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class CourseRegistrationItem(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_registration_items"
    __table_args__ = (UniqueConstraint("registration_id", "offering_id"),)

    registration_id: Mapped[uuid.UUID] = _fk("course_registrations.id", "CASCADE", nullable=False)
    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", nullable=False)
    course_id: Mapped[uuid.UUID] = _fk("courses.id", nullable=False)
    registration_type: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    priority: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="selected")
    is_credit_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_at: Mapped[datetime] = _now()
    dropped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drop_reason: Mapped[str | None] = mapped_column(Text)
    prerequisite_override_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ElectiveChoiceForm(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "elective_choice_forms"
    __table_args__ = (UniqueConstraint("student_program_enrollment_id", "elective_basket_id", "term_id"),)

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    elective_basket_id: Mapped[uuid.UUID] = _fk("elective_baskets.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    choices: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)  # [{course_id, priority}]
    allocated_course_id: Mapped[uuid.UUID | None] = _fk("courses.id")
    allocation_run_id: Mapped[uuid.UUID | None] = _fk("elective_allocation_runs.id", "SET NULL")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    submitted_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ElectiveAllocationRun(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "elective_allocation_runs"

    elective_basket_id: Mapped[uuid.UUID] = _fk("elective_baskets.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    run_at: Mapped[datetime] = _now()
    run_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class OfferingWaitlist(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "offering_waitlists"
    __table_args__ = (UniqueConstraint("offering_id", "student_program_enrollment_id"),)

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting")
    offered_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudentArrear(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "student_arrears"
    __table_args__ = (UniqueConstraint("student_program_enrollment_id", "course_id"),)

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    course_id: Mapped[uuid.UUID] = _fk("courses.id", nullable=False)
    first_failed_term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    last_attempt_term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    # FK → student_course_results (Phase 15, deferred constraint in the DDL)
    cleared_result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
