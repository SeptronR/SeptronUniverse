"""Question bank, blueprints, paper builder and study materials (carried from Orbit) — section 14 of
Database_Schema.sql (Prompts/13 §13.3). Bilingual bodies live in ``*_primary`` / ``*_secondary``; papers freeze their
``sections`` JSON (``[{title, questions:[{question_id, marks, sequence}]}]``)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class SyllabusTopic(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "syllabus_topics"

    course_id: Mapped[uuid.UUID] = _fk("courses.id", "CASCADE", nullable=False)
    unit_no: Mapped[int | None] = mapped_column(SmallInteger)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = _fk("syllabus_topics.id")
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    created_at: Mapped[datetime] = _now()


class Question(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "questions"

    course_id: Mapped[uuid.UUID | None] = _fk("courses.id")
    topic_id: Mapped[uuid.UUID | None] = _fk("syllabus_topics.id")
    co_id: Mapped[uuid.UUID | None] = _fk("course_outcomes.id")
    question_type: Mapped[str] = mapped_column(String(20), nullable=False)
    body_primary: Mapped[str] = mapped_column(Text, nullable=False)
    body_secondary: Mapped[str | None] = mapped_column(Text)
    marks: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=1)
    difficulty: Mapped[str] = mapped_column(String(10), nullable=False, default="medium")
    bloom_level: Mapped[str | None] = mapped_column(String(20))
    answer_key: Mapped[Any | None] = mapped_column(JSONB)
    explanation: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    media: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = _uuid()


class QuestionOption(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "question_options"

    question_id: Mapped[uuid.UUID] = _fk("questions.id", "CASCADE", nullable=False)
    label: Mapped[str | None] = mapped_column(String(5))
    body_primary: Mapped[str] = mapped_column(Text, nullable=False)
    body_secondary: Mapped[str | None] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class QuestionBlueprint(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "question_blueprints"

    course_id: Mapped[uuid.UUID | None] = _fk("courses.id")
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    total_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    pattern: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class QuestionPaper(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "question_papers"

    course_id: Mapped[uuid.UUID | None] = _fk("courses.id")
    blueprint_id: Mapped[uuid.UUID | None] = _fk("question_blueprints.id")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    total_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    duration_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    is_bilingual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class StudyMaterial(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "study_materials"

    course_id: Mapped[uuid.UUID | None] = _fk("courses.id")
    offering_id: Mapped[uuid.UUID | None] = _fk("course_offerings.id")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    material_type: Mapped[str] = mapped_column(String(20), nullable=False, default="notes")
    body_primary: Mapped[str | None] = mapped_column(Text)
    body_secondary: Mapped[str | None] = mapped_column(Text)
    file_url: Mapped[str | None] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
