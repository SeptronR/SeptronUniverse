"""Faculties, departments, HOD and dean assignment — Prompts/03 §03.6 ``department_service``.

Business rules
1. Departments/faculties are institution-wide readable; writes need ``departments:manage`` and — for a college-scoped
   admin — the parent college in scope (else 404 on the lookup / 403 on create). ``code`` is unique per college (409).
   A department's faculty must belong to the same college (422). Faculties need ``institution.faculties``.
2. HOD assignment (``PUT /departments/{id}/hod``): the person must be **staff of the college** — a ``staff`` row
   (Phase 06) whose ``college_id`` is the department's college (or NULL), or, until staff records exist, an active
   ``user_type = 'staff'`` user of the institution; anything else → 422. The ``hod`` role is granted scoped to the
   department through ``RbacService.assign`` (audited, ``user_role.assigned``); the previous HOD's ``hod``
   @department assignment is revoked. ``departments.hod_staff_id`` is set when a staff row exists (FK to ``staff``),
   otherwise left NULL — the role assignment is the source of truth for the holder (``hod_user_id`` in responses).
3. Dean assignment (faculty create/update ``dean_user_id``) follows rule 2 with the ``dean`` role @faculty.
4. Delete is soft; a faculty with departments or a department that still has an HOD assignment is refused (409).
5. Audit on every change; ``department.updated`` event (consumer ``search.reindex``).
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.audit import log_audit
from app.core.errors import APIError, ErrorCode
from app.models.platform import Department, Faculty, User
from app.repositories.college_repository import CollegeRepository
from app.repositories.department_repository import DepartmentRepository, FacultyRepository, UnitHolderRepository
from app.repositories.role_repository import RoleRepository
from app.schemas.institution import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    FacultyCreate,
    FacultyResponse,
    FacultyUpdate,
    HodAssign,
)
from app.schemas.rbac import UserRoleAssign
from app.services.institution.context import (
    check_college_writable,
    scope_college_filter,
    structure_visibility,
    tenant_id,
    writable_college_ids,
)
from app.services.rbac_service import RbacService
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta


def _snap(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in ((k, getattr(obj, k)) for k in keys)}


DEPT_KEYS = ("code", "name", "college_id", "faculty_id", "department_type", "hod_staff_id", "established_year")
FAC_KEYS = ("code", "name", "college_id", "dean_staff_id")


class DepartmentService:
    def __init__(self, db: AsyncSession, principal: Any, request: Request | None = None):
        self.db, self.principal, self.request = db, principal, request
        self.inst = tenant_id(principal, request)
        self.repo = DepartmentRepository(db, principal, self.inst)
        self.faculties = FacultyRepository(db, principal, self.inst)
        self.colleges = CollegeRepository(db, principal, self.inst)
        self.holders = UnitHolderRepository(db)

    # ---- departments: reads ---------------------------------------------------------------------------------------
    async def list_page(
        self,
        params: PageParams,
        scope: str | None,
        college_id: uuid.UUID | None,
        faculty_id: uuid.UUID | None,
        department_type: str | None,
        q: str | None,
    ) -> tuple[list[DepartmentResponse], PaginationMeta, VisibilityMeta]:
        college_ids = [college_id] if college_id else scope_college_filter(self.principal, scope)
        stmt = self.repo.filtered(college_ids=college_ids, faculty_id=faculty_id, department_type=department_type, q=q)
        if not params.sort:
            params = params.model_copy(update={"sort": "code"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._responses(list(rows)), pagination, structure_visibility(self.principal)

    async def get(self, department_id: uuid.UUID) -> DepartmentResponse:
        d = await self.repo.get_scoped(department_id, None)
        return (await self._responses([d]))[0]

    async def _responses(self, rows: list[Department]) -> list[DepartmentResponse]:
        hods = await self.holders.holders("hod", "department", [d.id for d in rows])
        codes = await self.colleges.codes(list({d.college_id for d in rows}))
        fac_codes = await self.faculties.codes([d.faculty_id for d in rows if d.faculty_id])
        out = []
        for d in rows:
            r = DepartmentResponse.model_validate(d)
            holder = hods.get(d.id)
            r.hod_user_id, r.hod_name = (holder[0], holder[1]) if holder else (None, None)
            r.college_code = codes.get(d.college_id)
            r.faculty_code = fac_codes.get(d.faculty_id) if d.faculty_id else None
            out.append(r)
        return out

    # ---- departments: writes (rule 1) -----------------------------------------------------------------------------
    async def create(self, body: DepartmentCreate) -> DepartmentResponse:
        college = await self.colleges.get_readable(body.college_id)
        check_college_writable(self.principal, college.id)
        await self._check_faculty(body.faculty_id, college.id)
        if await self.repo.by_code(self.inst, college.id, body.code):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"Department code {body.code!r} already exists in this college",
                {"field": "code"},
            )
        values = body.model_dump()
        values["code"] = body.code.upper()
        d = await self.repo.create(institution_id=self.inst, created_by=self.principal.id, **values)
        await self._audit("create", "department", d.id, None, _snap(d, DEPT_KEYS))
        await self._emit(d, "created")
        return (await self._responses([d]))[0]

    async def update(self, department_id: uuid.UUID, body: DepartmentUpdate) -> DepartmentResponse:
        d = await self.repo.get_scoped(department_id, writable_college_ids(self.principal))
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if "faculty_id" in values:
            await self._check_faculty(values["faculty_id"], d.college_id)
        old = _snap(d, DEPT_KEYS)
        await self.repo.update(d, expected_version=body.version, **values)
        await self._audit("update", "department", d.id, old, _snap(d, DEPT_KEYS))
        await self._emit(d, "updated")
        return (await self._responses([d]))[0]

    async def delete(self, department_id: uuid.UUID) -> None:
        d = await self.repo.get_scoped(department_id, writable_college_ids(self.principal))
        if await self.holders.assignments("hod", "department", d.id):
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Revoke the HOD assignment before deleting the department")
        old = _snap(d, DEPT_KEYS)
        await self.repo.soft_delete(d, self.principal.id)
        await self._audit("delete", "department", d.id, old, None)
        await self._emit(d, "deleted")

    async def _check_faculty(self, faculty_id: uuid.UUID | None, college_id: uuid.UUID) -> None:
        if faculty_id is None:
            return
        f = await self.faculties.get_scoped(faculty_id, None)
        if f.college_id != college_id:
            raise APIError(422, ErrorCode.VALIDATION, "The faculty belongs to another college", {"field": "faculty_id"})

    # ---- rule 2: HOD ----------------------------------------------------------------------------------------------
    async def assign_hod(self, department_id: uuid.UUID, body: HodAssign) -> DepartmentResponse:
        d = await self.repo.get_scoped(department_id, writable_college_ids(self.principal))
        user, staff_id = await self._staff_of_college(body.staff_id or body.user_id, d.college_id)  # type: ignore[arg-type]
        old = {
            "hod_staff_id": str(d.hod_staff_id) if d.hod_staff_id else None,
            "hod_user_id": await self._holder("hod", "department", d.id),
        }
        await self._grant_unit_role(user, "hod", "department", d.id)
        d.hod_staff_id = staff_id
        await self.db.flush()
        await self._audit(
            "assign_hod",
            "department",
            d.id,
            old,
            {"hod_staff_id": str(staff_id) if staff_id else None, "hod_user_id": str(user.id)},
        )
        await self._emit(d, "hod_assigned", {"hod_user_id": str(user.id)})
        return (await self._responses([d]))[0]

    async def _holder(self, slug: str, scope_type: str, scope_id: uuid.UUID) -> str | None:
        h = (await self.holders.holders(slug, scope_type, [scope_id])).get(scope_id)
        return str(h[0]) if h else None

    async def _staff_of_college(self, ident: uuid.UUID, college_id: uuid.UUID) -> tuple[User, uuid.UUID | None]:
        staff = await self.holders.staff_row(self.inst, ident)
        if staff is not None:
            if staff["college_id"] not in (None, college_id):
                raise APIError(
                    422, ErrorCode.VALIDATION, "The staff member belongs to another college", {"field": "staff_id"}
                )
            if staff["user_id"] is None:
                raise APIError(422, ErrorCode.VALIDATION, "The staff member has no user account", {"field": "staff_id"})
            user = await self.holders.user(self.inst, staff["user_id"])
            if user is None:
                raise APIError(
                    422, ErrorCode.VALIDATION, "The staff member's account is inactive", {"field": "staff_id"}
                )
            return user, staff["id"]
        user = await self.holders.user(self.inst, ident)
        if user is None or user.user_type != "staff":
            raise APIError(422, ErrorCode.VALIDATION, "Not a staff member of this institution", {"field": "staff_id"})
        return user, None

    async def _grant_unit_role(self, user: User, slug: str, scope_type: str, scope_id: uuid.UUID) -> None:
        role = await RoleRepository(self.db).get_by_slug(slug, self.inst)
        if role is None:
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"The institution has no {slug!r} role (seed the roles first)"
            )
        rbac = RbacService(self.db, self.principal)
        already = False
        for ur in await self.holders.assignments(slug, scope_type, scope_id):
            if ur.user_id == user.id:
                already = True
                continue
            previous = await self.holders.user(self.inst, ur.user_id)
            if previous is not None:
                await rbac.revoke(previous, ur.id, self.request)
        if not already:
            await rbac.assign(
                user, UserRoleAssign(role_id=role.id, scope_type=scope_type, scope_id=scope_id), self.request
            )

    # ---- faculties ------------------------------------------------------------------------------------------------
    async def list_faculties(
        self, params: PageParams, scope: str | None, college_id: uuid.UUID | None, q: str | None
    ) -> tuple[list[FacultyResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.faculties.filtered(college_id, q)
        ids = None if college_id else scope_college_filter(self.principal, scope)
        if ids is not None:
            stmt = stmt.where(Faculty.college_id.in_(ids))
        if not params.sort:
            params = params.model_copy(update={"sort": "code"})
        rows, pagination = await self.faculties.paginate(stmt, params)
        return await self._fac_responses(list(rows)), pagination, structure_visibility(self.principal)

    async def _fac_responses(self, rows: list[Faculty]) -> list[FacultyResponse]:
        deans = await self.holders.holders("dean", "faculty", [f.id for f in rows])
        counts = await self.repo.count_for_faculties([f.id for f in rows])
        out = []
        for f in rows:
            r = FacultyResponse.model_validate(f)
            holder = deans.get(f.id)
            r.dean_user_id, r.dean_name = (holder[0], holder[1]) if holder else (None, None)
            r.department_count = counts.get(f.id, 0)
            out.append(r)
        return out

    async def create_faculty(self, body: FacultyCreate) -> FacultyResponse:
        college = await self.colleges.get_readable(body.college_id)
        check_college_writable(self.principal, college.id)
        if await self.faculties.by_code(self.inst, college.id, body.code):
            raise APIError(409, ErrorCode.CONFLICT, f"Faculty code {body.code!r} already exists", {"field": "code"})
        f = await self.faculties.create(
            institution_id=self.inst,
            college_id=college.id,
            code=body.code.upper(),
            name=body.name,
            created_by=self.principal.id,
        )
        if body.dean_user_id:
            await self._assign_dean(f, body.dean_user_id)
        await self._audit("create", "faculty", f.id, None, _snap(f, FAC_KEYS))
        return (await self._fac_responses([f]))[0]

    async def update_faculty(self, faculty_id: uuid.UUID, body: FacultyUpdate) -> FacultyResponse:
        f = await self.faculties.get_scoped(faculty_id, writable_college_ids(self.principal))
        old = _snap(f, FAC_KEYS)
        values = body.model_dump(exclude_unset=True, exclude={"version", "dean_user_id"})
        await self.faculties.update(f, expected_version=body.version, **values)
        if body.dean_user_id:
            await self._assign_dean(f, body.dean_user_id)
        await self._audit("update", "faculty", f.id, old, _snap(f, FAC_KEYS))
        return (await self._fac_responses([f]))[0]

    async def _assign_dean(self, f: Faculty, ident: uuid.UUID) -> None:
        user, staff_id = await self._staff_of_college(ident, f.college_id)
        await self._grant_unit_role(user, "dean", "faculty", f.id)
        f.dean_staff_id = staff_id
        await self.db.flush()

    async def delete_faculty(self, faculty_id: uuid.UUID) -> None:
        f = await self.faculties.get_scoped(faculty_id, writable_college_ids(self.principal))
        if (await self.repo.count_for_faculties([f.id])).get(f.id):
            raise APIError(409, ErrorCode.RULE_VIOLATION, "The faculty still has departments")
        old = _snap(f, FAC_KEYS)
        await self.faculties.soft_delete(f, self.principal.id)
        await self._audit("delete", "faculty", f.id, old, None)

    # ---- rule 5 ---------------------------------------------------------------------------------------------------
    async def _audit(
        self,
        action: str,
        record_type: str,
        record_id: uuid.UUID,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
    ) -> None:
        await log_audit(
            self.db,
            principal=self.principal,
            module="departments" if record_type == "department" else "faculties",
            action=action,
            record_type=record_type,
            record_id=record_id,
            old=old,
            new=new,
            request=self.request,
        )

    async def _emit(self, d: Department, change: str, extra: dict[str, Any] | None = None) -> None:
        await events.emit(
            self.db,
            institution_id=self.inst,
            event_type="department.updated",
            payload={
                "department_id": str(d.id),
                "code": d.code,
                "college_id": str(d.college_id),
                "change": change,
                **(extra or {}),
            },
            aggregate_type="department",
            aggregate_id=d.id,
            actor_user_id=self.principal.id,
        )
