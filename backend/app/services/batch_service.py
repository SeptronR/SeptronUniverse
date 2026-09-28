"""Batches and sections — Prompts/05 §05.6 ``batch_service``.

Business rules
1. One batch per (college, programme, admission year, entry type) (409); the programme-regulation must bind the
   same programme; ``code`` defaults to ``{year}-{programme code}`` (``-LE`` for lateral entry),
   ``expected_graduation_year`` to ``year + duration`` (lateral entry one year less), ``current_term_number`` to 1
   (3 for lateral entry into a semester programme). Sections ``A…N`` are created with the batch
   (``section_count`` × ``section_capacity`` or an explicit list). Writes are narrowed to the programme's department
   (``batches:manage`` registrar / ``hod`` @department).
2. ``PUT /batches/{id}/sections`` replaces the section set: existing names are kept (capacity updated), new names
   added, missing names removed — refused (409) while a removed section still has a class advisor.
3. Class advisor (``PUT /batches/{id}/sections/{sid}/advisor``): the person must be staff of the batch's college (a
   ``staff`` row or, until Phase 06, an active ``user_type = staff`` user); the ``class_advisor`` role is granted
   **@offering scoped to the section** through ``RbacService.assign`` (``scope_type='offering'``, the section id —
   Phase 09 offerings use the same scope type), the previous advisor's assignment is revoked;
   ``batch_sections.class_advisor_staff_id`` is set when a staff row exists.
4. ``current_term_number`` is maintained by Phase 07 promotion; the Phase 03 rollover hook ``on_rollover`` proposes
   the promotion of every active batch (next term or graduation) as a ``batch.promotion_proposed`` event and returns
   the number of batches — Phase 07 executes it once term records exist.
5. ``batch.created`` event; every write audited (module ``batches``).
"""

import uuid
from decimal import Decimal
from typing import Any

from app.core.academic_hooks import register_rollover_hook
from app.core.errors import APIError, ErrorCode
from app.models.academic import Batch, BatchSection
from app.repositories.batch_repository import BatchRepository
from app.repositories.department_repository import UnitHolderRepository
from app.repositories.program_repository import ProgramRegulationRepository, ProgramRepository
from app.repositories.regulation_repository import RegulationRepository
from app.schemas.academics import (
    AdvisorAssign,
    BatchCreate,
    BatchResponse,
    BatchSectionIn,
    BatchSectionOut,
    BatchSectionsReplace,
    BatchUpdate,
)
from app.services.academics.common import AcademicServiceBase, snap
from app.services.academics.context import (
    academic_visibility,
    check_department_writable,
    scope_filters,
    writable_department_ids,
)
from app.services.department_service import DepartmentService
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

BATCH_KEYS = (
    "code",
    "name",
    "college_id",
    "program_id",
    "program_regulation_id",
    "admission_year",
    "entry_type",
    "status",
)
TERMS_PER_YEAR = {"semester": 2, "trimester": 3, "year": 1}


class BatchService(AcademicServiceBase):
    audit_module = "batches"

    def __init__(self, db: Any, principal: Any, request: Any = None):
        super().__init__(db, principal, request)
        self.repo = BatchRepository(db, principal, self.inst)
        self.programs = ProgramRepository(db, principal, self.inst)
        self.bindings = ProgramRegulationRepository(db, principal, self.inst)
        self.regulations = RegulationRepository(db, principal, self.inst)
        self.holders = UnitHolderRepository(db)

    # ---- reads -----------------------------------------------------------------------------------------------------
    async def list_page(
        self,
        params: PageParams,
        scope: str | None,
        *,
        program_id: uuid.UUID | None,
        admission_year: int | None,
        status: str | None,
        q: str | None,
    ) -> tuple[list[BatchResponse], PaginationMeta, VisibilityMeta]:
        dept_ids, college_ids = scope_filters(self.principal, scope)
        stmt = self.repo.filtered(
            college_ids=college_ids,
            department_ids=dept_ids,
            program_id=program_id,
            admission_year=admission_year,
            status=status,
            q=q,
        )
        if not params.sort:
            params = params.model_copy(update={"sort": "-admission_year"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._responses(list(rows)), pagination, academic_visibility(self.principal)

    async def get(self, batch_id: uuid.UUID) -> BatchResponse:
        return (await self._responses([await self.repo.get_batch(batch_id)]))[0]

    async def _responses(self, rows: list[Batch]) -> list[BatchResponse]:
        sections = await self.repo.sections([b.id for b in rows])
        programs = await self.programs.by_ids([b.program_id for b in rows])
        bindings = {b.program_regulation_id for b in rows}
        reg_codes: dict[uuid.UUID, str] = {}
        for pr_id in bindings:
            pr = await self.bindings.get_binding(pr_id)
            reg_codes[pr_id] = (await self.regulations.codes([pr.regulation_id])).get(pr.regulation_id, ("", ""))[0]
        advisors = await self.holders.holders("class_advisor", "offering", [s.id for v in sections.values() for s in v])
        out = []
        for b in rows:
            r = BatchResponse.model_validate(b)
            r.program_code = programs[b.program_id].code if b.program_id in programs else None
            r.regulation_code = reg_codes.get(b.program_regulation_id)
            r.sections = []
            for s in sections.get(b.id, []):
                so = BatchSectionOut.model_validate(s)
                holder = advisors.get(s.id)
                so.class_advisor_user_id, so.class_advisor_name = (holder[0], holder[1]) if holder else (None, None)
                r.sections.append(so)
            out.append(r)
        return out

    # ---- rule 1 ----------------------------------------------------------------------------------------------------
    async def create(self, body: BatchCreate) -> BatchResponse:
        program = await self.programs.get_program(body.program_id)
        check_department_writable(
            await writable_department_ids(self.db, self.principal), program.department_id, create=True
        )
        pr = await self.bindings.get_binding(body.program_regulation_id)
        if pr.program_id != program.id:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "The programme-regulation belongs to another programme",
                {"field": "program_regulation_id"},
            )
        college_id = body.college_id or program.college_id
        if college_id != program.college_id:
            raise APIError(
                422, ErrorCode.VALIDATION, "The programme is run by another college", {"field": "college_id"}
            )
        entry = body.entry_type.value
        if await self.repo.find(self.inst, college_id, program.id, body.admission_year, entry):
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                f"A {entry} batch of {program.code} for {body.admission_year} already exists",
            )
        lateral = entry == "lateral"
        per_year = TERMS_PER_YEAR.get(program.term_pattern, 2)
        duration = int(Decimal(program.duration_years).to_integral_value())
        code = body.code or f"{body.admission_year}-{program.code}{'-LE' if lateral else ''}"
        batch = await self.repo.create(
            institution_id=self.inst,
            college_id=college_id,
            program_id=program.id,
            program_regulation_id=pr.id,
            admission_year=body.admission_year,
            entry_type=entry,
            code=code.upper(),
            name=body.name or f"{program.name} {body.admission_year}{' (lateral)' if lateral else ''}",
            expected_graduation_year=body.expected_graduation_year
            or body.admission_year + duration - (1 if lateral else 0),
            current_term_number=1 + (per_year if lateral else 0),
            status="active",
            created_by=self.principal.id,
        )
        specs = body.sections or [
            BatchSectionIn(name=chr(ord("A") + i), capacity=body.section_capacity) for i in range(body.section_count)
        ]
        names = [s.name.upper() for s in specs]
        if len(names) != len(set(names)):
            raise APIError(422, ErrorCode.VALIDATION, "Section names must be unique", {"field": "sections"})
        for s in specs:
            self.db.add(
                BatchSection(institution_id=self.inst, batch_id=batch.id, name=s.name.upper(), capacity=s.capacity)
            )
        await self.db.flush()
        await self._audit("create", "batch", batch.id, None, {**snap(batch, BATCH_KEYS), "sections": names})
        await self._emit(
            "batch.created",
            {"batch_id": str(batch.id), "code": batch.code, "program_id": str(program.id), "sections": names},
            "batch",
            batch.id,
        )
        return (await self._responses([batch]))[0]

    async def update(self, batch_id: uuid.UUID, body: BatchUpdate) -> BatchResponse:
        batch = await self._writable(batch_id)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if values.get("status") is not None:
            values["status"] = str(values["status"])
        old = snap(batch, BATCH_KEYS)
        await self.repo.update(batch, expected_version=body.version, **values)
        await self._audit("update", "batch", batch.id, old, snap(batch, BATCH_KEYS))
        return (await self._responses([batch]))[0]

    async def _writable(self, batch_id: uuid.UUID) -> Batch:
        batch = await self.repo.get_batch(batch_id)
        program = await self.programs.get_program(batch.program_id)
        check_department_writable(
            await writable_department_ids(self.db, self.principal), program.department_id, create=False
        )
        return batch

    # ---- rule 2 ----------------------------------------------------------------------------------------------------
    async def replace_sections(self, batch_id: uuid.UUID, body: BatchSectionsReplace) -> BatchResponse:
        batch = await self._writable(batch_id)
        names = [s.name.upper() for s in body.sections]
        if len(names) != len(set(names)):
            raise APIError(422, ErrorCode.VALIDATION, "Section names must be unique", {"field": "sections"})
        existing = {s.name.upper(): s for s in (await self.repo.sections([batch.id]))[batch.id]}
        removed = [s for n, s in existing.items() if n not in names]
        advised = await self.holders.holders("class_advisor", "offering", [s.id for s in removed])
        if advised:
            busy = ", ".join(s.name for s in removed if s.id in advised)
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Remove the class advisor of section(s) {busy} first")
        await self.repo.delete_sections([s.id for s in removed])
        for spec in body.sections:
            row = existing.get(spec.name.upper())
            if row is not None:
                row.capacity = spec.capacity
            else:
                self.db.add(
                    BatchSection(
                        institution_id=self.inst, batch_id=batch.id, name=spec.name.upper(), capacity=spec.capacity
                    )
                )
        await self.db.flush()
        await self._audit("replace_sections", "batch", batch.id, {"sections": sorted(existing)}, {"sections": names})
        return (await self._responses([batch]))[0]

    # ---- rule 3 ----------------------------------------------------------------------------------------------------
    async def assign_advisor(self, batch_id: uuid.UUID, section_id: uuid.UUID, body: AdvisorAssign) -> BatchResponse:
        batch = await self._writable(batch_id)
        section = await self.repo.section(batch.id, section_id)
        departments = DepartmentService(self.db, self.principal, self.request)
        user, staff_id = await departments._staff_of_college(body.staff_id or body.user_id, batch.college_id)  # type: ignore[arg-type]
        previous = await self.holders.holders("class_advisor", "offering", [section.id])
        await departments._grant_unit_role(user, "class_advisor", "offering", section.id)
        section.class_advisor_staff_id = staff_id
        await self.db.flush()
        await self._audit(
            "assign_advisor",
            "batch_section",
            section.id,
            {"class_advisor_user_id": str(previous[section.id][0]) if section.id in previous else None},
            {"class_advisor_user_id": str(user.id), "class_advisor_staff_id": str(staff_id) if staff_id else None},
        )
        return (await self._responses([batch]))[0]

    # ---- rule 4: rollover hook -------------------------------------------------------------------------------------
    async def propose_promotions(self) -> int:
        proposals = []
        for batch, total_terms in await self.repo.promotable(self.inst):
            program = await self.programs.get_program(batch.program_id)
            step = TERMS_PER_YEAR.get(program.term_pattern, 2)
            nxt = batch.current_term_number + step
            proposals.append(
                {
                    "batch_id": str(batch.id),
                    "code": batch.code,
                    "current_term_number": batch.current_term_number,
                    "proposed_term_number": min(nxt, total_terms),
                    "graduating": nxt > total_terms,
                }
            )
        if proposals:
            await self._emit(
                "batch.promotion_proposed",
                {"proposals": proposals, "count": len(proposals)},
                "institution",
                self.inst,
            )
        return len(proposals)


async def on_rollover(db: Any, principal: Any, previous_year: Any, new_year: Any) -> int:
    """Phase 03 ``ROLLOVER_HOOKS['batches']`` — propose (not execute) the promotion of every active batch."""
    return await BatchService(db, principal).propose_promotions()


register_rollover_hook("batches", on_rollover)
