"""Faculties and departments — Prompts/03 §03.5 ``department_repository`` (``module="departments"``; scope columns
institution / college / faculty). HOD and dean holders are read from ``user_roles`` (the role assignment is the source
of truth until Phase 06 links ``staff`` rows)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.platform import Department, Faculty, Role, User, UserRole
from app.repositories.base import BaseRepository


class FacultyRepository(BaseRepository[Faculty]):
    model = Faculty
    module = "faculties"

    def filtered(self, college_id: uuid.UUID | None = None, q: str | None = None) -> Select[tuple[Faculty]]:
        stmt = self._base()
        if college_id:
            stmt = stmt.where(Faculty.college_id == college_id)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(Faculty.name).like(like), func.lower(Faculty.code).like(like)))
        return stmt

    async def get_scoped(self, faculty_id: uuid.UUID, writable: Sequence[uuid.UUID] | None) -> Faculty:
        stmt = self._base().where(Faculty.id == faculty_id)
        if writable is not None:
            stmt = stmt.where(Faculty.college_id.in_(writable))
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Faculty not found")
        return obj

    async def codes(self, faculty_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not faculty_ids:
            return {}
        rows = (await self.db.execute(select(Faculty.id, Faculty.code).where(Faculty.id.in_(faculty_ids)))).all()
        return {row[0]: row[1] for row in rows}

    async def by_code(self, institution_id: uuid.UUID, college_id: uuid.UUID, code: str) -> Faculty | None:
        return (
            await self.db.execute(
                select(Faculty).where(
                    Faculty.institution_id == institution_id,
                    Faculty.college_id == college_id,
                    func.upper(Faculty.code) == code.upper(),
                )
            )
        ).scalar_one_or_none()


class DepartmentRepository(BaseRepository[Department]):
    model = Department
    module = "departments"

    def filtered(
        self,
        *,
        college_ids: Sequence[uuid.UUID] | None = None,
        faculty_id: uuid.UUID | None = None,
        department_type: str | None = None,
        q: str | None = None,
    ) -> Select[tuple[Department]]:
        stmt = self._base().where(Department.is_active.is_(True))
        if college_ids is not None:
            stmt = stmt.where(Department.college_id.in_(college_ids))
        if faculty_id:
            stmt = stmt.where(Department.faculty_id == faculty_id)
        if department_type:
            stmt = stmt.where(Department.department_type == department_type)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(Department.name).like(like), func.lower(Department.code).like(like)))
        return stmt

    async def get_scoped(self, department_id: uuid.UUID, writable: Sequence[uuid.UUID] | None) -> Department:
        stmt = self._base().where(Department.id == department_id)
        if writable is not None:
            stmt = stmt.where(Department.college_id.in_(writable))
        obj = (await self.db.execute(stmt)).scalar_one_or_none()
        if obj is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Department not found")
        return obj

    async def by_code(self, institution_id: uuid.UUID, college_id: uuid.UUID, code: str) -> Department | None:
        return (
            await self.db.execute(
                select(Department).where(
                    Department.institution_id == institution_id,
                    Department.college_id == college_id,
                    func.upper(Department.code) == code.upper(),
                )
            )
        ).scalar_one_or_none()

    async def count_for_faculties(self, faculty_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        if not faculty_ids:
            return {}
        rows = (
            await self.db.execute(
                select(Department.faculty_id, func.count())
                .where(Department.faculty_id.in_(faculty_ids), Department.deleted_at.is_(None))
                .group_by(Department.faculty_id)
            )
        ).all()
        return {fid: int(n) for fid, n in rows if fid}


class UnitHolderRepository:
    """Who holds a unit-scoped role (``hod`` @department, ``dean`` @faculty) and staff lookups for the assignment."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def holders(
        self, role_slug: str, scope_type: str, scope_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:
        """scope_id → (user_id, display_name) of the (first) holder."""
        if not scope_ids:
            return {}
        rows = (
            await self.db.execute(
                select(UserRole.scope_id, User.id, User.display_name)
                .join(Role, Role.id == UserRole.role_id)
                .join(User, User.id == UserRole.user_id)
                .where(
                    Role.slug == role_slug,
                    UserRole.scope_type == scope_type,
                    UserRole.scope_id.in_(scope_ids),
                    User.deleted_at.is_(None),
                )
                .order_by(UserRole.assigned_at)
            )
        ).all()
        out: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
        for sid, uid, name in rows:
            out.setdefault(sid, (uid, name))
        return out

    async def assignments(self, role_slug: str, scope_type: str, scope_id: uuid.UUID) -> Sequence[UserRole]:
        return (
            (
                await self.db.execute(
                    select(UserRole)
                    .join(Role, Role.id == UserRole.role_id)
                    .where(Role.slug == role_slug, UserRole.scope_type == scope_type, UserRole.scope_id == scope_id)
                )
            )
            .scalars()
            .all()
        )

    async def staff_row(self, institution_id: uuid.UUID, ident: uuid.UUID) -> dict[str, Any] | None:
        """A ``staff`` row by its id or by its ``user_id`` (Phase 06 table; unmapped until then)."""
        row = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, user_id, college_id, status FROM staff WHERE institution_id = :i "
                        "AND deleted_at IS NULL AND (id = :x OR user_id = :x) LIMIT 1"
                    ),
                    {"i": institution_id, "x": ident},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    async def user(self, institution_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        return (
            await self.db.execute(
                select(User).where(
                    User.id == user_id,
                    User.institution_id == institution_id,
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
