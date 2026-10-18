"""Internal assessment — Prompts/13 §13.6 ``assessment_service``.

1. ``instantiate(offering)`` — the internal components (``cia`` / ``project_review``) of the offering's scheme
   (override → offering → course → regulation default) become ``offering_assessments``; deadline = today +
   ``assessment.marks_deadline_days``; idempotent on ``UNIQUE (offering_id, component_id)``.
2. Question map — parts / questions whose max marks sum to the assessment's ``max_marks`` (422 otherwise); COs must
   belong to the offering's course (422).
3. ``bulk_upsert`` — faculty of the offering while ``planned | conducted | marks_entry``; rows outside the roster are
   rejected with a reason; question-wise rows must sum to ``marks`` (or ``marks`` is computed); absent / exempt.
4. Chain ``submit`` (every rostered student has a mark / absent / exempt, else 409 with the list) → ``verify`` (HOD;
   reject returns to ``marks_entry``) → ``lock`` (exam cell / COE; Beat ``assessment.auto_lock`` locks verified
   assessments ``assessment.auto_lock_days`` after the deadline) → ``marks.locked`` (Phase 11 eligibility / Phase 17).
5. ``consolidate`` — per component ``marks / max × scaled_to``; ``best_of {take, of, group}`` keeps the best ``take``
   of a group; ``cia_scaled = cia_total / Σ counted scaled_to × cia_max``; HOD approve → lock → university submission
   (``college_data_submissions(type='cia_marks')``) for ``exam_authority='university'`` programmes.
6. Change requests after lock — workflow ``marks.change`` (HOD → COE) → ``apply`` writes through the single write
   path (``force``) and recomputes an unlocked consolidation; a locked consolidation → 409 ``RECORD_LOCKED``.
"""
# mypy: disable-error-code="arg-type"

import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.assessment import EDITABLE, INTERNAL_CATEGORIES
from app.models.assessment import (
    AssessmentQuestion,
    CiaConsolidation,
    CollegeDataSubmission,
    InternalMark,
    MarksChangeRequest,
    OfferingAssessment,
)
from app.models.curriculum import AssessmentComponent, AssessmentScheme, Course
from app.models.obe import CourseOutcome
from app.models.offerings import CourseOffering
from app.models.platform import WorkflowInstance
from app.models.students import Student, StudentProgramEnrollment
from app.repositories.assessment_scope import learner_offering_ids
from app.schemas.assessment import (
    AssessmentQuestionOut,
    ChangeRequestCreate,
    ChangeRequestOut,
    CiaRow,
    ConsolidateResponse,
    InstantiateRequest,
    InstantiateResult,
    MarksBulkUpsert,
    MarksGridResponse,
    MarksGridRow,
    MarksResult,
    MyMarksRow,
    OfferingAssessmentResponse,
    QuestionMapReplace,
    VerifyRequest,
)
from app.services.assessment.common import AssessmentBase, now_utc, q2, rule, student_name

ENTITY = "offering_assessment"
CR_ENTITY = "marks_change_request"
WF_CHANGE = "marks.change"


class AssessmentService(AssessmentBase):
    # ---- reads -----------------------------------------------------------------------------------------------------------
    async def get_assessment(
        self, aid: uuid.UUID, *, for_update: bool = False
    ) -> tuple[OfferingAssessment, CourseOffering]:
        a = (
            await self.db.execute(
                select(OfferingAssessment).where(
                    OfferingAssessment.id == aid, OfferingAssessment.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Assessment not found")
        offering = await self.offering(a.offering_id)
        if for_update:
            a = (
                await self.db.execute(select(OfferingAssessment).where(OfferingAssessment.id == aid).with_for_update())
            ).scalar_one()
        return a, offering

    async def outs(self, rows: list[OfferingAssessment], roster: int | None = None) -> list[OfferingAssessmentResponse]:
        ids = [r.id for r in rows]
        comps = (
            {
                c.id: c
                for c in (
                    await self.db.execute(
                        select(AssessmentComponent).where(AssessmentComponent.id.in_([r.component_id for r in rows]))
                    )
                ).scalars()
            }
            if rows
            else {}
        )
        qc: dict[Any, Any] = (
            dict(
                (
                    await self.db.execute(
                        select(AssessmentQuestion.offering_assessment_id, func.count())
                        .where(AssessmentQuestion.offering_assessment_id.in_(ids))
                        .group_by(AssessmentQuestion.offering_assessment_id)
                    )
                ).all()
            )
            if ids
            else {}
        )
        mc: dict[Any, Any] = (
            dict(
                (
                    await self.db.execute(
                        select(InternalMark.offering_assessment_id, func.count())
                        .where(InternalMark.offering_assessment_id.in_(ids))
                        .group_by(InternalMark.offering_assessment_id)
                    )
                ).all()
            )
            if ids
            else {}
        )
        out = []
        for r in rows:
            o = OfferingAssessmentResponse.model_validate(r)
            c = comps.get(r.component_id)
            if c is not None:
                o.component_code, o.category = c.code, c.category
                o.scaled_to = float(c.scaled_to) if c.scaled_to is not None else None
            o.question_count, o.marks_entered = int(qc.get(r.id, 0)), int(mc.get(r.id, 0))
            o.roster = roster or 0
            out.append(o)
        return out

    async def list_for(self, offering_id: uuid.UUID) -> list[OfferingAssessmentResponse]:
        offering = await self.offering(offering_id)
        rows = list(
            (
                await self.db.execute(
                    select(OfferingAssessment)
                    .where(OfferingAssessment.offering_id == offering.id)
                    .order_by(OfferingAssessment.created_at)
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(rows, len(await self.roster_ids(offering)))

    async def queue(self, status: str | None, scope: str | None) -> list[OfferingAssessmentResponse]:
        """Assessments across the caller's visible offerings (HOD verification / exam-cell lock queues)."""
        from app.repositories.assessment_scope import visible_offering_ids

        q = (
            select(OfferingAssessment, CourseOffering, Course)
            .join(CourseOffering, CourseOffering.id == OfferingAssessment.offering_id)
            .join(Course, Course.id == CourseOffering.course_id)
            .where(OfferingAssessment.institution_id == self.inst, OfferingAssessment.offering_id.in_(visible_offering_ids(self.principal, "marks", scope)))
        )
        if status:
            q = q.where(OfferingAssessment.status == status)
        rows = (await self.db.execute(q.order_by(OfferingAssessment.submitted_at.desc().nulls_last()).limit(500))).all()
        outs = await self.outs([r[0] for r in rows])
        for o, (_, off, course) in zip(outs, rows, strict=True):
            o.course_code, o.course_title, o.section_code = course.code, course.title, off.section_code
        return outs

    # ---- 1. instantiate ---------------------------------------------------------------------------------------------------
    async def scheme_for(self, offering: CourseOffering, override: uuid.UUID | None = None) -> AssessmentScheme | None:
        course = await self.course(offering.course_id)
        sid = override or offering.assessment_scheme_id or course.assessment_scheme_id
        if sid:
            return (
                await self.db.execute(select(AssessmentScheme).where(AssessmentScheme.id == sid))
            ).scalar_one_or_none()
        rows = (
            (
                await self.db.execute(
                    select(AssessmentScheme)
                    .where(
                        AssessmentScheme.regulation_id == course.regulation_id, AssessmentScheme.deleted_at.is_(None)
                    )
                    .order_by(AssessmentScheme.is_default.desc())
                )
            )
            .scalars()
            .all()
        )
        for s in rows:
            if not s.applies_to_course_types or course.course_type in s.applies_to_course_types:
                return s
        return rows[0] if rows else None

    async def instantiate(
        self, offering_id: uuid.UUID, body: InstantiateRequest | None = None, *, system: bool = False
    ) -> InstantiateResult:
        offering = (
            await self.offering(offering_id)
            if not system
            else (await self.db.execute(select(CourseOffering).where(CourseOffering.id == offering_id))).scalar_one()
        )
        if not system:
            await self.require_teacher(offering)
        scheme = await self.scheme_for(offering, body.scheme_override_id if body else None)
        if scheme is None:
            raise rule("No assessment scheme applies to this offering", "NO_SCHEME", 422)
        comps = (
            (
                await self.db.execute(
                    select(AssessmentComponent)
                    .where(AssessmentComponent.scheme_id == scheme.id)
                    .order_by(AssessmentComponent.sequence)
                )
            )
            .scalars()
            .all()
        )
        existing = {
            r.component_id: r
            for r in (
                await self.db.execute(select(OfferingAssessment).where(OfferingAssessment.offering_id == offering.id))
            ).scalars()
        }
        days = int(await self.setting("assessment", "marks_deadline_days") or 14)
        out = InstantiateResult()
        for c in comps:
            if c.category not in INTERNAL_CATEGORIES:
                continue
            if c.id in existing:
                out.existing += 1
                continue
            self.db.add(
                OfferingAssessment(
                    institution_id=self.inst,
                    offering_id=offering.id,
                    component_id=c.id,
                    name=c.name[:80],
                    max_marks=Decimal(c.max_marks),
                    marks_entry_deadline=(await self.today()) + timedelta(days=days),
                    status="planned",
                )
            )
            out.created += 1
        await self.db.flush()
        if out.created:
            await self._audit(
                "instantiate", "course_offering", offering.id, None, {"scheme": scheme.code, "created": out.created}
            )
            await self._emit(
                "assessment.instantiated",
                {"offering_id": str(offering.id), "created": out.created},
                "course_offering",
                offering.id,
            )
        if not system:
            out.assessments = await self.list_for(offering.id)
        return out

    # ---- 2. question map -----------------------------------------------------------------------------------------------
    async def questions(self, aid: uuid.UUID) -> list[AssessmentQuestionOut]:
        a, _ = await self.get_assessment(aid)
        rows = (
            await self.db.execute(
                select(AssessmentQuestion, CourseOutcome.code)
                .outerjoin(CourseOutcome, CourseOutcome.id == AssessmentQuestion.co_id)
                .where(AssessmentQuestion.offering_assessment_id == a.id)
                .order_by(AssessmentQuestion.part, AssessmentQuestion.question_no)
            )
        ).all()
        out = []
        for q, code in rows:
            o = AssessmentQuestionOut.model_validate(q)
            o.co_code = code
            out.append(o)
        return out

    async def replace_questions(self, aid: uuid.UUID, body: QuestionMapReplace) -> list[AssessmentQuestionOut]:
        a, offering = await self.get_assessment(aid, for_update=True)
        await self.require_teacher(offering)
        if a.status not in EDITABLE:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Assessment is {a.status}")
        total = sum(q2(q.max_marks) for q in body.questions)
        if total != q2(a.max_marks):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Question marks sum to {total}, the assessment is out of {a.max_marks}",
                {"code": "SUM_MISMATCH", "sum": float(total)},
            )
        if len({q.question_no for q in body.questions}) != len(body.questions):
            raise APIError(422, ErrorCode.VALIDATION, "Duplicate question numbers")
        cos = set((
                await self.db.execute(select(CourseOutcome.id).where(CourseOutcome.course_id == offering.course_id))
            ).scalars())
        bad = [q.question_no for q in body.questions if q.co_id and q.co_id not in cos]
        if bad:
            raise APIError(
                422, ErrorCode.VALIDATION, "CO does not belong to this course", {"code": "FOREIGN_CO", "questions": bad}
            )
        for old in (
            await self.db.execute(select(AssessmentQuestion).where(AssessmentQuestion.offering_assessment_id == a.id))
        ).scalars():
            await self.db.delete(old)
        await self.db.flush()
        for q in body.questions:
            self.db.add(
                AssessmentQuestion(
                    institution_id=self.inst,
                    offering_assessment_id=a.id,
                    question_no=q.question_no,
                    max_marks=q2(q.max_marks),
                    co_id=q.co_id,
                    bloom_level=q.bloom_level,
                    part=q.part,
                )
            )
        await self.db.flush()
        await self._audit("question_map", ENTITY, a.id, None, {"questions": len(body.questions)})
        return await self.questions(a.id)

    # ---- 3. grid / bulk ------------------------------------------------------------------------------------------------
    async def grid(self, aid: uuid.UUID) -> MarksGridResponse:
        a, offering = await self.get_assessment(aid)
        roster = await self.roster(offering)
        teacher = await self.is_teacher(offering.id)
        staff_reader = (
            teacher or self.can("marks", "view_all") or self.can("marks", "verify") or self.can("marks", "lock")
        )
        if not staff_reader:
            mine = await self.my_enrolment_ids()
            roster = [r for r in roster if r[0] in mine]
            if a.status not in ("verified", "locked") and not self.can("marks", "enter"):
                roster = list(roster)  # learners see their row once entered; values stay hidden below
        marks = {
            m.student_program_enrollment_id: m
            for m in (
                await self.db.execute(select(InternalMark).where(InternalMark.offering_assessment_id == a.id))
            ).scalars()
        }
        qs = await self.questions(a.id)
        rows = []
        for r in roster:
            m = marks.get(r[0])
            rows.append(
                MarksGridRow(
                    student_program_enrollment_id=r[0],
                    mark_id=m.id if m else None,
                    registration_number=r[4],
                    roll_number=r[5],
                    name=" ".join(x for x in (r[2], r[3]) if x),
                    marks=float(m.marks) if m and m.marks is not None else None,
                    is_absent=bool(m and m.is_absent),
                    is_exempt=bool(m and m.is_exempt),
                    question_wise={k: v for k, v in (m.question_wise or {}).items() if not k.startswith("_")}
                    if m
                    else None,
                    version=m.version if m else None,
                )
            )
        co_sum: dict[str, list[float]] = defaultdict(list)
        qmax = {q.question_no: (q.co_code, q.max_marks) for q in qs}
        for row in rows:
            for qn, v in (row.question_wise or {}).items():
                code, mx = qmax.get(qn, (None, 0))
                if code and mx:
                    co_sum[code].append(float(v) / float(mx) * 100)
        return MarksGridResponse(
            assessment=(await self.outs([a], len(roster)))[0],
            questions=qs,
            rows=rows,
            co_summary={k: round(sum(v) / len(v), 2) for k, v in co_sum.items() if v},
            read_only=not teacher or a.status not in EDITABLE,
        )

    async def bulk_upsert(self, aid: uuid.UUID, body: MarksBulkUpsert) -> MarksResult:
        a, offering = await self.get_assessment(aid, for_update=True)
        await self.require_teacher(offering)
        if a.status not in EDITABLE:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"Assessment is {a.status}", {"status": a.status})
        roster = await self.roster_ids(offering)
        qmax = {q.question_no: Decimal(str(q.max_marks)) for q in await self.questions(a.id)}
        out = MarksResult(status=a.status)
        for row in body.rows:
            eid = row.student_program_enrollment_id
            if eid not in roster:
                out.rejected.append({"student_program_enrollment_id": str(eid), "reason": "not on the roster"})
                continue
            marks = row.marks
            if row.is_absent or row.is_exempt:
                marks = None
            elif row.question_wise:
                bad = [
                    k
                    for k, v in row.question_wise.items()
                    if k not in qmax or Decimal(str(v)) < 0 or Decimal(str(v)) > qmax[k]
                ]
                if bad:
                    out.rejected.append(
                        {
                            "student_program_enrollment_id": str(eid),
                            "reason": f"question marks out of range / unknown: {', '.join(bad)}",
                        }
                    )
                    continue
                total = sum(Decimal(str(v)) for v in row.question_wise.values())
                if marks is not None and q2(marks) != q2(total):
                    out.rejected.append(
                        {
                            "student_program_enrollment_id": str(eid),
                            "reason": f"question-wise sum {total} ≠ marks {marks}",
                        }
                    )
                    continue
                marks = float(total)
            if marks is not None and (marks < 0 or Decimal(str(marks)) > Decimal(str(a.max_marks))):
                out.rejected.append(
                    {"student_program_enrollment_id": str(eid), "reason": f"marks must be within 0–{a.max_marks}"}
                )
                continue
            await self.write_internal_mark(
                a, eid, marks, is_absent=row.is_absent, is_exempt=row.is_exempt, question_wise=row.question_wise
            )
            out.saved += 1
        out.status = a.status
        await self._audit(
            "marks_upsert",
            ENTITY,
            a.id,
            None,
            {"saved": out.saved, "rejected": len(out.rejected), "source": body.source or "grid"},
        )
        return out

    # ---- 4. chain ------------------------------------------------------------------------------------------------------
    async def submit(self, aid: uuid.UUID) -> OfferingAssessmentResponse:
        a, offering = await self.get_assessment(aid, for_update=True)
        await self.require_teacher(offering)
        if a.status not in EDITABLE:
            raise APIError(409, ErrorCode.CONFLICT, f"Assessment is {a.status}")
        roster = await self.roster(offering)
        have = {
            m.student_program_enrollment_id
            for m in (
                await self.db.execute(select(InternalMark).where(InternalMark.offering_assessment_id == a.id))
            ).scalars()
            if m.marks is not None or m.is_absent or m.is_exempt
        }
        missing = [
            {"student_program_enrollment_id": str(r[0]), "registration_number": r[4]}
            for r in roster
            if r[0] not in have
        ]
        if missing:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"{len(missing)} student(s) have no mark / absent / exempt",
                {"code": "MARKS_MISSING", "missing": missing[:200]},
            )
        a.status, a.submitted_by, a.submitted_at = "submitted", self.actor_id, now_utc()
        a.version += 1
        await self.db.flush()
        await self._audit("submit", ENTITY, a.id, {"status": "marks_entry"}, {"status": "submitted"})
        await self._emit(
            "marks.submitted", {"offering_assessment_id": str(a.id), "offering_id": str(offering.id)}, ENTITY, a.id
        )
        return (await self.outs([a], len(roster)))[0]

    async def verify(self, aid: uuid.UUID, body: VerifyRequest) -> OfferingAssessmentResponse:
        a, offering = await self.get_assessment(aid, for_update=True)
        if a.status != "submitted":
            raise APIError(409, ErrorCode.CONFLICT, f"Assessment is {a.status}")
        if body.decision == "reject":
            a.status = "marks_entry"
            await self._audit(
                "verify_reject",
                ENTITY,
                a.id,
                {"status": "submitted"},
                {"status": "marks_entry", "comment": body.comment},
            )
        else:
            a.status, a.verified_by, a.verified_at = "verified", self.actor_id, now_utc()
            await self._audit(
                "verify", ENTITY, a.id, {"status": "submitted"}, {"status": "verified", "comment": body.comment}
            )
            await self._emit(
                "marks.verified", {"offering_assessment_id": str(a.id), "offering_id": str(offering.id)}, ENTITY, a.id
            )
        a.version += 1
        await self.db.flush()
        return (await self.outs([a]))[0]

    async def lock(self, aid: uuid.UUID, *, system: bool = False) -> OfferingAssessmentResponse:
        a, offering = (
            await self.get_assessment(aid, for_update=True)
            if not system
            else (
                (
                    await self.db.execute(
                        select(OfferingAssessment).where(OfferingAssessment.id == aid).with_for_update()
                    )
                ).scalar_one(),
                None,
            )
        )
        if a.status != "verified":
            raise APIError(409, ErrorCode.CONFLICT, f"Only verified marks can be locked (status {a.status})")
        a.status, a.locked_by, a.locked_at = "locked", self.actor_id, now_utc()
        a.version += 1
        await self.db.flush()
        await self._audit("lock", ENTITY, a.id, {"status": "verified"}, {"status": "locked", "auto": system})
        await self._emit(
            "marks.locked", {"offering_assessment_id": str(a.id), "offering_id": str(a.offering_id)}, ENTITY, a.id
        )
        del offering
        return (await self.outs([a]))[0]

    async def reopen(self, aid: uuid.UUID, reason: str) -> OfferingAssessmentResponse:
        a, _ = await self.get_assessment(aid, for_update=True)
        if a.status not in ("submitted", "verified", "locked"):
            raise APIError(409, ErrorCode.CONFLICT, f"Assessment is {a.status}")
        old = a.status
        a.status, a.locked_at, a.locked_by = "marks_entry", None, None
        a.version += 1
        await self.db.flush()
        await self._audit("reopen", ENTITY, a.id, {"status": old}, {"status": "marks_entry", "reason": reason})
        return (await self.outs([a]))[0]

    async def auto_lock(self) -> int:
        days = int(await self.setting("assessment", "auto_lock_days") or 7)
        cutoff = (await self.today()) - timedelta(days=days)
        rows = (
            (
                await self.db.execute(
                    select(OfferingAssessment.id).where(
                        OfferingAssessment.institution_id == self.inst,
                        OfferingAssessment.status == "verified",
                        OfferingAssessment.marks_entry_deadline < cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        for aid in rows:
            await self.lock(aid, system=True)
        return len(rows)

    async def deadline_reminders(self) -> int:
        from app.models.hr import Staff
        from app.models.offerings import CourseOfferingFaculty

        soon = (await self.today()) + timedelta(days=2)
        rows = (
            await self.db.execute(
                select(OfferingAssessment, Staff.user_id)
                .join(CourseOfferingFaculty, CourseOfferingFaculty.offering_id == OfferingAssessment.offering_id)
                .join(Staff, Staff.id == CourseOfferingFaculty.staff_id)
                .where(
                    OfferingAssessment.institution_id == self.inst,
                    OfferingAssessment.status.in_(tuple(EDITABLE)),
                    OfferingAssessment.marks_entry_deadline == soon,
                )
            )
        ).all()
        for a, uid in rows:
            await self._notify("marks.deadline", [uid], {"assessment": a.name, "deadline": soon.isoformat()})
        return len(rows)

    async def my_marks(self, term_id: uuid.UUID | None) -> list[MyMarksRow]:
        mine = await self.my_enrolment_ids()
        if not mine:
            return []
        q = (
            select(OfferingAssessment, InternalMark, CourseOffering, Course)
            .join(CourseOffering, CourseOffering.id == OfferingAssessment.offering_id)
            .join(Course, Course.id == CourseOffering.course_id)
            .outerjoin(
                InternalMark,
                (InternalMark.offering_assessment_id == OfferingAssessment.id)
                & InternalMark.student_program_enrollment_id.in_(list(mine)),
            )
            .where(OfferingAssessment.offering_id.in_(learner_offering_ids(self.principal)))
            .order_by(Course.code, OfferingAssessment.created_at)
        )
        if term_id:
            q = q.where(CourseOffering.term_id == term_id)
        by: dict[uuid.UUID, MyMarksRow] = {}
        for a, m, o, c in (await self.db.execute(q)).all():
            row = by.setdefault(o.id, MyMarksRow(offering_id=o.id, course_code=c.code, course_title=c.title))
            row.components.append(
                {
                    "assessment_id": str(a.id),
                    "name": a.name,
                    "max_marks": float(a.max_marks),
                    "status": a.status,
                    "marks": float(m.marks) if m and m.marks is not None else None,
                    "is_absent": bool(m and m.is_absent),
                }
            )
        cia = (
            (
                await self.db.execute(
                    select(CiaConsolidation).where(
                        CiaConsolidation.offering_id.in_(list(by)),
                        CiaConsolidation.student_program_enrollment_id.in_(list(mine)),
                    )
                )
            )
            .scalars()
            .all()
            if by
            else []
        )
        for c in cia:
            if c.offering_id in by:
                by[c.offering_id].cia_scaled = float(c.cia_scaled)
                by[c.offering_id].cia_max = float((c.component_breakdown or {}).get("_cia_max") or 0) or None
        return list(by.values())

    # ---- 5. consolidation -------------------------------------------------------------------------------------------------
    async def cia_max_of(self, offering: CourseOffering) -> Decimal:
        scheme = await self.scheme_for(offering)
        course = await self.course(offering.course_id)
        return Decimal(course.cia_max or (scheme.cia_max if scheme else 40))

    async def compute(self, offering: CourseOffering) -> list[dict[str, Any]]:
        assessments = (
            await self.db.execute(
                select(OfferingAssessment, AssessmentComponent)
                .join(AssessmentComponent, AssessmentComponent.id == OfferingAssessment.component_id)
                .where(OfferingAssessment.offering_id == offering.id)
            )
        ).all()
        marks: dict[uuid.UUID, dict[uuid.UUID, Any]] = defaultdict(dict)
        for m in (
            await self.db.execute(
                select(InternalMark).where(
                    InternalMark.offering_assessment_id.in_([a.id for a, _ in assessments] or [uuid.uuid4()])
                )
            )
        ).scalars():
            marks[m.student_program_enrollment_id][m.offering_assessment_id] = m
        cia_max = await self.cia_max_of(offering)
        out = []
        for r in await self.roster(offering):
            eid = r[0]
            parts: dict[str, Any] = {}
            groups: dict[str, list[tuple[Decimal, Decimal, str]]] = defaultdict(list)
            plain: list[tuple[Decimal, Decimal]] = []
            for a, c in assessments:
                mk = marks[eid].get(a.id)
                scaled_to = Decimal(str(c.scaled_to)) if c.scaled_to is not None else Decimal(str(a.max_marks))
                got = Decimal(str(mk.marks)) if mk and mk.marks is not None else Decimal(0)
                value = q2(got / Decimal(str(a.max_marks)) * scaled_to) if Decimal(str(a.max_marks)) else Decimal(0)
                if mk and mk.is_exempt:
                    parts[c.code] = {"marks": None, "exempt": True, "scaled_to": float(scaled_to)}
                    continue
                parts[c.code] = {
                    "marks": float(got) if mk and mk.marks is not None else None,
                    "absent": bool(mk and mk.is_absent),
                    "value": float(value),
                    "scaled_to": float(scaled_to),
                }
                if c.best_of:
                    groups[str(c.best_of.get("group") or c.best_of.get("of") or "best")].append(
                        (value, scaled_to, c.code)
                    )
                else:
                    plain.append((value, scaled_to))
            for gname, items in groups.items():
                take = 0
                for _a, c in assessments:
                    if c.best_of and str(c.best_of.get("group") or c.best_of.get("of") or "best") == gname:
                        take = int(c.best_of.get("take") or len(items))
                best = sorted(items, key=lambda x: x[0], reverse=True)[: take or len(items)]
                for v, s, code in best:
                    plain.append((v, s))
                    parts[code]["counted"] = True
                for _v, _s, code in items:
                    parts[code].setdefault("counted", False)
                parts[f"_best_of_{gname}"] = {"take": take, "of": len(items)}
            total = sum((v for v, _ in plain), Decimal(0))
            denom = sum((s for _, s in plain), Decimal(0))
            scaled = q2(total / denom * cia_max) if denom else Decimal(0)
            parts["_cia_max"] = float(cia_max)
            out.append(
                {
                    "enrol": eid,
                    "reg": r[4],
                    "name": " ".join(x for x in (r[2], r[3]) if x),
                    "breakdown": parts,
                    "total": q2(total),
                    "scaled": scaled,
                }
            )
        return out

    async def consolidation(self, offering_id: uuid.UUID, *, recompute: bool = False) -> ConsolidateResponse:
        offering = await self.offering(offering_id)
        existing = {
            c.student_program_enrollment_id: c
            for c in (
                await self.db.execute(
                    select(CiaConsolidation).where(CiaConsolidation.offering_id == offering.id).with_for_update()
                )
            ).scalars()
        }
        if recompute:
            if not (await self.is_teacher(offering.id) or self.can("marks", "verify") or self.can("marks", "lock")):
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the offering's faculty / HOD may consolidate")
            if any(c.status in ("locked", "submitted_to_university") for c in existing.values()):
                raise APIError(409, ErrorCode.RECORD_LOCKED, "CIA is locked for this offering")
            for row in await self.compute(offering):
                c = existing.get(row["enrol"])
                if c is None:
                    c = CiaConsolidation(
                        institution_id=self.inst,
                        offering_id=offering.id,
                        student_program_enrollment_id=row["enrol"],
                        component_breakdown=row["breakdown"],
                        cia_total=row["total"],
                        cia_scaled=row["scaled"],
                        status="computed",
                    )
                    self.db.add(c)
                    existing[row["enrol"]] = c
                else:
                    c.component_breakdown, c.cia_total, c.cia_scaled, c.status, c.computed_at = (
                        row["breakdown"],
                        row["total"],
                        row["scaled"],
                        "computed",
                        now_utc(),
                    )
            await self.db.flush()
            await self._audit("cia_consolidate", "course_offering", offering.id, None, {"rows": len(existing)})
            await self._emit(
                "cia.consolidated",
                {"offering_id": str(offering.id), "rows": len(existing)},
                "course_offering",
                offering.id,
            )
        names = {
            e: (s.registration_number, student_name(s))
            for e, s in (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_(list(existing) or [uuid.uuid4()]))
                )
            ).all()
        }
        staff = await self.is_teacher(offering.id) or self.can("marks", "view_all") or self.can("marks", "verify")
        mine = await self.my_enrolment_ids() if not staff else set()
        rows = [
            CiaRow(
                student_program_enrollment_id=e,
                registration_number=names.get(e, (None, None))[0],
                name=names.get(e, (None, None))[1],
                component_breakdown=c.component_breakdown,
                cia_total=float(c.cia_total),
                cia_scaled=float(c.cia_scaled),
                status=c.status,
            )
            for e, c in existing.items()
            if staff or e in mine
        ]
        statuses = {r.status for r in rows}
        return ConsolidateResponse(
            offering_id=offering.id,
            cia_max=float(await self.cia_max_of(offering)),
            rows=sorted(rows, key=lambda r: r.registration_number or ""),
            status=next(iter(statuses)) if len(statuses) == 1 else ("mixed" if statuses else None),
        )

    async def _cia_move(self, offering_id: uuid.UUID, frm: tuple[str, ...], to: str) -> ConsolidateResponse:
        offering = await self.offering(offering_id)
        rows = (
            (
                await self.db.execute(
                    select(CiaConsolidation).where(CiaConsolidation.offering_id == offering.id).with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise rule("Consolidate first", "NOT_CONSOLIDATED")
        bad = [r for r in rows if r.status not in frm]
        if bad:
            raise APIError(409, ErrorCode.CONFLICT, f"{len(bad)} row(s) are not {'/'.join(frm)}")
        for r in rows:
            r.status = to
            if to == "locked":
                r.locked_by, r.locked_at = self.actor_id, now_utc()
        await self.db.flush()
        await self._audit(
            f"cia_{to}", "course_offering", offering.id, {"status": frm[0]}, {"status": to, "rows": len(rows)}
        )
        return await self.consolidation(offering.id)

    async def approve_cia(self, offering_id: uuid.UUID) -> ConsolidateResponse:
        return await self._cia_move(offering_id, ("computed",), "hod_approved")

    async def lock_cia(self, offering_id: uuid.UUID) -> ConsolidateResponse:
        out = await self._cia_move(offering_id, ("hod_approved",), "locked")
        await self._emit("cia.locked", {"offering_id": str(offering_id)}, "course_offering", offering_id)
        return out

    async def submit_to_university(self, offering_id: uuid.UUID) -> ConsolidateResponse:
        offering = await self.offering(offering_id)
        if not await self.is_university_program(offering):
            raise rule("Only university-examined programmes submit CIA to the university", "NOT_AFFILIATED", 422)
        out = await self._cia_move(offering_id, ("locked",), "submitted_to_university")
        sub = (
            await self.db.execute(
                select(CollegeDataSubmission)
                .where(
                    CollegeDataSubmission.college_id == offering.college_id,
                    CollegeDataSubmission.term_id == offering.term_id,
                    CollegeDataSubmission.submission_type == "cia_marks",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if sub is None:
            sub = CollegeDataSubmission(
                institution_id=self.inst,
                college_id=offering.college_id,
                term_id=offering.term_id,
                submission_type="cia_marks",
                status="submitted",
                record_count=0,
            )
            self.db.add(sub)
        sub.record_count = int(sub.record_count or 0) + len(out.rows)
        sub.status, sub.submitted_by, sub.submitted_at = "submitted", self.actor_id, now_utc()
        await self.db.flush()
        await self._emit(
            "cia.submitted_to_university",
            {"offering_id": str(offering_id), "rows": len(out.rows)},
            "course_offering",
            offering_id,
        )
        return out

    # ---- 6. change requests --------------------------------------------------------------------------------------------
    async def cr_outs(self, rows: list[MarksChangeRequest]) -> list[ChangeRequestOut]:
        acts = await self.actionable([r.workflow_instance_id for r in rows])
        out = []
        for r in rows:
            o = ChangeRequestOut.model_validate(r)
            m = (
                await self.db.execute(
                    select(InternalMark, OfferingAssessment, Student)
                    .join(OfferingAssessment, OfferingAssessment.id == InternalMark.offering_assessment_id)
                    .join(
                        StudentProgramEnrollment,
                        StudentProgramEnrollment.id == InternalMark.student_program_enrollment_id,
                    )
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(InternalMark.id == r.target_id)
                )
            ).first()
            if m:
                o.assessment_name, o.student_name = m[1].name, student_name(m[2])
            o.can_act = r.workflow_instance_id in acts or (r.status == "coe_approved" and self.can("marks", "lock"))
            out.append(o)
        return out

    async def create_change(self, body: ChangeRequestCreate) -> ChangeRequestOut:
        m = (
            await self.db.execute(
                select(InternalMark).where(InternalMark.id == body.target_id, InternalMark.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if m is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Mark not found")
        a, offering = await self.get_assessment(m.offering_assessment_id)
        if not (await self.is_teacher(offering.id) or self.can("marks", "verify")):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Only the offering's faculty or the HOD may request a change"
            )
        if a.status not in ("verified", "locked"):
            raise rule("Edit the marks directly — the assessment is not locked", "NOT_LOCKED")
        new = body.new_value
        if "marks" in new and new["marks"] is not None and not (0 <= float(new["marks"]) <= float(a.max_marks)):
            raise APIError(422, ErrorCode.VALIDATION, "New marks out of range")
        r = MarksChangeRequest(
            institution_id=self.inst,
            target_type="internal_mark",
            target_id=m.id,
            old_value={"marks": float(m.marks) if m.marks is not None else None, "is_absent": m.is_absent},
            new_value=new,
            reason=body.reason,
            evidence_url=body.evidence_url,
            requested_by=self.actor_id or uuid.UUID(int=0),
            status="requested",
        )
        self.db.add(r)
        await self.db.flush()
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_CHANGE,
                entity_type=CR_ENTITY,
                entity_id=r.id,
                started_by=self.actor_id,
                context={"department_id": str(offering.department_id)},
                title=f"Marks change · {a.name}",
            )
            r.workflow_instance_id = wf.id
        except APIError:
            pass
        await self.db.flush()
        await self._audit("change_request", CR_ENTITY, r.id, r.old_value, {"new": new, "reason": body.reason})
        return (await self.cr_outs([r]))[0]

    async def list_changes(self, status: str | None) -> list[ChangeRequestOut]:
        q = select(MarksChangeRequest).where(MarksChangeRequest.institution_id == self.inst)
        if status:
            q = q.where(MarksChangeRequest.status == status)
        if not (self.can("marks", "view_all") or self.can("marks", "lock") or self.can("marks", "verify")):
            q = q.where(MarksChangeRequest.requested_by == self.actor_id)
        return await self.cr_outs(
            list((await self.db.execute(q.order_by(MarksChangeRequest.created_at.desc()).limit(300))).scalars().all())
        )

    async def _cr(self, rid: uuid.UUID) -> MarksChangeRequest:
        r = (
            await self.db.execute(
                select(MarksChangeRequest)
                .where(MarksChangeRequest.id == rid, MarksChangeRequest.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Change request not found")
        return r

    async def decide_change(self, rid: uuid.UUID, approve: bool, comment: str | None) -> ChangeRequestOut:
        r = await self._cr(rid)
        if r.status not in ("requested", "hod_approved"):
            raise APIError(409, ErrorCode.CONFLICT, f"Request is {r.status}")
        if r.workflow_instance_id:
            await workflow_engine.act(
                self.db,
                instance_id=r.workflow_instance_id,
                actor=self.principal,
                decision="approve" if approve else "reject",
                comment=comment,
            )
            await self.db.refresh(r)
        else:
            r.status = ("coe_approved" if r.status == "hod_approved" else "hod_approved") if approve else "rejected"
            await self.db.flush()
        return (await self.cr_outs([r]))[0]

    async def apply_change(self, rid: uuid.UUID) -> ChangeRequestOut:
        r = await self._cr(rid)
        if r.status != "coe_approved":
            raise rule("Only a COE-approved request can be applied", "NOT_APPROVED")
        m = (
            await self.db.execute(select(InternalMark).where(InternalMark.id == r.target_id).with_for_update())
        ).scalar_one()
        a = (
            await self.db.execute(select(OfferingAssessment).where(OfferingAssessment.id == m.offering_assessment_id))
        ).scalar_one()
        cia = (
            await self.db.execute(
                select(CiaConsolidation).where(
                    CiaConsolidation.offering_id == a.offering_id,
                    CiaConsolidation.student_program_enrollment_id == m.student_program_enrollment_id,
                )
            )
        ).scalar_one_or_none()
        if cia is not None and cia.status in ("locked", "submitted_to_university"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, "CIA is locked — the COE must reopen it first")
        new = r.new_value
        await self.write_internal_mark(
            a,
            m.student_program_enrollment_id,
            new.get("marks"),
            is_absent=bool(new.get("is_absent", False)),
            question_wise=new.get("question_wise") or m.question_wise,
            source="change_request",
            force=True,
        )
        r.status, r.applied_at, r.approved_by = "applied", now_utc(), self.actor_id
        await self.db.flush()
        if cia is not None:
            offering = (
                await self.db.execute(select(CourseOffering).where(CourseOffering.id == a.offering_id))
            ).scalar_one()
            for row in await self.compute(offering):
                if row["enrol"] == m.student_program_enrollment_id:
                    cia.component_breakdown, cia.cia_total, cia.cia_scaled, cia.computed_at = (
                        row["breakdown"],
                        row["total"],
                        row["scaled"],
                        now_utc(),
                    )
            await self.db.flush()
        await self._audit("change_applied", CR_ENTITY, r.id, r.old_value, r.new_value)
        await self._emit(
            "marks.changed", {"internal_mark_id": str(m.id), "offering_assessment_id": str(a.id)}, ENTITY, a.id
        )
        return (await self.cr_outs([r]))[0]


# ---- workflow hooks ----------------------------------------------------------------------------------------------------------
@workflow_engine.on(WF_CHANGE, "step_approved")
async def _cr_step(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != CR_ENTITY:
        return
    r = (
        await db.execute(
            select(MarksChangeRequest).where(MarksChangeRequest.id == instance.entity_id).with_for_update()
        )
    ).scalar_one_or_none()
    if r is not None and r.status == "requested":
        r.status = "hod_approved"
        await db.flush()


@workflow_engine.on(WF_CHANGE, "approved")
async def _cr_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != CR_ENTITY:
        return
    r = (
        await db.execute(
            select(MarksChangeRequest).where(MarksChangeRequest.id == instance.entity_id).with_for_update()
        )
    ).scalar_one_or_none()
    if r is not None and r.status in ("requested", "hod_approved"):
        r.status, r.approved_by = "coe_approved", getattr(actor, "id", None)
        await db.flush()


@workflow_engine.on(WF_CHANGE, "rejected")
async def _cr_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != CR_ENTITY:
        return
    r = (
        await db.execute(
            select(MarksChangeRequest).where(MarksChangeRequest.id == instance.entity_id).with_for_update()
        )
    ).scalar_one_or_none()
    if r is not None and r.status in ("requested", "hod_approved"):
        r.status = "rejected"
        await db.flush()


@workflow_engine.summariser(CR_ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    r = (await db.execute(select(MarksChangeRequest).where(MarksChangeRequest.id == entity_id))).scalar_one_or_none()
    return (
        (f"Marks change {r.old_value} → {r.new_value}: {r.reason[:80]}", "/hod/marks-verification")
        if r
        else (None, None)
    )
