"""Student master, documents and undertakings — Prompts/07 §07.5 ``student_repository.py`` (``module="students"``;
search by name / registration number / phone / e-mail with the trigram index; filters college / department /
programme / batch / section / status / category / gender / standing / has_holds). Visibility:
``repositories/student_scope.py``."""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.enums.students import OPEN_ENROLLMENT, SEATED_STATUSES
from app.models.academic import Batch, BatchSection, Program
from app.models.platform import College, Department, User
from app.models.students import (
    Student,
    StudentDocument,
    StudentHold,
    StudentProgramEnrollment,
    StudentTermRecord,
    StudentUndertaking,
)
from app.repositories import registration_scope  # noqa: F401  (Phase 09 own-offerings link on students)
from app.repositories.base import BaseRepository
from app.repositories.student_scope import student_predicate

NAME_EXPR = Student.first_name + " " + func.coalesce(Student.last_name, "")  # = ix_students_name_trgm


class StudentRepository(BaseRepository[Student]):
    model = Student
    module = "students"

    def filtered(
        self,
        *,
        scope: str | None = None,
        q: str | None = None,
        college_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        program_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
        section_id: uuid.UUID | None = None,
        status: str | None = None,
        category: str | None = None,
        gender: str | None = None,
        standing: str | None = None,
        has_holds: bool | None = None,
        ids: Sequence[uuid.UUID] | None = None,
    ) -> Select[tuple[Student]]:
        stmt = self._base()
        if self.principal is not None:
            stmt = stmt.where(student_predicate(self.principal, scope))
        if q:
            term = q.strip()
            like = f"%{term}%"
            stmt = stmt.where(
                or_(
                    NAME_EXPR.ilike(like),
                    Student.registration_number.ilike(like),
                    Student.phone.ilike(like),
                    Student.email.ilike(like),
                    func.word_similarity(term, NAME_EXPR) > 0.55,
                )
            )
        for col, value in (
            (Student.college_id, college_id),
            (Student.status, status),
            (Student.category, category),
            (Student.gender, gender),
        ):
            if value is not None:
                stmt = stmt.where(col == value)
        if ids is not None:
            stmt = stmt.where(Student.id.in_(list(ids)))
        enrol = select(StudentProgramEnrollment.student_id).where(StudentProgramEnrollment.deleted_at.is_(None))
        narrowed = False
        if department_id is not None:
            enrol, narrowed = enrol.where(StudentProgramEnrollment.department_id == department_id), True
        if program_id is not None:
            enrol, narrowed = enrol.where(StudentProgramEnrollment.program_id == program_id), True
        if batch_id is not None:
            enrol, narrowed = enrol.where(StudentProgramEnrollment.batch_id == batch_id), True
        if standing is not None:
            enrol = enrol.where(
                StudentProgramEnrollment.academic_standing == standing,
                StudentProgramEnrollment.status.in_(OPEN_ENROLLMENT),
            )
            narrowed = True
        if narrowed:
            stmt = stmt.where(Student.id.in_(enrol))
        if section_id is not None:
            stmt = stmt.where(
                Student.id.in_(
                    select(StudentProgramEnrollment.student_id)
                    .join(
                        StudentTermRecord,
                        StudentTermRecord.student_program_enrollment_id == StudentProgramEnrollment.id,
                    )
                    .where(
                        StudentProgramEnrollment.deleted_at.is_(None),
                        StudentTermRecord.section_id == section_id,
                        StudentTermRecord.term_number
                        == select(func.max(StudentTermRecord.term_number))
                        .where(StudentTermRecord.student_program_enrollment_id == StudentProgramEnrollment.id)
                        .correlate(StudentProgramEnrollment)
                        .scalar_subquery(),
                    )
                )
            )
        if has_holds is not None:
            held = (
                select(StudentProgramEnrollment.student_id)
                .join(StudentHold, StudentHold.student_program_enrollment_id == StudentProgramEnrollment.id)
                .where(StudentHold.released_at.is_(None))
            )
            stmt = stmt.where(Student.id.in_(held) if has_holds else Student.id.not_in(held))
        return stmt

    async def get_visible(self, student_id: uuid.UUID, *, for_update: bool = False) -> Student:
        stmt = self._base().where(Student.id == student_id)
        if self.principal is not None:
            stmt = stmt.where(student_predicate(self.principal, "all"))
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        return row

    async def by_id(self, student_id: uuid.UUID, *, for_update: bool = False) -> Student | None:
        stmt = self._base().where(Student.id == student_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def by_user(self, user_id: uuid.UUID) -> Student | None:
        return (await self.db.execute(self._base().where(Student.user_id == user_id))).scalar_one_or_none()

    async def registration_taken(self, number: str) -> bool:
        stmt = select(Student.id).where(
            Student.institution_id == self.institution_id, func.upper(Student.registration_number) == number.upper()
        )
        return (await self.db.execute(stmt)).first() is not None

    async def apaar_taken(self, apaar_id: str, exclude: uuid.UUID | None = None) -> bool:
        stmt = select(Student.id).where(Student.institution_id == self.institution_id, Student.apaar_id == apaar_id)
        if exclude is not None:
            stmt = stmt.where(Student.id != exclude)
        return (await self.db.execute(stmt)).first() is not None

    async def by_registration_numbers(self, numbers: Sequence[str]) -> dict[str, Student]:
        if not numbers:
            return {}
        rows = (await self.db.execute(self._base().where(Student.registration_number.in_(list(numbers))))).scalars()
        return {r.registration_number: r for r in rows}

    async def count_seated(self, institution_id: uuid.UUID) -> int:
        stmt = select(func.count(Student.id)).where(
            Student.institution_id == institution_id,
            Student.deleted_at.is_(None),
            Student.status.in_([s.value for s in SEATED_STATUSES]),
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def users(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, User]:
        clean = [i for i in ids if i]
        if not clean:
            return {}
        rows = (await self.db.execute(select(User).where(User.id.in_(clean)))).scalars().all()
        return {r.id: r for r in rows}

    async def college_rows(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, College]:
        clean = [i for i in ids if i]
        if not clean:
            return {}
        rows = (await self.db.execute(select(College).where(College.id.in_(clean)))).scalars().all()
        return {r.id: r for r in rows}

    async def department_rows(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Department]:
        clean = [i for i in ids if i]
        if not clean:
            return {}
        rows = (await self.db.execute(select(Department).where(Department.id.in_(clean)))).scalars().all()
        return {r.id: r for r in rows}

    async def program_rows(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Program]:
        clean = [i for i in ids if i]
        if not clean:
            return {}
        rows = (await self.db.execute(select(Program).where(Program.id.in_(clean)))).scalars().all()
        return {r.id: r for r in rows}

    async def batch_rows(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Batch]:
        clean = [i for i in ids if i]
        if not clean:
            return {}
        rows = (await self.db.execute(select(Batch).where(Batch.id.in_(clean)))).scalars().all()
        return {r.id: r for r in rows}

    async def section_rows(self, ids: Sequence[uuid.UUID | None]) -> dict[uuid.UUID, BatchSection]:
        clean = [i for i in ids if i]
        if not clean:
            return {}
        rows = (await self.db.execute(select(BatchSection).where(BatchSection.id.in_(clean)))).scalars().all()
        return {r.id: r for r in rows}

    async def stats(self, visible: Any, dimension: str) -> list[tuple[Any, int]]:
        """Counts of visible students grouped by a dimension (``status`` / ``category`` / ``gender`` on ``students``,
        ``program`` / ``batch`` / ``standing`` on the open — else latest — enrolment)."""
        if dimension in ("status", "category", "gender"):
            col = getattr(Student, dimension)
            stmt = select(col, func.count(Student.id)).where(Student.id.in_(visible)).group_by(col)
            return [(k, int(n)) for k, n in (await self.db.execute(stmt)).all()]
        col = {
            "program": StudentProgramEnrollment.program_id,
            "batch": StudentProgramEnrollment.batch_id,
            "standing": StudentProgramEnrollment.academic_standing,
        }[dimension]
        stmt = (
            select(col, func.count(func.distinct(StudentProgramEnrollment.student_id)))
            .where(
                StudentProgramEnrollment.deleted_at.is_(None),
                StudentProgramEnrollment.student_id.in_(visible),
                StudentProgramEnrollment.status.in_(OPEN_ENROLLMENT + ("completed",)),
            )
            .group_by(col)
        )
        return [(k, int(n)) for k, n in (await self.db.execute(stmt)).all()]


class StudentDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def for_student(self, student_id: uuid.UUID) -> Sequence[StudentDocument]:
        stmt = (
            select(StudentDocument)
            .where(StudentDocument.student_id == student_id)
            .order_by(StudentDocument.uploaded_at.desc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def get(self, doc_id: uuid.UUID, *, for_update: bool = False) -> StudentDocument | None:
        stmt = select(StudentDocument).where(StudentDocument.id == doc_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def add(self, obj: StudentDocument) -> StudentDocument:
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def delete(self, obj: StudentDocument) -> None:
        await self.db.delete(obj)
        await self.db.flush()

    async def expiring(self, institution_id: uuid.UUID, today: date, until: date) -> Sequence[tuple[Any, Any]]:
        stmt = (
            select(StudentDocument, Student)
            .join(Student, Student.id == StudentDocument.student_id)
            .where(
                StudentDocument.institution_id == institution_id,
                StudentDocument.expires_on.is_not(None),
                StudentDocument.expires_on >= today,
                StudentDocument.expires_on <= until,
                Student.deleted_at.is_(None),
                Student.status.in_([s.value for s in SEATED_STATUSES]),
            )
        )
        return [(d, s) for d, s in (await self.db.execute(stmt)).all()]


class UndertakingRepository:
    """Accepted undertakings and the undertaking templates (platform ``document_templates`` of type ``undertaking`` —
    the table belongs to Phase 26, so it is read with SQL here; an institution override wins over the platform row)."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def for_student(self, student_id: uuid.UUID) -> Sequence[StudentUndertaking]:
        stmt = (
            select(StudentUndertaking)
            .where(StudentUndertaking.student_id == student_id)
            .order_by(StudentUndertaking.accepted_at.desc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def find(
        self, student_id: uuid.UUID, undertaking_type: str, template_id: uuid.UUID | None
    ) -> StudentUndertaking | None:
        stmt = select(StudentUndertaking).where(
            StudentUndertaking.student_id == student_id,
            StudentUndertaking.undertaking_type == undertaking_type,
            (
                StudentUndertaking.template_id.is_(None)
                if template_id is None
                else StudentUndertaking.template_id == template_id
            ),
        )
        return (await self.db.execute(stmt.with_for_update())).scalar_one_or_none()

    async def add(self, obj: StudentUndertaking) -> StudentUndertaking:
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def templates(self, institution_id: uuid.UUID, template_type: str = "undertaking") -> list[dict[str, Any]]:
        rows = (
            (
                await self.db.execute(
                    text(
                        "SELECT id, institution_id, name, html_template, layout, version FROM document_templates "
                        "WHERE template_type = :t AND is_active AND deleted_at IS NULL "
                        "AND (institution_id IS NULL OR institution_id = :i) "
                        "ORDER BY institution_id NULLS LAST, version DESC"
                    ),
                    {"t": template_type, "i": institution_id},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def accepted_since(
        self, student_ids: Sequence[uuid.UUID], since: Any
    ) -> dict[uuid.UUID, dict[str, StudentUndertaking]]:
        out: dict[uuid.UUID, dict[str, StudentUndertaking]] = {s: {} for s in student_ids}
        if not student_ids:
            return out
        stmt = select(StudentUndertaking).where(
            StudentUndertaking.student_id.in_(list(student_ids)), StudentUndertaking.accepted_at >= since
        )
        for row in (await self.db.execute(stmt)).scalars():
            out.setdefault(row.student_id, {})[row.undertaking_type] = row
        return out


def ip_text(value: Any) -> str | None:
    return None if value is None else str(value)
