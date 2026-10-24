"""OBE attainment — section 17 of Database_Schema.sql (Prompts/17 §17.3): configs per regulation / programme, runs
(offering or programme-batch, with the config snapshot that makes them reproducible), CO / PO attainment rows and the
CQI action register. Also modelled here (read-only for this phase; Phase 27 owns the survey module):
``feedback_surveys`` / ``feedback_responses`` (§26) — the indirect attainment source.

DDL notes the services rely on: ``attainment_configs UNIQUE (scope_type, scope_id)``, ``co_attainments UNIQUE
(offering_id, course_outcome_id, run_id)``, ``po_attainments UNIQUE (program_id, batch_id, outcome_id, run_id)``.
Config keys the DDL has no column for (ESE apportion strategy, credit weighting, survey thresholds) live in
``platform_settings['attainment_defaults']`` / ``institution_settings`` and in every run's ``config_snapshot``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Boolean, Date, DateTime, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid(nullable: bool = True) -> Any:
    return mapped_column(UUID(as_uuid=True), nullable=nullable)


def _level() -> Any:
    return mapped_column(Numeric(3, 2))


class AttainmentConfig(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "attainment_configs"
    __table_args__ = (UniqueConstraint("scope_type", "scope_id"),)

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = _uuid(False)
    target_student_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=60)
    target_marks_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=60)
    levels: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    direct_weight: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=80)
    indirect_weight: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=20)
    cia_weight_in_direct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30)
    ese_weight_in_direct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=70)
    po_target_level: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, default=2)
    co_target_level: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, default=2)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AttainmentRun(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "attainment_runs"

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = _uuid(False)
    batch_id: Mapped[uuid.UUID | None] = _fk("batches.id")
    config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    run_at: Mapped[datetime] = _now()
    run_by: Mapped[uuid.UUID | None] = _uuid()
    job_id: Mapped[uuid.UUID | None] = _uuid()


class CoAttainment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "co_attainments"
    __table_args__ = (UniqueConstraint("offering_id", "course_outcome_id", "run_id"),)

    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    course_outcome_id: Mapped[uuid.UUID] = _fk("course_outcomes.id", "CASCADE", nullable=False)
    run_id: Mapped[uuid.UUID] = _fk("attainment_runs.id", "CASCADE", nullable=False)
    students_assessed: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    students_above_target: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    direct_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    direct_level: Mapped[Decimal | None] = _level()
    cia_level: Mapped[Decimal | None] = _level()
    ese_level: Mapped[Decimal | None] = _level()
    indirect_level: Mapped[Decimal | None] = _level()
    final_level: Mapped[Decimal | None] = _level()
    target_level: Mapped[Decimal | None] = _level()
    gap: Mapped[Decimal | None] = _level()
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = _now()


class PoAttainment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "po_attainments"
    __table_args__ = (UniqueConstraint("program_id", "batch_id", "outcome_id", "run_id"),)

    program_id: Mapped[uuid.UUID] = _fk("programs.id", "CASCADE", nullable=False)
    batch_id: Mapped[uuid.UUID] = _fk("batches.id", "CASCADE", nullable=False)
    outcome_id: Mapped[uuid.UUID] = _fk("outcome_definitions.id", "CASCADE", nullable=False)
    run_id: Mapped[uuid.UUID] = _fk("attainment_runs.id", "CASCADE", nullable=False)
    direct_level: Mapped[Decimal | None] = _level()
    indirect_level: Mapped[Decimal | None] = _level()
    final_level: Mapped[Decimal | None] = _level()
    target_level: Mapped[Decimal | None] = _level()
    gap: Mapped[Decimal | None] = _level()
    contributing_courses: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = _now()


class CqiAction(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "cqi_actions"

    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = _uuid(False)
    outcome_id: Mapped[uuid.UUID | None] = _fk("outcome_definitions.id")
    gap: Mapped[Decimal | None] = _level()
    action_text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    evidence_url: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class FeedbackSurvey(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "feedback_surveys"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    survey_type: Mapped[str] = mapped_column(String(20), nullable=False)
    term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    questions: Mapped[Any] = mapped_column(JSONB, nullable=False)
    audience_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class FeedbackResponse(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "feedback_responses"
    __table_args__ = (UniqueConstraint("survey_id", "respondent_hash", "target_id"),)

    survey_id: Mapped[uuid.UUID] = _fk("feedback_surveys.id", "CASCADE", nullable=False)
    respondent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[uuid.UUID | None] = _uuid()
    answers: Mapped[Any] = mapped_column(JSONB, nullable=False)
    submitted_at: Mapped[datetime] = _now()


# ---- value objects (stored inside ``breakdown`` JSON) -------------------------------------------------------------------
class LevelBand(BaseModel):
    level: int
    min_pct: float


class CoBreakdown(BaseModel):
    """One assessment's contribution to a CO."""

    assessment: str
    kind: str  # cia | ese
    source: str  # question_wise | qp_pattern | uniform
    co_max: float
    students_assessed: int
    students_above_target: int
    pct: float
    level: int
    weight: float = 1.0


class PoBreakdown(BaseModel):
    """One contributing course of a PO: CO final levels × map levels."""

    course_id: str
    course_code: str
    offering_id: str
    cos: list[dict[str, Any]]
    contribution: float
    credits: float = 0
