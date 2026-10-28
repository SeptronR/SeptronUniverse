"""Authentication — Prompts/02 §02.6 ``auth_service`` (login, OTP, refresh rotation, sessions, MFA, passwords, SSO).

Sessions: the pre-tenant flows (login, OTP, forgot/reset, refresh, SSO) run on the **platform session** (BYPASSRLS)
because they must find a user before any tenant context exists — ``_common.ps1`` logs in with identifier + password
only. Everything after ``get_current_user`` runs on the tenant session pinned by the token claims.

Business rules
1. ``login``: resolve the institution (body ``institution_slug`` → ``X-Institution-Slug`` / host → ``X-Institution-Id``;
   otherwise a cross-tenant match that must be unique → else 422 asking for the slug); refuse inactive / not-yet-valid
   / expired (time-boxed) accounts with 401 (message "account expired"); lockout key ``login_fail:{inst}:{identifier}``
   — ``LOGIN_LOCKOUT_ATTEMPTS`` failures inside ``LOGIN_LOCKOUT_MINUTES`` → 429 RATE_LIMITED; bcrypt verify; MFA when the
   user enrolled or the role requires it (``security.mfa`` effective and slug ∈ ``MFA_REQUIRED_ROLES`` /
   ``institution_settings[security.mfa_required_roles]``): no code → ``403 MFA_REQUIRED`` (``mfa_setup_required`` +
   a 10-minute ``mfa_setup`` token when not enrolled), wrong code → 401 (counts as a failure); success → session row
   (``refresh_family``, ``refresh_jti``), httpOnly ``refresh_token`` cookie (web) or body token (mobile), access token
   carrying ``sid``, ``login_history`` row, ``last_login_at``.
2. ``refresh``: decode → session by ``refresh_jti``; unknown-but-family-known or already revoked → **reuse detected**
   → revoke the whole family → 401; else rotate (new jti, same family), extend ``expires_at``, new access token.
3. ``logout``: revoke the session (``all=true`` → every session of the user), blacklist the access JTI until ``exp``,
   emit ``session.revoked``.
4. OTP: ``send_otp`` → Redis ``otp:{dest}`` (6 digits, ``OTP_TTL_SECONDS``), resend guard ``otp_rate:{dest}``
   (1/min → 429), Celery ``notifications.send_sms_otp`` / ``send_email_otp`` (mock providers); ``verify_otp`` logs the
   user in like rule 1 without the MFA step (the OTP is the second factor by policy).
5. Passwords: forgot (sha256 token, ``PASSWORD_RESET_TTL_MINUTES``, single-use, email through the notifications task +
   event ``user.password_reset_requested``), reset, change (policy ≥ 10 chars, 3 of 4 classes, not in the last 5
   hashes kept in ``users.preferences.password_history``), ``must_change_password`` cleared; other sessions revoked.
6. MFA: ``setup`` (pyotp secret encrypted with ``INTEGRATION_ENCRYPTION_KEY``, QR PNG), ``confirm`` (10 hashed
   single-use recovery codes; a limited-token confirmation also opens a session), ``disable`` (password + code),
   ``regenerate_recovery_codes``.
7. Sessions: list (self, masked IPs), revoke one / all others; login history (self).
8. ``load_principal``: (Phase 03: refused with 403 while the institution is suspended/archived — so is sign-in)
   user + valid role assignments (+ scopes) + flat permissions + effective features + impersonation
   claims (``imp`` / ``imp_log`` / ``imp_ro``) + ``sid``.
9. SSO hook (``security.sso``): ``start`` builds the provider redirect through the ``sso`` adapter (mock in this
   phase; ``login_hint`` picks the identity), ``callback`` verifies the signed ``state``, JIT-links a verified user by
   email or creates one with the roles mapped in ``institution_settings[security.sso_role_map]``.
10. ``ip_allowlisted(purpose)`` lives in ``core/authz/ip_allowlist.py`` (Phase 15 routes).
"""

import base64
import io
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.users.visibility  # noqa: F401  (registers the users visibility module)
from app.core import events
from app.core.audit import log_audit
from app.core.authz.dependencies import Principal
from app.core.authz.visibility import MODULES as VISIBILITY_MODULES
from app.core.authz.visibility import VisibilityResolver
from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.core.features import FEATURE_REGISTRY, effective_features, is_enabled
from app.core.rbac.registry import MFA_REQUIRED_ROLES
from app.core.security import (
    check_password_policy,
    create_access_token,
    create_limited_token,
    create_refresh_token,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    generate_totp_secret,
    hash_password,
    sha256_hex,
    sign_payload,
    token_ttl_seconds,
    totp_uri,
    verify_password,
    verify_signed,
    verify_totp,
)
from app.db.session import redis_client
from app.enums.auth import LoginOutcome
from app.models.platform import Institution, Permission, Role, RolePermission, User, UserRole
from app.repositories.platform_repository import PlatformConfigRepository
from app.repositories.session_repository import (
    LoginHistoryRepository,
    MfaRepository,
    PasswordResetRepository,
    SessionRepository,
)
from app.repositories.subscription_repository import ImpersonationRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_role_repository import UserRoleRepository
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginHistoryResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    MeUser,
    MfaConfirmResponse,
    MfaDisableRequest,
    MfaSetupResponse,
    OtpSendRequest,
    OtpVerifyRequest,
    PrincipalPayload,
    RecoveryCodesResponse,
    ResetPasswordRequest,
    ScopeOut,
    SessionResponse,
    SsoStartResponse,
    VisibilityDefault,
)
from app.schemas.platform import InstitutionSummary

log = structlog.get_logger()
MOBILE_PLATFORMS = {"android", "ios"}
REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth/refresh"


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def mask_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    if ":" in ip:
        parts = ip.split(":")
        return ":".join(parts[:3]) + ":…"
    octets = ip.split(".")
    return ".".join(octets[:2]) + ".x.x" if len(octets) == 4 else "…"


# ---- principal ---------------------------------------------------------------------------------------------------
async def load_principal(db: AsyncSession, user_id: uuid.UUID, request: Request | None = None) -> Principal:
    """Rule 8 — the contract used by ``core/authz/dependencies.py`` (and the WebSocket hub)."""
    user = (
        await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None), User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "User not found or inactive")
    now = datetime.now(UTC)
    if user.valid_to is not None and user.valid_to < now:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "This account expired")
    await ensure_institution_active(db, user.institution_id)
    assignments = (
        await db.execute(
            select(UserRole.role_id, UserRole.scope_type, UserRole.scope_id, Role.slug)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.user_id == user.id,
                Role.deleted_at.is_(None),
                Role.is_active.is_(True),
                (UserRole.valid_from.is_(None)) | (UserRole.valid_from <= now),
                (UserRole.valid_to.is_(None)) | (UserRole.valid_to >= now),
            )
        )
    ).all()
    role_ids = {a.role_id for a in assignments}
    roles = sorted({a.slug for a in assignments})
    scopes: list[tuple[str, uuid.UUID | None]] = sorted(
        {(a.scope_type, a.scope_id) for a in assignments}, key=lambda s: (s[0], str(s[1]))
    )
    permissions: set[str] = set()
    if role_ids:
        rows = (
            await db.execute(
                select(Permission.module, Permission.action)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id.in_(role_ids))
            )
        ).all()
        permissions = {f"{m}:{a}" for m, a in rows}
    if user.institution_id:
        features = await effective_features(user.institution_id)
    else:
        features = {k for k, f in FEATURE_REGISTRY.items() if f.default_enabled or f.is_core}
    claims: dict[str, Any] = getattr(request.state, "claims", {}) if request is not None else {}
    impersonator = (
        uuid.UUID(claims["imp"])
        if claims.get("imp")
        else (getattr(request.state, "impersonator_id", None) if request is not None else None)
    )
    sid = uuid.UUID(claims["sid"]) if claims.get("sid") else None
    return Principal(
        user, roles, permissions, scopes, features, impersonator_id=impersonator, session_id=sid, claims=claims
    )


async def ensure_institution_active(db: AsyncSession, institution_id: uuid.UUID | None) -> None:
    """Phase 03: a suspended / archived institution refuses sign-in and every existing token of its users."""
    if institution_id is None:
        return
    status = (await db.execute(select(Institution.status).where(Institution.id == institution_id))).scalar_one_or_none()
    if status is not None and status not in ("active", "pending"):
        raise APIError(
            403,
            ErrorCode.PERMISSION_DENIED,
            f"This institution is {status}; contact the SeptronUniverse team",
            {"reason": f"institution_{status}", "code": f"INSTITUTION_{status.upper()}"},
        )


# ---- service ------------------------------------------------------------------------------------------------------
class AuthService:
    def __init__(self, db: AsyncSession, request: Request | None = None, principal: Principal | None = None):
        self.db, self.request, self.principal = db, request, principal
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.history = LoginHistoryRepository(db)
        self.mfa = MfaRepository(db)
        self.resets = PasswordResetRepository(db)
        self.config = PlatformConfigRepository(db)

    # ---- institution + user resolution ---------------------------------------------------------------------------
    async def resolve_institution(self, slug: str | None) -> Institution | None:
        state = self.request.state if self.request is not None else None
        slug = slug or (getattr(state, "institution_slug", None) if state else None)
        if slug:
            inst = await self.config.institution_by_slug(slug)
            if inst is None:
                # Phase 03: a suspended / archived tenant answers 403 institution_<status>, not "unknown"
                other = (
                    await self.db.execute(
                        select(Institution.id).where(Institution.slug == slug, Institution.deleted_at.is_(None))
                    )
                ).scalar_one_or_none()
                if other is not None:
                    await ensure_institution_active(self.db, other)
                raise APIError(404, ErrorCode.NOT_FOUND, "Unknown institution", {"institution_slug": slug})
            return inst
        header_id = getattr(state, "institution_id", None) if state else None
        if header_id:
            try:
                iid = uuid.UUID(str(header_id))
            except ValueError:
                raise APIError(422, ErrorCode.VALIDATION, "Invalid X-Institution-Id") from None
            return (await self.db.execute(select(Institution).where(Institution.id == iid))).scalar_one_or_none()
        return None

    async def find_user(self, identifier: str, institution: Institution | None) -> User | None:
        if institution is not None:
            return await self.users.get_by_identifier(identifier, institution.id)
        matches = list(await self.users.find_by_identifier_any(identifier))
        if len(matches) > 1:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "This identifier exists in more than one institution; pass institution_slug",
                {"field": "institution_slug"},
            )
        return matches[0] if matches else None

    # ---- rule 1 ---------------------------------------------------------------------------------------------------
    async def login(self, body: LoginRequest) -> tuple[LoginResponse, str]:
        institution = await self.resolve_institution(body.institution_slug)
        user = await self.find_user(body.identifier, institution)
        lock_scope = (
            str(institution.id)
            if institution
            else (str(user.institution_id) if user and user.institution_id else "platform")
        )
        await self._check_lockout(lock_scope, body.identifier)
        if user is None or not verify_password(body.password, user.password_hash):
            await self._failure(lock_scope, body.identifier, user, LoginOutcome.BAD_PASSWORD)
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid credentials")
        await self._check_account_window(user, body.identifier)
        await ensure_institution_active(self.db, user.institution_id)
        institution = institution or await self._institution_of(user)
        roles = await self._role_slugs(user)
        if await self._mfa_required(user, roles, institution):
            enrolled = await self._mfa_enrolled(user)
            if not body.mfa_code:
                await self.history.record(
                    institution_id=user.institution_id,
                    user_id=user.id,
                    identifier=body.identifier,
                    outcome=LoginOutcome.MFA_REQUIRED,
                    ip=client_ip(self.request),
                    user_agent=self._ua(),
                )
                await self.db.commit()
                details: dict[str, Any] = {"mfa_required": True, "mfa_setup_required": not enrolled}
                if not enrolled:
                    details["mfa_setup_token"] = create_limited_token(
                        user.id, "mfa_setup", settings.MFA_SETUP_TOKEN_MINUTES, inst=str(user.institution_id or "")
                    )
                raise APIError(
                    403,
                    ErrorCode.MFA_REQUIRED,
                    "Multi-factor code required" if enrolled else "Multi-factor enrolment required",
                    details,
                )
            if not enrolled or not await self._verify_mfa_code(user, body.mfa_code):
                await self._failure(lock_scope, body.identifier, user, LoginOutcome.MFA_FAILED)
                raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid multi-factor code", {"mfa_required": True})
        return await self._open_session(
            user,
            institution,
            roles,
            body.identifier,
            body.platform,
            body.device_label,
            LoginOutcome.SUCCESS,
            lock_scope,
        )

    async def _open_session(
        self,
        user: User,
        institution: Institution | None,
        roles: list[str],
        identifier: str,
        platform: str,
        device_label: str | None,
        outcome: str,
        lock_scope: str | None = None,
    ) -> tuple[LoginResponse, str]:
        await ensure_institution_active(self.db, user.institution_id)
        now = datetime.now(UTC)
        family, jti = uuid.uuid4().hex, uuid.uuid4().hex
        session = await self.sessions.create(
            institution_id=user.institution_id,
            user_id=user.id,
            refresh_jti=jti,
            refresh_family=family,
            device_label=(device_label or _device_from_ua(self._ua()))[:120] if (device_label or self._ua()) else None,
            platform=platform[:20],
            ip=client_ip(self.request),
            user_agent=self._ua(),
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        refresh = create_refresh_token(user.id, family, jti)
        access = create_access_token(user.id, user.institution_id, user.is_super_admin, session_id=session.id)
        user.last_login_at = now
        await self.history.record(
            institution_id=user.institution_id,
            user_id=user.id,
            identifier=identifier,
            outcome=outcome,
            ip=client_ip(self.request),
            user_agent=self._ua(),
        )
        if lock_scope:
            await redis_client.delete(f"login_fail:{lock_scope}:{identifier.strip().lower()}")
        principal = await self._principal_for(user, session.id)
        payload = await self.principal_payload(principal, institution)
        response = LoginResponse(
            access_token=access,
            refresh_token=refresh if platform in MOBILE_PLATFORMS else None,
            **_payload_fields(payload),
        )
        return response, refresh

    async def _principal_for(self, user: User, session_id: uuid.UUID | None) -> Principal:
        """Principal without a request (platform session) — used right after login/OTP/SSO."""
        if self.request is not None:
            self.request.state.claims = {"sid": str(session_id)} if session_id else {}  # type: ignore[union-attr]
        return await load_principal(self.db, user.id, self.request)

    async def _check_lockout(self, scope: str, identifier: str) -> None:
        key = f"login_fail:{scope}:{identifier.strip().lower()}"
        count = int(await redis_client.get(key) or 0)
        if count >= settings.LOGIN_LOCKOUT_ATTEMPTS:
            ttl = await redis_client.ttl(key)
            raise APIError(
                429,
                ErrorCode.RATE_LIMITED,
                f"Too many failed attempts; try again in {max(int(ttl or 0) // 60, 1)} minutes",
                {"retry_after": max(int(ttl or 0), 1), "reason": "login_lockout"},
            )

    async def _failure(self, scope: str, identifier: str, user: User | None, outcome: str) -> None:
        key = f"login_fail:{scope}:{identifier.strip().lower()}"
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, settings.LOGIN_LOCKOUT_MINUTES * 60)
        await self.history.record(
            institution_id=user.institution_id if user else None,
            user_id=user.id if user else None,
            identifier=identifier,
            outcome=LoginOutcome.LOCKED if count >= settings.LOGIN_LOCKOUT_ATTEMPTS else outcome,
            ip=client_ip(self.request),
            user_agent=self._ua(),
        )
        await self.db.commit()  # the caller raises 401/429 and the session dependency would roll the row back

    async def _check_account_window(self, user: User, identifier: str) -> None:
        now = datetime.now(UTC)
        if not user.is_active or user.deleted_at is not None:
            await self.history.record(
                institution_id=user.institution_id,
                user_id=user.id,
                identifier=identifier,
                outcome=LoginOutcome.INACTIVE,
                ip=client_ip(self.request),
                user_agent=self._ua(),
            )
            await self.db.commit()
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "This account is inactive")
        if (user.valid_from is not None and user.valid_from > now) or (
            user.valid_to is not None and user.valid_to < now
        ):
            await self.history.record(
                institution_id=user.institution_id,
                user_id=user.id,
                identifier=identifier,
                outcome=LoginOutcome.EXPIRED,
                ip=client_ip(self.request),
                user_agent=self._ua(),
            )
            await self.db.commit()
            raise APIError(
                401,
                ErrorCode.UNAUTHENTICATED,
                (
                    "This account expired"
                    if user.valid_to is not None and user.valid_to < now
                    else "This account is not active yet"
                ),
                {
                    "valid_from": user.valid_from.isoformat() if user.valid_from else None,
                    "valid_to": user.valid_to.isoformat() if user.valid_to else None,
                },
            )

    async def _institution_of(self, user: User) -> Institution | None:
        if user.institution_id is None:
            return None
        return (
            await self.db.execute(select(Institution).where(Institution.id == user.institution_id))
        ).scalar_one_or_none()

    async def _role_slugs(self, user: User) -> list[str]:
        rows = await UserRoleRepository(self.db).for_user(user.id)
        now = datetime.now(UTC)
        return sorted(
            {
                r.slug
                for ur, r in rows
                if (ur.valid_from is None or ur.valid_from <= now) and (ur.valid_to is None or ur.valid_to >= now)
            }
        )

    async def _mfa_required(self, user: User, roles: list[str], institution: Institution | None) -> bool:
        if user.mfa_enabled:
            return True
        if institution is not None:
            if not await is_enabled(institution.id, "security.mfa"):
                return False
            configured = await self.config.institution_setting(institution.id, "security", "mfa_required_roles")
            required = set(configured) if isinstance(configured, list) else set(MFA_REQUIRED_ROLES)
        else:
            if not FEATURE_REGISTRY["security.mfa"].default_enabled:
                return False
            required = set(MFA_REQUIRED_ROLES)
            if user.is_super_admin:
                return "super_admin" in required
        return any(r in required for r in roles)

    async def _mfa_enrolled(self, user: User) -> bool:
        row = await self.mfa.get(user.id)
        return row is not None and row.confirmed_at is not None

    async def _verify_mfa_code(self, user: User, code: str) -> bool:
        row = await self.mfa.get(user.id)
        if row is None or row.confirmed_at is None:
            return False
        code = code.strip()
        if verify_totp(decrypt_secret(row.secret_encrypted), code):
            return True
        hashed = sha256_hex(code.lower())
        if hashed in (row.recovery_codes_hashed or []):
            row.recovery_codes_hashed = [h for h in row.recovery_codes_hashed if h != hashed]  # single use
            await self.db.flush()
            return True
        return False

    def _ua(self) -> str | None:
        return self.request.headers.get("user-agent") if self.request is not None else None

    # ---- principal payload (/auth/me + login) --------------------------------------------------------------------
    async def principal_payload(self, principal: Principal, institution: Institution | None = None) -> PrincipalPayload:
        user = principal.user
        if institution is None and user.institution_id:
            institution = await self._institution_of(user)
        ur = UserRoleRepository(self.db)
        scopes = [
            ScopeOut(scope_type=st, scope_id=sid, label=await ur.scope_label(st, sid) if sid else None)
            for st, sid in principal.scopes
        ]
        resolver = VisibilityResolver(principal)
        defaults = {
            m: VisibilityDefault(self=meta.self, scopes=meta.scopes, default=meta.default)
            for m in sorted(VISIBILITY_MODULES)
            for meta in [resolver.meta(m)]
        }
        me = MeUser(
            id=user.id,
            institution_id=user.institution_id,
            username=user.username,
            email=user.email,
            phone=user.phone,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            user_type=user.user_type,
            is_super_admin=user.is_super_admin,
            role_slugs=principal.roles,
            scopes=scopes,
            mfa_enabled=user.mfa_enabled,
            must_change_password=user.must_change_password,
            locale=user.locale,
            timezone=user.timezone,
            valid_to=user.valid_to,
            impersonator_id=principal.impersonator_id,
            impersonation_read_only=principal.impersonation_read_only,
        )
        return PrincipalPayload(
            user=me,
            institution=InstitutionSummary.model_validate(institution) if institution is not None else None,
            permissions=sorted(principal.permissions),
            features=sorted(principal.features),
            scopes=scopes,
            visibility_defaults=defaults,
            session_id=principal.session_id,
        )

    async def me(self) -> MeResponse:
        assert self.principal is not None
        payload = await self.principal_payload(self.principal)
        from app.services.saas.banners import banners

        return MeResponse(**_payload_fields(payload), banners=await banners(self.db, self.principal))

    # ---- rule 2 ---------------------------------------------------------------------------------------------------
    async def refresh(self, token: str, from_body: bool) -> tuple[str, str, User]:
        claims = decode_token(token, expected_type="refresh")
        family, jti = str(claims.get("family")), str(claims.get("jti"))
        session = await self.sessions.get_by_jti(jti, for_update=True)
        if session is None or session.revoked_at is not None:
            if session is not None or await self.sessions.family_known(family):
                revoked = await self.sessions.revoke_family(family, "reuse_detected")
                log.warning("refresh_token_reuse", family=family, revoked=revoked)
                await events.emit(
                    self.db,
                    institution_id=session.institution_id if session else None,
                    event_type="session.revoked",
                    payload={"family": family, "reason": "reuse_detected", "count": revoked},
                    aggregate_type="user_session",
                    aggregate_id=session.id if session else None,
                    actor_user_id=uuid.UUID(claims["sub"]),
                )
                # the request ends with 401 and the session dependency would roll back: commit the revocation first
                await self.db.commit()
                raise APIError(401, ErrorCode.UNAUTHENTICATED, "Refresh token reuse detected; sign in again")
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Unknown session; sign in again")
        now = datetime.now(UTC)
        if session.expires_at <= now:
            await self.sessions.revoke(session, "expired")
            await self.db.commit()
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Session expired; sign in again")
        user = await self.users.get_any(session.user_id)
        if user is None or not user.is_active or (user.valid_to is not None and user.valid_to < now):
            await self.sessions.revoke(session, "account_inactive")
            await self.db.commit()
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "This account is inactive or expired")
        new_jti = uuid.uuid4().hex
        await self.sessions.rotate(session, new_jti, now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
        access = create_access_token(user.id, user.institution_id, user.is_super_admin, session_id=session.id)
        return access, create_refresh_token(user.id, family, new_jti), user

    # ---- rule 3 ---------------------------------------------------------------------------------------------------
    async def logout(self, all_sessions: bool) -> int:
        assert self.principal is not None
        p = self.principal
        count = 0
        if all_sessions:
            count = await self.sessions.revoke_all(p.id, "logout_all")
        elif p.session_id is not None:
            session = await self.sessions.get(p.session_id)
            if session is not None:
                await self.sessions.revoke(session, "logout")
                count = 1
        jti = p.claims.get("jti")
        if jti:
            await redis_client.set(f"blacklist:jti:{jti}", "1", ex=token_ttl_seconds(p.claims))
        await events.emit(
            self.db,
            institution_id=p.institution_id,
            event_type="session.revoked",
            payload={"user_id": str(p.id), "all": all_sessions, "count": count, "reason": "logout"},
            aggregate_type="user_session",
            aggregate_id=p.session_id,
            actor_user_id=p.id,
        )
        return count

    # ---- rule 4 ---------------------------------------------------------------------------------------------------
    async def send_otp(self, body: OtpSendRequest) -> dict[str, Any]:
        dest = (body.phone or body.email or "").strip()
        rate_key = f"otp_rate:{dest.lower()}"
        if await redis_client.exists(rate_key):
            ttl = await redis_client.ttl(rate_key)
            raise APIError(
                429,
                ErrorCode.RATE_LIMITED,
                "OTP already sent; wait before requesting another",
                {"retry_after": max(int(ttl or 0), 1)},
            )
        institution = await self.resolve_institution(body.institution_slug)
        user = await self.find_user(dest, institution)
        await redis_client.set(rate_key, "1", ex=settings.OTP_RESEND_SECONDS)
        if user is not None and user.is_active:
            code = f"{secrets.randbelow(10**6):06d}"
            await redis_client.set(f"otp:{dest.lower()}", code, ex=settings.OTP_TTL_SECONDS)
            task = "notifications.send_sms_otp" if body.phone else "notifications.send_email_otp"
            _send_task(
                task,
                {
                    "institution_id": str(user.institution_id) if user.institution_id else None,
                    "destination": dest,
                    "code": code,
                    "ttl": settings.OTP_TTL_SECONDS,
                },
            )
            if settings.APP_ENV == "development":
                log.info("otp_issued_dev", destination=dest[:3] + "…", ttl=settings.OTP_TTL_SECONDS)
        return {"sent": True, "ttl_seconds": settings.OTP_TTL_SECONDS, "resend_after": settings.OTP_RESEND_SECONDS}

    async def verify_otp(self, body: OtpVerifyRequest) -> tuple[LoginResponse, str]:
        dest = (body.phone or body.email or "").strip()
        institution = await self.resolve_institution(body.institution_slug)
        user = await self.find_user(dest, institution)
        lock_scope = (
            str(institution.id)
            if institution
            else (str(user.institution_id) if user and user.institution_id else "platform")
        )
        await self._check_lockout(lock_scope, dest)
        stored = await redis_client.get(f"otp:{dest.lower()}")
        if user is None or not stored or stored != body.code:
            await self._failure(lock_scope, dest, user, LoginOutcome.BAD_PASSWORD)
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid or expired code")
        await redis_client.delete(f"otp:{dest.lower()}")
        await self._check_account_window(user, dest)
        institution = institution or await self._institution_of(user)
        roles = await self._role_slugs(user)
        return await self._open_session(
            user, institution, roles, dest, body.platform, body.device_label, LoginOutcome.OTP, lock_scope
        )

    # ---- rule 5 ---------------------------------------------------------------------------------------------------
    async def forgot_password(self, identifier: str, institution_slug: str | None) -> None:
        institution = await self.resolve_institution(institution_slug)
        try:
            user = await self.find_user(identifier, institution)
        except APIError:
            user = None  # ambiguous identifier: never reveal anything
        if user is None or not user.is_active or not user.email:
            return
        raw = secrets.token_urlsafe(32)
        await self.resets.create(user.id, sha256_hex(raw), settings.PASSWORD_RESET_TTL_MINUTES)
        reset_url = f"{settings.frontend_url}/reset-password?token={raw}"
        _send_task(
            "notifications.send_password_reset",
            {
                "institution_id": str(user.institution_id) if user.institution_id else None,
                "user_id": str(user.id),
                "email": user.email,
                "reset_url": reset_url,
                "ttl_minutes": settings.PASSWORD_RESET_TTL_MINUTES,
            },
        )
        await events.emit(
            self.db,
            institution_id=user.institution_id,
            event_type="user.password_reset_requested",
            payload={"user_id": str(user.id)},
            aggregate_type="user",
            aggregate_id=user.id,
            actor_user_id=user.id,
        )

    async def reset_password(self, body: ResetPasswordRequest) -> None:
        row = await self.resets.get_valid(sha256_hex(body.token))
        if row is None:
            raise APIError(400, ErrorCode.VALIDATION, "Invalid or expired reset token", {"field": "token"})
        user = await self.users.get_any(row.user_id)
        if user is None or not user.is_active:
            raise APIError(400, ErrorCode.VALIDATION, "Invalid or expired reset token", {"field": "token"})
        await self._set_password(user, body.password, keep_session=None)
        await self.resets.mark_used(row)
        await log_audit(
            self.db,
            principal=None,
            module="users",
            action="password_reset",
            record_type="user",
            record_id=user.id,
            request=self.request,
        )

    async def change_password(self, body: ChangePasswordRequest) -> None:
        assert self.principal is not None
        user = self.principal.user
        if not verify_password(body.current_password, user.password_hash):
            raise APIError(
                401, ErrorCode.UNAUTHENTICATED, "Current password is incorrect", {"field": "current_password"}
            )
        if body.current_password == body.new_password:
            raise APIError(
                422, ErrorCode.VALIDATION, "New password must differ from the current one", {"field": "new_password"}
            )
        await self._set_password(user, body.new_password, keep_session=self.principal.session_id)
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="password_change",
            record_type="user",
            record_id=user.id,
            request=self.request,
        )

    async def _set_password(self, user: User, password: str, keep_session: uuid.UUID | None) -> None:
        prefs = dict(user.preferences or {})
        history: list[str] = list(prefs.get("password_history") or [])
        check_password_policy(password, history + ([user.password_hash] if user.password_hash else []))
        if user.password_hash:
            history = [user.password_hash, *history][: settings.PASSWORD_HISTORY]
        prefs["password_history"] = history
        user.preferences = prefs
        user.password_hash = hash_password(password)
        user.password_changed_at = datetime.now(UTC)
        user.must_change_password = False
        await self.db.flush()
        await self.sessions.revoke_all(user.id, "password_changed", except_session=keep_session)
        await events.emit(
            self.db,
            institution_id=user.institution_id,
            event_type="user.password_changed",
            payload={"user_id": str(user.id)},
            aggregate_type="user",
            aggregate_id=user.id,
            actor_user_id=user.id,
        )

    # ---- rule 6 ---------------------------------------------------------------------------------------------------
    async def mfa_setup(self) -> MfaSetupResponse:
        assert self.principal is not None
        user = self.principal.user
        secret = generate_totp_secret()
        await self.mfa.upsert_pending(user.id, encrypt_secret(secret))
        uri = totp_uri(secret, user.email or user.username)
        return MfaSetupResponse(secret=secret, otpauth_url=uri, qr_png_base64=_qr_png_base64(uri))

    async def mfa_confirm(self, code: str) -> tuple[MfaConfirmResponse, str | None]:
        assert self.principal is not None
        user = self.principal.user
        row = await self.mfa.get(user.id)
        if row is None:
            raise APIError(409, ErrorCode.CONFLICT, "Run MFA setup first")
        if not verify_totp(decrypt_secret(row.secret_encrypted), code):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid code", {"field": "code"})
        codes = generate_recovery_codes(10)
        row.recovery_codes_hashed = [sha256_hex(c.lower()) for c in codes]
        row.confirmed_at = datetime.now(UTC)
        user.mfa_enabled = True
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="mfa_enabled",
            record_type="user",
            record_id=user.id,
            request=self.request,
        )
        access: str | None = None
        refresh: str | None = None
        if self.principal.limited:
            roles = await self._role_slugs(user)
            login, refresh = await self._open_session(
                user, await self._institution_of(user), roles, user.username, "web", None, LoginOutcome.SUCCESS
            )
            access = login.access_token
        return MfaConfirmResponse(recovery_codes=codes, access_token=access), refresh

    async def mfa_disable(self, body: MfaDisableRequest) -> None:
        assert self.principal is not None
        user = self.principal.user
        if not verify_password(body.password, user.password_hash):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Password is incorrect", {"field": "password"})
        if not await self._verify_mfa_code(user, body.code):
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid code", {"field": "code"})
        await self.mfa.delete(user.id)
        user.mfa_enabled = False
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="mfa_disabled",
            record_type="user",
            record_id=user.id,
            request=self.request,
        )

    async def regenerate_recovery_codes(self) -> RecoveryCodesResponse:
        assert self.principal is not None
        row = await self.mfa.get(self.principal.id)
        if row is None or row.confirmed_at is None:
            raise APIError(409, ErrorCode.CONFLICT, "MFA is not enabled")
        codes = generate_recovery_codes(10)
        row.recovery_codes_hashed = [sha256_hex(c.lower()) for c in codes]
        await self.db.flush()
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="mfa_recovery_codes",
            record_type="user",
            record_id=self.principal.id,
            request=self.request,
        )
        return RecoveryCodesResponse(recovery_codes=codes)

    # ---- rule 7 ---------------------------------------------------------------------------------------------------
    async def list_sessions(self) -> list[SessionResponse]:
        assert self.principal is not None
        rows = await self.sessions.list_active(self.principal.id)
        return [
            SessionResponse(
                id=s.id,
                device_label=s.device_label,
                platform=s.platform,
                ip_masked=mask_ip(str(s.ip) if s.ip else None),
                user_agent=(s.user_agent or "")[:120] or None,
                created_at=s.created_at,
                last_seen_at=s.last_seen_at,
                expires_at=s.expires_at,
                current=s.id == self.principal.session_id,
            )
            for s in rows
        ]

    async def revoke_session(self, session_id: uuid.UUID) -> None:
        assert self.principal is not None
        session = await self.sessions.get(session_id)
        if session is None or session.user_id != self.principal.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Session not found")
        await self.sessions.revoke(session, "revoked_by_user")
        await self._session_revoked_event(1, str(session_id))

    async def revoke_other_sessions(self) -> int:
        assert self.principal is not None
        n = await self.sessions.revoke_all(
            self.principal.id, "revoked_by_user", except_session=self.principal.session_id
        )
        await self._session_revoked_event(n, "others")
        return n

    async def _session_revoked_event(self, count: int, which: str) -> None:
        assert self.principal is not None
        await events.emit(
            self.db,
            institution_id=self.principal.institution_id,
            event_type="session.revoked",
            payload={"user_id": str(self.principal.id), "which": which, "count": count},
            aggregate_type="user_session",
            aggregate_id=self.principal.session_id,
            actor_user_id=self.principal.id,
        )
        await log_audit(
            self.db,
            principal=self.principal,
            module="users",
            action="session_revoke",
            record_type="user_session",
            record_id=self.principal.session_id,
            new={"which": which, "count": count},
            request=self.request,
        )

    async def login_history(self) -> list[LoginHistoryResponse]:
        assert self.principal is not None
        rows = await self.history.for_user(self.principal.id)
        return [
            LoginHistoryResponse(
                id=r.id,
                outcome=r.outcome,
                ip=str(r.ip) if r.ip else None,
                user_agent=(r.user_agent or "")[:120] or None,
                occurred_at=r.occurred_at,
            )
            for r in rows
        ]

    # ---- rule 9 ---------------------------------------------------------------------------------------------------
    async def sso_start(self, provider: str, institution_slug: str | None, login_hint: str | None) -> SsoStartResponse:
        institution = await self.resolve_institution(institution_slug)
        if institution is None:
            raise APIError(
                422, ErrorCode.VALIDATION, "institution_slug is required for SSO", {"field": "institution_slug"}
            )
        if not await is_enabled(institution.id, "security.sso"):
            raise APIError(
                403, ErrorCode.FEATURE_DISABLED, "Feature 'security.sso' is not enabled", {"feature": "security.sso"}
            )
        from app.integrations.registry import get_adapter

        state = sign_payload({"inst": str(institution.id), "provider": provider, "nonce": secrets.token_hex(8)}, 600)
        redirect_uri = f"{settings.frontend_url}/login/sso/callback"
        adapter = get_adapter("sso", provider)
        url = adapter.authorize_url(state=state, redirect_uri=redirect_uri, login_hint=login_hint, provider=provider)
        return SsoStartResponse(provider=provider, authorize_url=str(url), state=state)

    async def sso_callback(self, provider: str, code: str, state: str) -> tuple[LoginResponse, str]:
        payload = verify_signed(state)
        if payload.get("provider") != provider:
            raise APIError(400, ErrorCode.VALIDATION, "State does not match the provider")
        institution = (
            await self.db.execute(select(Institution).where(Institution.id == uuid.UUID(payload["inst"])))
        ).scalar_one_or_none()
        if institution is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Unknown institution")
        if not await is_enabled(institution.id, "security.sso"):
            raise APIError(
                403, ErrorCode.FEATURE_DISABLED, "Feature 'security.sso' is not enabled", {"feature": "security.sso"}
            )
        identity = await self._exchange(provider, code)
        email = (identity.get("email") or "").strip().lower()
        if not email:
            raise APIError(401, ErrorCode.UNAUTHENTICATED, "The identity provider returned no email")
        user = await self.users.get_by_identifier(email, institution.id)
        if user is None:
            user = await self._jit_provision(institution, email, identity)
        elif not user.is_verified:
            raise APIError(
                401, ErrorCode.UNAUTHENTICATED, "The account's email is not verified; contact your administrator"
            )
        await self._check_account_window(user, email)
        roles = await self._role_slugs(user)
        return await self._open_session(user, institution, roles, email, "web", None, LoginOutcome.SSO)

    async def _exchange(self, provider: str, code: str) -> dict[str, Any]:
        from app.integrations.registry import get_adapter

        result = await get_adapter("sso", provider).exchange(code=code)
        return dict(result) if isinstance(result, dict) else {}

    async def _jit_provision(self, institution: Institution, email: str, identity: dict[str, Any]) -> User:
        role_map = await self.config.institution_setting(institution.id, "security", "sso_role_map") or {}
        user = User(
            institution_id=institution.id,
            username=email,
            email=email,
            display_name=identity.get("name") or email.split("@")[0],
            user_type="staff",
            is_verified=True,
            must_change_password=False,
        )
        self.db.add(user)
        await self.db.flush()
        slugs: set[str] = set()
        if isinstance(role_map, dict):
            for group in identity.get("groups") or []:
                if group in role_map:
                    slugs.add(str(role_map[group]))
            if not slugs and role_map.get("default"):
                slugs.add(str(role_map["default"]))
        for slug in slugs:
            role = (
                await self.db.execute(select(Role).where(Role.institution_id == institution.id, Role.slug == slug))
            ).scalar_one_or_none()
            if role is not None:
                self.db.add(
                    UserRole(
                        institution_id=institution.id,
                        user_id=user.id,
                        role_id=role.id,
                        scope_type=(
                            role.default_scope_type
                            if role.default_scope_type in {"institution", "self"}
                            else "institution"
                        ),
                    )
                )
        await self.db.flush()
        await events.emit(
            self.db,
            institution_id=institution.id,
            event_type="user.created",
            payload={"user_id": str(user.id), "source": "sso"},
            aggregate_type="user",
            aggregate_id=user.id,
            actor_user_id=user.id,
        )
        return user

    # ---- impersonation stop -----------------------------------------------------------------------------------
    async def stop_impersonation(self) -> None:
        assert self.principal is not None
        p = self.principal
        if p.impersonator_id is None:
            raise APIError(409, ErrorCode.CONFLICT, "Not impersonating")
        log_id = p.impersonation_log_id
        if log_id is not None:
            row = await ImpersonationRepository(self.db).get(log_id)
            if row is not None:
                await ImpersonationRepository(self.db).end(row)
        jti = p.claims.get("jti")
        if jti:
            await redis_client.set(f"blacklist:jti:{jti}", "1", ex=token_ttl_seconds(p.claims))
        await log_audit(
            self.db,
            principal=p,
            module="users",
            action="impersonation_stop",
            record_type="user",
            record_id=p.id,
            new={"impersonator_id": str(p.impersonator_id)},
            request=self.request,
        )


# ---- helpers ------------------------------------------------------------------------------------------------------
def _payload_fields(payload: PrincipalPayload) -> dict[str, Any]:
    """Field values of the principal payload as objects (``model_dump()`` would rename aliased fields)."""
    return {name: getattr(payload, name) for name in PrincipalPayload.model_fields}


def _device_from_ua(ua: str | None) -> str:
    if not ua:
        return "Unknown device"
    u = ua.lower()
    for needle, label in (
        ("iphone", "iPhone"),
        ("ipad", "iPad"),
        ("android", "Android"),
        ("windows", "Windows"),
        ("mac os", "macOS"),
        ("linux", "Linux"),
        ("powershell", "PowerShell"),
        ("python", "Python client"),
    ):
        if needle in u:
            return label
    return ua[:60]


def _qr_png_base64(uri: str) -> str:
    import qrcode

    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _send_task(name: str, kwargs: dict[str, Any]) -> None:
    """Hand a notification to Celery; a broker outage never fails an auth flow (mock providers in this phase)."""
    from app.tasks.celery_app import celery

    try:
        celery.send_task(name, kwargs=kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("notification_task_not_sent", task=name, error=str(exc)[:200])


def refresh_cookie_kwargs(value: str) -> dict[str, Any]:
    return {
        "key": REFRESH_COOKIE,
        "value": value,
        "httponly": True,
        "samesite": "strict",
        "secure": settings.cookie_secure,
        "path": REFRESH_COOKIE_PATH,
        "max_age": settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    }
