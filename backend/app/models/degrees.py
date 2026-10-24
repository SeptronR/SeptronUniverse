"""Degrees, convocation & digital credentials — section 16 of Database_Schema.sql (Prompts/18 §18.3).

``abc_credit_ledger`` is modelled in ``app/models/results.py`` (Phase 15 inserts the rows; this phase pushes them).
``degrees_awarded.approval_resolution_id`` stays a plain UUID until ``resolutions`` (§30, Phase 33) is modelled; the
PDF URL / serial columns are written directly until Phase 26 adds ``issued_documents``.

DDL notes the services rely on: ``convocation_registrations UNIQUE (convocation_id, student_program_enrollment_id)``,
``digital_credentials UNIQUE (entity_type, entity_id, channel)``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class DegreeEligibilityCheck(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "degree_eligibility_checks"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    checked_at: Mapped[datetime] = _now()
    credits_earned: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    credits_required: Mapped[Decimal | None] = mapped_column(Numeric(6, 1))
    bucket_breakdown: Mapped[Any | None] = mapped_column(JSONB)
    backlog_count: Mapped[int | None] = mapped_column(SmallInteger)
    cgpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    min_cgpa_ok: Mapped[bool | None] = mapped_column(Boolean)
    duration_ok: Mapped[bool | None] = mapped_column(Boolean)
    dues_cleared: Mapped[bool | None] = mapped_column(Boolean)
    holds_clear: Mapped[bool | None] = mapped_column(Boolean)
    mandatory_noncredit_ok: Mapped[bool | None] = mapped_column(Boolean)
    is_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reasons: Mapped[Any | None] = mapped_column(JSONB)
    run_id: Mapped[uuid.UUID | None] = _uuid()


class Convocation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "convocations"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    held_on: Mapped[date | None] = mapped_column(Date)
    venue: Mapped[str | None] = mapped_column(String(200))
    registration_deadline: Mapped[date | None] = mapped_column(Date)
    fee_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ConvocationRegistration(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "convocation_registrations"
    __table_args__ = (UniqueConstraint("convocation_id", "student_program_enrollment_id"),)

    convocation_id: Mapped[uuid.UUID] = _fk("convocations.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="in_person")
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    gown_size: Mapped[str | None] = mapped_column(String(10))
    guests: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered")
    created_at: Mapped[datetime] = _now()


class DegreeAwarded(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "degrees_awarded"

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    award_type: Mapped[str] = mapped_column(String(20), nullable=False)
    degree_name: Mapped[str] = mapped_column(String(120), nullable=False)
    specialization: Mapped[str | None] = mapped_column(String(120))
    result_class: Mapped[str | None] = mapped_column(String(30))
    cgpa: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    date_of_award: Mapped[date | None] = mapped_column(Date)
    certificate_number: Mapped[str | None] = mapped_column(String(40))
    serial_no: Mapped[str | None] = mapped_column(String(40))
    convocation_id: Mapped[uuid.UUID | None] = _fk("convocations.id")
    pdf_url: Mapped[str | None] = mapped_column(Text)
    esign_ref: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="recommended")
    approved_by: Mapped[uuid.UUID | None] = _uuid()
    approval_resolution_id: Mapped[uuid.UUID | None] = _uuid()
    digital_credential_id: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class DigitalCredential(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "digital_credentials"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "channel"),)

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_ref: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
