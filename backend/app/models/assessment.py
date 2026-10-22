"""Internal assessment — section 14 of Database_Schema.sql (Prompts/13 §13.3) + ``college_data_submissions`` (§34; the
CIA university submission of Phase 13 writes it, Phase 34 owns the module).

DDL notes the services rely on: ``offering_assessments UNIQUE (offering_id, component_id)`` (instantiate is
idempotent), ``assessment_questions UNIQUE (offering_assessment_id, question_no)``, ``internal_marks UNIQUE
(offering_assessment_id, student_program_enrollment_id)`` (the single write path upserts on it),
``cia_consolidations UNIQUE (offering_id, student_program_enrollment_id)``, ``college_data_submissions UNIQUE
(college_id, term_id, submission_type)``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class OfferingAssessment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "offering_assessments"
    __table_args__ = (UniqueConstraint("offering_id", "component_id"),)

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    component_id: Mapped[uuid.UUID] = _fk("assessment_components.id", nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    scheduled_on: Mapped[date | None] = mapped_column(Date)
    marks_entry_deadline: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    question_paper_id: Mapped[uuid.UUID | None] = _uuid()
    submitted_by: Mapped[uuid.UUID | None] = _uuid()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[uuid.UUID | None] = _uuid()
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AssessmentQuestion(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "assessment_questions"
    __table_args__ = (UniqueConstraint("offering_assessment_id", "question_no"),)

    offering_assessment_id: Mapped[uuid.UUID] = _fk("offering_assessments.id", "CASCADE", nullable=False)
    question_no: Mapped[str] = mapped_column(String(10), nullable=False)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    co_id: Mapped[uuid.UUID | None] = _fk("course_outcomes.id")
    bloom_level: Mapped[str | None] = mapped_column(String(20))
    part: Mapped[str | None] = mapped_column(String(5))


class InternalMark(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "internal_marks"
    __table_args__ = (UniqueConstraint("offering_assessment_id", "student_program_enrollment_id"),)

    offering_assessment_id: Mapped[uuid.UUID] = _fk("offering_assessments.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    is_absent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_exempt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    question_wise: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    entered_by: Mapped[uuid.UUID | None] = _uuid()
    entered_at: Mapped[datetime] = _now()
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    updated_at: Mapped[datetime] = _updated()


class CiaConsolidation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "cia_consolidations"
    __table_args__ = (UniqueConstraint("offering_id", "student_program_enrollment_id"),)

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    component_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    cia_total: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    cia_scaled: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="computed")
    locked_by: Mapped[uuid.UUID | None] = _uuid()
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = _now()


class MarksChangeRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "marks_change_requests"

    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CollegeDataSubmission(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "college_data_submissions"
    __table_args__ = (UniqueConstraint("college_id", "term_id", "submission_type"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    exam_session_id: Mapped[uuid.UUID | None] = _uuid()
    submission_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    record_count: Mapped[int | None] = mapped_column(Integer)
    file_url: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[uuid.UUID | None] = _uuid()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
