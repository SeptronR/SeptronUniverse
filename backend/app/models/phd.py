"""PhD & research-scholar management — section 28 ``research_scholars`` … ``etd_uploads`` (Prompts/31 §31.3).

DDL facts: ``research_scholars.student_program_enrollment_id`` is unique (one scholar row per PhD enrolment) and the
guide / co-guide are ``staff`` rows (an external co-guide is JSON). ``publications.scholar_id`` (Phase 30) now carries
its FK to ``research_scholars``. ``doctoral_committees.members`` is the JSON member list
(``[{staff_id?, external{name, affiliation, email}?, role: convenor|member|external}]``) — DC-member ownership is JSON
containment on ``staff_id``. ``thesis_examiners.examiner`` holds ``{name, affiliation, email, token?}``. Facts without a
column (scholar timeline / relaxations / cancellation-review flag, coursework plan, DC meeting agenda / attendance,
disbursement hold reasons / contingency bills, request decisions, thesis workflow / certificate, examiner tokens /
dispatch links, viva notices, award / ETD embargo) live in ``institution_settings`` rows of category ``phd_meta``
(see ``app/services/phd/common.py``).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
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

__all__ = [
    "DcMeeting",
    "DoctoralCommittee",
    "EtdUpload",
    "FellowshipDisbursement",
    "ResearchScholar",
    "ScholarFellowship",
    "ScholarProgressReport",
    "ScholarRequest",
    "ThesisExaminer",
    "ThesisSubmission",
    "VivaVoce",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


class ResearchScholar(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "research_scholars"
    __mapper_args__ = _EAGER

    student_program_enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_program_enrollments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    guide_staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    co_guide_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    external_co_guide: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="full_time")
    fellowship_type: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    registration_date: Mapped[date | None] = mapped_column(Date)
    coursework_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    coursework_exemption_reason: Mapped[str | None] = mapped_column(Text)
    research_area: Mapped[str | None] = mapped_column(String(300))
    max_duration_end: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="admitted")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class DoctoralCommittee(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "doctoral_committees"
    __mapper_args__ = _EAGER

    scholar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_scholars.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    members: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    constituted_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class DcMeeting(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "dc_meetings"
    __table_args__ = (UniqueConstraint("scholar_id", "meeting_no"),)
    __mapper_args__ = _EAGER

    scholar_id: Mapped[uuid.UUID] = _fk("research_scholars.id", "CASCADE", nullable=False)
    meeting_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    held_on: Mapped[date | None] = mapped_column(Date)
    minutes: Mapped[str | None] = mapped_column(Text)
    recommendations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    minutes_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ScholarProgressReport(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "scholar_progress_reports"
    __table_args__ = (UniqueConstraint("scholar_id", "period_label"),)
    __mapper_args__ = _EAGER

    scholar_id: Mapped[uuid.UUID] = _fk("research_scholars.id", "CASCADE", nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    report_url: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    guide_remarks: Mapped[str | None] = mapped_column(Text)
    dc_rating: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    submitted_at: Mapped[datetime] = _now()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScholarFellowship(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "scholar_fellowships"
    __mapper_args__ = _EAGER

    scholar_id: Mapped[uuid.UUID] = _fk("research_scholars.id", "CASCADE", nullable=False)
    fellowship_type: Mapped[str] = mapped_column(String(20), nullable=False)
    monthly_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date | None] = mapped_column(Date)
    contingency_paise: Mapped[int | None] = mapped_column(Integer)
    hra_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    funding_source: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class FellowshipDisbursement(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fellowship_disbursements"
    __table_args__ = (UniqueConstraint("fellowship_id", "month"),)
    __mapper_args__ = _EAGER

    fellowship_id: Mapped[uuid.UUID] = _fk("scholar_fellowships.id", "CASCADE", nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    payroll_ref: Mapped[str | None] = mapped_column(String(60))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScholarRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "scholar_requests"
    __mapper_args__ = _EAGER

    scholar_id: Mapped[uuid.UUID] = _fk("research_scholars.id", "CASCADE", nullable=False)
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ThesisSubmission(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "thesis_submissions"
    __mapper_args__ = _EAGER

    scholar_id: Mapped[uuid.UUID] = _fk("research_scholars.id", "CASCADE", nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = _now()
    similarity_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    plagiarism_report_url: Mapped[str | None] = mapped_column(Text)
    ai_generated_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ThesisExaminer(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "thesis_examiners"
    __mapper_args__ = _EAGER

    thesis_id: Mapped[uuid.UUID] = _fk("thesis_submissions.id", "CASCADE", nullable=False)
    examiner: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    state: Mapped[str | None] = mapped_column(String(60))
    country: Mapped[str | None] = mapped_column(String(60))
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report_url: Mapped[str | None] = mapped_column(Text)
    report_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recommendation: Mapped[str | None] = mapped_column(String(20))
    remuneration_paise: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class VivaVoce(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "viva_voce"
    __mapper_args__ = _EAGER

    thesis_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("thesis_submissions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue_or_link: Mapped[str | None] = mapped_column(String(300))
    panel: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(String(20))
    report_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class EtdUpload(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "etd_uploads"
    __mapper_args__ = _EAGER

    thesis_id: Mapped[uuid.UUID] = _fk("thesis_submissions.id", "CASCADE", nullable=False)
    repository: Mapped[str] = mapped_column(String(20), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(200))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
