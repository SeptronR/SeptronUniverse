"""Withheld results, detention and readmission — Prompts/16 §16.6 ``withheld_service`` / ``detention_service``.

Withheld: current published rows with ``result_status='withheld'`` and the reasons that still hold —
``MALPRACTICE_PENDING`` (an open case on the item), ``WITHHELD_HOLD`` (an open ``exam|all`` hold), ``FEE_DUE`` (an
overdue invoice of the enrolment) or ``PUBLISH_WITHHELD`` (withheld by the COE at publication). ``release`` (COE,
``results:approve``) re-runs the rows as a ``correction`` run with ``ignore_holds`` and publishes it; ``auto_release``
(hourly Beat) does the same as the system for rows whose only causes have cleared.

Detention: term records of the term in ``detained`` status or with a ``detained`` eligibility decision. Readmission
(``students.readmission`` workflow, registrar): the request is a workflow instance (entity ``readmission``; the reason,
enrolment and term live in its context — no table); approval opens a term record for the same term (same type /
sequence) of the next academic year, re-activates the enrolment, emits ``student.readmitted`` (Phase 12 re-assigns the
fee structure) and opens a ``readmission`` registration window for that term.
"""

import uuid
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import or_, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.fees import OPEN_INVOICE
from app.models.academic import AcademicTerm
from app.models.attendance import TermEligibility
from app.models.curriculum import Course
from app.models.exams import MalpracticeCase
from app.models.fees import FeeInvoice
from app.models.platform import WorkflowDefinition, WorkflowInstance
from app.models.registration import RegistrationWindow
from app.models.results import ResultPublication, StudentCourseResult
from app.models.students import Student, StudentHold, StudentProgramEnrollment, StudentTermRecord
from app.schemas.post_result import (
    DetentionRow,
    ReadmissionRequest,
    ReadmissionResponse,
    WithheldReleaseRequest,
    WithheldRow,
)
from app.services.exams.common import now_utc, rule
from app.services.post_result.common import PostResultBase

WF_READMISSION = "students.readmission"
READMISSION_ENTITY = "readmission"
BLOCKING = ("MALPRACTICE_PENDING", "WITHHELD_HOLD", "FEE_DUE")


class WithheldService(PostResultBase):
    audit_module = "results"

    async def _reasons(self, rows: list[StudentCourseResult]) -> dict[uuid.UUID, list[str]]:
        enr = {r.student_program_enrollment_id for r in rows} or {uuid.uuid4()}
        items = {r.exam_registration_item_id for r in rows if r.exam_registration_item_id} or {uuid.uuid4()}
        mal = set(
            (
                await self.db.execute(
                    select(MalpracticeCase.exam_registration_item_id).where(
                        MalpracticeCase.exam_registration_item_id.in_(items),
                        MalpracticeCase.status.in_(("reported", "under_inquiry", "hearing_scheduled", "appealed")),
                    )
                )
            ).scalars()
        )
        holds = set(
            (
                await self.db.execute(
                    select(StudentHold.student_program_enrollment_id).where(
                        StudentHold.student_program_enrollment_id.in_(enr),
                        StudentHold.released_at.is_(None),
                        StudentHold.hold_type.in_(("exam", "all")),
                    )
                )
            ).scalars()
        )
        today = await self.today()
        dues = set(
            (
                await self.db.execute(
                    select(FeeInvoice.student_program_enrollment_id).where(
                        FeeInvoice.student_program_enrollment_id.in_(enr),
                        FeeInvoice.status.in_(tuple(OPEN_INVOICE)),
                        FeeInvoice.due_date < today,
                    )
                )
            ).scalars()
        )
        published_withheld: set[str] = set()
        for (wl,) in (
            await self.db.execute(
                select(ResultPublication.withheld_list).where(
                    ResultPublication.run_id.in_({r.run_id for r in rows} or {uuid.uuid4()})
                )
            )
        ).all():
            published_withheld |= {str(x) for x in (wl or [])}
        out: dict[uuid.UUID, list[str]] = {}
        for r in rows:
            reasons = []
            if r.exam_registration_item_id in mal:
                reasons.append("MALPRACTICE_PENDING")
            if r.student_program_enrollment_id in holds:
                reasons.append("WITHHELD_HOLD")
            if r.student_program_enrollment_id in dues:
                reasons.append("FEE_DUE")
            if str(r.student_program_enrollment_id) in published_withheld:
                reasons.append("PUBLISH_WITHHELD")
            out[r.id] = reasons
        return out

    async def _rows(
        self, session_id: uuid.UUID | None, ids: list[uuid.UUID] | None = None
    ) -> list[StudentCourseResult]:
        q = select(StudentCourseResult).where(
            StudentCourseResult.institution_id == self.inst,
            StudentCourseResult.is_current.is_(True),
            StudentCourseResult.status == "published",
            StudentCourseResult.result_status == "withheld",
        )
        if session_id:
            q = q.where(StudentCourseResult.exam_session_id == session_id)
        if ids:
            q = q.where(StudentCourseResult.id.in_(ids))
        colleges = self._college_ids()
        if colleges and not any(st == "institution" for st, _ in getattr(self.principal, "scopes", [])):
            q = q.where(StudentCourseResult.college_id.in_(colleges))
        return list((await self.db.execute(q)).scalars())

    async def list_withheld(self, session_id: uuid.UUID | None) -> list[WithheldRow]:
        rows = await self._rows(session_id)
        reasons = await self._reasons(rows)
        students: dict[uuid.UUID, Student] = dict(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(
                        StudentProgramEnrollment.id.in_(
                            {r.student_program_enrollment_id for r in rows} or {uuid.uuid4()}
                        )
                    )
                )
            )
            .tuples()
            .all()
        )
        courses = {
            c.id: c
            for c in (
                await self.db.execute(
                    select(Course).where(Course.id.in_({r.course_id for r in rows} or {uuid.uuid4()}))
                )
            ).scalars()
        }
        out = []
        for r in rows:
            st = students.get(r.student_program_enrollment_id)
            rs = reasons.get(r.id, [])
            out.append(
                WithheldRow(
                    result_id=r.id,
                    student_program_enrollment_id=r.student_program_enrollment_id,
                    registration_number=st.registration_number if st else None,
                    student_name=" ".join(x for x in (st.first_name, st.last_name) if x) if st else None,
                    course_code=courses[r.course_id].code if r.course_id in courses else None,
                    reasons=rs,
                    releasable=not any(x in BLOCKING for x in rs),
                )
            )
        return out

    async def _release(self, rows: list[StudentCourseResult], reason: str, *, system: bool) -> list[uuid.UUID]:
        by_session: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]] = {}
        for r in rows:
            if r.exam_session_id:
                by_session.setdefault(r.exam_session_id, []).append((r.student_program_enrollment_id, r.course_id))
        runs = []
        for sid, pairs in by_session.items():
            run_id = await self.correction_run(sid, pairs, ignore_holds=True, auto_publish=True)
            if run_id:
                runs.append(run_id)
                await self._audit(
                    "withheld_release",
                    "exam_session",
                    sid,
                    None,
                    {"rows": len(pairs), "run_id": str(run_id), "reason": reason, "system": system},
                )
                await self._emit(
                    "results.withheld_released",
                    {"session_id": str(sid), "run_id": str(run_id), "rows": len(pairs)},
                    "exam_session",
                    sid,
                )
        return runs

    async def release(self, body: WithheldReleaseRequest) -> dict[str, Any]:
        rows = await self._rows(None, body.result_ids)
        if not rows:
            raise APIError(404, ErrorCode.NOT_FOUND, "No withheld rows among the ids")
        reasons = await self._reasons(rows)
        blocked = [str(r.id) for r in rows if "MALPRACTICE_PENDING" in reasons.get(r.id, [])]
        if blocked:
            raise rule(
                "Rows with a pending malpractice case are released by the case decision", "CASE_PENDING", rows=blocked
            )
        runs = await self._release(rows, body.reason, system=False)
        return {"released": len(rows), "run_ids": [str(x) for x in runs]}

    async def auto_release(self) -> int:
        """Beat (hourly): rows withheld by a hold / fee due whose causes cleared are re-run and published."""
        rows = await self._rows(None)
        reasons = await self._reasons(rows)
        ready = [r for r in rows if not reasons.get(r.id)]
        if not ready:
            return 0
        await self._release(ready, "cause cleared", system=True)
        return len(ready)


class DetentionService(PostResultBase):
    audit_module = "students"

    async def detained(self, term_id: uuid.UUID) -> list[DetentionRow]:
        detained_records = select(TermEligibility.student_term_record_id).where(TermEligibility.decision == "detained")
        q = (
            select(StudentTermRecord, StudentProgramEnrollment, Student)
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == StudentTermRecord.student_program_enrollment_id
            )
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(
                StudentTermRecord.institution_id == self.inst,
                StudentTermRecord.term_id == term_id,
                or_(StudentTermRecord.status == "detained", StudentTermRecord.id.in_(detained_records)),
            )
        )
        colleges = self._college_ids()
        if colleges and not any(st == "institution" for st, _ in getattr(self.principal, "scopes", [])):
            q = q.where(StudentProgramEnrollment.college_id.in_(colleges))
        rows = (await self.db.execute(q.order_by(Student.registration_number))).all()
        from app.models.offerings import CourseOffering

        courses: dict[uuid.UUID, list[str]] = {}
        for rec_id, code in (
            await self.db.execute(
                select(TermEligibility.student_term_record_id, Course.code)
                .join(CourseOffering, CourseOffering.id == TermEligibility.offering_id)
                .join(Course, Course.id == CourseOffering.course_id)
                .where(
                    TermEligibility.student_term_record_id.in_([r.id for r, _, _ in rows] or [uuid.uuid4()]),
                    TermEligibility.decision == "detained",
                )
            )
        ).all():
            if code not in courses.setdefault(rec_id, []):
                courses[rec_id].append(code)
        readmissions = {
            (i.context or {}).get("enrollment_id"): i
            for i in await self._instances()
            if (i.context or {}).get("term_id") == str(term_id)
        }
        out = []
        for rec, e, st in rows:
            ri = readmissions.get(str(e.id))
            out.append(
                DetentionRow(
                    student_program_enrollment_id=e.id,
                    student_term_record_id=rec.id,
                    registration_number=st.registration_number,
                    student_name=" ".join(x for x in (st.first_name, st.last_name) if x),
                    term_number=rec.term_number,
                    attendance_pct=rec.attendance_pct,
                    detained_courses=courses.get(rec.id, []),
                    readmission={"id": str(ri.entity_id), "status": ri.status} if ri else None,
                )
            )
        return out

    async def _instances(self, entity_id: uuid.UUID | None = None) -> list[WorkflowInstance]:
        q = (
            select(WorkflowInstance)
            .join(WorkflowDefinition, WorkflowDefinition.id == WorkflowInstance.definition_id)
            .where(
                WorkflowInstance.institution_id == self.inst,
                WorkflowInstance.entity_type == READMISSION_ENTITY,
                WorkflowDefinition.key == WF_READMISSION,
            )
        )
        if entity_id:
            q = q.where(WorkflowInstance.entity_id == entity_id)
        return list((await self.db.execute(q.order_by(WorkflowInstance.started_at.desc()))).scalars())

    @staticmethod
    def out(i: WorkflowInstance) -> ReadmissionResponse:
        ctx = i.context or {}
        status = ctx.get("outcome") or {"pending": "pending", "escalated": "pending"}.get(i.status, i.status)
        return ReadmissionResponse(
            id=i.entity_id,
            enrollment_id=uuid.UUID(ctx["enrollment_id"]),
            term_id=uuid.UUID(ctx["term_id"]) if ctx.get("term_id") else None,
            status=status,
            reason=ctx.get("reason"),
            started_at=i.started_at,
            new_term_record_id=uuid.UUID(ctx["new_term_record_id"]) if ctx.get("new_term_record_id") else None,
        )

    async def list_readmissions(self, status: str | None) -> list[ReadmissionResponse]:
        rows = [self.out(i) for i in await self._instances()]
        if not self.can("students", "manage"):
            own = {
                e
                for e in (
                    await self.db.execute(
                        select(StudentProgramEnrollment.id).where(
                            StudentProgramEnrollment.id.in_([r.enrollment_id for r in rows] or [uuid.uuid4()])
                        )
                    )
                ).scalars()
                if await self.mine(e)
            }
            rows = [r for r in rows if r.enrollment_id in own]
        return [r for r in rows if status is None or r.status == status]

    async def submit(self, body: ReadmissionRequest) -> ReadmissionResponse:
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(
                    StudentProgramEnrollment.id == body.enrollment_id,
                    StudentProgramEnrollment.institution_id == self.inst,
                )
            )
        ).scalar_one_or_none()
        if e is None or (not self.can("students", "manage") and not await self.mine(e.id)):
            raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found")
        rec = (
            await self.db.execute(
                select(StudentTermRecord).where(
                    StudentTermRecord.student_program_enrollment_id == e.id, StudentTermRecord.term_id == body.term_id
                )
            )
        ).scalar_one_or_none()
        detained = rec is not None and (
            rec.status == "detained"
            or (
                await self.db.execute(
                    select(TermEligibility.id).where(
                        TermEligibility.student_term_record_id == rec.id, TermEligibility.decision == "detained"
                    )
                )
            ).first()
            is not None
        )
        if not detained:
            raise rule("The student is not detained in this term", "NOT_DETAINED")
        for i in await self._instances():
            ctx = i.context or {}
            if (
                ctx.get("enrollment_id") == str(e.id)
                and ctx.get("term_id") == str(body.term_id)
                and i.status in ("pending", "escalated")
            ):
                raise APIError(409, ErrorCode.CONFLICT, "A readmission request is already pending")
        rid = uuid.uuid4()
        i = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WF_READMISSION,
            entity_type=READMISSION_ENTITY,
            entity_id=rid,
            started_by=self.actor_id,
            context={
                "enrollment_id": str(e.id),
                "term_id": str(body.term_id),
                "term_record_id": str(rec.id) if rec else None,
                "term_number": rec.term_number if rec else None,
                "reason": body.reason,
                "college_id": str(e.college_id),
            },
            title=f"Readmission — term {rec.term_number if rec else ''}",
        )
        await self._audit(
            "readmission_request",
            READMISSION_ENTITY,
            rid,
            None,
            {"enrollment_id": str(e.id), "term_id": str(body.term_id)},
        )
        return self.out(i)

    async def decide(self, rid: uuid.UUID, approve: bool, comment: str | None) -> ReadmissionResponse:
        inst = next(iter(await self._instances(rid)), None)
        if inst is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Readmission request not found")
        if inst.status not in ("pending", "escalated"):
            raise APIError(409, ErrorCode.CONFLICT, f"Already {inst.status}")
        await workflow_engine.act(
            self.db,
            instance_id=inst.id,
            actor=self.principal,
            decision="approve" if approve else "reject",
            comment=comment,
        )
        await self.db.refresh(inst)
        return self.out(inst)

    async def apply(self, inst: WorkflowInstance) -> None:
        """``students.readmission`` approved: next-year term record, enrolment active, readmission window."""
        ctx = dict(inst.context or {})
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment)
                .where(StudentProgramEnrollment.id == uuid.UUID(ctx["enrollment_id"]))
                .with_for_update()
            )
        ).scalar_one()
        base = (
            await self.db.execute(select(AcademicTerm).where(AcademicTerm.id == uuid.UUID(ctx["term_id"])))
        ).scalar_one()
        nxt = (
            await self.db.execute(
                select(AcademicTerm)
                .where(
                    AcademicTerm.institution_id == self.inst,
                    AcademicTerm.term_type == base.term_type,
                    AcademicTerm.sequence == base.sequence,
                    AcademicTerm.start_date > base.start_date,
                    AcademicTerm.deleted_at.is_(None),
                    AcademicTerm.college_id.is_(None)
                    if base.college_id is None
                    else AcademicTerm.college_id == base.college_id,
                )
                .order_by(AcademicTerm.start_date)
                .limit(1)
            )
        ).scalar_one_or_none()
        if nxt is None:
            raise rule("The same term of the next academic year is not set up yet", "NO_NEXT_TERM")
        rec = (
            await self.db.execute(
                select(StudentTermRecord).where(
                    StudentTermRecord.student_program_enrollment_id == e.id, StudentTermRecord.term_id == nxt.id
                )
            )
        ).scalar_one_or_none()
        if rec is None:
            rec = StudentTermRecord(
                institution_id=self.inst,
                student_program_enrollment_id=e.id,
                term_id=nxt.id,
                term_number=int(ctx.get("term_number") or 1),
                status="pending_registration",
            )
            self.db.add(rec)
        if e.status == "detained":
            e.status = "active"
        await self.db.flush()
        starts = datetime.combine(max(await self.today(), nxt.registration_start or nxt.start_date), time.min).replace(
            tzinfo=now_utc().tzinfo
        )
        self.db.add(
            RegistrationWindow(
                institution_id=self.inst,
                college_id=e.college_id,
                term_id=nxt.id,
                name=f"Readmission — term {rec.term_number}",
                window_type="readmission",
                applies_to={
                    "program_ids": [str(e.program_id)],
                    "batch_ids": [str(e.batch_id)],
                    "term_numbers": [rec.term_number],
                },
                starts_at=starts,
                ends_at=starts + timedelta(days=14),
                requires_advisor_approval=True,
                status="open",
                created_by=self.actor_id,
            )
        )
        ctx.update({"outcome": "approved", "new_term_record_id": str(rec.id), "new_term_id": str(nxt.id)})
        inst.context = ctx
        await self.db.flush()
        await self._audit(
            "readmit", "student_term_record", rec.id, None, {"entry_type": "readmission", "term_id": str(nxt.id)}
        )
        await self._emit(
            "student.readmitted",
            {
                "enrollment_id": str(e.id),
                "term_id": str(nxt.id),
                "term_record_id": str(rec.id),
                "entry_type": "readmission",
            },
            "student_program_enrollment",
            e.id,
        )


def _actor(instance: WorkflowInstance, actor: Any) -> Any:
    from app.services.fees.payment_service import _Actor

    return _Actor(instance.institution_id, getattr(actor, "id", None))


@workflow_engine.on(WF_READMISSION, "approved")
async def _readmission_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == READMISSION_ENTITY:
        await DetentionService(db, _actor(instance, actor), None, instance.institution_id).apply(instance)


@workflow_engine.on(WF_READMISSION, "rejected")
async def _readmission_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == READMISSION_ENTITY:
        instance.context = {**(instance.context or {}), "outcome": "rejected"}
        await db.flush()


@workflow_engine.summariser(READMISSION_ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    i = (await db.execute(select(WorkflowInstance).where(WorkflowInstance.entity_id == entity_id))).scalar_one_or_none()
    if i is None:
        return None, None
    return f"Readmission — {(i.context or {}).get('reason', '')[:100]}", "/admin/students/detained"
