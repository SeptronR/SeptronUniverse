"""OBE definitions — section 14 of Database_Schema.sql (Prompts/13 §13.3): PEO / PO / PSO per programme (or the
institution), the PEO-PO matrix, course outcomes and the CO-PO / CO-PSO matrix (levels 1–3, CHECK in the DDL)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


class OutcomeDefinition(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "outcome_definitions"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id", "outcome_type", "code"),)

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    outcome_type: Mapped[str] = mapped_column(String(10), nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    framework: Mapped[str | None] = mapped_column(String(30))
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class PeoPoMapping(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "peo_po_mappings"
    __table_args__ = (UniqueConstraint("peo_id", "po_id"),)

    peo_id: Mapped[uuid.UUID] = _fk("outcome_definitions.id", "CASCADE", nullable=False)
    po_id: Mapped[uuid.UUID] = _fk("outcome_definitions.id", "CASCADE", nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class CourseOutcome(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "course_outcomes"
    __table_args__ = (UniqueConstraint("course_id", "code"),)

    course_id: Mapped[uuid.UUID] = _fk("courses.id", "CASCADE", nullable=False)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    bloom_level: Mapped[str | None] = mapped_column(String(20))
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CoPoMapping(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "co_po_mappings"
    __table_args__ = (UniqueConstraint("course_outcome_id", "outcome_id"),)

    course_outcome_id: Mapped[uuid.UUID] = _fk("course_outcomes.id", "CASCADE", nullable=False)
    outcome_id: Mapped[uuid.UUID] = _fk("outcome_definitions.id", "CASCADE", nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    justification: Mapped[str | None] = mapped_column(Text)
