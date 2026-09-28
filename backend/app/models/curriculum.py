"""Course-level curriculum — section 7 of Database_Schema.sql (Prompts/05 §05.3).

``assessment_schemes`` / ``assessment_components`` (configuration only — marks arrive with Phase 13), ``courses``
(owned by a regulation: "CS301 under R2022" and "CS301 under R2024" are two rows), ``course_prerequisites``,
``elective_baskets`` + ``elective_basket_courses`` and ``curriculum_courses`` (the per-term structure of a
programme-regulation). Programme-level tables are in ``models/academic.py``.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, SmallInteger, String, UniqueConstraint, func
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


class AssessmentScheme(TenantModelMixin, Base):
    __tablename__ = "assessment_schemes"
    __table_args__ = (UniqueConstraint("regulation_id", "code"),)

    regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    applies_to_course_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    cia_weight: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=40)
    ese_weight: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=60)
    cia_max: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=40)
    ese_max: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=60)
    pass_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AssessmentComponent(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "assessment_components"
    __table_args__ = (UniqueConstraint("scheme_id", "code"),)

    scheme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_schemes.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # cia|ese_theory|ese_practical|viva|project_review
    max_marks: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scaled_to: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    weight_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    best_of: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {take, of, group}
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    co_mappable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Course(TenantModelMixin, CollegeScopedMixin, Base):
    __tablename__ = "courses"
    __table_args__ = (UniqueConstraint("institution_id", "regulation_id", "code"),)

    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False)
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    short_title: Mapped[str | None] = mapped_column(String(60))
    course_type: Mapped[str] = mapped_column(String(30), nullable=False)
    lecture_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    tutorial_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    practical_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    credits: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False, default=0)
    contact_hours_per_week: Mapped[int | None] = mapped_column(SmallInteger)
    assessment_scheme_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assessment_schemes.id")
    )
    cia_max: Mapped[int | None] = mapped_column(SmallInteger)
    ese_max: Mapped[int | None] = mapped_column(SmallInteger)
    is_credit_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_gradable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_seats: Mapped[int | None] = mapped_column(SmallInteger)
    max_seats: Mapped[int | None] = mapped_column(SmallInteger)
    syllabus: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)  # [{unit, title, topics[], hours}]
    textbooks: Mapped[list[Any] | None] = mapped_column(JSONB)
    references_list: Mapped[list[Any] | None] = mapped_column(JSONB)
    is_public_catalog: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")  # draft|approved|active|retired


class CoursePrerequisite(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_prerequisites"
    __table_args__ = (UniqueConstraint("course_id", "related_course_id", "relation"),)

    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    related_course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(20), nullable=False)  # prerequisite | corequisite | antirequisite
    min_grade: Mapped[str | None] = mapped_column(String(3))
    is_hard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ElectiveBasket(TenantModelMixin, Base):
    __tablename__ = "elective_baskets"
    __table_args__ = (UniqueConstraint("program_regulation_id", "code"),)

    program_regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("program_regulations.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    basket_type: Mapped[str] = mapped_column(String(20), nullable=False)
    term_number: Mapped[int | None] = mapped_column(SmallInteger)
    min_choose: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    max_choose: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    credits_required: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    allocation_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="priority_cgpa")


class ElectiveBasketCourse(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "elective_basket_courses"
    __table_args__ = (UniqueConstraint("basket_id", "course_id"),)

    basket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("elective_baskets.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    offering_department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CurriculumCourse(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "curriculum_courses"
    __table_args__ = (UniqueConstraint("program_regulation_id", "term_number", "course_id"),)

    program_regulation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("program_regulations.id", ondelete="CASCADE"), nullable=False
    )
    term_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    elective_basket_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("elective_baskets.id", ondelete="SET NULL")
    )
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credit_bucket: Mapped[str | None] = mapped_column(String(30))  # HS|BS|ES|PC|PE|OE|EEC|MC|VAC|AEC|SEC
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
