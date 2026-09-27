"""SaaS schemas — Prompts/02 §02.4 (entitlements) and the one-time ``/install`` bootstrap."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class EntitlementLimits(BaseModel):
    students: int | None = None
    staff: int | None = None
    storage_gb: int | None = None
    sms_credits: int | None = None


class EntitlementUsage(BaseModel):
    students: int = 0
    staff: int = 0
    storage_bytes: int = 0
    sms_sent: int = 0
    period_month: date | None = None


class EntitlementsResponse(BaseModel):
    institution_id: uuid.UUID
    plan: str | None = Field(default=None, description="plan code")
    plan_name: str | None = None
    tier: str | None = None
    status: str = Field(description="trial | active | grace | expired | cancelled | none")
    starts_on: date | None = None
    ends_on: date | None = None
    grace_until: date | None = None
    limits: EntitlementLimits
    usage: EntitlementUsage
    writable: bool = Field(default=True, description="false while in grace / expired")


class InstallRequest(BaseModel):
    install_key: str = Field(min_length=1, max_length=200)
    super_admin_email: EmailStr
    super_admin_password: str = Field(min_length=1, max_length=200)
    super_admin_username: str = Field(default="superadmin", min_length=3, max_length=80)


class InstallResponse(BaseModel):
    installed_at: datetime
    permissions: int
    role_templates: int
    features: int
    plans: int
    super_admin_id: uuid.UUID
