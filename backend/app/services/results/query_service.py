# mypy: disable-error-code="arg-type,var-annotated"
"""Result queries — Prompts/15 §15.6 ``result_service`` rule 6: own results (published, current versions), wards,
a student's results (visibility resolver), an offering's result sheet (teachers / ``results:view_all``), the public
lookup (``reg_no + dob`` — only sessions published with ``audience='public'``), tabulation register, analysis and
rank list. Learners never see unpublished rows; ``revised`` marks version 2+.
"""

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select

from app.core.errors import APIError, ErrorCode
from app.enums.results import PASSING
from app.models.academic import AcademicTerm
from app.models.curriculum import Course
from app.models.offerings import CourseOffering
from app.models.results import GradeCard, ResultProcessingRun, ResultPublication, StudentCourseResult, StudentTermResult
from app.models.students import Student, StudentProgramEnrollment, StudentTermRecord
from app.repositories.assessment_scope import teaches
from app.repositories.fee_scope import own_enrollment_ids, ward_enrollment_ids
from app.repositories.result_scope import enrollment_predicate, may_view_all, result_predicate
from app.schemas.results import (
    MyResultsResponse,
    MyTerm,
    PublicLookupResponse,
    ResultAnalysis,
    TabulationRow,
    TermResultResponse,
)
from app.services.results.result_service import ResultBase


class ResultQueryService(ResultBase):
    async def _terms_out(self, rows: list[tuple[StudentTermResult, StudentTermRecord]]) -> list[TermResultResponse]:
        tids = {rec.term_id for _, rec in rows}
        names = dict(
            (
                await self.db.execute(
                    select(AcademicTerm.id, AcademicTerm.name).where(AcademicTerm.id.in_(tids or {uuid.uuid4()}))
                )
            ).all()
        )
        cards = dict(
            (
                await self.db.execute(
                    select(GradeCard.student_term_result_id, GradeCard.id).where(
                        GradeCard.student_term_result_id.in_({t.id for t, _ in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        out = []
        for t, rec in rows:
            o = TermResultResponse.model_validate(t, from_attributes=True)
            o.term_id, o.term_number, o.term_name = rec.term_id, rec.term_number, names.get(rec.term_id)
            o.grade_card_id = cards.get(t.id)
            out.append(o)
        return out

    async def results_for(self, enr: StudentProgramEnrollment, term_id: uuid.UUID | None = None) -> MyResultsResponse:
        tq = (
            select(StudentTermResult, StudentTermRecord)
            .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
            .where(
                StudentTermRecord.student_program_enrollment_id == enr.id,
                StudentTermResult.is_current.is_(True),
                StudentTermResult.status == "published",
            )
            .order_by(StudentTermRecord.term_number)
        )
        if term_id:
            tq = tq.where(StudentTermRecord.term_id == term_id)
        terms = (await self.db.execute(tq)).all()
        rq = select(StudentCourseResult).where(
            StudentCourseResult.student_program_enrollment_id == enr.id,
            StudentCourseResult.status == "published",
            StudentCourseResult.is_current.is_(True),
        )
        if term_id:
            rq = rq.where(StudentCourseResult.term_id == term_id)
        rows = await self.rows_out(list((await self.db.execute(rq)).scalars()))
        by_term: dict[uuid.UUID, list[Any]] = defaultdict(list)
        for r in rows:
            by_term[r.term_id].append(r)
        touts = await self._terms_out(list(terms))
        return MyResultsResponse(
            student_id=enr.student_id,
            enrollment_id=enr.id,
            terms=[
                MyTerm(term=t, courses=sorted(by_term.get(t.term_id, []), key=lambda c: c.course_code or ""))
                for t in touts
                if t.term_id
            ],
            cgpa=enr.cgpa,
            credits_earned=enr.credits_earned,
            standing=enr.academic_standing,
        )

    async def _enrolment_of_student(self, student_id: uuid.UUID, allowed: Any) -> StudentProgramEnrollment:
        e = (
            (
                await self.db.execute(
                    select(StudentProgramEnrollment)
                    .where(
                        StudentProgramEnrollment.student_id == student_id,
                        StudentProgramEnrollment.institution_id == self.inst,
                        StudentProgramEnrollment.deleted_at.is_(None),
                        allowed,
                    )
                    .order_by(StudentProgramEnrollment.admission_date.desc())
                )
            )
            .scalars()
            .first()
        )
        if e is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Student not found")
        return e

    async def my_results(self, term_id: uuid.UUID | None) -> MyResultsResponse:
        enrs = list(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment)
                    .where(
                        StudentProgramEnrollment.id.in_(own_enrollment_ids(self.principal, wards=False, advisees=False))
                    )
                    .order_by(StudentProgramEnrollment.admission_date.desc())
                )
            ).scalars()
        )
        if not enrs:
            return MyResultsResponse(terms=[])
        return await self.results_for(enrs[0], term_id)

    async def ward_results(self, student_id: uuid.UUID) -> MyResultsResponse:
        e = await self._enrolment_of_student(
            student_id, StudentProgramEnrollment.id.in_(ward_enrollment_ids(self.principal))
        )
        return await self.results_for(e)

    async def student_results(self, student_id: uuid.UUID) -> MyResultsResponse:
        e = await self._enrolment_of_student(
            student_id, enrollment_predicate(self.principal, StudentProgramEnrollment.id)
        )
        return await self.results_for(e)

    async def offering_results(self, oid: uuid.UUID) -> list[Any]:
        o = (
            await self.db.execute(
                select(CourseOffering).where(CourseOffering.id == oid, CourseOffering.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if o is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Offering not found")
        mine = bool((await self.db.execute(teaches(self.principal, o.id))).first()) if self.principal else True
        if not mine and not may_view_all(self.principal):
            raise APIError(404, ErrorCode.NOT_FOUND, "Offering not found")
        rows = list(
            (
                await self.db.execute(
                    select(StudentCourseResult).where(
                        StudentCourseResult.offering_id == o.id,
                        StudentCourseResult.is_current.is_(True),
                        StudentCourseResult.status == "published",
                    )
                )
            ).scalars()
        )
        return sorted(await self.rows_out(rows), key=lambda r: r.registration_number or "")

    # ---- registers ---------------------------------------------------------------------------------------------------
    async def _batch_rows(self, batch_id: uuid.UUID, term_id: uuid.UUID | None) -> list[StudentCourseResult]:
        q = (
            select(StudentCourseResult)
            .join(
                StudentProgramEnrollment,
                StudentProgramEnrollment.id == StudentCourseResult.student_program_enrollment_id,
            )
            .where(
                StudentProgramEnrollment.batch_id == batch_id,
                StudentCourseResult.is_current.is_(True),
                StudentCourseResult.status == "published",
                result_predicate(self.principal, "all"),
            )
        )
        if term_id:
            q = q.where(StudentCourseResult.term_id == term_id)
        return list((await self.db.execute(q)).scalars())

    async def tabulation(self, batch_id: uuid.UUID, term_id: uuid.UUID | None) -> list[TabulationRow]:
        rows = await self._batch_rows(batch_id, term_id)
        if not rows:
            return []
        codes = dict(
            (
                await self.db.execute(select(Course.id, Course.code).where(Course.id.in_({r.course_id for r in rows})))
            ).all()
        )
        studs = dict(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_({r.student_program_enrollment_id for r in rows}))
                )
            ).all()
        )
        tq = (
            select(StudentTermRecord.student_program_enrollment_id, StudentTermResult)
            .join(StudentTermResult, StudentTermResult.student_term_record_id == StudentTermRecord.id)
            .where(
                StudentTermRecord.student_program_enrollment_id.in_(set(studs)),
                StudentTermResult.is_current.is_(True),
                StudentTermResult.status == "published",
            )
        )
        if term_id:
            tq = tq.where(StudentTermRecord.term_id == term_id)
        terms: dict[uuid.UUID, StudentTermResult] = {}
        for e, t in (await self.db.execute(tq)).all():
            if e not in terms or (t.cumulative_credits or 0) >= (terms[e].cumulative_credits or 0):
                terms[e] = t
        grid: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
        for r in rows:
            grid[r.student_program_enrollment_id][codes.get(r.course_id, "?")] = r.letter_grade or r.result_status
        out = []
        for e, g in grid.items():
            st, t = studs.get(e), terms.get(e)
            out.append(
                TabulationRow(
                    enrollment_id=e,
                    registration_number=st.registration_number if st else None,
                    student_name=" ".join(x for x in (st.first_name, st.last_name) if x) if st else None,
                    courses=dict(sorted(g.items())),
                    sgpa=t.sgpa if t else None,
                    cgpa=t.cgpa if t else None,
                    credits_earned=t.cumulative_credits if t else None,
                    backlogs=t.backlog_count if t else 0,
                    result_class=t.result_class if t else None,
                )
            )
        return sorted(out, key=lambda x: x.registration_number or "")

    async def tabulation_xlsx(self, batch_id: uuid.UUID, term_id: uuid.UUID | None) -> bytes:
        import io

        from openpyxl import Workbook

        rows = await self.tabulation(batch_id, term_id)
        codes = sorted({c for r in rows for c in r.courses})
        wb = Workbook()
        ws = wb.active
        ws.title = "Tabulation"
        ws.append(["Reg. no", "Name", *codes, "SGPA", "CGPA", "Credits", "Backlogs", "Class"])
        for r in rows:
            ws.append(
                [
                    r.registration_number,
                    r.student_name,
                    *[r.courses.get(c, "") for c in codes],
                    float(r.sgpa) if r.sgpa is not None else None,
                    float(r.cgpa) if r.cgpa is not None else None,
                    float(r.credits_earned) if r.credits_earned is not None else None,
                    r.backlogs,
                    r.result_class,
                ]
            )
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    async def analysis(self, session_id: uuid.UUID | None, batch_id: uuid.UUID | None) -> ResultAnalysis:
        q = select(StudentCourseResult).where(
            StudentCourseResult.institution_id == self.inst,
            StudentCourseResult.is_current.is_(True),
            StudentCourseResult.status == "published",
            result_predicate(self.principal, "all"),
        )
        if session_id:
            q = q.where(StudentCourseResult.exam_session_id == session_id)
        if batch_id:
            q = q.where(
                StudentCourseResult.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.batch_id == batch_id)
                )
            )
        rows = list((await self.db.execute(q)).scalars())
        codes = dict(
            (
                await self.db.execute(
                    select(Course.id, Course.code).where(Course.id.in_({r.course_id for r in rows} or {uuid.uuid4()}))
                )
            ).all()
        )
        by_course: dict[uuid.UUID, list[StudentCourseResult]] = defaultdict(list)
        dist: dict[str, int] = defaultdict(int)
        for r in rows:
            by_course[r.course_id].append(r)
            dist[r.letter_grade or r.result_status] += 1
        per = [
            {
                "course_id": str(cid),
                "course": codes.get(cid),
                "appeared": len(rs),
                "passed": sum(1 for r in rs if r.result_status in PASSING),
                "pass_pct": round(100 * sum(1 for r in rs if r.result_status in PASSING) / len(rs), 2) if rs else None,
            }
            for cid, rs in by_course.items()
        ]
        students = {r.student_program_enrollment_id for r in rows}
        cleared = {
            e for e in students if all(r.result_status in PASSING for r in rows if r.student_program_enrollment_id == e)
        }
        toppers = await self._toppers(students, 10)
        return ResultAnalysis(
            pass_pct_by_course=sorted(per, key=lambda x: x["course"] or ""),
            grade_distribution=dict(sorted(dist.items())),
            toppers=toppers,
            students=len(students),
            pass_pct=round(100 * len(cleared) / len(students), 2) if students else None,
        )

    async def _toppers(self, enr_ids: set[uuid.UUID], n: int, term_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        if not enr_ids:
            return []
        q = (
            select(Student, StudentTermResult, StudentTermRecord.term_number)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
            .join(StudentTermRecord, StudentTermRecord.student_program_enrollment_id == StudentProgramEnrollment.id)
            .join(StudentTermResult, StudentTermResult.student_term_record_id == StudentTermRecord.id)
            .where(
                StudentProgramEnrollment.id.in_(enr_ids),
                StudentTermResult.is_current.is_(True),
                StudentTermResult.status == "published",
                StudentTermResult.backlog_count == 0,
            )
        )
        if term_id:
            q = q.where(StudentTermRecord.term_id == term_id)
        best: dict[uuid.UUID, tuple[Student, StudentTermResult, int]] = {}
        for st, t, tn in (await self.db.execute(q)).all():
            if st.id not in best or tn > best[st.id][2]:
                best[st.id] = (st, t, tn)
        key = (lambda v: v[1].sgpa or Decimal(0)) if term_id else (lambda v: v[1].cgpa or Decimal(0))
        ranked = sorted(best.values(), key=key, reverse=True)[:n]
        out = []
        rank, last = 0, None
        for i, (st, t, _) in enumerate(ranked, start=1):
            score = key((st, t, 0))
            if score != last:
                rank, last = i, score
            out.append(
                {
                    "rank": rank,
                    "registration_number": st.registration_number,
                    "name": " ".join(x for x in (st.first_name, st.last_name) if x),
                    "sgpa": float(t.sgpa) if t.sgpa is not None else None,
                    "cgpa": float(t.cgpa) if t.cgpa is not None else None,
                }
            )
        return out

    async def rank_list(self, batch_id: uuid.UUID, term_id: uuid.UUID | None, n: int = 50) -> list[dict[str, Any]]:
        enr = set(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id).where(
                        StudentProgramEnrollment.batch_id == batch_id,
                        enrollment_predicate(self.principal, StudentProgramEnrollment.id),
                    )
                )
            ).scalars()
        )
        return await self._toppers(enr, n, term_id)


async def public_lookup(db: Any, institution_id: uuid.UUID, reg_no: str, dob: Any) -> PublicLookupResponse:
    """Published, current term results of sessions published with ``audience='public'`` (masked name)."""
    from app.services.exams.common import mask

    st = (
        await db.execute(
            select(Student).where(
                Student.institution_id == institution_id,
                func.upper(Student.registration_number) == reg_no.strip().upper(),
                Student.dob == dob,
                Student.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if st is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "No published result for these details")
    public_runs = select(ResultPublication.run_id).where(
        ResultPublication.institution_id == institution_id, ResultPublication.audience == "public"
    )
    rows = (
        await db.execute(
            select(StudentTermResult, StudentTermRecord.term_number)
            .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == StudentTermRecord.student_program_enrollment_id
            )
            .join(ResultProcessingRun, ResultProcessingRun.id == StudentTermResult.run_id)
            .where(
                StudentProgramEnrollment.student_id == st.id,
                StudentTermResult.is_current.is_(True),
                StudentTermResult.status == "published",
                and_(ResultProcessingRun.id.in_(public_runs)),
            )
            .order_by(StudentTermRecord.term_number)
        )
    ).all()
    if not rows:
        raise APIError(404, ErrorCode.NOT_FOUND, "No published result for these details")
    return PublicLookupResponse(
        name=mask(" ".join(x for x in (st.first_name, st.last_name) if x)) or "",
        registration_number=st.registration_number,
        terms=[
            {
                "term_number": tn,
                "sgpa": float(t.sgpa) if t.sgpa is not None else None,
                "cgpa": float(t.cgpa) if t.cgpa is not None else None,
                "credits_earned": float(t.credits_earned),
                "result": "PASS" if t.backlog_count == 0 else f"{t.backlog_count} backlog(s)",
            }
            for t, tn in rows
        ],
    )
