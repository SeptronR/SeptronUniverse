"""Auth schemas — Prompts/02 §02.4 (login, OTP, refresh, password flows, MFA, sessions, principal, impersonation)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, model_validator

from app.core.authz.masking import MaskedEmail, MaskedPhone
from app.schemas.common import ORMModel
from app.schemas.platform import InstitutionSummary

ClientPlatform = Literal["web", "pwa", "android", "ios", "script"]


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=200, description="username | email | phone")
    password: str = Field(min_length=1, max_length=200)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=20, description="TOTP or recovery code")
    institution_slug: str | None = Field(
        default=None, max_length=60, description="required when the identifier is ambiguous"
    )
    platform: ClientPlatform = "web"
    device_label: str | None = Field(default=None, max_length=120)


class OtpSendRequest(BaseModel):
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    institution_slug: str | None = Field(default=None, max_length=60)
    captcha_token: str | None = None

    @model_validator(mode="after")
    def _one_destination(self) -> "OtpSendRequest":
        if not (self.phone or self.email) or (self.phone and self.email):
            raise ValueError("provide exactly one of phone or email")
        return self


class OtpVerifyRequest(BaseModel):
    phone: str | None = Field(default=None, max_length=20)
    email: EmailStr | None = None
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    institution_slug: str | None = Field(default=None, max_length=60)
    platform: ClientPlatform = "web"
    device_label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _one_destination(self) -> "OtpVerifyRequest":
        if not (self.phone or self.email) or (self.phone and self.email):
            raise ValueError("provide exactly one of phone or email")
        return self


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, description="mobile clients (web uses the httpOnly cookie)")


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str | None = Field(default=None, description="only for mobile clients (body-based refresh)")


class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=200)
    institution_slug: str | None = Field(default=None, max_length=60)
    captcha_token: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_url: str
    qr_png_base64: str


class MfaConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MfaConfirmResponse(BaseModel):
    recovery_codes: list[str]
    access_token: str | None = Field(default=None, description="full session when confirmed with the mfa_setup token")


class MfaDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=6, max_length=20)


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class SessionResponse(BaseModel):
    id: uuid.UUID
    device_label: str | None = None
    platform: str | None = None
    ip_masked: str | None = None
    user_agent: str | None = None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool = False


class LoginHistoryResponse(ORMModel):
    id: uuid.UUID
    outcome: str
    ip: str | None = None
    user_agent: str | None = None
    occurred_at: datetime


class ScopeOut(BaseModel):
    scope_type: str
    scope_id: uuid.UUID | None = None
    label: str | None = None


class MeUser(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID | None = None
    username: str
    email: MaskedEmail = None
    phone: MaskedPhone = None
    display_name: str | None = None
    avatar_url: str | None = None
    user_type: str
    is_super_admin: bool = False
    role_slugs: list[str] = Field(default_factory=list)
    scopes: list[ScopeOut] = Field(default_factory=list)
    mfa_enabled: bool = False
    must_change_password: bool = False
    locale: str | None = None
    timezone: str | None = None
    valid_to: datetime | None = None
    impersonator_id: uuid.UUID | None = None
    impersonation_read_only: bool = False


class VisibilityDefault(BaseModel):
    self: bool = True
    scopes: list[str] = Field(default_factory=list)
    default: str = "self"


class PrincipalPayload(BaseModel):
    user: MeUser
    institution: InstitutionSummary | None = None
    permissions: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    scopes: list[ScopeOut] = Field(default_factory=list)
    visibility_defaults: dict[str, VisibilityDefault] = Field(default_factory=dict)
    session_id: uuid.UUID | None = None


class LoginResponse(PrincipalPayload):
    access_token: str
    refresh_token: str | None = Field(default=None, description="mobile clients only; web receives the cookie")
    mfa_required: bool = False
    mfa_setup_required: bool = False


class MeResponse(PrincipalPayload):
    # Phase 38: shell banners — subscription state, provider outage, API cap, active impersonation, announcements
    banners: dict[str, Any] | None = None


class SsoStartResponse(BaseModel):
    provider: str
    authorize_url: str
    state: str


class ImpersonateRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ImpersonateResponse(BaseModel):
    access_token: str
    user: MeUser
    impersonation_log_id: uuid.UUID
    read_only: bool = False


class MessageResponse(BaseModel):
    detail: str
    extra: dict[str, Any] = Field(default_factory=dict)
