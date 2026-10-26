"""Accreditation & compliance (IQAC) — section 29 ``accreditation_frameworks`` … ``audit_registers`` (Prompts/32 §32.3).

DDL facts: frameworks, criteria and metric definitions are platform rows (no ``institution_id``; seeded by ``0001``
§36 and ``0032``). ``metric_values`` is UNIQUE on ``(institution_id, college_id, metric_key, period_label,
program_id)`` — NULL college / programme rows are the institution-level values, so the upsert matches with ``IS NOT
DISTINCT FROM`` under ``FOR UPDATE``. ``criterion_responses`` is UNIQUE per ``(cycle_id, framework_criterion_id)``.
``audit_registers.findings`` is the JSON finding list ``[{no, text, owner_staff_id, due_on, status, action_taken}]``.
Facts without a column (override proposals / stale auto values, evidence suggestions and versions, response versions /
due dates / workflow, cycle exports, submission diffs / corrections, consistency results, disclosures) live in
``institution_settings`` rows of category ``accreditation_meta`` (see ``app/services/accreditation/common.py``).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import TenantMixin, UUIDPrimaryKeyMixin
from app.models.registration import _fk, _now, _updated

__all__ = [
    "AccreditationCycle",
    "AccreditationFramework",
    "AuditRegister",
    "ComplianceSubmission",
    "CriterionResponse",
    "EvidenceDocument",
    "FrameworkCriterion",
    "MetricDefinition",
    "MetricValue",
]

_EAGER: dict[str, Any] = {"eager_defaults": True}


class AccreditationFramework(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "accreditation_frameworks"
    __mapper_args__ = _EAGER

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[str | None] = mapped_column(String(20))
    pack: Mapped[str] = mapped_column(String(10), nullable=False, default="IN")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()


class FrameworkCriterion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "framework_criteria"
    __table_args__ = (UniqueConstraint("framework_id", "code"),)

    framework_id: Mapped[uuid.UUID] = _fk("accreditation_frameworks.id", "CASCADE", nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = _fk("framework_criteria.id")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    metric_type: Mapped[str] = mapped_column(String(20), nullable=False, default="quantitative")
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    period_type: Mapped[str] = mapped_column(String(20), nullable=False, default="academic_year")
    metric_key: Mapped[str | None] = mapped_column(String(80))
    sequence: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class MetricDefinition(Base):
    __tablename__ = "metric_definitions"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(20))
    source_module: Mapped[str | None] = mapped_column(String(40))
    computation_key: Mapped[str] = mapped_column(String(80), nullable=False)
    params_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_derived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    depends_on: Mapped[list[str] | None] = mapped_column(JSONB)
    pack: Mapped[str] = mapped_column(String(10), nullable=False, default="IN")


class MetricValue(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "metric_values"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "metric_key", "period_label", "program_id"),)

    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id", "CASCADE")
    metric_key: Mapped[str] = mapped_column(String(80), ForeignKey("metric_definitions.key"), nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    program_id: Mapped[uuid.UUID | None] = _fk("programs.id")
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    numerator: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    denominator: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    override_reason: Mapped[str | None] = mapped_column(Text)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class EvidenceDocument(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "evidence_documents"
    __mapper_args__ = _EAGER

    framework_criterion_id: Mapped[uuid.UUID | None] = _fk("framework_criteria.id")
    metric_key: Mapped[str | None] = mapped_column(String(80))
    period_label: Mapped[str | None] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_type: Mapped[str | None] = mapped_column(String(40))
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _now()


class AccreditationCycle(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "accreditation_cycles"
    __mapper_args__ = _EAGER

    framework_id: Mapped[uuid.UUID] = _fk("accreditation_frameworks.id", nullable=False)
    college_id: Mapped[uuid.UUID | None] = _fk("colleges.id")
    program_id: Mapped[uuid.UUID | None] = _fk("programs.id")
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    submission_due_on: Mapped[date | None] = mapped_column(Date)
    coordinator_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planning")
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    grade: Mapped[str | None] = mapped_column(String(5))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class CriterionResponse(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "criterion_responses"
    __table_args__ = (UniqueConstraint("cycle_id", "framework_criterion_id"),)
    __mapper_args__ = _EAGER

    cycle_id: Mapped[uuid.UUID] = _fk("accreditation_cycles.id", "CASCADE", nullable=False)
    framework_criterion_id: Mapped[uuid.UUID] = _fk("framework_criteria.id", nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text)
    metric_value_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    evidence_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    owner_staff_id: Mapped[uuid.UUID | None] = _fk("staff.id")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = _updated()


class ComplianceSubmission(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "compliance_submissions"
    __mapper_args__ = _EAGER

    framework_id: Mapped[uuid.UUID | None] = _fk("accreditation_frameworks.id")
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    submission_type: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    file_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    submitted_on: Mapped[date | None] = mapped_column(Date)
    ack_ref: Mapped[str | None] = mapped_column(String(80))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()


class AuditRegister(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "audit_registers"
    __mapper_args__ = _EAGER

    audit_type: Mapped[str] = mapped_column(String(30), nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    auditor: Mapped[str | None] = mapped_column(String(200))
    report_url: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _updated()
