"""Evaluation — section 15 of Database_Schema.sql (Prompts/15 §15.3): answer-script bundles, dummy-number coding,
custody, valuation assignments / rounds, final marks and moderation.

DDL notes the services rely on: ``answer_scripts.exam_registration_item_id UNIQUE`` (one script per item),
``UNIQUE (bundle_id, dummy_number)``, ``valuation_assignments UNIQUE (bundle_id, valuation_round)``,
``script_valuations UNIQUE (answer_script_id, valuation_round)``, ``script_final_marks.answer_script_id UNIQUE``.
``answer_scripts_for_evaluation`` is a SQL view without identity columns — evaluator queries read only that mapping.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class AnswerScriptBundle(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "answer_script_bundles"
    __table_args__ = (UniqueConstraint("exam_paper_id", "bundle_number"),)

    exam_paper_id: Mapped[uuid.UUID] = _fk("exam_papers.id", "CASCADE", nullable=False)
    room_id: Mapped[uuid.UUID | None] = _fk("rooms.id")
    exam_centre_id: Mapped[uuid.UUID | None] = _fk("exam_centres.id", "SET NULL")
    bundle_number: Mapped[str] = mapped_column(String(30), nullable=False)
    script_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    coded_by: Mapped[uuid.UUID | None] = _uuid()
    coded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    custody_holder_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    custody_location: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AnswerScript(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "answer_scripts"
    __table_args__ = (
        UniqueConstraint("bundle_id", "dummy_number"),
        Index("ix_answer_scripts_bundle", "bundle_id", "status"),
    )

    exam_registration_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exam_registration_items.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    bundle_id: Mapped[uuid.UUID] = _fk("answer_script_bundles.id", nullable=False)
    dummy_number: Mapped[str] = mapped_column(String(20), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(40))
    pages: Mapped[int | None] = mapped_column(SmallInteger)
    scan_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AnswerScriptForEvaluation(Base):
    """Read-only mapping of the ``answer_scripts_for_evaluation`` view — no identity columns by construction."""

    __tablename__ = "answer_scripts_for_evaluation"
    __table_args__ = {"info": {"is_view": True}}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    institution_id: Mapped[uuid.UUID] = _uuid()
    bundle_id: Mapped[uuid.UUID] = _uuid()
    dummy_number: Mapped[str] = mapped_column(String(20))
    pages: Mapped[int | None] = mapped_column(SmallInteger)
    scan_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))


class ScriptCustodyLog(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "script_custody_log"

    bundle_id: Mapped[uuid.UUID] = _fk("answer_script_bundles.id", "CASCADE", nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    from_staff_id: Mapped[uuid.UUID | None] = _uuid()
    to_staff_id: Mapped[uuid.UUID | None] = _uuid()
    at: Mapped[datetime] = _now()
    location: Mapped[str | None] = mapped_column(String(120))
    remarks: Mapped[str | None] = mapped_column(Text)


class ValuationAssignment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "valuation_assignments"
    __table_args__ = (UniqueConstraint("bundle_id", "valuation_round"),)

    exam_paper_id: Mapped[uuid.UUID] = _fk("exam_papers.id", "CASCADE", nullable=False)
    bundle_id: Mapped[uuid.UUID] = _fk("answer_script_bundles.id", "CASCADE", nullable=False)
    evaluator_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    evaluator_user_id: Mapped[uuid.UUID | None] = _fk("users.id")
    external_evaluator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    evaluator_type: Mapped[str] = mapped_column(String(10), nullable=False, default="internal")
    valuation_round: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="assigned")
    assigned_at: Mapped[datetime] = _now()
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remuneration_paise: Mapped[int | None] = mapped_column(Integer)


class ScriptValuation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "script_valuations"
    __table_args__ = (UniqueConstraint("answer_script_id", "valuation_round"),)

    answer_script_id: Mapped[uuid.UUID] = _fk("answer_scripts.id", "CASCADE", nullable=False)
    valuation_round: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    evaluator_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    question_wise: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    annotations_url: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = _now()
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ModerationAction(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "moderation_actions"

    exam_paper_id: Mapped[uuid.UUID] = _fk("exam_papers.id", "CASCADE", nullable=False)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rule: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    affected_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ScriptFinalMarks(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "script_final_marks"

    answer_script_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("answer_scripts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    marks_v1: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    marks_v2: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    marks_v3: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    discrepancy: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    rule_applied: Mapped[str | None] = mapped_column(String(40))
    computed_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    moderated_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    moderation_action_id: Mapped[uuid.UUID | None] = _fk("moderation_actions.id", "SET NULL")
    final_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    updated_at: Mapped[datetime] = _updated()
