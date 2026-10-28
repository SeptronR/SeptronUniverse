"""SaaS models — Database_Schema.sql §32 (subscription plans, tenant subscriptions, usage meters, impersonation).

Phase 02 maps the four tables the entitlement and impersonation services need (Prompts/02 §02.3); Phase 38 adds
``platform_settings``, ``platform_announcements``, ``support_tickets``, ``pending_registrations`` and
``demo_requests`` (the website tables of §32 belong to Phase 40). Facts without columns (invoices, usage extras,
caps, ticket SLA / category / internal notes, registration tokens, CRM notes) live in the side stores described in
``app/services/saas/common.py``.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.base import UUIDPrimaryKeyMixin


class SubscriptionPlan(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "subscription_plans"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)  # starter | standard | professional | university
    price_paise_monthly: Mapped[int | None] = mapped_column(BigInteger)
    price_paise_yearly: Mapped[int | None] = mapped_column(BigInteger)
    student_limit: Mapped[int | None] = mapped_column(Integer)
    staff_limit: Mapped[int | None] = mapped_column(Integer)
    storage_gb: Mapped[int | None] = mapped_column(Integer)
    sms_credits: Mapped[int | None] = mapped_column(Integer)
    enabled_features: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InstitutionSubscription(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "institution_subscriptions"

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subscription_plans.id"), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date)
    billing_cycle: Mapped[str] = mapped_column(String(10), nullable=False, default="yearly")
    # trial | active | grace | expired | cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    grace_until: Mapped[date | None] = mapped_column(Date)
    payment_ref: Mapped[str | None] = mapped_column(String(80))
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UsageMeter(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "usage_meters"
    __table_args__ = (UniqueConstraint("institution_id", "period_month"),)

    institution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    active_students: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_staff: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sms_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    whatsapp_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emails_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    api_calls: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ImpersonationLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "impersonation_logs"

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE")
    )
    impersonator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    target_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any | None] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlatformAnnouncement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "platform_announcements"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # {type: all|plan|institution_type|institution_ids|roles, values: [...], channels: [banner, inapp, email]}
    audience: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SupportTicket(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_tickets"

    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutions.id", ondelete="CASCADE")
    )
    ticket_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    raised_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal")
    module: Mapped[str | None] = mapped_column(String(60))
    # open | in_progress | waiting | resolved | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # {"thread": [{by, at, text, attachments, internal}], "meta": {category, sla_due_at, breached, csat, ...}}
    messages: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PendingRegistration(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pending_registrations"

    institution_name: Mapped[str] = mapped_column(String(200), nullable=False)
    institution_type: Mapped[str] = mapped_column(String(30), nullable=False)
    slug: Mapped[str] = mapped_column(String(60), nullable=False)
    admin_name: Mapped[str | None] = mapped_column(String(200))
    admin_email: Mapped[str] = mapped_column(String(200), nullable=False)
    admin_phone: Mapped[str | None] = mapped_column(String(20))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("subscription_plans.id"))
    payment_ref: Mapped[str | None] = mapped_column(String(80))
    # pending | verified | paid | provisioned | failed | expired
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    institution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("institutions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DemoRequest(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "demo_requests"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    institution_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    institution_type: Mapped[str | None] = mapped_column(String(30))
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")  # new|contacted|converted|dropped
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def plan_limits(plan: SubscriptionPlan | None) -> dict[str, Any]:
    """Limits dict used by the entitlement service and the entitlements endpoint."""
    if plan is None:
        return {"students": None, "staff": None, "storage_gb": None, "sms_credits": None}
    return {
        "students": plan.student_limit,
        "staff": plan.staff_limit,
        "storage_gb": plan.storage_gb,
        "sms_credits": plan.sms_credits,
    }
