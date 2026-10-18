"""Term eligibility — Prompts/11 §11.6 ``eligibility_service.py`` ({attendance.eligibility_detention}).

1. ``compute(term, scope)`` — job ``eligibility.compute`` (``exams:eligibility``; a ``dry_run`` answers inline without
   writing). For every (term record, confirmed offering) of the scope: summaries recomputed, attendance band
   (course-wise, or the credit-weighted aggregate when ``attendance_mode = aggregate``), ``is_cia_ok`` (Phase 13
   ``cia_consolidations.cia_scaled`` ≥ ``cia_pass_min_pct`` when the rule is set, else true), ``is_fee_ok`` (overdue
   ``fee_invoices`` when ``exams.eligibility_requires_fee_clear``), ``is_hold_ok`` (Phase 07 ``exam`` holds). Decision:
   condoned → ``condoned``; below the floor or CIA fail → ``detained``; condonable / fee due / exam hold →
   ``pending``; else ``eligible``. ``reason_codes``: ``ATT_BELOW_MIN``, ``ATT_CONDONABLE``, ``CIA_FAIL``, ``FEE_DUE``,
   ``HOLD_EXAM``, ``DEBARRED``. Every compute writes a **new version** (earlier versions retained); a manual decision of
   the previous version (``decided_by`` set) is carried forward. ``student_term_records.attendance_pct`` is refreshed;
   ``eligibility.computed`` emitted; detained students notified once per version (``attendance.notify_detained``).
2. ``decide(row, decision, reason)`` — registrar / exam cell override in place, audited (old / new + reason).
3. ``detention_list`` (+ XLSX export job) and ``notify_detained``.
4. Phase 14 reads ``latest_version`` into ``exam_registrations.eligibility_snapshot``; Phase 15 marks detained items.
"""

import uuid
from collections import Counter
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm
from app.models.attendance import TermEligibility
from app.models.platform import AuditLog
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import StudentProgramEnrollment, StudentTermRecord
from app.repositories.timetable_scope import session_visibility
from app.schemas.attendance import (
    DecideRequest,
    DetentionListRow,
    EligibilityComputeRequest,
    EligibilityRow,
    EligibilityRunSummary,
)
from app.services.attendance.common import AttendanceBase, student_name
from app.services.timetable.common import now_utc
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

ENTITY = "term_eligibility"


class EligibilityService(AttendanceBase):
    # ---- compute ----------------------------------------------------------------------------------------------------
    async def _pairs(
        self, term: AcademicTerm, body: EligibilityComputeRequest
    ) -> list[tuple[StudentTermRecord, StudentProgramEnrollment, uuid.UUID]]:
        stmt = (
            select(StudentTermRecord, StudentProgramEnrollment, CourseRegistrationItem.offering_id)
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == StudentTermRecord.student_program_enrollment_id
            )
            .join(CourseRegistration, CourseRegistration.student_term_record_id == StudentTermRecord.id)
            .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
            .where(
                StudentTermRecord.term_id == term.id,
                StudentTermRecord.institution_id == self.inst,
                CourseRegistrationItem.status == "confirmed",
                StudentProgramEnrollment.deleted_at.is_(None),
            )
        )
        if body.college_id:
            stmt = stmt.where(StudentProgramEnrollment.college_id == body.college_id)
        if body.program_id:
            stmt = stmt.where(StudentProgramEnrollment.program_id == body.program_id)
        if body.offering_ids:
            stmt = stmt.where(CourseRegistrationItem.offering_id.in_(body.offering_ids))
        return [(r, e, o) for r, e, o in (await self.db.execute(stmt)).all()]

    async def compute(self, term_id: uuid.UUID, body: EligibilityComputeRequest) -> EligibilityRunSummary:
        """Endpoint entry: dry run inline, else the ``eligibility.compute`` job (202)."""
        term = await self.get_term(term_id)
        if body.dry_run:
            return await self.run(term, body, write=False)
        from app.core.jobs import enqueue

        job = await enqueue(
            self.db,
            self.principal,
            "eligibility.compute",
            {"term_id": str(term.id), "body": body.model_dump(mode="json")},
        )
        return EligibilityRunSummary(term_id=term.id, version=await self.elig.term_version(term.id) + 1, job_id=job.id)

    async def run(
        self, term: AcademicTerm, body: EligibilityComputeRequest, *, write: bool = True, progress: Any = None
    ) -> EligibilityRunSummary:
        from app.core.features import is_enabled
        from app.services.attendance.summary_service import SummaryService

        pairs = await self._pairs(term, body)
        summaries = SummaryService(self.db, self.principal, self.request, self.inst)
        offerings = sorted({o for _, _, o in pairs})
        for i, oid in enumerate(offerings, start=1):
            await summaries.recompute(oid)
            if progress and i % 10 == 0:
                await progress(int(i * 50 / max(1, len(offerings))), f"summaries {i}/{len(offerings)}")
        version = await self.elig.term_version(term.id) + 1
        weighted = await summaries.weighted(term.id, list({e.id for _, e, _ in pairs}))
        holds_on = await is_enabled(self.inst, "students.holds")
        fee_rule = bool(await self.setting("exams", "eligibility_requires_fee_clear"))
        today = await self.today()
        counts: Counter[str] = Counter()
        hold_cache: dict[uuid.UUID, bool] = {}
        fee_cache: dict[uuid.UUID, bool] = {}
        written = 0
        for idx, (rec, enrol, oid) in enumerate(pairs, start=1):
            rules = await self.rules_for_pr(enrol.program_regulation_id)
            mn, fl = float(rules.get("attendance_min_pct") or 75), float(rules.get("condonation_floor_pct") or 0)
            s = await self.summaries.of(oid, enrol.id)
            if str(rules.get("attendance_mode") or "course_wise") == "aggregate":
                pct = weighted.get(enrol.id, 100.0)
            else:
                pct = float(s.pct) if s else 100.0
            condoned = s is not None and s.eligibility == "condoned"
            codes: list[str] = []
            att_ok = condoned or pct >= mn
            if not att_ok:
                codes.append("ATT_CONDONABLE" if pct >= fl else "ATT_BELOW_MIN")
            cia_marks, cia_ok = None, True
            cia_min = rules.get("cia_pass_min_pct")
            row = (
                await self.db.execute(
                    text(
                        "SELECT cia_scaled FROM cia_consolidations WHERE offering_id = CAST(:o AS uuid) "
                        "AND student_program_enrollment_id = CAST(:e AS uuid)"
                    ),
                    {"o": str(oid), "e": str(enrol.id)},
                )
            ).first()
            if row is not None:
                cia_marks = Decimal(str(row[0]))
                if cia_min is not None and float(cia_marks) < float(cia_min):
                    cia_ok = False
                    codes.append("CIA_FAIL")
            if enrol.id not in fee_cache:
                fee_cache[enrol.id] = True
                if fee_rule:
                    due = (
                        await self.db.execute(
                            text(
                                "SELECT count(*) FROM fee_invoices WHERE student_program_enrollment_id = CAST(:e AS uuid) "
                                "AND status IN ('pending','partial','overdue') AND balance_paise > 0 AND due_date < :d"
                            ),
                            {"e": str(enrol.id), "d": today},
                        )
                    ).scalar_one()
                    fee_cache[enrol.id] = not due
            fee_ok = fee_cache[enrol.id]
            if not fee_ok:
                codes.append("FEE_DUE")
            if enrol.id not in hold_cache:
                hold_cache[enrol.id] = not (holds_on and await self.holds.open_holds(enrol.id, "exam"))
            hold_ok = hold_cache[enrol.id]
            if not hold_ok:
                codes.append("HOLD_EXAM")
            prev = await self.elig.latest_version(rec.id, oid)
            if prev is not None and prev.decision == "debarred":
                codes.append("DEBARRED")
            if "DEBARRED" in codes:
                decision = "debarred"
            elif "ATT_BELOW_MIN" in codes or "CIA_FAIL" in codes:
                decision = "detained"
            elif condoned and not codes:
                decision = "condoned"
            elif codes:
                decision = "pending"
            else:
                decision = "eligible"
            decided_by = decided_at = None
            if prev is not None and prev.decided_by is not None and prev.decision != "debarred":
                decision, decided_by, decided_at = prev.decision, prev.decided_by, prev.decided_at
            counts[decision] += 1
            if write:
                self.db.add(
                    TermEligibility(
                        institution_id=self.inst,
                        student_term_record_id=rec.id,
                        offering_id=oid,
                        attendance_pct=Decimal(str(round(pct, 2))),
                        cia_marks=cia_marks,
                        cia_max=None,
                        is_attendance_ok=att_ok,
                        is_cia_ok=cia_ok,
                        is_fee_ok=fee_ok,
                        is_hold_ok=hold_ok,
                        decision=decision,
                        reason_codes=codes or None,
                        decided_by=decided_by,
                        decided_at=decided_at,
                        version=version,
                    )
                )
                written += 1
                if written % 500 == 0:
                    await self.db.flush()
            if progress and idx % 200 == 0:
                await progress(50 + int(idx * 50 / max(1, len(pairs))), f"{idx}/{len(pairs)} rows")
        out = EligibilityRunSummary(
            term_id=term.id, version=version, rows=len(pairs), counts=dict(counts), dry_run=not write
        )
        if write:
            await self.db.flush()
            await self._audit(
                "compute",
                "academic_term",
                term.id,
                None,
                {"version": version, "rows": len(pairs), "counts": dict(counts)},
            )
            await self._emit("eligibility.computed", out.model_dump(mode="json"), "academic_term", term.id)
            if bool(await self.att_setting("notify_detained", True)):
                await self.notify_detained(term.id, version)
        return out

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[TermEligibility]) -> list[EligibilityRow]:
        recs = await self._rows(StudentTermRecord, [r.student_term_record_id for r in rows])
        people = await self.enrolments([r.student_program_enrollment_id for r in recs.values()])
        oc = await self.offering_courses(list({r.offering_id for r in rows}))
        out = []
        for r in rows:
            rec = recs.get(r.student_term_record_id)
            _, student = people.get(rec.student_program_enrollment_id, (None, None)) if rec else (None, None)
            course = oc.get(r.offering_id, (None, None))[1]
            o = EligibilityRow.model_validate(r)
            o.attendance_pct = float(r.attendance_pct) if r.attendance_pct is not None else None
            o.cia_marks = float(r.cia_marks) if r.cia_marks is not None else None
            o.student_program_enrollment_id = rec.student_program_enrollment_id if rec else None
            o.student_name = student_name(student)
            o.registration_number = student.registration_number if student else None
            o.course_code = course.code if course else None
            out.append(o)
        return out

    def _latest(self, term_id: uuid.UUID, version: int | None, scope: str | None) -> Any:
        stmt = self.elig.scoped(scope).where(
            TermEligibility.student_term_record_id.in_(
                select(StudentTermRecord.id).where(StudentTermRecord.term_id == term_id)
            )
        )
        if version:
            return stmt.where(TermEligibility.version == version)
        t2 = TermEligibility.__table__.alias("t2")
        latest = (
            select(func.max(t2.c.version))
            .where(
                t2.c.student_term_record_id == TermEligibility.student_term_record_id,
                t2.c.offering_id == TermEligibility.offering_id,
            )
            .scalar_subquery()
        )
        return stmt.where(TermEligibility.version == latest)

    async def list_page(
        self,
        term_id: uuid.UUID,
        params: PageParams,
        scope: str | None,
        offering_id: uuid.UUID | None,
        decision: str | None,
        version: int | None,
    ) -> tuple[list[EligibilityRow], PaginationMeta, VisibilityMeta]:
        stmt = self._latest(term_id, version, scope)
        if offering_id:
            stmt = stmt.where(TermEligibility.offering_id == offering_id)
        if decision:
            stmt = stmt.where(TermEligibility.decision == decision)
        rows, page = await self.elig.paginate(stmt, params)
        return await self.outs(list(rows)), page, session_visibility(self.principal)

    async def versions(self, term_id: uuid.UUID) -> list[int]:
        rows = (
            (
                await self.db.execute(
                    select(TermEligibility.version)
                    .join(StudentTermRecord, StudentTermRecord.id == TermEligibility.student_term_record_id)
                    .where(StudentTermRecord.term_id == term_id, TermEligibility.institution_id == self.inst)
                    .distinct()
                    .order_by(TermEligibility.version)
                )
            )
            .scalars()
            .all()
        )
        return [int(v) for v in rows]

    async def my_rows(self, term_id: uuid.UUID | None, ward_id: uuid.UUID | None) -> list[EligibilityRow]:
        _, enrolment = await self.learner(ward_id)
        term = await self.get_term(term_id, enrolment.college_id)
        rec = (
            await self.db.execute(
                select(StudentTermRecord).where(
                    StudentTermRecord.student_program_enrollment_id == enrolment.id,
                    StudentTermRecord.term_id == term.id,
                )
            )
        ).scalar_one_or_none()
        if rec is None:
            return []
        t2 = TermEligibility.__table__.alias("t2")
        latest = (
            select(func.max(t2.c.version))
            .where(
                t2.c.student_term_record_id == TermEligibility.student_term_record_id,
                t2.c.offering_id == TermEligibility.offering_id,
            )
            .scalar_subquery()
        )
        rows = (
            (
                await self.db.execute(
                    select(TermEligibility).where(
                        TermEligibility.student_term_record_id == rec.id, TermEligibility.version == latest
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    # ---- decide -----------------------------------------------------------------------------------------------------
    async def decide(self, row_id: uuid.UUID, body: DecideRequest) -> EligibilityRow:
        row = (
            await self.db.execute(self.elig.scoped("all").where(TermEligibility.id == row_id).with_for_update())
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Eligibility row not found")
        old = {"decision": row.decision, "reason_codes": row.reason_codes}
        row.decision, row.decided_by, row.decided_at = str(body.decision), self.actor_id, now_utc()
        await self.db.flush()
        await self._audit(
            "decide", ENTITY, row.id, old, {"decision": row.decision, "reason": body.reason, "version": row.version}
        )
        await self._emit(
            "eligibility.decided", {"id": str(row.id), "decision": row.decision, "reason": body.reason}, ENTITY, row.id
        )
        return (await self.outs([row]))[0]

    # ---- detention ----------------------------------------------------------------------------------------------------
    async def detention_list(
        self, term_id: uuid.UUID, college_id: uuid.UUID | None, program_id: uuid.UUID | None, scope: str | None = None
    ) -> list[DetentionListRow]:
        stmt = self._latest(term_id, None, scope).where(TermEligibility.decision == "detained")
        rows = list((await self.db.execute(stmt)).scalars().all())
        recs = await self._rows(StudentTermRecord, [r.student_term_record_id for r in rows])
        people = await self.enrolments([r.student_program_enrollment_id for r in recs.values()])
        oc = await self.offering_courses(list({r.offering_id for r in rows}))
        from app.models.academic import Program

        programs = await self._rows(Program, [e.program_id for e, _ in people.values()])
        out = []
        for r in rows:
            rec = recs.get(r.student_term_record_id)
            enrol, student = people.get(rec.student_program_enrollment_id, (None, None)) if rec else (None, None)
            if college_id and (enrol is None or enrol.college_id != college_id):
                continue
            if program_id and (enrol is None or enrol.program_id != program_id):
                continue
            course = oc.get(r.offering_id, (None, None))[1]
            prog = programs.get(enrol.program_id) if enrol else None
            out.append(
                DetentionListRow(
                    student_program_enrollment_id=enrol.id if enrol else None,
                    student_name=student_name(student),
                    registration_number=student.registration_number if student else None,
                    program_code=getattr(prog, "code", None),
                    offering_id=r.offering_id,
                    course_code=course.code if course else None,
                    attendance_pct=float(r.attendance_pct) if r.attendance_pct is not None else None,
                    reason_codes=list(r.reason_codes or []),
                    version=r.version,
                )
            )
        return sorted(out, key=lambda x: (x.program_code or "", x.registration_number or "", x.course_code or ""))

    async def notify_detained(self, term_id: uuid.UUID, version: int | None = None) -> int:
        version = version or await self.elig.term_version(term_id)
        done = (
            await self.db.execute(
                select(func.count()).where(
                    AuditLog.institution_id == self.inst,
                    AuditLog.record_type == "academic_term",
                    AuditLog.record_id == term_id,
                    AuditLog.action == "detention_notified",
                    AuditLog.new_values["version"].astext == str(version),
                )
            )
        ).scalar_one()
        if done:
            return 0
        rows = await self.detention_list(term_id, None, None, "all")
        by_student: dict[uuid.UUID, list[str]] = {}
        for r in rows:
            if r.student_program_enrollment_id:
                by_student.setdefault(r.student_program_enrollment_id, []).append(r.course_code or "")
        people = await self.enrolments(list(by_student))
        for enr, courses in by_student.items():
            _, student = people.get(enr, (None, None))
            if student is not None:
                await self._notify(
                    "eligibility.detained", [student.user_id], {"courses": ", ".join(sorted(courses))}, guardians=True
                )
        await self._audit(
            "detention_notified", "academic_term", term_id, None, {"version": version, "students": len(by_student)}
        )
        return len(by_student)


__all__ = ["EligibilityService"]
