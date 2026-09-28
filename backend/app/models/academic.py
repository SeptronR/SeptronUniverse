"""Academic structure — section 7 of Database_Schema.sql (Prompts/03 §03.3, Prompts/05 §05.3).

Phase 03: ``academic_years``, ``academic_terms``. The partial unique index ``one_current_year`` (one ``is_current``
year per institution/college) lives in the canonical DDL only (revision 0001);
``AcademicSessionService.set_current_year`` flips the previous row in the same transaction.

Phase 05 adds the programme-level tables of section 7 (grading scales, programmes, regulations, programme-regulation
bindings and structure terms, batches and sections); the course-level curriculum tables live in
``models/curriculum.py``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import (
    CollegeScopedMixin,
    TenantMixin,
    TenantModelMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class AcademicYear(TenantModelMixin, CollegeScopedMixin, Base):
    __tablename__ = "academic_years"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "name"),)

    name: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AcademicTerm(TenantModelMixin, CollegeScopedMixin, Base):
    __tablename__ = "academic_terms"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "academic_year_id", "term_type", "sequence"),)

    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    term_type: Mapped[str] = mapped_column(String(20), nullable=False)  # odd | even | summer | trimester | annual
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    registration_start: Mapped[date | None] = mapped_column(Date)
    registration_end: Mapped[date | None] = mapped_column(Date)
    add_drop_end: Mapped[date | None] = mapped_column(Date)
    last_instruction_date: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # planned | registration | in_progress | exam | result_processing | closed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")


# ---- Phase 05 --------------------------------------------------------------------------------------------------------
class GradingScale(TenantModelMixin, Base):
    __tablename__ = "grading_scales"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    # FK added by ALTER TABLE in the canonical DDL (grading_scales ↔ regulations reference each other)
    regulation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regulations.id", ondelete="SET NULL", use_alter=True)
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    scale_type: Mapped[str] = mapped_column(String(20), nullable=False, default="absolute")  # absolute | relative
    # [{grade, min_pct, max_pct, points, is_fail?}] — validated by GradingService (cover 0–100, one fail grade)
    ranges: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    relative_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    special_grades: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    max_grade_point: Mapped[Decimal] = mapped_column(Numeric(3, 1), nullable=False, default=10)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Program(TenantModelMixin, Base):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "code"),)

    college_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False
    )
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faculties.id", ondelete="SET NULL")
    )
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    degree_name: Mapped[str] = mapped_column(String(80), nullable=False)
    specialization: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    term_pattern: Mapped[str] = mapped_column(String(20), nullable=False, default="semester")
    duration_years: Mapped[Decimal] = mapped_column(Numeric(3, 1), nullable=False)
    total_terms: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    max_duration_years: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    sanctioned_intake: Mapped[int | None] = mapped_column(SmallInteger)
    lateral_intake: Mapped[int | None] = mapped_column(SmallInteger)
    approving_body: Mapped[str | None] = mapped_column(String(40))
    exam_authority: Mapped[str] = mapped_column(String(30), nullable=False, default="autonomous_college")
    is_nep_multidisciplinary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_open_enrolment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # draft | active | closed


class Regulation(TenantModelMixin, CollegeScopedMixin, Base):
    __tablename__ = "regulations"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    effective_from_admission_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    grading_scale_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("grading_scales.id"))
    # validated against ``app.schemas.academics.RegulationRules`` on every write (Prompts/05 §05.3)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft|approved|active|superseded
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_resolution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("regulations.id"))


class ProgramRegulation(TenantModelMixin, Base):
    __tablename__ = "program_regulations"
    __table_args__ = (UniqueConstraint("program_id", "regulation_id"),)

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programs.id", ondelete="CASCADE"), nullable=False
    )
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    rules_override: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    total_credits_required: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft | active | closed


class ProgramStructureTerm(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "program_structure_terms"
    __table_args__ = (UniqueConstraint("program_regulation_id", "term_number"),)

    program_regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("program_regulations.id", ondelete="CASCADE"), nullable=False
    )
    term_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    min_credits: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    max_credits: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    normal_credits: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    is_exit_point: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    exit_award: Mapped[str | None] = mapped_column(String(30))


class Batch(TenantModelMixin, Base):
    __tablename__ = "batches"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "program_id", "admission_year", "entry_type"),)

    college_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False
    )
    program_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("programs.id"), nullable=False)
    program_regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("program_regulations.id"), nullable=False
    )
    admission_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")  # regular | lateral
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    expected_graduation_year: Mapped[int | None] = mapped_column(SmallInteger)
    current_term_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class BatchSection(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "batch_sections"
    __table_args__ = (UniqueConstraint("batch_id", "name"),)

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batches.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(10), nullable=False)
    capacity: Mapped[int | None] = mapped_column(SmallInteger)
    # FK → staff (Phase 06); until staff rows exist the ``class_advisor`` @offering assignment names the holder
    class_advisor_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
