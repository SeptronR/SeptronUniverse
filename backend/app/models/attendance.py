"""Student attendance & eligibility — section 12 of Database_Schema.sql (Prompts/11 §11.3).

Column names mirror the DDL exactly (``check_schema_drift.py --phase 11``). DDL notes the services rely on:

* ``student_class_attendance`` is **partitioned** ``BY RANGE (session_date)`` with a default partition; its primary
  key is ``(id, session_date)`` and the upsert target is ``UNIQUE (session_id, student_program_enrollment_id,
  session_date)``. ``institution_id`` carries no FK in the DDL (partitioned parent);
* ``attendance_summaries`` is ``UNIQUE (offering_id, student_program_enrollment_id)``;
* ``term_eligibility`` is ``UNIQUE (student_term_record_id, offering_id, version)`` — every compute writes a new version.

``class_sessions`` (Phase 10, ``models/timetable.py``) is the anchor: ``attendance_status`` not_taken | taken |
finalized.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Index, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class StudentClassAttendance(Base):
    __tablename__ = "student_class_attendance"
    __table_args__ = (
        UniqueConstraint("session_id", "student_program_enrollment_id", "session_date"),
        Index("ix_sca_student", "student_program_enrollment_id", "session_date"),
        {"postgresql_partition_by": "RANGE (session_date)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_date: Mapped[date] = mapped_column(Date, primary_key=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    session_id: Mapped[uuid.UUID] = _fk("class_sessions.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    marked_by: Mapped[uuid.UUID | None] = _uuid()
    marked_at: Mapped[datetime] = _now()
    remarks: Mapped[str | None] = mapped_column(String(255))


class OnDutyRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "on_duty_requests"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    recommended_by: Mapped[uuid.UUID | None] = _uuid()
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    sessions_applied: Mapped[list[str] | None] = mapped_column(JSONB)
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AttendanceSummary(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "attendance_summaries"
    __table_args__ = (UniqueConstraint("offering_id", "student_program_enrollment_id"),)

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    total_sessions: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    present: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    absent: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    on_duty: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    late: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    exempt: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    eligibility: Mapped[str] = mapped_column(String(20), nullable=False, default="eligible")
    computed_at: Mapped[datetime] = _now()


class AttendanceCondonation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "attendance_condonations"

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    offering_id: Mapped[uuid.UUID | None] = _fk("course_offerings.id")
    actual_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    reason_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    fee_invoice_id: Mapped[uuid.UUID | None] = _uuid()
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class TermEligibility(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "term_eligibility"
    __table_args__ = (UniqueConstraint("student_term_record_id", "offering_id", "version"),)

    student_term_record_id: Mapped[uuid.UUID] = _fk("student_term_records.id", "CASCADE", nullable=False)
    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    attendance_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cia_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    cia_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    is_attendance_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_cia_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_fee_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_hold_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason_codes: Mapped[list[str] | None] = mapped_column(JSONB)
    decided_by: Mapped[uuid.UUID | None] = _uuid()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
