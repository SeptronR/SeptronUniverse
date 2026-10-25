"""Clubs & activities — section 26 ``clubs``, ``club_members``, ``club_events``, ``activity_hours`` (Prompts/27 §27.3).

``student_achievements`` (Phase 16 ``app.models.post_result.StudentAchievement``) and ``feedback_surveys`` /
``feedback_responses`` (Phase 17 ``app.models.obe_attainment``) are reused as they are. DDL facts: ``clubs UNIQUE
(institution_id, name)``, ``club_members UNIQUE (club_id, student_program_enrollment_id)``; a join request is a
member row with ``role='pending'``; a rejected hours entry keeps ``verified_by`` / ``verified_at`` with
``hours = 0`` and the remark in ``description``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = ["ActivityHour", "Club", "ClubEvent", "ClubMember"]

_EAGER: dict[str, Any] = {"eager_defaults": True}


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Club(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "clubs"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)
    __mapper_args__ = _EAGER

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    club_type: Mapped[str] = mapped_column(String(20), nullable=False)
    faculty_advisor_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    description: Mapped[str | None] = mapped_column(Text)
    budget_paise: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ClubMember(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "club_members"
    __table_args__ = (UniqueConstraint("club_id", "student_program_enrollment_id"),)

    club_id: Mapped[uuid.UUID] = _fk("clubs.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)


class ClubEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "club_events"
    __mapper_args__ = _EAGER

    club_id: Mapped[uuid.UUID] = _fk("clubs.id", "CASCADE", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    held_on: Mapped[date | None] = mapped_column(Date)
    venue: Mapped[str | None] = mapped_column(String(200))
    participants_count: Mapped[int | None] = mapped_column(Integer)
    budget_paise: Mapped[int | None] = mapped_column(BigInteger)
    report_url: Mapped[str | None] = mapped_column(Text)
    images: Mapped[list[Any] | None] = mapped_column(JSONB)
    event_id: Mapped[uuid.UUID | None] = _fk("events.id")
    created_at: Mapped[datetime] = _now()


class ActivityHour(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "activity_hours"
    __mapper_args__ = _EAGER

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    hours: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    on_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(String(200))
    evidence_url: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credits_course_id: Mapped[uuid.UUID | None] = _fk("courses.id")
    created_at: Mapped[datetime] = _now()
