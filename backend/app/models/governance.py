"""Governance — section 30 ``committees`` … ``policies`` (Prompts/33 §33.3).

``Committee`` / ``CommitteeMember`` stay mapped in ``app/models/post_result.py`` (Phase 16 / 27 created rows through them
— same tables, no data migration) and are re-exported here. DDL facts the services rely on: ``resolutions`` is UNIQUE on
``(institution_id, number)`` and hangs off a meeting (the committee is reached through ``meetings.committee_id``);
``legal_cases`` UNIQUE ``(institution_id, case_no)``; ``rti_requests`` UNIQUE ``(institution_id, request_no)``;
``audit_paras`` UNIQUE ``(audit_register_id, para_no)``; ``efiles`` UNIQUE ``(institution_id, file_no)``;
``efile_movements`` is append-only (no ``updated_at``). Facts without a column (meeting notice / minutes versions /
corrigenda / workflow, ATR decisions, hearings, RTI consultations / appeal decisions, para replies, file links,
policy owner / summary / acknowledgements / supersession) live in ``institution_settings`` rows of category
``governance_meta`` (see ``app/services/governance/common.py``).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.post_result import Committee, CommitteeMember
from app.models.registration import _fk, _now, _updated

__all__ = [
    "ActionTakenReport",
    "AuditPara",
    "Committee",
    "CommitteeMember",
    "Efile",
    "EfileMovement",
    "LegalCase",
    "Meeting",
    "Policy",
    "Resolution",
    "RtiRequest",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Meeting(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "meetings"
    __mapper_args__ = _EAGER

    committee_id: Mapped[uuid.UUID] = _fk("committees.id", "CASCADE", nullable=False)
    meeting_no: Mapped[str | None] = mapped_column(String(20))
    held_on: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    venue_or_link: Mapped[str | None] = mapped_column(String(300))
    agenda: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    quorum_met: Mapped[bool | None] = mapped_column(Boolean)
    attendance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    minutes_url: Mapped[str | None] = mapped_column(Text)
    minutes_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    created_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Resolution(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "resolutions"
    __table_args__ = (UniqueConstraint("institution_id", "number"),)
    __mapper_args__ = _EAGER

    meeting_id: Mapped[uuid.UUID] = _fk("meetings.id", "CASCADE", nullable=False)
    number: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    action_owner_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="passed")
    linked_entity: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class ActionTakenReport(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "action_taken_reports"
    __mapper_args__ = _EAGER

    resolution_id: Mapped[uuid.UUID] = _fk("resolutions.id", "CASCADE", nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[Any] | None] = mapped_column(JSONB)
    submitted_by: Mapped[uuid.UUID | None] = _uuid()
    submitted_at: Mapped[datetime] = _now()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="submitted")


class LegalCase(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "legal_cases"
    __table_args__ = (UniqueConstraint("institution_id", "case_no"),)
    __mapper_args__ = _EAGER

    case_no: Mapped[str] = mapped_column(String(60), nullable=False)
    court: Mapped[str | None] = mapped_column(String(160))
    case_type: Mapped[str | None] = mapped_column(String(60))
    parties: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    counsel: Mapped[str | None] = mapped_column(String(200))
    filed_on: Mapped[date | None] = mapped_column(Date)
    next_hearing: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    documents: Mapped[list[Any] | None] = mapped_column(JSONB)
    outcome: Mapped[str | None] = mapped_column(Text)
    owner_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class RtiRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "rti_requests"
    __table_args__ = (UniqueConstraint("institution_id", "request_no"),)
    __mapper_args__ = _EAGER

    request_no: Mapped[str] = mapped_column(String(40), nullable=False)
    applicant: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    pio_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    fee_paise: Mapped[int | None] = mapped_column(Integer)
    response_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    first_appeal: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    responded_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AuditPara(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "audit_paras"
    __table_args__ = (UniqueConstraint("audit_register_id", "para_no"),)
    __mapper_args__ = _EAGER

    audit_register_id: Mapped[uuid.UUID] = _fk("audit_registers.id", "CASCADE", nullable=False)
    para_no: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    owner_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    reply_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Efile(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "efiles"
    __table_args__ = (UniqueConstraint("institution_id", "file_no"),)
    __mapper_args__ = _EAGER

    file_no: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60))
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    current_holder_user_id: Mapped[uuid.UUID | None] = _uuid()
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class EfileMovement(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "efile_movements"
    __mapper_args__ = _EAGER

    efile_id: Mapped[uuid.UUID] = _fk("efiles.id", "CASCADE", nullable=False)
    from_user_id: Mapped[uuid.UUID | None] = _uuid()
    to_user_id: Mapped[uuid.UUID | None] = _uuid()
    noting: Mapped[str | None] = mapped_column(Text)
    attachments: Mapped[list[Any] | None] = mapped_column(JSONB)
    action: Mapped[str] = mapped_column(String(20), nullable=False, default="forward")
    moved_at: Mapped[datetime] = _now()


class Policy(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "policies"
    __mapper_args__ = _EAGER

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60))
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    approved_resolution_id: Mapped[uuid.UUID | None] = _fk("resolutions.id")
    effective_from: Mapped[date | None] = mapped_column(Date)
    file_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
