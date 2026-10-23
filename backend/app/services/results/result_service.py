# mypy: disable-error-code="arg-type,var-annotated"
"""Result processing runs — Prompts/15 §15.6 ``result_service`` rules 1–5.

1. ``create_run`` (``results:compute``): snapshot of the merged rules per programme-regulation in scope
   (``RulesResolver``), the grading scale(s) (regulation → session → institution default → built-in), the assessment
   maxima and the feature switches; ``queued`` → job ``results.compute_run``.
2. ``compute`` (job): one row per registered item (cancelled items skipped) — CIA from ``cia_consolidations.cia_scaled``
   (arrears carry the previous attempt's CIA; missing → ``MISSING_CIA``), ESE = ``script_final_marks.final_marks``
   (status ``final``) scaled to ``ese_max``; absent → ``absent`` (marks present too → ``ABSENT_WITH_MARKS``), detained
   eligibility → ``detained``, open malpractice case → ``withheld`` (``MALPRACTICE_PENDING``), active ``exam|all`` hold
   → ``withheld`` (``WITHHELD_HOLD``), no final marks → ``incomplete`` (``ESE_MISSING``); grace within
   ``rules.grace`` (``exams.grace``; ``GRACE_APPLIED``); pass = ESE % ≥ ``ese_pass_min_pct`` and total % ≥
   ``total_pass_min_pct`` (and CIA % ≥ ``cia_pass_min_pct`` when set); grade absolute (``GRADE_BOUNDARY`` within 0.5)
   or relative (``exams.relative_grading`` + scale ``relative``: z-bands per course cohort ≥ ``min_class_size``,
   otherwise absolute — recorded in ``config_snapshot.relative_fallback``); audit / non-gradable courses →
   ``audit_pass|audit_fail`` (not in CGPA); approved credit transfers of the term → ``credit_transfer`` rows (grade from
   ``mooc_grade_map``); withdrawn registration items → ``withdrawn`` (``W``). ``version`` = current version + 1 for the
   same (enrolment, course, attempt) with ``supersedes_id``. Term results: SGPA / CGPA (``compute.sgpa`` /
   ``compute.cgpa``), cumulative credits, backlogs, class. ``checksum`` = sha256 of the ordered row hashes.
   Computing a run retires the session's other unpublished runs (``rolled_back``, ``error_log.superseded_by``) — the
   ``UNIQUE (enrolment, course, attempt, version)`` key allows one open version per row.
3. ``verify`` (exam cell; anomalies must be acknowledged), ``approve`` (COE / VC; optional governance resolution),
   ``rollback`` until publish (the run's rows are deleted — previous versions untouched).
4. ``publish`` (``results:publish|manage``): one transaction — rows / term results published, previous current
   versions superseded (other attempts keep ``published`` with ``is_current=false``), term records and enrolments
   updated, arrears ledger, standing (Phase 07), ``abc_credit_ledger(pending)`` (``academics.abc_apaar``),
   ``result_publications``, session ``results_published``, notifications (masked SMS: SGPA only), grade-card job.
5. Re-runs after publish (``revaluation`` / ``correction`` / ``supplementary_merge``) create new versions only for the
   affected rows (``scope.enrollment_ids`` / ``course_ids``; correction ``marks_delta``).
"""

import contextlib
import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, or_, select

from app.core.errors import APIError, ErrorCode
from app.enums.results import PASSING, SPECIAL_GRADE
from app.models.academic import AcademicTerm, GradingScale, ProgramRegulation, Regulation
from app.models.assessment import CiaConsolidation
from app.models.curriculum import AssessmentScheme, Course
from app.models.exams import (
    ExamAttendance,
    ExamPaper,
    ExamRegistration,
    ExamRegistrationItem,
    ExamSession,
    MalpracticeCase,
)
from app.models.registration import CourseRegistration, CourseRegistrationItem, StudentArrear
from app.models.results import (
    AbcCreditLedger,
    ResultProcessingRun,
    ResultPublication,
    StudentCourseResult,
    StudentTermResult,
)
from app.models.students import CreditTransfer, Student, StudentHold, StudentProgramEnrollment, StudentTermRecord
from app.models.valuation import AnswerScript, ScriptFinalMarks
from app.repositories.result_scope import college_ids, institution_scope
from app.schemas.results import (
    AnomalyRow,
    CourseResultResponse,
    PublishRequest,
    RunAction,
    RunCreateRequest,
    RunResponse,
)
from app.services.exams.common import ExamBase, now_utc, rule
from app.services.results import compute as C

ROW_HASH_FIELDS = (
    "student_program_enrollment_id",
    "course_id",
    "term_id",
    "attempt_number",
    "attempt_type",
    "credits",
    "cia_marks",
    "ese_marks",
    "grace_marks",
    "total_marks",
    "percentage",
    "letter_grade",
    "grade_point",
    "result_status",
    "counts_toward_cgpa",
    "version",
)


def hash_of(r: StudentCourseResult) -> str:
    return C.row_hash({k: getattr(r, k) for k in ROW_HASH_FIELDS})


class ResultBase(ExamBase):
    audit_module = "results"

    async def run(self, rid: uuid.UUID, *, for_update: bool = False) -> ResultProcessingRun:
        q = select(ResultProcessingRun).where(
            ResultProcessingRun.id == rid, ResultProcessingRun.institution_id == self.inst
        )
        if for_update:
            q = q.with_for_update()
        r = (await self.db.execute(q)).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Result run not found")
        mine = college_ids(self.principal) if self.principal is not None else []
        scoped = (r.scope or {}).get("college_ids") or []
        if mine and not institution_scope(self.principal) and scoped and not set(map(str, mine)) & set(scoped):
            raise APIError(404, ErrorCode.NOT_FOUND, "Result run not found")
        return r

    async def run_out(self, r: ResultProcessingRun) -> RunResponse:
        name = None
        if r.exam_session_id:
            name = (
                await self.db.execute(select(ExamSession.name).where(ExamSession.id == r.exam_session_id))
            ).scalar_one_or_none()
        out = RunResponse.model_validate(r, from_attributes=True)
        out.session_name = name
        out.anomalies_count = len(((r.error_log or {}) if isinstance(r.error_log, dict) else {}).get("anomalies", []))
        return out

    async def rows_out(self, rows: list[StudentCourseResult]) -> list[CourseResultResponse]:
        if not rows:
            return []
        courses = {
            c.id: c
            for c in (await self.db.execute(select(Course).where(Course.id.in_({r.course_id for r in rows})))).scalars()
        }
        studs = dict(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_({r.student_program_enrollment_id for r in rows}))
                )
            ).all()
        )
        out = []
        for r in rows:
            o = CourseResultResponse.model_validate(r, from_attributes=True)
            c = courses.get(r.course_id)
            s = studs.get(r.student_program_enrollment_id)
            o.course_code, o.course_title = (c.code, c.title) if c else (None, None)
            if s is not None:
                o.student_name = " ".join(x for x in (s.first_name, s.last_name) if x)
                o.registration_number = s.registration_number
            o.revised = r.version > 1
            out.append(o)
        return out


class ResultRunService(ResultBase):
    # ---- 1. create ---------------------------------------------------------------------------------------------------
    async def _scale_for(self, regulation_id: uuid.UUID | None, s: ExamSession) -> GradingScale | None:
        sid = None
        if regulation_id:
            sid = (
                await self.db.execute(select(Regulation.grading_scale_id).where(Regulation.id == regulation_id))
            ).scalar_one_or_none()
        sid = sid or s.grading_scale_id
        if sid:
            g = (await self.db.execute(select(GradingScale).where(GradingScale.id == sid))).scalar_one_or_none()
            if g is not None:
                return g
        return (
            (
                await self.db.execute(
                    select(GradingScale).where(
                        GradingScale.institution_id == self.inst,
                        GradingScale.is_default.is_(True),
                        GradingScale.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .first()
        )

    def _registrations(self, s: ExamSession, scope: dict[str, Any]) -> Any:
        q = (
            select(ExamRegistration, StudentProgramEnrollment)
            .join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == ExamRegistration.student_program_enrollment_id
            )
            .where(ExamRegistration.exam_session_id == s.id, ExamRegistration.status.in_(("confirmed", "submitted")))
        )
        if scope.get("college_ids"):
            q = q.where(ExamRegistration.college_id.in_(scope["college_ids"]))
        if scope.get("program_ids"):
            q = q.where(StudentProgramEnrollment.program_id.in_(scope["program_ids"]))
        if scope.get("batch_ids"):
            q = q.where(StudentProgramEnrollment.batch_id.in_(scope["batch_ids"]))
        if scope.get("enrollment_ids"):
            q = q.where(StudentProgramEnrollment.id.in_(scope["enrollment_ids"]))
        return q

    async def create_run(self, body: RunCreateRequest) -> ResultProcessingRun:
        from app.core.features import is_enabled
        from app.services.academics.rules import RulesResolver

        s = await self.session(body.exam_session_id)
        if s.status in ("draft", "registration_open", "registration_closed", "scheduled"):
            raise rule("Results are processed after the examinations", "SESSION_NOT_READY", session_status=s.status)
        scope = body.scope.model_dump(mode="json")
        mine = college_ids(self.principal) if self.principal is not None else []
        if mine and not institution_scope(self.principal):
            wanted = (
                [c for c in scope["college_ids"] if uuid.UUID(c) in mine]
                if scope["college_ids"]
                else [str(c) for c in mine]
            )
            if not wanted:
                raise APIError(403, ErrorCode.PERMISSION_DENIED, "The scope is outside your colleges")
            scope["college_ids"] = wanted
        if body.run_type in ("correction", "revaluation") and not scope["enrollment_ids"]:
            raise APIError(422, ErrorCode.VALIDATION, "Correction / revaluation runs name the affected enrolments")
        busy = (
            await self.db.execute(
                select(func.count())
                .select_from(ResultProcessingRun)
                .where(
                    ResultProcessingRun.exam_session_id == s.id,
                    ResultProcessingRun.status.in_(("queued", "computing", "computed", "verified", "approved")),
                )
            )
        ).scalar_one()
        if busy and body.run_type in ("provisional", "final"):
            pass  # parallel provisional runs are allowed; only publication is exclusive
        prs = list(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.program_regulation_id)
                    .where(
                        StudentProgramEnrollment.id.in_(
                            self._registrations(s, scope).with_only_columns(StudentProgramEnrollment.id)
                        )
                    )
                    .distinct()
                )
            ).scalars()
        )
        rules: dict[str, Any] = {}
        scales: dict[str, Any] = {}
        pr_scale: dict[str, str | None] = {}
        resolver = RulesResolver(self.db)
        for pr in prs:
            rules[str(pr)] = await resolver.for_program_regulation(pr)
            reg = (
                await self.db.execute(select(ProgramRegulation.regulation_id).where(ProgramRegulation.id == pr))
            ).scalar_one()
            g = await self._scale_for(reg, s)
            pr_scale[str(pr)] = str(g.id) if g else None
            if g is not None and str(g.id) not in scales:
                scales[str(g.id)] = {
                    "name": g.name,
                    "scale_type": g.scale_type,
                    "ranges": g.ranges,
                    "relative_config": g.relative_config,
                    "max_grade_point": float(g.max_grade_point),
                }
        snapshot = {
            "rules": rules,
            "scales": scales,
            "program_regulation_scale": pr_scale,
            "session": {
                "id": str(s.id),
                "term_id": str(s.term_id),
                "valuation_mode": s.valuation_mode,
                "kind": s.exam_kind,
            },
            "features": {
                "grace": await is_enabled(self.inst, "exams.grace"),
                "relative_grading": await is_enabled(self.inst, "exams.relative_grading"),
                "abc_apaar": await is_enabled(self.inst, "academics.abc_apaar"),
            },
            "taken_at": now_utc().isoformat(),
        }
        r = ResultProcessingRun(
            institution_id=self.inst,
            exam_session_id=s.id,
            scope=scope,
            run_type=body.run_type,
            status="queued",
            triggered_by=self.actor_id,
            config_snapshot=snapshot,
        )
        self.db.add(r)
        if s.status == "valuation" or s.status == "in_progress":
            s.status = "result_processing"
        await self.db.flush()
        await self._audit("run_create", "result_run", r.id, None, {"type": r.run_type, "scope": scope})
        await self._emit("results.run_created", {"run_id": str(r.id), "session_id": str(s.id)}, "result_run", r.id)
        return r

    # ---- 2. compute --------------------------------------------------------------------------------------------------
    async def compute(self, rid: uuid.UUID, progress: Any = None) -> RunResponse:
        r = await self.run(rid, for_update=True)
        if r.status not in ("queued", "computed", "failed"):
            raise rule(f"A {r.status} run cannot be recomputed", "INVALID_TRANSITION")
        r.status = "computing"
        await self.db.flush()
        try:
            await self._compute(r, progress)
        except APIError:
            raise
        except Exception as exc:  # noqa: BLE001 — recorded on the run, re-raised for the job log
            r.status, r.error_log = "failed", {"error": str(exc)[:2000]}
            await self.db.flush()
            raise
        return await self.run_out(r)

    async def _compute(self, r: ResultProcessingRun, progress: Any) -> None:
        s = (await self.db.execute(select(ExamSession).where(ExamSession.id == r.exam_session_id))).scalar_one()
        snap = r.config_snapshot or {}
        scope = r.scope or {}
        feats = snap.get("features") or {}
        await self.db.execute(delete(StudentTermResult).where(StudentTermResult.run_id == r.id))
        await self.db.execute(delete(StudentCourseResult).where(StudentCourseResult.run_id == r.id))
        # one open run per session: a newer computation retires the unpublished runs before it (rows share versions)
        for other in (
            await self.db.execute(
                select(ResultProcessingRun)
                .where(
                    ResultProcessingRun.exam_session_id == s.id,
                    ResultProcessingRun.id != r.id,
                    ResultProcessingRun.status.in_(("computed", "verified", "approved", "failed")),
                )
                .with_for_update()
            )
        ).scalars():
            await self.db.execute(delete(StudentTermResult).where(StudentTermResult.run_id == other.id))
            await self.db.execute(delete(StudentCourseResult).where(StudentCourseResult.run_id == other.id))
            other.status = "rolled_back"
            other.error_log = {**(other.error_log or {}), "superseded_by": str(r.id)}
        regs = (await self.db.execute(self._registrations(s, scope))).all()
        enr_by_id = {e.id: e for _, e in regs}
        reg_ids = [g.id for g, _ in regs]
        items = (
            (
                await self.db.execute(
                    select(ExamRegistrationItem).where(
                        ExamRegistrationItem.exam_registration_id.in_(reg_ids),
                        ExamRegistrationItem.status != "cancelled",
                    )
                )
            )
            .scalars()
            .all()
            if reg_ids
            else []
        )
        if scope.get("course_ids"):
            wanted = {uuid.UUID(c) for c in scope["course_ids"]}
            items = [i for i in items if i.course_id in wanted]
        reg_enr = {g.id: g.student_program_enrollment_id for g, _ in regs}
        item_ids = [i.id for i in items]
        courses = {
            c.id: c
            for c in (
                await self.db.execute(
                    select(Course).where(Course.id.in_({i.course_id for i in items} or {uuid.uuid4()}))
                )
            ).scalars()
        }
        schemes = {
            sc.id: sc
            for sc in (
                await self.db.execute(
                    select(AssessmentScheme).where(
                        AssessmentScheme.id.in_(
                            {c.assessment_scheme_id for c in courses.values() if c.assessment_scheme_id}
                            or {uuid.uuid4()}
                        )
                    )
                )
            ).scalars()
        }
        papers = {
            p.id: p
            for p in (await self.db.execute(select(ExamPaper).where(ExamPaper.exam_session_id == s.id))).scalars()
        }
        att = (
            dict(
                (
                    await self.db.execute(
                        select(ExamAttendance.exam_registration_item_id, ExamAttendance.status).where(
                            ExamAttendance.exam_registration_item_id.in_(item_ids)
                        )
                    )
                ).all()
            )
            if item_ids
            else {}
        )
        finals = (
            dict(
                (
                    await self.db.execute(
                        select(AnswerScript.exam_registration_item_id, ScriptFinalMarks.final_marks)
                        .join(ScriptFinalMarks, ScriptFinalMarks.answer_script_id == AnswerScript.id)
                        .where(AnswerScript.exam_registration_item_id.in_(item_ids), ScriptFinalMarks.status == "final")
                    )
                ).all()
            )
            if item_ids
            else {}
        )
        mal = (
            set(
                (
                    await self.db.execute(
                        select(MalpracticeCase.exam_registration_item_id).where(
                            MalpracticeCase.exam_registration_item_id.in_(item_ids),
                            MalpracticeCase.status.in_(("reported", "under_inquiry", "hearing_scheduled", "appealed")),
                        )
                    )
                ).scalars()
            )
            if item_ids
            else set()
        )
        mal_decided = (
            set(
                (
                    await self.db.execute(
                        select(MalpracticeCase.exam_registration_item_id).where(
                            MalpracticeCase.exam_registration_item_id.in_(item_ids),
                            MalpracticeCase.status.in_(("decided", "appeal_decided", "closed")),
                            MalpracticeCase.punishment.in_(("cancel_paper", "cancel_session", "debar_terms", "expel")),
                        )
                    )
                ).scalars()
            )
            if item_ids
            else set()
        )
        # cancel_session: every item of a registration with such a decided case is cancelled (Phase 16)
        if item_ids:
            cancelled_regs = set(
                (
                    await self.db.execute(
                        select(ExamRegistrationItem.exam_registration_id)
                        .join(MalpracticeCase, MalpracticeCase.exam_registration_item_id == ExamRegistrationItem.id)
                        .where(
                            ExamRegistrationItem.id.in_(item_ids),
                            MalpracticeCase.status.in_(("decided", "appeal_decided", "closed")),
                            MalpracticeCase.punishment == "cancel_session",
                        )
                    )
                ).scalars()
            )
            mal_decided |= {i.id for i in items if i.exam_registration_id in cancelled_regs}
        enr_ids = list(enr_by_id)
        holds = (
            set(
                (
                    await self.db.execute(
                        select(StudentHold.student_program_enrollment_id).where(
                            StudentHold.student_program_enrollment_id.in_(enr_ids),
                            StudentHold.released_at.is_(None),
                            StudentHold.hold_type.in_(("exam", "all")),
                        )
                    )
                ).scalars()
            )
            if enr_ids
            else set()
        )
        # offerings of the term (CIA) — confirmed course-registration items
        offer: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = {}
        withdrawn: list[tuple[uuid.UUID, CourseRegistrationItem]] = []
        if enr_ids:
            for enr, cri in (
                await self.db.execute(
                    select(CourseRegistration.student_program_enrollment_id, CourseRegistrationItem)
                    .join(CourseRegistrationItem, CourseRegistrationItem.registration_id == CourseRegistration.id)
                    .where(
                        CourseRegistration.student_program_enrollment_id.in_(enr_ids),
                        CourseRegistration.term_id == s.term_id,
                    )
                )
            ).all():
                if cri.status == "withdrawn":
                    withdrawn.append((enr, cri))
                elif cri.status in ("confirmed", "approved", "selected"):
                    offer[(enr, cri.course_id)] = cri.offering_id
        cia = {
            (c.student_program_enrollment_id, c.offering_id): c.cia_scaled
            for c in (
                await self.db.execute(
                    select(CiaConsolidation).where(
                        CiaConsolidation.student_program_enrollment_id.in_(enr_ids or [uuid.uuid4()]),
                        CiaConsolidation.offering_id.in_(set(offer.values()) or {uuid.uuid4()}),
                    )
                )
            ).scalars()
        }
        # current rows (previous attempts / versions)
        current: dict[tuple[uuid.UUID, uuid.UUID], list[StudentCourseResult]] = defaultdict(list)
        for row in (
            await self.db.execute(
                select(StudentCourseResult).where(
                    StudentCourseResult.student_program_enrollment_id.in_(enr_ids or [uuid.uuid4()]),
                    StudentCourseResult.status == "published",
                )
            )
        ).scalars():
            current[(row.student_program_enrollment_id, row.course_id)].append(row)

        anomalies: list[dict[str, Any]] = []
        new_rows: list[StudentCourseResult] = []
        relative_fallback: dict[str, str] = {}
        deltas = {k: Decimal(str(v)) for k, v in (scope.get("marks_delta") or {}).items()}
        grace_used: dict[uuid.UUID, tuple[int, Decimal]] = defaultdict(lambda: (0, Decimal(0)))

        def anomaly(enr: uuid.UUID, course: uuid.UUID | None, code: str, detail: str) -> None:
            anomalies.append(
                {
                    "enrollment_id": str(enr),
                    "course_id": str(course) if course else None,
                    "code": code,
                    "detail": detail,
                }
            )

        total_items = len(items) or 1
        for n, it in enumerate(items, start=1):
            enr_id = reg_enr[it.exam_registration_id]
            enr = enr_by_id[enr_id]
            c = courses.get(it.course_id)
            if c is None:
                continue
            rules = (snap.get("rules") or {}).get(str(enr.program_regulation_id)) or {}
            scale_id = (snap.get("program_regulation_scale") or {}).get(str(enr.program_regulation_id))
            scale = (snap.get("scales") or {}).get(scale_id or "", {})
            ranges = scale.get("ranges") or C.DEFAULT_RANGES
            sch = schemes.get(c.assessment_scheme_id) if c.assessment_scheme_id else None
            cia_max = Decimal(c.cia_max if c.cia_max is not None else (sch.cia_max if sch else 40))
            ese_max = Decimal(c.ese_max if c.ese_max is not None else (sch.ese_max if sch else 60))
            prev = sorted(current.get((enr_id, c.id), []), key=lambda x: (x.attempt_number, x.version))
            same = [p for p in prev if p.attempt_number == it.attempt_number]
            version = (max(p.version for p in same) + 1) if same else 1
            supersedes = max(same, key=lambda p: p.version).id if same else None
            offering_id = offer.get((enr_id, c.id))
            # CIA
            cia_marks: Decimal | None = None
            if offering_id and (enr_id, offering_id) in cia:
                cia_marks = C.d2(cia[(enr_id, offering_id)])
            elif prev and prev[-1].cia_marks is not None:
                cia_marks = prev[-1].cia_marks  # arrear / re-run: CIA carries over
            elif cia_max > 0:
                anomaly(enr_id, c.id, "MISSING_CIA", f"No CIA consolidation for {c.code}")
            # ESE
            paper = papers.get(it.exam_paper_id)
            pmax = paper.max_marks if paper else ese_max
            raw = finals.get(it.id)
            ese: Decimal | None = C.d2(Decimal(raw) / pmax * ese_max) if raw is not None and pmax else None
            if r.run_type == "correction" and same:
                base = max(same, key=lambda p: p.version)
                ese = base.ese_marks if ese is None else ese
                ese = C.d2(
                    min(max((ese or Decimal(0)) + deltas.get(f"{enr_id}:{c.id}", Decimal(0)), Decimal(0)), ese_max)
                )
                cia_marks = base.cia_marks if cia_marks is None else cia_marks
            status_att = att.get(it.id)
            result_status: str | None = None
            if it.eligibility == "detained":
                result_status = "detained"
            elif it.id in mal_decided:
                result_status = "malpractice"
            elif it.id in mal:
                result_status = "withheld"
                anomaly(enr_id, c.id, "MALPRACTICE_PENDING", "Open malpractice case")
            elif enr_id in holds and not scope.get("ignore_holds"):
                result_status = "withheld"
                anomaly(enr_id, c.id, "WITHHELD_HOLD", "Active exam hold")
            elif status_att == "absent" or it.status == "absent":
                result_status = "absent"
                if raw is not None:
                    anomaly(enr_id, c.id, "ABSENT_WITH_MARKS", "Marked absent but final marks exist")
            elif ese is None and r.run_type != "correction":
                result_status = "incomplete"
                anomaly(enr_id, c.id, "ESE_MISSING", "No decoded ESE marks")
            grace = Decimal(0)
            grace_reason = None
            total = (cia_marks or Decimal(0)) + (ese or Decimal(0))
            total_max = cia_max + ese_max
            pct = C.d2(total / total_max * 100) if total_max > 0 else Decimal(0)
            audit = c.course_type == "audit" or not c.is_gradable

            letter: str | None = None
            gp: Decimal | None = None
            if result_status is None:
                ok = C.passes(ese, total, cia_marks, cia_max, ese_max, total_max, rules)
                g = rules.get("grace") or {}
                if not ok and feats.get("grace") and not audit and g:
                    used_n, used_m = grace_used[enr_id]
                    need = Decimal(0)
                    ese_need = max(
                        Decimal(str(rules.get("ese_pass_min_pct", 45))) / 100 * ese_max - (ese or Decimal(0)),
                        Decimal(0),
                    )
                    tot_need = max(
                        Decimal(str(rules.get("total_pass_min_pct", 50))) / 100 * total_max - total, Decimal(0)
                    )
                    need = C.d1(max(ese_need, tot_need) + Decimal("0.049"))
                    if (
                        need > 0
                        and need <= Decimal(str(g.get("max_per_course", 5)))
                        and used_n < int(g.get("max_courses_per_term", 2))
                        and used_m + need <= Decimal(str(g.get("max_total_per_term", 8)))
                    ):
                        e2 = (ese or Decimal(0)) + need
                        t2 = total + need
                        if C.passes(e2, t2, cia_marks, cia_max, ese_max, total_max, rules):
                            grace, grace_reason = need, "Grace per regulation"
                            ese, total, ok = C.d2(e2), t2, True
                            pct = C.d2(total / total_max * 100) if total_max > 0 else Decimal(0)
                            grace_used[enr_id] = (used_n + 1, used_m + need)
                            anomaly(enr_id, c.id, "GRACE_APPLIED", f"{need} grace mark(s)")
                if audit:
                    result_status = "audit_pass" if ok else "audit_fail"
                elif ok:
                    result_status = "pass"
                    letter, gp, boundary = C.grade_for(pct, ranges)
                    if boundary:
                        anomaly(enr_id, c.id, "GRADE_BOUNDARY", f"{pct}% is within 0.5 of the next grade")
                else:
                    result_status = "fail"
                    letter, gp = C.fail_grade(ranges)
            if result_status in SPECIAL_GRADE and letter is None:
                letter, gp = SPECIAL_GRADE[result_status], Decimal(0)
            row = StudentCourseResult(
                institution_id=self.inst,
                college_id=enr.college_id,
                student_program_enrollment_id=enr_id,
                term_id=s.term_id,
                course_id=c.id,
                offering_id=offering_id,
                exam_session_id=s.id,
                exam_registration_item_id=it.id,
                attempt_number=it.attempt_number,
                attempt_type=it.attempt_type if it.attempt_type in ("regular", "arrear", "improvement") else "regular",
                credits=c.credits if c.is_credit_bearing else Decimal(0),
                cia_marks=cia_marks,
                cia_max=cia_max,
                ese_marks=ese,
                ese_max=ese_max,
                grace_marks=grace,
                grace_reason=grace_reason,
                total_marks=C.d2(total)
                if result_status not in ("absent", "withheld", "detained", "incomplete")
                else None,
                total_max=total_max,
                percentage=pct if result_status not in ("absent", "withheld", "detained", "incomplete") else None,
                letter_grade=letter,
                grade_point=gp,
                result_status=result_status,
                counts_toward_cgpa=bool(c.is_credit_bearing and not audit),
                is_current=True,
                version=version,
                supersedes_id=supersedes,
                run_id=r.id,
                status="computed",
            )
            new_rows.append(row)
            if progress and n % 200 == 0:
                await progress(int(n * 70 / total_items), f"{n} items")

        # relative grading per course cohort (passing rows only)
        if feats.get("relative_grading"):
            by_course: dict[uuid.UUID, list[StudentCourseResult]] = defaultdict(list)
            for row in new_rows:
                if row.result_status == "pass":
                    by_course[row.course_id].append(row)
            for cid, rows in by_course.items():
                enr = enr_by_id[rows[0].student_program_enrollment_id]
                scale_id = (snap.get("program_regulation_scale") or {}).get(str(enr.program_regulation_id))
                scale = (snap.get("scales") or {}).get(scale_id or "", {})
                if scale.get("scale_type") != "relative":
                    continue
                cfg = scale.get("relative_config") or {}
                if len(rows) < int(cfg.get("min_class_size", 30)):
                    relative_fallback[str(cid)] = f"cohort {len(rows)} < min_class_size — absolute grading"
                    continue
                letters = C.relative_bands([float(x.percentage or 0) for x in rows], cfg)
                ranges = scale.get("ranges") or C.DEFAULT_RANGES
                for row, g in zip(rows, letters, strict=True):
                    row.letter_grade = g
                    row.grade_point = C.points_of(g, ranges) or row.grade_point

        # credit transfers approved for the term
        if not scope.get("course_ids"):
            for ct in (
                await self.db.execute(
                    select(CreditTransfer).where(
                        CreditTransfer.student_program_enrollment_id.in_(enr_ids or [uuid.uuid4()]),
                        CreditTransfer.status == "approved",
                        CreditTransfer.result_id.is_(None),
                        or_(CreditTransfer.term_id == s.term_id, CreditTransfer.term_id.is_(None)),
                        CreditTransfer.equivalent_course_id.is_not(None),
                    )
                )
            ).scalars():
                enr = enr_by_id[ct.student_program_enrollment_id]
                rules = (snap.get("rules") or {}).get(str(enr.program_regulation_id)) or {}
                scale_id = (snap.get("program_regulation_scale") or {}).get(str(enr.program_regulation_id))
                ranges = ((snap.get("scales") or {}).get(scale_id or "", {})).get("ranges") or C.DEFAULT_RANGES
                letter = ct.source_grade
                if ct.source_score_pct is not None:
                    for band, g in (rules.get("mooc_grade_map") or {}).items():
                        lo, _, hi = band.partition("-")
                        if float(lo) <= float(ct.source_score_pct) <= float(hi or 100):
                            letter = g
                            break
                gp = C.points_of(letter or "", ranges) if letter else None
                prev = current.get((enr.id, ct.equivalent_course_id), [])  # type: ignore[arg-type]
                new_rows.append(
                    StudentCourseResult(
                        institution_id=self.inst,
                        college_id=enr.college_id,
                        student_program_enrollment_id=enr.id,
                        term_id=s.term_id,
                        course_id=ct.equivalent_course_id,
                        attempt_number=1,
                        attempt_type="credit_transfer",
                        credits=ct.credits,
                        percentage=ct.source_score_pct,
                        letter_grade=(letter or "P")[:3],
                        grade_point=gp,
                        result_status="pass" if letter else "exempted",
                        counts_toward_cgpa=gp is not None,
                        version=(max((p.version for p in prev if p.attempt_number == 1), default=0) + 1),
                        run_id=r.id,
                        status="computed",
                    )
                )
            # withdrawn registration items → W
            for enr_id, cri in withdrawn:
                c = (
                    courses.get(cri.course_id)
                    or (await self.db.execute(select(Course).where(Course.id == cri.course_id))).scalar_one()
                )
                enr = enr_by_id[enr_id]
                prev = current.get((enr_id, c.id), [])
                if any(x.course_id == c.id and x.student_program_enrollment_id == enr_id for x in new_rows):
                    continue
                new_rows.append(
                    StudentCourseResult(
                        institution_id=self.inst,
                        college_id=enr.college_id,
                        student_program_enrollment_id=enr_id,
                        term_id=s.term_id,
                        course_id=c.id,
                        offering_id=cri.offering_id,
                        exam_session_id=s.id,
                        attempt_number=cri.attempt_number,
                        attempt_type="regular",
                        credits=c.credits,
                        letter_grade="W",
                        grade_point=Decimal(0),
                        result_status="withdrawn",
                        counts_toward_cgpa=False,
                        version=(
                            max((p.version for p in prev if p.attempt_number == cri.attempt_number), default=0) + 1
                        ),
                        run_id=r.id,
                        status="computed",
                    )
                )

        for row in new_rows:
            row.hash = hash_of(row)
            self.db.add(row)
        await self.db.flush()
        if progress:
            await progress(80, "term results")
        term_results = await TermResultBuilder(self).build(r, new_rows, enr_by_id, snap)
        stats: dict[str, Any] = {
            "rows": len(new_rows),
            "students": len({x.student_program_enrollment_id for x in new_rows}),
            "term_results": term_results,
            "by_status": dict(
                sorted(
                    {
                        st: sum(1 for x in new_rows if x.result_status == st)
                        for st in {x.result_status for x in new_rows}
                    }.items()
                )
            ),
            "anomalies_by_code": {
                code: sum(1 for a in anomalies if a["code"] == code) for code in sorted({a["code"] for a in anomalies})
            },
        }
        if relative_fallback:
            r.config_snapshot = {**snap, "relative_fallback": relative_fallback}
        r.stats = stats
        r.error_log = {"anomalies": anomalies}
        r.checksum = C.checksum([x.hash or "" for x in new_rows])
        r.status = "computed"
        await self.db.flush()
        await self._audit("run_compute", "result_run", r.id, None, {"rows": len(new_rows), "anomalies": len(anomalies)})
        await self._emit("results.computed", {"run_id": str(r.id), "rows": len(new_rows)}, "result_run", r.id)

    # ---- 3. chain ------------------------------------------------------------------------------------------------------
    async def anomalies(self, rid: uuid.UUID, code: str | None = None) -> list[AnomalyRow]:
        r = await self.run(rid)
        items = ((r.error_log or {}) if isinstance(r.error_log, dict) else {}).get("anomalies", [])
        if code:
            items = [a for a in items if a["code"] == code]
        enr_ids = {uuid.UUID(a["enrollment_id"]) for a in items if a.get("enrollment_id")}
        studs = dict(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_(enr_ids or {uuid.uuid4()}))
                )
            ).all()
        )
        cids = {uuid.UUID(a["course_id"]) for a in items if a.get("course_id")}
        codes = dict(
            (await self.db.execute(select(Course.id, Course.code).where(Course.id.in_(cids or {uuid.uuid4()})))).all()
        )
        rows = {
            (x.student_program_enrollment_id, x.course_id): x.id
            for x in (
                await self.db.execute(select(StudentCourseResult).where(StudentCourseResult.run_id == r.id))
            ).scalars()
        }
        out = []
        for a in items:
            e = uuid.UUID(a["enrollment_id"]) if a.get("enrollment_id") else None
            cid = uuid.UUID(a["course_id"]) if a.get("course_id") else None
            st = studs.get(e) if e else None
            out.append(
                AnomalyRow(
                    student=" ".join(x for x in (st.first_name, st.last_name) if x) if st else None,
                    registration_number=st.registration_number if st else None,
                    enrollment_id=e,
                    course=codes.get(cid) if cid else None,
                    course_id=cid,
                    code=a["code"],
                    detail=a.get("detail") or "",
                    row_id=rows.get((e, cid)) if e and cid else None,
                )
            )
        return out

    async def _set_rows(self, r: ResultProcessingRun, status: str) -> None:
        for row in (
            await self.db.execute(select(StudentCourseResult).where(StudentCourseResult.run_id == r.id))
        ).scalars():
            row.status = status

    async def verify(self, rid: uuid.UUID, body: RunAction) -> RunResponse:
        r = await self.run(rid, for_update=True)
        if r.status != "computed":
            raise rule(f"Only a computed run can be verified (status {r.status})", "INVALID_TRANSITION")
        n = len(((r.error_log or {}) if isinstance(r.error_log, dict) else {}).get("anomalies", []))
        if n and not body.acknowledge_anomalies:
            raise rule(f"{n} anomalies must be acknowledged before verification", "ANOMALIES_UNACKNOWLEDGED", count=n)
        r.status, r.verified_by, r.verified_at = "verified", self.actor_id, now_utc()
        await self._set_rows(r, "verified")
        await self.db.flush()
        await self._audit(
            "run_verify",
            "result_run",
            r.id,
            {"status": "computed"},
            {"status": "verified", "acknowledged": n, "comment": body.comment},
        )
        await self._emit("results.verified", {"run_id": str(r.id)}, "result_run", r.id)
        return await self.run_out(r)

    async def approve(self, rid: uuid.UUID, body: RunAction) -> RunResponse:
        r = await self.run(rid, for_update=True)
        if r.status != "verified":
            raise rule(f"Only a verified run can be approved (status {r.status})", "INVALID_TRANSITION")
        r.status, r.approved_by, r.approved_at = "approved", self.actor_id, now_utc()
        r.approval_resolution_id = body.resolution_id
        await self._set_rows(r, "approved")
        for t in (await self.db.execute(select(StudentTermResult).where(StudentTermResult.run_id == r.id))).scalars():
            t.status = "approved"
        await self.db.flush()
        await self._audit(
            "run_approve", "result_run", r.id, {"status": "verified"}, {"status": "approved", "comment": body.comment}
        )
        await self._emit("results.approved", {"run_id": str(r.id)}, "result_run", r.id)
        return await self.run_out(r)

    async def rollback(self, rid: uuid.UUID, body: RunAction) -> RunResponse:
        r = await self.run(rid, for_update=True)
        if r.status not in ("computed", "verified", "approved", "failed"):
            raise rule(f"A {r.status} run cannot be rolled back", "INVALID_TRANSITION")
        await self.db.execute(delete(StudentTermResult).where(StudentTermResult.run_id == r.id))
        n = (await self.db.execute(delete(StudentCourseResult).where(StudentCourseResult.run_id == r.id))).rowcount  # type: ignore[attr-defined]
        old = r.status
        r.status = "rolled_back"
        await self.db.flush()
        await self._audit(
            "run_rollback",
            "result_run",
            r.id,
            {"status": old},
            {"status": "rolled_back", "rows_deleted": n, "comment": body.comment},
        )
        await self._emit("results.rolled_back", {"run_id": str(r.id)}, "result_run", r.id)
        return await self.run_out(r)

    # ---- 4. publish ----------------------------------------------------------------------------------------------------
    async def publish(self, rid: uuid.UUID, body: PublishRequest) -> RunResponse:
        from app.core.jobs import enqueue
        from app.services.enrollment_service import EnrollmentService

        r = await self.run(rid, for_update=True)
        if r.status != "approved":
            raise rule(f"Only an approved run can be published (status {r.status})", "INVALID_TRANSITION")
        now = now_utc()
        withhold = set(body.withhold_ids)
        rows = list(
            (
                await self.db.execute(
                    select(StudentCourseResult).where(StudentCourseResult.run_id == r.id).with_for_update()
                )
            ).scalars()
        )
        enr_ids = {x.student_program_enrollment_id for x in rows}
        # previous current rows of the same (enrolment, course)
        olds = list(
            (
                await self.db.execute(
                    select(StudentCourseResult)
                    .where(
                        StudentCourseResult.student_program_enrollment_id.in_(enr_ids or {uuid.uuid4()}),
                        StudentCourseResult.is_current.is_(True),
                        StudentCourseResult.run_id != r.id,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        touched = {(x.student_program_enrollment_id, x.course_id) for x in rows}
        superseded = {x.supersedes_id for x in rows if x.supersedes_id}
        for o in olds:
            if (o.student_program_enrollment_id, o.course_id) in touched:
                o.is_current = False
                if o.id in superseded and o.status == "published":
                    o.status = "superseded"
        for x in rows:
            if x.student_program_enrollment_id in withhold and x.result_status not in ("withheld",):
                x.result_status, x.letter_grade, x.grade_point = "withheld", "WH", Decimal(0)
            x.status, x.published_at = "published", now
            x.hash = hash_of(x)
        await self.db.flush()
        # term results
        terms = list(
            (
                await self.db.execute(
                    select(StudentTermResult).where(StudentTermResult.run_id == r.id).with_for_update()
                )
            ).scalars()
        )
        rec_ids = {t.student_term_record_id for t in terms}
        for ot in (
            await self.db.execute(
                select(StudentTermResult)
                .where(
                    StudentTermResult.student_term_record_id.in_(rec_ids or {uuid.uuid4()}),
                    StudentTermResult.is_current.is_(True),
                    StudentTermResult.run_id != r.id,
                )
                .with_for_update()
            )
        ).scalars():
            ot.is_current = False
            if ot.status == "published":
                ot.status = "superseded"
        records = {
            x.id: x
            for x in (
                await self.db.execute(
                    select(StudentTermRecord)
                    .where(StudentTermRecord.id.in_(rec_ids or {uuid.uuid4()}))
                    .with_for_update()
                )
            ).scalars()
        }
        enrolments = {
            e.id: e
            for e in (
                await self.db.execute(
                    select(StudentProgramEnrollment)
                    .where(StudentProgramEnrollment.id.in_(enr_ids or {uuid.uuid4()}))
                    .with_for_update()
                )
            ).scalars()
        }
        sgpa_of: dict[uuid.UUID, Decimal | None] = {}
        for t in terms:
            rec = records.get(t.student_term_record_id)
            withheld = rec is not None and rec.student_program_enrollment_id in withhold
            t.status = "withheld" if withheld else "published"
            t.published_at = now
            if rec is None or withheld:
                continue
            sgpa_of[rec.student_program_enrollment_id] = t.sgpa
            rec.sgpa, rec.cgpa = t.sgpa, t.cgpa
            rec.credits_registered, rec.credits_earned = t.credits_registered, t.credits_earned
            rec.result_status = "pass" if t.backlog_count == 0 else "fail"
            detained = any(
                x.result_status == "detained" and x.student_program_enrollment_id == rec.student_program_enrollment_id
                for x in rows
            )
            rec.status = "detained" if detained else "completed"
            e = enrolments.get(rec.student_program_enrollment_id)
            if e is not None:
                e.cgpa = t.cgpa
                e.credits_earned = t.cumulative_credits or e.credits_earned
        # arrears ledger
        arrears = {
            (a.student_program_enrollment_id, a.course_id): a
            for a in (
                await self.db.execute(
                    select(StudentArrear)
                    .where(StudentArrear.student_program_enrollment_id.in_(enr_ids or {uuid.uuid4()}))
                    .with_for_update()
                )
            ).scalars()
        }
        arrear_changes = 0
        for x in rows:
            if x.attempt_type in ("credit_transfer", "audit", "legacy") or x.result_status in (
                "withheld",
                "withdrawn",
                "incomplete",
            ):
                continue
            key = (x.student_program_enrollment_id, x.course_id)
            a = arrears.get(key)
            if x.result_status in ("fail", "absent", "detained", "malpractice"):
                if a is None:
                    a = StudentArrear(
                        institution_id=self.inst,
                        student_program_enrollment_id=x.student_program_enrollment_id,
                        course_id=x.course_id,
                        first_failed_term_id=x.term_id,
                        last_attempt_term_id=x.term_id,
                        attempts=x.attempt_number,
                        status="open",
                    )
                    self.db.add(a)
                    arrears[key] = a
                else:
                    a.attempts, a.last_attempt_term_id = max(a.attempts, x.attempt_number), x.term_id
                    if a.status in ("registered", "cleared"):
                        a.status = "open"
                arrear_changes += 1
            elif x.result_status in PASSING and a is not None and a.status in ("open", "registered"):
                a.status, a.cleared_result_id, a.last_attempt_term_id = "cleared", x.id, x.term_id
                arrear_changes += 1
        # credit transfers → result link
        for x in rows:
            if x.attempt_type == "credit_transfer":
                for ct in (
                    await self.db.execute(
                        select(CreditTransfer).where(
                            CreditTransfer.student_program_enrollment_id == x.student_program_enrollment_id,
                            CreditTransfer.equivalent_course_id == x.course_id,
                            CreditTransfer.result_id.is_(None),
                        )
                    )
                ).scalars():
                    ct.result_id = x.id
        # ABC ledger
        snap = r.config_snapshot or {}
        abc = 0
        if (snap.get("features") or {}).get("abc_apaar"):
            abc = await self._abc_rows(rows)
        await self.db.flush()
        # standing (Phase 07)
        es = EnrollmentService(self.db, self.principal, institution_id=self.inst)
        for e in enrolments.values():
            with contextlib.suppress(APIError):
                await es.recompute_standing(e)
        pub = ResultPublication(
            institution_id=self.inst,
            run_id=r.id,
            exam_session_id=r.exam_session_id,
            published_by=self.actor_id or uuid.UUID(int=0),
            audience=body.audience,
            notify={"enabled": body.notify},
            withheld_list=[str(w) for w in withhold],
        )
        self.db.add(pub)
        r.status, r.published_at = "published", now
        if r.exam_session_id:
            s = (await self.db.execute(select(ExamSession).where(ExamSession.id == r.exam_session_id))).scalar_one()
            if s.status in ("in_progress", "valuation", "result_processing"):
                s.status = "results_published"
        await self.db.flush()
        await self._audit(
            "run_publish",
            "result_run",
            r.id,
            {"status": "approved"},
            {
                "status": "published",
                "rows": len(rows),
                "withheld": len(withhold),
                "arrears": arrear_changes,
                "abc": abc,
            },
        )
        await self._emit(
            "results.published",
            {
                "run_id": str(r.id),
                "session_id": str(r.exam_session_id) if r.exam_session_id else None,
                "enrollment_ids": [str(e) for e in enr_ids],
                "audience": body.audience,
                "run_type": r.run_type,
            },
            "result_run",
            r.id,
        )
        if any(x.version > 1 for x in rows):
            await self._emit("results.version_created", {"run_id": str(r.id)}, "result_run", r.id)
        if arrear_changes:
            await self._emit("arrears.updated", {"run_id": str(r.id), "changes": arrear_changes}, "result_run", r.id)
        if body.notify:
            await self._notify_students(enrolments, sgpa_of, withhold)
            pub.notify = {"enabled": True, "sent": True}
            await self.db.flush()
        with contextlib.suppress(Exception):  # grade cards can also be generated on demand
            await enqueue(self.db, self.principal, "results.grade_cards", {"run_id": str(r.id)})
        return await self.run_out(r)

    async def _abc_rows(self, rows: list[StudentCourseResult]) -> int:
        good = [x for x in rows if x.result_status in PASSING and x.credits and x.counts_toward_cgpa]
        if not good:
            return 0
        enr = dict(
            (
                await self.db.execute(
                    select(StudentProgramEnrollment.id, Student)
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_({x.student_program_enrollment_id for x in good}))
                )
            ).all()
        )
        courses = {
            c.id: c
            for c in (await self.db.execute(select(Course).where(Course.id.in_({x.course_id for x in good})))).scalars()
        }
        year = None
        term = (
            await self.db.execute(select(AcademicTerm).where(AcademicTerm.id == good[0].term_id))
        ).scalar_one_or_none()
        if term is not None:
            from app.models.academic import AcademicYear

            year = (
                await self.db.execute(select(AcademicYear.name).where(AcademicYear.id == term.academic_year_id))
            ).scalar_one_or_none()
        n = 0
        for x in good:
            st = enr.get(x.student_program_enrollment_id)
            c = courses.get(x.course_id)
            if st is None or c is None:
                continue
            self.db.add(
                AbcCreditLedger(
                    institution_id=self.inst,
                    student_id=st.id,
                    apaar_id=st.apaar_id,
                    student_course_result_id=x.id,
                    term_id=x.term_id,
                    course_code=c.code,
                    course_title=c.title,
                    credits=x.credits,
                    letter_grade=x.letter_grade,
                    grade_point=x.grade_point,
                    academic_year=year,
                    status="pending",
                )
            )
            n += 1
        return n

    async def _notify_students(
        self,
        enrolments: dict[uuid.UUID, StudentProgramEnrollment],
        sgpa_of: dict[uuid.UUID, Decimal | None],
        withhold: set[uuid.UUID],
    ) -> None:
        studs = dict(
            (
                await self.db.execute(
                    select(Student.id, Student.user_id).where(
                        Student.id.in_({e.student_id for e in enrolments.values()} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        for e in enrolments.values():
            uid = studs.get(e.student_id)
            if uid is None or e.id in withhold:
                continue
            sg = sgpa_of.get(e.id)
            await self._notify(
                "results.published",
                [uid],
                {"sgpa": f"{sg:.2f}" if sg is not None else "—"},
                guardians=True,
            )

    async def retry_notifications(self) -> int:
        """Beat (10 min): publications of the last 6 hours whose notification step did not complete."""
        n = 0
        for pub in (
            await self.db.execute(
                select(ResultPublication).where(
                    ResultPublication.institution_id == self.inst,
                    ResultPublication.published_at > now_utc() - timedelta(hours=6),
                )
            )
        ).scalars():
            meta = pub.notify or {}
            if not meta.get("enabled") or meta.get("sent"):
                continue
            terms = (
                await self.db.execute(
                    select(StudentTermRecord.student_program_enrollment_id, StudentTermResult.sgpa)
                    .join(StudentTermResult, StudentTermResult.student_term_record_id == StudentTermRecord.id)
                    .where(StudentTermResult.run_id == pub.run_id)
                )
            ).all()
            sg = dict(terms)
            enrolments = {
                e.id: e
                for e in (
                    await self.db.execute(
                        select(StudentProgramEnrollment).where(
                            StudentProgramEnrollment.id.in_(set(sg) or {uuid.uuid4()})
                        )
                    )
                ).scalars()
            }
            await self._notify_students(enrolments, sg, {uuid.UUID(w) for w in (pub.withheld_list or [])})
            pub.notify = {**meta, "sent": True}
            n += 1
        await self.db.flush()
        return n

    async def list_runs(self, session_id: uuid.UUID | None, status: str | None) -> list[RunResponse]:
        q = select(ResultProcessingRun).where(ResultProcessingRun.institution_id == self.inst)
        if session_id:
            q = q.where(ResultProcessingRun.exam_session_id == session_id)
        if status:
            q = q.where(ResultProcessingRun.status == status)
        mine = college_ids(self.principal) if self.principal is not None else []
        out = []
        for r in (await self.db.execute(q.order_by(ResultProcessingRun.created_at.desc()).limit(200))).scalars():
            scoped = (r.scope or {}).get("college_ids") or []
            if mine and not institution_scope(self.principal) and scoped and not set(map(str, mine)) & set(scoped):
                continue
            out.append(await self.run_out(r))
        return out

    async def get_run(self, rid: uuid.UUID) -> RunResponse:
        return await self.run_out(await self.run(rid))

    async def run_rows(
        self, rid: uuid.UUID, program_id: uuid.UUID | None, course_id: uuid.UUID | None, status: str | None, page: Any
    ) -> tuple[list[CourseResultResponse], int]:
        from app.repositories.result_scope import result_predicate

        r = await self.run(rid)
        if not any(self.can("results", a) for a in ("compute", "verify", "manage")) and r.status in (
            "queued",
            "computing",
            "computed",
            "failed",
        ):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Run rows are readable after verification")
        q = select(StudentCourseResult).where(
            StudentCourseResult.run_id == r.id, result_predicate(self.principal, "all")
        )
        if program_id:
            q = q.where(
                StudentCourseResult.student_program_enrollment_id.in_(
                    select(StudentProgramEnrollment.id).where(StudentProgramEnrollment.program_id == program_id)
                )
            )
        if course_id:
            q = q.where(StudentCourseResult.course_id == course_id)
        if status:
            q = q.where(StudentCourseResult.result_status == status)
        total = int((await self.db.execute(select(func.count()).select_from(q.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(
                    q.order_by(StudentCourseResult.student_program_enrollment_id, StudentCourseResult.course_id)
                    .offset(page.offset)
                    .limit(page.page_size)
                )
            ).scalars()
        )
        return await self.rows_out(rows), total


class TermResultBuilder:
    """SGPA / CGPA / class per (enrolment, term) of a run's rows — shared by compute and the legacy import."""

    def __init__(self, svc: ResultBase):
        self.svc = svc
        self.db = svc.db

    async def build(
        self,
        r: ResultProcessingRun,
        new_rows: list[StudentCourseResult],
        enr_by_id: dict[uuid.UUID, StudentProgramEnrollment],
        snap: dict[str, Any],
    ) -> int:
        by_term: dict[tuple[uuid.UUID, uuid.UUID], list[StudentCourseResult]] = defaultdict(list)
        for x in new_rows:
            by_term[(x.student_program_enrollment_id, x.term_id)].append(x)
        if not by_term:
            return 0
        enr_ids = {e for e, _ in by_term}
        records = {
            (t.student_program_enrollment_id, t.term_id): t
            for t in (
                await self.db.execute(
                    select(StudentTermRecord).where(StudentTermRecord.student_program_enrollment_id.in_(enr_ids))
                )
            ).scalars()
        }
        published = list(
            (
                await self.db.execute(
                    select(StudentCourseResult).where(
                        StudentCourseResult.student_program_enrollment_id.in_(enr_ids),
                        StudentCourseResult.status == "published",
                    )
                )
            ).scalars()
        )
        prev_terms = {
            t.student_term_record_id: t.version
            for t in (
                await self.db.execute(
                    select(StudentTermResult).where(
                        StudentTermResult.student_term_record_id.in_(
                            {x.id for x in records.values()} or {uuid.uuid4()}
                        ),
                        StudentTermResult.is_current.is_(True),
                    )
                )
            ).scalars()
        }
        made = 0
        for (enr_id, term_id), rows in by_term.items():
            rec = records.get((enr_id, term_id))
            if rec is None:
                continue
            enr = enr_by_id.get(enr_id)
            if enr is None:
                enr = (
                    await self.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == enr_id))
                ).scalar_one()
            rules = (snap.get("rules") or {}).get(str(enr.program_regulation_id)) or {}
            include_failed = bool(rules.get("include_failed_credits_in_sgpa", True))
            policy = str(rules.get("cgpa_attempt_policy", "latest"))
            # this term's set = this run's rows + other current published rows of the term not replaced by the run
            replaced = {x.course_id for x in rows}
            term_set = rows + [
                p
                for p in published
                if p.student_program_enrollment_id == enr_id
                and p.term_id == term_id
                and p.is_current
                and p.course_id not in replaced
            ]
            graded = [
                x
                for x in term_set
                if x.counts_toward_cgpa and x.credits and x.result_status not in ("withheld", "withdrawn", "incomplete")
            ]
            sg = C.sgpa([(x.credits, x.grade_point, x.result_status in PASSING) for x in graded], include_failed)
            # CGPA across all attempts (published + this run's rows; same version chain → latest wins)
            attempts: dict[uuid.UUID, list[tuple[int, int, Decimal, Decimal | None, bool]]] = defaultdict(list)
            superseded = {x.supersedes_id for x in rows if x.supersedes_id}
            for p in published:
                if p.student_program_enrollment_id == enr_id and p.counts_toward_cgpa and p.id not in superseded:
                    attempts[p.course_id].append(
                        (p.attempt_number, p.version, p.credits, p.grade_point, p.result_status in PASSING)
                    )
            for x in rows:
                if x.counts_toward_cgpa and x.result_status not in ("withheld", "withdrawn", "incomplete"):
                    attempts[x.course_id] = [a for a in attempts[x.course_id] if a[0] != x.attempt_number]
                    attempts[x.course_id].append(
                        (x.attempt_number, x.version, x.credits, x.grade_point, x.result_status in PASSING)
                    )
            cg, earned = C.cgpa(attempts, policy, include_failed)
            backlogs = sum(
                1
                for rows_ in attempts.values()
                if rows_ and not max(rows_, key=lambda a: (a[0], a[1]))[4] and not any(a[4] for a in rows_)
            )
            first_attempt = all(a[0] == 1 for rows_ in attempts.values() for a in rows_)
            cls = C.result_class(cg, rules.get("class_rules") or [], first_attempt) if backlogs == 0 else None
            self.db.add(
                StudentTermResult(
                    institution_id=self.svc.inst,
                    student_term_record_id=rec.id,
                    run_id=r.id,
                    credits_registered=sum((x.credits for x in term_set if x.counts_toward_cgpa), Decimal(0)),
                    credits_earned=sum(
                        (x.credits for x in term_set if x.counts_toward_cgpa and x.result_status in PASSING), Decimal(0)
                    ),
                    sgpa=sg,
                    cgpa=cg,
                    cumulative_credits=earned,
                    backlog_count=backlogs,
                    result_class=cls,
                    status="computed",
                    version=prev_terms.get(rec.id, 0) + 1,
                    is_current=True,
                )
            )
            made += 1
        await self.db.flush()
        return made
