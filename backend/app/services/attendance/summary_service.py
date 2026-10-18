"""Attendance summaries — Prompts/11 §11.6 ``summary_service.py``.

* ``recompute(offering[, enrolments])`` — one aggregate query over the offering's counted sessions → upsert into
  ``attendance_summaries`` for every roster student (bands from the student's regulation rules; a ``condoned`` row
  stays condoned) and refresh ``student_term_records.attendance_pct`` (credit-weighted over the term's offerings).
  Marking recomputes inline (one query per offering); the job ``attendance.recompute_summaries`` covers a whole term.
* Reads: scoped rows (``record_predicate``), per-offering aggregates, *my* summary (student / parent ward —
  credit-weighted overall, per-offering calculator), a student's summary for staff, the session × student register.
* ``checkpoints`` (Beat, daily): when today crosses one of ``attendance.checkpoints`` (% of the term's instruction
  days), students below the minimum get ``attendance.below_threshold`` (+ guardians, + mentor / class advisor).
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.academic import AcademicTerm
from app.models.attendance import AttendanceSummary, StudentClassAttendance
from app.models.curriculum import Course
from app.models.offerings import CourseOffering
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.models.timetable import ClassSession
from app.repositories.attendance_repository import COUNTED
from app.repositories.timetable_scope import session_visibility
from app.schemas.attendance import (
    MySummaryResponse,
    RegisterGrid,
    StudentAttendanceSummary,
    StudentHistoryRow,
    SummaryResponse,
    Totals,
)
from app.services.attendance.common import (
    AttendanceBase,
    attended_counted,
    band,
    pct_of,
    q2,
    sessions_can_miss,
    sessions_needed,
    student_name,
    totals_of,
)
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta


class SummaryService(AttendanceBase):
    # ---- recompute ------------------------------------------------------------------------------------------------
    async def recompute(self, offering_id: uuid.UUID, enrolment_ids: Sequence[uuid.UUID] | None = None) -> int:
        off = (await self.offering_courses([offering_id])).get(offering_id, (None, None))[0]
        if off is None:
            return 0
        roster = await self.marks.roster_ids(offering_id, off.term_id)
        agg = await self.summaries.aggregate(offering_id, enrolment_ids)
        ids = set(agg) | (roster if enrolment_ids is None else roster & set(enrolment_ids))
        if not ids:
            return 0
        people = await self.enrolments(list(ids))
        existing = {
            s.student_program_enrollment_id: s
            for s in (
                await self.db.execute(
                    select(AttendanceSummary).where(
                        AttendanceSummary.offering_id == offering_id,
                        AttendanceSummary.student_program_enrollment_id.in_(list(ids)),
                    )
                )
            ).scalars()
        }
        rows: list[dict[str, Any]] = []
        for enr_id in ids:
            t = totals_of(agg.get(enr_id, {}))
            attended, counted = attended_counted(t)
            pct = pct_of(attended, counted)
            mn, fl = await self.thresholds(people.get(enr_id, (None, None))[0])
            b = band(pct, mn, fl)
            old = existing.get(enr_id)
            if old is not None and old.eligibility == "condoned" and b != "eligible":
                b = "condoned"
            rows.append(
                {
                    "offering_id": offering_id,
                    "student_program_enrollment_id": enr_id,
                    **t,
                    "pct": q2(pct),
                    "eligibility": b,
                }
            )
        await self.summaries.upsert(self.inst, rows)
        await self.db.flush()
        await self.refresh_term_pct(off.term_id, list(ids))
        return len(rows)

    async def recompute_term(self, term_id: uuid.UUID, progress: Any = None) -> dict[str, int]:
        offerings = (
            (
                await self.db.execute(
                    select(CourseOffering.id).where(
                        CourseOffering.institution_id == self.inst,
                        CourseOffering.term_id == term_id,
                        CourseOffering.deleted_at.is_(None),
                        CourseOffering.status.notin_(("cancelled", "planned")),
                    )
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for i, oid in enumerate(offerings, start=1):
            n += await self.recompute(oid)
            if progress and i % 10 == 0:
                await progress(int(i * 100 / max(1, len(offerings))), f"{i}/{len(offerings)} offerings")
        return {"offerings": len(offerings), "rows": n}

    async def refresh_term_pct(self, term_id: uuid.UUID, enrolment_ids: list[uuid.UUID]) -> None:
        """``student_term_records.attendance_pct`` = credit-weighted pct over the term's summarised offerings."""
        for enr_id, pct in (await self.weighted(term_id, enrolment_ids)).items():
            rec = (
                await self.db.execute(
                    select(StudentTermRecord).where(
                        StudentTermRecord.student_program_enrollment_id == enr_id, StudentTermRecord.term_id == term_id
                    )
                )
            ).scalar_one_or_none()
            if rec is not None:
                rec.attendance_pct = q2(pct)

    async def weighted(self, term_id: uuid.UUID, enrolment_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
        if not enrolment_ids:
            return {}
        rows = (
            await self.db.execute(
                select(AttendanceSummary.student_program_enrollment_id, AttendanceSummary.pct, Course.credits)
                .join(CourseOffering, CourseOffering.id == AttendanceSummary.offering_id)
                .join(Course, Course.id == CourseOffering.course_id)
                .where(
                    CourseOffering.term_id == term_id,
                    AttendanceSummary.student_program_enrollment_id.in_(enrolment_ids),
                )
            )
        ).all()
        acc: dict[uuid.UUID, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for enr, pct, credits in rows:
            w = float(credits or 0) or 1.0
            acc[enr][0] += float(pct) * w
            acc[enr][1] += w
        return {e: round(v[0] / v[1], 2) for e, v in acc.items() if v[1]}

    # ---- responses --------------------------------------------------------------------------------------------------
    async def rows_out(self, rows: Sequence[AttendanceSummary]) -> list[StudentAttendanceSummary]:
        people = await self.enrolments([r.student_program_enrollment_id for r in rows])
        oc = await self.offering_courses(list({r.offering_id for r in rows}))
        out = []
        for r in rows:
            enrol, student = people.get(r.student_program_enrollment_id, (None, None))
            course = oc.get(r.offering_id, (None, None))[1]
            mn, fl = await self.thresholds(enrol)
            t = {k: int(getattr(r, k)) for k in ("total_sessions", "present", "absent", "on_duty", "late", "exempt")}
            attended, counted = attended_counted(t)
            out.append(
                StudentAttendanceSummary(
                    offering_id=r.offering_id,
                    student_program_enrollment_id=r.student_program_enrollment_id,
                    student_name=student_name(student),
                    registration_number=student.registration_number if student else None,
                    course_code=course.code if course else None,
                    course_title=course.title if course else None,
                    credits=float(course.credits) if course and course.credits is not None else None,
                    pct=float(r.pct),
                    eligibility=r.eligibility,
                    min_pct=mn,
                    floor_pct=fl,
                    sessions_needed_for_threshold=sessions_needed(attended, counted, mn),
                    sessions_can_miss=sessions_can_miss(attended, counted, mn),
                    computed_at=r.computed_at,
                    **t,
                )
            )
        return out

    async def list_page(
        self,
        params: PageParams,
        scope: str | None,
        offering_id: uuid.UUID | None,
        eligibility: str | None,
        below: float | None,
    ) -> tuple[list[StudentAttendanceSummary], PaginationMeta, VisibilityMeta]:
        if offering_id:
            await self.recompute(offering_id)
        stmt = self.summaries.scoped(scope)
        if offering_id:
            stmt = stmt.where(AttendanceSummary.offering_id == offering_id)
        if eligibility:
            stmt = stmt.where(AttendanceSummary.eligibility == eligibility)
        if below is not None:
            stmt = stmt.where(AttendanceSummary.pct < Decimal(str(below)))
        if not params.sort:
            stmt = stmt.order_by(AttendanceSummary.pct)
        rows, page = await self.summaries.paginate(stmt, params)
        return await self.rows_out(list(rows)), page, session_visibility(self.principal)

    async def offerings_overview(self, term_id: uuid.UUID | None, scope: str | None) -> list[SummaryResponse]:
        stmt = (
            select(
                AttendanceSummary.offering_id,
                func.sum(AttendanceSummary.total_sessions),
                func.sum(AttendanceSummary.present),
                func.sum(AttendanceSummary.absent),
                func.sum(AttendanceSummary.on_duty),
                func.sum(AttendanceSummary.late),
                func.sum(AttendanceSummary.exempt),
                func.avg(AttendanceSummary.pct),
                func.count().filter(AttendanceSummary.eligibility == "eligible"),
                func.count().filter(AttendanceSummary.eligibility == "condonable"),
                func.count().filter(AttendanceSummary.eligibility == "not_eligible"),
                func.count().filter(AttendanceSummary.eligibility == "condoned"),
            )
            .where(AttendanceSummary.id.in_(self.summaries.scoped(scope).with_only_columns(AttendanceSummary.id)))
            .group_by(AttendanceSummary.offering_id)
        )
        if term_id:
            stmt = stmt.where(
                AttendanceSummary.offering_id.in_(select(CourseOffering.id).where(CourseOffering.term_id == term_id))
            )
        rows = (await self.db.execute(stmt)).all()
        oc = await self.offering_courses([r[0] for r in rows])
        out = []
        for oid, tot, pr, ab, od, lt, ex, avg, e1, e2, e3, e4 in rows:
            course = oc.get(oid, (None, None))[1]
            out.append(
                SummaryResponse(
                    offering_id=oid,
                    course_code=course.code if course else None,
                    course_title=course.title if course else None,
                    totals=Totals(
                        total_sessions=int(tot or 0),
                        present=int(pr or 0),
                        absent=int(ab or 0),
                        on_duty=int(od or 0),
                        late=int(lt or 0),
                        exempt=int(ex or 0),
                    ),
                    pct=round(float(avg or 0), 2),
                    eligibility={"eligible": e1, "condonable": e2, "not_eligible": e3, "condoned": e4},
                )
            )
        return sorted(out, key=lambda r: r.course_code or "")

    async def _for_enrolment(
        self, enrolment: StudentProgramEnrollment, student: Student, term_id: uuid.UUID | None
    ) -> MySummaryResponse:
        term = (
            await self.get_term(term_id, enrolment.college_id)
            if term_id
            else await self.current_term(enrolment.college_id)
        )
        offering_ids = (
            (
                await self.db.execute(
                    select(CourseRegistrationItem.offering_id)
                    .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
                    .where(
                        CourseRegistration.student_program_enrollment_id == enrolment.id,
                        CourseRegistrationItem.status == "confirmed",
                        *([CourseRegistration.term_id == term.id] if term else []),
                    )
                )
            )
            .scalars()
            .all()
        )
        for oid in offering_ids:
            await self.recompute(oid, [enrolment.id])
        rows = (
            (
                await self.db.execute(
                    select(AttendanceSummary).where(
                        AttendanceSummary.student_program_enrollment_id == enrolment.id,
                        AttendanceSummary.offering_id.in_(list(offering_ids)),
                    )
                )
            )
            .scalars()
            .all()
        )
        per = await self.rows_out(list(rows))
        weighted = (await self.weighted(term.id, [enrolment.id])).get(enrolment.id) if term else None
        rules = await self.rules_for_pr(enrolment.program_regulation_id)
        return MySummaryResponse(
            term_id=term.id if term else None,
            student_program_enrollment_id=enrolment.id,
            student_name=student_name(student),
            overall_pct=weighted if weighted is not None else 100.0,
            attendance_mode=str(rules.get("attendance_mode") or "course_wise"),
            per_offering=sorted(per, key=lambda r: r.course_code or ""),
        )

    async def my_summary(self, term_id: uuid.UUID | None, ward_id: uuid.UUID | None) -> MySummaryResponse:
        student, enrolment = await self.learner(ward_id)
        return await self._for_enrolment(enrolment, student, term_id)

    async def for_student(self, student_id: uuid.UUID, term_id: uuid.UUID | None) -> MySummaryResponse:
        enrolment = (
            await self.db.execute(
                self.enrollments.visible(
                    select(StudentProgramEnrollment).where(
                        StudentProgramEnrollment.student_id == student_id, StudentProgramEnrollment.deleted_at.is_(None)
                    )
                )
                .order_by(StudentProgramEnrollment.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if enrolment is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        student = (await self.db.execute(select(Student).where(Student.id == student_id))).scalar_one()
        return await self._for_enrolment(enrolment, student, term_id)

    async def history(self, ward_id: uuid.UUID | None, offering_id: uuid.UUID | None) -> list[StudentHistoryRow]:
        _, enrolment = await self.learner(ward_id)
        offering_ids = (
            [offering_id]
            if offering_id
            else (
                await self.db.execute(
                    select(CourseRegistrationItem.offering_id)
                    .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
                    .where(
                        CourseRegistration.student_program_enrollment_id == enrolment.id,
                        CourseRegistrationItem.status == "confirmed",
                    )
                )
            )
            .scalars()
            .all()
        )
        rows = await self.marks.history(enrolment.id, offering_ids)
        oc = await self.offering_courses(list({s.offering_id for s, _, _ in rows}))
        codes = {oid: (c.code if c else None) for oid, (_, c) in oc.items()}
        return [
            StudentHistoryRow(
                session_id=s.id,
                session_date=s.session_date,
                start_time=s.start_time,
                course_code=codes.get(s.offering_id),
                status=status,
                source=source,
            )
            for s, status, source in rows
        ]

    async def register(self, offering_id: uuid.UUID, date_from: date | None, date_to: date | None) -> RegisterGrid:
        self.assert_staff()
        sessions = self.sessions.filtered("all", offering_id=offering_id, date_from=date_from, date_to=date_to).where(
            COUNTED
        )
        srows = list(
            (await self.db.execute(sessions.order_by(ClassSession.session_date, ClassSession.start_time)))
            .scalars()
            .all()
        )
        if not srows and not await self.may_view_offering(offering_id):
            raise APIError(404, ErrorCode.NOT_FOUND, "Offering not found")
        off = (await self.offering_courses([offering_id])).get(offering_id, (None, None))[0]
        roster = list(
            (await self.db.execute(self.marks.roster_stmt(offering_id, off.term_id if off else None, None))).all()
        )
        ids = [s.id for s in srows]
        marks: dict[str, dict[str, str]] = defaultdict(dict)
        if ids:
            for m in (
                await self.db.execute(select(StudentClassAttendance).where(StudentClassAttendance.session_id.in_(ids)))
            ).scalars():
                marks[str(m.student_program_enrollment_id)][str(m.session_id)] = m.status
        return RegisterGrid(
            offering_id=offering_id,
            sessions=[
                {
                    "id": str(s.id),
                    "date": s.session_date.isoformat(),
                    "start": s.start_time.isoformat()[:5],
                    "status": s.attendance_status,
                }
                for s in srows
            ],
            students=[
                {
                    "id": str(r[0]),
                    "name": " ".join(p for p in (r[2], r[3]) if p),
                    "registration_number": r[4],
                    "roll_number": r[5],
                }
                for r in roster
            ],
            marks=dict(marks),
        )

    async def may_view_offering(self, offering_id: uuid.UUID) -> bool:
        n = (
            await self.db.execute(
                select(func.count()).select_from(self.sessions.filtered("all", offering_id=offering_id).subquery())
            )
        ).scalar_one()
        return bool(n)

    # ---- checkpoints (Beat) ----------------------------------------------------------------------------------------
    async def checkpoints(self, force_pct: int | None = None) -> int:
        """Warnings when today crosses a checkpoint of the current term's instruction days (``force_pct`` = dev)."""
        from app.core.features import is_enabled

        if not await is_enabled(self.inst, "attendance.guardian_alerts"):
            return 0
        today = await self.today()
        marks = [int(x) for x in (await self.att_setting("checkpoints", [25, 50, 75]) or [])]
        terms = (
            (
                await self.db.execute(
                    select(AcademicTerm).where(
                        AcademicTerm.institution_id == self.inst,
                        AcademicTerm.is_current.is_(True),
                        AcademicTerm.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        sent = 0
        for term in terms:
            end = term.last_instruction_date or term.end_date
            span = max(1, (end - term.start_date).days)
            now_pct = (today - term.start_date).days * 100 / span
            prev_pct = (today - term.start_date).days * 100 / span - 100 / span
            hit = force_pct if force_pct is not None else next((c for c in marks if prev_pct < c <= now_pct), None)
            if hit is None:
                continue
            await self.recompute_term(term.id)
            sent += await self._warn_below(term, int(hit))
        return sent

    async def _warn_below(self, term: AcademicTerm, checkpoint: int) -> int:
        rows = (
            (
                await self.db.execute(
                    select(AttendanceSummary)
                    .join(CourseOffering, CourseOffering.id == AttendanceSummary.offering_id)
                    .where(
                        CourseOffering.term_id == term.id,
                        AttendanceSummary.eligibility.in_(("condonable", "not_eligible")),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return 0
        people = await self.enrolments([r.student_program_enrollment_id for r in rows])
        oc = await self.offering_courses(list({r.offering_id for r in rows}))
        guardians = bool(await self.att_setting("notify_guardians", True))
        mentor = bool(await self.att_setting("notify_mentor", True))
        sent = 0
        for r in rows:
            enrol, student = people.get(r.student_program_enrollment_id, (None, None))
            if student is None:
                continue
            course = oc.get(r.offering_id, (None, None))[1]
            mn, _ = await self.thresholds(enrol)
            users = [student.user_id] + (
                await self.mentor_users(r.student_program_enrollment_id, term.id) if mentor else []
            )
            await self._notify(
                "attendance.below_threshold",
                users,
                {
                    "course": course.code if course else "course",
                    "percentage": float(r.pct),
                    "minimum": mn,
                    "checkpoint": checkpoint,
                },
                guardians=guardians,
            )
            await self._emit(
                "attendance.below_threshold",
                {
                    "student_program_enrollment_id": str(r.student_program_enrollment_id),
                    "offering_id": str(r.offering_id),
                    "pct": float(r.pct),
                    "checkpoint": checkpoint,
                },
                "attendance_summary",
                r.id,
            )
            sent += 1
        return sent

    async def mentor_users(self, enrolment_id: uuid.UUID, term_id: uuid.UUID) -> list[uuid.UUID]:
        """Mentor (``mentor_assignments``, Phase 27 table) and the class advisor of the student's section."""
        from sqlalchemy import text

        from app.models.academic import BatchSection
        from app.models.hr import Staff

        out: list[uuid.UUID] = []
        row = (
            await self.db.execute(
                text(
                    "SELECT s.user_id FROM mentor_assignments m JOIN staff s ON s.id = m.mentor_staff_id "
                    "WHERE m.student_program_enrollment_id = CAST(:e AS uuid) AND m.term_id = CAST(:t AS uuid) "
                    "AND m.status = 'active'"
                ),
                {"e": str(enrolment_id), "t": str(term_id)},
            )
        ).first()
        if row and row[0]:
            out.append(row[0])
        advisor = (
            await self.db.execute(
                select(Staff.user_id)
                .join(BatchSection, BatchSection.class_advisor_staff_id == Staff.id)
                .join(StudentTermRecord, StudentTermRecord.section_id == BatchSection.id)
                .where(
                    StudentTermRecord.student_program_enrollment_id == enrolment_id,
                    StudentTermRecord.term_id == term_id,
                )
            )
        ).scalar_one_or_none()
        if advisor:
            out.append(advisor)
        return out


__all__ = ["SummaryService"]
