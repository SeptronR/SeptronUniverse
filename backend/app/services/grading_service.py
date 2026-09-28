"""Grading scales and assessment schemes — Prompts/05 §05.6 ``grading_service`` (configuration only).

Business rules
1. **Scales**: ranges must cover 0–100 without gaps or overlaps (inclusive bounds; consecutive ranges may be 1 point
   apart — ``70–79`` then ``80–89``; a range without ``max_pct`` reaches up to the next grade's ``min_pct``), grades
   are unique, points never exceed ``max_grade_point``, and **exactly one fail grade** (``is_fail`` or 0 points) —
   special grades (AB, W, I …) live in ``special_grades``. One ``is_default`` scale per institution.
2. **Schemes** (per regulation, ``regulation_id`` NOT NULL): ``cia_weight + ese_weight = 100``; the CIA components'
   ``Σ scaled_to = cia_max`` (a ``best_of {take, of, group}`` group contributes ``take`` of its components) and, when
   ESE components are listed, their ``Σ scaled_to = ese_max``; ``best_of.take ≤ of``; component codes unique. One
   ``is_default`` scheme per regulation. Schemes under an active regulation are frozen (409 ``RECORD_LOCKED``).
3. **Copy-from-pack**: ``seed_pack_schemes(regulation)`` creates the pack's default schemes (IN: ``CIA40_SEE60``)
   for a new regulation (Phase 03 deferred them here — assessment schemes need a regulation).
Every write is audited (module ``exams``) — configuration consumed by Phases 13–15.
"""

import uuid
from decimal import Decimal
from typing import Any

from app.core.errors import APIError, ErrorCode
from app.core.packs import get_pack
from app.models.academic import GradingScale, Regulation
from app.models.curriculum import AssessmentComponent, AssessmentScheme
from app.repositories.assessment_scheme_repository import AssessmentSchemeRepository
from app.repositories.grading_repository import GradingRepository
from app.repositories.institution_repository import InstitutionRepository
from app.repositories.regulation_repository import RegulationRepository
from app.schemas.academics import (
    AssessmentComponentIn,
    AssessmentComponentOut,
    AssessmentComponentsReplace,
    AssessmentSchemeCreate,
    AssessmentSchemeResponse,
    AssessmentSchemeUpdate,
    GradeRange,
    GradingScaleCreate,
    GradingScaleResponse,
    GradingScaleUpdate,
)
from app.services.academics.common import AcademicServiceBase, ensure_structure_editable, snap
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

SCALE_KEYS = ("name", "regulation_id", "scale_type", "ranges", "special_grades", "max_grade_point", "is_default")
SCHEME_KEYS = (
    "code",
    "name",
    "applies_to_course_types",
    "cia_weight",
    "ese_weight",
    "cia_max",
    "ese_max",
    "pass_rules",
)
ESE_CATEGORIES = {"ese_theory", "ese_practical", "viva"}


def _vio(message: str, field: str, **details: Any) -> APIError:
    return APIError(422, ErrorCode.VALIDATION, message, {"field": field, **details})


def normalise_ranges(ranges: list[GradeRange], max_grade_point: Decimal) -> list[dict[str, Any]]:
    """Rule 1 — returns the ranges sorted from the highest band down with explicit ``max_pct`` and ``is_fail``."""
    items = sorted(ranges, key=lambda r: r.min_pct, reverse=True)
    grades = [r.grade.upper() for r in items]
    if len(grades) != len(set(grades)):
        raise _vio("Grades must be unique", "ranges")
    out: list[dict[str, Any]] = []
    upper_bound: float | None = None  # min_pct of the next higher band
    for r in items:
        if r.points > float(max_grade_point):
            raise _vio(f"Grade {r.grade}: points exceed max_grade_point {max_grade_point}", "ranges")
        max_pct = r.max_pct
        if max_pct is None:
            max_pct = 100.0 if upper_bound is None else upper_bound  # reaches the next band (half-open)
        if max_pct < r.min_pct:
            raise _vio(f"Grade {r.grade}: max_pct is below min_pct", "ranges")
        if upper_bound is None:
            if max_pct != 100:
                raise _vio("The highest grade must reach 100", "ranges", grade=r.grade)
        else:
            gap = upper_bound - max_pct
            if gap < 0:
                raise _vio(f"Grade {r.grade} overlaps the next higher grade", "ranges", grade=r.grade)
            if gap > 1:
                raise _vio(
                    f"Gap between {max_pct:g} and {upper_bound:g}: ranges must cover 0–100",
                    "ranges",
                    grade=r.grade,
                )
        is_fail = r.is_fail if r.is_fail is not None else r.points == 0
        out.append(
            {
                "grade": r.grade,
                "min_pct": r.min_pct,
                "max_pct": max_pct,
                "points": r.points,
                "is_fail": is_fail,
                **({"description": r.description} if r.description else {}),
            }
        )
        upper_bound = r.min_pct
    if items[-1].min_pct != 0:
        raise _vio("The lowest grade must start at 0", "ranges")
    fails = [o for o in out if o["is_fail"]]
    if len(fails) != 1:
        raise _vio(f"Exactly one fail grade is required (found {len(fails)})", "ranges")
    return out


def stored_ranges(ranges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows written by the Phase 03 pack seed use ``grade_point``; responses always say ``points``."""
    out = []
    for r in ranges or []:
        row = dict(r)
        if "points" not in row and "grade_point" in row:
            row["points"] = row.pop("grade_point")
        out.append(row)
    return out


def check_components(scheme: Any, components: list[AssessmentComponentIn]) -> None:
    """Rule 2 — weights and maxima of a scheme's components."""
    codes = [c.code.upper() for c in components]
    if len(codes) != len(set(codes)):
        raise _vio("Component codes must be unique", "components")
    groups: dict[str, list[AssessmentComponentIn]] = {}
    for c in components:
        if c.best_of is not None:
            if c.best_of.take > c.best_of.of:
                raise _vio(f"{c.code}: best_of.take must be ≤ best_of.of", "components", code=c.code)
            groups.setdefault(c.best_of.group or c.code, []).append(c)

    def total(cats: set[str] | None) -> Decimal:
        s = Decimal("0")
        seen: set[str] = set()
        for c in components:
            if (cats is None and c.category != "cia") or (cats is not None and c.category not in cats):
                continue
            value = Decimal(str(c.scaled_to if c.scaled_to is not None else c.max_marks))
            if c.best_of is not None:
                key = c.best_of.group or c.code
                if key in seen:
                    continue
                seen.add(key)
                members = groups[key]
                value = max(Decimal(str(m.scaled_to if m.scaled_to is not None else m.max_marks)) for m in members)
                value *= min(c.best_of.take, len(members))
            s += value
        return s

    cia = [c for c in components if c.category == "cia"]
    if cia:
        cia_total = total({"cia"})
        if cia_total != Decimal(scheme.cia_max):
            raise _vio(
                f"Σ scaled_to of the CIA components is {cia_total:g}, but cia_max is {scheme.cia_max}",
                "components",
                cia_total=float(cia_total),
                cia_max=scheme.cia_max,
            )
    ese = [c for c in components if c.category in ESE_CATEGORIES]
    if ese:
        ese_total = total(ESE_CATEGORIES)
        if ese_total != Decimal(scheme.ese_max):
            raise _vio(
                f"Σ scaled_to of the ESE components is {ese_total:g}, but ese_max is {scheme.ese_max}",
                "components",
                ese_total=float(ese_total),
                ese_max=scheme.ese_max,
            )


class GradingService(AcademicServiceBase):
    audit_module = "exams"

    def __init__(self, db: Any, principal: Any, request: Any = None):
        super().__init__(db, principal, request)
        self.scales = GradingRepository(db, principal, self.inst)
        self.schemes = AssessmentSchemeRepository(db, principal, self.inst)
        self.regulations = RegulationRepository(db, principal, self.inst)

    # ---- scales (rule 1) -------------------------------------------------------------------------------------------
    async def list_scales(
        self, params: PageParams, regulation_id: uuid.UUID | None, q: str | None
    ) -> tuple[list[GradingScaleResponse], PaginationMeta]:
        if not params.sort:
            params = params.model_copy(update={"sort": "name"})
        rows, pagination = await self.scales.paginate(self.scales.filtered(regulation_id, q), params)
        return [self._scale_out(s) for s in rows], pagination

    def _scale_out(self, s: GradingScale) -> GradingScaleResponse:
        r = GradingScaleResponse.model_validate(s)
        r.ranges = stored_ranges(s.ranges)
        return r

    async def create_scale(self, body: GradingScaleCreate) -> GradingScaleResponse:
        if await self.scales.by_name(self.inst, body.name):
            raise APIError(409, ErrorCode.CONFLICT, f"A grading scale named {body.name!r} exists", {"field": "name"})
        if body.regulation_id:
            await self.regulations.get_regulation(body.regulation_id)
        ranges = normalise_ranges(body.ranges, body.max_grade_point)
        s = await self.scales.create(
            institution_id=self.inst,
            regulation_id=body.regulation_id,
            name=body.name,
            scale_type=body.scale_type.value,
            ranges=ranges,
            relative_config=body.relative_config,
            special_grades=[g.model_dump() for g in body.special_grades] if body.special_grades else None,
            max_grade_point=body.max_grade_point,
            is_default=body.is_default,
            created_by=self.principal.id,
        )
        if body.is_default:
            await self.scales.clear_default(self.inst, s.id)
        await self._audit("create", "grading_scale", s.id, None, snap(s, SCALE_KEYS))
        return self._scale_out(s)

    async def update_scale(self, scale_id: uuid.UUID, body: GradingScaleUpdate) -> GradingScaleResponse:
        s = await self.scales.get_scale(scale_id)
        await self._ensure_scale_editable(s)
        old = snap(s, SCALE_KEYS)
        values = body.model_dump(exclude_unset=True, exclude={"version", "ranges", "special_grades"})
        if "scale_type" in values and values["scale_type"] is not None:
            values["scale_type"] = str(values["scale_type"])
        if (
            values.get("name")
            and values["name"].lower() != s.name.lower()
            and await self.scales.by_name(self.inst, values["name"])
        ):
            raise APIError(409, ErrorCode.CONFLICT, f"A grading scale named {values['name']!r} exists")
        mgp = body.max_grade_point or s.max_grade_point
        if body.ranges is not None:
            values["ranges"] = normalise_ranges(body.ranges, mgp)
        elif body.max_grade_point is not None:
            values["ranges"] = normalise_ranges([GradeRange.model_validate(r) for r in stored_ranges(s.ranges)], mgp)
        if body.special_grades is not None:
            values["special_grades"] = [g.model_dump() for g in body.special_grades]
        await self.scales.update(s, expected_version=body.version, **values)
        if body.is_default:
            await self.scales.clear_default(self.inst, s.id)
        await self._audit("update", "grading_scale", s.id, old, snap(s, SCALE_KEYS))
        return self._scale_out(s)

    async def _ensure_scale_editable(self, s: GradingScale) -> None:
        if s.regulation_id:
            ensure_structure_editable(await self.regulations.get_regulation(s.regulation_id))

    # ---- schemes (rule 2) ------------------------------------------------------------------------------------------
    async def list_schemes(
        self, params: PageParams, regulation_id: uuid.UUID | None
    ) -> tuple[list[AssessmentSchemeResponse], PaginationMeta]:
        if not params.sort:
            params = params.model_copy(update={"sort": "code"})
        rows, pagination = await self.schemes.paginate(self.schemes.filtered(regulation_id), params)
        return await self._scheme_out(list(rows)), pagination

    async def _scheme_out(self, rows: list[AssessmentScheme]) -> list[AssessmentSchemeResponse]:
        comps = await self.schemes.components([s.id for s in rows])
        regs = await self.regulations.codes(list({s.regulation_id for s in rows}))
        out = []
        for s in rows:
            r = AssessmentSchemeResponse.model_validate(s)
            r.components = [AssessmentComponentOut.model_validate(c) for c in comps.get(s.id, [])]
            r.regulation_code = regs.get(s.regulation_id, (None, None))[0]
            out.append(r)
        return out

    async def create_scheme(self, body: AssessmentSchemeCreate) -> AssessmentSchemeResponse:
        reg = await self.regulations.get_regulation(body.regulation_id)
        ensure_structure_editable(reg)
        if await self.schemes.by_code(reg.id, body.code):
            raise APIError(409, ErrorCode.CONFLICT, f"Scheme {body.code!r} exists in {reg.code}", {"field": "code"})
        self._check_weights(body.cia_weight, body.ese_weight)
        scheme = await self.schemes.create(
            institution_id=self.inst,
            regulation_id=reg.id,
            code=body.code.upper(),
            name=body.name,
            applies_to_course_types=[t.value for t in body.applies_to_course_types],
            cia_weight=body.cia_weight,
            ese_weight=body.ese_weight,
            cia_max=body.cia_max,
            ese_max=body.ese_max,
            pass_rules=body.pass_rules.model_dump(exclude_none=True),
            is_default=body.is_default,
            created_by=self.principal.id,
        )
        if body.components:
            check_components(scheme, body.components)
            await self.schemes.replace_components(scheme.id, self._components(scheme.id, body.components))
        if body.is_default:
            await self.schemes.clear_default(reg.id, scheme.id)
        await self._audit("create", "assessment_scheme", scheme.id, None, snap(scheme, SCHEME_KEYS))
        return (await self._scheme_out([scheme]))[0]

    async def update_scheme(self, scheme_id: uuid.UUID, body: AssessmentSchemeUpdate) -> AssessmentSchemeResponse:
        scheme = await self.schemes.get_scheme(scheme_id)
        ensure_structure_editable(await self.regulations.get_regulation(scheme.regulation_id))
        old = snap(scheme, SCHEME_KEYS)
        values = body.model_dump(exclude_unset=True, exclude={"version", "pass_rules", "applies_to_course_types"})
        if body.applies_to_course_types is not None:
            values["applies_to_course_types"] = [t.value for t in body.applies_to_course_types]
        if body.pass_rules is not None:
            values["pass_rules"] = body.pass_rules.model_dump(exclude_none=True)
        self._check_weights(values.get("cia_weight", scheme.cia_weight), values.get("ese_weight", scheme.ese_weight))
        await self.schemes.update(scheme, expected_version=body.version, **values)
        existing = (await self.schemes.components([scheme.id]))[scheme.id]
        if existing and ("cia_max" in values or "ese_max" in values):
            check_components(scheme, [AssessmentComponentIn.model_validate(c, from_attributes=True) for c in existing])
        if body.is_default:
            await self.schemes.clear_default(scheme.regulation_id, scheme.id)
        await self._audit("update", "assessment_scheme", scheme.id, old, snap(scheme, SCHEME_KEYS))
        return (await self._scheme_out([scheme]))[0]

    async def replace_components(
        self, scheme_id: uuid.UUID, body: AssessmentComponentsReplace
    ) -> AssessmentSchemeResponse:
        scheme = await self.schemes.get_scheme(scheme_id)
        ensure_structure_editable(await self.regulations.get_regulation(scheme.regulation_id))
        check_components(scheme, body.components)
        old = [c.code for c in (await self.schemes.components([scheme.id]))[scheme.id]]
        await self.schemes.replace_components(scheme.id, self._components(scheme.id, body.components))
        await self._audit(
            "replace_components",
            "assessment_scheme",
            scheme.id,
            {"components": old},
            {"components": [c.model_dump(mode="json") for c in body.components]},
        )
        return (await self._scheme_out([scheme]))[0]

    @staticmethod
    def _check_weights(cia: int, ese: int) -> None:
        if cia + ese != 100:
            raise _vio(f"cia_weight + ese_weight must be 100 (got {cia + ese})", "cia_weight")

    def _components(self, scheme_id: uuid.UUID, items: list[AssessmentComponentIn]) -> list[AssessmentComponent]:
        return [
            AssessmentComponent(
                institution_id=self.inst,
                scheme_id=scheme_id,
                code=c.code.upper(),
                name=c.name,
                category=c.category.value,
                max_marks=c.max_marks,
                scaled_to=c.scaled_to,
                weight_pct=c.weight_pct,
                best_of=c.best_of.model_dump(exclude_none=True) if c.best_of else None,
                sequence=c.sequence,
                is_mandatory=c.is_mandatory,
                co_mappable=c.co_mappable,
            )
            for c in items
        ]

    # ---- rule 3: copy-from-pack ----------------------------------------------------------------------------------
    async def seed_pack_schemes(self, reg: Regulation) -> int:
        inst = await InstitutionRepository(self.db).get(self.inst)
        pack = get_pack(getattr(inst, "regulatory_pack", None))
        created = 0
        for n, ps in enumerate(pack.default_assessment_schemes):
            if await self.schemes.by_code(reg.id, ps.code):
                continue
            scheme = await self.schemes.create(
                institution_id=self.inst,
                regulation_id=reg.id,
                code=ps.code,
                name=ps.name,
                applies_to_course_types=[],
                cia_weight=ps.internal_pct,
                ese_weight=ps.external_pct,
                cia_max=ps.internal_pct,
                ese_max=ps.external_pct,
                pass_rules={},
                is_default=n == 0,
                created_by=self.principal.id,
            )
            comps = [AssessmentComponentIn.model_validate(c) for c in ps.components] or [
                AssessmentComponentIn(
                    code="CIA", name="Continuous internal assessment", category="cia", max_marks=ps.internal_pct
                ),
                AssessmentComponentIn(
                    code="ESE",
                    name="End-semester examination",
                    category="ese_theory",
                    max_marks=100,
                    scaled_to=Decimal(ps.external_pct),
                    sequence=2,
                ),
            ]
            check_components(scheme, comps)
            await self.schemes.replace_components(scheme.id, self._components(scheme.id, comps))
            created += 1
        return created

    async def default_scheme_for(self, regulation_id: uuid.UUID, course_type: str) -> uuid.UUID | None:
        """The regulation's scheme whose ``applies_to_course_types`` lists the type, else its default scheme."""
        schemes = await self.schemes.for_regulation(regulation_id)
        for s in schemes:
            if course_type in (s.applies_to_course_types or []):
                return s.id
        for s in schemes:
            if s.is_default:
                return s.id
        return None
