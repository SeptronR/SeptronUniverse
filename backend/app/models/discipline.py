"""Discipline — section 26 ``disciplinary_cases`` (Prompts/27 §27.3).

``UNIQUE (institution_id, case_number)``; ``subject_type`` student (``subject_id`` = ``student_program_enrollments.id``)
or staff (``staff.id``). ``evidence`` holds ``{"items": [...], "source": {...}, "timeline": [...], "notices": [...],
"statements": [...], "hearings": [...], "appeal": {...}, "workflow_instance_id": ..., "decision_text": ...,
"decision_document_id": ..., "effects": [...]}`` — the DDL keeps one JSON column for the case file.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = ["DisciplinaryCase"]


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class DisciplinaryCase(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "disciplinary_cases"
    __table_args__ = (UniqueConstraint("institution_id", "case_number"),)
    __mapper_args__ = {"eager_defaults": True}

    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    case_number: Mapped[str] = mapped_column(String(30), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reported_by: Mapped[uuid.UUID | None] = _uuid()
    committee_id: Mapped[uuid.UUID | None] = _uuid()
    hearing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sanctions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    appeal_status: Mapped[str | None] = mapped_column(String(20))
    decided_by: Mapped[uuid.UUID | None] = _uuid()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reported")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
