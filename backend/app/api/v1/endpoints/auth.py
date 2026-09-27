"""Authentication endpoints — Prompts/02 §02.8 (router included with ``feature_required("core.auth")``).

Public (``PUBLIC_ROUTES``): login, send/verify OTP, refresh, forgot/reset password, SSO start/callback, install.
``[auth]`` routes use ``authenticated()``; MFA routes additionally carry ``feature_required("security.mfa")`` and
session routes ``security.session_management``. The pre-tenant flows run on the platform session (see
``services/auth_service.py``); the web refresh token travels as an httpOnly cookie scoped to ``/api/v1/auth/refresh``.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, authenticated, mfa_enrolment_principal
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.core.rate_limit import rate_limited, verify_captcha
from app.db.session import get_db, get_platform_db
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginHistoryResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MessageResponse,
    MfaConfirmRequest,
    MfaConfirmResponse,
    MfaDisableRequest,
    MfaSetupResponse,
    OtpSendRequest,
    OtpVerifyRequest,
    RecoveryCodesResponse,
    RefreshRequest,
    RefreshResponse,
    ResetPasswordRequest,
    SessionResponse,
    SsoStartResponse,
)
from app.schemas.common import Envelope
from app.services.auth_service import REFRESH_COOKIE, AuthService, refresh_cookie_kwargs
from app.utils.response import ok

router = APIRouter(prefix="/auth", tags=["auth"])


def _with_cookie(payload: dict[str, Any], refresh: str | None, platform: str) -> ORJSONResponse:
    resp = ORJSONResponse(content=payload)
    if refresh and platform not in {"android", "ios"}:
        resp.set_cookie(**refresh_cookie_kwargs(refresh))
    return resp


# ---- public -------------------------------------------------------------------------------------------------------
@router.post(
    "/login",
    summary="Password (+ MFA code) login",
    response_model=Envelope[LoginResponse],
    # per-client guard only: the real brute-force defence is the per-identifier lockout (auth_service rule 1), and a
    # whole campus can share one NAT address
    dependencies=[rate_limited("login", limit=120, window=60)],
)
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_platform_db)) -> Any:
    payload, refresh = await AuthService(db, request).login(body)
    return _with_cookie(ok(payload, message="Signed in"), refresh, body.platform)


@router.post(
    "/send-otp",
    summary="Send a one-time code to a phone or email",
    response_model=Envelope[dict[str, Any]],
    dependencies=[rate_limited("otp", limit=10, window=60)],
)
async def send_otp(
    body: OtpSendRequest, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    await verify_captcha(body.captcha_token, request.client.host if request.client else None)
    return ok(await AuthService(db, request).send_otp(body), message="Code sent")


@router.post(
    "/verify-otp",
    summary="OTP login",
    response_model=Envelope[LoginResponse],
    dependencies=[rate_limited("otp_verify", limit=20, window=60)],
)
async def verify_otp(body: OtpVerifyRequest, request: Request, db: AsyncSession = Depends(get_platform_db)) -> Any:
    payload, refresh = await AuthService(db, request).verify_otp(body)
    return _with_cookie(ok(payload, message="Signed in"), refresh, body.platform)


@router.post(
    "/refresh", summary="Rotate the refresh token → new access token", response_model=Envelope[RefreshResponse]
)
async def refresh(
    request: Request, body: RefreshRequest | None = None, db: AsyncSession = Depends(get_platform_db)
) -> Any:
    from_body = bool(body and body.refresh_token)
    token = body.refresh_token if body and body.refresh_token else request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Missing refresh token")
    access, new_refresh, _ = await AuthService(db, request).refresh(token, from_body)
    if from_body:
        return ok(RefreshResponse(access_token=access, refresh_token=new_refresh))
    resp = ORJSONResponse(content=ok(RefreshResponse(access_token=access)))
    resp.set_cookie(**refresh_cookie_kwargs(new_refresh))
    return resp


@router.post(
    "/forgot-password",
    summary="Request a password-reset link (always 200)",
    response_model=Envelope[MessageResponse],
    dependencies=[rate_limited("forgot", limit=5, window=900)],
)
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    await verify_captcha(body.captcha_token, request.client.host if request.client else None)
    await AuthService(db, request).forgot_password(body.identifier, body.institution_slug)
    return ok(MessageResponse(detail="If the account exists, a reset link has been sent"))


@router.post(
    "/reset-password", summary="Set a new password with a reset token", response_model=Envelope[MessageResponse]
)
async def reset_password(
    body: ResetPasswordRequest, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    await AuthService(db, request).reset_password(body)
    return ok(MessageResponse(detail="Password updated; sign in with the new password"), message="Password updated")


@router.get(
    "/sso/{provider}/start", summary="Begin an SSO login (redirect URL)", response_model=Envelope[SsoStartResponse]
)
async def sso_start(
    provider: str,
    request: Request,
    institution_slug: str | None = Query(default=None, max_length=60),
    login_hint: str | None = Query(default=None, max_length=200, description="mock provider: the email to sign in as"),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await AuthService(db, request).sso_start(provider, institution_slug, login_hint))


@router.get("/sso/{provider}/callback", summary="Complete an SSO login", response_model=Envelope[LoginResponse])
async def sso_callback(
    provider: str,
    request: Request,
    code: str = Query(min_length=1, max_length=2000),
    state: str = Query(min_length=1, max_length=2000),
    db: AsyncSession = Depends(get_platform_db),
) -> Any:
    payload, refresh = await AuthService(db, request).sso_callback(provider, code, state)
    return _with_cookie(ok(payload, message="Signed in"), refresh, "web")


# ---- authenticated -----------------------------------------------------------------------------------------------
@router.get(
    "/me",
    summary="Principal: user, permissions, features, scopes, visibility defaults",
    response_model=Envelope[MeResponse],
)
async def me(
    request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuthService(db, request, principal).me())


@router.post(
    "/logout", summary="Revoke the current session (all=true: every session)", response_model=Envelope[MessageResponse]
)
async def logout(
    request: Request,
    response: Response,
    all: bool = Query(default=False),  # noqa: A002
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    n = await AuthService(db, request, principal).logout(all)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth/refresh")
    return ok(MessageResponse(detail="Signed out", extra={"revoked": n}), message="Signed out")


@router.post(
    "/change-password", summary="Change the own password (policy enforced)", response_model=Envelope[MessageResponse]
)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await AuthService(db, request, principal).change_password(body)
    return ok(MessageResponse(detail="Password changed"), message="Password changed")


@router.post(
    "/mfa/setup",
    summary="Start TOTP enrolment (secret + QR); also accepts the mfa_setup token",
    response_model=Envelope[MfaSetupResponse],
    dependencies=[feature_required("security.mfa")],
)
async def mfa_setup(
    request: Request, principal: Principal = Depends(mfa_enrolment_principal), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuthService(db, request, principal).mfa_setup())


@router.post(
    "/mfa/confirm",
    summary="Confirm enrolment with a code → recovery codes",
    response_model=Envelope[MfaConfirmResponse],
    dependencies=[feature_required("security.mfa")],
)
async def mfa_confirm(
    body: MfaConfirmRequest,
    request: Request,
    principal: Principal = Depends(mfa_enrolment_principal),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result, refresh = await AuthService(db, request, principal).mfa_confirm(body.code)
    return _with_cookie(ok(result, message="Multi-factor authentication enabled"), refresh, "web")


@router.post(
    "/mfa/disable",
    summary="Disable MFA (password + code)",
    response_model=Envelope[MessageResponse],
    dependencies=[feature_required("security.mfa")],
)
async def mfa_disable(
    body: MfaDisableRequest,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await AuthService(db, request, principal).mfa_disable(body)
    return ok(MessageResponse(detail="Multi-factor authentication disabled"), message="MFA disabled")


@router.post(
    "/mfa/recovery-codes/regenerate",
    summary="Issue a fresh set of recovery codes",
    response_model=Envelope[RecoveryCodesResponse],
    dependencies=[feature_required("security.mfa")],
)
async def mfa_recovery_codes(
    request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuthService(db, request, principal).regenerate_recovery_codes())


@router.get(
    "/sessions",
    summary="Active sessions of the signed-in user",
    response_model=Envelope[list[SessionResponse]],
    dependencies=[feature_required("security.session_management")],
)
async def sessions(
    request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuthService(db, request, principal).list_sessions())


@router.delete(
    "/sessions",
    summary="Revoke every other session",
    response_model=Envelope[MessageResponse],
    dependencies=[feature_required("security.session_management")],
)
async def revoke_other_sessions(
    request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    n = await AuthService(db, request, principal).revoke_other_sessions()
    return ok(MessageResponse(detail=f"{n} session(s) revoked", extra={"revoked": n}), message="Sessions revoked")


@router.delete(
    "/sessions/{id}",
    summary="Revoke one session",
    response_model=Envelope[MessageResponse],
    dependencies=[feature_required("security.session_management")],
)
async def revoke_session(
    id: uuid.UUID, request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await AuthService(db, request, principal).revoke_session(id)
    return ok(MessageResponse(detail="Session revoked"), message="Session revoked")


@router.get(
    "/login-history",
    summary="Recent sign-in attempts of the signed-in user",
    response_model=Envelope[list[LoginHistoryResponse]],
)
async def login_history(
    request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuthService(db, request, principal).login_history())


@router.post("/impersonation/stop", summary="End the current impersonation", response_model=Envelope[MessageResponse])
async def impersonation_stop(
    request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await AuthService(db, request, principal).stop_impersonation()
    return ok(MessageResponse(detail="Impersonation ended"), message="Impersonation ended")
