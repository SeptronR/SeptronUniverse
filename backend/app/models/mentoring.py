"""Mentoring & early warning — section 26 ``mentor_assignments``, ``mentoring_slots``, ``mentoring_bookings``,
``mentoring_sessions``, ``counselling_referrals``, ``risk_flags`` (Prompts/27 §27.3).

DDL facts the services rely on: ``mentor_assignments UNIQUE (student_program_enrollment_id, term_id)`` (one active
mentor per enrolment per term — reassignment updates the row and keeps the history in ``mentoring_meta``),
``risk_flags UNIQUE (student_program_enrollment_id, term_id)``. ``mentoring_sessions.concerns`` holds
``{"items": [...], "share_with_guardian": bool, "guardian_summary": str}`` (the DDL has no share column).
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

__all__ = [
    "CounsellingReferral",
    "MentorAssignment",
    "MentoringBooking",
    "MentoringSession",
    "MentoringSlot",
    "RiskFlag",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class MentorAssignment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mentor_assignments"
    __table_args__ = (UniqueConstraint("student_program_enrollment_id", "term_id"),)
    __mapper_args__ = _EAGER

    mentor_staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = _now()


class MentoringSlot(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mentoring_slots"
    __mapper_args__ = _EAGER

    mentor_staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    location: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = _now()


class MentoringBooking(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mentoring_bookings"
    __mapper_args__ = _EAGER

    slot_id: Mapped[uuid.UUID] = _fk("mentoring_slots.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID | None] = _fk("student_program_enrollments.id")
    guardian_user_id: Mapped[uuid.UUID | None] = _fk("users.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="booked")
    created_at: Mapped[datetime] = _now()


class MentoringSession(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mentoring_sessions"
    __mapper_args__ = _EAGER

    mentor_assignment_id: Mapped[uuid.UUID] = _fk("mentor_assignments.id", "CASCADE", nullable=False)
    held_on: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="in_person")
    notes: Mapped[str | None] = mapped_column(Text)
    concerns: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    action_items: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CounsellingReferral(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "counselling_referrals"
    __mapper_args__ = _EAGER

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    referred_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    counsellor_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="referred")
    is_confidential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class RiskFlag(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "risk_flags"
    __table_args__ = (UniqueConstraint("student_program_enrollment_id", "term_id"),)
    __mapper_args__ = _EAGER

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    factors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    computed_at: Mapped[datetime] = _now()
    acknowledged_by: Mapped[uuid.UUID | None] = _uuid()
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
