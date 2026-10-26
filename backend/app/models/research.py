"""Research & faculty development — section 28 ``publications`` … ``incubation_startups`` (Prompts/30 §30.3).

DDL facts: ``publications.authors`` is the JSON author list (``[{name, staff_id?, scholar_id?, is_corresponding}]``) —
co-authors inside the institution share one row and each tagged author sees it as their own; ``publications.scholar_id``
references ``research_scholars`` (Phase 31). ``research_projects.grant_ledger_id`` points at the Phase 23
``grant_ledgers`` row created by the ``research.project_sanctioned`` consumer (``grant_ledgers.research_project_id``
points back without an FK). ``ethics_approvals`` doubles as the application (``decision`` NULL while under review).
Facts without a column (publication verification level / remarks / import source, project reports / staff / expense
requests / ethics category, consultancy receipts / share override, incentive computed amount, MoU workflow / version
history, ethics amendments / adverse events, API snapshots) live in ``institution_settings`` rows of category
``research_meta`` (see ``app/services/research/common.py``).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, Index, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = [
    "Collaboration",
    "Consultancy",
    "EthicsApproval",
    "EthicsCommittee",
    "FacultyAward",
    "FacultyDevelopment",
    "IncubationStartup",
    "Mou",
    "Patent",
    "Publication",
    "ResearchIncentive",
    "ResearchProject",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


def _uuid() -> Any:
    return mapped_column(UUID(as_uuid=True))


class Publication(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "publications"
    __table_args__ = (Index("ix_publications_staff", "staff_id", "year"),)
    __mapper_args__ = _EAGER

    staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    scholar_id: Mapped[uuid.UUID | None] = _fk("research_scholars.id", "SET NULL")
    pub_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    venue: Mapped[str | None] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    doi: Mapped[str | None] = mapped_column(String(120))
    issn_isbn: Mapped[str | None] = mapped_column(String(30))
    indexing: Mapped[str | None] = mapped_column(String(20))
    impact_factor: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    authors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    author_position: Mapped[int | None] = mapped_column(SmallInteger)
    citations: Mapped[int | None] = mapped_column(Integer)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[uuid.UUID | None] = _uuid()
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Patent(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "patents"
    __mapper_args__ = _EAGER

    staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    application_no: Mapped[str | None] = mapped_column(String(60))
    country: Mapped[str | None] = mapped_column(String(60))
    filed_on: Mapped[date | None] = mapped_column(Date)
    published_on: Mapped[date | None] = mapped_column(Date)
    granted_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="filed")
    co_inventors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    evidence_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class EthicsCommittee(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "ethics_committees"
    __mapper_args__ = _EAGER

    committee_type: Mapped[str] = mapped_column(String(10), nullable=False)
    committee_id: Mapped[uuid.UUID | None] = _uuid()
    members: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    registration_no: Mapped[str | None] = mapped_column(String(60))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class EthicsApproval(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "ethics_approvals"
    __mapper_args__ = _EAGER

    ethics_committee_id: Mapped[uuid.UUID] = _fk("ethics_committees.id", nullable=False)
    project_title: Mapped[str] = mapped_column(String(500), nullable=False)
    pi_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    submitted_on: Mapped[date | None] = mapped_column(Date)
    decision: Mapped[str | None] = mapped_column(String(20))
    approval_no: Mapped[str | None] = mapped_column(String(60))
    valid_to: Mapped[date | None] = mapped_column(Date)
    document_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ResearchProject(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "research_projects"
    __mapper_args__ = _EAGER

    pi_staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    co_pi: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    funding_agency: Mapped[str | None] = mapped_column(String(200))
    scheme: Mapped[str | None] = mapped_column(String(160))
    sanctioned_paise: Mapped[int | None] = mapped_column(BigInteger)
    received_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    start_on: Mapped[date | None] = mapped_column(Date)
    end_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="applied")
    utilisation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    budget_heads: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    ethics_approval_id: Mapped[uuid.UUID | None] = _fk("ethics_approvals.id")
    grant_ledger_id: Mapped[uuid.UUID | None] = _fk("grant_ledgers.id")
    sanction_letter_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Consultancy(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "consultancies"
    __mapper_args__ = _EAGER

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    client: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    institution_share_paise: Mapped[int | None] = mapped_column(BigInteger)
    start_on: Mapped[date | None] = mapped_column(Date)
    end_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ongoing")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class ResearchIncentive(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "research_incentives"
    __mapper_args__ = _EAGER

    incentive_type: Mapped[str] = mapped_column(String(30), nullable=False)
    staff_id: Mapped[uuid.UUID] = _fk("staff.id", nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    justification: Mapped[str | None] = mapped_column(Text)
    linked_entity: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    workflow_instance_id: Mapped[uuid.UUID | None] = _uuid()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class FacultyDevelopment(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "faculty_developments"
    __mapper_args__ = _EAGER

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    organiser: Mapped[str | None] = mapped_column(String(200))
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="attended")
    hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))
    certificate_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class FacultyAward(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "faculty_awards"
    __mapper_args__ = _EAGER

    staff_id: Mapped[uuid.UUID] = _fk("staff.id", "CASCADE", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    agency: Mapped[str | None] = mapped_column(String(200))
    year: Mapped[int | None] = mapped_column(SmallInteger)
    level: Mapped[str | None] = mapped_column(String(20))
    evidence_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Mou(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "mous"
    __mapper_args__ = _EAGER

    partner: Mapped[str] = mapped_column(String(200), nullable=False)
    partner_type: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str | None] = mapped_column(String(60))
    mou_type: Mapped[str] = mapped_column(String(20), nullable=False)
    signed_on: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    activities: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    document_url: Mapped[str | None] = mapped_column(Text)
    coordinator_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class Collaboration(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "collaborations"
    __mapper_args__ = _EAGER

    mou_id: Mapped[uuid.UUID | None] = _fk("mous.id")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    collaboration_type: Mapped[str] = mapped_column(String(20), nullable=False)
    participants: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    from_on: Mapped[date | None] = mapped_column(Date)
    to_on: Mapped[date | None] = mapped_column(Date)
    outcomes: Mapped[list[Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class IncubationStartup(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "incubation_startups"
    __mapper_args__ = _EAGER

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    founders: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    sector: Mapped[str | None] = mapped_column(String(80))
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="idea")
    funding_paise: Mapped[int | None] = mapped_column(BigInteger)
    mentor_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    registered_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
