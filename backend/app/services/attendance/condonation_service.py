"""Attendance condonation — Prompts/11 §11.6 ``condonation_service.py`` ({attendance.condonation}).

* Eligible when ``condonation_floor_pct ≤ pct < attendance_min_pct`` — course-wise (``offering_id`` required) or on
  the credit-weighted term aggregate (``attendance_mode = aggregate``, ``offering_id`` omitted). Below the floor →
  409 ``RULE_VIOLATION BELOW_CONDONATION_FLOOR``; at / above the minimum → ``NOT_REQUIRED``; an open request for the
  same course / term → 409 ``CONFLICT``. The student files it (or an advisor / staff member for a student they see).
* Workflow ``attendance.condonation`` (Phase 04 template: HOD → registrar → vice-chancellor). The queue endpoints decide
  directly (HOD ``recommend`` → ``hod_recommended``; an institution- / college-wide ``attendance:condone`` holder
  ``approve``) and close the instance; the approvals inbox fires the hooks.
* **Fee before Phase 12**: approval records a mock fee order (``rules.condonation_fee_paise``) as an audit row
  (``record_type='attendance_condonation'``, action ``fee_order``) — ``fee_invoice_id`` stays NULL until Phase 12
  ``create_invoice(source_type='condonation')``. A zero fee condones at once; otherwise the payment (dev
  ``POST /_dev/condonations/{id}/paid`` or the Phase 12 ``fees.payment_received`` consumer) condones: the summary
  becomes ``condoned`` and a new eligibility version is written for that offering.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.attendance import AttendanceCondonation, AttendanceSummary, TermEligibility
from app.models.offerings import CourseOffering
from app.models.platform import AuditLog, WorkflowInstance, WorkflowStep
from app.models.students import StudentTermRecord
from app.repositories.timetable_scope import is_staff, session_visibility
from app.schemas.attendance import CondonationCreate, CondonationDecision, CondonationResponse
from app.services.attendance.common import ATT, AttendanceBase, q2, rule, student_name
from app.services.timetable.common import now_utc
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

WF_KEY = "attendance.condonation"
ENTITY = "attendance_condonation"
OPEN = ("requested", "hod_recommended")


class CondonationService(AttendanceBase):
    # ---- reads --------------------------------------------------------------------------------------------------------
    async def _fee(self, cid: uuid.UUID) -> tuple[int, str | None]:
        rows = (
            await self.db.execute(
                select(AuditLog.action, AuditLog.new_values)
                .where(
                    AuditLog.institution_id == self.inst,
                    AuditLog.record_type == ENTITY,
                    AuditLog.record_id == cid,
                    AuditLog.action.in_(("fee_order", "fee_paid")),
                )
                .order_by(AuditLog.occurred_at)
            )
        ).all()
        fee, status = 0, None
        for action, values in rows:
            if action == "fee_order":
                fee, status = int((values or {}).get("amount_paise") or 0), "pending"
            elif action == "fee_paid":
                status = "paid"
        return fee, status

    async def outs(self, rows: Sequence[AttendanceCondonation]) -> list[CondonationResponse]:
        people = await self.enrolments([r.student_program_enrollment_id for r in rows])
        oc = await self.offering_courses([r.offering_id for r in rows if r.offering_id])
        out = []
        for r in rows:
            _, student = people.get(r.student_program_enrollment_id, (None, None))
            o = CondonationResponse.model_validate(r)
            o.actual_pct = float(r.actual_pct)
            o.student_name = student_name(student)
            o.registration_number = student.registration_number if student else None
            course = oc.get(r.offering_id, (None, None))[1] if r.offering_id else None
            o.course_code = course.code if course else None
            o.fee_paise, o.fee_status = await self._fee(r.id)
            o.can_act = r.status in OPEN and is_staff(self.principal) and self.can(ATT, "condone")
            out.append(o)
        return out

    async def list_page(
        self, params: PageParams, scope: str | None, status: str | None, term_id: uuid.UUID | None
    ) -> tuple[list[CondonationResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.condonations.scoped(scope)
        if status:
            stmt = stmt.where(AttendanceCondonation.status == status)
        if term_id:
            stmt = stmt.where(AttendanceCondonation.term_id == term_id)
        if not params.sort:
            stmt = stmt.order_by(AttendanceCondonation.created_at.desc())
        rows, page = await self.condonations.paginate(stmt, params)
        return await self.outs(list(rows)), page, session_visibility(self.principal)

    async def mine(self) -> list[CondonationResponse]:
        _, enrolment = await self.me()
        rows = (
            (
                await self.db.execute(
                    select(AttendanceCondonation)
                    .where(AttendanceCondonation.student_program_enrollment_id == enrolment.id)
                    .order_by(AttendanceCondonation.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return await self.outs(list(rows))

    async def get(self, cid: uuid.UUID) -> CondonationResponse:
        return (await self.outs([await self.condonations.get_one(cid)]))[0]

    # ---- create -------------------------------------------------------------------------------------------------------
    async def create(self, body: CondonationCreate) -> CondonationResponse:
        from app.services.attendance.summary_service import SummaryService

        if body.student_program_enrollment_id and is_staff(self.principal):
            enrol_id = await self.assert_student_visible(body.student_program_enrollment_id)
        else:
            _, me = await self.me()
            enrol_id = me.id
        enrol, student = (await self.enrolments([enrol_id]))[enrol_id]
        term = await self.get_term(body.term_id, enrol.college_id)
        rules = await self.rules_for_pr(enrol.program_regulation_id)
        mn, fl = await self.thresholds(enrol)
        summaries = SummaryService(self.db, self.principal, self.request, self.inst)
        aggregate = str(rules.get("attendance_mode") or "course_wise") == "aggregate"
        if aggregate and body.offering_id is None:
            mine = await summaries._for_enrolment(enrol, student, term.id)
            pct = mine.overall_pct
        else:
            if body.offering_id is None:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "offering_id is required (course-wise attendance)",
                    {"field": "offering_id"},
                )
            await summaries.recompute(body.offering_id, [enrol_id])
            summ = await self.summaries.of(body.offering_id, enrol_id)
            if summ is None:
                raise rule("You are not registered in this course", "NOT_REGISTERED")
            pct = float(summ.pct)
        if pct >= mn:
            raise rule(f"Attendance {pct}% already meets the minimum {mn}%", "NOT_REQUIRED", pct=pct)
        if pct < fl:
            raise rule(
                f"Attendance {pct}% is below the condonation floor {fl}%", "BELOW_CONDONATION_FLOOR", pct=pct, floor=fl
            )
        dup = (
            await self.db.execute(
                select(AttendanceCondonation.id).where(
                    AttendanceCondonation.student_program_enrollment_id == enrol_id,
                    AttendanceCondonation.term_id == term.id,
                    AttendanceCondonation.offering_id.is_(None)
                    if body.offering_id is None
                    else AttendanceCondonation.offering_id == body.offering_id,
                    AttendanceCondonation.status.in_((*OPEN, "approved")),
                )
            )
        ).first()
        if dup:
            raise APIError(
                409, ErrorCode.CONFLICT, "A condonation request already exists", {"condonation_id": str(dup[0])}
            )
        row = AttendanceCondonation(
            institution_id=self.inst,
            college_id=enrol.college_id,
            student_program_enrollment_id=enrol_id,
            term_id=term.id,
            offering_id=body.offering_id,
            actual_pct=q2(pct),
            reason_type=str(body.reason_type),
            reason=body.reason,
            documents=body.documents,
            status="requested",
        )
        self.db.add(row)
        await self.db.flush()
        try:
            inst = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_KEY,
                entity_type=ENTITY,
                entity_id=row.id,
                started_by=self.actor_id,
                context={"department_id": str(enrol.department_id), "college_id": str(enrol.college_id)},
                title=f"Condonation · {student.registration_number} · {pct}%",
            )
            row.workflow_instance_id = inst.id
        except APIError:
            pass
        await self._audit(
            "create",
            ENTITY,
            row.id,
            None,
            {"pct": pct, "offering_id": str(body.offering_id) if body.offering_id else None},
        )
        await self._emit("condonation.requested", {"condonation_id": str(row.id), "pct": pct}, ENTITY, row.id)
        await self._notify(
            "condonation.requested",
            await self.hod_user_ids(enrol.department_id),
            {"student_name": student_name(student), "percentage": pct},
        )
        return (await self.outs([row]))[0]

    async def add_document(self, cid: uuid.UUID, upload: UploadFile) -> CondonationResponse:
        from app.services.file_service import FileService

        row = await self.condonations.get_one(cid, for_update=True)
        if row.status not in OPEN:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        saved = await FileService(self.db).save(upload, "attendance/condonation", institution_id=self.inst)
        row.documents = [
            *(row.documents or []),
            {"key": saved.key, "name": upload.filename, "content_type": saved.content_type},
        ]
        await self.db.flush()
        return (await self.outs([row]))[0]

    # ---- decisions ----------------------------------------------------------------------------------------------------
    async def _assert_unit(self, row: AttendanceCondonation, *, institution_level: bool) -> None:
        if self.principal is None or getattr(self.principal, "is_super_admin", False):
            return
        if not self.can(ATT, "condone"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Condonation needs attendance:condone")
        scopes = getattr(self.principal, "scopes", [])
        wide = any(st == "institution" for st, _ in scopes) or any(
            st == "college" and sid == row.college_id for st, sid in scopes
        )
        if institution_level:
            if not wide:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Approval is by the registrar / principal")
            return
        if wide:
            return
        depts = await self.department_filter()
        enrol = (await self.enrolments([row.student_program_enrollment_id]))[row.student_program_enrollment_id][0]
        if depts is not None and enrol.department_id not in depts:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "The student is outside your department")

    async def recommend(
        self, cid: uuid.UUID, body: CondonationDecision, *, via_workflow: bool = False
    ) -> CondonationResponse:
        row = await self.condonations.get_one(cid, for_update=True)
        if not via_workflow:
            await self._assert_unit(row, institution_level=False)
        if row.status != "requested":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        row.status = "hod_recommended"
        await self.db.flush()
        if not via_workflow:
            await self._act(row, "approve", body.comment)
        await self._audit(
            "recommend", ENTITY, row.id, {"status": "requested"}, {"status": "hod_recommended", "comment": body.comment}
        )
        return (await self.outs([row]))[0]

    async def approve(
        self, cid: uuid.UUID, body: CondonationDecision, *, via_workflow: bool = False
    ) -> CondonationResponse:
        row = await self.condonations.get_one(cid, for_update=True)
        if not via_workflow:
            await self._assert_unit(row, institution_level=True)
        if row.status not in OPEN:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        row.status, row.approved_by, row.approved_at = "approved", self.actor_id, now_utc()
        await self.db.flush()
        if not via_workflow:
            await self._close_instance(row.id, "approved")
        enrol, student = (await self.enrolments([row.student_program_enrollment_id]))[row.student_program_enrollment_id]
        fee = int((await self.rules_for_pr(enrol.program_regulation_id)).get("condonation_fee_paise") or 0)
        await self._audit(
            "approve",
            ENTITY,
            row.id,
            {"status": "requested"},
            {"status": "approved", "fee_paise": fee, "comment": body.comment},
        )
        await self._emit("condonation.approved", {"condonation_id": str(row.id), "fee_paise": fee}, ENTITY, row.id)
        if fee > 0:
            await self._audit(
                "fee_order",
                ENTITY,
                row.id,
                None,
                {"amount_paise": fee, "source_type": "condonation", "source_id": str(row.id), "status": "pending"},
            )
            await self._emit(
                "fees.condonation_invoice",
                {
                    "source_type": "condonation",
                    "source_id": str(row.id),
                    "amount_paise": fee,
                    "student_program_enrollment_id": str(enrol.id),
                },
                ENTITY,
                row.id,
            )
        else:
            await self.condone(row)
        await self._notify(
            "condonation.approved", [student.user_id], {"fee": f"₹{fee / 100:.2f}" if fee else "no fee"}, guardians=True
        )
        return (await self.outs([row]))[0]

    async def reject(
        self, cid: uuid.UUID, body: CondonationDecision, *, via_workflow: bool = False
    ) -> CondonationResponse:
        row = await self.condonations.get_one(cid, for_update=True)
        if not via_workflow:
            await self._assert_unit(row, institution_level=False)
        if row.status not in OPEN:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        row.status = "rejected"
        await self.db.flush()
        if not via_workflow:
            await self._close_instance(row.id, "rejected")
        await self._audit(
            "reject", ENTITY, row.id, {"status": "requested"}, {"status": "rejected", "comment": body.comment}
        )
        await self._emit("condonation.rejected", {"condonation_id": str(row.id)}, ENTITY, row.id)
        _, student = (await self.enrolments([row.student_program_enrollment_id]))[row.student_program_enrollment_id]
        await self._notify("condonation.rejected", [student.user_id], {"comment": body.comment or ""})
        return (await self.outs([row]))[0]

    async def mark_paid(self, cid: uuid.UUID, reference: str | None = None) -> CondonationResponse:
        row = await self.condonations.get_one(cid, for_update=True)
        fee, status = await self._fee(row.id)
        if row.status != "approved":
            raise rule("The condonation is not approved", "NOT_APPROVED")
        if status == "paid":
            return (await self.outs([row]))[0]
        await self._audit("fee_paid", ENTITY, row.id, None, {"amount_paise": fee, "reference": reference})
        await self.condone(row)
        return (await self.outs([row]))[0]

    async def condone(self, row: AttendanceCondonation) -> int:
        """Summary → ``condoned`` and a new eligibility version for the affected offering(s)."""
        stmt = select(AttendanceSummary).where(
            AttendanceSummary.student_program_enrollment_id == row.student_program_enrollment_id
        )
        if row.offering_id:
            stmt = stmt.where(AttendanceSummary.offering_id == row.offering_id)
        else:
            stmt = stmt.where(
                AttendanceSummary.offering_id.in_(
                    select(CourseOffering.id).where(CourseOffering.term_id == row.term_id)
                ),
                AttendanceSummary.eligibility.in_(("condonable", "not_eligible")),
            )
        changed = 0
        record = (
            await self.db.execute(
                select(StudentTermRecord).where(
                    StudentTermRecord.student_program_enrollment_id == row.student_program_enrollment_id,
                    StudentTermRecord.term_id == row.term_id,
                )
            )
        ).scalar_one_or_none()
        for s in (await self.db.execute(stmt.with_for_update())).scalars().all():
            s.eligibility = "condoned"
            changed += 1
            if record is not None:
                latest = await self.elig.latest_version(record.id, s.offering_id)
                if latest is not None:
                    self.db.add(
                        TermEligibility(
                            institution_id=self.inst,
                            student_term_record_id=record.id,
                            offering_id=s.offering_id,
                            attendance_pct=latest.attendance_pct,
                            cia_marks=latest.cia_marks,
                            cia_max=latest.cia_max,
                            is_attendance_ok=True,
                            is_cia_ok=latest.is_cia_ok,
                            is_fee_ok=latest.is_fee_ok,
                            is_hold_ok=latest.is_hold_ok,
                            decision="condoned" if latest.is_cia_ok else latest.decision,
                            reason_codes=[c for c in (latest.reason_codes or []) if not c.startswith("ATT_")],
                            decided_by=self.actor_id,
                            decided_at=now_utc(),
                            version=latest.version + 1,
                        )
                    )
        await self.db.flush()
        await self._audit("condoned", ENTITY, row.id, None, {"summaries": changed})
        return changed

    # ---- workflow plumbing ------------------------------------------------------------------------------------------
    async def _act(self, row: AttendanceCondonation, decision: str, comment: str | None) -> None:
        """Advance the engine step when the caller is its approver (silently skipped otherwise)."""
        if row.workflow_instance_id is None or self.principal is None:
            return
        try:
            async with self.db.begin_nested():
                await workflow_engine.act(
                    self.db,
                    instance_id=row.workflow_instance_id,
                    actor=self.principal,
                    decision=decision,
                    comment=comment,
                )
        except APIError:
            pass

    async def _close_instance(self, cid: uuid.UUID, status: str) -> None:
        inst = (
            await self.db.execute(
                select(WorkflowInstance)
                .where(
                    WorkflowInstance.entity_type == ENTITY,
                    WorkflowInstance.entity_id == cid,
                    WorkflowInstance.status.in_(("pending", "escalated")),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if inst is None:
            return
        for step in (
            await self.db.execute(
                select(WorkflowStep).where(
                    WorkflowStep.instance_id == inst.id, WorkflowStep.status.in_(("pending", "escalated"))
                )
            )
        ).scalars():
            step.status = "skipped"
        inst.status, inst.closed_at = status, now_utc()


class _Actor:
    def __init__(self, institution_id: uuid.UUID, user_id: Any):
        self.institution_id, self.id = institution_id, user_id
        self.impersonator_id, self.is_super_admin = None, False
        self.scopes: list[Any] = [("institution", None)]

    def has(self, module: str, action: str) -> bool:
        return True


def _service(db: Any, instance: WorkflowInstance, actor: Any) -> CondonationService:
    return CondonationService(
        db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id
    )


@workflow_engine.on(WF_KEY, "step_approved")
async def _on_step(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY or instance.current_step != 1:
        return
    svc = _service(db, instance, actor)
    row = await svc.condonations.get_one(instance.entity_id)
    if row.status == "requested":
        await svc.recommend(row.id, CondonationDecision(), via_workflow=True)


@workflow_engine.on(WF_KEY, "approved")
async def _on_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = _service(db, instance, actor)
    row = await svc.condonations.get_one(instance.entity_id)
    if row.status in OPEN:
        await svc.approve(row.id, CondonationDecision(), via_workflow=True)


@workflow_engine.on(WF_KEY, "rejected")
async def _on_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = _service(db, instance, actor)
    row = await svc.condonations.get_one(instance.entity_id)
    if row.status in OPEN:
        await svc.reject(row.id, CondonationDecision(), via_workflow=True)


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (
        await db.execute(select(AttendanceCondonation).where(AttendanceCondonation.id == entity_id))
    ).scalar_one_or_none()
    if row is None:
        return None, None
    return f"Condonation · {float(row.actual_pct)}% ({row.reason_type})", "/admin/attendance/condonations"


__all__ = ["CondonationService"]
