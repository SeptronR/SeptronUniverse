"""Transfers & migration — Prompts/07 §07.6 ``transfer_service.py`` (``students.transfers_migration``).

Status machine ``requested → dues_check → approved → completed`` (``rejected`` on any rejection):

1. **Request** (the registrar, or the student for the own record): one open request per student (409); the workflow
   ``students.transfer`` starts (registrar → principal = ``vice_chancellor``; context: the student's department and
   college). ``from_ref`` snapshots the current placement; ``transfer.requested`` is emitted.
2. The registrar's approval moves the request to ``dues_check`` — Phase 12 raises the ``no_dues`` request there and
   holds the request until every desk clears; until Phase 12 exists the check passes through. The principal's approval
   → ``approved`` (``approved_by``); a rejection → ``rejected``; the student / guardians are notified.
3. **Complete** (``approved`` only): certificate numbers from the institution's sequences (``tc_no`` →
   ``TC/{yyyy}/{seq:5}``, ``migration_cert_no`` → ``MIG/{yyyy}/{seq:5}``, created on first use; Phase 26 renders the
   certificates from its templates), ``effective_date``; leaving transfers (``migration_out`` / ``inter_university``)
   make the student ``transferred`` (enrolment ``transferred``, user deactivated); ``inter_college`` /
   ``program_change`` with a target ``to_ref.batch_id`` close the enrolment and open one in the target batch
   (``entry_type='migrated'``); ``transfer.completed`` is emitted.
"""

import uuid
from typing import Any

from sqlalchemy import select, text

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.academic import Batch, BatchSection, Program
from app.models.platform import WorkflowInstance
from app.models.students import Student, StudentProgramEnrollment, StudentTransfer
from app.repositories.sequence_repository import SequenceRepository, date_context, render
from app.repositories.student_scope import student_visibility
from app.repositories.transfer_repository import TransferRepository
from app.schemas.students import TransferComplete, TransferCreate, TransferResponse
from app.services.students.common import StudentServiceBase, snap
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

WORKFLOW_KEY = "students.transfer"
ENTITY = "student_transfer"
LEAVING = {"migration_out", "inter_university"}
MOVING = {"inter_college", "program_change"}
TRANSFER_KEYS = ("transfer_type", "status", "tc_no", "migration_certificate_no", "effective_date", "approved_by")
SEQUENCES = {"tc_no": "TC/{yyyy}/{seq:5}", "migration_cert_no": "MIG/{yyyy}/{seq:5}"}


class TransferService(StudentServiceBase):
    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.repo = TransferRepository(self.db, self.principal, self.inst)

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, *, status: str | None, transfer_type: str | None, q: str | None, scope: str | None
    ) -> tuple[list[TransferResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.repo.filtered(status=status, transfer_type=transfer_type, q=q, scope=scope)
        rows, total = await self.repo.page(stmt, params.offset, params.page_size)
        pagination = PaginationMeta(
            page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size))
        )
        return await self.responses(list(rows)), pagination, student_visibility(self.principal)

    async def for_student(self, student_id: uuid.UUID) -> list[TransferResponse]:
        student = await self.students.get_visible(student_id)
        rows, _ = await self.repo.page(self.repo.filtered(student_id=student.id), 0, 100)
        return await self.responses(list(rows))

    async def responses(self, rows: list[StudentTransfer]) -> list[TransferResponse]:
        students = {}
        ids = list({r.student_id for r in rows})
        if ids:
            students = {s.id: s for s in (await self.db.execute(select(Student).where(Student.id.in_(ids)))).scalars()}
        instances = await self.workflow_instances([r.workflow_instance_id for r in rows])
        actionable = await self.actionable([r.workflow_instance_id for r in rows])
        out = []
        for r in rows:
            resp = TransferResponse.model_validate(r)
            s = students.get(r.student_id)
            if s is not None:
                resp.registration_number, resp.student_name = s.registration_number, s.full_name
            inst = instances.get(r.workflow_instance_id) if r.workflow_instance_id else None
            if inst is not None:
                resp.workflow_status, resp.current_step = inst.status, inst.current_step
            resp.can_act = r.status in ("requested", "dues_check") and r.workflow_instance_id in actionable
            out.append(resp)
        return out

    # ---- rule 1 -----------------------------------------------------------------------------------------------------
    async def create(self, student_id: uuid.UUID, body: TransferCreate) -> TransferResponse:
        student = await self.students.get_visible(student_id, for_update=True)
        own = student.user_id is not None and student.user_id == self.actor_id
        if not own and not self.can("students", "transfer"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires students:transfer")
        if student.status in ("transferred", "exited", "graduated", "alumni", "expelled", "deceased", "dropped_out"):
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"A {student.status} student cannot request a transfer")
        if await self.repo.open_for(student.id) is not None:
            raise APIError(409, ErrorCode.CONFLICT, "An open transfer request already exists")
        enrolment = await self.enrollments.current(student.id)
        placement: dict[str, Any] = {
            "registration_number": student.registration_number,
            "college_id": str(student.college_id),
        }
        if enrolment is not None:
            program = (await self.students.program_rows([enrolment.program_id])).get(enrolment.program_id)
            batch = (await self.students.batch_rows([enrolment.batch_id])).get(enrolment.batch_id)
            placement |= {
                "enrollment_id": str(enrolment.id),
                "program_code": program.code if program else None,
                "batch_code": batch.code if batch else None,
                "department_id": str(enrolment.department_id),
            }
        row = await self.repo.add(
            StudentTransfer(
                institution_id=self.inst,
                student_id=student.id,
                transfer_type=body.transfer_type.value,
                from_ref=placement,
                to_ref=body.to_ref,
                reason=body.reason,
                effective_date=body.effective_date,
                status="requested",
            )
        )
        instance = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WORKFLOW_KEY,
            entity_type=ENTITY,
            entity_id=row.id,
            started_by=self.actor_id,
            context={
                "department_id": str(enrolment.department_id) if enrolment else None,
                "college_id": str(student.college_id),
                "student_id": str(student.id),
                "transfer_type": row.transfer_type,
            },
            title=f"{row.transfer_type.replace('_', ' ').title()} — {student.full_name} ({student.registration_number})",
        )
        row.workflow_instance_id = instance.id
        await self.db.flush()
        await self._audit(
            "transfer_request",
            "student_transfer",
            row.id,
            None,
            {**snap(row, TRANSFER_KEYS), "student_id": str(student.id)},
        )
        await self._emit(
            "transfer.requested",
            {"transfer_id": str(row.id), "student_id": str(student.id), "transfer_type": row.transfer_type},
            "student",
            student.id,
        )
        return (await self.responses([row]))[0]

    # ---- rule 2 -----------------------------------------------------------------------------------------------------
    async def decide(self, transfer_id: uuid.UUID, decision: str, comment: str | None) -> TransferResponse:
        row = await self.repo.get(transfer_id, for_update=True)
        if row.status not in ("requested", "dues_check") or row.workflow_instance_id is None:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The transfer request is {row.status}")
        await workflow_engine.act(
            self.db, instance_id=row.workflow_instance_id, actor=self.principal, decision=decision, comment=comment
        )
        await self.db.refresh(row)
        return (await self.responses([row]))[0]

    async def mark(self, row: StudentTransfer, status: str, actor_id: uuid.UUID | None) -> None:
        old = snap(row, TRANSFER_KEYS)
        row.status = status
        if status == "approved":
            row.approved_by = actor_id
        await self.db.flush()
        await self._audit(f"transfer_{status}", "student_transfer", row.id, old, snap(row, TRANSFER_KEYS))
        if status in ("approved", "rejected"):
            student = await self.students.by_id(row.student_id)
            if student is not None:
                await self._notify(
                    "transfer.decided",
                    [student.user_id],
                    {
                        "transfer_type": row.transfer_type.replace("_", " "),
                        "student_name": student.full_name,
                        "decision": status,
                    },
                    guardians=True,
                )

    # ---- rule 3 -----------------------------------------------------------------------------------------------------
    async def complete(self, transfer_id: uuid.UUID, body: TransferComplete) -> TransferResponse:
        from app.services.student_service import StudentService

        row = await self.repo.get(transfer_id, for_update=True)
        if not self.can("students", "transfer"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires students:transfer")
        if row.status != "approved":
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Only approved requests complete (this one is {row.status})")
        student = await self.students.by_id(row.student_id, for_update=True)
        assert student is not None
        old = snap(row, TRANSFER_KEYS)
        if row.transfer_type in LEAVING | {"inter_college"}:
            row.tc_no = await self._number("tc_no", student.college_id)
        if row.transfer_type in LEAVING:
            row.migration_certificate_no = await self._number("migration_cert_no", student.college_id)
        row.effective_date = body.effective_date or row.effective_date or await self.today()
        row.status = "completed"
        await self.db.flush()
        students = StudentService(self.db, self.principal, self.request, self.inst)
        if row.transfer_type in LEAVING:
            await students.apply_status(
                student, "transferred", f"{row.transfer_type} completed", enrollment_status="transferred"
            )
        elif row.transfer_type in MOVING and (row.to_ref or {}).get("batch_id"):
            await self._move(student, row)
        await self._audit("transfer_complete", "student_transfer", row.id, old, snap(row, TRANSFER_KEYS))
        await self._emit(
            "transfer.completed",
            {
                "transfer_id": str(row.id),
                "student_id": str(student.id),
                "transfer_type": row.transfer_type,
                "tc_no": row.tc_no,
                "migration_certificate_no": row.migration_certificate_no,
            },
            "student",
            student.id,
        )
        await self._notify(
            "transfer.decided",
            [student.user_id],
            {
                "transfer_type": row.transfer_type.replace("_", " "),
                "student_name": student.full_name,
                "decision": "completed",
            },
            guardians=True,
        )
        return (await self.responses([row]))[0]

    async def _number(self, scope_key: str, college_id: uuid.UUID) -> str:
        await self.db.execute(
            text(
                "INSERT INTO number_sequences (institution_id, college_id, scope_key, pattern, next_value, padding, "
                "reset_policy) SELECT CAST(:i AS uuid), NULL, CAST(:k AS varchar), CAST(:p AS varchar), 1, 5, 'yearly' "
                "WHERE NOT EXISTS (SELECT 1 FROM number_sequences "
                "WHERE institution_id = CAST(:i AS uuid) AND college_id IS NULL AND scope_key = CAST(:k AS varchar))"
            ),
            {"i": self.inst, "k": scope_key, "p": SEQUENCES[scope_key]},
        )
        value, seq = await SequenceRepository(self.db, self.principal, self.inst).next_value(
            self.inst, scope_key, college_id
        )
        return render(seq.pattern, date_context(await self.today()), value, seq.padding)

    async def _move(self, student: Student, row: StudentTransfer) -> None:
        try:
            target_id = uuid.UUID(str((row.to_ref or {}).get("batch_id")))
        except ValueError:
            raise APIError(
                422, ErrorCode.VALIDATION, "to_ref.batch_id is not a batch id", {"field": "to_ref.batch_id"}
            ) from None
        target = (await self.db.execute(select(Batch).where(Batch.id == target_id))).scalar_one_or_none()
        if target is None:
            raise APIError(422, ErrorCode.VALIDATION, "The target batch does not exist", {"field": "to_ref.batch_id"})
        program = (await self.db.execute(select(Program).where(Program.id == target.program_id))).scalar_one()
        current = await self.enrollments.open_for(student.id, for_update=True)
        if current is not None:
            current.status = "transferred"
            await self.db.flush()
        enrolment = StudentProgramEnrollment(
            institution_id=self.inst,
            college_id=target.college_id,
            student_id=student.id,
            program_id=program.id,
            batch_id=target.id,
            program_regulation_id=target.program_regulation_id,
            department_id=program.department_id,
            admission_date=row.effective_date or await self.today(),
            entry_type="migrated",
            entry_term_number=target.current_term_number,
            expected_exit_term=program.total_terms,
            status="active",
            created_by=self.actor_id,
        )
        self.db.add(enrolment)
        await self.db.flush()
        student.college_id = target.college_id
        term = await self.current_term(target.college_id)
        if term is not None:
            section = (
                (
                    await self.db.execute(
                        select(BatchSection).where(BatchSection.batch_id == target.id).order_by(BatchSection.name)
                    )
                )
                .scalars()
                .first()
            )
            await self.terms.get_or_create(
                enrolment.id, term.id, target.current_term_number, section_id=section.id if section else None
            )
        await self.db.flush()


# ---- workflow hooks + inbox summaries --------------------------------------------------------------------------------
async def _row(db: Any, instance: WorkflowInstance) -> StudentTransfer | None:
    if instance.entity_type != ENTITY:
        return None
    return await TransferRepository(db).get_any(instance.entity_id, for_update=True)


@workflow_engine.on(WORKFLOW_KEY, "step_approved")
async def _on_step(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await _row(db, instance)
    if row is not None and row.status == "requested" and instance.current_step == 1:
        await TransferService(db, actor, institution_id=instance.institution_id).mark(
            row, "dues_check", getattr(actor, "id", None)
        )


@workflow_engine.on(WORKFLOW_KEY, "approved")
async def _on_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await _row(db, instance)
    if row is not None and row.status in ("requested", "dues_check"):
        await TransferService(db, actor, institution_id=instance.institution_id).mark(
            row, "approved", getattr(actor, "id", None)
        )


@workflow_engine.on(WORKFLOW_KEY, "rejected")
async def _on_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await _row(db, instance)
    if row is not None and row.status in ("requested", "dues_check"):
        await TransferService(db, actor, institution_id=instance.institution_id).mark(
            row, "rejected", getattr(actor, "id", None)
        )


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(StudentTransfer, Student)
            .join(Student, Student.id == StudentTransfer.student_id)
            .where(StudentTransfer.id == entity_id)
        )
    ).first()
    if row is None:
        return None, None
    transfer, student = row
    return (
        f"{student.full_name} ({student.registration_number}) · {transfer.transfer_type.replace('_', ' ')}",
        f"/admin/students/transfers?transfer={entity_id}",
    )
