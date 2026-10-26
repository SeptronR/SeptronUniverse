"""Alumni, endowments & fundraising — section 27 ``alumni_profiles`` … ``donations`` (Prompts/29 §29.3).

DDL facts: ``alumni_profiles.student_id UNIQUE`` (one profile per student; legacy alumni get a ``students(status=
'alumni')`` stub), ``alumni_employment_history`` cascades with the profile, ``alumni_events.event_id`` wraps a Phase 25
``events(event_type='alumni')`` row, ``donations.receipt_document_id`` points at the Phase 26 ``issued_documents`` row
of the 80G receipt and ``donations.pan_encrypted`` holds the Fernet-encrypted PAN. Facts without a column (claim
status, per-field directory consent, engagement score, job moderation status / clicks, restricted-fund mapping,
milestones, anonymous display, refunds, online donation intents, contact requests, chapters) live in
``institution_settings`` rows of category ``alumni_meta`` (see ``app/services/alumni/common.py``).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = [
    "AlumniEmploymentHistory",
    "AlumniEvent",
    "AlumniJob",
    "AlumniProfile",
    "Donation",
    "FundraisingCampaign",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


class AlumniProfile(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "alumni_profiles"
    __mapper_args__ = _EAGER

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id"), nullable=False, unique=True
    )
    user_id: Mapped[uuid.UUID | None] = _fk("users.id")
    graduation_year: Mapped[int | None] = mapped_column(SmallInteger)
    program_id: Mapped[uuid.UUID | None] = _fk("programs.id")
    current_company: Mapped[str | None] = mapped_column(String(200))
    designation: Mapped[str | None] = mapped_column(String(120))
    city: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(80))
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    willing_to_mentor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    willing_to_recruit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_updated_by_alumni_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AlumniEmploymentHistory(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "alumni_employment_history"

    alumni_id: Mapped[uuid.UUID] = _fk("alumni_profiles.id", "CASCADE", nullable=False)
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    designation: Mapped[str | None] = mapped_column(String(120))
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AlumniEvent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "alumni_events"
    __mapper_args__ = _EAGER

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    held_on: Mapped[date | None] = mapped_column(Date)
    venue: Mapped[str | None] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(20), nullable=False, default="meet")
    registrations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_id: Mapped[uuid.UUID | None] = _fk("events.id")
    created_at: Mapped[datetime] = _now()


class AlumniJob(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "alumni_jobs"
    __mapper_args__ = _EAGER

    posted_by_alumni_id: Mapped[uuid.UUID | None] = _fk("alumni_profiles.id")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    location: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    expires_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class FundraisingCampaign(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "fundraising_campaigns"
    __mapper_args__ = _EAGER

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str | None] = mapped_column(Text)
    goal_paise: Mapped[int | None] = mapped_column(BigInteger)
    raised_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Donation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "donations"
    __mapper_args__ = _EAGER

    donor_type: Mapped[str] = mapped_column(String(20), nullable=False)  # alumni | corporate | individual
    donor_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = _fk("fundraising_campaigns.id")
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    on_date: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(20))
    receipt_no: Mapped[str | None] = mapped_column(String(40))
    is_80g: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pan_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    receipt_document_id: Mapped[uuid.UUID | None] = _fk("issued_documents.id")
    created_at: Mapped[datetime] = _now()
