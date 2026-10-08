"""Guardians — Prompts/07 §07.5 ``guardian_repository.py``: a student's guardians, the wards of a parent user and the
lookup that reuses one guardian user across siblings (same phone or e-mail)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform import User
from app.models.students import Student, StudentGuardian


class GuardianRepository:
    def __init__(self, db: AsyncSession, institution_id: uuid.UUID | None = None):
        self.db, self.institution_id = db, institution_id

    async def for_student(self, student_id: uuid.UUID) -> Sequence[StudentGuardian]:
        stmt = (
            select(StudentGuardian)
            .where(StudentGuardian.student_id == student_id)
            .order_by(StudentGuardian.is_primary.desc(), StudentGuardian.created_at)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def get(self, student_id: uuid.UUID, guardian_id: uuid.UUID) -> StudentGuardian | None:
        stmt = select(StudentGuardian).where(
            StudentGuardian.id == guardian_id, StudentGuardian.student_id == student_id
        )
        return (await self.db.execute(stmt.with_for_update())).scalar_one_or_none()

    async def duplicate(self, student_id: uuid.UUID, relation: str, name: str) -> StudentGuardian | None:
        stmt = select(StudentGuardian).where(
            StudentGuardian.student_id == student_id,
            StudentGuardian.relation == relation,
            func.lower(StudentGuardian.name) == name.lower(),
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def clear_primary(self, student_id: uuid.UUID, keep: uuid.UUID | None = None) -> None:
        for g in await self.for_student(student_id):
            if g.id != keep and g.is_primary:
                g.is_primary = False
        await self.db.flush()

    async def add(self, obj: StudentGuardian) -> StudentGuardian:
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete(self, obj: StudentGuardian) -> None:
        await self.db.delete(obj)
        await self.db.flush()

    async def guardian_user(self, phone: str | None, email: str | None) -> User | None:
        """An existing guardian user of the institution with the same phone or e-mail (sibling reuse)."""
        conds = []
        if phone:
            conds.append(User.phone == phone)
        if email:
            conds.append(func.lower(User.email) == email.lower())
        if not conds:
            return None
        stmt = (
            select(User)
            .where(
                User.institution_id == self.institution_id,
                User.user_type == "guardian",
                User.deleted_at.is_(None),
                or_(*conds),
            )
            .order_by(User.created_at)
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def wards_of(self, user_id: uuid.UUID) -> Sequence[tuple[Student, StudentGuardian]]:
        """Students the user guards with portal access *and* the student's consent (the parent portal's list)."""
        stmt = (
            select(Student, StudentGuardian)
            .join(StudentGuardian, StudentGuardian.student_id == Student.id)
            .where(
                StudentGuardian.user_id == user_id,
                StudentGuardian.portal_access.is_(True),
                Student.guardian_portal_consent.is_(True),
                Student.deleted_at.is_(None),
            )
            .order_by(Student.first_name)
        )
        return [(s, g) for s, g in (await self.db.execute(stmt)).all()]

    async def ward_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        return {s.id for s, _ in await self.wards_of(user_id)}

    async def user_ids_for_students(self, student_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
        """Consented guardian users per student (notification audiences)."""
        out: dict[uuid.UUID, list[uuid.UUID]] = {}
        if not student_ids:
            return out
        stmt = (
            select(StudentGuardian.student_id, StudentGuardian.user_id)
            .join(Student, Student.id == StudentGuardian.student_id)
            .where(
                StudentGuardian.student_id.in_(list(student_ids)),
                StudentGuardian.user_id.is_not(None),
                StudentGuardian.portal_access.is_(True),
                Student.guardian_portal_consent.is_(True),
            )
        )
        for sid, uid in (await self.db.execute(stmt)).all():
            out.setdefault(sid, []).append(uid)
        return out
