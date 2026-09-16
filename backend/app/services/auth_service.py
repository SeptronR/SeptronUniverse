"""Principal loading — Phase 02 implements login, sessions, MFA and the full ``load_principal``.

The skeleton keeps the contract ``await load_principal(db, user_id, request) -> Principal`` used by
``app/core/authz/dependencies.py`` and resolves the user, roles, permissions, scopes and features from the platform
tables so protected routes can be exercised as soon as a token can be minted.
"""

import uuid
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal
from app.core.errors import APIError, ErrorCode
from app.core.features import effective_features
from app.models.platform import Permission, Role, RolePermission, User, UserRole


async def load_principal(db: AsyncSession, user_id: uuid.UUID, request: Request | None = None) -> Principal:
    user = (
        await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None), User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "User not found or inactive")
    now = datetime.now(UTC)
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
    features = await effective_features(user.institution_id) if user.institution_id else set()
    impersonator = getattr(request.state, "impersonator_id", None) if request is not None else None
    return Principal(user, roles, permissions, scopes, features, impersonator_id=impersonator)
