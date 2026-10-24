"""CO attainment per offering — Prompts/17 §17.6 ``co_attainment_service``.

``request_run`` creates a ``queued`` run and enqueues ``obe.co_run`` (inline when called by consumers / seeders);
``compute(run)`` does the work:

1. **Prerequisites** — every CIA assessment (component category ``cia`` / ``project_review``) ``locked``; when the
   course had an ESE paper in the offering's term, results of the offering ``published``. Missing → warnings
   ``CIA_NOT_LOCKED`` / ``RESULTS_NOT_PUBLISHED`` and the run ends ``failed`` with no rows (409 ``PREREQUISITES`` at
   request time when setting ``obe.strict_prereq`` is on).
2. **CIA** (``co_mappable`` components, question-wise marks): student CO marks = Σ marks of the questions tagged to the
   CO; CO max = Σ max of those questions; ``pct = count(co_marks ≥ target_marks_pct × co_max) / assessed`` → level by
   the bands (0 below band 1). ``cia_level`` = mean of the assessment levels weighted by component ``weight_pct``.
3. **ESE** — ``question_wise`` (latest locked valuation's question-wise marks scaled to the final marks, questions
   mapped through ``qp_pattern.questions[].co``), else ``qp_pattern`` (final totals apportioned by ``qp_pattern``
   ``co_weights`` or the per-question CO tags' max), else uniform across COs (``ESE_UNIFORM_APPORTION``). Totals come
   from ``script_final_marks.final_marks`` or, without scripts, ``student_course_results.ese_marks``.
4. ``direct = (cia_w × cia + ese_w × ese) / (cia_w + ese_w)`` (one side only when the other is missing).
5. **Indirect** (``obe.indirect_surveys``): course-exit survey questions tagged ``co_id`` / ``co`` → mean answer →
   level by ``survey_thresholds``; ``final = (direct_w × direct + indirect_w × indirect) / 100``; without a survey
   ``final = direct`` + ``NO_INDIRECT``. ``gap = target − final``.

Per-student CO achievement (marks / max per CO, CIA + ESE) is cached in ``config_snapshot._students`` for the optional
student view; warnings in ``config_snapshot._warnings``.
"""

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import desc, func, select

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.models.academic import Batch
from app.models.assessment import AssessmentQuestion, InternalMark, OfferingAssessment
from app.models.curriculum import AssessmentComponent
from app.models.exams import ExamPaper, ExamRegistration, ExamRegistrationItem, ExamSession
from app.models.obe import CourseOutcome
from app.models.obe_attainment import AttainmentRun, CoAttainment, CoBreakdown, FeedbackResponse, FeedbackSurvey
from app.models.offerings import CourseOffering, CourseOfferingTarget
from app.models.results import StudentCourseResult
from app.models.students import Student, StudentProgramEnrollment
from app.models.valuation import AnswerScript, ScriptFinalMarks, ScriptValuation
from app.schemas.obe_attainment import (
    CoAttainmentResponse,
    CoPoHeatmap,
    CoRow,
    CoRunRequest,
    IndirectSurveySummary,
    Prerequisites,
    RunResponse,
    RunSummary,
    StudentCoAchievement,
    StudentCoItem,
)
from app.services.obe.common import ObeBase, d2, f2, level_for, run_summary, survey_level
from app.services.obe.config_service import AttainmentConfigService

CIA_CATEGORIES = ("cia", "project_review")


def _w(weights: list[tuple[float, float]]) -> float | None:
    """Weighted mean of ``(value, weight)``; plain mean when every weight is 0."""
    if not weights:
        return None
    total = sum(w for _, w in weights)
    if total <= 0:
        return sum(v for v, _ in weights) / len(weights)
    return sum(v * w for v, w in weights) / total


def survey_question_map(questions: Any, key: str) -> dict[str, str]:
    """``{question id: tag}`` for questions tagged ``<key>_id`` (uuid) or ``<key>`` (code)."""
    items = questions.get("questions") if isinstance(questions, dict) else questions
    out: dict[str, str] = {}
    for i, q in enumerate(items or []):
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id") or q.get("key") or q.get("q") or i)
        tag = q.get(f"{key}_id") or q.get(key)
        if tag:
            out[qid] = str(tag)
    return out


def survey_means(questions: Any, answers: list[Any], key: str) -> tuple[dict[str, float], int]:
    qmap = survey_question_map(questions, key)
    acc: dict[str, list[float]] = defaultdict(list)
    for a in answers:
        if not isinstance(a, dict):
            continue
        for qid, tag in qmap.items():
            v = a.get(qid)
            try:
                acc[tag].append(float(v))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
    return {t: sum(v) / len(v) for t, v in acc.items() if v}, len(answers)


class CoAttainmentService(ObeBase):
    # ---- request / job ----------------------------------------------------------------------------------------------
    async def prerequisites(self, o: CourseOffering) -> Prerequisites:
        rows = (
            await self.db.execute(
                select(OfferingAssessment.name, OfferingAssessment.status)
                .join(AssessmentComponent, AssessmentComponent.id == OfferingAssessment.component_id)
                .where(OfferingAssessment.offering_id == o.id, AssessmentComponent.category.in_(CIA_CATEGORIES))
            )
        ).all()
        pending = [r[0] for r in rows if r[1] != "locked"]
        paper = await self._ese_paper(o)
        published = (
            await self.db.execute(
                select(func.count())
                .select_from(StudentCourseResult)
                .where(StudentCourseResult.offering_id == o.id, StudentCourseResult.status == "published")
            )
        ).scalar_one() > 0
        survey = await self._course_exit_survey(o, None)
        return Prerequisites(
            cia_locked=bool(rows) and not pending,
            cia_pending=pending,
            has_ese=paper is not None,
            results_published=published,
            survey_present=survey is not None,
        )

    async def request_run(
        self, offering_id: uuid.UUID, body: CoRunRequest, *, inline: bool = False, force: bool = False
    ) -> RunResponse:
        """``force`` (demo seeder only) computes despite missing prerequisites — the warnings stay on the run."""
        o = await self.att_offering(offering_id) if self.principal is not None else await self._offering(offering_id)
        if self.principal is not None:
            await self.require_compute(o)
        pre = await self.prerequisites(o)
        warnings = self._pre_warnings(pre)
        if warnings and not force and await self.setting("obe", "strict_prereq"):
            raise APIError(
                409,
                ErrorCode.RULE_VIOLATION,
                "Attainment prerequisites not met",
                {"code": "PREREQUISITES", "warnings": warnings},
            )
        run = AttainmentRun(
            institution_id=self.inst,
            scope_type="offering",
            scope_id=o.id,
            status="queued",
            run_by=self.actor_id,
            config_snapshot={"_request": body.model_dump(mode="json"), "_force": force},
        )
        self.db.add(run)
        await self.db.flush()
        if inline:
            await self.compute(run.id)
        else:
            from app.core.jobs import enqueue

            job = await enqueue(self.db, self.principal, "obe.co_run", {"run_id": str(run.id)})
            run.job_id = job.id
        await self.db.flush()
        snap = run.config_snapshot or {}
        return RunResponse(
            run_id=run.id,
            job_id=run.job_id,
            scope_type="offering",
            scope_id=o.id,
            status=run.status,
            config_snapshot={k: v for k, v in snap.items() if not k.startswith("_")} or None,
            computed_at=run.run_at if run.status == "computed" else None,
            warnings=list(snap.get("_warnings") or warnings),
        )

    @staticmethod
    def _pre_warnings(pre: Prerequisites) -> list[str]:
        w = []
        if not pre.cia_locked:
            w.append("CIA_NOT_LOCKED")
        if pre.has_ese and not pre.results_published:
            w.append("RESULTS_NOT_PUBLISHED")
        return w

    async def _offering(self, offering_id: uuid.UUID) -> CourseOffering:
        row = (
            await self.db.execute(
                select(CourseOffering).where(
                    CourseOffering.id == offering_id, CourseOffering.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Course offering not found")
        return row

    async def _program_of(self, o: CourseOffering) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        row = (
            await self.db.execute(
                select(Batch.program_id, Batch.id)
                .join(CourseOfferingTarget, CourseOfferingTarget.batch_id == Batch.id)
                .where(CourseOfferingTarget.offering_id == o.id)
                .limit(1)
            )
        ).first()
        return (row[0], row[1]) if row else (None, None)

    # ---- compute ----------------------------------------------------------------------------------------------------
    async def compute(self, run_id: uuid.UUID) -> AttainmentRun:  # noqa: C901, PLR0912, PLR0915 - one formula
        run = (await self.db.execute(select(AttainmentRun).where(AttainmentRun.id == run_id))).scalar_one()
        o = await self._offering(run.scope_id)
        req = (run.config_snapshot or {}).get("_request") or {}
        force = bool((run.config_snapshot or {}).get("_force"))
        program_id, batch_id = await self._program_of(o)
        cfg = await AttainmentConfigService(self.db, self.principal, self.request, self.inst).effective(
            program_id, batch_id=batch_id
        )
        warnings: list[str] = []
        pre = await self.prerequisites(o)
        blocking = self._pre_warnings(pre)
        if blocking and force:
            warnings.extend(blocking)
        elif blocking:
            run.status = "failed"
            run.config_snapshot = {**cfg, "_warnings": blocking, "_request": req}
            await self.db.flush()
            return run

        bands = cfg["levels"]
        target_marks = float(cfg["target_marks_pct"]) / 100
        cos = list(
            (
                await self.db.execute(
                    select(CourseOutcome).where(CourseOutcome.course_id == o.course_id).order_by(CourseOutcome.sequence)
                )
            )
            .scalars()
            .all()
        )
        if not cos:
            run.status = "failed"
            run.config_snapshot = {**cfg, "_warnings": ["NO_COURSE_OUTCOMES"], "_request": req}
            await self.db.flush()
            return run
        co_by_id = {c.id: c for c in cos}
        co_by_code = {c.code.upper(): c for c in cos}
        roster = await self.roster(o)
        roster_ids = {r[0] for r in roster}

        # per-student achievement: enrol -> co_id -> [marks, max]
        students: dict[uuid.UUID, dict[uuid.UUID, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        cia_parts: dict[uuid.UUID, list[CoBreakdown]] = defaultdict(list)
        ese_parts: dict[uuid.UUID, list[CoBreakdown]] = defaultdict(list)
        assessed_union: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)

        def tally(
            co_id: uuid.UUID,
            name: str,
            kind: str,
            source: str,
            co_max: float,
            marks: dict[uuid.UUID, float],
            weight: float,
        ) -> None:
            if co_max <= 0 or not marks:
                return
            above = sum(1 for v in marks.values() if v >= target_marks * co_max - 1e-9)
            pct = above / len(marks) * 100
            part = CoBreakdown(
                assessment=name,
                kind=kind,
                source=source,
                co_max=round(co_max, 2),
                students_assessed=len(marks),
                students_above_target=above,
                pct=round(pct, 2),
                level=level_for(pct, bands),
                weight=weight,
            )
            (cia_parts if kind == "cia" else ese_parts)[co_id].append(part)
            for e, v in marks.items():
                students[e][co_id][0] += v
                students[e][co_id][1] += co_max
                assessed_union[co_id].add(e)

        # ---- CIA ----
        assessments = (
            await self.db.execute(
                select(OfferingAssessment, AssessmentComponent)
                .join(AssessmentComponent, AssessmentComponent.id == OfferingAssessment.component_id)
                .where(
                    OfferingAssessment.offering_id == o.id,
                    AssessmentComponent.category.in_(CIA_CATEGORIES),
                    AssessmentComponent.co_mappable.is_(True),
                )
                .order_by(AssessmentComponent.sequence)
            )
        ).all()
        for a, comp in assessments:
            questions = (
                (
                    await self.db.execute(
                        select(AssessmentQuestion).where(AssessmentQuestion.offering_assessment_id == a.id)
                    )
                )
                .scalars()
                .all()
            )
            tagged = [q for q in questions if q.co_id in co_by_id]
            if not tagged:
                warnings.append(f"NO_CO_MAP:{a.name}")
                continue
            marks_rows = (
                (
                    await self.db.execute(
                        select(InternalMark).where(
                            InternalMark.offering_assessment_id == a.id,
                            InternalMark.is_absent.is_(False),
                            InternalMark.is_exempt.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )
            marks_rows = [m for m in marks_rows if m.student_program_enrollment_id in roster_ids or not roster_ids]
            if marks_rows and not any(m.question_wise for m in marks_rows):
                warnings.append(f"NO_QUESTION_WISE:{a.name}")
                continue
            by_co: dict[uuid.UUID, list[AssessmentQuestion]] = defaultdict(list)
            for q in tagged:
                by_co[q.co_id].append(q)  # type: ignore[index]
            weight = float(comp.weight_pct) if comp.weight_pct is not None else 1.0
            for co_id, qs in by_co.items():
                co_max = sum(float(q.max_marks) for q in qs)
                marks: dict[uuid.UUID, float] = {}
                for m in marks_rows:
                    qw = {k: v for k, v in (m.question_wise or {}).items() if not str(k).startswith("_")}
                    if not qw:
                        continue
                    total = 0.0
                    for q in qs:
                        try:
                            total += float(qw.get(q.question_no) or 0)
                        except (TypeError, ValueError):
                            continue
                    marks[m.student_program_enrollment_id] = total
                tally(co_id, a.name, "cia", "question_wise", co_max, marks, weight)

        # ---- ESE ----
        paper = await self._ese_paper(o)
        if paper is None:
            warnings.append("NO_ESE")
        else:
            await self._ese(o, paper, cfg, cos, co_by_code, roster_ids, tally, warnings)

        # ---- indirect ----
        indirect: dict[uuid.UUID, int] = {}
        survey_used: dict[str, Any] | None = None
        if req.get("include_indirect", True) and await is_enabled(self.inst, "obe.indirect_surveys"):
            sid = uuid.UUID(req["survey_id"]) if req.get("survey_id") else None
            survey = await self._course_exit_survey(o, sid)
            if survey is not None:
                answers = (
                    (
                        await self.db.execute(
                            select(FeedbackResponse.answers).where(
                                FeedbackResponse.survey_id == survey.id, FeedbackResponse.target_id == o.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                means, n = survey_means(survey.questions, list(answers), "co")
                thresholds = cfg.get("survey_thresholds") or []
                for tag, mean in means.items():
                    co = co_by_code.get(tag.upper()) or next((c for c in cos if str(c.id) == tag), None)
                    if co is not None:
                        indirect[co.id] = survey_level(mean, thresholds)
                survey_used = {"id": str(survey.id), "title": survey.title, "responses": n}
        if not indirect:
            warnings.append("NO_INDIRECT")

        # ---- rows ----
        cw, ew = float(cfg["cia_weight_in_direct"]), float(cfg["ese_weight_in_direct"])
        dw, iw = float(cfg["direct_weight"]), float(cfg["indirect_weight"])
        target = float(cfg["co_target_level"])
        gaps = []
        for co in cos:
            cia = _w([(p.level, p.weight) for p in cia_parts.get(co.id, [])])
            ese = _w([(p.level, 1.0) for p in ese_parts.get(co.id, [])])
            if cia is not None and ese is not None:
                direct: float | None = (cw * cia + ew * ese) / (cw + ew) if cw + ew else (cia + ese) / 2
            else:
                direct = cia if cia is not None else ese
            ind = indirect.get(co.id)
            final = None if direct is None else ((dw * direct + iw * ind) / 100 if ind is not None else direct)
            parts = cia_parts.get(co.id, []) + ese_parts.get(co.id, [])
            assessed = len(assessed_union.get(co.id, set()))
            above = sum(
                1
                for e in assessed_union.get(co.id, set())
                if students[e][co.id][1] > 0 and students[e][co.id][0] >= target_marks * students[e][co.id][1] - 1e-9
            )
            gap = None if final is None else target - final
            self.db.add(
                CoAttainment(
                    institution_id=self.inst,
                    offering_id=o.id,
                    course_outcome_id=co.id,
                    run_id=run.id,
                    students_assessed=assessed,
                    students_above_target=above,
                    direct_pct=d2(above / assessed * 100) if assessed else None,
                    direct_level=d2(direct),
                    cia_level=d2(cia),
                    ese_level=d2(ese),
                    indirect_level=d2(ind),
                    final_level=d2(final),
                    target_level=d2(target),
                    gap=d2(gap),
                    breakdown={"parts": [p.model_dump() for p in parts]},
                )
            )
            if gap is not None and gap > 0:
                gaps.append({"co": co.code, "gap": round(gap, 2)})
        run.status = "computed"
        run.config_snapshot = {
            **cfg,
            "_request": req,
            "_warnings": sorted(set(warnings)),
            "_survey": survey_used,
            "_students": {
                str(e): {str(c): [round(v[0], 2), round(v[1], 2)] for c, v in m.items()} for e, m in students.items()
            },
        }
        await self.db.flush()
        await self._emit(
            "obe.co_attainment_computed",
            {"run_id": str(run.id), "offering_id": str(o.id), "course_id": str(o.course_id), "gaps": gaps},
            "attainment_run",
            run.id,
        )
        if gaps:
            await self._emit(
                "obe.gap_detected", {"scope": "offering", "scope_id": str(o.id), "gaps": gaps}, "attainment_run", run.id
            )
            await self._notify_gap(o, gaps)
        return run

    async def _notify_gap(self, o: CourseOffering, gaps: list[dict[str, Any]]) -> None:
        from app.models.hr import Staff
        from app.models.offerings import CourseOfferingFaculty

        users = (
            (
                await self.db.execute(
                    select(Staff.user_id)
                    .join(CourseOfferingFaculty, CourseOfferingFaculty.staff_id == Staff.id)
                    .where(CourseOfferingFaculty.offering_id == o.id)
                )
            )
            .scalars()
            .all()
        )
        ref = await self.offering_ref(o)
        await self._notify(
            "obe.gap_detected",
            list(users),
            {"scope": f"{ref.course_code} {ref.section_code}", "count": str(len(gaps))},
        )

    async def _ese_paper(self, o: CourseOffering) -> ExamPaper | None:
        return (
            await self.db.execute(
                select(ExamPaper)
                .join(ExamSession, ExamSession.id == ExamPaper.exam_session_id)
                .where(
                    ExamPaper.course_id == o.course_id,
                    ExamSession.term_id == o.term_id,
                    ExamSession.deleted_at.is_(None),
                    ExamPaper.paper_type.in_(("theory", "practical", "online")),
                )
                .order_by((ExamSession.exam_kind == "regular").desc(), ExamPaper.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _ese(  # noqa: C901, PLR0912 - three strategies
        self,
        o: CourseOffering,
        paper: ExamPaper,
        cfg: dict[str, Any],
        cos: list[CourseOutcome],
        co_by_code: dict[str, CourseOutcome],
        roster_ids: set[uuid.UUID],
        tally: Any,
        warnings: list[str],
    ) -> None:
        items = (
            await self.db.execute(
                select(ExamRegistrationItem.id, ExamRegistration.student_program_enrollment_id)
                .join(ExamRegistration, ExamRegistration.id == ExamRegistrationItem.exam_registration_id)
                .where(
                    ExamRegistrationItem.exam_paper_id == paper.id,
                    ExamRegistrationItem.status.in_(("appeared", "registered")),
                )
            )
        ).all()
        enrol_of = {i: e for i, e in items if not roster_ids or e in roster_ids}
        scripts = (
            await self.db.execute(
                select(AnswerScript.id, AnswerScript.exam_registration_item_id, ScriptFinalMarks.final_marks)
                .outerjoin(ScriptFinalMarks, ScriptFinalMarks.answer_script_id == AnswerScript.id)
                .where(AnswerScript.exam_registration_item_id.in_(list(enrol_of) or [uuid.uuid4()]))
            )
        ).all()
        totals: dict[uuid.UUID, float] = {}
        script_of: dict[uuid.UUID, uuid.UUID] = {}
        for sid, iid, final in scripts:
            if final is not None:
                totals[enrol_of[iid]] = float(final)
                script_of[sid] = enrol_of[iid]
        if not totals:
            res = (
                await self.db.execute(
                    select(StudentCourseResult.student_program_enrollment_id, StudentCourseResult.ese_marks).where(
                        StudentCourseResult.offering_id == o.id,
                        StudentCourseResult.status == "published",
                        StudentCourseResult.ese_marks.is_not(None),
                    )
                )
            ).all()
            totals = {e: float(m) for e, m in res}
        if not totals:
            warnings.append("NO_ESE_MARKS")
            return
        pmax = float(paper.max_marks)
        pattern = paper.qp_pattern or {}
        qlist = pattern.get("questions") if isinstance(pattern, dict) else None
        qco: dict[str, tuple[CourseOutcome, float]] = {}
        for q in qlist or []:
            if isinstance(q, dict) and q.get("co") and str(q["co"]).upper() in co_by_code:
                qco[str(q.get("q"))] = (co_by_code[str(q["co"]).upper()], float(q.get("max") or 0))
        strategy = str(cfg.get("ese_apportion_strategy") or "question_wise")
        label = f"ESE {paper.paper_code or ''}".strip()

        if strategy == "question_wise" and qco and script_of:
            vals = (
                (
                    await self.db.execute(
                        select(ScriptValuation)
                        .where(
                            ScriptValuation.answer_script_id.in_(list(script_of)),
                            ScriptValuation.question_wise.is_not(None),
                        )
                        .order_by(ScriptValuation.answer_script_id, desc(ScriptValuation.valuation_round))
                    )
                )
                .scalars()
                .all()
            )
            latest: dict[uuid.UUID, ScriptValuation] = {}
            for v in vals:
                latest.setdefault(v.answer_script_id, v)
            if latest:
                per_co: dict[uuid.UUID, dict[uuid.UUID, float]] = defaultdict(dict)
                co_max: dict[uuid.UUID, float] = defaultdict(float)
                for _q, (co, mx) in qco.items():
                    co_max[co.id] += mx
                for sid, v in latest.items():
                    e = script_of[sid]
                    raw = float(v.marks) or 0.0
                    scale = (totals.get(e, raw) / raw) if raw else 1.0  # moderation / third round → final marks
                    for q, (co, _mx) in qco.items():
                        try:
                            per_co[co.id][e] = (
                                per_co[co.id].get(e, 0.0) + float((v.question_wise or {}).get(q) or 0) * scale
                            )
                        except (TypeError, ValueError):
                            continue
                for co_id, marks in per_co.items():
                    tally(co_id, label, "ese", "question_wise", co_max[co_id], marks, 1.0)
                return
        weights: dict[uuid.UUID, float] = {}
        cw = pattern.get("co_weights") if isinstance(pattern, dict) else None
        if isinstance(cw, dict):
            for code, w in cw.items():
                if str(code).upper() in co_by_code:
                    weights[co_by_code[str(code).upper()].id] = float(w)
        if not weights and qco:
            for co, mx in qco.values():
                weights[co.id] = weights.get(co.id, 0.0) + mx
        source = "qp_pattern"
        if not weights or strategy == "uniform":
            weights = {c.id: 1.0 for c in cos}
            source = "uniform"
            warnings.append("ESE_UNIFORM_APPORTION")
        wsum = sum(weights.values()) or 1.0
        for co_id, w in weights.items():
            share = w / wsum
            tally(co_id, label, "ese", source, pmax * share, {e: t * share for e, t in totals.items()}, 1.0)

    async def _course_exit_survey(self, o: CourseOffering, survey_id: uuid.UUID | None) -> FeedbackSurvey | None:
        q = select(FeedbackSurvey).where(
            FeedbackSurvey.institution_id == self.inst, FeedbackSurvey.survey_type == "course_exit"
        )
        if survey_id is not None:
            q = q.where(FeedbackSurvey.id == survey_id)
        else:
            q = q.where(
                FeedbackSurvey.id.in_(select(FeedbackResponse.survey_id).where(FeedbackResponse.target_id == o.id))
            ).order_by((FeedbackSurvey.term_id == o.term_id).desc(), FeedbackSurvey.created_at.desc())
        return (await self.db.execute(q.limit(1))).scalars().first()

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def latest_run(self, offering_id: uuid.UUID, *, computed: bool = True) -> AttainmentRun | None:
        q = select(AttainmentRun).where(
            AttainmentRun.institution_id == self.inst,
            AttainmentRun.scope_type == "offering",
            AttainmentRun.scope_id == offering_id,
        )
        if computed:
            q = q.where(AttainmentRun.status == "computed")
        return (await self.db.execute(q.order_by(AttainmentRun.run_at.desc()).limit(1))).scalar_one_or_none()

    async def get(self, offering_id: uuid.UUID, run_id: uuid.UUID | None = None) -> CoAttainmentResponse:
        o = await self.att_offering(offering_id)
        if run_id is not None:
            run = (
                await self.db.execute(
                    select(AttainmentRun).where(AttainmentRun.id == run_id, AttainmentRun.scope_id == o.id)
                )
            ).scalar_one_or_none()
            if run is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Run not found")
        else:
            run = await self.latest_run(o.id)
        out = CoAttainmentResponse(
            offering=await self.offering_ref(o), run=run_summary(run), prerequisites=await self.prerequisites(o)
        )
        if run is None:
            last = await self.latest_run(o.id, computed=False)
            out.run = run_summary(last)
            return out
        rows = (
            await self.db.execute(
                select(CoAttainment, CourseOutcome)
                .join(CourseOutcome, CourseOutcome.id == CoAttainment.course_outcome_id)
                .where(CoAttainment.run_id == run.id)
                .order_by(CourseOutcome.sequence, CourseOutcome.code)
            )
        ).all()
        out.cos = [
            CoRow(
                co_id=co.id,
                co=co.code,
                statement=co.statement,
                students_assessed=r.students_assessed,
                students_above_target=r.students_above_target,
                direct_pct=f2(r.direct_pct),
                cia_level=f2(r.cia_level),
                ese_level=f2(r.ese_level),
                direct_level=f2(r.direct_level),
                indirect_level=f2(r.indirect_level),
                final_level=f2(r.final_level),
                target=f2(r.target_level),
                gap=f2(r.gap),
                breakdown=(r.breakdown or {}).get("parts") or [],
            )
            for r, co in rows
        ]
        return out

    async def runs(self, offering_id: uuid.UUID) -> list[RunSummary]:
        o = await self.att_offering(offering_id)
        rows = (
            (
                await self.db.execute(
                    select(AttainmentRun)
                    .where(AttainmentRun.scope_type == "offering", AttainmentRun.scope_id == o.id)
                    .order_by(AttainmentRun.run_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        return [s for s in (run_summary(r) for r in rows) if s is not None]

    async def heatmap(self, offering_id: uuid.UUID) -> CoPoHeatmap:
        """CO × assessment levels from the latest computed run (Phase 13 preview promoted to computed values)."""
        data = await self.get(offering_id)
        columns: list[str] = []
        for c in data.cos:
            for p in c.breakdown:
                if p["assessment"] not in columns:
                    columns.append(p["assessment"])
        columns += ["Direct", "Final"]
        cells = []
        for c in data.cos:
            by = {p["assessment"]: float(p["level"]) for p in c.breakdown}
            cells.append([by.get(col) for col in columns[:-2]] + [c.direct_level, c.final_level])
        return CoPoHeatmap(
            rows=[c.co for c in data.cos], columns=columns, cells=cells, row_ids=[str(c.co_id) for c in data.cos]
        )

    async def _achievement(
        self, o: CourseOffering, run: AttainmentRun | None, enrol_ids: set[uuid.UUID] | None
    ) -> list[StudentCoAchievement]:
        ref = await self.offering_ref(o)
        if run is None:
            return []
        snap = run.config_snapshot or {}
        target = float(snap.get("target_marks_pct") or 60) / 100
        cos = (
            (
                await self.db.execute(
                    select(CourseOutcome).where(CourseOutcome.course_id == o.course_id).order_by(CourseOutcome.sequence)
                )
            )
            .scalars()
            .all()
        )
        cache = snap.get("_students") or {}
        ids = [uuid.UUID(e) for e in cache if enrol_ids is None or uuid.UUID(e) in enrol_ids]
        names = {
            r[0]: r[1:]
            for r in (
                await self.db.execute(
                    select(
                        StudentProgramEnrollment.id, Student.first_name, Student.last_name, Student.registration_number
                    )
                    .join(Student, Student.id == StudentProgramEnrollment.student_id)
                    .where(StudentProgramEnrollment.id.in_(ids or [uuid.uuid4()]))
                )
            ).all()
        }
        out = []
        for e in ids:
            per = cache.get(str(e)) or {}
            items = []
            for c in cos:
                mm = per.get(str(c.id))
                pct = (mm[0] / mm[1] * 100) if mm and mm[1] else None
                items.append(
                    StudentCoItem(
                        co=c.code,
                        statement=c.statement,
                        marks_pct=round(pct, 2) if pct is not None else None,
                        above_target=(pct >= target * 100 - 1e-9) if pct is not None else None,
                    )
                )
            n = names.get(e)
            out.append(
                StudentCoAchievement(
                    offering=ref,
                    student_program_enrollment_id=e,
                    student_name=" ".join(x for x in (n[0], n[1]) if x) if n else None,
                    registration_number=n[2] if n else None,
                    cos=items,
                )
            )
        return sorted(out, key=lambda x: x.registration_number or "")

    async def student_achievement(self, offering_id: uuid.UUID) -> list[StudentCoAchievement]:
        o = await self.att_offering(offering_id)
        return await self._achievement(o, await self.latest_run(o.id), None)

    async def me(self, offering_id: uuid.UUID) -> StudentCoAchievement:
        if not await self.setting("obe", "show_students"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Course outcome achievement is not shared with students")
        o = await self.offering(offering_id, "marks")
        enrol = await self.learner_enrolment(o)
        rows = await self._achievement(o, await self.latest_run(o.id), {enrol})
        if not rows:
            raise APIError(404, ErrorCode.NOT_FOUND, "No attainment computed for this offering yet")
        return rows[0]

    async def indirect_summary(self, survey_id: uuid.UUID) -> IndirectSurveySummary:
        s = (
            await self.db.execute(
                select(FeedbackSurvey).where(FeedbackSurvey.id == survey_id, FeedbackSurvey.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Survey not found")
        answers = (
            (await self.db.execute(select(FeedbackResponse.answers).where(FeedbackResponse.survey_id == s.id)))
            .scalars()
            .all()
        )
        by_co, n = survey_means(s.questions, list(answers), "co")
        by_out, _ = survey_means(s.questions, list(answers), "outcome")
        cfg = await AttainmentConfigService(self.db, self.principal, self.request, self.inst).platform_defaults()
        th = cfg.get("survey_thresholds") or []
        return IndirectSurveySummary(
            survey={"id": str(s.id), "title": s.title, "type": s.survey_type, "status": s.status},
            responses=n,
            mean_by_co={k: round(v, 2) for k, v in by_co.items()},
            mean_by_outcome={k: round(v, 2) for k, v in by_out.items()},
            levels={k: survey_level(v, th) for k, v in {**by_co, **by_out}.items()},
        )

    # ---- term recompute / auto-run ------------------------------------------------------------------------------------
    async def offerings_of_term(self, term_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            (
                await self.db.execute(
                    select(CourseOffering.id).where(
                        CourseOffering.institution_id == self.inst,
                        CourseOffering.term_id == term_id,
                        CourseOffering.deleted_at.is_(None),
                        CourseOffering.status != "cancelled",
                    )
                )
            )
            .scalars()
            .all()
        )

    async def offerings_of_result_run(self, result_run_id: uuid.UUID) -> list[uuid.UUID]:
        return [
            x
            for x in (
                await self.db.execute(
                    select(StudentCourseResult.offering_id)
                    .where(StudentCourseResult.run_id == result_run_id, StudentCourseResult.offering_id.is_not(None))
                    .distinct()
                )
            )
            .scalars()
            .all()
            if x is not None
        ]

    async def run_many(
        self, offering_ids: list[uuid.UUID], include_indirect: bool = True, *, force: bool = False
    ) -> dict[str, int]:
        done = failed = 0
        for oid in offering_ids:
            res = await self.request_run(oid, CoRunRequest(include_indirect=include_indirect), inline=True, force=force)
            if res.status == "computed":
                done += 1
            else:
                failed += 1
        return {"computed": done, "skipped": failed}
