"""Credit transfers (MOOC / ABC / other university / prior learning) — Prompts/07 §07.6 ``credit_transfer_service.py``
(``academics.credit_transfer_mooc``).

1. **Submit** (the student; or the office with ``student_id``): on the open enrolment; MOOC sources (SWAYAM, NPTEL,
   Coursera, other MOOC) are capped by ``rules.mooc_max_credits`` over the live transfers (→ 422); an ABC source with
   ``academics.abc_apaar`` on fetches the learner's record through the ``CreditBank`` adapter (Phase 41 ships the real
   adapters — the mock answers until then); the workflow ``students.credit_transfer`` starts (HOD of the student's
   department → registrar). Certificates are uploaded with ``POST /credit-transfers/{id}/certificate``.
2. **Verify** (step 1, ``credit_transfers:verify``): the HOD maps the transfer to an ``equivalent_course_id`` of the
   enrolment's regulation (or an elective basket) → ``verified``.
3. **Approve** (step 2, ``credit_transfers:approve``) → ``approved`` (``approved_by/at``), ``credit_transfer.approved``.
   Phase 15 turns approved transfers into ``student_course_results(attempt_type='credit_transfer')`` with the letter
   grade from ``rules.mooc_grade_map`` and sets ``result_id`` / ``credited`` — **until Phase 15 exists approval stores
   ``status='approved'`` only and Phase 15 back-fills the result rows on install** (Prompts/07 §07.6 note).
4. **Reject** at either step → ``rejected``; the student is notified of every decision.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.workflow import engine as workflow_engine
from app.enums.students import MOOC_SOURCES
from app.models.curriculum import Course, ElectiveBasket
from app.models.platform import Department, WorkflowInstance
from app.models.students import CreditTransfer, Student, StudentProgramEnrollment
from app.repositories.credit_transfer_repository import CreditTransferRepository
from app.repositories.student_scope import student_visibility
from app.schemas.students import CreditTransferCreate, CreditTransferDecision, CreditTransferResponse
from app.services.academics.rules import RulesResolver
from app.services.students.common import StudentServiceBase, snap
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

WORKFLOW_KEY = "students.credit_transfer"
ENTITY = "credit_transfer"
CT_KEYS = ("source", "source_title", "credits", "status", "equivalent_course_id", "elective_basket_id", "approved_by")
TEN_YEARS = 10 * 365 * 24 * 3600


def letter_grade(score: Decimal | None, grade_map: dict[str, str]) -> str | None:
    if score is None:
        return None
    value = float(score)
    for band, grade in grade_map.items():
        try:
            low, high = (float(x) for x in band.split("-", 1))
        except ValueError:
            continue
        if low <= value <= high + 0.999:
            return grade
    return None


class CreditTransferService(StudentServiceBase):
    audit_module = "credit_transfers"

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.repo = CreditTransferRepository(self.db, self.principal, self.inst)

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def list_page(
        self,
        params: PageParams,
        *,
        status: str | None,
        source: str | None,
        department_id: uuid.UUID | None,
        q: str | None,
        scope: str | None,
    ) -> tuple[list[CreditTransferResponse], PaginationMeta, VisibilityMeta]:
        stmt = self.repo.filtered(status=status, source=source, department_id=department_id, q=q, scope=scope)
        rows, total = await self.repo.page(stmt, params.offset, params.page_size)
        pagination = PaginationMeta(
            page=params.page, page_size=params.page_size, total=total, total_pages=max(1, -(-total // params.page_size))
        )
        return await self.responses(list(rows)), pagination, student_visibility(self.principal)

    async def mine(self) -> list[CreditTransferResponse]:
        student = await self._me()
        ids = [e.id for e in await self.enrollments.for_student(student.id)]
        rows, _ = await self.repo.page(self.repo.filtered(enrollment_ids=ids), 0, 200)
        return await self.responses(list(rows))

    async def for_student(self, student_id: uuid.UUID) -> list[CreditTransferResponse]:
        student = await self.students.get_visible(student_id)
        ids = [e.id for e in await self.enrollments.for_student(student.id)]
        rows, _ = await self.repo.page(self.repo.filtered(enrollment_ids=ids), 0, 200)
        return await self.responses(list(rows))

    async def _me(self) -> Student:
        row = await self.students.by_user(self.actor_id) if self.actor_id else None
        if row is None:
            raise APIError(
                404, ErrorCode.NOT_FOUND, "Your account is not linked to a student record", {"reason": "no_student"}
            )
        return row

    async def responses(self, rows: list[CreditTransfer]) -> list[CreditTransferResponse]:
        enrolment_ids = list({r.student_program_enrollment_id for r in rows})
        enrolments = {}
        if enrolment_ids:
            enrolments = {
                e.id: e
                for e in (
                    await self.db.execute(
                        select(StudentProgramEnrollment).where(StudentProgramEnrollment.id.in_(enrolment_ids))
                    )
                ).scalars()
            }
        students = {}
        sids = list({e.student_id for e in enrolments.values()})
        if sids:
            students = {s.id: s for s in (await self.db.execute(select(Student).where(Student.id.in_(sids)))).scalars()}
        depts = {}
        dids = list({e.department_id for e in enrolments.values()})
        if dids:
            depts = {
                d.id: d for d in (await self.db.execute(select(Department).where(Department.id.in_(dids)))).scalars()
            }
        courses = {}
        cids = [r.equivalent_course_id for r in rows if r.equivalent_course_id]
        if cids:
            courses = {c.id: c for c in (await self.db.execute(select(Course).where(Course.id.in_(cids)))).scalars()}
        instances = await self._instances_by_entity([r.id for r in rows])
        actionable = await self.actionable([i.id for i in instances.values()])
        grade_maps: dict[uuid.UUID, dict[str, str]] = {}
        out = []
        for r in rows:
            resp = CreditTransferResponse.model_validate(r)
            e = enrolments.get(r.student_program_enrollment_id)
            if e is not None:
                s = students.get(e.student_id)
                if s is not None:
                    resp.student_id, resp.registration_number, resp.student_name = (
                        s.id,
                        s.registration_number,
                        s.full_name,
                    )
                d = depts.get(e.department_id)
                resp.department_code = d.code if d else None
                if e.program_regulation_id not in grade_maps:
                    rules = await RulesResolver(self.db).for_program_regulation(e.program_regulation_id)
                    grade_maps[e.program_regulation_id] = dict(rules.get("mooc_grade_map") or {})
                if r.source in MOOC_SOURCES:
                    resp.letter_grade = letter_grade(r.source_score_pct, grade_maps[e.program_regulation_id])
            c = courses.get(r.equivalent_course_id) if r.equivalent_course_id else None
            resp.equivalent_course = f"{c.code} · {c.title}" if c else None
            inst = instances.get(r.id)
            if inst is not None:
                resp.workflow_instance_id, resp.workflow_status, resp.current_step = (
                    inst.id,
                    inst.status,
                    inst.current_step,
                )
                resp.can_act = r.status in ("submitted", "verified") and inst.id in actionable
            out.append(resp)
        return out

    async def _instances_by_entity(self, ids: list[uuid.UUID]) -> dict[uuid.UUID, WorkflowInstance]:
        if not ids:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(WorkflowInstance).where(
                        WorkflowInstance.entity_type == ENTITY, WorkflowInstance.entity_id.in_(ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        return {r.entity_id: r for r in rows}

    # ---- rule 1: submit ---------------------------------------------------------------------------------------------
    async def create(self, body: CreditTransferCreate) -> CreditTransferResponse:
        if body.student_id is not None:
            if not (
                self.can("credit_transfers", "verify")
                or self.can("credit_transfers", "approve")
                or self.can("students", "manage")
            ):
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the office submits on behalf of a student")
            student = await self.students.get_visible(body.student_id)
        else:
            student = await self._me()
        enrolment = await self.enrollments.open_for(student.id)
        if enrolment is None:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "The student has no open enrolment")
        rules = await RulesResolver(self.db).for_program_regulation(enrolment.program_regulation_id)
        source = body.source.value
        if source in MOOC_SOURCES:
            cap = Decimal(str(rules.get("mooc_max_credits", 12)))
            used = await self.repo.mooc_credits(enrolment.id)
            if used + body.credits > cap:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"MOOC credits are capped at {float(cap):g}: {float(used):g} already claimed, {float(body.credits):g} more exceeds it",
                    {"field": "credits", "cap": float(cap), "used": float(used)},
                )
        abc_ref = body.abc_credit_ref
        if source == "abc" and await is_enabled(self.inst, "academics.abc_apaar"):
            abc_ref = abc_ref or await self._abc_fetch(student)
        if body.elective_basket_id is not None:
            await self._basket(body.elective_basket_id, enrolment)
        row = await self.repo.add(
            CreditTransfer(
                institution_id=self.inst,
                student_program_enrollment_id=enrolment.id,
                term_id=body.term_id,
                source=source,
                source_course_code=body.source_course_code,
                source_title=body.source_title.strip(),
                source_institution=body.source_institution,
                credits=body.credits,
                source_grade=body.source_grade,
                source_score_pct=body.source_score_pct,
                elective_basket_id=body.elective_basket_id,
                certificate_url=body.certificate_url,
                abc_credit_ref=abc_ref,
                status="submitted",
            )
        )
        await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WORKFLOW_KEY,
            entity_type=ENTITY,
            entity_id=row.id,
            started_by=self.actor_id,
            context={
                "department_id": str(enrolment.department_id),
                "college_id": str(enrolment.college_id),
                "student_id": str(student.id),
                "credits": float(body.credits),
                "source": source,
            },
            title=f"Credit transfer {row.source_title} ({float(row.credits):g} cr) — {student.full_name}",
        )
        await self._audit(
            "create", "credit_transfer", row.id, None, {**snap(row, CT_KEYS), "student_id": str(student.id)}
        )
        await self._emit(
            "credit_transfer.submitted",
            {
                "credit_transfer_id": str(row.id),
                "student_id": str(student.id),
                "source": source,
                "credits": float(row.credits),
            },
            "student",
            student.id,
        )
        return (await self.responses([row]))[0]

    async def _abc_fetch(self, student: Student) -> str | None:
        """``CreditBank.fetch_learner`` over the ``nad_abc`` capability (the mock until Phase 41 connects ABC)."""
        from app.integrations.registry import get_adapter

        learner = student.abc_id or student.apaar_id
        if not learner:
            return None
        try:
            record = await get_adapter("nad_abc").fetch_learner(apaar_id=learner)
        except Exception:  # noqa: BLE001 - an unreachable ABC never blocks the submission
            return None
        ref = (record or {}).get("ref") or (record or {}).get("reference")
        return str(ref)[:60] if ref else None

    async def _basket(self, basket_id: uuid.UUID, enrolment: StudentProgramEnrollment) -> ElectiveBasket:
        basket = (
            await self.db.execute(select(ElectiveBasket).where(ElectiveBasket.id == basket_id))
        ).scalar_one_or_none()
        if basket is None or basket.program_regulation_id != enrolment.program_regulation_id:
            raise APIError(
                422, ErrorCode.VALIDATION, "The basket belongs to another curriculum", {"field": "elective_basket_id"}
            )
        return basket

    async def attach_certificate(self, ct_id: uuid.UUID, upload: UploadFile) -> CreditTransferResponse:
        from app.services.file_service import DOCUMENT_TYPES, IMAGE_TYPES, FileService, storage

        row = await self.repo.get(ct_id, for_update=True)
        if row.status not in ("submitted", "verified"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The credit transfer is {row.status}")
        saved = await FileService(self.db).save(
            upload, "credit-transfers", IMAGE_TYPES + DOCUMENT_TYPES, max_mb=10, institution_id=self.inst
        )
        row.certificate_url = storage.signed_url(saved.key, TEN_YEARS)
        await self.db.flush()
        await self._audit("certificate", "credit_transfer", row.id, None, {"key": saved.key})
        return (await self.responses([row]))[0]

    # ---- rules 2–4: decisions ---------------------------------------------------------------------------------------
    async def decide(self, ct_id: uuid.UUID, decision: str, body: CreditTransferDecision) -> CreditTransferResponse:
        row = await self.repo.get(ct_id, for_update=True)
        expected = {"verify": ("submitted",), "approve": ("verified",), "reject": ("submitted", "verified")}[decision]
        if row.status not in expected:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"A {row.status} credit transfer cannot be {decision}d here",
                {"status": row.status},
            )
        instance = (await self._instances_by_entity([row.id])).get(row.id)
        if instance is None:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "The credit transfer has no workflow")
        if decision == "verify":
            enrolment = await self.enrollments.by_id(row.student_program_enrollment_id)
            assert enrolment is not None
            if body.equivalent_course_id is None and body.elective_basket_id is None and row.elective_basket_id is None:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    "Map the transfer to an equivalent course or a basket",
                    {"field": "equivalent_course_id"},
                )
            if body.equivalent_course_id is not None:
                await self._course(body.equivalent_course_id, enrolment)
            if body.elective_basket_id is not None:
                await self._basket(body.elective_basket_id, enrolment)
        await workflow_engine.act(
            self.db,
            instance_id=instance.id,
            actor=self.principal,
            decision="reject" if decision == "reject" else "approve",
            comment=body.comment,
        )
        await self.db.refresh(row)
        if decision == "verify" and row.status == "submitted":
            old = snap(row, CT_KEYS)
            row.status = "verified"
            if body.equivalent_course_id is not None:
                row.equivalent_course_id = body.equivalent_course_id
            if body.elective_basket_id is not None:
                row.elective_basket_id = body.elective_basket_id
            await self.db.flush()
            await self._audit("verify", "credit_transfer", row.id, old, {**snap(row, CT_KEYS), "comment": body.comment})
            await self._notify_student(row, "verified", body.comment)
        return (await self.responses([row]))[0]

    async def _course(self, course_id: uuid.UUID, enrolment: StudentProgramEnrollment) -> Course:
        from app.models.academic import ProgramRegulation

        reg_id = (
            await self.db.execute(
                select(ProgramRegulation.regulation_id).where(ProgramRegulation.id == enrolment.program_regulation_id)
            )
        ).scalar_one()
        course = (await self.db.execute(select(Course).where(Course.id == course_id))).scalar_one_or_none()
        if course is None or course.regulation_id != reg_id:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "The equivalent course must belong to the student's regulation",
                {"field": "equivalent_course_id"},
            )
        return course

    async def mark(self, row: CreditTransfer, status: str, actor_id: uuid.UUID | None) -> None:
        old = snap(row, CT_KEYS)
        row.status = status
        if status == "approved":
            row.approved_by, row.approved_at = actor_id, datetime.now(UTC)
        await self.db.flush()
        await self._audit(status, "credit_transfer", row.id, old, snap(row, CT_KEYS))
        if status == "approved":
            await self._emit(
                "credit_transfer.approved",
                {
                    "credit_transfer_id": str(row.id),
                    "enrollment_id": str(row.student_program_enrollment_id),
                    "credits": float(row.credits),
                    "equivalent_course_id": str(row.equivalent_course_id) if row.equivalent_course_id else None,
                },
                "credit_transfer",
                row.id,
            )
        await self._notify_student(row, status, None)

    async def _notify_student(self, row: CreditTransfer, decision: str, comment: str | None) -> None:
        enrolment = await self.enrollments.by_id(row.student_program_enrollment_id)
        student = await self.students.by_id(enrolment.student_id) if enrolment else None
        if student is not None:
            await self._notify(
                "credit_transfer.decided",
                [student.user_id],
                {
                    "title": row.source_title,
                    "credits": f"{float(row.credits):g}",
                    "decision": decision,
                    "comment": comment or "",
                },
            )


# ---- workflow hooks + inbox summaries --------------------------------------------------------------------------------
async def _row(db: Any, instance: WorkflowInstance) -> CreditTransfer | None:
    if instance.entity_type != ENTITY:
        return None
    return await CreditTransferRepository(db).get_any(instance.entity_id, for_update=True)


@workflow_engine.on(WORKFLOW_KEY, "approved")
async def _on_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await _row(db, instance)
    if row is not None and row.status in ("submitted", "verified"):
        await CreditTransferService(db, actor, institution_id=instance.institution_id).mark(
            row, "approved", getattr(actor, "id", None)
        )


@workflow_engine.on(WORKFLOW_KEY, "rejected")
async def _on_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await _row(db, instance)
    if row is not None and row.status in ("submitted", "verified"):
        await CreditTransferService(db, actor, institution_id=instance.institution_id).mark(
            row, "rejected", getattr(actor, "id", None)
        )


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(CreditTransfer, Student)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.id == CreditTransfer.student_program_enrollment_id)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(CreditTransfer.id == entity_id)
        )
    ).first()
    if row is None:
        return None, None
    ct, student = row
    return (
        f"{student.full_name} · {ct.source_title} ({float(ct.credits):g} cr, {ct.source})",
        f"/admin/students/credit-transfers?ct={entity_id}",
    )
