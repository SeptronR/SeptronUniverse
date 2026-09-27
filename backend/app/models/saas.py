"""SaaS models — Database_Schema.sql §32 (subscription plans, tenant subscriptions, usage meters, impersonation).

Phase 02 maps the four tables the entitlement and impersonation services need (Prompts/02 §02.3); Phase 38 adds the
rest of §32 (``platform_settings``, announcements, support tickets, registrations, website tables).
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
