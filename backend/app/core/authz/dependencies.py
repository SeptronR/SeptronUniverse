"""Principal resolution and permission dependencies — Prompts/00 §3.11, Prompts/02 §02.6.

Phase 02 completes the chain: the tenant context comes from the **token claim** (``inst``) before the user row is
read (RLS would otherwise hide a tenant user from the app role), the JTI blacklist is honoured, the
``must_change_password`` gate confines a user to ``/auth/*`` until the password is rotated, and a read-only
impersonation token (support agents) refuses every write. ``authenticated()`` marks routes any signed-in user may
call (``auth:authenticated`` in the access matrix); ``mfa_enrolment_principal`` also accepts the short-lived
``mfa_setup`` token handed out with ``403 MFA_REQUIRED``.
"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.core.security import decode_token
from app.db.session import bind_tenant, get_db, redis_client, set_tenant

bearer = HTTPBearer(auto_error=False)

AUTHENTICATED_MARKER = ("auth", "authenticated")  # any signed-in user (gen_access_matrix renders it as Y for all)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# routes a user may call while must_change_password is set or under read-only impersonation
AUTH_PREFIX = "/api/v1/auth"
READ_ONLY_IMPERSONATION_ALLOWED = {"/api/v1/auth/impersonation/stop", "/api/v1/auth/logout"}


class Principal:
    """Resolved once per request: user row, role slugs, flat permissions ('module:action'), scopes, features."""

    def __init__(
        self,
        user: Any,
        roles: list[str],
        permissions: set[str],
        scopes: list[tuple[str, uuid.UUID | None]],
        features: set[str],
        impersonator_id: uuid.UUID | None = None,
        *,
        session_id: uuid.UUID | None = None,
        claims: dict[str, Any] | None = None,
        limited: bool = False,
    ):
        self.user = user
        self.roles = roles
        self.permissions = permissions
        self.scopes = scopes
        self.features = features
        self.impersonator_id = impersonator_id
        self.session_id = session_id
        self.claims = claims or {}
        self.limited = limited  # mfa_setup token: may only enrol MFA

    @property
    def id(self) -> uuid.UUID:
        return self.user.id  # type: ignore[no-any-return]

    @property
    def institution_id(self) -> uuid.UUID | None:
        return self.user.institution_id  # type: ignore[no-any-return]

    @property
    def is_super_admin(self) -> bool:
        return bool(self.user.is_super_admin)

    @property
    def impersonation_read_only(self) -> bool:
        return bool(self.claims.get("imp_ro"))

    @property
    def impersonation_log_id(self) -> uuid.UUID | None:
        raw = self.claims.get("imp_log")
        return uuid.UUID(raw) if raw else None

    def has(self, module: str, action: str) -> bool:
        if self.is_super_admin:
            return True
        if f"{module}:{action}" in self.permissions:
            return True
        # ``manage`` is the module wildcard — except PII unmasking, which must always be granted explicitly
        return action != "view_pii" and f"{module}:manage" in self.permissions

    def has_feature(self, key: str) -> bool:
        return key in self.features


async def _resolve(request: Request, token: str, db: AsyncSession, *, allow_limited: bool = False) -> Principal:
    try:
        claims = decode_token(token, expected_type="access")
        limited = False
    except APIError:
        if not allow_limited:
            raise
        claims = decode_token(token, expected_type="mfa_setup")
        limited = True
    if await redis_client.exists(f"blacklist:jti:{claims['jti']}"):
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Token revoked")
    request.state.claims = claims
    # RLS: pin the tenant named by the token BEFORE reading the user row; super admins keep the header override
    header_inst = getattr(request.state, "institution_id", None)
    token_inst = claims.get("inst")
    inst = (header_inst or token_inst) if claims.get("sa") else token_inst
    if inst:
        bind_tenant(db, inst)
        await set_tenant(db, inst)
    from app.services.auth_service import load_principal

    principal = await load_principal(db, uuid.UUID(claims["sub"]), request)
    principal.limited = limited
    if principal.is_super_admin:
        request.state.institution_id = header_inst or principal.institution_id
    else:
        request.state.institution_id = principal.institution_id
    request.state.user_id = principal.id
    if request.state.institution_id and str(request.state.institution_id) != str(inst or ""):
        bind_tenant(db, request.state.institution_id)
        await set_tenant(db, request.state.institution_id)
    return principal


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    if not creds:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Missing bearer token")
    principal = await _resolve(request, creds.credentials, db)
    path = request.url.path
    if principal.user.must_change_password and not path.startswith(AUTH_PREFIX):
        raise APIError(
            403,
            ErrorCode.PERMISSION_DENIED,
            "Password change required before continuing",
            {"reason": "must_change_password"},
        )
    if (
        principal.impersonation_read_only
        and request.method in WRITE_METHODS
        and path not in READ_ONLY_IMPERSONATION_ALLOWED
    ):
        raise APIError(
            403,
            ErrorCode.PERMISSION_DENIED,
            "Read-only impersonation: writes are not allowed",
            {"reason": "impersonation"},
        )
    return principal


async def mfa_enrolment_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    """Accepts a normal access token or the limited ``mfa_setup`` token (Prompts/02 §02.11 step 4)."""
    if not creds:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Missing bearer token")
    return await _resolve(request, creds.credentials, db, allow_limited=True)


mfa_enrolment_principal.__permissions__ = [AUTHENTICATED_MARKER]  # type: ignore[attr-defined]

PermissionDependency = Callable[..., Awaitable[Principal]]


def permission_required(module: str, action: str) -> PermissionDependency:
    async def _dep(principal: Principal = Depends(get_current_user)) -> Principal:
        if not principal.has(module, action):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, f"Requires {module}:{action}", {"module": module, "action": action}
            )
        return principal

    _dep.__permissions__ = [(module, action)]  # type: ignore[attr-defined]  # read by check_authz_coverage / gen_access_matrix
    return _dep


def any_permission_required(*pairs: tuple[str, str]) -> PermissionDependency:
    async def _dep(principal: Principal = Depends(get_current_user)) -> Principal:
        if not any(principal.has(m, a) for m, a in pairs):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Insufficient permissions")
        return principal

    _dep.__permissions__ = list(pairs)  # type: ignore[attr-defined]
    return _dep


def authenticated() -> PermissionDependency:
    """Any signed-in user (``[auth]`` routes of the prompts: /auth/me, sessions, consents, …)."""

    async def _dep(principal: Principal = Depends(get_current_user)) -> Principal:
        return principal

    _dep.__permissions__ = [AUTHENTICATED_MARKER]  # type: ignore[attr-defined]
    return _dep


def super_admin_required() -> PermissionDependency:
    """Platform-only routes (feature toggles, matrix): the super admin flag on the user row."""

    async def _dep(principal: Principal = Depends(get_current_user)) -> Principal:
        if not principal.is_super_admin:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Super admin only")
        return principal

    _dep.__permissions__ = [("features", "manage")]  # type: ignore[attr-defined]
    return _dep


def get_scopes(principal: Principal = Depends(get_current_user)) -> list[tuple[str, uuid.UUID | None]]:
    """Scopes of the principal (union across role assignments)."""
    return principal.scopes
