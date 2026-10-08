"""Courses — Prompts/05 §05.6 ``course_service`` (+ the prerequisite graph of ``curriculum_service`` rule 3).

Business rules
1. CRUD under a regulation: ``code`` unique per regulation (409); ``contact_hours_per_week = L + T + P``; credits ≥ 0;
   ``is_credit_bearing = false`` (and credits 0) for ``audit`` / ``mandatory_non_credit``; the assessment scheme
   defaults from the regulation by course type (``applies_to_course_types``, else the default scheme) and seeds
   ``cia_max`` / ``ese_max``. Writes are narrowed to the caller's departments — ``hod`` @department drafts the courses
   of its own department (another department → 403 on create, 404 on update).
2. Courses under an ``active``/``superseded`` regulation are frozen (409 ``RECORD_LOCKED`` on every mutation) — the
   only exception is retiring a course (``→ retired`` is lifecycle, not content). Status machine
   ``draft → approved → active → retired`` (``approved → draft`` to rework); ``→ approved`` needs ``courses:approve``
   (dean @faculty, registrar), the other moves ``courses:update``; ``active`` is set when the regulation is
   activated, never by hand.
3. Prerequisites (``PUT /courses/{id}/prerequisites``, replace): related courses of the same regulation (422), never
   the course itself (422); the ``prerequisite`` relation must stay **acyclic** (DFS over the regulation's graph →
   422 ``RULE_VIOLATION`` naming the cycle); ``antirequisite`` is symmetric (mirror rows kept in sync).
4. ``bulk_import`` — CSV ``code,title,type,L,T,P,credits,department_code,scheme_code`` as the job
   ``courses.bulk_import``; each row runs rule 1 inside a savepoint, the report lists ``succeeded`` and
   ``failed[{row, code, message}]``. ``export`` → XLSX of the filtered list.
5. Events ``course.created|updated|retired`` (consumers ``search.reindex``, ``catalog.invalidate``); audit on every
   change (module ``courses``).
"""

import csv
import io
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.core import jobs
from app.core.errors import APIError, ErrorCode
from app.enums.academics import COURSE_TRANSITIONS, NON_CREDIT_COURSE_TYPES, CourseType
from app.models.curriculum import Course, CoursePrerequisite, CurriculumCourse
from app.models.platform import Department
from app.repositories.assessment_scheme_repository import AssessmentSchemeRepository
from app.repositories.course_repository import CourseRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.regulation_repository import RegulationRepository
from app.schemas.curriculum import (
    CourseBulkImportRequest,
    CourseCreate,
    CourseResponse,
    CourseStatusChange,
    CourseUpdate,
    PrerequisiteOut,
    PrerequisiteSet,
)
from app.services.academics.common import AcademicServiceBase, ensure_structure_editable, snap
from app.services.academics.context import (
    academic_visibility,
    check_department_writable,
    scope_filters,
    writable_department_ids,
)
from app.services.curriculum_service import ltpc
from app.services.grading_service import GradingService
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

COURSE_KEYS = (
    "code",
    "title",
    "course_type",
    "department_id",
    "regulation_id",
    "lecture_hours",
    "tutorial_hours",
    "practical_hours",
    "credits",
    "assessment_scheme_id",
    "cia_max",
    "ese_max",
    "is_credit_bearing",
    "is_public_catalog",
    "status",
)
CSV_COLUMNS = ("code", "title", "type", "L", "T", "P", "credits", "department_code", "scheme_code")


def find_cycle(edges: dict[uuid.UUID, set[uuid.UUID]], start: uuid.UUID) -> list[uuid.UUID] | None:
    """Iterative DFS: a path start → … → start through ``edges`` (course → its prerequisites), else None."""
    stack: list[tuple[uuid.UUID, list[uuid.UUID]]] = [(n, [start, n]) for n in edges.get(start, ())]
    seen: set[uuid.UUID] = set()
    while stack:
        node, path = stack.pop()
        if node == start:
            return path
        if node in seen:
            continue
        seen.add(node)
        stack.extend((nxt, [*path, nxt]) for nxt in edges.get(node, ()))
    return None


class CourseService(AcademicServiceBase):
    audit_module = "courses"

    def __init__(self, db: Any, principal: Any, request: Any = None):
        super().__init__(db, principal, request)
        self.repo = CourseRepository(db, principal, self.inst)
        self.regulations = RegulationRepository(db, principal, self.inst)
        self.departments = DepartmentRepository(db, principal, self.inst)
        self.schemes = AssessmentSchemeRepository(db, principal, self.inst)

    # ---- reads -----------------------------------------------------------------------------------------------------
    async def list_page(
        self,
        params: PageParams,
        scope: str | None,
        *,
        regulation_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        course_type: str | None,
        status: str | None,
        q: str | None,
    ) -> tuple[list[CourseResponse], PaginationMeta, VisibilityMeta]:
        dept_ids, college_ids = scope_filters(self.principal, scope)
        stmt = self.repo.filtered(
            regulation_id=regulation_id,
            department_id=department_id,
            department_ids=dept_ids if not department_id else None,
            course_type=course_type,
            status=status,
            q=q,
        )
        if college_ids is not None:
            stmt = stmt.where(Course.college_id.in_(list(college_ids)))
        if not params.sort and not q:
            params = params.model_copy(update={"sort": "code"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._responses(list(rows), with_prereqs=True), pagination, academic_visibility(self.principal)

    async def get(self, course_id: uuid.UUID) -> CourseResponse:
        from app.services.academics.enrolled import ensure_course_in_enrolled_curriculum

        await ensure_course_in_enrolled_curriculum(self.db, self.principal, course_id)  # students / parents (Phase 07)
        c = await self.repo.get_course(course_id)
        return (await self._responses([c], with_prereqs=True))[0]

    async def _responses(self, rows: list[Course], *, with_prereqs: bool = False) -> list[CourseResponse]:
        regs = await self.regulations.codes(list({c.regulation_id for c in rows}))
        dept_codes = await self._dept_codes(list({c.department_id for c in rows}))
        schemes = await self.schemes.codes([c.assessment_scheme_id for c in rows if c.assessment_scheme_id])
        writable = await writable_department_ids(self.db, self.principal)
        can_update = self.principal.has("courses", "update")
        prereqs: dict[uuid.UUID, list[PrerequisiteOut]] = {}
        if with_prereqs:
            links = await self.repo.prerequisites([c.id for c in rows])
            related = await self.repo.by_ids([p.related_course_id for p in links])
            for p in links:
                out = PrerequisiteOut.model_validate(p)
                rc = related.get(p.related_course_id)
                out.related_code, out.related_title = (rc.code, rc.title) if rc else (None, None)
                prereqs.setdefault(p.course_id, []).append(out)
        out_rows = []
        for c in rows:
            r = CourseResponse.model_validate(c)
            r.regulation_code, r.regulation_status = regs.get(c.regulation_id, (None, None))
            r.department_code = dept_codes.get(c.department_id)
            r.scheme_code = schemes.get(c.assessment_scheme_id) if c.assessment_scheme_id else None
            r.ltpc = ltpc(c)
            r.can_edit = (
                can_update
                and r.regulation_status in ("draft", "approved")
                and (writable is None or c.department_id in writable)
            )
            r.prerequisites = prereqs.get(c.id, [])
            out_rows.append(r)
        return out_rows

    async def _dept_codes(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        rows = (await self.db.execute(select(Department.id, Department.code).where(Department.id.in_(ids)))).all()
        return {r[0]: r[1] for r in rows}

    # ---- rule 1 ----------------------------------------------------------------------------------------------------
    async def create(self, body: CourseCreate, *, emit: bool = True) -> CourseResponse:
        reg = await self.regulations.get_regulation(body.regulation_id)
        ensure_structure_editable(reg)
        dept = await self.departments.get_scoped(body.department_id, None)
        check_department_writable(await writable_department_ids(self.db, self.principal), dept.id, create=True)
        if await self.repo.by_code(reg.id, body.code):
            raise APIError(
                409, ErrorCode.CONFLICT, f"Course {body.code.upper()} already exists in {reg.code}", {"field": "code"}
            )
        values = body.model_dump(exclude={"syllabus"})
        values["course_type"] = body.course_type.value
        values["code"] = body.code.upper()
        values["college_id"] = body.college_id or reg.college_id or dept.college_id
        values["syllabus"] = [u.model_dump() for u in body.syllabus] if body.syllabus else None
        await self._derive(values, reg.id)
        c = await self.repo.create(institution_id=self.inst, created_by=self.principal.id, status="draft", **values)
        await self._audit("create", "course", c.id, None, snap(c, COURSE_KEYS))
        if emit:
            await self._event(c, "course.created")
        return (await self._responses([c]))[0]

    async def _derive(self, values: dict[str, Any], regulation_id: uuid.UUID, current: Course | None = None) -> None:
        """Rule 1 derivations on a create payload (``current`` None) or on the changed fields of an update."""

        def pick(key: str) -> Any:
            return values[key] if key in values else getattr(current, key, None)

        ctype = pick("course_type")
        values["contact_hours_per_week"] = sum(
            int(pick(k) or 0) for k in ("lecture_hours", "tutorial_hours", "practical_hours")
        )
        if ctype in NON_CREDIT_COURSE_TYPES:
            values["is_credit_bearing"] = False
            values["credits"] = Decimal("0")
        elif current is None or "course_type" in values:
            values["is_credit_bearing"] = True
        type_changed = current is None or ("course_type" in values and values["course_type"] != current.course_type)
        if values.get("assessment_scheme_id") is None and type_changed and ctype is not None:
            values["assessment_scheme_id"] = await GradingService(
                self.db, self.principal, self.request
            ).default_scheme_for(regulation_id, ctype)
        sid = values.get("assessment_scheme_id")
        if sid is None:
            return
        scheme = await self.schemes.get_scheme(sid)
        if scheme.regulation_id != regulation_id:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "The assessment scheme belongs to another regulation",
                {"field": "assessment_scheme_id"},
            )
        if values.get("cia_max") is None:
            values["cia_max"] = scheme.cia_max
        if values.get("ese_max") is None:
            values["ese_max"] = scheme.ese_max

    async def update(self, course_id: uuid.UUID, body: CourseUpdate) -> CourseResponse:
        c = await self.repo.get_course(course_id, for_update=True)
        ensure_structure_editable(await self.regulations.get_regulation(c.regulation_id))
        writable = await writable_department_ids(self.db, self.principal)
        check_department_writable(writable, c.department_id, create=False)
        values = body.model_dump(exclude_unset=True, exclude={"version", "syllabus"})
        if "department_id" in values and values["department_id"] is not None:
            dept = await self.departments.get_scoped(values["department_id"], None)
            check_department_writable(writable, dept.id, create=True)
        if values.get("course_type") is not None:
            values["course_type"] = str(values["course_type"])
        if body.syllabus is not None:
            values["syllabus"] = [u.model_dump() for u in body.syllabus]
        if values.get("credits") is None:
            values.pop("credits", None)
        await self._derive(values, c.regulation_id, current=c)
        old = snap(c, COURSE_KEYS)
        await self.repo.update(c, expected_version=body.version, **values)
        await self._audit("update", "course", c.id, old, snap(c, COURSE_KEYS))
        await self._event(c, "course.updated")
        return (await self._responses([c]))[0]

    async def change_status(self, course_id: uuid.UUID, body: CourseStatusChange) -> CourseResponse:
        c = await self.repo.get_course(course_id, for_update=True)
        reg = await self.regulations.get_regulation(c.regulation_id)
        target = body.status.value
        needed = "approve" if target == "approved" else "update"
        if not self.principal.has("courses", needed):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, f"Requires courses:{needed}", {"module": "courses"})
        if target != "retired":
            ensure_structure_editable(reg)
        check_department_writable(await writable_department_ids(self.db, self.principal), c.department_id, create=False)
        if target == "active":
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "Courses become active when their regulation is activated",
                {"allowed": sorted(COURSE_TRANSITIONS.get(c.status, frozenset()) - {"active"})},
            )
        if target not in COURSE_TRANSITIONS.get(c.status, frozenset()):
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"Cannot move a {c.status} course to {target}",
                {"from": c.status, "to": target, "allowed": sorted(COURSE_TRANSITIONS.get(c.status, frozenset()))},
            )
        old = snap(c, COURSE_KEYS)
        c.status = target
        await self.db.flush()
        await self._audit("status", "course", c.id, old, snap(c, COURSE_KEYS))
        await self._event(c, "course.retired" if target == "retired" else "course.updated")
        return (await self._responses([c]))[0]

    async def delete(self, course_id: uuid.UUID) -> None:
        c = await self.repo.get_course(course_id, for_update=True)
        ensure_structure_editable(await self.regulations.get_regulation(c.regulation_id))
        check_department_writable(await writable_department_ids(self.db, self.principal), c.department_id, create=False)
        if c.status != "draft":
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Only draft courses can be deleted — retire it instead")
        used = (await self.db.execute(select(CurriculumCourse.id).where(CurriculumCourse.course_id == c.id))).first()
        if used:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "The course is placed in a programme structure")
        old = snap(c, COURSE_KEYS)
        await self.repo.soft_delete(c, self.principal.id)
        await self._audit("delete", "course", c.id, old, None)
        await self._event(c, "course.retired")

    async def _event(self, c: Course, event_type: str) -> None:
        await self._emit(
            event_type,
            {
                "course_id": str(c.id),
                "code": c.code,
                "regulation_id": str(c.regulation_id),
                "department_id": str(c.department_id),
                "status": c.status,
            },
            "course",
            c.id,
        )

    # ---- rule 3: prerequisites --------------------------------------------------------------------------------------
    async def set_prerequisites(self, course_id: uuid.UUID, body: PrerequisiteSet) -> CourseResponse:
        c = await self.repo.get_course(course_id, for_update=True)
        ensure_structure_editable(await self.regulations.get_regulation(c.regulation_id))
        check_department_writable(await writable_department_ids(self.db, self.principal), c.department_id, create=False)
        related = await self.repo.by_ids([i.related_course_id for i in body.items])
        keys: set[tuple[uuid.UUID, str]] = set()
        for item in body.items:
            if item.related_course_id == c.id:
                raise APIError(422, ErrorCode.VALIDATION, "A course cannot be its own prerequisite", {"field": "items"})
            rc = related.get(item.related_course_id)
            if rc is None or rc.regulation_id != c.regulation_id:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "Related courses must belong to the same regulation",
                    {"field": "items", "related_course_id": str(item.related_course_id)},
                )
            key = (item.related_course_id, item.relation.value)
            if key in keys:
                raise APIError(422, ErrorCode.VALIDATION, f"{rc.code} is listed twice as {item.relation.value}")
            keys.add(key)
        # acyclic prerequisite graph: this course's new prerequisite set + every other course's existing edges
        edges: dict[uuid.UUID, set[uuid.UUID]] = {}
        for src, dst, rel in await self.repo.prerequisite_edges(c.regulation_id):
            if rel == "prerequisite" and src != c.id:
                edges.setdefault(src, set()).add(dst)
        edges[c.id] = {i.related_course_id for i in body.items if i.relation.value == "prerequisite"}
        cycle = find_cycle(edges, c.id)
        if cycle:
            codes = await self.repo.by_ids(cycle)
            path = " → ".join(codes[n].code if n in codes else str(n) for n in cycle)
            raise APIError(
                422,
                ErrorCode.RULE_VIOLATION,
                f"Prerequisite cycle: {path}",
                {"cycle": [str(n) for n in cycle], "path": path},
            )
        old = [
            {"related_course_id": str(p.related_course_id), "relation": p.relation}
            for p in await self.repo.prerequisites([c.id])
        ]
        rows = [
            CoursePrerequisite(
                institution_id=self.inst,
                course_id=c.id,
                related_course_id=i.related_course_id,
                relation=i.relation.value,
                min_grade=i.min_grade,
                is_hard=i.is_hard,
            )
            for i in body.items
        ]
        await self.repo.replace_prerequisites(c.id, rows)
        anti = {i.related_course_id for i in body.items if i.relation.value == "antirequisite"}
        await self.repo.delete_antirequisite_mirror(c.id, anti)
        for other in anti:
            await self.repo.ensure_antirequisite(self.inst, other, c.id)
        await self.db.flush()
        await self._audit(
            "set_prerequisites",
            "course",
            c.id,
            {"items": old},
            {"items": [i.model_dump(mode="json") for i in body.items]},
        )
        await self._event(c, "course.updated")
        return (await self._responses([c], with_prereqs=True))[0]

    # ---- rule 4: bulk import / export -------------------------------------------------------------------------------
    async def enqueue_bulk_import(self, body: CourseBulkImportRequest) -> dict[str, Any]:
        reg = await self.regulations.get_regulation(body.regulation_id)
        ensure_structure_editable(reg)
        header = next(csv.reader(io.StringIO(body.csv.lstrip("﻿"))), [])
        missing = [c for c in CSV_COLUMNS if c not in [h.strip() for h in header]]
        if missing:
            raise APIError(422, ErrorCode.VALIDATION, f"CSV header is missing {', '.join(missing)}", {"field": "csv"})
        row = await jobs.enqueue(
            self.db,
            self.principal,
            "courses.bulk_import",
            {"regulation_id": str(reg.id), "csv": body.csv},
            queue="reports",
        )
        return {"job_id": row.id, "status": row.status, "job_type": row.job_type}

    async def run_bulk_import(self, regulation_id: uuid.UUID, text_csv: str, progress: Any = None) -> dict[str, Any]:
        """Job body: one savepoint per row → partial success report."""
        reg = await self.regulations.get_regulation(regulation_id)
        ensure_structure_editable(reg)
        reader = csv.DictReader(io.StringIO(text_csv.lstrip("﻿")))
        rows = [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in reader]
        dept_by_code = await self._dept_by_code()
        schemes = {s.code.upper(): s.id for s in await self.schemes.for_regulation(reg.id)}
        succeeded, failed = 0, []
        for n, raw in enumerate(rows, start=2):  # row 1 = header
            try:
                body = self._csv_course(raw, reg.id, dept_by_code, schemes)
                async with self.db.begin_nested():
                    await self.create(body, emit=False)
                succeeded += 1
            except APIError as exc:
                failed.append({"row": n, "code": raw.get("code"), "error": exc.code, "message": exc.message})
            except (ValueError, InvalidOperation) as exc:
                failed.append({"row": n, "code": raw.get("code"), "error": "VALIDATION", "message": str(exc)[:300]})
            if progress is not None and n % 10 == 0:
                await progress(int(n * 90 / max(len(rows), 1)), f"{n - 1}/{len(rows)} rows")
        if succeeded:
            await self._emit(
                "course.updated",
                {"regulation_id": str(reg.id), "bulk_import": True, "created": succeeded},
                "regulation",
                reg.id,
            )
        return {"total": len(rows), "succeeded": succeeded, "failed": failed, "regulation_code": reg.code}

    async def _dept_by_code(self) -> dict[str, uuid.UUID]:
        rows = (
            await self.db.execute(
                select(Department.code, Department.id).where(
                    Department.institution_id == self.inst, Department.deleted_at.is_(None)
                )
            )
        ).all()
        return {r[0].upper(): r[1] for r in rows}

    @staticmethod
    def _csv_course(
        raw: dict[str, str], regulation_id: uuid.UUID, depts: dict[str, uuid.UUID], schemes: dict[str, uuid.UUID]
    ) -> CourseCreate:
        dept = depts.get(raw.get("department_code", "").upper())
        if dept is None:
            raise ValueError(f"unknown department_code {raw.get('department_code')!r}")
        scheme_code = raw.get("scheme_code", "").upper()
        if scheme_code and scheme_code not in schemes:
            raise ValueError(f"unknown scheme_code {raw.get('scheme_code')!r}")
        ctype = raw.get("type", "").lower()
        if ctype not in {t.value for t in CourseType}:
            raise ValueError(f"unknown course type {raw.get('type')!r}")
        try:
            return CourseCreate(
                regulation_id=regulation_id,
                department_id=dept,
                code=raw.get("code", ""),
                title=raw.get("title", ""),
                course_type=CourseType(ctype),
                lecture_hours=int(raw.get("L") or 0),
                tutorial_hours=int(raw.get("T") or 0),
                practical_hours=int(raw.get("P") or 0),
                credits=Decimal(raw.get("credits") or "0"),
                assessment_scheme_id=schemes.get(scheme_code) if scheme_code else None,
            )
        except ValidationError as exc:
            first = exc.errors(include_url=False)[0]
            raise ValueError(f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from exc

    async def export_xlsx(
        self,
        *,
        regulation_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
        course_type: str | None,
        status: str | None,
        q: str | None,
    ) -> bytes:
        from openpyxl import Workbook

        rows, _, _ = await self.list_page(
            PageParams(page=1, page_size=5000),
            "all",
            regulation_id=regulation_id,
            department_id=department_id,
            course_type=course_type,
            status=status,
            q=q,
        )
        wb = Workbook()
        ws = wb.active
        ws.title = "Courses"
        ws.append(["Regulation", "Code", "Title", "Type", "L", "T", "P", "Credits", "Department", "Scheme", "Status"])
        for r in rows:
            ws.append(
                [
                    r.regulation_code,
                    r.code,
                    r.title,
                    r.course_type,
                    r.lecture_hours,
                    r.tutorial_hours,
                    r.practical_hours,
                    float(r.credits),
                    r.department_code,
                    r.scheme_code,
                    r.status,
                ]
            )
        for col, width in zip("ABCDEFGHIJK", (12, 12, 44, 18, 5, 5, 5, 8, 12, 16, 10), strict=True):
            ws.column_dimensions[col].width = width
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()
