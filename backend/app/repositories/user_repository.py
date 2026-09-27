"""``users`` repository — Prompts/02 §02.5 (``module="users"``; visibility registered in ``services/users/visibility.py``).

``get_by_identifier`` matches username / email / phone inside one institution (plus platform users);
``find_by_identifier_any`` is the cross-tenant lookup the login flow runs on the **platform session** when no tenant
could be resolved from the request (``_common.ps1`` logs in with identifier + password only) — it must find exactly
one active account, otherwise the caller asks for ``institution_slug``.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Role, User, UserRole
from app.repositories.base import BaseRepository
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


def _identifier_clause(identifier: str) -> Any:
    ident = identifier.strip()
    return or_(User.username == ident, func.lower(User.email) == ident.lower(), User.phone == ident)


class UserRepository(BaseRepository[User]):
    model = User
    module = "users"

    def __init__(self, db: AsyncSession, principal: Any = None):
        super().__init__(db, principal)

    async def get_by_identifier(self, identifier: str, institution_id: uuid.UUID | None) -> User | None:
        q = select(User).where(User.deleted_at.is_(None), _identifier_clause(identifier))
        if institution_id is None:
            q = q.where(User.institution_id.is_(None))
        else:
            q = q.where(or_(User.institution_id == institution_id, User.institution_id.is_(None)))
        rows = (await self.db.execute(q.order_by(User.institution_id.is_(None)))).scalars().all()
        return rows[0] if rows else None

    async def find_by_identifier_any(self, identifier: str) -> Sequence[User]:
        """Cross-tenant match (platform session only)."""
        q = select(User).where(User.deleted_at.is_(None), User.is_active.is_(True), _identifier_clause(identifier))
        return (await self.db.execute(q)).scalars().all()

    async def get_any(self, user_id: uuid.UUID) -> User | None:
        """Row by id without the visibility predicate (auth flows: refresh, principal loading, impersonation)."""
        return (
            await self.db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
        ).scalar_one_or_none()

    async def list_users(
        self,
        params: PageParams,
        scope: str | None = None,
        q: str | None = None,
        user_type: str | None = None,
        is_active: bool | None = None,
        role_slug: str | None = None,
    ) -> tuple[Sequence[User], PaginationMeta]:
        stmt = self.visible(self._base(), scope)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    User.username.ilike(like),
                    User.display_name.ilike(like),
                    User.email.ilike(like),
                    User.phone.ilike(like),
                )
            )
        if user_type:
            stmt = stmt.where(User.user_type == user_type)
        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        if role_slug:
            stmt = stmt.where(
                User.id.in_(
                    select(UserRole.user_id).join(Role, Role.id == UserRole.role_id).where(Role.slug == role_slug)
                )
            )
        if not params.sort:
            stmt = stmt.order_by(User.display_name.nulls_last(), User.username)
        return await self.paginate(stmt, params)

    async def username_taken(self, institution_id: uuid.UUID | None, username: str) -> bool:
        q = select(User.id).where(User.username == username)
        q = q.where(User.institution_id == institution_id) if institution_id else q.where(User.institution_id.is_(None))
        return (await self.db.execute(q)).first() is not None

    async def count_active(self, institution_id: uuid.UUID, user_types: Sequence[str]) -> int:
        q = select(func.count()).where(
            User.institution_id == institution_id,
            User.deleted_at.is_(None),
            User.is_active.is_(True),
            User.user_type.in_(list(user_types)),
        )
        return int((await self.db.execute(q)).scalar_one())

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> Sequence[User]:
        if not ids:
            return []
        return (await self.db.execute(self.visible(self._base()).where(User.id.in_(list(ids))))).scalars().all()
