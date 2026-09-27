"""``roles`` / ``permissions`` / ``role_permissions`` repositories — Prompts/02 §02.5.

Institution roles carry ``institution_id``; the 51 platform templates have ``institution_id IS NULL`` and are cloned
into every tenant by ``RbacService.seed_institution_roles``. ``PermissionRepository`` is read-only (the catalogue is
seeded by revision ``0002`` / ``seed_platform.py``).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import Permission, Role, RolePermission, UserRole
from app.repositories.base import BaseRepository
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta


class PermissionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def all(self) -> Sequence[Permission]:
        return (
            (await self.db.execute(select(Permission).order_by(Permission.module, Permission.action))).scalars().all()
        )

    async def by_keys(self, keys: Sequence[str]) -> dict[str, Permission]:
        if not keys:
            return {}
        pairs = [k.split(":", 1) for k in keys if ":" in k]
        rows = (
            (
                await self.db.execute(
                    select(Permission).where(
                        func.concat(Permission.module, ":", Permission.action).in_([f"{m}:{a}" for m, a in pairs])
                    )
                )
            )
            .scalars()
            .all()
        )
        return {f"{p.module}:{p.action}": p for p in rows}


class RoleRepository(BaseRepository[Role]):
    model = Role
    module = "roles"

    def _base(self, include_deleted: bool = False) -> Select[tuple[Role]]:
        q = select(Role)
        if not include_deleted:
            q = q.where(Role.deleted_at.is_(None))
        if self.principal is not None and not self.principal.is_super_admin:
            q = q.where(Role.institution_id == self.principal.institution_id)
        return q

    async def list_roles(
        self, params: PageParams, institution_id: uuid.UUID | None, q: str | None = None
    ) -> tuple[Sequence[Role], PaginationMeta]:
        stmt = self._base().where(
            Role.institution_id == institution_id if institution_id else Role.institution_id.is_(None)
        )
        if q:
            stmt = stmt.where(Role.name.ilike(f"%{q.strip()}%"))
        if not params.sort:
            stmt = stmt.order_by(Role.is_system.desc(), Role.name)
        return await self.paginate(stmt, params)

    async def get_role(self, role_id: uuid.UUID, institution_id: uuid.UUID | None) -> Role | None:
        stmt = select(Role).where(Role.id == role_id, Role.deleted_at.is_(None))
        stmt = stmt.where(Role.institution_id == institution_id if institution_id else Role.institution_id.is_(None))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, slug: str, institution_id: uuid.UUID | None) -> Role | None:
        stmt = select(Role).where(Role.slug == slug, Role.deleted_at.is_(None))
        stmt = stmt.where(Role.institution_id == institution_id if institution_id else Role.institution_id.is_(None))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def templates(self) -> Sequence[Role]:
        return (
            (await self.db.execute(select(Role).where(Role.institution_id.is_(None), Role.deleted_at.is_(None))))
            .scalars()
            .all()
        )

    async def institution_role_slugs(self, institution_id: uuid.UUID) -> set[str]:
        rows = (
            await self.db.execute(
                select(Role.slug).where(Role.institution_id == institution_id, Role.deleted_at.is_(None))
            )
        ).scalars()
        return set(rows)

    async def permission_keys(self, role_id: uuid.UUID) -> set[str]:
        rows = (
            await self.db.execute(
                select(Permission.module, Permission.action)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role_id)
            )
        ).all()
        return {f"{m}:{a}" for m, a in rows}

    async def permission_keys_many(self, role_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, set[str]]:
        out: dict[uuid.UUID, set[str]] = {rid: set() for rid in role_ids}
        if not role_ids:
            return out
        rows = (
            await self.db.execute(
                select(RolePermission.role_id, Permission.module, Permission.action)
                .join(Permission, Permission.id == RolePermission.permission_id)
                .where(RolePermission.role_id.in_(list(role_ids)))
            )
        ).all()
        for rid, m, a in rows:
            out.setdefault(rid, set()).add(f"{m}:{a}")
        return out

    async def add_permissions(self, role_id: uuid.UUID, permission_ids: Sequence[uuid.UUID]) -> None:
        for pid in permission_ids:
            self.db.add(RolePermission(role_id=role_id, permission_id=pid))
        await self.db.flush()

    async def remove_permissions(self, role_id: uuid.UUID, permission_ids: Sequence[uuid.UUID]) -> None:
        if not permission_ids:
            return
        await self.db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id, RolePermission.permission_id.in_(list(permission_ids))
            )
        )

    async def assignment_count(self, role_id: uuid.UUID) -> int:
        return int((await self.db.execute(select(func.count()).where(UserRole.role_id == role_id))).scalar_one())

    async def create_role(self, **values: Any) -> Role:
        role = Role(**values)
        self.db.add(role)
        await self.db.flush()
        return role
