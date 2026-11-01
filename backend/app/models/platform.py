"""Platform models — sections 2-6 of Database_Schema.sql (copied, never retyped).

Phase 00 mapped the 20 tables the core skeleton depends on; Phase 01 completes the 44 platform models
(Prompts/01 §01.3) — ``scripts/phase_manifest.py["01"]`` lists them and ``check_schema_drift.py --phase 01`` must
report 0 diffs. Relationships are ``lazy="noload"``; repositories use explicit ``selectinload`` (Orbit convention).
Partitioned parents (``domain_events``, ``webhook_deliveries``, ``audit_logs``) carry ``postgresql_partition_by``;
their monthly children are created by ``tasks/platform.py:ensure_next_month`` and never mapped.
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
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CIDR, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import (
    CollegeScopedMixin,
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


class InstitutionProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "institution_profile"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    established_year: Mapped[int | None] = mapped_column(SmallInteger)
    vision: Mapped[str | None] = mapped_column(Text)
    mission: Mapped[str | None] = mapped_column(Text)
    accreditations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    recognitions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    social_links: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    head_title: Mapped[str | None] = mapped_column(String(60))
    head_name: Mapped[str | None] = mapped_column(String(200))
    head_signature_url: Mapped[str | None] = mapped_column(Text)
    seal_url: Mapped[str | None] = mapped_column(Text)
    letterhead_url: Mapped[str | None] = mapped_column(Text)


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


class Faculty(TenantModelMixin, Base):
    __tablename__ = "faculties"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "code"),)

    college_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dean_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK to staff added in §33


class Department(TenantModelMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "code"),)

    college_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("colleges.id", ondelete="CASCADE"), nullable=False, index=True
    )
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("faculties.id", ondelete="SET NULL")
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # academic | administrative | research_centre
    department_type: Mapped[str] = mapped_column(String(30), nullable=False, default="academic")
    hod_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK to staff added in §33
    established_year: Mapped[int | None] = mapped_column(SmallInteger)
    description: Mapped[str | None] = mapped_column(Text)


class InstitutionSetting(UUIDPrimaryKeyMixin, TenantMixin, CollegeScopedMixin, TimestampMixin, Base):
    __tablename__ = "institution_settings"
    # NULLS NOT DISTINCT (0045): institution-wide rows (college_id NULL) must collide for ON CONFLICT upserts
    __table_args__ = (
        UniqueConstraint("institution_id", "college_id", "category", "key", postgresql_nulls_not_distinct=True),
    )

    category: Mapped[str] = mapped_column(String(40), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[Any | None] = mapped_column(JSONB)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Holiday(
    UUIDPrimaryKeyMixin, TenantMixin, CollegeScopedMixin, TimestampMixin, SoftDeleteMixin, CreatedByMixin, Base
):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "holiday_date", "name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    # public | institution | restricted | exam_break
    holiday_type: Mapped[str] = mapped_column(String(30), nullable=False, default="public")
    applies_to: Mapped[str] = mapped_column(String(20), nullable=False, default="all")  # all | students | staff


class NumberSequence(UUIDPrimaryKeyMixin, TenantMixin, CollegeScopedMixin, TimestampMixin, Base):
    __tablename__ = "number_sequences"
    __table_args__ = (UniqueConstraint("institution_id", "college_id", "scope_key"),)

    scope_key: Mapped[str] = mapped_column(String(120), nullable=False)
    pattern: Mapped[str] = mapped_column(String(120), nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    padding: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=4)
    reset_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="never")  # never | yearly | per_term


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


class PasswordResetToken(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_sessions"

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    refresh_family: Mapped[str] = mapped_column(String(64), nullable=False)
    device_label: Mapped[str | None] = mapped_column(String(120))
    platform: Mapped[str | None] = mapped_column(String(20))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(60))


class MfaSecret(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "mfa_secrets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    recovery_codes_hashed: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class LoginHistory(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "login_history"

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    identifier: Mapped[str | None] = mapped_column(String(200))
    # success | bad_password | locked | mfa_failed | sso
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IpAllowlist(UUIDPrimaryKeyMixin, TenantMixin, CreatedByMixin, Base):
    __tablename__ = "ip_allowlists"
    __table_args__ = (UniqueConstraint("institution_id", "purpose", "cidr"),)

    purpose: Mapped[str] = mapped_column(String(40), nullable=False)  # exam_decode | results_publish | features | admin
    cidr: Mapped[str] = mapped_column(CIDR, nullable=False)
    label: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeviceToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_tokens"
    __table_args__ = (UniqueConstraint("provider", "token"),)

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # fcm | webpush | expo
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False)
    topics: Mapped[list[str] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CredentialSheet(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "credential_sheets"

    batch_label: Mapped[str | None] = mapped_column(String(120))
    audience: Mapped[str] = mapped_column(String(20), nullable=False)  # students | guardians | staff
    file_url: Mapped[str | None] = mapped_column(Text)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK to background_jobs added in §33


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


class ApiKey(UUIDPrimaryKeyMixin, TenantMixin, CreatedByMixin, Base):
    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    hashed_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Webhook(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "webhooks"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    events: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WebhookDelivery(Base):
    """Outbound webhook attempts (Phase 41 delivers). Partitioned monthly by ``created_at``; default partition in the SQL."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        PrimaryKeyConstraint("id", "created_at"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    response_code: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationConnection(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, CreatedByMixin, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (UniqueConstraint("institution_id", "capability", "provider", "label"),)

    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    config_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    public_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # configured | healthy | degraded | failed | disabled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="configured")
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class IntegrationHealthCheck(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "integration_health_checks"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration_connections.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)


class DataImport(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "data_imports"

    entity: Mapped[str] = mapped_column(String(60), nullable=False)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    mapping: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="dry_run")  # dry_run | apply
    # uploaded | validated | applying | applied | failed | rolled_back
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    total_rows: Mapped[int | None] = mapped_column(Integer)
    valid_rows: Mapped[int | None] = mapped_column(Integer)
    error_rows: Mapped[int | None] = mapped_column(Integer)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # FK to background_jobs added in §33
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataImportRow(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "data_import_rows"

    institution_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_imports.id", ondelete="CASCADE"), nullable=False
    )
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    normalized: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    errors: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ConsentRecord(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "consent_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # academic | communication | marketing | health | photo | third_party
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    text_version: Mapped[str | None] = mapped_column(String(20))
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(INET)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataSubjectRequest(UUIDPrimaryKeyMixin, TenantMixin, Base):
    __tablename__ = "data_subject_requests"

    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)  # access | export | correction | erasure
    # received | in_progress | completed | rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    details: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    result_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class HelpArticle(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "help_articles"
    __table_args__ = (UniqueConstraint("institution_id", "slug"),)

    # NULL = platform article (visible to every institution)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    module: Mapped[str | None] = mapped_column(String(60))
    # Phase 01 stored a role list; Phase 38 authoring writes {roles: [...], portals: [...], public: bool}
    audience: Mapped[dict[str, Any] | list[str] | None] = mapped_column(JSONB)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FeedbackEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "feedback_entries"

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    page: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(30))  # bug | idea | question | praise
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    message: Mapped[str | None] = mapped_column(Text)
    screenshot_url: Mapped[str | None] = mapped_column(Text)
    client: Mapped[str | None] = mapped_column(String(20))  # web | mobile | pwa
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")  # new | triaged | closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


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
