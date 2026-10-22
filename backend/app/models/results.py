"""Results — section 16 of Database_Schema.sql (Prompts/15 §15.3): processing runs, versioned course / term results,
publications, grade cards, legacy imports and the ABC credit ledger (rows created here, pushed in Phase 18).

DDL notes the services rely on: ``student_course_results UNIQUE (enrolment, course, attempt_number, version)`` and the
``trg_results_immutable`` / ``trg_term_results_immutable`` triggers (published rows may only move to ``superseded`` and
flip ``is_current``), ``student_term_results UNIQUE (student_term_record_id, version)``,
``abc_credit_ledger.student_course_result_id UNIQUE``, ``grade_cards.qr_token UNIQUE``.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class ResultProcessingRun(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "result_processing_runs"

    exam_session_id: Mapped[uuid.UUID | None] = _fk("exam_sessions.id", "CASCADE")
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    run_type: Mapped[str] = mapped_column(String(30), nullable=False, default="provisional")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    triggered_by: Mapped[uuid.UUID | None] = _uuid()
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_resolution_id: Mapped[uuid.UUID | None] = _uuid()  # FK → resolutions (governance phase)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    checksum: Mapped[str | None] = mapped_column(String(64))
    error_log: Mapped[Any | None] = mapped_column(JSONB)
    job_id: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class StudentCourseResult(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_course_results"
    __table_args__ = (
        UniqueConstraint("student_program_enrollment_id", "course_id", "attempt_number", "version"),
        Index("ix_scr_current", "student_program_enrollment_id", "course_id", postgresql_where="is_current"),
        Index("ix_scr_run", "run_id", "status"),
        Index("ix_scr_term", "term_id", "college_id"),
    )

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    course_id: Mapped[uuid.UUID] = _fk("courses.id", nullable=False)
    offering_id: Mapped[uuid.UUID | None] = _fk("course_offerings.id")
    exam_session_id: Mapped[uuid.UUID | None] = _fk("exam_sessions.id")
    exam_registration_item_id: Mapped[uuid.UUID | None] = _fk("exam_registration_items.id")
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    attempt_type: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    credits: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    cia_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    cia_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    ese_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    ese_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    grace_marks: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    grace_reason: Mapped[str | None] = mapped_column(String(120))
    moderation_delta: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    total_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    total_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    letter_grade: Mapped[str | None] = mapped_column(String(3))
    grade_point: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    result_status: Mapped[str] = mapped_column(String(20), nullable=False)
    counts_toward_cgpa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = _fk("student_course_results.id")
    run_id: Mapped[uuid.UUID] = _fk("result_processing_runs.id", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class StudentTermResult(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_term_results"
    __table_args__ = (
        UniqueConstraint("student_term_record_id", "version"),
        Index("ix_str_results_record", "student_term_record_id", postgresql_where="is_current"),
    )

    student_term_record_id: Mapped[uuid.UUID] = _fk("student_term_records.id", "CASCADE", nullable=False)
    run_id: Mapped[uuid.UUID] = _fk("result_processing_runs.id", nullable=False)
    credits_registered: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    credits_earned: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False, default=0)
    sgpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    cgpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    cumulative_credits: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    backlog_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    result_class: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="computed")
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class ResultPublication(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "result_publications"

    run_id: Mapped[uuid.UUID] = _fk("result_processing_runs.id", "CASCADE", nullable=False)
    exam_session_id: Mapped[uuid.UUID | None] = _fk("exam_sessions.id")
    published_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    published_at: Mapped[datetime] = _now()
    audience: Mapped[str] = mapped_column(String(20), nullable=False, default="student")
    notify: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    withheld_list: Mapped[Any | None] = mapped_column(JSONB)


class GradeCard(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "grade_cards"
    __table_args__ = (UniqueConstraint("institution_id", "document_number"),)

    student_term_result_id: Mapped[uuid.UUID] = _fk("student_term_results.id", "CASCADE", nullable=False)
    document_number: Mapped[str] = mapped_column(String(40), nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    qr_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    template_id: Mapped[uuid.UUID | None] = _uuid()  # FK → document_templates (Phase 26)
    generated_at: Mapped[datetime] = _now()
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class LegacyResultImport(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "legacy_result_imports"

    batch_id: Mapped[uuid.UUID] = _fk("batches.id", nullable=False)
    term_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    run_id: Mapped[uuid.UUID | None] = _fk("result_processing_runs.id")
    job_id: Mapped[uuid.UUID | None] = _uuid()
    requested_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AbcCreditLedger(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "abc_credit_ledger"

    student_id: Mapped[uuid.UUID] = _fk("students.id", "CASCADE", nullable=False)
    apaar_id: Mapped[str | None] = mapped_column(String(20))
    student_course_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_course_results.id"), nullable=False, unique=True
    )
    term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    course_code: Mapped[str] = mapped_column(String(30), nullable=False)
    course_title: Mapped[str] = mapped_column(String(200), nullable=False)
    credits: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    letter_grade: Mapped[str | None] = mapped_column(String(3))
    grade_point: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    academic_year: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    push_batch_id: Mapped[uuid.UUID | None] = _uuid()
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
