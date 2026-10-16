"""``user_roles`` repository — scoped role assignments (Prompts/02 §02.5; docs/Roles_and_Permissions.md §4)."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac.registry import SCOPE_ALT_TABLES, SCOPE_TABLES
from app.models.platform import Role, UserRole

# label column per scope table (Database_Schema.sql §7, §11, §19, §30)
# label expression per scope table (a real Phase 09 offering reads "<course code> / <section>")
SCOPE_LABEL_COLUMNS: dict[str, str] = {
    "course_offerings": "(SELECT c.code FROM courses c WHERE c.id = course_id) || ' / ' || section_code"
}


class UserRoleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def for_user(self, user_id: uuid.UUID) -> Sequence[tuple[UserRole, Role]]:
        rows = (
            await self.db.execute(
                select(UserRole, Role)
                .join(Role, Role.id == UserRole.role_id)
                .where(UserRole.user_id == user_id)
                .order_by(UserRole.assigned_at)
            )
        ).all()
        return [(ur, r) for ur, r in rows]

    async def get(self, assignment_id: uuid.UUID, user_id: uuid.UUID) -> UserRole | None:
        return (
            await self.db.execute(select(UserRole).where(UserRole.id == assignment_id, UserRole.user_id == user_id))
        ).scalar_one_or_none()

    async def exists(self, user_id: uuid.UUID, role_id: uuid.UUID, scope_type: str, scope_id: uuid.UUID | None) -> bool:
        stmt = select(UserRole.id).where(
            UserRole.user_id == user_id, UserRole.role_id == role_id, UserRole.scope_type == scope_type
        )
        stmt = stmt.where(UserRole.scope_id == scope_id) if scope_id else stmt.where(UserRole.scope_id.is_(None))
        return (await self.db.execute(stmt)).first() is not None

    async def create(
        self,
        *,
        institution_id: uuid.UUID | None,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        scope_type: str,
        scope_id: uuid.UUID | None,
        valid_from: datetime | None,
        valid_to: datetime | None,
        assigned_by: uuid.UUID | None,
    ) -> UserRole:
        row = UserRole(
            institution_id=institution_id,
            user_id=user_id,
            role_id=role_id,
            scope_type=scope_type,
            scope_id=scope_id,
            valid_from=valid_from,
            valid_to=valid_to,
            assigned_by=assigned_by,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def delete(self, assignment: UserRole) -> None:
        await self.db.execute(delete(UserRole).where(UserRole.id == assignment.id))

    async def scope_label(self, scope_type: str, scope_id: uuid.UUID | None) -> str | None:
        """Human label for a scope (college/department/... name) — used by ``MeUser.scopes[].label``."""
        table = SCOPE_TABLES.get(scope_type)
        if not table or scope_id is None:
            return None
        col = SCOPE_LABEL_COLUMNS.get(table, "name")
        row = (await self.db.execute(text(f"SELECT {col} FROM {table} WHERE id = :id"), {"id": scope_id})).first()
        if row is None and "batch_sections" in SCOPE_ALT_TABLES.get(scope_type, ()):
            row = (
                await self.db.execute(
                    text(
                        "SELECT b.code || ' / ' || s.name FROM batch_sections s JOIN batches b ON b.id = s.batch_id "
                        "WHERE s.id = :id"
                    ),
                    {"id": scope_id},
                )
            ).first()
        return str(row[0]) if row and row[0] is not None else None

    async def scope_exists(self, scope_type: str, scope_id: uuid.UUID, institution_id: uuid.UUID) -> bool:
        """The scope row must exist **inside the institution** (Prompts/02 §02.11 step 8 → 422 otherwise)."""
        table = SCOPE_TABLES.get(scope_type)
        if not table:
            return False
        for candidate in (table, *SCOPE_ALT_TABLES.get(scope_type, ())):
            row = (
                await self.db.execute(
                    text(f"SELECT 1 FROM {candidate} WHERE id = :id AND institution_id = :inst"),
                    {"id": scope_id, "inst": institution_id},
                )
            ).first()
            if row is not None:
                return True
        return False
