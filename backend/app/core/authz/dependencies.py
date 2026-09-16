"""Principal resolution and permission dependencies — Prompts/00_PREREQUISITE_Project_Setup.md §3.11."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.core.security import decode_token
from app.db.session import get_db, redis_client

bearer = HTTPBearer(auto_error=False)


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
    ):
        self.user = user
        self.roles = roles
        self.permissions = permissions
        self.scopes = scopes
        self.features = features
        self.impersonator_id = impersonator_id

    @property
    def id(self) -> uuid.UUID:
        return self.user.id  # type: ignore[no-any-return]

    @property
    def institution_id(self) -> uuid.UUID | None:
        return self.user.institution_id  # type: ignore[no-any-return]

    @property
    def is_super_admin(self) -> bool:
        return bool(self.user.is_super_admin)

    def has(self, module: str, action: str) -> bool:
        return self.is_super_admin or f"{module}:{action}" in self.permissions or f"{module}:manage" in self.permissions

    def has_feature(self, key: str) -> bool:
        return key in self.features


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    if not creds:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Missing bearer token")
    claims = decode_token(creds.credentials, expected_type="access")
    if await redis_client.exists(f"blacklist:jti:{claims['jti']}"):
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Token revoked")
    from app.services.auth_service import load_principal

    principal = await load_principal(db, uuid.UUID(claims["sub"]), request)
    # Tenant context comes from the user row (super admins may override via X-Institution-Id); re-apply RLS for this transaction
    if principal.is_super_admin:
        request.state.institution_id = request.state.institution_id or principal.institution_id
    else:
        request.state.institution_id = principal.institution_id
    request.state.user_id = principal.id
    if request.state.institution_id:
        await db.execute(text("SET LOCAL app.institution_id = :i"), {"i": str(request.state.institution_id)})
    return principal


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


def get_scopes(principal: Principal = Depends(get_current_user)) -> list[tuple[str, uuid.UUID | None]]:
    """Scopes of the principal (union across role assignments)."""
    return principal.scopes
