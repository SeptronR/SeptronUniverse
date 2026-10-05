"""Staff master, designations and the staff records (faculty profile, qualifications, documents, service book) —
Prompts/06 §06.5 ``staff_repository.py`` (``module="hr"``; search by name / employee id; filters department /
designation / type / status). Visibility: ``repositories/hr_scope.py``."""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import Select, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError, ErrorCode
from app.models.hr import (
    Designation,
    FacultyProfile,
    FacultyQualification,
    ServiceBookEntry,
    Staff,
    StaffDocument,
)
from app.models.platform import Department, Role, User, UserRole
from app.repositories.base import BaseRepository
from app.repositories.hr_scope import staff_predicate


class StaffRepository(BaseRepository[Staff]):
    model = Staff
    module = "hr"

    def filtered(
        self,
        *,
        scope: str | None = None,
        module: str = "hr",
        q: str | None = None,
        department_id: uuid.UUID | None = None,
        designation_id: uuid.UUID | None = None,
        college_id: uuid.UUID | None = None,
        employment_type: str | None = None,
        staff_category: str | None = None,
        status: str | None = None,
    ) -> Select[tuple[Staff]]:
        stmt = self._base()
        if self.principal is not None:
            stmt = stmt.where(staff_predicate(self.principal, module, scope))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    func.concat_ws(" ", Staff.first_name, Staff.middle_name, Staff.last_name).ilike(like),
                    Staff.employee_id.ilike(like),
                    Staff.email.ilike(like),
                )
            )
        for col, value in (
            (Staff.department_id, department_id),
            (Staff.designation_id, designation_id),
            (Staff.college_id, college_id),
            (Staff.employment_type, employment_type),
            (Staff.staff_category, staff_category),
            (Staff.status, status),
        ):
            if value is not None:
                stmt = stmt.where(col == value)
        return stmt

    async def get_visible(self, staff_id: uuid.UUID, *, module: str = "hr", for_update: bool = False) -> Staff:
        stmt = self._base().where(Staff.id == staff_id)
        if self.principal is not None:
            stmt = stmt.where(staff_predicate(self.principal, module, "all"))
        if for_update:
            stmt = stmt.with_for_update()
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Staff not found")
        return row

    async def by_id(self, staff_id: uuid.UUID) -> Staff | None:
        return (await self.db.execute(self._base().where(Staff.id == staff_id))).scalar_one_or_none()

    async def by_user(self, user_id: uuid.UUID) -> Staff | None:
        return (await self.db.execute(self._base().where(Staff.user_id == user_id))).scalar_one_or_none()

    async def by_employee_codes(self, codes: Sequence[str]) -> dict[str, Staff]:
        if not codes:
            return {}
        rows = (await self.db.execute(self._base().where(Staff.employee_id.in_(list(codes))))).scalars().all()
        return {r.employee_id: r for r in rows}

    async def employee_id_taken(self, employee_id: str) -> bool:
        stmt = select(Staff.id).where(Staff.institution_id == self.institution_id, Staff.employee_id == employee_id)
        return (await self.db.execute(stmt)).first() is not None

    async def active(
        self,
        *,
        college_id: uuid.UUID | None = None,
        staff_ids: Sequence[uuid.UUID] | None = None,
        department_id: uuid.UUID | None = None,
        teaching_only: bool = False,
    ) -> Sequence[Staff]:
        stmt = self._base().where(Staff.status != "exited")
        if college_id is not None:
            stmt = stmt.where(Staff.college_id == college_id)
        if staff_ids:
            stmt = stmt.where(Staff.id.in_(list(staff_ids)))
        if department_id is not None:
            stmt = stmt.where(Staff.department_id == department_id)
        if teaching_only:
            stmt = stmt.where(Staff.staff_category == "teaching")
        return (await self.db.execute(stmt.order_by(Staff.employee_id))).scalars().all()

    async def names(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
        """staff id → (full name, employee id)."""
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = (await self.db.execute(select(Staff).where(Staff.id.in_(ids)))).scalars().all()
        return {r.id: (r.full_name, r.employee_id) for r in rows}

    async def department_rows(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Department]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = (await self.db.execute(select(Department).where(Department.id.in_(ids)))).scalars().all()
        return {r.id: r for r in rows}

    async def user(self, user_id: uuid.UUID) -> User | None:
        return (await self.db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

    async def usernames(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = (await self.db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
        return {r[0]: r[1] for r in rows}

    async def username_taken(self, username: str) -> bool:
        stmt = select(User.id).where(User.institution_id == self.institution_id, User.username == username)
        return (await self.db.execute(stmt)).first() is not None

    async def unit_assignments(self, user_id: uuid.UUID) -> Sequence[tuple[str, str, uuid.UUID | None]]:
        """(role slug, scope type, scope id) of the user's assignments — links HOD/dean/advisor units to the row."""
        rows = (
            await self.db.execute(
                select(Role.slug, UserRole.scope_type, UserRole.scope_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(UserRole.user_id == user_id)
            )
        ).all()
        return [(slug, st, sid) for slug, st, sid in rows]

    async def link_unit(self, table: str, column: str, scope_id: uuid.UUID, staff_id: uuid.UUID) -> int:
        """Back a Phase 03/05 unit holder with the staff row (``departments.hod_staff_id`` …) unless another staff row
        already holds the unit. ``table``/``column`` are literals chosen by the service."""
        allowed = {
            ("departments", "hod_staff_id"),
            ("faculties", "dean_staff_id"),
            ("batch_sections", "class_advisor_staff_id"),
        }
        assert (table, column) in allowed
        res = await self.db.execute(
            text(
                f"UPDATE {table} SET {column} = :s WHERE id = :x AND ({column} IS NULL OR {column} = :s)"  # noqa: S608 - literals above
            ),
            {"s": staff_id, "x": scope_id},
        )
        return int(getattr(res, "rowcount", 0) or 0)

    async def clear_reports_to(self, staff_id: uuid.UUID) -> None:
        await self.db.execute(
            update(Staff).where(Staff.reports_to_staff_id == staff_id).values(reports_to_staff_id=None)
        )


class DesignationRepository(BaseRepository[Designation]):
    model = Designation
    module = "hr"

    async def all(self, include_inactive: bool = False) -> Sequence[Designation]:
        stmt = self._base()
        if not include_inactive:
            stmt = stmt.where(Designation.is_active.is_(True))
        return (
            (
                await self.db.execute(
                    stmt.order_by(Designation.category, Designation.level.desc().nulls_last(), Designation.name)
                )
            )
            .scalars()
            .all()
        )

    async def get_one(self, designation_id: uuid.UUID) -> Designation:
        row = (await self.db.execute(self._base().where(Designation.id == designation_id))).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Designation not found")
        return row

    async def by_name(self, name: str) -> Designation | None:
        return (
            await self.db.execute(self._base().where(func.lower(Designation.name) == name.lower()))
        ).scalar_one_or_none()

    async def by_cadre(self, cadre: str) -> Designation | None:
        stmt = (
            self._base()
            .where(Designation.cadre == cadre, Designation.is_active.is_(True))
            .order_by(Designation.level.desc().nulls_last())
        )
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    async def in_use(self, designation_id: uuid.UUID) -> bool:
        stmt = select(Staff.id).where(Staff.designation_id == designation_id, Staff.deleted_at.is_(None)).limit(1)
        return (await self.db.execute(stmt)).first() is not None

    async def by_ids(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Designation]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = (await self.db.execute(select(Designation).where(Designation.id.in_(ids)))).scalars().all()
        return {r.id: r for r in rows}


class StaffRecordsRepository:
    """Faculty profile, qualifications, documents and service book of one staff member."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def profile(self, staff_id: uuid.UUID) -> FacultyProfile | None:
        return (
            await self.db.execute(select(FacultyProfile).where(FacultyProfile.staff_id == staff_id))
        ).scalar_one_or_none()

    async def profiles(self, staff_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, FacultyProfile]:
        if not staff_ids:
            return {}
        rows = (
            (await self.db.execute(select(FacultyProfile).where(FacultyProfile.staff_id.in_(list(staff_ids)))))
            .scalars()
            .all()
        )
        return {r.staff_id: r for r in rows}

    async def qualifications(self, staff_id: uuid.UUID) -> Sequence[FacultyQualification]:
        stmt = (
            select(FacultyQualification)
            .where(FacultyQualification.staff_id == staff_id)
            .order_by(FacultyQualification.is_highest.desc(), FacultyQualification.year.desc().nulls_last())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def clear_highest(self, staff_id: uuid.UUID) -> None:
        await self.db.execute(
            update(FacultyQualification).where(FacultyQualification.staff_id == staff_id).values(is_highest=False)
        )

    async def documents(self, staff_id: uuid.UUID) -> Sequence[StaffDocument]:
        stmt = (
            select(StaffDocument).where(StaffDocument.staff_id == staff_id).order_by(StaffDocument.uploaded_at.desc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def expiring_documents(self, today: date, until: date) -> Sequence[tuple[StaffDocument, Staff]]:
        stmt = (
            select(StaffDocument, Staff)
            .join(Staff, Staff.id == StaffDocument.staff_id)
            .where(
                StaffDocument.expires_on.is_not(None),
                StaffDocument.expires_on >= today,
                StaffDocument.expires_on <= until,
                Staff.deleted_at.is_(None),
                Staff.status != "exited",
            )
        )
        return [(d, s) for d, s in (await self.db.execute(stmt)).all()]

    async def service_book(self, staff_id: uuid.UUID) -> Sequence[ServiceBookEntry]:
        stmt = (
            select(ServiceBookEntry)
            .where(ServiceBookEntry.staff_id == staff_id)
            .order_by(ServiceBookEntry.effective_date.desc(), ServiceBookEntry.created_at.desc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def last_entry(self, staff_id: uuid.UUID, entry_type: str) -> ServiceBookEntry | None:
        stmt = (
            select(ServiceBookEntry)
            .where(ServiceBookEntry.staff_id == staff_id, ServiceBookEntry.entry_type == entry_type)
            .order_by(ServiceBookEntry.effective_date.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def add(self, obj: Any) -> Any:
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def counts(self, sql: str, params: dict[str, Any]) -> int:
        """Count rows of a later-phase table (Phase 30 research metrics) — 0 when it holds nothing yet."""
        try:
            async with self.db.begin_nested():
                return int((await self.db.execute(text(sql), params)).scalar() or 0)
        except Exception:  # noqa: BLE001 - an absent / not-yet-populated table simply contributes nothing
            return 0
