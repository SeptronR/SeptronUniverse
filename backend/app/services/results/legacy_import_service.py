# mypy: disable-error-code="arg-type,var-annotated"
"""Legacy result import — Prompts/15 §15.6 ``legacy_import_service`` (``results.legacy_import``).

Upload (XLSX or CSV) with a column mapping (``reg_no, course_code, course_title, credits, cia, ese, total, grade, gp,
attempt``; defaults to the same header names) → ``validate`` (student of the batch exists, grade in the batch's scale,
course exists in the batch's regulation or will be created as a ``retired`` course flagged ``LEGACY``) → ``apply``:
a ``legacy_import`` run published in one step (no verification chain — audited), rows ``attempt_type='legacy'``, term
results computed from the imported rows (term records are created when missing); ``rollback`` deletes the run's rows
when nothing newer references them (no later version supersedes them).
"""

import csv
import io
import uuid
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import UploadFile
from sqlalchemy import delete, func, select

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm, Batch, GradingScale, ProgramRegulation, Regulation
from app.models.curriculum import Course
from app.models.results import LegacyResultImport, ResultProcessingRun, StudentCourseResult, StudentTermResult
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.schemas.results import LegacyImportCreate, LegacyImportResponse, LegacyValidationReport
from app.services.exams.common import now_utc
from app.services.results import compute as C
from app.services.results.result_service import ResultBase, TermResultBuilder, hash_of

FIELDS = ("reg_no", "course_code", "course_title", "credits", "cia", "ese", "total", "grade", "gp", "attempt")


def _dec(v: Any) -> Decimal | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return Decimal(str(v).strip())
    except InvalidOperation:
        return None


class LegacyImportService(ResultBase):
    async def _imp(self, iid: uuid.UUID, *, for_update: bool = False) -> LegacyResultImport:
        q = select(LegacyResultImport).where(
            LegacyResultImport.id == iid, LegacyResultImport.institution_id == self.inst
        )
        if for_update:
            q = q.with_for_update()
        imp = (await self.db.execute(q)).scalar_one_or_none()
        if imp is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Import not found")
        return imp

    def _out(self, imp: LegacyResultImport) -> LegacyImportResponse:
        return LegacyImportResponse.model_validate(imp, from_attributes=True)

    async def create(self, body: LegacyImportCreate, upload: UploadFile | None) -> LegacyImportResponse:
        from app.services.file_service import FileService

        batch = (
            await self.db.execute(select(Batch).where(Batch.id == body.batch_id, Batch.institution_id == self.inst))
        ).scalar_one_or_none()
        if batch is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Batch not found")
        key = body.file_url
        if upload is not None:
            saved = await FileService(self.db).save(
                upload,
                "results/legacy",
                allowed_types=(
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "text/csv",
                    "text/plain",
                ),
                institution_id=self.inst,
            )
            key = saved.key
        if not key:
            raise APIError(422, ErrorCode.VALIDATION, "Upload the file or give its stored key")
        imp = LegacyResultImport(
            institution_id=self.inst,
            batch_id=batch.id,
            term_number=body.term_number,
            file_url=key,
            mapping=body.mapping or {f: f for f in FIELDS},
            status="uploaded",
            requested_by=self.actor_id,
        )
        self.db.add(imp)
        await self.db.flush()
        await self._audit(
            "legacy_upload", "legacy_result_import", imp.id, None, {"batch": str(batch.id), "term": body.term_number}
        )
        return self._out(imp)

    async def get(self, iid: uuid.UUID) -> LegacyImportResponse:
        return self._out(await self._imp(iid))

    async def _rows(self, imp: LegacyResultImport) -> list[dict[str, Any]]:
        from app.core.files import storage

        data = await storage.get(imp.file_url)
        if not data:
            raise APIError(422, ErrorCode.VALIDATION, "The uploaded file could not be read")
        # the mapping is stored as field → column; read it as column → field
        col_to_field = {col: field for field, col in (imp.mapping or {}).items()} or {f: f for f in FIELDS}
        records: list[dict[str, Any]] = []
        if data[:2] == b"PK":
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.active
            it = ws.iter_rows(values_only=True)
            header = [str(h).strip() if h is not None else "" for h in next(it, [])]
            for vals in it:
                if not any(v is not None and str(v).strip() for v in vals):
                    continue
                records.append({col_to_field.get(h, h): v for h, v in zip(header, vals, strict=False)})
        else:
            text = data.decode("utf-8-sig", errors="replace")
            for row in csv.DictReader(io.StringIO(text)):
                records.append({col_to_field.get(k.strip(), k.strip()): v for k, v in row.items() if k})
        return records

    async def _context(self, imp: LegacyResultImport) -> tuple[Batch, uuid.UUID, list[dict[str, Any]]]:
        batch = (await self.db.execute(select(Batch).where(Batch.id == imp.batch_id))).scalar_one()
        reg = (
            await self.db.execute(
                select(ProgramRegulation.regulation_id).where(ProgramRegulation.id == batch.program_regulation_id)
            )
        ).scalar_one()
        scale_id = (
            await self.db.execute(select(Regulation.grading_scale_id).where(Regulation.id == reg))
        ).scalar_one_or_none()
        ranges: list[dict[str, Any]] = C.DEFAULT_RANGES
        if scale_id:
            g = (await self.db.execute(select(GradingScale).where(GradingScale.id == scale_id))).scalar_one_or_none()
            if g is not None:
                ranges = g.ranges
        return batch, reg, ranges

    async def validate(self, iid: uuid.UUID) -> LegacyImportResponse:
        imp = await self._imp(iid, for_update=True)
        if imp.status not in ("uploaded", "validated"):
            raise APIError(409, ErrorCode.CONFLICT, f"A {imp.status} import cannot be validated again")
        batch, reg, ranges = await self._context(imp)
        rows = await self._rows(imp)
        regs = {
            r.upper(): e
            for r, e in (
                await self.db.execute(
                    select(Student.registration_number, StudentProgramEnrollment.id)
                    .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                    .where(StudentProgramEnrollment.batch_id == batch.id)
                )
            ).all()
        }
        codes = set(
            (
                await self.db.execute(
                    select(Course.code).where(Course.regulation_id == reg, Course.institution_id == self.inst)
                )
            ).scalars()
        )
        grades = {str(r.get("grade")) for r in ranges} | {"AB", "W", "WH", "MP", "I"}
        errors: list[dict[str, Any]] = []
        to_create: set[str] = set()
        students: set[str] = set()
        for i, r in enumerate(rows, start=2):
            reg_no = str(r.get("reg_no") or "").strip().upper()
            code = str(r.get("course_code") or "").strip()
            grade = str(r.get("grade") or "").strip().upper()
            if reg_no not in regs:
                errors.append({"row": i, "field": "reg_no", "value": reg_no, "error": "not a student of the batch"})
                continue
            if not code:
                errors.append({"row": i, "field": "course_code", "error": "missing"})
                continue
            if grade and grade not in {g.upper() for g in grades}:
                errors.append({"row": i, "field": "grade", "value": grade, "error": "not in the grading scale"})
                continue
            if _dec(r.get("credits")) is None:
                errors.append({"row": i, "field": "credits", "value": r.get("credits"), "error": "not a number"})
                continue
            if code not in codes:
                to_create.add(code)
            students.add(reg_no)
        report = LegacyValidationReport(
            rows=len(rows),
            valid=len(rows) - len(errors),
            errors=errors[:500],
            students=len(students),
            courses_to_create=sorted(to_create),
        )
        imp.validation_report = report.model_dump(mode="json")
        imp.status = "validated"
        await self.db.flush()
        return self._out(imp)

    async def apply(self, iid: uuid.UUID) -> LegacyImportResponse:
        imp = await self._imp(iid, for_update=True)
        if imp.status != "validated":
            raise APIError(409, ErrorCode.CONFLICT, "Validate the import before applying it")
        batch, reg, ranges = await self._context(imp)
        rows = await self._rows(imp)
        bad = {e["row"] for e in (imp.validation_report or {}).get("errors", [])}
        enrolments = {
            s.upper(): e
            for s, e in (
                await self.db.execute(
                    select(Student.registration_number, StudentProgramEnrollment)
                    .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                    .where(StudentProgramEnrollment.batch_id == batch.id)
                )
            ).all()
        }
        courses = {
            c.code: c
            for c in (
                await self.db.execute(
                    select(Course).where(Course.regulation_id == reg, Course.institution_id == self.inst)
                )
            ).scalars()
        }
        # term of the legacy term number: an existing term record of the batch, else the earliest term of the college
        term_id = (
            await self.db.execute(
                select(StudentTermRecord.term_id)
                .join(
                    StudentProgramEnrollment,
                    StudentProgramEnrollment.id == StudentTermRecord.student_program_enrollment_id,
                )
                .where(StudentProgramEnrollment.batch_id == batch.id, StudentTermRecord.term_number == imp.term_number)
                .limit(1)
            )
        ).scalar_one_or_none()
        if term_id is None:
            term_id = (
                await self.db.execute(
                    select(AcademicTerm.id)
                    .where(AcademicTerm.institution_id == self.inst)
                    .order_by(AcademicTerm.start_date)
                    .offset(max(imp.term_number - 1, 0))
                    .limit(1)
                )
            ).scalar_one_or_none()
        if term_id is None:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "No academic term to attach the legacy results to")
        dept = (
            await self.db.execute(
                select(StudentProgramEnrollment.department_id)
                .where(StudentProgramEnrollment.batch_id == batch.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        run = ResultProcessingRun(
            institution_id=self.inst,
            scope={"batch_ids": [str(batch.id)], "term_number": imp.term_number, "legacy_import_id": str(imp.id)},
            run_type="legacy_import",
            status="computing",
            triggered_by=self.actor_id,
            config_snapshot={"legacy": True, "ranges": ranges},
        )
        self.db.add(run)
        await self.db.flush()
        new_rows: list[StudentCourseResult] = []
        enr_by_id: dict[uuid.UUID, StudentProgramEnrollment] = {}
        existing_versions: dict[tuple[uuid.UUID, uuid.UUID, int], int] = defaultdict(int)
        for e, cid, att, v in (
            await self.db.execute(
                select(
                    StudentCourseResult.student_program_enrollment_id,
                    StudentCourseResult.course_id,
                    StudentCourseResult.attempt_number,
                    func.max(StudentCourseResult.version),
                )
                .where(
                    StudentCourseResult.student_program_enrollment_id.in_(
                        [e.id for e in enrolments.values()] or [uuid.uuid4()]
                    )
                )
                .group_by(
                    StudentCourseResult.student_program_enrollment_id,
                    StudentCourseResult.course_id,
                    StudentCourseResult.attempt_number,
                )
            )
        ).all():
            existing_versions[(e, cid, att)] = int(v)
        now = now_utc()
        for i, r in enumerate(rows, start=2):
            if i in bad:
                continue
            enr = enrolments.get(str(r.get("reg_no") or "").strip().upper())
            if enr is None:
                continue
            code = str(r.get("course_code") or "").strip()
            c = courses.get(code)
            credits = _dec(r.get("credits")) or Decimal(0)
            if c is None and dept is not None:
                c = Course(
                    institution_id=self.inst,
                    college_id=batch.college_id,
                    department_id=dept,
                    regulation_id=reg,
                    code=code[:30],
                    title=str(r.get("course_title") or f"{code} (legacy)")[:200],
                    short_title="LEGACY",
                    course_type="core",
                    credits=credits,
                    status="retired",
                )
                self.db.add(c)
                await self.db.flush()
                courses[code] = c
            if c is None:
                continue
            grade = str(r.get("grade") or "").strip().upper() or None
            gp = _dec(r.get("gp"))
            if gp is None and grade:
                gp = C.points_of(grade, ranges)
            fail_g, _ = C.fail_grade(ranges)
            status = {"AB": "absent", "W": "withdrawn", "WH": "withheld", "MP": "malpractice", "I": "incomplete"}.get(
                grade or "", "fail" if grade == fail_g.upper() else "pass"
            )
            att = int(_dec(r.get("attempt")) or 1)
            version = existing_versions[(enr.id, c.id, att)] + 1
            existing_versions[(enr.id, c.id, att)] = version
            total = _dec(r.get("total"))
            row = StudentCourseResult(
                institution_id=self.inst,
                college_id=enr.college_id,
                student_program_enrollment_id=enr.id,
                term_id=term_id,
                course_id=c.id,
                attempt_number=att,
                attempt_type="legacy",
                credits=credits,
                cia_marks=_dec(r.get("cia")),
                ese_marks=_dec(r.get("ese")),
                total_marks=total,
                percentage=total if total is not None and total <= 100 else None,
                letter_grade=grade[:3] if grade else None,
                grade_point=gp,
                result_status=status,
                counts_toward_cgpa=status not in ("withdrawn",),
                version=version,
                run_id=run.id,
                status="published",
                published_at=now,
            )
            row.hash = hash_of(row)
            self.db.add(row)
            new_rows.append(row)
            enr_by_id[enr.id] = enr
        await self.db.flush()
        # term records for the legacy term (created when missing)
        have = {
            e
            for (e,) in (
                await self.db.execute(
                    select(StudentTermRecord.student_program_enrollment_id).where(
                        StudentTermRecord.student_program_enrollment_id.in_(list(enr_by_id) or [uuid.uuid4()]),
                        StudentTermRecord.term_id == term_id,
                    )
                )
            ).all()
        }
        for e in enr_by_id.values():
            if e.id not in have:
                self.db.add(
                    StudentTermRecord(
                        institution_id=self.inst,
                        student_program_enrollment_id=e.id,
                        term_id=term_id,
                        term_number=imp.term_number,
                        status="completed",
                    )
                )
        await self.db.flush()
        rules = {}
        from app.services.academics.rules import RulesResolver

        rules[str(batch.program_regulation_id)] = await RulesResolver(self.db).for_program_regulation(
            batch.program_regulation_id
        )
        await TermResultBuilder(self).build(run, new_rows, enr_by_id, {"rules": rules})
        for t in (await self.db.execute(select(StudentTermResult).where(StudentTermResult.run_id == run.id))).scalars():
            t.status, t.published_at = "published", now
            rec = (
                await self.db.execute(select(StudentTermRecord).where(StudentTermRecord.id == t.student_term_record_id))
            ).scalar_one()
            rec.sgpa, rec.cgpa, rec.credits_earned, rec.credits_registered = (
                t.sgpa,
                t.cgpa,
                t.credits_earned,
                t.credits_registered,
            )
            rec.result_status = "pass" if t.backlog_count == 0 else "fail"
            e = enr_by_id.get(rec.student_program_enrollment_id)
            if e is not None and (e.cgpa is None or rec.term_number >= imp.term_number):
                e.cgpa, e.credits_earned = t.cgpa, t.cumulative_credits or e.credits_earned
        run.status, run.published_at = "published", now
        run.stats = {"rows": len(new_rows), "students": len(enr_by_id)}
        run.checksum = C.checksum([x.hash or "" for x in new_rows])
        imp.status, imp.run_id = "applied", run.id
        await self.db.flush()
        await self._audit(
            "legacy_apply", "legacy_result_import", imp.id, None, {"rows": len(new_rows), "run": str(run.id)}
        )
        await self._emit(
            "legacy.imported", {"import_id": str(imp.id), "rows": len(new_rows)}, "legacy_result_import", imp.id
        )
        return self._out(imp)

    async def rollback(self, iid: uuid.UUID) -> LegacyImportResponse:
        imp = await self._imp(iid, for_update=True)
        if imp.status != "applied" or imp.run_id is None:
            raise APIError(409, ErrorCode.CONFLICT, "Only an applied import can be rolled back")
        ids = select(StudentCourseResult.id).where(StudentCourseResult.run_id == imp.run_id)
        newer = (
            await self.db.execute(
                select(func.count()).select_from(StudentCourseResult).where(StudentCourseResult.supersedes_id.in_(ids))
            )
        ).scalar_one()
        if newer:
            raise APIError(409, ErrorCode.CONFLICT, "Newer results reference the imported rows; they cannot be removed")
        # published rows are immutable for updates, not deletes — the run's rows go with the run
        await self.db.execute(delete(StudentTermResult).where(StudentTermResult.run_id == imp.run_id))
        n = (
            await self.db.execute(delete(StudentCourseResult).where(StudentCourseResult.run_id == imp.run_id))
        ).rowcount  # type: ignore[attr-defined]
        run = (
            await self.db.execute(select(ResultProcessingRun).where(ResultProcessingRun.id == imp.run_id))
        ).scalar_one()
        run.status = "rolled_back"
        imp.status = "rolled_back"
        await self.db.flush()
        await self._audit(
            "legacy_rollback",
            "legacy_result_import",
            imp.id,
            {"status": "applied"},
            {"status": "rolled_back", "rows": n},
        )
        return self._out(imp)
