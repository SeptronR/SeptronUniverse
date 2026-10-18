"""On-duty requests — Prompts/11 §11.6 ``od_service.py`` ({attendance.on_duty}).

* A student applies for a date range (reason, documents via ``FileService.save``); staff may file for a student they
  teach / advise / administer. Overlapping open or approved requests → 409 ``CONFLICT``.
* The optional Phase 04 workflow ``attendance.on_duty`` (HOD; template added by Phase 11) runs alongside: the queue
  endpoints decide directly and close the instance; the approvals inbox fires the hooks.
* ``recommend`` — faculty of the student's offerings / advisor / HOD (``attendance:mark``); ``approve`` — the approver
  from ``attendance.od_approver`` (``hod`` = HOD over the student's department or the registrar; ``registrar`` = an
  institution-wide holder only). Approval marks every session of the student's confirmed offerings in the range
  ``on_duty`` (a present / late mark is kept); finalized sessions go through the audited privileged path;
  ``sessions_applied`` records them and the summaries are recomputed (OD is never part of an absence streak).
* Sessions created later (extra classes, timetables published after approval) receive the OD mark from the consumers
  of ``session.created`` / ``timetable.published`` (``apply_to_sessions``).
"""

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from fastapi import UploadFile
from sqlalchemy import or_, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.attendance import OnDutyRequest
from app.models.platform import WorkflowInstance, WorkflowStep
from app.models.registration import CourseRegistration, CourseRegistrationItem
from app.models.timetable import ClassSession
from app.repositories.timetable_scope import is_staff, session_visibility
from app.schemas.attendance import OdCreate, OdDecision, OdResponse
from app.services.attendance.common import ATT, AttendanceBase, student_name
from app.services.timetable.common import now_utc
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

WF_KEY = "attendance.on_duty"
ENTITY = "on_duty_request"
OPEN = ("requested", "recommended")


class OdService(AttendanceBase):
    # ---- reads --------------------------------------------------------------------------------------------------------
    async def outs(self, rows: Sequence[OnDutyRequest]) -> list[OdResponse]:
        people = await self.enrolments([r.student_program_enrollment_id for r in rows])
        staff = is_staff(self.principal)
        out = []
        for r in rows:
            _, student = people.get(r.student_program_enrollment_id, (None, None))
            o = OdResponse.model_validate(r)
            o.student_name = student_name(student)
            o.registration_number = student.registration_number if student else None
            o.can_recommend = staff and r.status == "requested" and self.can(ATT, "mark")
            o.can_approve = staff and r.status in OPEN and await self._may_approve(r)
            out.append(o)
        return out

    async def list_page(
        self, params: PageParams, scope: str | None, status: str | None, enrolment_id: uuid.UUID | None
    ) -> tuple[list[OdResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.ods.scoped(scope)
        if status:
            stmt = stmt.where(OnDutyRequest.status == status)
        if enrolment_id:
            stmt = stmt.where(OnDutyRequest.student_program_enrollment_id == enrolment_id)
        if not params.sort:
            stmt = stmt.order_by(OnDutyRequest.created_at.desc())
        rows, page = await self.ods.paginate(stmt, params)
        return await self.outs(list(rows)), page, session_visibility(self.principal)

    async def get(self, od_id: uuid.UUID) -> OdResponse:
        return (await self.outs([await self.ods.get_one(od_id)]))[0]

    # ---- create -------------------------------------------------------------------------------------------------------
    async def create(self, body: OdCreate) -> OdResponse:
        if body.student_program_enrollment_id and is_staff(self.principal):
            enrol_id = await self.assert_student_visible(body.student_program_enrollment_id)
        else:
            _, enrolment = await self.me()
            enrol_id = enrolment.id
        clash = (
            await self.db.execute(
                select(OnDutyRequest.id).where(
                    OnDutyRequest.student_program_enrollment_id == enrol_id,
                    OnDutyRequest.status.in_((*OPEN, "approved")),
                    OnDutyRequest.from_date <= body.to_date,
                    OnDutyRequest.to_date >= body.from_date,
                )
            )
        ).first()
        if clash:
            raise APIError(
                409, ErrorCode.CONFLICT, "An on-duty request already covers these dates", {"od_id": str(clash[0])}
            )
        row = OnDutyRequest(
            institution_id=self.inst,
            student_program_enrollment_id=enrol_id,
            from_date=body.from_date,
            to_date=body.to_date,
            reason_type=str(body.reason_type),
            reason=body.reason,
            documents=body.documents,
            status="requested",
        )
        self.db.add(row)
        await self.db.flush()
        people = await self.enrolments([enrol_id])
        enrol, student = people[enrol_id]
        try:
            inst = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_KEY,
                entity_type=ENTITY,
                entity_id=row.id,
                started_by=self.actor_id,
                context={"department_id": str(enrol.department_id)},
                title=f"On duty · {student.registration_number} · {body.from_date.isoformat()}",
            )
            row.workflow_instance_id = inst.id
        except APIError:
            pass  # the workflow is optional (definition removed / inactive)
        await self._audit(
            "create",
            ENTITY,
            row.id,
            None,
            {"from": body.from_date.isoformat(), "to": body.to_date.isoformat(), "reason_type": row.reason_type},
        )
        await self._emit(
            "od.requested", {"od_id": str(row.id), "student_program_enrollment_id": str(enrol_id)}, ENTITY, row.id
        )
        await self._notify(
            "od.requested",
            await self.hod_user_ids(enrol.department_id),
            {
                "student_name": student_name(student),
                "from_date": body.from_date.isoformat(),
                "to_date": body.to_date.isoformat(),
            },
        )
        return (await self.outs([row]))[0]

    async def add_document(self, od_id: uuid.UUID, upload: UploadFile) -> OdResponse:
        from app.services.file_service import FileService

        row = await self.ods.get_one(od_id, for_update=True)
        if row.status not in OPEN:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        saved = await FileService(self.db).save(upload, "attendance/on-duty", institution_id=self.inst)
        docs = list(row.documents or [])
        docs.append({"key": saved.key, "name": upload.filename, "content_type": saved.content_type})
        row.documents = docs
        await self.db.flush()
        return (await self.outs([row]))[0]

    # ---- decisions ----------------------------------------------------------------------------------------------------
    async def _may_approve(self, r: OnDutyRequest) -> bool:
        if self.principal is None or getattr(self.principal, "is_super_admin", False):
            return True
        if not (self.can(ATT, "condone") or self.can(ATT, "edit_finalized")):
            return False
        who = await self.att_setting("od_approver", "hod")
        depts = await self.department_filter()
        if depts is None:
            return True
        if who == "registrar":
            return False
        enrol = (await self.enrolments([r.student_program_enrollment_id])).get(
            r.student_program_enrollment_id, (None, None)
        )[0]
        return enrol is not None and enrol.department_id in depts

    async def recommend(self, od_id: uuid.UUID, body: OdDecision) -> OdResponse:
        row = await self.ods.get_one(od_id, for_update=True)
        if not is_staff(self.principal):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Staff only")
        if row.status != "requested":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        row.status, row.recommended_by = "recommended", self.actor_id
        await self.db.flush()
        await self._audit(
            "recommend", ENTITY, row.id, {"status": "requested"}, {"status": "recommended", "comment": body.comment}
        )
        return (await self.outs([row]))[0]

    async def approve(self, od_id: uuid.UUID, body: OdDecision, *, via_workflow: bool = False) -> OdResponse:
        row = await self.ods.get_one(od_id, for_update=True)
        if not via_workflow and not await self._may_approve(row):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may not approve this on-duty request")
        if row.status not in OPEN:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        row.status, row.approved_by = "approved", self.actor_id
        applied = await self._apply(row)
        row.sessions_applied = [str(i) for i in applied]
        await self.db.flush()
        if not via_workflow:
            await self._close_instance(row.id, "approved")
        await self._audit(
            "approve",
            ENTITY,
            row.id,
            {"status": "requested"},
            {"status": "approved", "sessions": len(applied), "comment": body.comment},
        )
        await self._emit("od.approved", {"od_id": str(row.id), "sessions": len(applied)}, ENTITY, row.id)
        await self._decided(row, "od.approved", body.comment)
        return (await self.outs([row]))[0]

    async def reject(self, od_id: uuid.UUID, body: OdDecision, *, via_workflow: bool = False) -> OdResponse:
        row = await self.ods.get_one(od_id, for_update=True)
        if not via_workflow and not await self._may_approve(row):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "You may not decide this on-duty request")
        if row.status not in OPEN:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        row.status = "rejected"
        await self.db.flush()
        if not via_workflow:
            await self._close_instance(row.id, "rejected")
        await self._audit(
            "reject", ENTITY, row.id, {"status": "requested"}, {"status": "rejected", "comment": body.comment}
        )
        await self._emit("od.rejected", {"od_id": str(row.id)}, ENTITY, row.id)
        await self._decided(row, "od.rejected", body.comment)
        return (await self.outs([row]))[0]

    async def withdraw(self, od_id: uuid.UUID) -> OdResponse:
        row = await self.ods.get_one(od_id, for_update=True)
        _, enrolment = await self.me()
        if row.student_program_enrollment_id != enrolment.id:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the student may withdraw the request")
        if row.status not in OPEN:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The request is already {row.status}")
        row.status = "withdrawn"
        await self.db.flush()
        await self._close_instance(row.id, "cancelled")
        await self._audit("withdraw", ENTITY, row.id, {"status": "requested"}, {"status": "withdrawn"})
        return (await self.outs([row]))[0]

    async def _decided(self, row: OnDutyRequest, event: str, comment: str | None) -> None:
        _, student = (await self.enrolments([row.student_program_enrollment_id]))[row.student_program_enrollment_id]
        await self._notify(
            event,
            [student.user_id],
            {"from_date": row.from_date.isoformat(), "to_date": row.to_date.isoformat(), "comment": comment or ""},
        )

    async def _close_instance(self, od_id: uuid.UUID, status: str) -> None:
        inst = (
            await self.db.execute(
                select(WorkflowInstance)
                .where(
                    WorkflowInstance.entity_type == ENTITY,
                    WorkflowInstance.entity_id == od_id,
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

    # ---- applying marks ---------------------------------------------------------------------------------------------
    async def _student_offerings(self, enrol_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            (
                await self.db.execute(
                    select(CourseRegistrationItem.offering_id)
                    .join(CourseRegistration, CourseRegistration.id == CourseRegistrationItem.registration_id)
                    .where(
                        CourseRegistration.student_program_enrollment_id == enrol_id,
                        CourseRegistrationItem.status == "confirmed",
                    )
                )
            ).scalars()
        )

    async def _apply(self, row: OnDutyRequest, only_sessions: Sequence[uuid.UUID] | None = None) -> list[uuid.UUID]:
        from app.services.attendance.marking_service import MarkingService
        from app.services.attendance.summary_service import SummaryService

        offerings = await self._student_offerings(row.student_program_enrollment_id)
        if not offerings:
            return []
        stmt = select(ClassSession).where(
            ClassSession.offering_id.in_(offerings),
            ClassSession.session_date >= row.from_date,
            ClassSession.session_date <= row.to_date,
            ClassSession.status.in_(("scheduled", "conducted")),
        )
        if only_sessions is not None:
            stmt = stmt.where(ClassSession.id.in_(list(only_sessions)))
        sessions = (await self.db.execute(stmt.with_for_update())).scalars().all()
        marking = MarkingService(self.db, self.principal, self.request, self.inst)
        applied: list[uuid.UUID] = []
        touched: set[uuid.UUID] = set()
        enr = row.student_program_enrollment_id
        for s in sessions:
            if enr not in {r[0] for r in await self.marks.roster(s)}:
                continue
            old = (await self.marks.marks(s)).get(enr)
            if old is not None and old.status in ("present", "late", "on_duty", "exempt"):
                continue
            if s.attendance_status == "finalized":
                await marking.privileged_edit(s, {enr: ("on_duty", "approved OD")}, f"approved OD {row.id}")
            else:
                await self.marks.upsert_marks(
                    s,
                    [
                        {
                            "student_program_enrollment_id": enr,
                            "status": "on_duty",
                            "source": "manual",
                            "marked_by": self.actor_id,
                            "remarks": "approved OD",
                        }
                    ],
                )
                touched.add(s.offering_id)
            applied.append(s.id)
        await self.db.flush()
        summaries = SummaryService(self.db, self.principal, self.request, self.inst)
        for oid in touched:
            await summaries.recompute(oid, [enr])
        return applied

    async def apply_to_sessions(
        self, session_ids: Sequence[uuid.UUID] | None = None, date_from: date | None = None
    ) -> int:
        """Consumers: approved ODs covering newly created sessions get their marks."""
        today = date_from or await self.today()
        stmt = select(OnDutyRequest).where(
            OnDutyRequest.institution_id == self.inst,
            OnDutyRequest.status == "approved",
            OnDutyRequest.to_date >= today,
        )
        if session_ids:
            dates = (
                (await self.db.execute(select(ClassSession.session_date).where(ClassSession.id.in_(list(session_ids)))))
                .scalars()
                .all()
            )
            if not dates:
                return 0
            stmt = stmt.where(or_(*[(OnDutyRequest.from_date <= d) & (OnDutyRequest.to_date >= d) for d in set(dates)]))
        n = 0
        for row in (await self.db.execute(stmt)).scalars().all():
            applied = await self._apply(row, session_ids)
            if applied:
                row.sessions_applied = sorted(set(row.sessions_applied or []) | {str(i) for i in applied})
                n += len(applied)
        return n


class _Actor:
    def __init__(self, institution_id: uuid.UUID, user_id: Any):
        self.institution_id, self.id = institution_id, user_id
        self.impersonator_id, self.is_super_admin = None, False
        self.scopes: list[Any] = [("institution", None)]

    def has(self, module: str, action: str) -> bool:
        return True


def _service(db: Any, instance: WorkflowInstance, actor: Any) -> OdService:
    return OdService(db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id)


@workflow_engine.on(WF_KEY, "approved")
async def _on_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = _service(db, instance, actor)
    row = await svc.ods.get_one(instance.entity_id)
    if row.status in OPEN:
        await svc.approve(row.id, OdDecision(), via_workflow=True)


@workflow_engine.on(WF_KEY, "rejected")
async def _on_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = _service(db, instance, actor)
    row = await svc.ods.get_one(instance.entity_id)
    if row.status in OPEN:
        await svc.reject(row.id, OdDecision(), via_workflow=True)


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (await db.execute(select(OnDutyRequest).where(OnDutyRequest.id == entity_id))).scalar_one_or_none()
    if row is None:
        return None, None
    return (
        f"On duty · {row.from_date.isoformat()} – {row.to_date.isoformat()} ({row.reason_type})",
        "/admin/attendance/od",
    )


__all__ = ["OdService"]
