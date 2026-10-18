"""OBE definitions — Prompts/13 §13.6 ``obe_service``.

* PEO / PO / PSO per programme (``outcome_definitions(scope_type='program')``), imported from the template in
  ``platform_settings['obe_templates']`` (revision ``0013``; NBA 12 POs for engineering, generic 8 otherwise) or edited;
  PEO-PO matrix (levels 1–3).
* COs per course (code / statement / Bloom; 4–8 recommended → warning) and the CO-PO / PSO matrix with
  justifications; **every CO maps to at least one PO** (422 ``CO_UNMAPPED``).
* Who edits: ``obe:manage`` (OBE coordinator, dean, institution admin; the HOD only for programmes / courses of its
  departments) and, for COs, faculty of the course's department while the regulation is not yet ``active`` — COs of
  an active regulation change only through ``obe:manage`` (audited ``override``). Reads are institution-wide.
"""

import csv
import io
import json
import uuid
from typing import Any

from sqlalchemy import select, text

from app.core.errors import APIError, ErrorCode
from app.models.academic import Program
from app.models.curriculum import Course
from app.models.hr import Staff
from app.models.obe import CoPoMapping, CourseOutcome, OutcomeDefinition, PeoPoMapping
from app.schemas.obe import (
    CoOut,
    CoPoCell,
    CoPoMatrixReplace,
    CoReplace,
    CourseOutcomes,
    OutcomeOut,
    OutcomesReplace,
    PeoPoCell,
    PeoPoMatrix,
    ProgramOutcomes,
    TemplateImport,
)
from app.services.assessment.common import AssessmentBase

NBA_POS = (
    (
        "PO1",
        "Engineering knowledge: apply mathematics, science, engineering fundamentals and specialisation to complex engineering problems.",
    ),
    ("PO2", "Problem analysis: identify, formulate, review literature and analyse complex engineering problems."),
    (
        "PO3",
        "Design/development of solutions: design solutions meeting specified needs with public health, safety, cultural, societal and environmental considerations.",
    ),
    ("PO4", "Conduct investigations of complex problems using research-based knowledge and methods."),
    (
        "PO5",
        "Modern tool usage: create, select and apply appropriate techniques, resources and modern engineering and IT tools.",
    ),
    (
        "PO6",
        "The engineer and society: assess societal, health, safety, legal and cultural issues relevant to professional practice.",
    ),
    (
        "PO7",
        "Environment and sustainability: understand the impact of engineering solutions in societal and environmental contexts.",
    ),
    ("PO8", "Ethics: apply ethical principles and commit to professional ethics and responsibilities."),
    (
        "PO9",
        "Individual and team work: function effectively as an individual and as a member or leader in diverse teams.",
    ),
    (
        "PO10",
        "Communication: communicate effectively on complex engineering activities with the community and society.",
    ),
    ("PO11", "Project management and finance: apply engineering and management principles to manage projects."),
    ("PO12", "Life-long learning: recognise the need for and engage in independent and life-long learning."),
)
GENERIC_POS = (
    ("PO1", "Disciplinary knowledge: demonstrate comprehensive knowledge of the discipline."),
    ("PO2", "Critical thinking and problem solving."),
    ("PO3", "Communication skills: express ideas effectively in writing and speech."),
    ("PO4", "Research-related skills: inquiry, analysis and interpretation of data."),
    ("PO5", "Digital and information literacy."),
    ("PO6", "Ethical, moral and social responsibility."),
    ("PO7", "Teamwork and leadership."),
    ("PO8", "Self-directed and life-long learning."),
)


class ObeService(AssessmentBase):
    audit_module = "obe"

    # ---- permission helpers ------------------------------------------------------------------------------------------
    def _manager(self) -> bool:
        return self.can("obe", "manage")

    def _dept_ids(self) -> list[uuid.UUID]:
        return [sid for st, sid in getattr(self.principal, "scopes", []) if st == "department" and sid is not None]

    def _unit_limited(self) -> bool:
        """HOD-style managers (department-scoped only) are narrowed to their departments."""
        scopes = {st for st, _ in getattr(self.principal, "scopes", [])}
        return bool(self._dept_ids()) and not ({"institution", "college", "faculty"} & scopes)

    async def _program(self, pid: uuid.UUID, *, write: bool = False) -> Program:
        p = (
            await self.db.execute(select(Program).where(Program.id == pid, Program.institution_id == self.inst))
        ).scalar_one_or_none()
        if p is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Programme not found")
        if write:
            if not self._manager():
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "obe:manage is required")
            if self._unit_limited() and getattr(p, "department_id", None) not in self._dept_ids():
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only programmes of your department")
        return p

    async def _course_write(self, course: Course) -> bool:
        """``True`` = override (manager on an active regulation); raises 403 when the caller may not edit."""
        status = (
            await self.db.execute(
                text("SELECT status FROM regulations WHERE id = CAST(:r AS uuid)"), {"r": str(course.regulation_id)}
            )
        ).scalar_one_or_none()
        active = status in ("active", "approved", "published")
        if self._manager():
            if self._unit_limited() and course.department_id not in self._dept_ids():
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only courses of your department")
            return active
        own_dept = (
            await self.db.execute(
                select(Staff.department_id).where(Staff.user_id == self.actor_id, Staff.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if own_dept != course.department_id or not self.can("marks", "enter"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only faculty of the course's department may edit its COs")
        if active:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "The regulation is active — COs change through a new regulation or an OBE override",
                {"code": "REGULATION_ACTIVE"},
            )
        return False

    # ---- programme outcomes ----------------------------------------------------------------------------------------------
    async def program_outcomes(self, pid: uuid.UUID) -> ProgramOutcomes:
        await self._program(pid)
        rows = (
            (
                await self.db.execute(
                    select(OutcomeDefinition)
                    .where(
                        OutcomeDefinition.scope_type == "program",
                        OutcomeDefinition.scope_id == pid,
                        OutcomeDefinition.is_active.is_(True),
                    )
                    .order_by(OutcomeDefinition.outcome_type, OutcomeDefinition.sequence)
                )
            )
            .scalars()
            .all()
        )
        ids = [r.id for r in rows]
        cells = (
            (await self.db.execute(select(PeoPoMapping).where(PeoPoMapping.peo_id.in_(ids or [uuid.uuid4()]))))
            .scalars()
            .all()
        )
        return ProgramOutcomes(
            program_id=pid,
            outcomes=[OutcomeOut.model_validate(r) for r in rows],
            peo_po=[PeoPoCell(peo_id=c.peo_id, po_id=c.po_id, level=c.level) for c in cells],
        )

    async def replace_outcomes(self, pid: uuid.UUID, body: OutcomesReplace) -> ProgramOutcomes:
        await self._program(pid, write=True)
        existing = {
            (r.outcome_type, r.code): r
            for r in (
                await self.db.execute(
                    select(OutcomeDefinition).where(
                        OutcomeDefinition.scope_type == "program", OutcomeDefinition.scope_id == pid
                    )
                )
            ).scalars()
        }
        keep: set[tuple[str, str]] = set()
        for o in body.outcomes:
            key: tuple[str, str] = (str(o.outcome_type), o.code)
            keep.add(key)
            row = existing.get(key)
            if row is None:
                self.db.add(
                    OutcomeDefinition(institution_id=self.inst, scope_type="program", scope_id=pid, **o.model_dump())
                )
            else:
                row.statement, row.framework, row.sequence, row.is_active = o.statement, o.framework, o.sequence, True
        for key, row in existing.items():
            if key not in keep:
                row.is_active = False
        await self.db.flush()
        await self._audit("outcomes", "program", pid, None, {"count": len(body.outcomes)})
        await self._emit("obe.definitions_changed", {"program_id": str(pid)}, "program", pid)
        return await self.program_outcomes(pid)

    async def import_template(self, pid: uuid.UUID, body: TemplateImport) -> ProgramOutcomes:
        p = await self._program(pid, write=True)
        deg = f"{p.degree_name} {p.code}".lower().replace(".", "")
        tmpl = body.template or (
            "nba_engineering"
            if any(k in deg for k in ("btech", "be ", "mtech", "me ", "engineering", "tech"))
            else "generic"
        )
        stored = (
            await self.db.execute(text("SELECT value FROM platform_settings WHERE key = 'obe_templates'"))
        ).scalar_one_or_none()
        pos = None
        if stored:
            data = stored if isinstance(stored, dict) else json.loads(stored)
            pos = [(x["code"], x["statement"]) for x in (data.get(tmpl) or {}).get("PO", [])] or None
        pos = pos or list(NBA_POS if tmpl == "nba_engineering" else GENERIC_POS)
        current = (await self.program_outcomes(pid)).outcomes
        merged = [o for o in current if o.outcome_type != "PO"]
        from app.schemas.obe import OutcomeIn

        body_out = [
            OutcomeIn(
                outcome_type=o.outcome_type,
                code=o.code,
                statement=o.statement,
                framework=o.framework,
                sequence=o.sequence,
            )
            for o in merged
        ]  # type: ignore[arg-type]
        body_out += [
            OutcomeIn(
                outcome_type="PO",
                code=c,
                statement=s,
                framework="NBA" if tmpl == "nba_engineering" else "generic",
                sequence=i + 1,
            )
            for i, (c, s) in enumerate(pos)
        ]
        psos = body.psos or (
            []
            if any(o.outcome_type == "PSO" for o in merged)
            else [f"Programme-specific outcome {i} of {p.code}" for i in (1, 2)]
        )
        body_out += [
            OutcomeIn(
                outcome_type="PSO",
                code=f"PSO{i + 1}",
                statement=s,
                framework="NBA" if tmpl == "nba_engineering" else "generic",
                sequence=i + 1,
            )
            for i, s in enumerate(psos)
        ]
        return await self.replace_outcomes(pid, OutcomesReplace(outcomes=body_out))

    async def replace_peo_po(self, pid: uuid.UUID, body: PeoPoMatrix) -> ProgramOutcomes:
        await self._program(pid, write=True)
        outs = {o.id: o for o in (await self.program_outcomes(pid)).outcomes}
        for c in body.cells:
            if (
                outs.get(c.peo_id) is None
                or outs[c.peo_id].outcome_type != "PEO"
                or outs.get(c.po_id) is None
                or outs[c.po_id].outcome_type not in ("PO", "PSO")
            ):
                raise APIError(
                    422, ErrorCode.VALIDATION, "Cells must map a PEO of this programme to one of its POs / PSOs"
                )
        for old in (
            await self.db.execute(
                select(PeoPoMapping).where(
                    PeoPoMapping.peo_id.in_([k for k, v in outs.items() if v.outcome_type == "PEO"] or [uuid.uuid4()])
                )
            )
        ).scalars():
            await self.db.delete(old)
        await self.db.flush()
        for c in body.cells:
            self.db.add(PeoPoMapping(institution_id=self.inst, peo_id=c.peo_id, po_id=c.po_id, level=c.level))
        await self.db.flush()
        await self._audit("peo_po", "program", pid, None, {"cells": len(body.cells)})
        return await self.program_outcomes(pid)

    # ---- course outcomes -------------------------------------------------------------------------------------------------
    async def _program_of_course(self, course: Course) -> uuid.UUID | None:
        pid = (
            await self.db.execute(
                text("SELECT program_id FROM program_regulations WHERE regulation_id = CAST(:r AS uuid) LIMIT 1"),
                {"r": str(course.regulation_id)},
            )
        ).scalar_one_or_none()
        return pid

    async def course_outcomes(self, course_id: uuid.UUID) -> CourseOutcomes:
        course = await self.course(course_id)
        cos = (
            (
                await self.db.execute(
                    select(CourseOutcome).where(CourseOutcome.course_id == course.id).order_by(CourseOutcome.sequence)
                )
            )
            .scalars()
            .all()
        )
        cells = (
            (
                await self.db.execute(
                    select(CoPoMapping).where(CoPoMapping.course_outcome_id.in_([c.id for c in cos] or [uuid.uuid4()]))
                )
            )
            .scalars()
            .all()
        )
        pid = await self._program_of_course(course)
        pos = (await self.program_outcomes(pid)).outcomes if pid else []
        warnings = []
        if cos and not 4 <= len(cos) <= 8:
            warnings.append(f"{len(cos)} COs — 4 to 8 are recommended")
        editable = True
        try:
            await self._course_write(course)
        except APIError:
            editable = False
        return CourseOutcomes(
            course_id=course.id,
            cos=[CoOut.model_validate(c) for c in cos],
            program_outcomes=[p for p in pos if p.outcome_type in ("PO", "PSO")],
            matrix=[
                CoPoCell(
                    co_id=c.course_outcome_id, outcome_id=c.outcome_id, level=c.level, justification=c.justification
                )
                for c in cells
            ],
            warnings=warnings,
            editable=editable,
        )

    async def replace_cos(self, course_id: uuid.UUID, body: CoReplace) -> CourseOutcomes:
        course = await self.course(course_id)
        override = await self._course_write(course)
        existing = {
            c.code: c
            for c in (
                await self.db.execute(select(CourseOutcome).where(CourseOutcome.course_id == course.id))
            ).scalars()
        }
        keep = set()
        for co in body.outcomes:
            keep.add(co.code)
            row = existing.get(co.code)
            if row is None:
                self.db.add(CourseOutcome(institution_id=self.inst, course_id=course.id, **co.model_dump()))
            else:
                row.statement, row.bloom_level, row.sequence = co.statement, co.bloom_level, co.sequence
        for code, row in existing.items():
            if code not in keep:
                await self.db.delete(row)
        await self.db.flush()
        await self._audit(
            "override_cos" if override else "cos", "course", course.id, None, {"count": len(body.outcomes)}
        )
        await self._emit("obe.definitions_changed", {"course_id": str(course.id)}, "course", course.id)
        return await self.course_outcomes(course.id)

    async def replace_matrix(self, course_id: uuid.UUID, body: CoPoMatrixReplace) -> CourseOutcomes:
        course = await self.course(course_id)
        override = await self._course_write(course)
        cos = {
            c.id
            for c in (
                await self.db.execute(select(CourseOutcome).where(CourseOutcome.course_id == course.id))
            ).scalars()
        }
        pid = await self._program_of_course(course)
        pos = (
            {o.id for o in (await self.program_outcomes(pid)).outcomes if o.outcome_type in ("PO", "PSO")}
            if pid
            else set()
        )
        if any(c.co_id not in cos for c in body.cells) or any(c.outcome_id not in pos for c in body.cells):
            raise APIError(422, ErrorCode.VALIDATION, "Cells must map this course's COs to its programme's POs / PSOs")
        unmapped = cos - {c.co_id for c in body.cells}
        if unmapped:
            codes = [
                c.code
                for c in (
                    await self.db.execute(select(CourseOutcome).where(CourseOutcome.id.in_(list(unmapped))))
                ).scalars()
            ]
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Every CO must map to at least one PO — unmapped: {', '.join(sorted(codes))}",
                {"code": "CO_UNMAPPED", "cos": codes},
            )
        for old in (
            await self.db.execute(
                select(CoPoMapping).where(CoPoMapping.course_outcome_id.in_(list(cos) or [uuid.uuid4()]))
            )
        ).scalars():
            await self.db.delete(old)
        await self.db.flush()
        for c in body.cells:
            self.db.add(
                CoPoMapping(
                    institution_id=self.inst,
                    course_outcome_id=c.co_id,
                    outcome_id=c.outcome_id,
                    level=c.level,
                    justification=c.justification,
                )
            )
        await self.db.flush()
        await self._audit(
            "override_co_po" if override else "co_po", "course", course.id, None, {"cells": len(body.cells)}
        )
        await self._emit("obe.definitions_changed", {"course_id": str(course.id)}, "course", course.id)
        return await self.course_outcomes(course.id)

    async def matrix_csv(self, course_id: uuid.UUID) -> bytes:
        data = await self.course_outcomes(course_id)
        cols = list(data.program_outcomes)
        level = {(c.co_id, c.outcome_id): c.level for c in data.matrix}
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["CO", "Statement", *[p.code for p in cols]])
        for co in data.cos:
            w.writerow([co.code, co.statement, *[level.get((co.id, p.id), "-") for p in cols]])
        return buf.getvalue().encode("utf-8-sig")


def template_json() -> dict[str, Any]:
    """``platform_settings['obe_templates']`` seeded by revision ``0013``."""
    return {
        "nba_engineering": {"PO": [{"code": c, "statement": s} for c, s in NBA_POS]},
        "generic": {"PO": [{"code": c, "statement": s} for c, s in GENERIC_POS]},
        "bloom_levels": ["remember", "understand", "apply", "analyze", "evaluate", "create"],
    }
