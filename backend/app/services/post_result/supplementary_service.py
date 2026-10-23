"""Supplementary / arrear loop — Prompts/16 §16.6 ``supplementary_service`` ({results.supplementary}).

``preview(term, kind)`` lists the open arrears (``student_arrears.status='open'``, optionally only those failed in
``from_session_id``) grouped by course; ``create`` opens a Phase 14 session (``exam_kind`` supplementary | arrear) with
one theory paper per arrear course and builds the registrations through Phase 14 (``build_for`` → ``attempt_type
='arrear'``, ``attempt_number = attempts + 1``; fees per the session's ``fee_rules``). Results come back through a
Phase 15 ``supplementary_merge`` run (new attempts, CGPA per ``cgpa_attempt_policy``, arrears cleared on a pass).
"""

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError
from app.models.academic import AcademicTerm
from app.models.curriculum import Course
from app.models.registration import StudentArrear
from app.models.results import StudentCourseResult
from app.models.students import StudentProgramEnrollment
from app.schemas.exams import ExamPaperCreate, ExamSessionCreate
from app.schemas.post_result import SupplementaryCreateRequest, SupplementaryPreview
from app.services.post_result.common import PostResultBase


class SupplementaryService(PostResultBase):
    audit_module = "exams"

    async def _arrears(
        self, body: SupplementaryCreateRequest
    ) -> list[tuple[StudentArrear, StudentProgramEnrollment, Course]]:
        q = (
            select(StudentArrear, StudentProgramEnrollment, Course)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.id == StudentArrear.student_program_enrollment_id)
            .join(Course, Course.id == StudentArrear.course_id)
            .where(
                StudentArrear.institution_id == self.inst,
                StudentArrear.status == "open",
                StudentProgramEnrollment.status.in_(("active", "detained")),
            )
        )
        if body.from_session_id:
            q = q.where(
                StudentArrear.course_id.in_(
                    select(StudentCourseResult.course_id).where(
                        StudentCourseResult.exam_session_id == body.from_session_id
                    )
                )
            )
        colleges = self._college_ids()
        if colleges and not any(st == "institution" for st, _ in getattr(self.principal, "scopes", [])):
            q = q.where(StudentProgramEnrollment.college_id.in_(colleges))
        return list((await self.db.execute(q)).all())  # type: ignore[arg-type]

    async def preview(self, body: SupplementaryCreateRequest) -> SupplementaryPreview:
        rows = await self._arrears(body)
        by_course: dict[uuid.UUID, dict[str, Any]] = {}
        students: set[uuid.UUID] = set()
        for _a, e, c in rows:
            students.add(e.id)
            d = by_course.setdefault(
                c.id, {"course_id": str(c.id), "course_code": c.code, "course_title": c.title, "students": 0}
            )
            d["students"] += 1
        return SupplementaryPreview(
            students=len(students), papers=sorted(by_course.values(), key=lambda x: x["course_code"])
        )

    async def create(self, body: SupplementaryCreateRequest) -> dict[str, Any]:
        from app.services.exams.registration_service import ExamRegistrationService
        from app.services.exams.session_service import ExamSessionService

        rows = await self._arrears(body)
        if not rows:
            from app.services.exams.common import rule

            raise rule("No open arrears to examine", "NOTHING_TO_EXAMINE", 422)
        term = (await self.db.execute(select(AcademicTerm).where(AcademicTerm.id == body.term_id))).scalar_one()
        sessions = ExamSessionService(self.db, self.principal, self.request, self.inst)
        out = await sessions.create(
            ExamSessionCreate(
                name=body.name or f"{term.name} — {body.exam_kind.title()} examinations",
                term_id=term.id,
                exam_kind=body.exam_kind,
                fee_rules=body.fee_rules,
            )
        )
        courses: dict[uuid.UUID, Course] = {c.id: c for _, _, c in rows}
        papers = 0
        for c in sorted(courses.values(), key=lambda x: x.code):
            try:
                await sessions.create_paper(
                    out.id, ExamPaperCreate(course_id=c.id, paper_type="theory", paper_code=f"{c.code}-S"[:30])
                )
                papers += 1
            except APIError:
                continue
        regs = ExamRegistrationService(self.db, self.principal, self.request, self.inst)
        s = await regs.session(out.id, write=True)
        by_enrol: dict[uuid.UUID, StudentProgramEnrollment] = {}
        for _, e, _ in rows:
            by_enrol[e.id] = e
        built: defaultdict[str, int] = defaultdict(int)
        for e in by_enrol.values():
            reg = await regs.build_for(s, e)
            if reg.status != "draft":
                built["skipped"] += 1
                continue
            try:
                r = await regs._finalise(s, reg, e, None, skip_holds=True)
                built[r.status] += 1
            except APIError:
                built["skipped"] += 1
        await self._audit("supplementary_create", "exam_session", out.id, None, {"papers": papers, **built})
        await self._emit(
            "supplementary.session_created",
            {"session_id": str(out.id), "papers": papers, "students": len(by_enrol)},
            "exam_session",
            out.id,
        )
        return {"session_id": str(out.id), "papers": papers, "students": len(by_enrol), "registrations": dict(built)}
