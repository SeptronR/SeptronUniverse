"""Programmes and programme-regulation bindings — Prompts/05 §05.6 ``program_service``.

Business rules
1. CRUD with ``programs:*``; ``code`` unique per college (409); the department (and faculty, when given) must belong to
   the programme's college (422); writes are narrowed to the caller's units (``academics.context``).
2. ``exam_authority`` defaults from the institution type: an affiliated college's programmes are examined by the
   **university**, everything else by the autonomous college/university itself (``autonomous_college``).
3. ``is_open_enrolment`` is only allowed for ``certificate`` / ``diploma`` levels (value-added / CE courses).
4. Closing (``POST /programs/{id}/close``) requires **no active batches** (409 listing the count); delete is soft and
   refused while batches or programme-regulations exist.
5. Programme-regulation bindings (``curriculum:manage``): one per (programme, regulation); the regulation must be of
   the programme's college or institution-wide; ``rules_override`` is validated by merging it over the regulation's
   rules (``RegulationRules``); ``total_credits_required`` > 0.
6. Events ``program.created`` / ``program.updated`` (consumer ``catalog.invalidate``); every write audited.
"""

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

import app.services.academics.visibility  # noqa: F401  (registers the Phase 05 visibility modules)
from app.core.errors import APIError, ErrorCode
from app.models.academic import Program, ProgramRegulation
from app.models.platform import Department
from app.repositories.college_repository import CollegeRepository
from app.repositories.department_repository import DepartmentRepository, FacultyRepository
from app.repositories.institution_repository import InstitutionRepository
from app.repositories.program_repository import ProgramRegulationRepository, ProgramRepository
from app.repositories.regulation_repository import RegulationRepository
from app.schemas.academics import (
    ProgramCreate,
    ProgramRegulationCreate,
    ProgramRegulationResponse,
    ProgramRegulationUpdate,
    ProgramResponse,
    ProgramUpdate,
    RegulationRules,
    merge_rules,
)
from app.services.academics.common import AcademicServiceBase, ensure_structure_editable, snap
from app.services.academics.context import (
    academic_visibility,
    check_department_writable,
    scope_filters,
    writable_department_ids,
)
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

PROGRAM_KEYS = (
    "code",
    "name",
    "degree_name",
    "specialization",
    "college_id",
    "faculty_id",
    "department_id",
    "level",
    "mode",
    "term_pattern",
    "duration_years",
    "total_terms",
    "sanctioned_intake",
    "lateral_intake",
    "approving_body",
    "exam_authority",
    "is_open_enrolment",
    "status",
)
PR_KEYS = ("program_id", "regulation_id", "total_credits_required", "rules_override", "status")
OPEN_ENROLMENT_LEVELS = {"certificate", "diploma"}


def validate_override(base_rules: dict[str, Any], override: dict[str, Any] | None) -> None:
    if not override:
        return
    try:
        RegulationRules.model_validate(merge_rules(base_rules, override))
    except ValidationError as exc:
        raise APIError(
            422,
            ErrorCode.VALIDATION,
            "rules_override is not valid",
            {"field": "rules_override", "errors": exc.errors(include_url=False, include_context=False)},
        ) from exc


class ProgramService(AcademicServiceBase):
    audit_module = "programs"

    def __init__(self, db: Any, principal: Any, request: Any = None):
        super().__init__(db, principal, request)
        self.repo = ProgramRepository(db, principal, self.inst)
        self.bindings = ProgramRegulationRepository(db, principal, self.inst)
        self.regulations = RegulationRepository(db, principal, self.inst)
        self.colleges = CollegeRepository(db, principal, self.inst)
        self.departments = DepartmentRepository(db, principal, self.inst)
        self.faculties = FacultyRepository(db, principal, self.inst)

    # ---- reads -----------------------------------------------------------------------------------------------------
    async def list_page(
        self,
        params: PageParams,
        scope: str | None,
        *,
        college_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        level: str | None,
        status: str | None,
        q: str | None,
    ) -> tuple[list[ProgramResponse], PaginationMeta, VisibilityMeta]:
        dept_ids, college_ids = scope_filters(self.principal, scope)
        stmt = self.repo.filtered(
            college_ids=[college_id] if college_id else college_ids,
            department_id=department_id,
            level=level,
            status=status,
            q=q,
        )
        if dept_ids is not None and not department_id:
            stmt = stmt.where(Program.department_id.in_(list(dept_ids)))
        if not params.sort:
            params = params.model_copy(update={"sort": "code"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._responses(list(rows)), pagination, academic_visibility(self.principal)

    async def get(self, program_id: uuid.UUID) -> ProgramResponse:
        return (await self._responses([await self.repo.get_program(program_id)]))[0]

    async def _responses(self, rows: list[Program]) -> list[ProgramResponse]:
        codes = await self.colleges.codes(list({p.college_id for p in rows}))
        writable = await writable_department_ids(self.db, self.principal)
        dept_codes = {d.id: d.code for d in await self._departments([p.department_id for p in rows])}
        out = []
        for p in rows:
            r = ProgramResponse.model_validate(p)
            r.college_code = codes.get(p.college_id)
            r.department_code = dept_codes.get(p.department_id)
            r.can_edit = self.principal.has("programs", "update") and (writable is None or p.department_id in writable)
            out.append(r)
        return out

    async def _departments(self, ids: list[uuid.UUID]) -> list[Department]:
        if not ids:
            return []
        return list((await self.db.execute(select(Department).where(Department.id.in_(ids)))).scalars().all())

    # ---- writes (rules 1–4) -----------------------------------------------------------------------------------------
    async def create(self, body: ProgramCreate) -> ProgramResponse:
        college = await self.colleges.get_readable(body.college_id)
        dept = await self.departments.get_scoped(body.department_id, None)
        if dept.college_id != college.id:
            raise APIError(
                422, ErrorCode.VALIDATION, "The department belongs to another college", {"field": "department_id"}
            )
        check_department_writable(await writable_department_ids(self.db, self.principal), dept.id, create=True)
        faculty_id = body.faculty_id or dept.faculty_id
        if faculty_id is not None:
            fac = await self.faculties.get_scoped(faculty_id, None)
            if fac.college_id != college.id:
                raise APIError(
                    422, ErrorCode.VALIDATION, "The faculty belongs to another college", {"field": "faculty_id"}
                )
        if await self.repo.by_code(self.inst, college.id, body.code):
            raise APIError(
                409, ErrorCode.CONFLICT, f"Programme code {body.code!r} exists in this college", {"field": "code"}
            )
        self._check_open_enrolment(body.level.value, body.is_open_enrolment)
        values = body.model_dump(exclude={"exam_authority", "faculty_id"})
        values.update(
            code=body.code.upper(),
            faculty_id=faculty_id,
            level=body.level.value,
            mode=body.mode.value,
            term_pattern=body.term_pattern.value,
            status=body.status.value,
            exam_authority=(body.exam_authority.value if body.exam_authority else await self._default_authority()),
        )
        p = await self.repo.create(institution_id=self.inst, created_by=self.principal.id, **values)
        await self._audit("create", "program", p.id, None, snap(p, PROGRAM_KEYS))
        await self._event(p, "program.created")
        return (await self._responses([p]))[0]

    async def update(self, program_id: uuid.UUID, body: ProgramUpdate) -> ProgramResponse:
        p = await self._writable(program_id)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        for k in ("mode", "term_pattern", "exam_authority"):
            if values.get(k) is not None:
                values[k] = str(values[k])
        if "faculty_id" in values and values["faculty_id"] is not None:
            fac = await self.faculties.get_scoped(values["faculty_id"], None)
            if fac.college_id != p.college_id:
                raise APIError(
                    422, ErrorCode.VALIDATION, "The faculty belongs to another college", {"field": "faculty_id"}
                )
        self._check_open_enrolment(p.level, values.get("is_open_enrolment", p.is_open_enrolment))
        old = snap(p, PROGRAM_KEYS)
        await self.repo.update(p, expected_version=body.version, **values)
        await self._audit("update", "program", p.id, old, snap(p, PROGRAM_KEYS))
        await self._event(p, "program.updated")
        return (await self._responses([p]))[0]

    async def close(self, program_id: uuid.UUID) -> ProgramResponse:
        p = await self._writable(program_id)
        active = await self.repo.active_batch_count(p.id)
        if active:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"{active} active batch(es) still run this programme",
                {"active_batches": active},
            )
        old = snap(p, PROGRAM_KEYS)
        p.status = "closed"
        await self.db.flush()
        await self._audit("close", "program", p.id, old, snap(p, PROGRAM_KEYS))
        await self._event(p, "program.updated", change="closed")
        return (await self._responses([p]))[0]

    async def delete(self, program_id: uuid.UUID) -> None:
        p = await self._writable(program_id)
        bound = await self.bindings.paginate(self.bindings.filtered(program_id=p.id), PageParams(page=1, page_size=1))
        if await self.repo.active_batch_count(p.id) or bound[1].total:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Remove the programme's regulations and batches first")
        old = snap(p, PROGRAM_KEYS)
        await self.repo.soft_delete(p, self.principal.id)
        await self._audit("delete", "program", p.id, old, None)
        await self._event(p, "program.updated", change="deleted")

    async def _writable(self, program_id: uuid.UUID) -> Program:
        p = await self.repo.get_program(program_id)
        check_department_writable(await writable_department_ids(self.db, self.principal), p.department_id, create=False)
        return p

    async def _default_authority(self) -> str:
        inst = await InstitutionRepository(self.db).get(self.inst)
        return (
            "university" if inst is not None and inst.institution_type == "affiliated_college" else "autonomous_college"
        )

    @staticmethod
    def _check_open_enrolment(level: str, flag: bool | None) -> None:
        if flag and level not in OPEN_ENROLMENT_LEVELS:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Open enrolment is only for certificate / diploma programmes",
                {"field": "is_open_enrolment"},
            )

    async def _event(self, p: Program, event_type: str, change: str | None = None) -> None:
        await self._emit(
            event_type,
            {"program_id": str(p.id), "code": p.code, "college_id": str(p.college_id), "change": change},
            "program",
            p.id,
        )

    # ---- programme-regulation bindings (rule 5) -----------------------------------------------------------------------
    async def list_bindings(
        self,
        params: PageParams,
        program_id: uuid.UUID | None,
        regulation_id: uuid.UUID | None,
        status: str | None,
    ) -> tuple[list[ProgramRegulationResponse], PaginationMeta]:
        from app.services.academics.enrolled import enrolled_pr_ids, reads_curriculum

        stmt = self.bindings.filtered(program_id=program_id, regulation_id=regulation_id, status=status)
        if not reads_curriculum(self.principal):  # students / parents: their (wards') enrolment only (Phase 07)
            stmt = stmt.where(ProgramRegulation.id.in_(await enrolled_pr_ids(self.db, self.principal)))
        rows, pagination = await self.bindings.paginate(stmt, params)
        return await self.binding_responses(list(rows)), pagination

    async def binding_responses(self, rows: list[ProgramRegulation]) -> list[ProgramRegulationResponse]:
        programs = await self.repo.by_ids([r.program_id for r in rows])
        regs = await self.regulations.codes([r.regulation_id for r in rows])
        out = []
        for b in rows:
            r = ProgramRegulationResponse.model_validate(b)
            p = programs.get(b.program_id)
            r.program_code, r.program_name = (p.code, p.name) if p else (None, None)
            r.total_terms = p.total_terms if p else None
            r.regulation_code, r.regulation_status = regs.get(b.regulation_id, (None, None))
            out.append(r)
        return out

    async def create_binding(self, body: ProgramRegulationCreate) -> ProgramRegulationResponse:
        program = await self._writable(body.program_id)
        reg = await self.regulations.get_regulation(body.regulation_id)
        if reg.college_id is not None and reg.college_id != program.college_id:
            raise APIError(
                422, ErrorCode.VALIDATION, "The regulation belongs to another college", {"field": "regulation_id"}
            )
        if await self.bindings.find(program.id, reg.id):
            raise APIError(409, ErrorCode.CONFLICT, f"{program.code} is already bound to {reg.code}")
        validate_override(reg.rules, body.rules_override)
        b = await self.bindings.create(
            institution_id=self.inst,
            program_id=program.id,
            regulation_id=reg.id,
            total_credits_required=body.total_credits_required,
            rules_override=body.rules_override,
            status=body.status.value,
            created_by=self.principal.id,
        )
        await self._audit("create", "program_regulation", b.id, None, snap(b, PR_KEYS), module="curriculum")
        return (await self.binding_responses([b]))[0]

    async def update_binding(self, pr_id: uuid.UUID, body: ProgramRegulationUpdate) -> ProgramRegulationResponse:
        b = await self.bindings.get_binding(pr_id)
        await self._writable(b.program_id)
        reg = await self.regulations.get_regulation(b.regulation_id)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if "status" in values and values["status"] is not None:
            values["status"] = str(values["status"])
        if ("total_credits_required" in values or "rules_override" in values) and reg.status in (
            "active",
            "superseded",
        ):
            ensure_structure_editable(reg)
        if "rules_override" in values:
            validate_override(reg.rules, values["rules_override"])
        old = snap(b, PR_KEYS)
        await self.bindings.update(b, expected_version=body.version, **values)
        await self._audit("update", "program_regulation", b.id, old, snap(b, PR_KEYS), module="curriculum")
        return (await self.binding_responses([b]))[0]
