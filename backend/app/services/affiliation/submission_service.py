"""College data submissions — Prompts/34 §34.6 ``submission_service`` + ``submission_repository`` (system-data
extractors) {affiliation.data_submissions}.

1. **Windows** per type from term / session dates (``affiliation.submission_windows``: ``term_start+30d``,
   ``last_instruction_date+7d``, ``session_registration_end+2d``); autonomous colleges submit only the non-exam types.
2. **Preparation**: from system data (extractor per type with a record count) or a file upload (CSV / XLSX read through
   the storage backend, header mapping) for colleges not on the system; **validation** (``submission_validation_rules``:
   CIA for every registered paper, marks within range, eligibility decided, faculty list covers offerings) → report.
3. **Review** ``draft → submitted`` (college, 422 ``VALIDATION_ERRORS`` while errors remain) ``→ verified`` (university
   verifier) ``→ accepted`` (COE for exam types, registrar for the rest) ``→ locked`` (freezes the college's source data:
   Phase 13 CIA edits / Phase 11 eligibility / Phase 14 registrations answer 409 ``LOCKED``), ``returned`` with remarks
   (the college fixes and resubmits — the version increments and the earlier version is kept), ``unlock`` (COE, reason,
   audited). The unique key is ``(college_id, term_id, submission_type)`` so a resubmission reuses the row.
4. **Gating**: ``college_status(session)`` = Phase 15 per-college gating (``gates.session_gating``); compliance dashboard
   (on-time %, returns) per college; reminders before the due date and escalation after.
"""

import csv
import io
import re
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, text

from app.core.errors import APIError, ErrorCode
from app.enums.affiliation import AUTONOMOUS_SUBMISSIONS, EXAM_SUBMISSIONS, SubmissionType
from app.models.affiliation import CollegeDataSubmission
from app.models.exams import ExamSession
from app.schemas.affiliation import (
    CollegeGatingStatus,
    ComplianceRow,
    SubmissionAction,
    SubmissionCreate,
    SubmissionImport,
    SubmissionOut,
    SubmissionWindowOut,
    ValidationIssue,
    ValidationReport,
)
from app.services.affiliation.common import AffiliationBase, forbidden, not_found, now_utc, pairs, rule
from app.services.affiliation.gates import session_gating

ENTITY = "college_data_submission"
REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "student_registrations": ("roll_number", "name", "program_code"),
    "course_registrations": ("roll_number", "course_code"),
    "cia_marks": ("roll_number", "course_code", "cia_marks", "cia_max"),
    "attendance_eligibility": ("roll_number", "course_code", "attendance_pct", "decision"),
    "practical_marks": ("roll_number", "course_code", "marks", "max_marks"),
    "exam_registrations": ("roll_number", "course_code"),
    "internal_faculty_list": ("employee_id", "name", "department"),
}
PRACTICAL_TYPES = ("lab", "integrated_lab", "practical", "project")


def _offset(spec: str) -> tuple[str, int]:
    m = re.fullmatch(r"\s*([a-z_]+)\s*([+-]\s*\d+)\s*d\s*", spec or "")
    if not m:
        return "term_start", 30
    return m.group(1), int(m.group(2).replace(" ", ""))


class SubmissionService(AffiliationBase):
    # ---- rows / visibility --------------------------------------------------------------------------------------------
    async def _row(self, sid: uuid.UUID, *, lock: bool = False) -> CollegeDataSubmission:
        stmt = select(CollegeDataSubmission).where(
            CollegeDataSubmission.id == sid, CollegeDataSubmission.institution_id == self.inst
        )
        if lock:
            stmt = stmt.with_for_update()
        s = (await self.db.execute(stmt)).scalar_one_or_none()
        if s is None:
            raise not_found("Submission")
        if not (self.system() or self.office_reader() or self.exam_office() or s.college_id in self.my_college_ids()):
            raise not_found("Submission")
        return s

    def _college_writer(self, s: CollegeDataSubmission) -> bool:
        if self.system():
            return True
        p = self.principal
        if s.submission_type in EXAM_SUBMISSIONS and self.college_writer(s.college_id, "submit"):
            return True
        return self.college_writer(s.college_id, "submit") and (
            p.has("affiliation", "apply") or p.has("affiliation", "manage") or s.submission_type in EXAM_SUBMISSIONS
        )

    # ---- windows ------------------------------------------------------------------------------------------------------
    async def _due(self, stype: str, term: Any, session: ExamSession | None) -> date | None:
        windows = await self.aff_setting("submission_windows") or {}
        anchor, days = _offset(str(windows.get(stype) or "term_start+30d"))
        base: date | None
        if anchor == "term_start":
            base = term.start_date
        elif anchor == "last_instruction_date":
            base = term.last_instruction_date or term.end_date
        elif anchor == "session_registration_end":
            base = session.registration_end.date() if session and session.registration_end else term.end_date
        else:
            base = term.end_date
        return base + timedelta(days=days) if base else None

    async def _central_session(self, term_id: uuid.UUID) -> ExamSession | None:
        return (
            await self.db.execute(
                select(ExamSession)
                .where(
                    ExamSession.institution_id == self.inst,
                    ExamSession.term_id == term_id,
                    ExamSession.college_id.is_(None),
                    ExamSession.deleted_at.is_(None),
                )
                .order_by(ExamSession.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def windows(self, term_id: uuid.UUID, college_id: uuid.UUID | None) -> list[SubmissionWindowOut]:
        term = await self.term(term_id)
        cid = college_id or (self.my_college_ids()[0] if self.my_college_ids() else None)
        c = await self.visible_college(cid) if cid else None
        session = await self._central_session(term.id)
        today = await self.today()
        subs = {}
        if c is not None:
            subs = {
                s.submission_type: s
                for s in (
                    await self.db.execute(
                        select(CollegeDataSubmission).where(
                            CollegeDataSubmission.college_id == c.id, CollegeDataSubmission.term_id == term.id
                        )
                    )
                ).scalars()
            }
        out = []
        for st in SubmissionType:
            t = str(st)
            applies = c is None or c.college_type != "autonomous" or t in AUTONOMOUS_SUBMISSIONS
            due = await self._due(t, term, session)
            s = subs.get(t)
            if s is not None and s.status in ("accepted", "locked"):
                status = "closed"
            elif due is None or today < term.start_date:
                status = "upcoming"
            elif today > due:
                status = "overdue"
            elif (due - today).days <= 3:
                status = "due"
            else:
                status = "open"
            out.append(
                SubmissionWindowOut(
                    submission_type=t,
                    applies=applies,
                    opens_on=term.start_date,
                    due_on=due,
                    status=status,  # type: ignore[arg-type]
                    submission_id=s.id if s else None,
                    submission_status=s.status if s else None,
                    exam_related=t in EXAM_SUBMISSIONS,
                )
            )
        return out

    # ---- output -------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[CollegeDataSubmission]) -> list[SubmissionOut]:
        colleges = await self.colleges_map([r.college_id for r in rows])
        metas = await self.metas("sub", [r.id for r in rows])
        out = []
        for r in rows:
            m = metas.get(str(r.id)) or {}
            c = colleges.get(r.college_id)
            v = m.get("validation")
            out.append(
                SubmissionOut(
                    id=r.id,
                    college_id=r.college_id,
                    college_code=c.code if c else None,
                    college_name=c.name if c else None,
                    term_id=r.term_id,
                    exam_session_id=r.exam_session_id,
                    submission_type=r.submission_type,
                    status=r.status,
                    version=int(m.get("version") or 1),
                    source="file" if m.get("source") == "file" else "system",
                    record_count=r.record_count,
                    file_url=r.file_url,
                    submitted_by=r.submitted_by,
                    submitted_at=r.submitted_at,
                    verified_by=r.verified_by,
                    verified_at=r.verified_at,
                    remarks=r.remarks,
                    locked_at=r.locked_at,
                    due_on=date.fromisoformat(m["due_on"]) if m.get("due_on") else None,
                    late=bool(m.get("late")),
                    validation=ValidationReport(**v) if v else None,
                    timeline=list(m.get("timeline") or []),
                    versions=list(m.get("versions") or []),
                )
            )
        return out

    async def get(self, sid: uuid.UUID) -> SubmissionOut:
        return (await self.outs([await self._row(sid)]))[0]

    async def list_submissions(
        self,
        college_id: uuid.UUID | None,
        term_id: uuid.UUID | None,
        stype: str | None,
        status: str | None,
        scope: str | None,
    ) -> list[SubmissionOut]:
        stmt = select(CollegeDataSubmission).where(CollegeDataSubmission.institution_id == self.inst)
        if scope == "college" or not (self.system() or self.office_reader() or self.exam_office()):
            mine = self.my_college_ids()
            if not mine:
                return []
            stmt = stmt.where(CollegeDataSubmission.college_id.in_(mine))
        if college_id:
            stmt = stmt.where(CollegeDataSubmission.college_id == college_id)
        if term_id:
            stmt = stmt.where(CollegeDataSubmission.term_id == term_id)
        if stype:
            stmt = stmt.where(CollegeDataSubmission.submission_type == stype)
        if status:
            stmt = stmt.where(CollegeDataSubmission.status == status)
        rows = list(
            (
                await self.db.execute(
                    stmt.order_by(CollegeDataSubmission.college_id, CollegeDataSubmission.submission_type).limit(2000)
                )
            ).scalars()
        )
        return await self.outs(rows)

    # ---- create -------------------------------------------------------------------------------------------------------
    async def create(self, body: SubmissionCreate) -> SubmissionOut:
        self.require_writer()
        c = await self.college(body.college_id)
        if not (self.office() or self.college_writer(c.id, "submit")):
            raise forbidden("affiliation:submit for the college required")
        stype = str(body.submission_type)
        if c.college_type == "autonomous" and stype not in AUTONOMOUS_SUBMISSIONS:
            raise rule("Autonomous colleges conduct their own examinations", "NOT_APPLICABLE", 422)
        term = await self.term(body.term_id)
        existing = (
            await self.db.execute(
                select(CollegeDataSubmission)
                .where(
                    CollegeDataSubmission.college_id == c.id,
                    CollegeDataSubmission.term_id == term.id,
                    CollegeDataSubmission.submission_type == stype,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        session = None
        if body.exam_session_id:
            session = (
                await self.db.execute(select(ExamSession).where(ExamSession.id == body.exam_session_id))
            ).scalar_one_or_none()
        elif stype in EXAM_SUBMISSIONS:
            session = await self._central_session(term.id)
        if existing is not None:
            if existing.status not in ("draft", "returned"):
                raise rule(f"The {stype} submission is already {existing.status}", "DUPLICATE_SUBMISSION")
            s = existing
        else:
            s = CollegeDataSubmission(
                institution_id=self.inst,
                college_id=c.id,
                term_id=term.id,
                submission_type=stype,
                status="draft",
                exam_session_id=session.id if session else None,
            )
            self.db.add(s)
            await self.db.flush()
        if body.file_url:
            s.file_url = body.file_url
        meta = await self.meta("sub", s.id)
        due = await self._due(stype, term, session)
        meta.setdefault("version", 1)
        meta["source"] = "file" if body.file_url else meta.get("source", "system")
        meta["due_on"] = due.isoformat() if due else None
        await self.put_meta("sub", s.id, meta)
        await self.db.flush()
        await self.timeline("sub", s.id, "created" if existing is None else "reopened", source=meta["source"])
        await self._emit(
            "affiliation.submission_created",
            {"submission_id": str(s.id), "college_id": str(c.id), "type": stype},
            ENTITY,
            s.id,
        )
        return (await self.outs([s]))[0]

    # ---- extract (system data) ----------------------------------------------------------------------------------------
    async def _scalar(self, sql: str, params: dict[str, Any]) -> int:
        return int((await self.db.execute(text(sql), params)).scalar_one() or 0)

    async def extract_count(self, s: CollegeDataSubmission) -> tuple[int, dict[str, Any]]:
        p = {"c": s.college_id, "t": s.term_id, "i": self.inst, "x": s.exam_session_id}
        st = s.submission_type
        if st == "student_registrations":
            n = await self._scalar(
                "SELECT count(*) FROM student_term_records r JOIN student_program_enrollments e "
                "ON e.id = r.student_program_enrollment_id WHERE r.institution_id = :i AND r.term_id = :t "
                "AND e.college_id = :c AND r.status NOT IN ('withdrawn', 'on_break')",
                p,
            )
        elif st == "course_registrations":
            n = await self._scalar(
                "SELECT count(*) FROM course_registrations WHERE institution_id = :i AND college_id = :c "
                "AND term_id = :t AND status IN ('approved', 'locked')",
                p,
            )
        elif st in ("cia_marks", "practical_marks"):
            practical = "AND co.course_type IN ('lab', 'integrated_lab', 'practical', 'project')"
            n = await self._scalar(
                "SELECT count(*) FROM cia_consolidations x JOIN course_offerings o ON o.id = x.offering_id "
                "JOIN courses co ON co.id = o.course_id WHERE x.institution_id = :i AND o.college_id = :c "
                f"AND o.term_id = :t AND x.status = 'submitted_to_university' {practical if st == 'practical_marks' else ''}",
                p,
            )
        elif st == "attendance_eligibility":
            n = await self._scalar(
                "SELECT count(*) FROM term_eligibility te JOIN student_term_records r ON r.id = te.student_term_record_id "
                "JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id "
                "WHERE te.institution_id = :i AND r.term_id = :t AND e.college_id = :c AND te.decision <> 'pending'",
                p,
            )
        elif st == "exam_registrations":
            n = await self._scalar(
                "SELECT count(*) FROM exam_registrations g JOIN exam_sessions es ON es.id = g.exam_session_id "
                "WHERE g.institution_id = :i AND g.college_id = :c AND g.status = 'confirmed' "
                "AND (es.id = :x OR (CAST(:x AS uuid) IS NULL AND es.term_id = :t))",
                p,
            )
        else:  # internal_faculty_list
            n = await self._scalar(
                "SELECT count(*) FROM staff WHERE institution_id = :i AND college_id = :c AND status = 'active' "
                "AND staff_category = 'teaching' AND deleted_at IS NULL",
                p,
            )
        return n, {"extracted_at": now_utc().isoformat(), "type": st}

    async def extract(self, sid: uuid.UUID) -> SubmissionOut:
        s = await self._row(sid, lock=True)
        self.require_writer()
        if not (self.office() or self._college_writer(s)):
            raise forbidden("affiliation:submit for the college required")
        if s.status not in ("draft", "returned"):
            raise rule(f"A {s.status} submission cannot be re-extracted", "INVALID_TRANSITION")
        n, info = await self.extract_count(s)
        s.record_count = n
        meta = await self.meta("sub", s.id)
        meta.update({"source": "system", "extract": info})
        await self.put_meta("sub", s.id, meta)
        await self.db.flush()
        await self.timeline("sub", s.id, "extracted", records=n)
        return (await self.outs([s]))[0]

    # ---- import (file) ------------------------------------------------------------------------------------------------
    async def _read_rows(self, url: str) -> list[dict[str, str]] | None:
        from app.core.files import get_storage

        key = url.split("?", 1)[0]
        m = re.search(r"([0-9a-f-]{36}/.+)$", key)
        if not m:
            return None
        try:
            data = await get_storage().get(m.group(1))
        except Exception:  # noqa: BLE001 - not a storage object (external link): counted from the mapping
            return None
        if key.endswith(".xlsx"):
            try:
                from openpyxl import load_workbook

                wb = load_workbook(io.BytesIO(data), read_only=True)
                ws = wb.active
                it = ws.iter_rows(values_only=True)
                head = [str(h or "").strip().lower() for h in next(it)]
                return [
                    {head[i]: str(v if v is not None else "") for i, v in enumerate(r) if i < len(head)} for r in it
                ]
            except Exception:  # noqa: BLE001
                return None
        try:
            return [
                {str(k).strip().lower(): str(v or "") for k, v in r.items()}
                for r in csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
            ]
        except (UnicodeDecodeError, csv.Error):
            return None

    async def import_file(self, sid: uuid.UUID, body: SubmissionImport) -> SubmissionOut:
        s = await self._row(sid, lock=True)
        self.require_writer()
        if not (self.office() or self._college_writer(s)):
            raise forbidden("affiliation:submit for the college required")
        if s.status not in ("draft", "returned"):
            raise rule(f"A {s.status} submission cannot be re-imported", "INVALID_TRANSITION")
        rows = await self._read_rows(body.file_url)
        s.file_url = body.file_url
        meta = await self.meta("sub", s.id)
        meta.update({"source": "file", "mapping": body.mapping})
        warnings: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        if rows is None:
            warnings.append({"code": "FILE_UNREAD", "message": "The file could not be read; the verifier checks it"})
            s.record_count = s.record_count or 0
        else:
            need = REQUIRED_COLUMNS.get(s.submission_type, ())
            cols = {body.mapping.get(k, k) for k in need}
            have = set(rows[0].keys()) if rows else set()
            for col in sorted(cols - have):
                errors.append({"code": "MISSING_COLUMN", "message": f"Column {col} is missing"})
            for i, r in enumerate(rows, start=2):
                if not any(v.strip() for v in r.values()):
                    warnings.append({"code": "EMPTY_ROW", "message": "Empty row", "row": i})
            s.record_count = len(rows)
        meta["import_issues"] = {"errors": errors, "warnings": warnings}
        await self.put_meta("sub", s.id, meta)
        await self.db.flush()
        await self.timeline("sub", s.id, "imported", records=s.record_count)
        return (await self.outs([s]))[0]

    # ---- validation ---------------------------------------------------------------------------------------------------
    async def validate(self, sid: uuid.UUID) -> ValidationReport:  # noqa: C901
        s = await self._row(sid, lock=True)
        rules_ = await self.aff_setting("submission_validation_rules") or {}
        meta = await self.meta("sub", s.id)
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        p = {"c": s.college_id, "t": s.term_id, "i": self.inst}
        if meta.get("source") == "file":
            issues = meta.get("import_issues") or {}
            errors += [ValidationIssue(**e) for e in issues.get("errors") or []]
            warnings += [ValidationIssue(**w) for w in issues.get("warnings") or []]
        elif s.submission_type in ("cia_marks", "practical_marks") and rules_.get("cia_complete", True):
            practical = s.submission_type == "practical_marks"
            rows = (
                await self.db.execute(
                    text(
                        "SELECT co.code, o.id, count(DISTINCT cr.student_program_enrollment_id) AS regs, "
                        "count(DISTINCT x.student_program_enrollment_id) FILTER (WHERE x.status = 'submitted_to_university') AS cia "
                        "FROM course_offerings o JOIN courses co ON co.id = o.course_id "
                        "JOIN course_registration_items i ON i.offering_id = o.id AND i.status IN ('confirmed', 'selected') "
                        "JOIN course_registrations cr ON cr.id = i.registration_id "
                        "LEFT JOIN cia_consolidations x ON x.offering_id = o.id "
                        "AND x.student_program_enrollment_id = cr.student_program_enrollment_id "
                        "WHERE o.institution_id = :i AND o.college_id = :c AND o.term_id = :t AND o.is_active "
                        + (
                            "AND co.course_type IN ('lab', 'integrated_lab', 'practical', 'project') "
                            if practical
                            else ""
                        )
                        + "GROUP BY co.code, o.id"
                    ),
                    p,
                )
            ).all()
            for code, _oid, regs, cia in rows:
                if int(cia or 0) < int(regs or 0):
                    errors.append(
                        ValidationIssue(
                            code="CIA_MISSING",
                            message=f"{code}: CIA submitted for {int(cia or 0)} of {int(regs)} registered students",
                            ref=str(code),
                        )
                    )
            if rules_.get("marks_within_max", True):
                bad = await self._scalar(
                    "SELECT count(*) FROM cia_consolidations x JOIN course_offerings o ON o.id = x.offering_id "
                    "WHERE x.institution_id = :i AND o.college_id = :c AND o.term_id = :t AND (x.cia_scaled < 0 OR x.cia_total < 0)",
                    p,
                )
                if bad:
                    errors.append(ValidationIssue(code="MARKS_OUT_OF_RANGE", message=f"{bad} CIA rows below zero"))
        elif s.submission_type == "attendance_eligibility" and rules_.get("eligibility_decided", True):
            pending = await self._scalar(
                "SELECT count(*) FROM term_eligibility te JOIN student_term_records r ON r.id = te.student_term_record_id "
                "JOIN student_program_enrollments e ON e.id = r.student_program_enrollment_id "
                "WHERE te.institution_id = :i AND r.term_id = :t AND e.college_id = :c AND te.decision = 'pending'",
                p,
            )
            if pending:
                errors.append(
                    ValidationIssue(code="ELIGIBILITY_PENDING", message=f"{pending} eligibility decisions pending")
                )
        elif s.submission_type == "internal_faculty_list" and rules_.get("faculty_matches_offerings", True):
            uncovered = await self._scalar(
                "SELECT count(*) FROM course_offerings o WHERE o.institution_id = :i AND o.college_id = :c "
                "AND o.term_id = :t AND o.is_active AND o.coordinator_staff_id IS NULL",
                p,
            )
            if uncovered:
                warnings.append(
                    ValidationIssue(code="OFFERING_UNSTAFFED", message=f"{uncovered} offerings without a coordinator")
                )
        if not s.record_count:
            warnings.append(ValidationIssue(code="NO_RECORDS", message="No records extracted / imported yet"))
        report = ValidationReport(
            errors=errors,
            warnings=warnings,
            summary={"records": s.record_count or 0, "errors": len(errors), "warnings": len(warnings)},
            validated_at=now_utc(),
        )
        meta["validation"] = report.model_dump(mode="json")
        await self.put_meta("sub", s.id, meta)
        await self.timeline("sub", s.id, "validated", errors=len(errors), warnings=len(warnings))
        return report

    async def report(self, sid: uuid.UUID) -> ValidationReport:
        s = await self._row(sid)
        v = (await self.meta("sub", s.id)).get("validation")
        return ValidationReport(**v) if v else ValidationReport(summary={"records": s.record_count or 0})

    # ---- review state machine -----------------------------------------------------------------------------------------
    def _acceptor(self, s: CollegeDataSubmission) -> bool:
        if s.submission_type in EXAM_SUBMISSIONS:
            return self.exam_office()
        return self.office()

    async def action(self, sid: uuid.UUID, body: SubmissionAction) -> SubmissionOut:  # noqa: C901, PLR0912
        s = await self._row(sid, lock=True)
        self.require_writer()
        meta = await self.meta("sub", s.id)
        old = s.status
        now = now_utc()
        today = await self.today()
        act = body.action
        if act == "submit":
            if not (self.office() or self._college_writer(s)):
                raise forbidden("affiliation:submit for the college required")
            if s.status not in ("draft", "returned"):
                raise rule(f"A {s.status} submission cannot be submitted", "INVALID_TRANSITION")
            report = await self.validate(s.id)
            if report.errors:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "The submission has validation errors",
                    {"code": "VALIDATION_ERRORS", "errors": [e.model_dump() for e in report.errors][:50]},
                )
            meta = await self.meta("sub", s.id)
            if s.status == "returned":
                versions = list(meta.get("versions") or [])
                versions.append(
                    {
                        "version": int(meta.get("version") or 1),
                        "record_count": s.record_count,
                        "file_url": s.file_url,
                        "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
                        "returned_remarks": s.remarks,
                    }
                )
                meta["versions"] = versions
                meta["version"] = int(meta.get("version") or 1) + 1
            due = meta.get("due_on")
            meta["late"] = bool(due and today > date.fromisoformat(due))
            s.status, s.submitted_by, s.submitted_at = "submitted", self.actor_id, now
        elif act == "verify":
            if not self.verifier():
                raise forbidden("affiliation:verify_submission required")
            if s.status != "submitted":
                raise rule(f"A {s.status} submission cannot be verified", "INVALID_TRANSITION")
            s.status, s.verified_by, s.verified_at = "verified", self.actor_id, now
        elif act == "return":
            if not (self.verifier() or self._acceptor(s)):
                raise forbidden("affiliation:verify_submission required")
            if s.status not in ("submitted", "verified"):
                raise rule(f"A {s.status} submission cannot be returned", "INVALID_TRANSITION")
            if not body.remarks:
                raise APIError(422, ErrorCode.VALIDATION, "Remarks are required to return", {"field": "remarks"})
            s.status = "returned"
            meta["returns"] = int(meta.get("returns") or 0) + 1
        elif act == "accept":
            if not self._acceptor(s):
                raise forbidden(
                    "The COE (exams:configure) accepts exam submissions; the registrar (affiliation:manage) the rest"
                )
            if s.status != "verified":
                raise rule(f"A {s.status} submission cannot be accepted", "INVALID_TRANSITION")
            s.status = "accepted"
        elif act == "lock":
            if not self._acceptor(s):
                raise forbidden("Only the accepting office may lock")
            if s.status != "accepted":
                raise rule(f"A {s.status} submission cannot be locked", "INVALID_TRANSITION")
            s.status, s.locked_at = "locked", now
        else:  # unlock
            if not self.exam_office():
                raise forbidden("Only the COE may unlock a submission")
            if s.status != "locked":
                raise rule(f"A {s.status} submission is not locked", "INVALID_TRANSITION")
            if not body.remarks:
                raise APIError(422, ErrorCode.VALIDATION, "A reason is required to unlock", {"field": "remarks"})
            s.status, s.locked_at = "accepted", None
        if body.remarks:
            s.remarks = body.remarks
        await self._review_workflow(s, act, meta, body.remarks)
        await self.put_meta("sub", s.id, meta)
        await self.db.flush()
        await self.timeline("sub", s.id, act, remarks=body.remarks, status=s.status)
        await self._audit(
            f"submission_{act}", ENTITY, s.id, {"status": old}, {"status": s.status, "remarks": body.remarks}
        )
        event = {
            "submit": "affiliation.submission_submitted",
            "verify": "affiliation.submission_verified",
            "return": "affiliation.submission_returned",
            "accept": "affiliation.submission_accepted",
            "lock": "affiliation.submission_locked",
            "unlock": "affiliation.submission_unlocked",
        }[act]
        payload = {
            "submission_id": str(s.id),
            "college_id": str(s.college_id),
            "term_id": str(s.term_id),
            "type": s.submission_type,
            "status": s.status,
            "exam_session_id": str(s.exam_session_id) if s.exam_session_id else None,
        }
        await self._emit(event, payload, ENTITY, s.id)
        c = await self.college(s.college_id)
        label = s.submission_type.replace("_", " ")
        if act in ("return", "accept", "lock"):
            slugs = ("college_admin", "college_exam_coordinator")
            await self.notify_college(
                c,
                f"affiliation.submission_{'returned' if act == 'return' else 'accepted' if act == 'accept' else 'locked'}",
                {"type": label, "remarks": body.remarks or ""},
                *slugs,
            )
        if act in ("accept", "lock", "unlock") and s.exam_session_id:
            await self._emit(
                "affiliation.results_ungated" if act != "unlock" else "affiliation.results_gated",
                payload,
                ENTITY,
                s.id,
            )
        return (await self.outs([s]))[0]

    async def _review_workflow(
        self, s: CollegeDataSubmission, act: str, meta: dict[str, Any], remarks: str | None
    ) -> None:
        """``affiliation.submission_review`` tracks the university side (verifier → acceptor); the record decides."""
        wf = meta.get("workflow_instance_id")
        if act == "submit":
            acceptor = (
                await self.role_users("controller_of_examinations")
                if s.submission_type in EXAM_SUBMISSIONS
                else await self.role_users("registrar")
            )
            c = await self.college(s.college_id)
            new = await self.start_workflow(
                "affiliation.submission_review",
                ENTITY,
                s.id,
                f"{c.code} · {s.submission_type.replace('_', ' ')} (v{meta.get('version') or 1})",
                {"acceptor": str(acceptor[0]) if acceptor else None, "college_id": str(s.college_id)},
            )
            meta["workflow_instance_id"] = str(new) if new else None
        elif act in ("verify", "accept") and wf:
            try:
                async with self.db.begin_nested():
                    await self.acted_on_workflow(wf, True, remarks)
            except APIError:
                pass
            if act == "accept":
                await self.close_workflow(uuid.UUID(wf), "approved")
        elif act == "return" and wf:
            await self.close_workflow(uuid.UUID(wf), "rejected")

    # ---- compliance / gating ------------------------------------------------------------------------------------------
    async def compliance(self, term_id: uuid.UUID) -> list[ComplianceRow]:
        stmt = select(CollegeDataSubmission).where(
            CollegeDataSubmission.institution_id == self.inst, CollegeDataSubmission.term_id == term_id
        )
        if not (self.system() or self.office_reader() or self.exam_office()):
            mine = self.my_college_ids()
            if not mine:
                return []
            stmt = stmt.where(CollegeDataSubmission.college_id.in_(mine))
        rows = list((await self.db.execute(stmt)).scalars())
        metas = await self.metas("sub", [r.id for r in rows])
        by: dict[uuid.UUID, ComplianceRow] = {}
        for r in rows:
            row = by.setdefault(r.college_id, ComplianceRow(college_id=r.college_id))
            row.by_type[r.submission_type] = r.status
            m = metas.get(str(r.id)) or {}
            row.returns += int(m.get("returns") or 0)
            if r.status in ("accepted", "locked"):
                row.accepted += 1
            else:
                row.pending += 1
        for cid, row in by.items():
            subs = [r for r in rows if r.college_id == cid and r.submitted_at is not None]
            on_time = [r for r in subs if not (metas.get(str(r.id)) or {}).get("late")]
            row.on_time_pct = round(100 * len(on_time) / len(subs), 1) if subs else None
        colleges = await self.colleges_map(list(by))
        for cid, row in by.items():
            c = colleges.get(cid)
            row.college_code, row.college_name = (c.code, c.name) if c else (None, None)
        return sorted(by.values(), key=lambda r: r.college_code or "")

    async def college_status(self, session_id: uuid.UUID) -> list[CollegeGatingStatus]:
        s = (
            await self.db.execute(
                select(ExamSession).where(ExamSession.id == session_id, ExamSession.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise not_found("Exam session")
        gating = await session_gating(self.db, self.inst, s)
        if not (self.system() or self.office_reader() or self.exam_office()):
            mine = set(self.my_college_ids())
            gating = {k: v for k, v in gating.items() if k in mine}
        colleges = await self.colleges_map(list(gating))
        out = []
        for cid, g in gating.items():
            c = colleges.get(cid)
            out.append(
                CollegeGatingStatus(
                    college_id=cid,
                    college_code=c.code if c else None,
                    college_name=c.name if c else None,
                    status=g["status"],
                    missing=g["missing"],
                    by_type=g["by_type"],
                    registrations=g["registrations"],
                )
            )
        return sorted(out, key=lambda r: (r.status != "gated", r.college_code or ""))

    # ---- Beat -----------------------------------------------------------------------------------------------------------
    async def window_scan(self) -> int:
        """Open / due / escalate notifications for the current terms' submission windows (one per day per state)."""
        from app.models.academic import AcademicTerm

        today = await self.today()
        terms = list(
            (
                await self.db.execute(
                    select(AcademicTerm).where(
                        AcademicTerm.institution_id == self.inst,
                        or_(
                            AcademicTerm.is_current.is_(True),
                            and_(AcademicTerm.start_date <= today, AcademicTerm.end_date >= today),
                        ),
                    )
                )
            ).scalars()
        )
        colleges = [c for c in (await self.colleges_map()).values() if c.college_type in ("affiliated", "autonomous")]
        n = 0
        for term in terms:
            session = await self._central_session(term.id)
            subs = {
                (r.college_id, r.submission_type): r
                for r in (
                    await self.db.execute(select(CollegeDataSubmission).where(CollegeDataSubmission.term_id == term.id))
                ).scalars()
            }
            for st in SubmissionType:
                t = str(st)
                due = await self._due(t, term, session)
                if due is None:
                    continue
                days_left = (due - today).days
                state = (
                    "open"
                    if today == term.start_date
                    else "due"
                    if days_left in (3, 1)
                    else "overdue"
                    if days_left < 0
                    else None
                )
                if state is None:
                    continue
                for c in colleges:
                    if c.college_type == "autonomous" and t not in AUTONOMOUS_SUBMISSIONS:
                        continue
                    sub = subs.get((c.id, t))
                    if sub is not None and sub.status in ("submitted", "verified", "accepted", "locked"):
                        continue
                    key = f"win:{term.id}:{c.id}:{t}:{state}:{today.isoformat() if state == 'overdue' else ''}"
                    if (await self.meta("reminded", key)).get("sent"):
                        continue
                    ctx = {"type": t.replace("_", " "), "due_on": due.isoformat(), "term": term.name}
                    event = {
                        "open": "affiliation.submission_window_open",
                        "due": "affiliation.submission_due",
                        "overdue": "affiliation.submission_due",
                    }[state]
                    await self.notify_college(c, event, ctx, "college_admin", "college_exam_coordinator")
                    if state == "overdue" and days_left in (-1, -7):
                        await self._notify(event, await self.office_users(), {"college": c.name, **ctx})
                    await self.put_meta("reminded", key, {"sent": True})
                    n += 1
        return n

    async def counts_by_status(self) -> dict[str, int]:
        return pairs(
            (
                await self.db.execute(
                    select(CollegeDataSubmission.status, func.count())
                    .where(CollegeDataSubmission.institution_id == self.inst)
                    .group_by(CollegeDataSubmission.status)
                )
            ).all()
        )


__all__ = ["PRACTICAL_TYPES", "SubmissionService"]
