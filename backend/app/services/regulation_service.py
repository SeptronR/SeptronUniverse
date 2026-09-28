"""Regulations — Prompts/05 §05.6 ``regulation_service``.

Business rules
1. **Create** a ``draft`` with ``rules`` validated against ``RegulationRules`` — missing keys are pre-filled from the
   institution's pack (``pack.default_regulation_rules`` translated by ``pack_rules``), then the model defaults;
   ``code`` unique per (institution, college) (409); the grading scale defaults to the institution's default scale;
   the pack's assessment schemes are copied into the new regulation (Phase 03 deferred them here). Institution-wide
   regulations need an institution scope, college regulations the college in scope (``college_admin`` @college).
2. **Approve** (``draft → approved``): every programme structure bound to the regulation must validate *for
   approval* (credit totals, exit points, course statuses) — otherwise 409 ``RULE_VIOLATION`` listing the issues.
   With ``academics.bos_approval_workflow`` on, the call **submits** the regulation to the ``regulation.approval``
   workflow (Phase 04 engine; dean @faculty of the bound programmes → academic-council secretary) and the
   ``approved`` hook calls ``mark_approved``; without it the caller needs ``regulations:approve`` and the regulation
   is approved directly (``approval_resolution_id`` optional). From approval on the **rules are locked**; courses and
   structure stay editable until activation.
3. **Activate** (``approved → active``, ``regulations:publish``): re-validates, sets ``locked_at``, activates the
   regulation's ``approved`` courses and ``draft`` programme-regulations; the clone source (if active) becomes
   ``superseded`` with ``superseded_by_id`` → this regulation. Under ``active`` every mutating endpoint of courses,
   structures, baskets and schemes answers 409 ``RECORD_LOCKED``.
4. **Clone** (``regulations:clone``): deep copy — regulation (``draft``), assessment schemes + components, courses
   (same codes, new ids; ``active`` → ``approved``), prerequisites, regulation-scoped grading scales, programme
   bindings with their structure terms, curriculum courses and baskets. The ``clone`` audit row records
   ``source_id`` (the predecessor used by ``diff`` until the clone supersedes its source).
5. **Diff** vs the predecessor: courses added / removed / changed (by code) and rules keys changed.
6. ``rules_effective`` = rules ⊕ ``rules_override`` through ``RulesResolver`` (``academics.rules``).
Events ``regulation.approved|activated|superseded``; every write audited (module ``regulations``).
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, text

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.packs import get_pack
from app.core.workflow import engine as workflow_engine
from app.models.academic import GradingScale, ProgramRegulation, ProgramStructureTerm, Regulation
from app.models.curriculum import (
    AssessmentComponent,
    AssessmentScheme,
    Course,
    CoursePrerequisite,
    CurriculumCourse,
    ElectiveBasket,
    ElectiveBasketCourse,
)
from app.models.platform import WorkflowInstance
from app.repositories.curriculum_repository import CurriculumRepository
from app.repositories.grading_repository import GradingRepository
from app.repositories.institution_repository import InstitutionRepository
from app.repositories.program_repository import ProgramRegulationRepository, ProgramRepository
from app.repositories.regulation_repository import RegulationRepository
from app.schemas.academics import (
    RegulationApproveRequest,
    RegulationApproveResponse,
    RegulationCloneRequest,
    RegulationCreate,
    RegulationResponse,
    RegulationRules,
    RegulationUpdate,
    RulesEffectiveResponse,
    merge_rules,
    pack_rules,
)
from app.schemas.curriculum import CourseBrief, CourseChange, RegulationDiffResponse
from app.services.academics.common import AcademicServiceBase, ensure_rules_editable, snap
from app.services.academics.context import (
    academic_visibility,
    check_regulation_writable,
    scope_filters,
    writable_college_ids_for_units,
)
from app.services.academics.rules import RulesResolver
from app.services.curriculum_service import CurriculumService
from app.services.grading_service import GradingService
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

REG_KEYS = (
    "code",
    "name",
    "college_id",
    "effective_from_admission_year",
    "grading_scale_id",
    "status",
    "approved_by",
    "approval_resolution_id",
    "locked_at",
    "superseded_by_id",
)
DIFF_FIELDS = (
    "title",
    "course_type",
    "lecture_hours",
    "tutorial_hours",
    "practical_hours",
    "credits",
    "is_credit_bearing",
    "department_id",
    "syllabus",
)
WORKFLOW_KEY = "regulation.approval"


def validated_rules(rules: dict[str, Any]) -> dict[str, Any]:
    try:
        return RegulationRules.model_validate(rules).model_dump(mode="json")
    except ValidationError as exc:
        raise APIError(
            422,
            ErrorCode.VALIDATION,
            "Regulation rules are not valid",
            {"field": "rules", "errors": exc.errors(include_url=False, include_context=False)},
        ) from exc


class RegulationService(AcademicServiceBase):
    audit_module = "regulations"

    def __init__(self, db: Any, principal: Any, request: Any = None):
        super().__init__(db, principal, request)
        self.repo = RegulationRepository(db, principal, self.inst)
        self.bindings = ProgramRegulationRepository(db, principal, self.inst)
        self.programs = ProgramRepository(db, principal, self.inst)
        self.scales = GradingRepository(db, principal, self.inst)

    # ---- reads -----------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, status: str | None, q: str | None
    ) -> tuple[list[RegulationResponse], PaginationMeta, VisibilityMeta]:
        _, college_ids = scope_filters(self.principal, scope)
        stmt = self.repo.filtered(college_ids=college_ids, status=status, q=q)
        if not params.sort:
            params = params.model_copy(update={"sort": "-effective_from_admission_year"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._responses(list(rows)), pagination, academic_visibility(self.principal)

    async def get(self, regulation_id: uuid.UUID) -> RegulationResponse:
        reg = await self.repo.get_regulation(regulation_id)
        out = (await self._responses([reg]))[0]
        prev = await self.repo.predecessor(reg)
        out.predecessor_id = prev.id if prev else None
        return out

    async def _responses(self, rows: list[Regulation]) -> list[RegulationResponse]:
        courses, programs = await self.repo.counts([r.id for r in rows])
        instances = await self._instances([r.id for r in rows])
        out = []
        for r in rows:
            item = RegulationResponse.model_validate(r)
            item.course_count = courses.get(r.id, 0)
            item.program_count = programs.get(r.id, 0)
            item.workflow_instance_id = instances.get(r.id)
            item.rules_locked = r.status != "draft"
            item.structure_locked = r.status in ("active", "superseded")
            out.append(item)
        return out

    async def _instances(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        if not ids:
            return {}
        rows = (
            await self.db.execute(
                select(WorkflowInstance.entity_id, WorkflowInstance.id)
                .where(WorkflowInstance.entity_type == "regulation", WorkflowInstance.entity_id.in_(ids))
                .order_by(WorkflowInstance.started_at)
            )
        ).all()
        return {r[0]: r[1] for r in rows}

    # ---- rule 1 ----------------------------------------------------------------------------------------------------
    async def create(self, body: RegulationCreate) -> RegulationResponse:
        check_regulation_writable(self.principal, body.college_id, create=True)
        if await self.repo.by_code(self.inst, body.college_id, body.code):
            raise APIError(409, ErrorCode.CONFLICT, f"Regulation {body.code.upper()} already exists", {"field": "code"})
        inst = await InstitutionRepository(self.db).get(self.inst)
        base = pack_rules(get_pack(getattr(inst, "regulatory_pack", None)).default_regulation_rules)
        rules = validated_rules(merge_rules(base, body.rules))
        scale_id = body.grading_scale_id
        if scale_id is not None:
            await self.scales.get_scale(scale_id)
        else:
            default = await self.scales.default_scale(self.inst)
            scale_id = default.id if default else None
        reg = await self.repo.create(
            institution_id=self.inst,
            college_id=body.college_id,
            code=body.code.upper(),
            name=body.name,
            effective_from_admission_year=body.effective_from_admission_year,
            grading_scale_id=scale_id,
            rules=rules,
            status="draft",
            created_by=self.principal.id,
        )
        schemes = await GradingService(self.db, self.principal, self.request).seed_pack_schemes(reg)
        await self._audit("create", "regulation", reg.id, None, {**snap(reg, REG_KEYS), "pack_schemes": schemes})
        return (await self._responses([reg]))[0]

    async def update(self, regulation_id: uuid.UUID, body: RegulationUpdate) -> RegulationResponse:
        reg = await self.repo.get_regulation(regulation_id, for_update=True)
        check_regulation_writable(self.principal, reg.college_id)
        values = body.model_dump(exclude_unset=True, exclude={"version", "rules"})
        if body.rules is not None or "grading_scale_id" in values or reg.status in ("active", "superseded"):
            ensure_rules_editable(reg)
        if values.get("grading_scale_id"):
            await self.scales.get_scale(values["grading_scale_id"])
        old = {**snap(reg, REG_KEYS), "rules": reg.rules}
        if body.rules is not None:
            values["rules"] = validated_rules(merge_rules(reg.rules, body.rules))
        await self.repo.update(reg, expected_version=body.version, **values)
        await self._audit("update", "regulation", reg.id, old, {**snap(reg, REG_KEYS), "rules": reg.rules})
        return (await self._responses([reg]))[0]

    # ---- rule 2 ----------------------------------------------------------------------------------------------------
    async def approve(self, regulation_id: uuid.UUID, body: RegulationApproveRequest) -> RegulationApproveResponse:
        reg = await self.repo.get_regulation(regulation_id, for_update=True)
        if reg.status != "draft":
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Regulation {reg.code} is already {reg.status}")
        issues = await CurriculumService(self.db, self.principal, self.request).approval_issues(reg)
        if issues:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"The programme structures of {reg.code} have {len(issues)} issue(s)",
                {"issues": issues},
            )
        if await is_enabled(self.inst, "academics.bos_approval_workflow"):
            if not (self.principal.has("regulations", "update") or self.principal.has("regulations", "approve")):
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires regulations:update to submit for approval")
            check_regulation_writable(self.principal, reg.college_id)
            instance = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WORKFLOW_KEY,
                entity_type="regulation",
                entity_id=reg.id,
                started_by=self.principal.id,
                context=await self._workflow_context(reg, body),
                title=f"Regulation {reg.code} — {reg.name}",
            )
            await self._audit("submit", "regulation", reg.id, None, {"workflow_instance_id": str(instance.id)})
            return RegulationApproveResponse(
                regulation=(await self._responses([reg]))[0], workflow_instance_id=instance.id, pending_workflow=True
            )
        if not self.principal.has("regulations", "approve"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires regulations:approve")
        await self._check_approver_scope(reg)
        await self.mark_approved(reg, self.principal.id, body.resolution_id)
        return RegulationApproveResponse(regulation=(await self._responses([reg]))[0])

    async def _check_approver_scope(self, reg: Regulation) -> None:
        if reg.college_id is None:
            return
        colleges = await writable_college_ids_for_units(self.db, self.principal)
        if colleges is not None and reg.college_id not in colleges:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "The regulation belongs to a college outside your scope")

    async def _workflow_context(self, reg: Regulation, body: RegulationApproveRequest) -> dict[str, Any]:
        """Approver resolution: the faculty/department of the bound programmes (dean @faculty), the college and the
        institution's academic council (committee secretary) when one is constituted."""
        ctx: dict[str, Any] = {"regulation_id": str(reg.id), "regulation_code": reg.code}
        if reg.college_id:
            ctx["college_id"] = str(reg.college_id)
        for b in await self.bindings.for_regulation(reg.id):
            p = await self.programs.get_program(b.program_id)
            if p.faculty_id:
                ctx.setdefault("faculty_id", str(p.faculty_id))
            ctx.setdefault("department_id", str(p.department_id))
            ctx.setdefault("college_id", str(p.college_id))
        council = (
            await self.db.execute(
                text(
                    "SELECT id FROM committees WHERE institution_id = :i AND committee_type = 'academic_council' "
                    "AND is_active ORDER BY created_at LIMIT 1"
                ),
                {"i": self.inst},
            )
        ).first()
        if council is not None:
            ctx["committee_id"] = str(council[0])
        if body.resolution_id:
            ctx["resolution_id"] = str(body.resolution_id)
        return ctx

    async def mark_approved(
        self, reg: Regulation, approved_by: uuid.UUID | None, resolution_id: uuid.UUID | None = None
    ) -> None:
        """``draft → approved`` (direct approval, or the ``regulation.approval`` workflow's ``approved`` hook)."""
        old = snap(reg, REG_KEYS)
        reg.status = "approved"
        reg.approved_by = approved_by
        reg.approved_at = datetime.now(UTC)
        reg.approval_resolution_id = resolution_id
        await self.db.flush()
        await self._audit("approve", "regulation", reg.id, old, snap(reg, REG_KEYS))
        await self._emit(
            "regulation.approved",
            {"regulation_id": str(reg.id), "code": reg.code, "approved_by": str(approved_by) if approved_by else None},
            "regulation",
            reg.id,
        )

    # ---- rule 3 ----------------------------------------------------------------------------------------------------
    async def activate(self, regulation_id: uuid.UUID) -> RegulationResponse:
        reg = await self.repo.get_regulation(regulation_id, for_update=True)
        check_regulation_writable(self.principal, reg.college_id)
        if reg.status != "approved":
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"Only an approved regulation can be activated ({reg.code} is {reg.status})",
            )
        issues = await CurriculumService(self.db, self.principal, self.request).approval_issues(reg)
        if issues:
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"{reg.code} has {len(issues)} structure issue(s)", {"issues": issues}
            )
        old = snap(reg, REG_KEYS)
        now = datetime.now(UTC)
        reg.status, reg.locked_at = "active", now
        courses = (
            (
                await self.db.execute(
                    select(Course).where(
                        Course.regulation_id == reg.id, Course.status == "approved", Course.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        for c in courses:
            c.status = "active"
        for b in await self.bindings.for_regulation(reg.id):
            if b.status == "draft":
                b.status = "active"
        await self.db.flush()
        await self._audit(
            "activate", "regulation", reg.id, old, {**snap(reg, REG_KEYS), "courses_activated": len(courses)}
        )
        await self._emit(
            "regulation.activated",
            {"regulation_id": str(reg.id), "code": reg.code, "courses_activated": len(courses)},
            "regulation",
            reg.id,
        )
        source_id = await self.repo.clone_source(reg)
        if source_id is not None:
            source = await self.repo.get_regulation(source_id, for_update=True)
            if source.status == "active":
                prev = snap(source, REG_KEYS)
                source.status, source.superseded_by_id = "superseded", reg.id
                await self.db.flush()
                await self._audit("supersede", "regulation", source.id, prev, snap(source, REG_KEYS))
                await self._emit(
                    "regulation.superseded",
                    {"regulation_id": str(source.id), "code": source.code, "superseded_by_id": str(reg.id)},
                    "regulation",
                    source.id,
                )
        return (await self._responses([reg]))[0]

    # ---- rule 4 ----------------------------------------------------------------------------------------------------
    async def clone(self, regulation_id: uuid.UUID, body: RegulationCloneRequest) -> RegulationResponse:
        src = await self.repo.get_regulation(regulation_id)
        check_regulation_writable(self.principal, src.college_id, create=True)
        if await self.repo.by_code(self.inst, src.college_id, body.code):
            raise APIError(409, ErrorCode.CONFLICT, f"Regulation {body.code.upper()} already exists", {"field": "code"})
        new = await self.repo.create(
            institution_id=self.inst,
            college_id=src.college_id,
            code=body.code.upper(),
            name=body.name,
            effective_from_admission_year=body.effective_from_admission_year,
            grading_scale_id=src.grading_scale_id,
            rules=dict(src.rules),
            status="draft",
            created_by=self.principal.id,
        )
        counts: dict[str, int] = {}
        scheme_map = await self._clone_schemes(src.id, new.id, counts)
        scale_map = await self._clone_scales(src, new, counts)
        if new.grading_scale_id in scale_map:
            new.grading_scale_id = scale_map[new.grading_scale_id]
        course_map = await self._clone_courses(src.id, new.id, scheme_map, counts)
        await self._clone_structures(src.id, new.id, course_map, counts)
        await self.db.flush()
        await self._audit(
            "clone", "regulation", new.id, None, {**snap(new, REG_KEYS), "source_id": str(src.id), **counts}
        )
        return (await self._responses([new]))[0]

    async def _clone_schemes(
        self, src_id: uuid.UUID, new_id: uuid.UUID, counts: dict[str, int]
    ) -> dict[uuid.UUID, uuid.UUID]:
        mapping: dict[uuid.UUID, uuid.UUID] = {}
        schemes = (
            (
                await self.db.execute(
                    select(AssessmentScheme).where(
                        AssessmentScheme.regulation_id == src_id, AssessmentScheme.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        for s in schemes:
            copy = AssessmentScheme(
                institution_id=self.inst,
                regulation_id=new_id,
                code=s.code,
                name=s.name,
                applies_to_course_types=list(s.applies_to_course_types or []),
                cia_weight=s.cia_weight,
                ese_weight=s.ese_weight,
                cia_max=s.cia_max,
                ese_max=s.ese_max,
                pass_rules=dict(s.pass_rules or {}),
                is_default=s.is_default,
                created_by=self.principal.id,
            )
            self.db.add(copy)
            await self.db.flush()
            mapping[s.id] = copy.id
            comps = (
                (await self.db.execute(select(AssessmentComponent).where(AssessmentComponent.scheme_id == s.id)))
                .scalars()
                .all()
            )
            for c in comps:
                self.db.add(
                    AssessmentComponent(
                        institution_id=self.inst,
                        scheme_id=copy.id,
                        code=c.code,
                        name=c.name,
                        category=c.category,
                        max_marks=c.max_marks,
                        scaled_to=c.scaled_to,
                        weight_pct=c.weight_pct,
                        best_of=c.best_of,
                        sequence=c.sequence,
                        is_mandatory=c.is_mandatory,
                        co_mappable=c.co_mappable,
                    )
                )
        counts["schemes"] = len(mapping)
        return mapping

    async def _clone_scales(
        self, src: Regulation, new: Regulation, counts: dict[str, int]
    ) -> dict[uuid.UUID, uuid.UUID]:
        mapping: dict[uuid.UUID, uuid.UUID] = {}
        scales = (
            (
                await self.db.execute(
                    select(GradingScale).where(GradingScale.regulation_id == src.id, GradingScale.deleted_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        for s in scales:
            copy = GradingScale(
                institution_id=self.inst,
                regulation_id=new.id,
                name=f"{s.name[:66]} · {new.code}"[:80],
                scale_type=s.scale_type,
                ranges=list(s.ranges),
                relative_config=s.relative_config,
                special_grades=s.special_grades,
                max_grade_point=s.max_grade_point,
                is_default=False,
                created_by=self.principal.id,
            )
            self.db.add(copy)
            await self.db.flush()
            mapping[s.id] = copy.id
        counts["grading_scales"] = len(mapping)
        return mapping

    async def _clone_courses(
        self,
        src_id: uuid.UUID,
        new_id: uuid.UUID,
        scheme_map: dict[uuid.UUID, uuid.UUID],
        counts: dict[str, int],
    ) -> dict[uuid.UUID, uuid.UUID]:
        mapping: dict[uuid.UUID, uuid.UUID] = {}
        courses = (
            (await self.db.execute(select(Course).where(Course.regulation_id == src_id, Course.deleted_at.is_(None))))
            .scalars()
            .all()
        )
        for c in courses:
            copy = Course(
                institution_id=self.inst,
                college_id=c.college_id,
                department_id=c.department_id,
                regulation_id=new_id,
                code=c.code,
                title=c.title,
                short_title=c.short_title,
                course_type=c.course_type,
                lecture_hours=c.lecture_hours,
                tutorial_hours=c.tutorial_hours,
                practical_hours=c.practical_hours,
                credits=c.credits,
                contact_hours_per_week=c.contact_hours_per_week,
                assessment_scheme_id=scheme_map.get(c.assessment_scheme_id) if c.assessment_scheme_id else None,
                cia_max=c.cia_max,
                ese_max=c.ese_max,
                is_credit_bearing=c.is_credit_bearing,
                is_gradable=c.is_gradable,
                min_seats=c.min_seats,
                max_seats=c.max_seats,
                syllabus=c.syllabus,
                textbooks=c.textbooks,
                references_list=c.references_list,
                is_public_catalog=c.is_public_catalog,
                status="approved" if c.status == "active" else c.status,
                created_by=self.principal.id,
            )
            self.db.add(copy)
            await self.db.flush()
            mapping[c.id] = copy.id
        prereqs = (
            (await self.db.execute(select(CoursePrerequisite).where(CoursePrerequisite.course_id.in_(list(mapping)))))
            .scalars()
            .all()
            if mapping
            else []
        )
        for p in prereqs:
            if p.related_course_id in mapping:
                self.db.add(
                    CoursePrerequisite(
                        institution_id=self.inst,
                        course_id=mapping[p.course_id],
                        related_course_id=mapping[p.related_course_id],
                        relation=p.relation,
                        min_grade=p.min_grade,
                        is_hard=p.is_hard,
                    )
                )
        counts["courses"], counts["prerequisites"] = len(mapping), len(prereqs)
        return mapping

    async def _clone_structures(
        self,
        src_id: uuid.UUID,
        new_id: uuid.UUID,
        course_map: dict[uuid.UUID, uuid.UUID],
        counts: dict[str, int],
    ) -> None:
        repo = CurriculumRepository(self.db, self.inst)
        bindings = await self.bindings.for_regulation(src_id)
        for b in bindings:
            nb = ProgramRegulation(
                institution_id=self.inst,
                program_id=b.program_id,
                regulation_id=new_id,
                rules_override=b.rules_override,
                total_credits_required=b.total_credits_required,
                status="draft",
                created_by=self.principal.id,
            )
            self.db.add(nb)
            await self.db.flush()
            bundle = await repo.load(b.id)
            basket_map: dict[uuid.UUID, uuid.UUID] = {}
            for bk in bundle.baskets:
                nbk = ElectiveBasket(
                    institution_id=self.inst,
                    program_regulation_id=nb.id,
                    code=bk.code,
                    name=bk.name,
                    basket_type=bk.basket_type,
                    term_number=bk.term_number,
                    min_choose=bk.min_choose,
                    max_choose=bk.max_choose,
                    credits_required=bk.credits_required,
                    allocation_mode=bk.allocation_mode,
                    created_by=self.principal.id,
                )
                self.db.add(nbk)
                await self.db.flush()
                basket_map[bk.id] = nbk.id
                for m in bundle.basket_courses.get(bk.id, []):
                    if m.course_id in course_map:
                        self.db.add(
                            ElectiveBasketCourse(
                                institution_id=self.inst,
                                basket_id=nbk.id,
                                course_id=course_map[m.course_id],
                                offering_department_id=m.offering_department_id,
                            )
                        )
            for t in bundle.terms:
                self.db.add(
                    ProgramStructureTerm(
                        institution_id=self.inst,
                        program_regulation_id=nb.id,
                        term_number=t.term_number,
                        name=t.name,
                        min_credits=t.min_credits,
                        max_credits=t.max_credits,
                        normal_credits=t.normal_credits,
                        is_exit_point=t.is_exit_point,
                        exit_award=t.exit_award,
                    )
                )
            for cc in bundle.courses:
                if cc.course_id not in course_map:
                    continue
                self.db.add(
                    CurriculumCourse(
                        institution_id=self.inst,
                        program_regulation_id=nb.id,
                        term_number=cc.term_number,
                        course_id=course_map[cc.course_id],
                        elective_basket_id=basket_map.get(cc.elective_basket_id) if cc.elective_basket_id else None,
                        is_mandatory=cc.is_mandatory,
                        credit_bucket=cc.credit_bucket,
                        sequence=cc.sequence,
                    )
                )
        counts["program_regulations"] = len(bindings)

    # ---- rule 5 ----------------------------------------------------------------------------------------------------
    async def diff(self, regulation_id: uuid.UUID) -> RegulationDiffResponse:
        reg, courses = await self.repo.with_courses(regulation_id)
        prev = await self.repo.predecessor(reg)
        out = RegulationDiffResponse(regulation_id=reg.id, regulation_code=reg.code)
        if prev is None:
            out.added = [self._brief(c) for c in courses]
            return out
        _, prev_courses = await self.repo.with_courses(prev.id)
        out.predecessor_id, out.predecessor_code = prev.id, prev.code
        mine = {c.code: c for c in courses}
        theirs = {c.code: c for c in prev_courses}
        out.added = [self._brief(mine[k]) for k in sorted(set(mine) - set(theirs))]
        out.removed = [self._brief(theirs[k]) for k in sorted(set(theirs) - set(mine))]
        for code in sorted(set(mine) & set(theirs)):
            a, b = theirs[code], mine[code]
            fields = {
                f: {"old": _jsonable(getattr(a, f)), "new": _jsonable(getattr(b, f))}
                for f in DIFF_FIELDS
                if getattr(a, f) != getattr(b, f)
            }
            if fields:
                out.changed.append(CourseChange(code=code, title=b.title, fields=fields))
            else:
                out.unchanged_count += 1
        keys = set(reg.rules or {}) | set(prev.rules or {})
        out.rules_changed = {
            k: {"old": (prev.rules or {}).get(k), "new": (reg.rules or {}).get(k)}
            for k in sorted(keys)
            if (prev.rules or {}).get(k) != (reg.rules or {}).get(k)
        }
        return out

    @staticmethod
    def _brief(c: Course) -> CourseBrief:
        return CourseBrief(code=c.code, title=c.title, credits=c.credits, course_type=c.course_type)

    # ---- rule 6 ----------------------------------------------------------------------------------------------------
    async def rules_effective(self, regulation_id: uuid.UUID, program_id: uuid.UUID | None) -> RulesEffectiveResponse:
        await self.repo.get_regulation(regulation_id)
        rules, binding = await RulesResolver(self.db).for_regulation(regulation_id, program_id)
        return RulesEffectiveResponse(
            regulation_id=regulation_id,
            program_id=program_id,
            program_regulation_id=binding.id if binding else None,
            rules=rules,
            overridden_keys=sorted((binding.rules_override or {}).keys()) if binding else [],
        )


def _jsonable(v: Any) -> Any:
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


# ---- workflow hook + inbox summary (Prompts/05 §05.7: regulation.approval → mark_approved) ---------------------------
@workflow_engine.on(WORKFLOW_KEY, "approved")
async def _on_regulation_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    reg = (await db.execute(select(Regulation).where(Regulation.id == instance.entity_id))).scalar_one_or_none()
    if reg is None or reg.status != "draft":
        return
    service = RegulationService(db, actor)
    resolution = (instance.context or {}).get("resolution_id")
    await service.mark_approved(reg, getattr(actor, "id", None), uuid.UUID(resolution) if resolution else None)


@workflow_engine.summariser("regulation")
async def _summarise_regulation(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (await db.execute(select(Regulation.code, Regulation.name).where(Regulation.id == entity_id))).first()
    if row is None:
        return None, None
    return f"{row[0]} — {row[1]}", f"/admin/academics/regulations/{entity_id}"
