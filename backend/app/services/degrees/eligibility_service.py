"""Degree eligibility engine — Prompts/18 §18.6 ``eligibility_service``.

Per enrolment (``active`` / ``completed``; ``exited_early`` with ``include_exits``):

* **credits** — current published ``student_course_results`` with ``result_status`` pass / audit_pass /
  credit_transfer counting toward CGPA, plus ``credit_transfers`` in ``approved|credited``; required =
  ``program_regulations.total_credits_required``;
* **buckets** — requirement per ``curriculum_courses.credit_bucket`` = Σ credits of mandatory courses + each elective
  basket's ``credits_required`` (honours / minor baskets only for honours / minor enrolments); earned = Σ credits of
  passed courses mapped to the bucket (unmapped → ``other``); short buckets → ``CREDITS_SHORT:<bucket>``;
* ``BACKLOGS`` (open ``student_arrears``), ``CGPA_BELOW_MIN`` (rules ``min_cgpa_for_degree``), ``DURATION_EXCEEDED``
  (admission + ``programs.max_duration_years``), ``MANDATORY_NONCREDIT`` (curriculum courses of type
  ``mandatory_non_credit`` without a pass), ``HOLD_GRADUATION`` (open ``graduation`` / ``all`` holds),
  ``DUES_PENDING`` (no ``no_dues_requests(purpose='graduation', status='cleared')`` — or, with setting
  ``degrees.zero_outstanding_ok``, no unpaid invoices).

Each run writes new rows (history; ``run_id`` groups them). NEP exits: ``exited_early`` enrolments are checked against
``rules.exit_points`` (highest award whose ``min_credits`` is reached) and get a ``recommended`` award of type
``certificate`` / ``diploma``. Overrides (``degrees:manage``) write a new row with the decision and a
``{"override": reason}`` entry in ``reasons``.
"""

import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.models.academic import Program, ProgramRegulation
from app.models.curriculum import Course, CurriculumCourse, ElectiveBasket
from app.models.degrees import DegreeAwarded, DegreeEligibilityCheck
from app.models.fees import FeeInvoice, NoDuesRequest
from app.models.registration import StudentArrear
from app.models.results import StudentCourseResult, StudentTermResult
from app.models.students import CreditTransfer, StudentHold, StudentProgramEnrollment, StudentTermRecord
from app.repositories.degree_scope import enrollment_predicate
from app.schemas.degrees import (
    BucketRow,
    DegreeEligibilityRunSummary,
    EligibilityCheckResponse,
    EligibilityOverride,
    EligibilityRunRequest,
)
from app.services.academics.rules import rules_effective
from app.services.degrees.common import DegreeBase, now_utc

PASS = ("pass", "audit_pass", "exempted")
ENTITY = "degree_eligibility"


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def reason_codes(reasons: Any) -> list[str]:
    return [r for r in (reasons or []) if isinstance(r, str)]


def override_of(reasons: Any) -> str | None:
    for r in reasons or []:
        if isinstance(r, dict) and r.get("override"):
            return str(r["override"])
    return None


class EligibilityService(DegreeBase):
    # ---- scope ------------------------------------------------------------------------------------------------------
    async def _scope(self, body: EligibilityRunRequest) -> list[StudentProgramEnrollment]:
        statuses = ["active", "completed"] + (["exited_early"] if body.include_exits else [])
        q = select(StudentProgramEnrollment).where(
            StudentProgramEnrollment.institution_id == self.inst,
            StudentProgramEnrollment.deleted_at.is_(None),
            StudentProgramEnrollment.status.in_(statuses),
            enrollment_predicate(self.principal, StudentProgramEnrollment.id),
        )
        if body.enrollment_ids:
            q = q.where(StudentProgramEnrollment.id.in_(body.enrollment_ids))
        elif body.batch_id:
            q = q.where(StudentProgramEnrollment.batch_id == body.batch_id)
        elif body.program_id:
            q = q.where(StudentProgramEnrollment.program_id == body.program_id)
        else:
            raise APIError(422, ErrorCode.VALIDATION, "batch_id, program_id or enrollment_ids is required")
        return list((await self.db.execute(q)).scalars().all())

    def require_manage(self) -> None:
        if not (self.can("degrees", "manage") or self.can("degrees", "award")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "degrees:manage required")

    async def submit_run(self, body: EligibilityRunRequest) -> DegreeEligibilityRunSummary:
        """Queue ``degrees.eligibility_run`` (the job calls ``run``)."""
        from app.core.jobs import enqueue

        self.require_manage()
        if not (body.batch_id or body.program_id or body.enrollment_ids):
            raise APIError(422, ErrorCode.VALIDATION, "batch_id, program_id or enrollment_ids is required")
        run_id = uuid.uuid4()
        job = await enqueue(
            self.db, self.principal, "degrees.eligibility_run", {"run_id": str(run_id), **body.model_dump(mode="json")}
        )
        return DegreeEligibilityRunSummary(run_id=run_id, job_id=job.id)

    async def run(self, body: EligibilityRunRequest, run_id: uuid.UUID | None = None) -> DegreeEligibilityRunSummary:
        run_id = run_id or uuid.uuid4()
        enrolments = await self._scope(body)
        summary = DegreeEligibilityRunSummary(run_id=run_id)
        by_reason: dict[str, int] = defaultdict(int)
        for e in enrolments:
            if e.status == "exited_early":
                if await self.exit_award(e):
                    summary.exit_awards += 1
                continue
            row = await self.check(e, run_id)
            summary.checked += 1
            if row.is_eligible:
                summary.eligible += 1
            else:
                summary.ineligible += 1
                for r in reason_codes(row.reasons):
                    by_reason[r.split(":")[0]] += 1
        summary.by_reason = dict(by_reason)
        await self._emit(
            "degrees.eligibility_computed",
            {"run_id": str(run_id), "eligible": summary.eligible, "ineligible": summary.ineligible},
            "degree_eligibility_run",
            run_id,
        )
        if body.notify:
            await self.notify_run(run_id)
        return summary

    # ---- one enrolment ------------------------------------------------------------------------------------------------
    async def check(self, e: StudentProgramEnrollment, run_id: uuid.UUID | None = None) -> DegreeEligibilityCheck:  # noqa: C901, PLR0912, PLR0915
        rules = await rules_effective(self.db, e.program_regulation_id)
        pr = (
            await self.db.execute(select(ProgramRegulation).where(ProgramRegulation.id == e.program_regulation_id))
        ).scalar_one()
        program = (await self.db.execute(select(Program).where(Program.id == e.program_id))).scalar_one()
        passed = (
            await self.db.execute(
                select(
                    StudentCourseResult.course_id, StudentCourseResult.credits, StudentCourseResult.attempt_type
                ).where(
                    StudentCourseResult.student_program_enrollment_id == e.id,
                    StudentCourseResult.is_current.is_(True),
                    StudentCourseResult.status == "published",
                    or_(
                        StudentCourseResult.result_status.in_(PASS),
                        StudentCourseResult.attempt_type == "credit_transfer",
                    ),
                )
            )
        ).all()
        passed_courses = {r[0] for r in passed}
        earned = sum(Decimal(str(r[1] or 0)) for r in passed)
        transfers = (
            await self.db.execute(
                select(func.coalesce(func.sum(CreditTransfer.credits), 0)).where(
                    CreditTransfer.student_program_enrollment_id == e.id,
                    CreditTransfer.status.in_(("approved", "credited")),
                )
            )
        ).scalar_one()
        # credit transfers already graded into results (attempt_type credit_transfer) are not counted twice
        if not any(r[2] == "credit_transfer" for r in passed):
            earned += Decimal(str(transfers or 0))
        required = Decimal(str(pr.total_credits_required or 0))

        # buckets
        curriculum = (
            await self.db.execute(
                select(CurriculumCourse, Course)
                .join(Course, Course.id == CurriculumCourse.course_id)
                .where(CurriculumCourse.program_regulation_id == e.program_regulation_id)
            )
        ).all()
        need: dict[str, float] = defaultdict(float)
        got: dict[str, float] = defaultdict(float)
        bucket_of: dict[uuid.UUID, str] = {}
        mandatory_nc: list[uuid.UUID] = []
        for cc, course in curriculum:
            bucket = cc.credit_bucket or "core"
            bucket_of[course.id] = bucket
            if cc.is_mandatory and cc.elective_basket_id is None:
                need[bucket] += float(course.credits or 0)
            if course.course_type == "mandatory_non_credit":
                mandatory_nc.append(course.id)
        baskets = (
            (
                await self.db.execute(
                    select(ElectiveBasket).where(
                        ElectiveBasket.program_regulation_id == e.program_regulation_id,
                        ElectiveBasket.is_active.is_(True),
                        ElectiveBasket.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for b in baskets:
            if b.basket_type == "honours" and not e.is_honours:
                continue
            if b.basket_type == "minor" and e.minor_program_id is None:
                continue
            if b.credits_required:
                bucket = (
                    next(
                        (
                            cc.credit_bucket
                            for cc, _ in curriculum
                            if cc.elective_basket_id == b.id and cc.credit_bucket
                        ),
                        None,
                    )
                    or b.basket_type
                )
                need[bucket] += float(b.credits_required)
        for cid, credits, _ in passed:
            got[bucket_of.get(cid, "other")] += float(credits or 0)
        breakdown = [
            {
                "bucket": k,
                "required": round(v, 1),
                "earned": round(got.get(k, 0.0), 1),
                "ok": got.get(k, 0.0) + 1e-9 >= v,
            }
            for k, v in sorted(need.items())
        ]
        if got.get("other"):
            breakdown.append({"bucket": "other", "required": 0.0, "earned": round(got["other"], 1), "ok": True})

        backlogs = (
            await self.db.execute(
                select(func.count())
                .select_from(StudentArrear)
                .where(
                    StudentArrear.student_program_enrollment_id == e.id,
                    StudentArrear.status.in_(("open", "registered")),
                )
            )
        ).scalar_one()
        cgpa = (
            await self.db.execute(
                select(StudentTermResult.cgpa)
                .join(StudentTermRecord, StudentTermRecord.id == StudentTermResult.student_term_record_id)
                .where(StudentTermRecord.student_program_enrollment_id == e.id, StudentTermResult.status == "published")
                .order_by(StudentTermRecord.term_number.desc(), StudentTermResult.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        cgpa = cgpa if cgpa is not None else e.cgpa
        min_cgpa = float(rules.get("min_cgpa_for_degree") or 0)
        min_cgpa_ok = cgpa is not None and float(cgpa) + 1e-9 >= min_cgpa
        max_years = float(
            program.max_duration_years or (float(program.duration_years) * 2 if program.duration_years else 0)
        )
        today = await self.today()
        duration_ok = True
        if max_years and e.admission_date:
            years = (today - e.admission_date).days / 365.25
            duration_ok = years <= max_years + 1e-9
        nc_ok = all(c in passed_courses for c in mandatory_nc)
        holds = (
            await self.db.execute(
                select(func.count())
                .select_from(StudentHold)
                .where(
                    StudentHold.student_program_enrollment_id == e.id,
                    StudentHold.released_at.is_(None),
                    StudentHold.hold_type.in_(("graduation", "all")),
                )
            )
        ).scalar_one()
        dues_cleared = (
            await self.db.execute(
                select(func.count())
                .select_from(NoDuesRequest)
                .where(
                    NoDuesRequest.student_program_enrollment_id == e.id,
                    NoDuesRequest.purpose == "graduation",
                    NoDuesRequest.status == "cleared",
                )
            )
        ).scalar_one() > 0
        if not dues_cleared and await self.setting("degrees", "zero_outstanding_ok"):
            unpaid = (
                await self.db.execute(
                    select(func.count())
                    .select_from(FeeInvoice)
                    .where(
                        FeeInvoice.student_program_enrollment_id == e.id,
                        FeeInvoice.balance_paise > 0,
                        FeeInvoice.status.notin_(("cancelled", "paid", "waived")),
                    )
                )
            ).scalar_one()
            dues_cleared = unpaid == 0

        reasons: list[Any] = []
        if earned + Decimal("0.0001") < required:
            reasons.append("CREDITS_SHORT:total")
        reasons += [f"CREDITS_SHORT:{b['bucket']}" for b in breakdown if not b["ok"]]
        if backlogs:
            reasons.append("BACKLOGS")
        if not min_cgpa_ok:
            reasons.append("CGPA_BELOW_MIN")
        if not duration_ok:
            reasons.append("DURATION_EXCEEDED")
        if not nc_ok:
            reasons.append("MANDATORY_NONCREDIT")
        if holds:
            reasons.append("HOLD_GRADUATION")
        if not dues_cleared:
            reasons.append("DUES_PENDING")
        row = DegreeEligibilityCheck(
            institution_id=self.inst,
            checked_at=now_utc(),  # explicit: rows of one transaction must still order (override after its base)
            student_program_enrollment_id=e.id,
            credits_earned=earned,
            credits_required=required,
            bucket_breakdown=breakdown,
            backlog_count=int(backlogs),
            cgpa=cgpa,
            min_cgpa_ok=min_cgpa_ok,
            duration_ok=duration_ok,
            dues_cleared=dues_cleared,
            holds_clear=holds == 0,
            mandatory_noncredit_ok=nc_ok,
            is_eligible=not reasons,
            reasons=reasons,
            run_id=run_id,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def exit_award(self, e: StudentProgramEnrollment) -> bool:
        """NEP exit: highest ``exit_points`` award whose ``min_credits`` the enrolment reached → recommended award."""
        rules = await rules_effective(self.db, e.program_regulation_id)
        points = sorted(rules.get("exit_points") or [], key=lambda x: float(x.get("min_credits") or 0))
        credits = float(e.credits_earned or 0)
        hit = None
        for p in points:
            if credits + 1e-9 >= float(p.get("min_credits") or 0) and str(p.get("award")) in ("certificate", "diploma"):
                hit = p
        if hit is None:
            return False
        award_type = str(hit["award"])
        existing = (
            await self.db.execute(
                select(DegreeAwarded.id).where(
                    DegreeAwarded.student_program_enrollment_id == e.id,
                    DegreeAwarded.award_type == award_type,
                    DegreeAwarded.status.notin_(("cancelled", "reissued")),
                )
            )
        ).first()
        if existing:
            return False
        program = (await self.db.execute(select(Program).where(Program.id == e.program_id))).scalar_one()
        a = DegreeAwarded(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            award_type=award_type,
            degree_name=f"{award_type.title()} in {program.name}"[:120],
            specialization=e.specialization,
            cgpa=e.cgpa,
            date_of_award=e.exit_date or await self.today(),
            status="recommended",
        )
        self.db.add(a)
        await self.db.flush()
        await self._audit("exit_award", "degree_award", a.id, None, {"award_type": award_type, "credits": credits})
        await self._emit("degrees.recommended", {"award_id": str(a.id), "award_type": award_type}, "degree_award", a.id)
        return True

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def latest(self, enrollment_id: uuid.UUID) -> DegreeEligibilityCheck | None:
        return (
            await self.db.execute(
                select(DegreeEligibilityCheck)
                .where(DegreeEligibilityCheck.student_program_enrollment_id == enrollment_id)
                .order_by(DegreeEligibilityCheck.checked_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def outs(self, rows: list[DegreeEligibilityCheck]) -> list[EligibilityCheckResponse]:
        refs = await self.refs([r.student_program_enrollment_id for r in rows])
        return [
            EligibilityCheckResponse(
                id=r.id,
                enrollment=refs.get(r.student_program_enrollment_id) or {"id": r.student_program_enrollment_id},  # type: ignore[arg-type]
                checked_at=r.checked_at,
                credits_earned=_f(r.credits_earned),
                credits_required=_f(r.credits_required),
                bucket_breakdown=[BucketRow(**b) for b in (r.bucket_breakdown or [])],
                backlog_count=r.backlog_count,
                cgpa=_f(r.cgpa),
                min_cgpa_ok=r.min_cgpa_ok,
                duration_ok=r.duration_ok,
                dues_cleared=r.dues_cleared,
                holds_clear=r.holds_clear,
                mandatory_noncredit_ok=r.mandatory_noncredit_ok,
                is_eligible=r.is_eligible,
                reasons=reason_codes(r.reasons),
                overridden=override_of(r.reasons) is not None,
                override_reason=override_of(r.reasons),
                run_id=r.run_id,
            )
            for r in rows
        ]

    async def list_checks(
        self,
        batch_id: uuid.UUID | None,
        program_id: uuid.UUID | None,
        eligible: bool | None,
        run_id: uuid.UUID | None = None,
    ) -> list[EligibilityCheckResponse]:
        latest = (
            select(
                DegreeEligibilityCheck.id,
                func.row_number()
                .over(
                    partition_by=DegreeEligibilityCheck.student_program_enrollment_id,
                    order_by=DegreeEligibilityCheck.checked_at.desc(),
                )
                .label("rn"),
            )
            .where(DegreeEligibilityCheck.institution_id == self.inst)
            .subquery()
        )
        q = select(DegreeEligibilityCheck).join(
            StudentProgramEnrollment,
            StudentProgramEnrollment.id == DegreeEligibilityCheck.student_program_enrollment_id,
        )
        if run_id is None:
            q = q.join(latest, latest.c.id == DegreeEligibilityCheck.id).where(latest.c.rn == 1)
        else:
            q = q.where(DegreeEligibilityCheck.run_id == run_id)
        q = q.where(enrollment_predicate(self.principal, DegreeEligibilityCheck.student_program_enrollment_id))
        if batch_id:
            q = q.where(StudentProgramEnrollment.batch_id == batch_id)
        if program_id:
            q = q.where(StudentProgramEnrollment.program_id == program_id)
        if eligible is not None:
            q = q.where(DegreeEligibilityCheck.is_eligible.is_(eligible))
        rows = list((await self.db.execute(q.limit(5000))).scalars().all())
        out = await self.outs(rows)
        return sorted(out, key=lambda x: x.enrollment.registration_number or "")

    async def get(self, check_id: uuid.UUID) -> EligibilityCheckResponse:
        row = (
            await self.db.execute(
                select(DegreeEligibilityCheck).where(
                    DegreeEligibilityCheck.id == check_id,
                    DegreeEligibilityCheck.institution_id == self.inst,
                    enrollment_predicate(self.principal, DegreeEligibilityCheck.student_program_enrollment_id),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Eligibility check not found")
        return (await self.outs([row]))[0]

    async def me(self) -> list[EligibilityCheckResponse]:
        out = []
        for eid in await self.mine():
            row = await self.latest(eid)
            if row is not None:
                out += await self.outs([row])
        return out

    async def override(self, check_id: uuid.UUID, body: EligibilityOverride) -> EligibilityCheckResponse:
        if not self.can("degrees", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the registrar may override eligibility")
        base = (
            await self.db.execute(
                select(DegreeEligibilityCheck).where(
                    DegreeEligibilityCheck.id == check_id,
                    DegreeEligibilityCheck.institution_id == self.inst,
                    enrollment_predicate(self.principal, DegreeEligibilityCheck.student_program_enrollment_id),
                )
            )
        ).scalar_one_or_none()
        if base is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Eligibility check not found")
        row = DegreeEligibilityCheck(
            institution_id=self.inst,
            checked_at=now_utc(),  # explicit: rows of one transaction must still order (override after its base)
            student_program_enrollment_id=base.student_program_enrollment_id,
            credits_earned=base.credits_earned,
            credits_required=base.credits_required,
            bucket_breakdown=base.bucket_breakdown,
            backlog_count=base.backlog_count,
            cgpa=base.cgpa,
            min_cgpa_ok=base.min_cgpa_ok,
            duration_ok=base.duration_ok,
            dues_cleared=base.dues_cleared,
            holds_clear=base.holds_clear,
            mandatory_noncredit_ok=base.mandatory_noncredit_ok,
            is_eligible=body.decision == "eligible",
            reasons=[
                *reason_codes(base.reasons),
                {"override": body.reason, "decision": body.decision, "base": str(base.id)},
            ],
            run_id=base.run_id,
        )
        self.db.add(row)
        await self.db.flush()
        await self._audit(
            "eligibility_override",
            ENTITY,
            row.id,
            {"is_eligible": base.is_eligible, "reasons": reason_codes(base.reasons)},
            {"is_eligible": row.is_eligible, "reason": body.reason},
        )
        await self._emit(
            "degrees.eligibility_overridden",
            {
                "check_id": str(row.id),
                "enrollment_id": str(row.student_program_enrollment_id),
                "decision": body.decision,
            },
            ENTITY,
            row.id,
        )
        return (await self.outs([row]))[0]

    async def recheck_enrolment(self, enrollment_id: uuid.UUID) -> DegreeEligibilityCheck | None:
        """Re-evaluate one enrolment that already has a check (no-dues cleared / hold released)."""
        if await self.latest(enrollment_id) is None:
            return None
        e = (
            await self.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == enrollment_id))
        ).scalar_one_or_none()
        if e is None or e.status not in ("active", "completed"):
            return None
        return await self.check(e)

    async def notify_run(self, run_id: uuid.UUID) -> int:
        from app.models.students import Student

        rows = (
            await self.db.execute(
                select(DegreeEligibilityCheck, Student.user_id)
                .join(
                    StudentProgramEnrollment,
                    StudentProgramEnrollment.id == DegreeEligibilityCheck.student_program_enrollment_id,
                )
                .join(Student, Student.id == StudentProgramEnrollment.student_id)
                .where(DegreeEligibilityCheck.run_id == run_id)
            )
        ).all()
        for r, uid in rows:
            await self._notify(
                "degrees.eligible",
                [uid],
                {
                    "status": "eligible" if r.is_eligible else "not yet eligible",
                    "reasons": ", ".join(reason_codes(r.reasons)) or "—",
                },
            )
        return len(rows)

    async def final_term_batches_of_run(self, result_run_id: uuid.UUID) -> list[uuid.UUID]:
        """Enrolments of a published result run whose term is the programme's last term."""
        rows = (
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id)
                    .join(
                        StudentCourseResult,
                        StudentCourseResult.student_program_enrollment_id == StudentProgramEnrollment.id,
                    )
                    .join(Program, Program.id == StudentProgramEnrollment.program_id)
                    .join(
                        StudentTermRecord,
                        (StudentTermRecord.student_program_enrollment_id == StudentProgramEnrollment.id)
                        & (StudentTermRecord.term_id == StudentCourseResult.term_id),
                    )
                    .where(
                        StudentCourseResult.run_id == result_run_id,
                        StudentTermRecord.term_number >= Program.total_terms,
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
