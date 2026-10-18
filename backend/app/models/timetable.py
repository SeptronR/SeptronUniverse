"""Timetable & rooms — section 12 of Database_Schema.sql (Prompts/10 §10.3) + ``calendar_feed_tokens`` (§24,
created here for the iCal feeds; Phase 25 reuses it).

Column names mirror the DDL exactly (``check_schema_drift.py --phase 10``). DDL notes the services rely on:

* ``timetable_entries`` carries three partial unique indexes ``uq_tt_room`` / ``uq_tt_staff`` / ``uq_tt_section`` on
  ``(term_id, <x>, day_of_week, time_slot_id, week_pattern) WHERE is_active`` — the last line of defence behind the
  explicit conflict pre-check. Only the entries of the **published** version of a scope are ``is_active``; draft
  entries are stored inactive and switched on at publish (so a draft cloned from the published version never
  collides with it), the previous version's entries switched off in the same transaction;
* ``class_sessions`` is ``UNIQUE (offering_id, session_date, start_time)``;
* ``timetable_substitutions`` is ``UNIQUE (timetable_entry_id, on_date)``.
"""

import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, SmallInteger, String, Text, Time, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Building(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "buildings"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "code"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    floors: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Room(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "code"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    building_id: Mapped[uuid.UUID | None] = _fk("buildings.id", "SET NULL")
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    room_type: Mapped[str] = mapped_column(String(20), nullable=False, default="classroom")
    floor: Mapped[int | None] = mapped_column(SmallInteger)
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    exam_capacity: Mapped[int | None] = mapped_column(SmallInteger)
    features: Mapped[list[str] | dict[str, Any] | None] = mapped_column(JSONB)
    is_bookable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = _uuid()


class TimeSlot(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "time_slots"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "slot_group", "name"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    slot_group: Mapped[str] = mapped_column(String(40), nullable=False, default="Default")
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_type: Mapped[str] = mapped_column(String(20), nullable=False, default="lecture")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class Timetable(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "timetables"
    __table_args__ = (UniqueConstraint("term_id", "scope_type", "scope_id", "version"),)

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    effective_from: Mapped[date | None] = mapped_column(Date)
    published_by: Mapped[uuid.UUID | None] = _uuid()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = _uuid()


class TimetableEntry(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "timetable_entries"
    __table_args__ = (
        Index(
            "uq_tt_room",
            "term_id",
            "room_id",
            "day_of_week",
            "time_slot_id",
            "week_pattern",
            unique=True,
            postgresql_where=text("is_active AND room_id IS NOT NULL"),
        ),
        Index(
            "uq_tt_staff",
            "term_id",
            "staff_id",
            "day_of_week",
            "time_slot_id",
            "week_pattern",
            unique=True,
            postgresql_where=text("is_active AND staff_id IS NOT NULL"),
        ),
        Index(
            "uq_tt_section",
            "term_id",
            "section_id",
            "day_of_week",
            "time_slot_id",
            "week_pattern",
            unique=True,
            postgresql_where=text("is_active AND section_id IS NOT NULL"),
        ),
        Index("ix_timetable_entries_offering", "offering_id"),
    )

    timetable_id: Mapped[uuid.UUID] = _fk("timetables.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    section_id: Mapped[uuid.UUID | None] = _fk("batch_sections.id")
    day_of_week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    time_slot_id: Mapped[uuid.UUID] = _fk("time_slots.id", nullable=False)
    room_id: Mapped[uuid.UUID | None] = _fk("rooms.id")
    staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    session_type: Mapped[str] = mapped_column(String(20), nullable=False, default="lecture")
    week_pattern: Mapped[str] = mapped_column(String(10), nullable=False, default="all")
    slot_span: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TimetableSubstitution(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "timetable_substitutions"
    __table_args__ = (UniqueConstraint("timetable_entry_id", "on_date"),)

    timetable_entry_id: Mapped[uuid.UUID] = _fk("timetable_entries.id", "CASCADE", nullable=False)
    on_date: Mapped[date] = mapped_column(Date, nullable=False)
    substitute_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    approved_by: Mapped[uuid.UUID | None] = _uuid()


class ClassSession(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "class_sessions"
    __table_args__ = (
        UniqueConstraint("offering_id", "session_date", "start_time"),
        Index("ix_class_sessions_staff_date", "staff_id", "session_date"),
        Index("ix_class_sessions_offering_date", "offering_id", "session_date"),
    )

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    offering_id: Mapped[uuid.UUID] = _fk("course_offerings.id", "CASCADE", nullable=False)
    timetable_entry_id: Mapped[uuid.UUID | None] = _fk("timetable_entries.id", "SET NULL")
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_slot_id: Mapped[uuid.UUID | None] = _fk("time_slots.id")
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    session_type: Mapped[str] = mapped_column(String(20), nullable=False, default="lecture")
    topic: Mapped[str | None] = mapped_column(String(255))
    lesson_plan_item_id: Mapped[uuid.UUID | None] = _uuid()  # FK → lesson_plans (Phase 13 maps that table)
    online_link: Mapped[str | None] = mapped_column(Text)
    room_id: Mapped[uuid.UUID | None] = _fk("rooms.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    attendance_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_taken")
    attendance_taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_by: Mapped[uuid.UUID | None] = _uuid()
    qr_token: Mapped[str | None] = mapped_column(String(64))
    qr_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CalendarFeedToken(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "calendar_feed_tokens"

    user_id: Mapped[uuid.UUID] = _fk("users.id", "CASCADE", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _now()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
