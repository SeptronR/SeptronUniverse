"""Grievances — section 26 ``grievances``, ``grievance_updates`` (Prompts/27 §27.3).

``UNIQUE (institution_id, ticket_number)``. Anonymous rows keep ``raised_by_user_id`` NULL; the tracking secret is
stored only as a SHA-256 hash inside ``attachments`` (``{"files": [...], "tracking": {"secret_hash": ...}}``) — the
DDL has no column for it and the API never returns the ``tracking`` key.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = ["Grievance", "GrievanceUpdate"]

_EAGER: dict[str, Any] = {"eager_defaults": True}


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Grievance(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "grievances"
    __table_args__ = (UniqueConstraint("institution_id", "ticket_number"),)
    __mapper_args__ = _EAGER

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    ticket_number: Mapped[str] = mapped_column(String(30), nullable=False)
    raised_by_user_id: Mapped[uuid.UUID | None] = _fk("users.id")
    student_program_enrollment_id: Mapped[uuid.UUID | None] = _fk("student_program_enrollments.id")
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    committee: Mapped[str | None] = mapped_column(String(20))
    committee_id: Mapped[uuid.UUID | None] = _uuid()
    assigned_to: Mapped[uuid.UUID | None] = _uuid()
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    satisfaction_rating: Mapped[int | None] = mapped_column(SmallInteger)
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class GrievanceUpdate(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "grievance_updates"
    __mapper_args__ = _EAGER

    grievance_id: Mapped[uuid.UUID] = _fk("grievances.id", "CASCADE", nullable=False)
    by_user_id: Mapped[uuid.UUID | None] = _uuid()
    note: Mapped[str] = mapped_column(Text, nullable=False)
    is_internal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attachments: Mapped[list[Any] | None] = mapped_column(JSONB)
    at: Mapped[datetime] = _now()
