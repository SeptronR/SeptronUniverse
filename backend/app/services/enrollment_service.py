"""Programme enrolments, term records, promotion, NEP exit / re-entry and academic standing — Prompts/07 §07.6
``enrollment_service.py``.

Rules
1. ``promote_batch(batch, request)``: ``to_term_number`` defaults to the batch's ``current_term_number + 1`` (it may be
   the current one again — a re-run — never further ahead, never past the programme's last term). Candidates are the
   batch's **active** enrolments with a term record at ``to − 1``; the new records go into the academic term that
   follows that record's term (the college's own terms first, then institution-wide — 409 when none exists). With
   ``apply_detention_rule`` an enrolment whose open arrears (``student_arrears``, Phases 09/15) exceed
   ``rules.max_backlogs_for_promotion`` is **detained** (enrolment + term record ``detained``, student ``detained``,
   ``student.detained``); everyone else gets the next record (section and roll number carried) and
   ``batch.current_term_number`` moves on. Enrolments on break are listed, never promoted. Idempotent: an enrolment
   that already has the target record is counted as ``already_promoted``. ``dry_run`` returns the preview only; the
   real run is the job ``students.promote`` (web) or runs inline (rollover hook, seeder). ``batch.promoted`` is emitted.
2. ``exit(enrollment, award)``: only at a structure term flagged ``is_exit_point`` (the enrolment's current term), the
   award must be that exit point's award and ``credits_earned ≥ exit_points[award].min_credits`` (Phase 15 maintains
   ``credits_earned``) — else ``409 RULE_VIOLATION``. Enrolment ``exited_early`` (+ award, date), student ``exited``
   (user deactivated), ``student.exited`` (Phase 18 creates the certificate / diploma).
3. ``reentry(student, request)``: after an exit — a new enrolment ``entry_type='exit_reentry'`` in another batch of the
   programme (the partial unique index ``one_active_enrollment`` guarantees a single open enrolment → 409), carrying the
   prior credits as ``credit_transfers(source='internal_prior', status='approved')`` plus the selected approved
   transfers, and a term record at ``entry_term_number`` (the batch's current or next term).
4. ``change_section`` / ``change_regulation`` — explicit and audited; a regulation change maps passed courses by code to
   the new regulation as ``internal_prior`` credit transfers.
5. ``recompute_standing(enrollment)`` (Phase 15 calls it at every publish; the dev route before that): evaluates
   ``rules.standing_rules`` over the SGPA / CGPA history of the term records (``sgpa_below`` on the latest term,
   ``cgpa_below`` over ``consecutive_terms`` latest terms, ``backlogs_above`` on open arrears) — the most severe match
   wins (``good`` otherwise); a change is audited (the history) and notified; ``dismissal`` places an ``all`` hold.
"""

import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core import jobs
from app.core.academic_hooks import register_rollover_hook
from app.core.errors import APIError, ErrorCode
from app.enums.students import OPEN_ENROLLMENT, STANDING_SEVERITY
from app.models.academic import AcademicTerm, Batch, BatchSection, Program, ProgramRegulation, ProgramStructureTerm
from app.models.students import CreditTransfer, Student, StudentProgramEnrollment, StudentTermRecord
from app.repositories.batch_repository import BatchRepository
from app.schemas.students import (
    EnrollmentResponse,
    ExitRequest,
    PromoteBatchRequest,
    PromotionPreview,
    PromotionRow,
    ReentryRequest,
    RegulationChange,
    SectionChange,
    StandingHistoryItem,
    StandingResponse,
    TermRecordResponse,
)
from app.services.academics.context import check_department_writable, writable_department_ids
from app.services.academics.rules import RulesResolver
from app.services.students.common import StudentServiceBase, snap

ENROLLMENT_KEYS = (
    "status",
    "batch_id",
    "program_regulation_id",
    "exit_award",
    "exit_date",
    "credits_earned",
    "academic_standing",
    "entry_type",
)


class EnrollmentService(StudentServiceBase):
    # ---- reads ------------------------------------------------------------------------------------------------------
    async def for_student(self, student_id: uuid.UUID) -> list[EnrollmentResponse]:
        student = await self.students.get_visible(student_id)
        return await self.enrollment_responses(await self.enrollments.for_student(student.id))

    async def get(self, enrollment_id: uuid.UUID) -> EnrollmentResponse:
        return (await self.enrollment_responses([await self.enrollments.get_visible(enrollment_id)]))[0]

    async def term_records(self, enrollment_id: uuid.UUID) -> list[TermRecordResponse]:
        enrolment = await self.enrollments.get_visible(enrollment_id)
        return await self.term_record_responses(await self.terms.for_enrollment(enrolment.id))

    # ---- rule 1: promotion ------------------------------------------------------------------------------------------
    async def _batch(self, batch_id: uuid.UUID, *, write: bool) -> tuple[Batch, Program]:
        batch = await BatchRepository(self.db, self.principal, self.inst).get_batch(batch_id)
        program = (await self.db.execute(select(Program).where(Program.id == batch.program_id))).scalar_one()
        if write and self.principal is not None and not getattr(self.principal, "is_super_admin", False):
            check_department_writable(
                await writable_department_ids(self.db, self.principal), program.department_id, create=False
            )
        return batch, program

    async def promote(
        self, batch_id: uuid.UUID, body: PromoteBatchRequest, *, dry_run: bool | None = None
    ) -> PromotionPreview:
        """Preview (``dry_run``) or enqueue the promotion job; the job calls ``run_promotion``."""
        if body.batch_id is not None and body.batch_id != batch_id:
            raise APIError(422, ErrorCode.VALIDATION, "batch_id does not match the path", {"field": "batch_id"})
        preview = await self.run_promotion(batch_id, body, dry_run=True)
        if dry_run if dry_run is not None else body.dry_run:
            return preview
        if preview.blocking:
            raise APIError(409, ErrorCode.RULE_VIOLATION, preview.blocking, {"reason": "promotion_blocked"})
        job = await jobs.enqueue(
            self.db,
            self.principal,
            "students.promote",
            {
                "batch_id": str(batch_id),
                "to_term_number": preview.to_term_number,
                "apply_detention_rule": body.apply_detention_rule,
            },
            queue="reports",
        )
        preview.dry_run, preview.job_id = False, job.id
        return preview

    async def run_promotion(
        self,
        batch_id: uuid.UUID,
        body: PromoteBatchRequest,
        *,
        dry_run: bool,
        target_term: AcademicTerm | None = None,
        progress: Callable[[int, str], Awaitable[None]] | None = None,
    ) -> PromotionPreview:
        batch, program = await self._batch(batch_id, write=True)
        to_number = body.to_term_number or (batch.current_term_number or 1) + 1
        if to_number > batch.current_term_number + 1:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"{batch.code} is in term {batch.current_term_number}: promote one term at a time",
                {"field": "to_term_number"},
            )
        if to_number < 2 or to_number > program.total_terms:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"Term {to_number} is outside {program.code} (terms 1–{program.total_terms}); final-term students "
                "graduate through Phase 18",
                {"field": "to_term_number"},
            )
        if to_number < batch.current_term_number:
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"{batch.code} is already in term {batch.current_term_number}"
            )
        rules = await RulesResolver(self.db).for_program_regulation(batch.program_regulation_id)
        max_backlogs = int(rules.get("max_backlogs_for_promotion", 4))
        pairs = await self.enrollments.of_batch(batch.id, OPEN_ENROLLMENT, for_update=not dry_run)
        enrolment_ids = [e.id for e, _ in pairs]
        sources = await self.terms.at_number(enrolment_ids, to_number - 1, for_update=not dry_run)
        existing = await self.terms.at_number(enrolment_ids, to_number)
        backlogs = await self.enrollments.backlog_counts(enrolment_ids) if body.apply_detention_rule else {}
        sections = await self.students.section_rows([r.section_id for r in sources.values()])
        from_term = None
        sample = next(iter(sources.values()), None)
        if sample is not None:
            from_term = await self.terms.term(sample.term_id)
        to_term = target_term or (await self.terms.next_term(from_term, batch.college_id) if from_term else None)
        preview = PromotionPreview(
            batch_id=batch.id,
            batch_code=batch.code,
            from_term_number=to_number - 1,
            to_term_number=to_number,
            from_term={"id": str(from_term.id), "name": from_term.name} if from_term else None,
            to_term=(
                {"id": str(to_term.id), "name": to_term.name, "start_date": to_term.start_date.isoformat()}
                if to_term
                else None
            ),
            max_backlogs=max_backlogs,
            dry_run=dry_run,
        )
        if from_term is not None and to_term is None:
            preview.blocking = f"No academic term follows {from_term.name} — create the next term first"
        promote: list[tuple[StudentProgramEnrollment, Student, StudentTermRecord]] = []
        detain: list[tuple[StudentProgramEnrollment, Student, StudentTermRecord, int]] = []
        for e, s in pairs:
            source = sources.get(e.id)
            row = PromotionRow(
                student_id=s.id,
                enrollment_id=e.id,
                registration_number=s.registration_number,
                name=s.full_name,
                section_name=sections[source.section_id].name if source and source.section_id in sections else None,
                backlogs=backlogs.get(e.id, 0),
            )
            if e.status == "break":
                preview.on_break.append(row)
            elif e.status != "active" or source is None:
                continue
            elif e.id in existing:
                preview.already_promoted += 1
            elif body.apply_detention_rule and row.backlogs > max_backlogs:
                preview.detained.append(row)
                detain.append((e, s, source, row.backlogs))
            else:
                preview.promoted.append(row)
                promote.append((e, s, source))
        if dry_run or preview.blocking:
            return preview
        assert to_term is not None
        total = max(len(promote) + len(detain), 1)
        for done, (e, _student, source) in enumerate(promote, start=1):
            if source.status in ("pending_registration", "registered", "in_progress", "exam_pending"):
                source.status = "completed"
            await self.terms.get_or_create(
                e.id, to_term.id, to_number, section_id=source.section_id, roll_number=source.roll_number
            )
            if progress and done % 25 == 0:
                await progress(int(done * 90 / total), f"{done}/{total} enrolments")
        for e, s, source, n in detain:
            e.status = "detained"
            source.status = "detained"
            if s.status in ("active", "admitted"):
                s.status = "detained"
            await self._emit(
                "student.detained",
                {
                    "student_id": str(s.id),
                    "enrollment_id": str(e.id),
                    "term_number": to_number - 1,
                    "backlogs": n,
                    "max_backlogs": max_backlogs,
                },
                "student",
                s.id,
            )
            await self._notify(
                "student.detained",
                [s.user_id],
                {
                    "student_name": s.full_name,
                    "term_number": to_number - 1,
                    "backlogs": n,
                    "max_backlogs": max_backlogs,
                },
                guardians=True,
            )
        if promote:
            await self._notify(
                "student.promoted",
                [s.user_id for _, s, _ in promote],
                {"student_name": "You", "term_number": to_number, "term_name": to_term.name},
            )
        previous = batch.current_term_number
        batch.current_term_number = max(batch.current_term_number, to_number)
        await self.db.flush()
        await self._audit(
            "promote",
            "batch",
            batch.id,
            {"current_term_number": previous},
            {
                "current_term_number": batch.current_term_number,
                "promoted": len(promote),
                "detained": len(detain),
                "already_promoted": preview.already_promoted,
                "to_term_id": str(to_term.id),
            },
        )
        await self._emit(
            "batch.promoted",
            {
                "batch_id": str(batch.id),
                "from_term_number": to_number - 1,
                "to_term_number": to_number,
                "to_term_id": str(to_term.id),
                "promoted": len(promote),
                "detained": len(detain),
            },
            "batch",
            batch.id,
        )
        return preview

    # ---- rule 2: exit -----------------------------------------------------------------------------------------------
    async def _exit_points(
        self, enrolment: StudentProgramEnrollment
    ) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
        rules = await RulesResolver(self.db).for_program_regulation(enrolment.program_regulation_id)
        points = {int(p["after_term"]): dict(p) for p in rules.get("exit_points", [])}
        structure = (
            (
                await self.db.execute(
                    select(ProgramStructureTerm).where(
                        ProgramStructureTerm.program_regulation_id == enrolment.program_regulation_id
                    )
                )
            )
            .scalars()
            .all()
        )
        flagged = {t.term_number: t for t in structure if t.is_exit_point}
        out: dict[int, dict[str, Any]] = {}
        for n, term in flagged.items():
            spec = points.get(n, {})
            out[n] = {"award": term.exit_award or spec.get("award"), "min_credits": float(spec.get("min_credits") or 0)}
        return out, rules

    async def exit(self, enrollment_id: uuid.UUID, body: ExitRequest) -> EnrollmentResponse:
        from app.services.student_service import StudentService

        enrolment = await self.enrollments.get_visible(enrollment_id, for_update=True)
        if enrolment.status not in OPEN_ENROLLMENT:
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"The enrolment is {enrolment.status}")
        latest = (await self.terms.latest_for([enrolment.id])).get(enrolment.id)
        term_number = latest.term_number if latest else enrolment.entry_term_number
        points, _ = await self._exit_points(enrolment)
        point = points.get(term_number)
        if point is None:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"Term {term_number} is not an exit point of this programme",
                {"term_number": term_number, "exit_points": sorted(points)},
            )
        if point["award"] and body.exit_award != point["award"]:
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"The exit after term {term_number} awards a {point['award']}",
                {"field": "exit_award", "award": point["award"]},
            )
        if Decimal(enrolment.credits_earned or 0) < Decimal(str(point["min_credits"])):
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                f"A {body.exit_award} needs {point['min_credits']:g} credits; {float(enrolment.credits_earned):g} earned",
                {"credits_earned": float(enrolment.credits_earned), "min_credits": point["min_credits"]},
            )
        old = snap(enrolment, ENROLLMENT_KEYS)
        enrolment.status, enrolment.exit_award = "exited_early", body.exit_award
        enrolment.exit_date = body.exit_date or await self.today()
        await self.db.flush()
        student = await self.students.by_id(enrolment.student_id, for_update=True)
        assert student is not None
        await StudentService(self.db, self.principal, self.request, self.inst).apply_status(
            student, "exited", body.reason or f"NEP exit with {body.exit_award}", enrollment_status="exited_early"
        )
        await self._audit(
            "exit", "enrollment", enrolment.id, old, {**snap(enrolment, ENROLLMENT_KEYS), "term_number": term_number}
        )
        program = (await self.students.program_rows([enrolment.program_id])).get(enrolment.program_id)
        await self._emit(
            "student.exited",
            {
                "student_id": str(student.id),
                "enrollment_id": str(enrolment.id),
                "award": body.exit_award,
                "term_number": term_number,
                "credits_earned": float(enrolment.credits_earned),
                "exit_date": enrolment.exit_date.isoformat(),
            },
            "student",
            student.id,
        )
        await self._notify(
            "student.exited",
            [student.user_id],
            {
                "student_name": student.full_name,
                "program": program.name if program else "",
                "term_number": term_number,
                "award": body.exit_award,
            },
            guardians=True,
        )
        return (await self.enrollment_responses([enrolment]))[0]

    # ---- rule 3: re-entry -------------------------------------------------------------------------------------------
    async def reentry(self, student_id: uuid.UUID, body: ReentryRequest) -> EnrollmentResponse:
        student = await self.students.get_visible(student_id, for_update=True)
        if await self.enrollments.open_for(student.id) is not None:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "The student already has an open enrolment",
                {"reason": "one_active_enrollment"},
            )
        previous = [e for e in await self.enrollments.for_student(student.id) if e.status == "exited_early"]
        if not previous:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "Re-entry needs an earlier exit (exited_early enrolment)")
        prior = previous[0]
        batch = (
            await self.db.execute(select(Batch).where(Batch.id == body.batch_id, Batch.institution_id == self.inst))
        ).scalar_one_or_none()
        if batch is None or batch.program_id != body.program_id:
            raise APIError(422, ErrorCode.VALIDATION, "The batch belongs to another programme", {"field": "batch_id"})
        program = (await self.db.execute(select(Program).where(Program.id == body.program_id))).scalar_one()
        if body.entry_term_number not in (batch.current_term_number, batch.current_term_number + 1):
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"{batch.code} is in term {batch.current_term_number}: re-enter at that term or the next one",
                {"field": "entry_term_number"},
            )
        if body.entry_term_number > program.total_terms:
            raise APIError(
                422, ErrorCode.VALIDATION, "Beyond the programme's last term", {"field": "entry_term_number"}
            )
        carried = []
        if body.carried_credit_transfer_ids:
            from app.repositories.credit_transfer_repository import CreditTransferRepository

            rows = await CreditTransferRepository(self.db).by_ids(body.carried_credit_transfer_ids)
            own = {e.id for e in await self.enrollments.for_student(student.id)}
            for ct in rows:
                if ct.student_program_enrollment_id not in own or ct.status not in ("approved", "credited"):
                    raise APIError(
                        422,
                        ErrorCode.VALIDATION,
                        "Only the student's approved credit transfers can be carried",
                        {"field": "carried_credit_transfer_ids"},
                    )
            carried = list(rows)
        enrolment = StudentProgramEnrollment(
            institution_id=self.inst,
            college_id=batch.college_id,
            student_id=student.id,
            program_id=program.id,
            batch_id=batch.id,
            program_regulation_id=batch.program_regulation_id,
            department_id=program.department_id,
            admission_date=await self.today(),
            entry_type="exit_reentry",
            entry_term_number=body.entry_term_number,
            expected_exit_term=program.total_terms,
            status="active",
            created_by=self.actor_id,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(enrolment)
                await self.db.flush()
        except IntegrityError:
            raise APIError(
                409,
                ErrorCode.CONFLICT,
                "Only one open enrolment per student (or this batch was already joined)",
                {"reason": "one_active_enrollment"},
            ) from None
        credits = Decimal(prior.credits_earned or 0)
        institution = await self.institution()
        rows_to_add = (
            [
                CreditTransfer(
                    institution_id=self.inst,
                    student_program_enrollment_id=enrolment.id,
                    source="internal_prior",
                    source_title=f"Credits of the earlier enrolment (exited with {prior.exit_award or 'an exit award'})",
                    source_institution=institution.name,
                    credits=min(credits, Decimal("30.0")) if credits else Decimal("0.5"),
                    status="approved",
                    approved_by=self.actor_id,
                )
            ]
            if credits > 0
            else []
        )
        for ct in carried:
            rows_to_add.append(
                CreditTransfer(
                    institution_id=self.inst,
                    student_program_enrollment_id=enrolment.id,
                    term_id=ct.term_id,
                    source="internal_prior",
                    source_course_code=ct.source_course_code,
                    source_title=ct.source_title,
                    source_institution=ct.source_institution,
                    credits=ct.credits,
                    source_grade=ct.source_grade,
                    source_score_pct=ct.source_score_pct,
                    equivalent_course_id=ct.equivalent_course_id,
                    certificate_url=ct.certificate_url,
                    status="approved",
                    approved_by=self.actor_id,
                )
            )
        for row in rows_to_add:
            self.db.add(row)
        enrolment.credits_earned = credits
        await self.db.flush()
        term = await self.current_term(batch.college_id)
        if term is not None:
            target = term
            if body.entry_term_number == batch.current_term_number + 1:
                target = await self.terms.next_term(term, batch.college_id) or term
            section = (
                (
                    await self.db.execute(
                        select(BatchSection).where(BatchSection.batch_id == batch.id).order_by(BatchSection.name)
                    )
                )
                .scalars()
                .first()
            )
            await self.terms.get_or_create(
                enrolment.id,
                target.id,
                body.entry_term_number,
                section_id=body.section_id or (section.id if section else None),
            )
        previous_status = student.status
        student.status = "active"
        if student.user_id:
            user = (await self.students.users([student.user_id])).get(student.user_id)
            if user is not None:
                user.is_active = True
        await self.db.flush()
        await self._audit(
            "reentry",
            "student",
            student.id,
            {"status": previous_status, "prior_enrollment_id": str(prior.id)},
            {
                "status": "active",
                "enrollment_id": str(enrolment.id),
                "carried": len(rows_to_add),
                "credits": float(credits),
            },
        )
        await self._emit(
            "student.reentered",
            {
                "student_id": str(student.id),
                "enrollment_id": str(enrolment.id),
                "prior_enrollment_id": str(prior.id),
                "entry_term_number": body.entry_term_number,
            },
            "student",
            student.id,
        )
        return (await self.enrollment_responses([enrolment]))[0]

    # ---- rule 4: section / regulation change ------------------------------------------------------------------------
    async def change_section(self, enrollment_id: uuid.UUID, body: SectionChange) -> EnrollmentResponse:
        enrolment = await self.enrollments.get_visible(enrollment_id, for_update=True)
        section = (
            await self.db.execute(select(BatchSection).where(BatchSection.id == body.section_id))
        ).scalar_one_or_none()
        if section is None or section.batch_id != enrolment.batch_id:
            raise APIError(422, ErrorCode.VALIDATION, "The section belongs to another batch", {"field": "section_id"})
        latest = (await self.terms.latest_for([enrolment.id])).get(enrolment.id)
        if latest is None:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "The enrolment has no term record yet")
        old = {"section_id": str(latest.section_id) if latest.section_id else None}
        latest.section_id = section.id
        await self.db.flush()
        await self._audit(
            "change_section", "enrollment", enrolment.id, old, {"section_id": str(section.id), "reason": body.reason}
        )
        await self._emit(
            "student.updated",
            {"student_id": str(enrolment.student_id), "fields": ["section"]},
            "student",
            enrolment.student_id,
        )
        return (await self.enrollment_responses([enrolment]))[0]

    async def change_regulation(self, enrollment_id: uuid.UUID, body: RegulationChange) -> EnrollmentResponse:
        enrolment = await self.enrollments.get_visible(enrollment_id, for_update=True)
        binding = (
            await self.db.execute(select(ProgramRegulation).where(ProgramRegulation.id == body.program_regulation_id))
        ).scalar_one_or_none()
        if binding is None or binding.program_id != enrolment.program_id:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "The programme-regulation belongs to another programme",
                {"field": "program_regulation_id"},
            )
        if binding.id == enrolment.program_regulation_id:
            raise APIError(409, ErrorCode.CONFLICT, "The enrolment already follows this regulation")
        mapped = await self._map_passed_courses(enrolment, binding)
        old = snap(enrolment, ENROLLMENT_KEYS)
        enrolment.program_regulation_id = binding.id
        await self.db.flush()
        await self._audit(
            "change_regulation",
            "enrollment",
            enrolment.id,
            old,
            {**snap(enrolment, ENROLLMENT_KEYS), "reason": body.reason, "mapped_courses": mapped},
        )
        await self._emit(
            "student.updated",
            {"student_id": str(enrolment.student_id), "fields": ["program_regulation_id"], "mapped_courses": mapped},
            "student",
            enrolment.student_id,
        )
        return (await self.enrollment_responses([enrolment]))[0]

    async def _map_passed_courses(self, enrolment: StudentProgramEnrollment, binding: ProgramRegulation) -> int:
        """Passed results under the old regulation → ``internal_prior`` credit transfers onto the equivalent course
        (same code) of the new regulation (``student_course_results`` fill from Phase 15; 0 before that)."""
        rows = (
            await self.db.execute(
                text(
                    "SELECT c.code, c.title, r.credits, r.letter_grade, r.term_id, nc.id AS new_id "
                    "FROM student_course_results r JOIN courses c ON c.id = r.course_id "
                    "JOIN courses nc ON nc.code = c.code AND nc.regulation_id = :reg AND nc.deleted_at IS NULL "
                    "WHERE r.student_program_enrollment_id = :e AND r.is_current AND r.result_status = 'pass'"
                ),
                {"e": enrolment.id, "reg": binding.regulation_id},
            )
        ).all()
        for r in rows:
            self.db.add(
                CreditTransfer(
                    institution_id=self.inst,
                    student_program_enrollment_id=enrolment.id,
                    term_id=r.term_id,
                    source="internal_prior",
                    source_course_code=r.code,
                    source_title=r.title,
                    credits=r.credits,
                    source_grade=r.letter_grade,
                    equivalent_course_id=r.new_id,
                    status="approved",
                    approved_by=self.actor_id,
                )
            )
        await self.db.flush()
        return len(rows)

    # ---- rule 5: standing -------------------------------------------------------------------------------------------
    async def standing(self, student_id: uuid.UUID) -> StandingResponse:
        student = await self.students.get_visible(student_id)
        enrolment = await self.enrollments.current(student.id)
        if enrolment is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "The student has no enrolment")
        rules = await RulesResolver(self.db).for_program_regulation(enrolment.program_regulation_id)
        rows = (
            await self.db.execute(
                text(
                    "SELECT occurred_at, old_values, new_values, user_id FROM audit_logs WHERE record_type = 'enrollment' "
                    "AND record_id = :e AND action = 'standing' ORDER BY occurred_at DESC LIMIT 50"
                ),
                {"e": enrolment.id},
            )
        ).all()
        users = await self.students.users([r.user_id for r in rows])
        history = []
        for r in rows:
            new = r.new_values or {}
            actor = users.get(r.user_id) if r.user_id else None
            history.append(
                StandingHistoryItem(
                    at=r.occurred_at,
                    from_standing=(r.old_values or {}).get("academic_standing"),
                    to_standing=new.get("academic_standing", "good"),
                    cgpa=new.get("cgpa"),
                    sgpa=new.get("sgpa"),
                    term_number=new.get("term_number"),
                    rule=new.get("rule"),
                    by=(actor.display_name or actor.username) if actor else "system",
                )
            )
        return StandingResponse(
            enrollment_id=enrolment.id,
            standing=enrolment.academic_standing,
            cgpa=enrolment.cgpa,
            rules=list(rules.get("standing_rules", [])),
            history=history,
        )

    async def recompute_standing(self, enrolment: StudentProgramEnrollment) -> str:
        rules = await RulesResolver(self.db).for_program_regulation(enrolment.program_regulation_id)
        records = [r for r in await self.terms.for_enrollment(enrolment.id) if r.sgpa is not None or r.cgpa is not None]
        records.sort(key=lambda r: r.term_number)
        backlogs = (await self.enrollments.backlog_counts([enrolment.id])).get(enrolment.id, 0)
        latest = records[-1] if records else None
        result, matched = "good", None
        for rule in rules.get("standing_rules", []):
            when = rule.get("when") or {}
            ok = True
            if "sgpa_below" in when:
                ok = (
                    ok
                    and latest is not None
                    and latest.sgpa is not None
                    and float(latest.sgpa) < float(when["sgpa_below"])
                )
            if "cgpa_below" in when:
                n = max(1, int(when.get("consecutive_terms", 1)))
                tail = [r for r in records if r.cgpa is not None][-n:]
                ok = ok and len(tail) == n and all(float(r.cgpa) < float(when["cgpa_below"]) for r in tail)  # type: ignore[arg-type]
            elif "consecutive_terms" in when:
                ok = ok and len(records) >= int(when["consecutive_terms"])
            if "backlogs_above" in when:
                ok = ok and backlogs > int(when["backlogs_above"])
            if ok and STANDING_SEVERITY.get(rule["status"], 0) > STANDING_SEVERITY.get(result, 0):
                result, matched = rule["status"], rule
        if latest is not None and latest.cgpa is not None:
            enrolment.cgpa = latest.cgpa
        previous = enrolment.academic_standing
        if result == previous:
            await self.db.flush()
            return result
        enrolment.academic_standing = result
        await self.db.flush()
        student = await self.students.by_id(enrolment.student_id)
        await self._audit(
            "standing",
            "enrollment",
            enrolment.id,
            {"academic_standing": previous},
            {
                "academic_standing": result,
                "cgpa": float(latest.cgpa) if latest and latest.cgpa is not None else None,
                "sgpa": float(latest.sgpa) if latest and latest.sgpa is not None else None,
                "term_number": latest.term_number if latest else None,
                "rule": matched,
                "backlogs": backlogs,
            },
        )
        await self._emit(
            "standing.changed",
            {
                "student_id": str(enrolment.student_id),
                "enrollment_id": str(enrolment.id),
                "from": previous,
                "to": result,
            },
            "enrollment",
            enrolment.id,
        )
        if student is not None:
            await self._notify(
                "standing.changed",
                [student.user_id],
                {"student_name": student.full_name, "standing": result, "cgpa": f"{float(enrolment.cgpa or 0):.2f}"},
                guardians=True,
            )
            if result == "dismissal":
                from app.services.hold_service import HoldService

                await HoldService(self.db, self.principal, self.request, self.inst).place_system(
                    enrolment,
                    "all",
                    f"Academic dismissal (CGPA {float(enrolment.cgpa or 0):.2f})",
                    "standing",
                    enrolment.id,
                )
        return result

    async def set_term_results(
        self, student_id: uuid.UUID, terms: list[Any], credits: Decimal | None
    ) -> StandingResponse:
        """Dev fixture (``POST /_dev/students/{id}/term-results``) until Phase 15 publishes results."""
        student = await self.students.get_visible(student_id)
        enrolment = await self.enrollments.current(student.id, for_update=True)
        if enrolment is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "The student has no enrolment")
        by_number = {r.term_number: r for r in await self.terms.for_enrollment(enrolment.id)}
        for t in terms:
            rec = by_number.get(t.term_number)
            if rec is None:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"No term record for term {t.term_number}", {"field": "terms"}
                )
            if t.sgpa is not None:
                rec.sgpa = t.sgpa
            if t.cgpa is not None:
                rec.cgpa = t.cgpa
            if t.credits_earned is not None:
                rec.credits_earned = t.credits_earned
        if credits is not None:
            enrolment.credits_earned = credits
        await self.db.flush()
        await self.recompute_standing(enrolment)
        return await self.standing(student.id)


# ---- Phase 03 rollover hook (promote_batches=true) ---------------------------------------------------------------------
async def on_rollover(db: Any, principal: Any, previous_year: Any, new_year: Any) -> int:
    """Promote every active batch whose students sit in the batch's current term into the new year's first term."""
    from app.repositories.academic_session_repository import AcademicTermRepository

    service = EnrollmentService(db, principal, institution_id=new_year.institution_id)
    target = await AcademicTermRepository(db, principal, new_year.institution_id).get_current_term(
        new_year.institution_id, new_year.college_id
    )
    if target is None:
        return 0
    rows = (
        await db.execute(
            select(Batch, Program.total_terms)
            .join(Program, Program.id == Batch.program_id)
            .where(
                Batch.institution_id == new_year.institution_id, Batch.status == "active", Batch.deleted_at.is_(None)
            )
        )
    ).all()
    promoted = 0
    for batch, total_terms in rows:
        if new_year.college_id is not None and batch.college_id != new_year.college_id:
            continue
        if batch.current_term_number >= int(total_terms):
            batch.status = "graduating"
            continue
        result = await service.run_promotion(
            batch.id,
            PromoteBatchRequest(to_term_number=batch.current_term_number + 1),
            dry_run=False,
            target_term=target,
        )
        promoted += len(result.promoted)
    await db.flush()
    return promoted


register_rollover_hook("students", on_rollover)
