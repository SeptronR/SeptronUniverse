"""Student projects / dissertations — section 14 of Database_Schema.sql (Prompts/13 §13.3).
``project_members UNIQUE (project_id, student_program_enrollment_id)``, ``project_reviews UNIQUE (project_id,
review_no)``; review marks flow into ``internal_marks`` through ``offering_assessment_id``."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


class StudentProject(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_projects"

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    project_type: Mapped[str] = mapped_column(String(20), nullable=False, default="major")
    guide_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    co_guide_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    external_guide: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    abstract: Mapped[str | None] = mapped_column(Text)
    repository_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ProjectMember(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "student_program_enrollment_id"),)

    project_id: Mapped[uuid.UUID] = _fk("student_projects.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="member")


class ProjectReview(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "project_reviews"
    __table_args__ = (UniqueConstraint("project_id", "review_no"),)

    project_id: Mapped[uuid.UUID] = _fk("student_projects.id", "CASCADE", nullable=False)
    review_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    scheduled_on: Mapped[date | None] = mapped_column(Date)
    panel: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    rubric_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    remarks: Mapped[str | None] = mapped_column(Text)
    offering_assessment_id: Mapped[uuid.UUID | None] = _fk("offering_assessments.id")
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _now()
