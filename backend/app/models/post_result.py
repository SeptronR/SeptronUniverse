"""Post-result services — section 16 of Database_Schema.sql (Prompts/16 §16.3): revaluation-family requests and
transcripts; ``malpractice_cases`` is modelled in ``app/models/exams.py`` (Phase 14). Also modelled here for the
malpractice inquiry and medals: ``committees`` / ``committee_members`` (§30 — Phase 33 adds the governance UI) and
``student_achievements`` (§27 — Phase 27 owns the module; academic medals are created here).

DDL notes the services rely on: ``reval_requests UNIQUE (exam_registration_item_id, request_type)`` (one request per
item and type), ``transcripts.verification_token UNIQUE``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class RevalRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "reval_requests"
    __table_args__ = (UniqueConstraint("exam_registration_item_id", "request_type"),)

    exam_session_id: Mapped[uuid.UUID] = _fk("exam_sessions.id", "CASCADE", nullable=False)
    exam_registration_item_id: Mapped[uuid.UUID] = _fk("exam_registration_items.id", "CASCADE", nullable=False)
    answer_script_id: Mapped[uuid.UUID | None] = _fk("answer_scripts.id")
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    original_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    revised_marks: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    delta: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    evaluator_assignment_id: Mapped[uuid.UUID | None] = _fk("valuation_assignments.id")
    photocopy_url: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = _uuid()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refund_due: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Transcript(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "transcripts"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    transcript_type: Mapped[str] = mapped_column(String(20), nullable=False, default="consolidated")
    document_number: Mapped[str | None] = mapped_column(String(40))
    pdf_url: Mapped[str | None] = mapped_column(Text)
    verification_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    requested_at: Mapped[datetime] = _now()
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by: Mapped[uuid.UUID | None] = _uuid()
    copies: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")


class Committee(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "committees"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    committee_type: Mapped[str] = mapped_column(String(30), nullable=False)
    department_id: Mapped[uuid.UUID | None] = _fk("departments.id")
    chair_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    secretary_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    constituted_on: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    quorum_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CommitteeMember(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "committee_members"

    committee_id: Mapped[uuid.UUID] = _fk("committees.id", "CASCADE", nullable=False)
    member_type: Mapped[str] = mapped_column(String(10), nullable=False, default="staff")
    staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    user_id: Mapped[uuid.UUID | None] = _fk("users.id")
    external: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="member")
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)


class StudentAchievement(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_achievements"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[str | None] = mapped_column(String(20))
    position: Mapped[str | None] = mapped_column(String(20))
    held_on: Mapped[date | None] = mapped_column(Date)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
