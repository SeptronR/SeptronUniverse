"""Programme structure and elective baskets — Prompts/05 §05.6 ``curriculum_service``.

Business rules
1. ``replace_structure(program_regulation_id, request)`` replaces terms + curriculum courses (+ baskets when the
   request carries them) in **one transaction**. Blocking checks (422 ``VALIDATION``): term numbers are unique and in
   ``1..programs.total_terms``; ``min ≤ normal ≤ max`` credits; every course belongs to the programme-regulation's
   regulation and is ``approved|active``; a course appears once per term and only in a declared term; basket
   references resolve; basket courses ⊂ the regulation's courses; exit-point terms are listed in
   ``rules.exit_points``. Credit totals are **not** blocking on a draft: Σ mandatory credits + Σ basket
   ``credits_required`` ≠ ``total_credits_required`` is a *warning* on save and an *error* on approval.
   Frozen under an active regulation (409 ``RECORD_LOCKED``); optimistic lock on the programme-regulation version.
2. ``validate(program_regulation_id)`` → ``StructureValidationResponse`` (credit totals per term, issues);
   ``for_approval=True`` promotes the credit mismatch to an error (used by ``RegulationService.approve/activate``).
3. Baskets (``/elective-baskets``): code unique per programme-regulation (409), ``min_choose ≤ max_choose``, courses
   ⊂ the regulation's courses (422), frozen under an active regulation.
4. Writes are narrowed to the programme's department (``academics.context``); ``curriculum.replaced`` is emitted and
   every write is audited (module ``curriculum``).
"""

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from app.core.errors import APIError, ErrorCode
from app.models.academic import Program, ProgramRegulation, ProgramStructureTerm, Regulation
from app.models.curriculum import Course, CurriculumCourse, ElectiveBasket, ElectiveBasketCourse
from app.repositories.course_repository import CourseRepository
from app.repositories.curriculum_repository import BasketRepository, CurriculumRepository, StructureBundle
from app.repositories.program_repository import ProgramRegulationRepository, ProgramRepository
from app.repositories.regulation_repository import RegulationRepository
from app.schemas.curriculum import (
    BasketCourseOut,
    BasketCoursesReplace,
    BasketCreate,
    BasketIn,
    BasketOut,
    BasketUpdate,
    CurriculumCourseOut,
    StructureIssue,
    StructureReplaceRequest,
    StructureResponse,
    StructureTermOut,
    StructureValidationResponse,
)
from app.services.academics.common import AcademicServiceBase, ensure_structure_editable, snap
from app.services.academics.context import check_department_writable, writable_department_ids
from app.services.academics.rules import effective
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

TERM_WORD = {"semester": "Semester", "year": "Year", "trimester": "Trimester"}
LIVE_COURSE = ("approved", "active")
BASKET_KEYS = ("code", "name", "basket_type", "term_number", "min_choose", "max_choose", "credits_required")


def _bad(message: str, field: str, **details: Any) -> APIError:
    return APIError(422, ErrorCode.VALIDATION, message, {"field": field, **details})


def ltpc(c: Course) -> str:
    return f"{c.lecture_hours}-{c.tutorial_hours}-{c.practical_hours}-{c.credits.normalize():f}"


class CurriculumService(AcademicServiceBase):
    audit_module = "curriculum"

    def __init__(self, db: Any, principal: Any, request: Any = None):
        super().__init__(db, principal, request)
        self.bindings = ProgramRegulationRepository(db, principal, self.inst)
        self.programs = ProgramRepository(db, principal, self.inst)
        self.regulations = RegulationRepository(db, principal, self.inst)
        self.courses = CourseRepository(db, principal, self.inst)
        self.repo = CurriculumRepository(db, self.inst)
        self.baskets = BasketRepository(db, principal, self.inst)

    async def _context(self, pr_id: uuid.UUID, *, write: bool = False) -> tuple[ProgramRegulation, Program, Regulation]:
        b = await self.bindings.get_binding(pr_id, for_update=write)
        program = await self.programs.get_program(b.program_id)
        reg = await self.regulations.get_regulation(b.regulation_id)
        if write:
            check_department_writable(
                await writable_department_ids(self.db, self.principal), program.department_id, create=False
            )
            ensure_structure_editable(reg)
        return b, program, reg

    # ---- reads -----------------------------------------------------------------------------------------------------
    async def get_structure(self, pr_id: uuid.UUID) -> StructureResponse:
        from app.services.academics.enrolled import ensure_enrolled_program_regulation

        await ensure_enrolled_program_regulation(self.db, self.principal, pr_id)  # students / parents (Phase 07)
        b, program, reg = await self._context(pr_id)
        return await self._structure(b, program, reg, await self.repo.load(b.id))

    async def _structure(
        self, b: ProgramRegulation, program: Program, reg: Regulation, bundle: StructureBundle
    ) -> StructureResponse:
        course_ids = [c.course_id for c in bundle.courses] + [
            bc.course_id for rows in bundle.basket_courses.values() for bc in rows
        ]
        courses = await self.baskets.course_briefs(course_ids)
        basket_codes = {bk.id: bk.code for bk in bundle.baskets}
        rules = effective(reg.rules, b.rules_override)
        return StructureResponse(
            program_regulation_id=b.id,
            program_id=program.id,
            regulation_id=reg.id,
            regulation_status=reg.status,
            total_terms=program.total_terms,
            term_pattern=program.term_pattern,
            total_credits_required=b.total_credits_required,
            version=b.version,
            locked=reg.status in ("active", "superseded"),
            terms=[StructureTermOut.model_validate(t) for t in bundle.terms],
            courses=[self._cc_out(cc, courses.get(cc.course_id), basket_codes) for cc in bundle.courses],
            baskets=[self._basket_out(bk, bundle.basket_courses.get(bk.id, []), courses) for bk in bundle.baskets],
            exit_points=rules.get("exit_points", []),
        )

    @staticmethod
    def _cc_out(cc: CurriculumCourse, c: Course | None, basket_codes: dict[uuid.UUID, str]) -> CurriculumCourseOut:
        out = CurriculumCourseOut.model_validate(cc)
        out.basket_code = basket_codes.get(cc.elective_basket_id) if cc.elective_basket_id else None
        if c is not None:
            out.course_code, out.course_title, out.course_type = c.code, c.title, c.course_type
            out.credits, out.ltpc = c.credits, ltpc(c)
        return out

    @staticmethod
    def _basket_out(
        bk: ElectiveBasket, rows: list[ElectiveBasketCourse], courses: dict[uuid.UUID, Course]
    ) -> BasketOut:
        out = BasketOut.model_validate(bk)
        out.courses = [
            BasketCourseOut(
                course_id=r.course_id,
                offering_department_id=r.offering_department_id,
                code=courses[r.course_id].code if r.course_id in courses else None,
                title=courses[r.course_id].title if r.course_id in courses else None,
                credits=courses[r.course_id].credits if r.course_id in courses else None,
            )
            for r in rows
        ]
        return out

    # ---- rule 1 ----------------------------------------------------------------------------------------------------
    async def replace_structure(self, pr_id: uuid.UUID, req: StructureReplaceRequest) -> StructureResponse:
        b, program, reg = await self._context(pr_id, write=True)
        if req.version is not None and req.version != b.version:
            raise APIError(
                409,
                ErrorCode.STALE_VERSION,
                "The structure was modified by someone else",
                {"current_version": b.version},
            )
        rules = effective(reg.rules, b.rules_override)
        exit_terms = {int(e["after_term"]): e for e in rules.get("exit_points", [])}

        # terms
        numbers = [t.term_number for t in req.terms]
        if len(numbers) != len(set(numbers)):
            raise _bad("Term numbers must be unique", "terms")
        for t in req.terms:
            if not 1 <= t.term_number <= program.total_terms:
                raise _bad(
                    f"Term {t.term_number} is outside 1..{program.total_terms}", "terms", term_number=t.term_number
                )
            if not t.min_credits <= t.normal_credits <= t.max_credits:
                raise _bad(
                    f"Term {t.term_number}: credits must satisfy min ≤ normal ≤ max", "terms", term_number=t.term_number
                )
            if t.is_exit_point and t.term_number not in exit_terms:
                raise _bad(
                    f"Term {t.term_number} is marked as an exit point but rules.exit_points has no exit after it",
                    "terms",
                    term_number=t.term_number,
                )

        reg_courses = {c.id: c for c in await self.courses.for_regulation(reg.id)}
        declared = set(numbers)

        # baskets (request-local codes)
        basket_specs: dict[str, BasketIn] = {}
        if req.baskets is not None:
            for bk in req.baskets:
                code = bk.code.upper()
                if code in basket_specs:
                    raise _bad(f"Basket code {bk.code} appears twice", "baskets")
                self._check_basket_courses(bk.course_ids, reg_courses)
                if bk.term_number is not None and bk.term_number not in declared:
                    raise _bad(f"Basket {bk.code}: term {bk.term_number} is not declared", "baskets")
                basket_specs[code] = bk
            existing_codes: dict[str, uuid.UUID] = {}
        else:
            existing_codes = {bk.code.upper(): bk.id for bk in await self.repo.baskets(b.id)}

        # curriculum courses
        seen: set[tuple[int, uuid.UUID]] = set()
        for cc in req.courses:
            course = reg_courses.get(cc.course_id)
            if course is None:
                raise _bad("A course does not belong to this regulation", "courses", course_id=str(cc.course_id))
            if course.status not in LIVE_COURSE:
                raise _bad(
                    f"{course.code} is {course.status}: only approved/active courses can be placed",
                    "courses",
                    course_id=str(course.id),
                )
            if cc.term_number not in declared:
                raise _bad(f"{course.code}: term {cc.term_number} is not declared", "courses", course_id=str(course.id))
            key = (cc.term_number, cc.course_id)
            if key in seen:
                raise _bad(f"{course.code} is listed twice in term {cc.term_number}", "courses")
            seen.add(key)
            if cc.basket_code and cc.basket_code.upper() not in (basket_specs or existing_codes):
                raise _bad(f"{course.code}: unknown basket {cc.basket_code}", "courses")

        # write
        old = {"terms": len((await self.repo.load(b.id)).terms)}
        await self.repo.replace_terms_and_courses(b.id)
        basket_ids = dict(existing_codes)
        if req.baskets is not None:
            await self.repo.delete_baskets(b.id)
            for code, bk in basket_specs.items():
                row = ElectiveBasket(
                    institution_id=self.inst,
                    program_regulation_id=b.id,
                    code=code,
                    name=bk.name,
                    basket_type=bk.basket_type.value,
                    term_number=bk.term_number,
                    min_choose=bk.min_choose,
                    max_choose=bk.max_choose,
                    credits_required=bk.credits_required,
                    allocation_mode=bk.allocation_mode.value,
                    created_by=self.principal.id,
                )
                self.db.add(row)
                await self.db.flush()
                basket_ids[code] = row.id
                for cid in dict.fromkeys(bk.course_ids):
                    self.db.add(
                        ElectiveBasketCourse(
                            institution_id=self.inst,
                            basket_id=row.id,
                            course_id=cid,
                            offering_department_id=reg_courses[cid].department_id,
                        )
                    )
        word = TERM_WORD.get(program.term_pattern, "Term")
        for t in req.terms:
            award = t.exit_award or (exit_terms[t.term_number]["award"] if t.is_exit_point else None)
            self.db.add(
                ProgramStructureTerm(
                    institution_id=self.inst,
                    program_regulation_id=b.id,
                    term_number=t.term_number,
                    name=t.name or f"{word} {t.term_number}",
                    min_credits=t.min_credits,
                    normal_credits=t.normal_credits,
                    max_credits=t.max_credits,
                    is_exit_point=t.is_exit_point,
                    exit_award=award,
                )
            )
        for cc in req.courses:
            self.db.add(
                CurriculumCourse(
                    institution_id=self.inst,
                    program_regulation_id=b.id,
                    term_number=cc.term_number,
                    course_id=cc.course_id,
                    elective_basket_id=basket_ids.get(cc.basket_code.upper()) if cc.basket_code else None,
                    is_mandatory=cc.is_mandatory and not cc.basket_code,
                    credit_bucket=cc.credit_bucket,
                    sequence=cc.sequence,
                )
            )
        b.version += 1  # the structure is part of the binding's state (optimistic lock of the editor)
        await self.db.flush()
        new = {"terms": len(req.terms), "courses": len(req.courses), "baskets": len(basket_ids)}
        await self._audit("replace_structure", "program_regulation", b.id, old, new)
        await self._emit(
            "curriculum.replaced",
            {"program_regulation_id": str(b.id), "program_id": str(program.id), "regulation_id": str(reg.id), **new},
            "program_regulation",
            b.id,
        )
        return await self._structure(b, program, reg, await self.repo.load(b.id))

    @staticmethod
    def _check_basket_courses(course_ids: list[uuid.UUID], reg_courses: dict[uuid.UUID, Course]) -> None:
        foreign = [str(c) for c in course_ids if c not in reg_courses]
        if foreign:
            raise _bad(
                "Basket courses must belong to the programme-regulation's regulation", "course_ids", course_ids=foreign
            )

    # ---- rule 2 ----------------------------------------------------------------------------------------------------
    async def validate(self, pr_id: uuid.UUID, *, for_approval: bool = False) -> StructureValidationResponse:
        b, program, reg = await self._context(pr_id)
        bundle = await self.repo.load(b.id)
        rules = effective(reg.rules, b.rules_override)
        return await self._validate(b, program, reg, bundle, rules, for_approval)

    async def _validate(
        self,
        b: ProgramRegulation,
        program: Program,
        reg: Regulation,
        bundle: StructureBundle,
        rules: dict[str, Any],
        for_approval: bool,
    ) -> StructureValidationResponse:
        issues: list[StructureIssue] = []
        ids = [c.course_id for c in bundle.courses] + [x.course_id for v in bundle.basket_courses.values() for x in v]
        courses = await self.baskets.course_briefs(ids)
        per_term: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
        mandatory = Decimal("0")
        for cc in bundle.courses:
            c = courses.get(cc.course_id)
            if c is None:
                continue
            if c.regulation_id != reg.id:
                issues.append(
                    StructureIssue(
                        code="FOREIGN_COURSE",
                        severity="error",
                        message=f"{c.code} belongs to another regulation",
                        course_id=c.id,
                    )
                )
            if c.status not in LIVE_COURSE:
                issues.append(
                    StructureIssue(
                        code="COURSE_NOT_APPROVED",
                        severity="error",
                        message=f"{c.code} is {c.status}",
                        term_number=cc.term_number,
                        course_id=c.id,
                    )
                )
            if cc.is_mandatory and cc.elective_basket_id is None and c.is_credit_bearing:
                per_term[cc.term_number] += c.credits
                mandatory += c.credits
        basket_total = Decimal("0")
        for bk in bundle.baskets:
            members = bundle.basket_courses.get(bk.id, [])
            if len(members) < bk.min_choose:
                issues.append(
                    StructureIssue(
                        code="BASKET_TOO_SMALL",
                        severity="error",
                        message=f"Basket {bk.code} offers {len(members)} course(s) but students choose at least {bk.min_choose}",
                        term_number=bk.term_number,
                    )
                )
            if bk.credits_required is None:
                issues.append(
                    StructureIssue(
                        code="BASKET_CREDITS_MISSING",
                        severity="warning",
                        message=f"Basket {bk.code} has no credits_required",
                        term_number=bk.term_number,
                    )
                )
                continue
            basket_total += bk.credits_required
            if bk.term_number is not None:
                per_term[bk.term_number] += bk.credits_required
        declared = {t.term_number for t in bundle.terms}
        for t in bundle.terms:
            load = per_term.get(t.term_number, Decimal("0"))
            if load > t.max_credits:
                issues.append(
                    StructureIssue(
                        code="TERM_OVER_MAX",
                        severity="warning",
                        message=f"Term {t.term_number}: {load:g} credits exceed max {t.max_credits:g}",
                        term_number=t.term_number,
                    )
                )
            elif load < t.min_credits:
                issues.append(
                    StructureIssue(
                        code="TERM_UNDER_MIN",
                        severity="warning",
                        message=f"Term {t.term_number}: {load:g} credits are below min {t.min_credits:g}",
                        term_number=t.term_number,
                    )
                )
        missing = [n for n in range(1, program.total_terms + 1) if n not in declared]
        if missing:
            issues.append(
                StructureIssue(
                    code="TERMS_MISSING",
                    severity="error" if for_approval else "warning",
                    message=f"Terms without a structure row: {', '.join(map(str, missing))}",
                )
            )
        exit_terms = {int(e["after_term"]) for e in rules.get("exit_points", [])}
        for t in bundle.terms:
            if t.is_exit_point and t.term_number not in exit_terms:
                issues.append(
                    StructureIssue(
                        code="EXIT_POINT_MISALIGNED",
                        severity="error",
                        message=f"Term {t.term_number} is an exit point that rules.exit_points does not list",
                        term_number=t.term_number,
                    )
                )
        total = mandatory + basket_total
        if total != b.total_credits_required:
            issues.append(
                StructureIssue(
                    code="CREDIT_TOTAL_MISMATCH",
                    severity="error" if for_approval else "warning",
                    message=f"Σ mandatory ({mandatory:g}) + Σ baskets ({basket_total:g}) = {total:g}, "
                    f"required {b.total_credits_required:g}",
                )
            )
        return StructureValidationResponse(
            program_regulation_id=b.id,
            credit_totals_by_term={n: per_term.get(n, Decimal("0")) for n in sorted(declared | set(per_term))},
            mandatory_credits=mandatory,
            basket_credits=basket_total,
            total=total,
            required=b.total_credits_required,
            issues=issues,
            valid=not any(i.severity == "error" for i in issues),
        )

    async def approval_issues(self, reg: Regulation) -> list[dict[str, Any]]:
        """Errors of every structure bound to ``reg`` (``for_approval``) — the 409 detail of approve/activate."""
        out: list[dict[str, Any]] = []
        for b in await self.bindings.for_regulation(reg.id):
            v = await self.validate(b.id, for_approval=True)
            program = await self.programs.get_program(b.program_id)
            out.extend(
                {"program_regulation_id": str(b.id), "program": program.code, **i.model_dump(mode="json")}
                for i in v.issues
                if i.severity == "error"
            )
        return out

    # ---- rule 3: baskets --------------------------------------------------------------------------------------------
    async def list_baskets(
        self, params: PageParams, pr_id: uuid.UUID | None, basket_type: str | None
    ) -> tuple[list[BasketOut], PaginationMeta]:
        stmt = self.baskets._base()
        if pr_id:
            stmt = stmt.where(ElectiveBasket.program_regulation_id == pr_id)
        if basket_type:
            stmt = stmt.where(ElectiveBasket.basket_type == basket_type)
        if not params.sort:
            params = params.model_copy(update={"sort": "code"})
        rows, pagination = await self.baskets.paginate(stmt, params)
        return await self._basket_outs(list(rows)), pagination

    async def _basket_outs(self, rows: list[ElectiveBasket]) -> list[BasketOut]:
        members = await self.repo.basket_courses([r.id for r in rows])
        courses = await self.baskets.course_briefs([m.course_id for v in members.values() for m in v])
        return [self._basket_out(r, members.get(r.id, []), courses) for r in rows]

    async def create_basket(self, body: BasketCreate) -> BasketOut:
        b, _, reg = await self._context(body.program_regulation_id, write=True)
        if await self.baskets.by_code(b.id, body.code):
            raise APIError(409, ErrorCode.CONFLICT, f"Basket {body.code!r} exists", {"field": "code"})
        reg_courses = {c.id: c for c in await self.courses.for_regulation(reg.id)}
        self._check_basket_courses(body.course_ids, reg_courses)
        bk = await self.baskets.create(
            institution_id=self.inst,
            program_regulation_id=b.id,
            code=body.code.upper(),
            name=body.name,
            basket_type=body.basket_type.value,
            term_number=body.term_number,
            min_choose=body.min_choose,
            max_choose=body.max_choose,
            credits_required=body.credits_required,
            allocation_mode=body.allocation_mode.value,
            created_by=self.principal.id,
        )
        await self.repo.replace_basket_courses(bk.id, self._members(bk.id, body.course_ids, reg_courses))
        await self._audit("create", "elective_basket", bk.id, None, snap(bk, BASKET_KEYS))
        return (await self._basket_outs([bk]))[0]

    async def update_basket(self, basket_id: uuid.UUID, body: BasketUpdate) -> BasketOut:
        bk = await self.baskets.get_basket(basket_id)
        await self._context(bk.program_regulation_id, write=True)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        for k in ("basket_type", "allocation_mode"):
            if values.get(k) is not None:
                values[k] = str(values[k])
        lo, hi = values.get("min_choose", bk.min_choose), values.get("max_choose", bk.max_choose)
        if lo > hi:
            raise _bad("min_choose must be ≤ max_choose", "min_choose")
        old = snap(bk, BASKET_KEYS)
        await self.baskets.update(bk, expected_version=body.version, **values)
        await self._audit("update", "elective_basket", bk.id, old, snap(bk, BASKET_KEYS))
        return (await self._basket_outs([bk]))[0]

    async def delete_basket(self, basket_id: uuid.UUID) -> None:
        bk = await self.baskets.get_basket(basket_id)
        await self._context(bk.program_regulation_id, write=True)
        old = snap(bk, BASKET_KEYS)
        await self.baskets.soft_delete(bk, self.principal.id)
        await self._audit("delete", "elective_basket", bk.id, old, None)

    async def replace_basket_courses(self, basket_id: uuid.UUID, body: BasketCoursesReplace) -> BasketOut:
        bk = await self.baskets.get_basket(basket_id)
        _, _, reg = await self._context(bk.program_regulation_id, write=True)
        reg_courses = {c.id: c for c in await self.courses.for_regulation(reg.id)}
        ids = [c.course_id for c in body.courses]
        self._check_basket_courses(ids, reg_courses)
        depts = {c.course_id: c.offering_department_id for c in body.courses}
        rows = self._members(bk.id, ids, reg_courses)
        for r in rows:
            r.offering_department_id = depts.get(r.course_id) or r.offering_department_id
        old = [str(m.course_id) for m in (await self.repo.basket_courses([bk.id]))[bk.id]]
        await self.repo.replace_basket_courses(bk.id, rows)
        await self._audit(
            "replace_courses", "elective_basket", bk.id, {"courses": old}, {"courses": [str(i) for i in ids]}
        )
        return (await self._basket_outs([bk]))[0]

    def _members(
        self, basket_id: uuid.UUID, course_ids: list[uuid.UUID], reg_courses: dict[uuid.UUID, Course]
    ) -> list[ElectiveBasketCourse]:
        return [
            ElectiveBasketCourse(
                institution_id=self.inst,
                basket_id=basket_id,
                course_id=cid,
                offering_department_id=reg_courses[cid].department_id,
            )
            for cid in dict.fromkeys(course_ids)
        ]
