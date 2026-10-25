"""Placement, internships & training — section 27 ``companies`` … ``company_feedback`` (Prompts/28 §28.3).

DDL facts: ``companies UNIQUE (institution_id, name)`` (recruiters bound through ``recruiter_user_ids`` JSON array),
``drive_rounds UNIQUE (drive_id, round_no)``, ``drive_applications UNIQUE (drive_id, student_program_enrollment_id)``,
``drive_round_results UNIQUE (application_id, round_id)``, ``placement_offers.application_id UNIQUE`` (one offer per
application), ``student_placement_profiles.student_program_enrollment_id UNIQUE``, ``training_attendance UNIQUE
(program_id, student_program_enrollment_id)``. Facts without a column (blacklist expiry, drive publication counts,
recruiter-submitted offers awaiting confirmation, readiness scores, vendor costs) live in ``institution_settings`` rows
of category ``placement_meta``; internship NOC / evaluation details live in ``internships.evaluation``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
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
from app.models.base import (
    OptimisticLockMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.registration import _fk, _now, _updated

__all__ = [
    "Company",
    "CompanyFeedback",
    "DriveApplication",
    "DriveRound",
    "DriveRoundResult",
    "Internship",
    "PlacementDrive",
    "PlacementOffer",
    "PlacementPolicy",
    "StudentPlacementProfile",
    "TrainingAttendance",
    "TrainingProgram",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Company(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, OptimisticLockMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(80))
    website: Mapped[str | None] = mapped_column(Text)
    hq_city: Mapped[str | None] = mapped_column(String(80))
    tier: Mapped[str | None] = mapped_column(String(20))
    contacts: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    recruiter_user_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)


class PlacementDrive(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "placement_drives"
    __mapper_args__ = _EAGER

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    company_id: Mapped[uuid.UUID] = _fk("companies.id", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_role: Mapped[str | None] = mapped_column(String(120))
    job_type: Mapped[str] = mapped_column(String(20), nullable=False, default="full_time")
    ctc_min_paise: Mapped[int | None] = mapped_column(BigInteger)
    ctc_max_paise: Mapped[int | None] = mapped_column(BigInteger)
    stipend_paise: Mapped[int | None] = mapped_column(Integer)
    locations: Mapped[list[str] | None] = mapped_column(JSONB)
    bond: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    eligibility_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    registration_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    drive_on: Mapped[date | None] = mapped_column(Date)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="on_campus")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    jd_url: Mapped[str | None] = mapped_column(Text)
    owner_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class DriveRound(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "drive_rounds"
    __table_args__ = (UniqueConstraint("drive_id", "round_no"),)

    drive_id: Mapped[uuid.UUID] = _fk("placement_drives.id", "CASCADE", nullable=False)
    round_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    round_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue: Mapped[str | None] = mapped_column(String(200))


class DriveApplication(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "drive_applications"
    __table_args__ = (UniqueConstraint("drive_id", "student_program_enrollment_id"),)
    __mapper_args__ = _EAGER

    drive_id: Mapped[uuid.UUID] = _fk("placement_drives.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    eligibility_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    override_by: Mapped[uuid.UUID | None] = _uuid()
    override_reason: Mapped[str | None] = mapped_column(Text)
    resume_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="applied")
    applied_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class DriveRoundResult(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "drive_round_results"
    __table_args__ = (UniqueConstraint("application_id", "round_id"),)

    application_id: Mapped[uuid.UUID] = _fk("drive_applications.id", "CASCADE", nullable=False)
    round_id: Mapped[uuid.UUID] = _fk("drive_rounds.id", "CASCADE", nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    remarks: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[uuid.UUID | None] = _uuid()
    recorded_at: Mapped[datetime] = _now()


class PlacementOffer(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "placement_offers"
    __mapper_args__ = _EAGER

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drive_applications.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    company_id: Mapped[uuid.UUID] = _fk("companies.id", nullable=False)
    role: Mapped[str | None] = mapped_column(String(120))
    ctc_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ctc_breakup: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    location: Mapped[str | None] = mapped_column(String(120))
    offer_letter_url: Mapped[str | None] = mapped_column(Text)
    offered_on: Mapped[date | None] = mapped_column(Date)
    joining_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="offered")
    is_ppo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class PlacementPolicy(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "placement_policies"
    __mapper_args__ = _EAGER

    batch_id: Mapped[uuid.UUID | None] = _fk("batches.id")
    program_id: Mapped[uuid.UUID | None] = _fk("programs.id")
    max_offers: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    dream_ctc_threshold_paise: Mapped[int | None] = mapped_column(BigInteger)
    allow_upgrade_if_dream: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    opt_out_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rules: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class StudentPlacementProfile(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "student_placement_profiles"
    __mapper_args__ = _EAGER

    student_program_enrollment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_program_enrollments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    resume_url: Mapped[str | None] = mapped_column(Text)
    resume_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    skills: Mapped[list[str] | None] = mapped_column(JSONB)
    is_opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opt_out_reason: Mapped[str | None] = mapped_column(String(30))
    higher_studies: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    placement_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unplaced")
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blacklist_reason: Mapped[str | None] = mapped_column(Text)
    consent_share_profile: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = _updated()


class Internship(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "internships"
    __mapper_args__ = _EAGER

    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    company_id: Mapped[uuid.UUID | None] = _fk("companies.id")
    company_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(120))
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date | None] = mapped_column(Date)
    stipend_paise: Mapped[int | None] = mapped_column(Integer)
    mentor: Mapped[str | None] = mapped_column(String(160))
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    certificate_url: Mapped[str | None] = mapped_column(Text)
    noc_document_id: Mapped[uuid.UUID | None] = _fk("issued_documents.id")
    credits_course_id: Mapped[uuid.UUID | None] = _fk("courses.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ongoing")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class TrainingProgram(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "training_programs"
    __mapper_args__ = _EAGER

    training_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    trainer: Mapped[str | None] = mapped_column(String(160))
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)
    batches: Mapped[list[str] | None] = mapped_column(JSONB)
    sessions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class TrainingAttendance(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "training_attendance"
    __table_args__ = (UniqueConstraint("program_id", "student_program_enrollment_id"),)

    program_id: Mapped[uuid.UUID] = _fk("training_programs.id", "CASCADE", nullable=False)
    student_program_enrollment_id: Mapped[uuid.UUID] = _fk("student_program_enrollments.id", "CASCADE", nullable=False)
    sessions_attended: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))


class CompanyFeedback(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "company_feedback"

    drive_id: Mapped[uuid.UUID] = _fk("placement_drives.id", "CASCADE", nullable=False)
    ratings: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    remarks: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[uuid.UUID | None] = _uuid()
    submitted_at: Mapped[datetime] = _now()
