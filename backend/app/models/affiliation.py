"""Affiliation — section 31 ``affiliation_applications`` … ``exam_centres`` (Prompts/34 §34.3).

``ExamCentre`` moved here from the Phase 14 stub (same table, no data migration; ``app.models.exams`` re-exports it).
DDL facts the services rely on: ``affiliation_program_approvals`` is UNIQUE on ``(college_id, program_id,
academic_year_id)``; ``affiliation_fee_schedules`` UNIQUE ``(academic_year_id, fee_type)`` (no ``updated_at``);
``college_data_submissions`` UNIQUE ``(college_id, term_id, submission_type)`` — a returned submission is resubmitted on
the same row and earlier versions are kept in the side store; ``exam_centres`` UNIQUE ``(exam_session_id,
centre_code)`` (no ``updated_at``). Facts without a column (application number, scrutiny / inspection trail, decision
conditions and resolution, order document; college documents vault / last inspection; submission versions and validation
report; centre appointment letters) live in ``institution_settings`` rows of category ``affiliation_meta`` (see
``app/services/affiliation/common.py``).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = [
    "AffiliationApplication",
    "AffiliationFeeSchedule",
    "AffiliationProgramApproval",
    "CollegeDataSubmission",
    "ExamCentre",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class AffiliationApplication(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "affiliation_applications"
    __mapper_args__ = _EAGER

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    application_type: Mapped[str] = mapped_column(String(30), nullable=False)
    programs: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    documents: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fee_invoice_id: Mapped[uuid.UUID | None] = _fk("fee_invoices.id")
    inspection_committee: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    inspection_on: Mapped[date | None] = mapped_column(Date)
    inspection_report_url: Mapped[str | None] = mapped_column(Text)
    deficiencies: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    decided_by: Mapped[uuid.UUID | None] = _uuid()
    order_no: Mapped[str | None] = mapped_column(String(60))
    order_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AffiliationProgramApproval(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "affiliation_program_approvals"
    __table_args__ = (UniqueConstraint("college_id", "program_id", "academic_year_id"),)
    __mapper_args__ = _EAGER

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    program_id: Mapped[uuid.UUID] = _fk("programs.id", nullable=False)
    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    sanctioned_intake: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lateral_intake: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="provisional")
    order_no: Mapped[str | None] = mapped_column(String(60))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AffiliationFeeSchedule(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "affiliation_fee_schedules"
    __table_args__ = (UniqueConstraint("academic_year_id", "fee_type"),)

    academic_year_id: Mapped[uuid.UUID] = _fk("academic_years.id", nullable=False)
    fee_type: Mapped[str] = mapped_column(String(30), nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    per_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="flat")


class CollegeDataSubmission(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "college_data_submissions"
    __table_args__ = (UniqueConstraint("college_id", "term_id", "submission_type"),)
    __mapper_args__ = _EAGER

    college_id: Mapped[uuid.UUID] = _fk("colleges.id", "CASCADE", nullable=False)
    term_id: Mapped[uuid.UUID] = _fk("academic_terms.id", nullable=False)
    exam_session_id: Mapped[uuid.UUID | None] = _fk("exam_sessions.id")
    submission_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    record_count: Mapped[int | None] = mapped_column(Integer)
    file_url: Mapped[str | None] = mapped_column(Text)
    submitted_by: Mapped[uuid.UUID | None] = _uuid()
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


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
