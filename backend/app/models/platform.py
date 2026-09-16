"""Platform models — sections 2-6 of Database_Schema.sql (copied, never retyped).

Phase 00 maps the tables the core skeleton depends on (tenancy, auth, RBAC, features, jobs, events, idempotency,
workflow, read-only mode, audit). Phase 01 completes the 44 platform models and the ``0001`` revision.
Relationships are ``lazy="noload"``; repositories use explicit ``selectinload`` (Orbit convention).
Partitioned parents (``domain_events``, ``audit_logs``) carry ``postgresql_partition_by``.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import (
    CreatedByMixin,
    OptimisticLockMixin,
    SoftDeleteMixin,
    TenantMixin,
    TenantModelMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

# ===================================== 2. TENANCY =====================================


class Institution(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, OptimisticLockMixin, Base):
    __tablename__ = "institutions"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(60))
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    code: Mapped[str | None] = mapped_column(String(20))
    # university | deemed_university | autonomous_college | affiliated_college | standalone_college | multi_campus
    institution_type: Mapped[str] = mapped_column(String(30), nullable=False)
    regulatory_pack: Mapped[str] = mapped_column(String(10), nullable=False, default="IN")
    pack_version: Mapped[str | None] = mapped_column(String(20))
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="Asia/Kolkata")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-IN")
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="INR")
    parent_university_name: Mapped[str | None] = mapped_column(String(200))
    aishe_code: Mapped[str | None] = mapped_column(String(20))
    aicte_pid: Mapped[str | None] = mapped_column(String(30))
    naac_id: Mapped[str | None] = mapped_column(String(30))
    ugc_status: Mapped[str | None] = mapped_column(String(40))
    gstin: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    contact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    logo_url: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(Text)
    # pending | active | suspended | archived
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")


class College(TenantModelMixin, Base):
    __tablename__ = "colleges"
    __table_args__ = (UniqueConstraint("institution_id", "code"),)

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(60))
    # constituent | affiliated | autonomous | campus | deemed_unit | study_centre | main
    college_type: Mapped[str] = mapped_column(String(30), nullable=False, default="constituent")
    affiliation_number: Mapped[str | None] = mapped_column(String(40))
    affiliated_since: Mapped[date | None] = mapped_column(Date)
    principal_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    exam_centre_code: Mapped[str | None] = mapped_column(String(20))
    is_exam_centre: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    aishe_code: Mapped[str | None] = mapped_column(String(20))
    aicte_pid: Mapped[str | None] = mapped_column(String(30))
    gstin: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    contact: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    logo_url: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str | None] = mapped_column(String(60))
    is_main: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


# ===================================== 3. AUTH =====================================


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, OptimisticLockMixin, CreatedByMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("institution_id", "username"),)

    # NULL for platform users
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(200))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    # staff | student | guardian | alumni | applicant | recruiter | external | platform
    user_type: Mapped[str] = mapped_column(String(30), nullable=False, default="staff")
    is_super_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    locale: Mapped[str | None] = mapped_column(String(10))
    timezone: Mapped[str | None] = mapped_column(String(60))
    preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ===================================== 4. RBAC =====================================


class Permission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (UniqueConstraint("module", "action"),)

    module: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_platform: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Role(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, OptimisticLockMixin, CreatedByMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("institution_id", "slug"),)

    # NULL = platform role template
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="institution")
    portal: Mapped[str | None] = mapped_column(String(30))


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", "scope_type", "scope_id"),)

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    # institution | college | faculty | department | program | offering | self | committee | hostel
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="institution")
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ===================================== 5. FEATURES =====================================


class PlatformFeature(Base):
    __tablename__ = "platform_features"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    group_name: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    default_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_plan_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="starter")
    depends_on: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_core: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    config_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InstitutionFeatureFlag(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "institution_feature_flags"
    __table_args__ = (UniqueConstraint("institution_id", "feature_key"),)

    feature_key: Mapped[str] = mapped_column(
        String(80), ForeignKey("platform_features.key", ondelete="CASCADE"), nullable=False
    )
    platform_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    institution_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="plan")  # plan | override
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    set_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FeatureFlagChange(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "feature_flag_changes"

    feature_key: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


# ===================================== 6. PLATFORM SERVICES =====================================


class BackgroundJob(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "background_jobs"

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # queued | running | succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(String(255))
    result_url: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DomainEvent(Base):
    """Transactional outbox (ADR 0005). Partitioned monthly by ``created_at``; default partition in the SQL."""

    __tablename__ = "domain_events"
    __table_args__ = (
        PrimaryKeyConstraint("id", "created_at"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_type: Mapped[str | None] = mapped_column(String(60))
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # pending | dispatched | failed | dead
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventConsumption(Base):
    __tablename__ = "event_consumptions"

    consumer: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IdempotencyKey(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "route", "idempotency_key"),)

    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    route: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    response_code: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowDefinition(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (UniqueConstraint("institution_id", "key", "version"),)

    module: Mapped[str] = mapped_column(String(60), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # [{order, approver:{type: role|scope_rule|user, value}, mode: sequential|parallel, sla_hours, escalate_to}]
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class WorkflowInstance(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "workflow_instances"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "definition_id"),)

    definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_definitions.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    # pending | approved | rejected | cancelled | escalated
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    current_step: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class WorkflowStep(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "workflow_steps"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    approver_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    approver_role_slug: Mapped[str | None] = mapped_column(String(60))
    # pending | approved | rejected | skipped | escalated | delegated
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    acted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WorkflowDelegation(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "workflow_delegations"

    from_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    module: Mapped[str | None] = mapped_column(String(60))
    from_on: Mapped[date] = mapped_column(Date, nullable=False)
    to_on: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ReadOnlyMode(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "read_only_modes"

    # NULL = platform-wide
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE")
    )
    reason: Mapped[str | None] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    set_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AuditLog(Base):
    """Hash-chained audit trail. Partitioned monthly by ``occurred_at``; the DB trigger computes the chain."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        PrimaryKeyConstraint("id", "occurred_at"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    impersonator_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    module: Mapped[str] = mapped_column(String(60), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    record_type: Mapped[str | None] = mapped_column(String(60))
    record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    old_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(40))
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
