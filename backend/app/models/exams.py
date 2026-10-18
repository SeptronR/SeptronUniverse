"""Exam administration — section 15 of Database_Schema.sql (Prompts/14 §14.3) + ``exam_centres`` (§31),
``malpractice_cases`` (§15; Phase 16 runs the inquiry, Phase 14 files the report) and ``calendar_events`` (§24; the
date-sheet publishes exam events, Phase 25 owns the calendar module).

DDL notes the services rely on: ``exam_papers UNIQUE (exam_session_id, course_id, paper_type)`` (bulk creation is
idempotent), ``exam_registrations UNIQUE (exam_session_id, student_program_enrollment_id)`` + partial unique
``uq_hall_ticket``, ``exam_registration_items UNIQUE (exam_registration_id, exam_paper_id)``,
``exam_seating_plans UNIQUE (session, date, slot, room)``, ``exam_seat_allocations`` one per item and
``UNIQUE (seating_plan_id, seat_number)``, ``invigilation_duties UNIQUE (session, date, slot, staff)`` (no staff on two
rooms of a slot), ``exam_attendance`` one per item, ``question_paper_assignments UNIQUE (exam_paper_id, set_label)``.
"""

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class ExamSession(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "exam_sessions"

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id", "CASCADE")
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    exam_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    coe_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    registration_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late_fee_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fee_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    hall_ticket_release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    valuation_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="single")
    discrepancy_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=15)
    grading_scale_id: Mapped[uuid.UUID | None] = _fk("grading_scales.id")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = _uuid()


class ExamPaper(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "exam_papers"
    __table_args__ = (UniqueConstraint("exam_session_id", "course_id", "paper_type"),)

    exam_session_id: Mapped[uuid.UUID] = _fk("exam_sessions.id", "CASCADE", nullable=False)
    course_id: Mapped[uuid.UUID] = _fk("courses.id", nullable=False)
    paper_code: Mapped[str | None] = mapped_column(String(30))
    paper_type: Mapped[str] = mapped_column(String(20), nullable=False, default="theory")
    exam_date: Mapped[date | None] = mapped_column(Date)
    session_slot: Mapped[str | None] = mapped_column(String(5))
    start_time: Mapped[time | None] = mapped_column(Time)
    duration_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    qp_pattern: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    quiz_id: Mapped[uuid.UUID | None] = _fk("quizzes.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ExamRegistration(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "exam_registrations"
    __table_args__ = (
        UniqueConstraint("exam_session_id", "student_program_enrollment_id"),
        Index("ix_exam_registrations_session", "exam_session_id", "status"),
    )

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    exam_session_id: Mapped[uuid.UUID] = _fk("exam_sessions.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    total_fee_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hall_ticket_number: Mapped[str | None] = mapped_column(String(30))
    hall_ticket_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hall_ticket_qr_token: Mapped[str | None] = mapped_column(String(64))
    hall_ticket_pdf_url: Mapped[str | None] = mapped_column(Text)
    eligibility_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ExamRegistrationItem(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "exam_registration_items"
    __table_args__ = (
        UniqueConstraint("exam_registration_id", "exam_paper_id"),
        Index("ix_exam_reg_items_paper", "exam_paper_id", "status"),
    )

    exam_registration_id: Mapped[uuid.UUID] = _fk("exam_registrations.id", "CASCADE", nullable=False)
    exam_paper_id: Mapped[uuid.UUID] = _fk("exam_papers.id", nullable=False)
    course_id: Mapped[uuid.UUID] = _fk("courses.id", nullable=False)
    attempt_type: Mapped[str] = mapped_column(String(20), nullable=False, default="regular")
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    fee_paise: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligibility: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="registered")


class ExamSeatingPlan(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "exam_seating_plans"
    __table_args__ = (UniqueConstraint("exam_session_id", "exam_date", "session_slot", "room_id"),)

    exam_session_id: Mapped[uuid.UUID] = _fk("exam_sessions.id", "CASCADE", nullable=False)
    exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_slot: Mapped[str] = mapped_column(String(5), nullable=False)
    room_id: Mapped[uuid.UUID] = _fk("rooms.id", nullable=False)
    capacity_used: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ExamSeatAllocation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "exam_seat_allocations"
    __table_args__ = (UniqueConstraint("seating_plan_id", "seat_number"),)

    seating_plan_id: Mapped[uuid.UUID] = _fk("exam_seating_plans.id", "CASCADE", nullable=False)
    exam_registration_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    seat_number: Mapped[str] = mapped_column(String(10), nullable=False)
    row_no: Mapped[int | None] = mapped_column(SmallInteger)
    col_no: Mapped[int | None] = mapped_column(SmallInteger)


class InvigilationDuty(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "invigilation_duties"
    __table_args__ = (UniqueConstraint("exam_session_id", "exam_date", "session_slot", "staff_id"),)

    exam_session_id: Mapped[uuid.UUID] = _fk("exam_sessions.id", "CASCADE", nullable=False)
    exam_date: Mapped[date] = mapped_column(Date, nullable=False)
    session_slot: Mapped[str] = mapped_column(String(5), nullable=False)
    room_id: Mapped[uuid.UUID | None] = _fk("rooms.id")
    staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="invigilator")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="assigned")
    swap_with_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    remuneration_paise: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ExamAttendance(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "exam_attendance"

    exam_registration_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    answer_booklet_number: Mapped[str | None] = mapped_column(String(30))
    face_match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    marked_by: Mapped[uuid.UUID | None] = _uuid()
    marked_at: Mapped[datetime] = _now()


class QuestionPaperAssignment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "question_paper_assignments"
    __table_args__ = (UniqueConstraint("exam_paper_id", "set_label"),)

    exam_paper_id: Mapped[uuid.UUID] = _fk("exam_papers.id", "CASCADE", nullable=False)
    setter_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    external_setter: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    set_label: Mapped[str] = mapped_column(String(5), nullable=False, default="A")
    blueprint_id: Mapped[uuid.UUID | None] = _fk("question_blueprints.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="invited")
    file_key_encrypted: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scrutiny_by: Mapped[uuid.UUID | None] = _uuid()
    scrutiny_remarks: Mapped[str | None] = mapped_column(Text)
    remuneration_paise: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class QuestionPaperPrintLog(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "question_paper_print_log"

    exam_paper_id: Mapped[uuid.UUID] = _fk("exam_papers.id", "CASCADE", nullable=False)
    set_label: Mapped[str] = mapped_column(String(5), nullable=False)
    printed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    printed_at: Mapped[datetime] = _now()
    copies: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    watermark_text: Mapped[str | None] = mapped_column(String(120))
    ip: Mapped[str | None] = mapped_column(INET)


class ExamCentre(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "exam_centres"
    __table_args__ = (UniqueConstraint("exam_session_id", "centre_code"),)

    exam_session_id: Mapped[uuid.UUID] = _fk("exam_sessions.id", "CASCADE", nullable=False)
    college_id: Mapped[uuid.UUID] = _fk("colleges.id", nullable=False)
    centre_code: Mapped[str] = mapped_column(String(20), nullable=False)
    chief_superintendent_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    capacity: Mapped[int | None] = mapped_column(SmallInteger)
    assigned_colleges: Mapped[list[str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class MalpracticeCase(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "malpractice_cases"
    __table_args__ = (UniqueConstraint("institution_id", "case_number"),)

    exam_session_id: Mapped[uuid.UUID] = _fk("exam_sessions.id", "CASCADE", nullable=False)
    exam_registration_item_id: Mapped[uuid.UUID] = _fk("exam_registration_items.id", nullable=False)
    case_number: Mapped[str] = mapped_column(String(30), nullable=False)
    reported_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reported_at: Mapped[datetime] = _now()
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    invigilator_report: Mapped[str | None] = mapped_column(Text)
    student_statement: Mapped[str | None] = mapped_column(Text)
    committee_id: Mapped[uuid.UUID | None] = _uuid()
    hearing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    punishment: Mapped[str | None] = mapped_column(String(20))
    debar_until_term_id: Mapped[uuid.UUID | None] = _fk("academic_terms.id")
    decision_text: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID | None] = _uuid()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reported")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CalendarEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "calendar_events"
    __table_args__ = (Index("ix_calendar_events_range", "institution_id", "starts_at"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, default="general")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    location: Mapped[str | None] = mapped_column(String(200))
    audience_rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[uuid.UUID | None] = _uuid()
    color: Mapped[str | None] = mapped_column(String(10))
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
