"""PO / PSO attainment per programme-batch, dashboard and gap list — Prompts/17 §17.6 ``po_attainment_service``.

Contributing courses = curriculum courses of the batch's programme-regulation up to ``term_upto`` (default the batch's
current term) that map to a PO / PSO and have a computed CO run for an offering targeted at the batch
(``course_offering_targets.batch_id``; latest run wins). Per course and outcome:
``contribution = Σ_CO (CO_final × map_level) / Σ_CO map_level``; programme direct = mean over contributing courses
(credit-weighted when the config says so). Indirect: programme-exit / alumni / employer surveys whose responses target
the programme (``target_type='program'``) and whose questions are tagged ``outcome_id`` / ``outcome`` (code) → mean →
level by the survey thresholds (averaged across surveys). ``final = (direct_w × direct + indirect_w × indirect) / 100``
(direct only without indirect, ``NO_INDIRECT``); ``gap = po_target − final``. Coverage < 60 % of the mapped courses →
``INSUFFICIENT_COVERAGE``. PEO attainment is derived through ``peo_po_mappings`` (level-weighted mean of PO finals) and
reported, not stored.
"""

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.models.academic import Batch, Program
from app.models.curriculum import Course, CurriculumCourse
from app.models.obe import CoPoMapping, CourseOutcome, OutcomeDefinition, PeoPoMapping
from app.models.obe_attainment import (
    AttainmentRun,
    CoAttainment,
    CqiAction,
    FeedbackResponse,
    FeedbackSurvey,
    PoAttainment,
    PoBreakdown,
)
from app.models.offerings import CourseOffering, CourseOfferingTarget
from app.repositories.attainment_scope import offering_predicate
from app.schemas.obe_attainment import (
    CoPoHeatmap,
    DashboardResponse,
    GapListRow,
    PeoRow,
    PoAttainmentResponse,
    PoRow,
    PoRunRequest,
    ProgramAttainmentTrend,
    RunResponse,
    TrendBatch,
)
from app.services.obe.co_service import survey_means
from app.services.obe.common import ObeBase, d2, f2, run_summary, survey_level
from app.services.obe.config_service import AttainmentConfigService

PO_SURVEYS = ("program_exit", "alumni", "employer")


def suggest(outcome: str, gap: float) -> str:
    if gap >= 1:
        return f"Revise delivery and assessment design for {outcome}: add targeted activities and re-map questions"
    if gap >= 0.5:
        return f"Add remedial sessions / assignments addressing {outcome} and review question-to-outcome mapping"
    return f"Reinforce {outcome} with additional practice and monitor in the next cycle"


class PoAttainmentService(ObeBase):
    async def outcomes(self, program: Program) -> list[OutcomeDefinition]:
        rows = (
            (
                await self.db.execute(
                    select(OutcomeDefinition)
                    .where(
                        OutcomeDefinition.institution_id == self.inst,
                        OutcomeDefinition.is_active.is_(True),
                        OutcomeDefinition.outcome_type.in_(("PO", "PSO", "PEO")),
                        or_(
                            (OutcomeDefinition.scope_type == "program") & (OutcomeDefinition.scope_id == program.id),
                            OutcomeDefinition.scope_type == "institution",
                        ),
                    )
                    .order_by(OutcomeDefinition.outcome_type, OutcomeDefinition.sequence, OutcomeDefinition.code)
                )
            )
            .scalars()
            .all()
        )
        prog = [r for r in rows if r.scope_type == "program"]
        return list(prog or rows)

    # ---- request / job ----------------------------------------------------------------------------------------------
    async def request_run(
        self, program_id: uuid.UUID, batch_id: uuid.UUID, body: PoRunRequest, *, inline: bool = False
    ) -> RunResponse:
        program = await self.att_program(program_id) if self.principal is not None else await self._program(program_id)
        batch = await self.batch_of(program, batch_id)
        if self.principal is not None and not (self.can("obe", "compute") or self.can("obe", "manage")):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "obe:compute required")
        run = AttainmentRun(
            institution_id=self.inst,
            scope_type="program_batch",
            scope_id=program.id,
            batch_id=batch.id,
            status="queued",
            run_by=self.actor_id,
            config_snapshot={"_request": body.model_dump(mode="json")},
        )
        self.db.add(run)
        await self.db.flush()
        if inline:
            await self.compute(run.id)
        else:
            from app.core.jobs import enqueue

            job = await enqueue(self.db, self.principal, "obe.po_run", {"run_id": str(run.id)})
            run.job_id = job.id
        await self.db.flush()
        snap = run.config_snapshot or {}
        return RunResponse(
            run_id=run.id,
            job_id=run.job_id,
            scope_type="program_batch",
            scope_id=program.id,
            status=run.status,
            config_snapshot={k: v for k, v in snap.items() if not k.startswith("_")} or None,
            computed_at=run.run_at if run.status == "computed" else None,
            warnings=list(snap.get("_warnings") or []),
        )

    async def _program(self, program_id: uuid.UUID) -> Program:
        row = (
            await self.db.execute(select(Program).where(Program.id == program_id, Program.institution_id == self.inst))
        ).scalar_one_or_none()
        if row is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Programme not found")
        return row

    # ---- compute ----------------------------------------------------------------------------------------------------
    async def compute(self, run_id: uuid.UUID) -> AttainmentRun:  # noqa: C901, PLR0912, PLR0915 - one formula
        run = (await self.db.execute(select(AttainmentRun).where(AttainmentRun.id == run_id))).scalar_one()
        program = await self._program(run.scope_id)
        batch = (await self.db.execute(select(Batch).where(Batch.id == run.batch_id))).scalar_one()
        req = (run.config_snapshot or {}).get("_request") or {}
        cfg = await AttainmentConfigService(self.db, self.principal, self.request, self.inst).effective(
            program.id, batch_id=batch.id
        )
        warnings: list[str] = []
        term_upto = int(req.get("term_upto") or batch.current_term_number or 99)
        outcomes = [x for x in await self.outcomes(program) if x.outcome_type in ("PO", "PSO")]
        out_ids = {x.id for x in outcomes}
        if not outcomes:
            run.status = "failed"
            run.config_snapshot = {**cfg, "_request": req, "_warnings": ["NO_PROGRAM_OUTCOMES"]}
            await self.db.flush()
            return run
        curriculum = (
            await self.db.execute(
                select(CurriculumCourse.course_id, Course.code, Course.title, Course.credits)
                .join(Course, Course.id == CurriculumCourse.course_id)
                .where(
                    CurriculumCourse.program_regulation_id == batch.program_regulation_id,
                    CurriculumCourse.term_number <= term_upto,
                )
                .distinct()
            )
        ).all()
        course_meta = {r[0]: (r[1], r[2], float(r[3] or 0)) for r in curriculum}
        maps = (
            await self.db.execute(
                select(
                    CourseOutcome.course_id, CoPoMapping.course_outcome_id, CoPoMapping.outcome_id, CoPoMapping.level
                )
                .join(CourseOutcome, CourseOutcome.id == CoPoMapping.course_outcome_id)
                .where(
                    CourseOutcome.course_id.in_(list(course_meta) or [uuid.uuid4()]),
                    CoPoMapping.outcome_id.in_(out_ids),
                )
            )
        ).all()
        mapped_courses = {m[0] for m in maps}
        # latest computed CO run per course among the batch's offerings
        runs = (
            await self.db.execute(
                select(AttainmentRun.id, AttainmentRun.scope_id, CourseOffering.course_id, AttainmentRun.run_at)
                .join(CourseOffering, CourseOffering.id == AttainmentRun.scope_id)
                .join(CourseOfferingTarget, CourseOfferingTarget.offering_id == CourseOffering.id)
                .where(
                    AttainmentRun.scope_type == "offering",
                    AttainmentRun.status == "computed",
                    CourseOfferingTarget.batch_id == batch.id,
                    CourseOffering.course_id.in_(list(mapped_courses) or [uuid.uuid4()]),
                )
                .order_by(AttainmentRun.run_at.desc())
            )
        ).all()
        latest: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID]] = {}
        for rid, oid, cid, _at in runs:
            latest.setdefault(cid, (rid, oid))
        co_final: dict[uuid.UUID, tuple[float | None, str]] = {}
        if latest:
            for co_id, final, code in (
                await self.db.execute(
                    select(CoAttainment.course_outcome_id, CoAttainment.final_level, CourseOutcome.code)
                    .join(CourseOutcome, CourseOutcome.id == CoAttainment.course_outcome_id)
                    .where(CoAttainment.run_id.in_([r for r, _ in latest.values()]))
                )
            ).all():
                co_final[co_id] = (float(final) if final is not None else None, code)
        coverage = (len(latest) / len(mapped_courses) * 100) if mapped_courses else 0.0
        if coverage < 60:
            warnings.append("INSUFFICIENT_COVERAGE")

        # contribution per (course, outcome)
        per: dict[uuid.UUID, dict[uuid.UUID, dict[str, Any]]] = defaultdict(dict)  # outcome -> course -> data
        for cid, co_id, oid, level in maps:
            if cid not in latest:
                continue
            final, code = co_final.get(co_id, (None, "?"))
            if final is None:
                continue
            d = per[oid].setdefault(cid, {"num": 0.0, "den": 0.0, "cos": []})
            d["num"] += final * level
            d["den"] += level
            d["cos"].append({"co": code, "final": round(final, 2), "map_level": level})

        # indirect
        indirect: dict[uuid.UUID, float] = {}
        surveys_used: list[dict[str, Any]] = []
        if req.get("include_indirect", True) and await is_enabled(self.inst, "obe.indirect_surveys"):
            surveys = (
                (
                    await self.db.execute(
                        select(FeedbackSurvey).where(
                            FeedbackSurvey.institution_id == self.inst,
                            FeedbackSurvey.survey_type.in_(PO_SURVEYS),
                            FeedbackSurvey.id.in_(
                                select(FeedbackResponse.survey_id).where(FeedbackResponse.target_id == program.id)
                            ),
                        )
                    )
                )
                .scalars()
                .all()
            )
            levels: dict[uuid.UUID, list[int]] = defaultdict(list)
            by_code = {x.code.upper(): x for x in outcomes}
            for s in surveys:
                answers = (
                    (
                        await self.db.execute(
                            select(FeedbackResponse.answers).where(
                                FeedbackResponse.survey_id == s.id, FeedbackResponse.target_id == program.id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                means, n = survey_means(s.questions, list(answers), "outcome")
                for tag, mean in means.items():
                    o = by_code.get(tag.upper()) or next((x for x in outcomes if str(x.id) == tag), None)
                    if o is not None:
                        levels[o.id].append(survey_level(mean, cfg.get("survey_thresholds") or []))
                surveys_used.append({"id": str(s.id), "type": s.survey_type, "title": s.title, "responses": n})
            indirect = {k: sum(v) / len(v) for k, v in levels.items() if v}
        if not indirect:
            warnings.append("NO_INDIRECT")

        dw, iw = float(cfg["direct_weight"]), float(cfg["indirect_weight"])
        target = float(cfg["po_target_level"])
        credit_weighted = bool(cfg.get("credit_weighted_po"))
        gaps = []
        for o in outcomes:
            contribs = []
            for cid, d in per.get(o.id, {}).items():
                if d["den"] <= 0:
                    continue
                meta = course_meta.get(cid, ("?", "", 0.0))
                contribs.append(
                    PoBreakdown(
                        course_id=str(cid),
                        course_code=meta[0],
                        offering_id=str(latest[cid][1]),
                        cos=d["cos"],
                        contribution=round(d["num"] / d["den"], 2),
                        credits=meta[2],
                    )
                )
            if contribs:
                if credit_weighted and sum(c.credits for c in contribs) > 0:
                    direct: float | None = sum(c.contribution * c.credits for c in contribs) / sum(
                        c.credits for c in contribs
                    )
                else:
                    direct = sum(c.contribution for c in contribs) / len(contribs)
            else:
                direct = None
            ind = indirect.get(o.id)
            if direct is None:
                final = ind
            else:
                final = (dw * direct + iw * ind) / 100 if ind is not None else direct
            gap = None if final is None else target - final
            self.db.add(
                PoAttainment(
                    institution_id=self.inst,
                    program_id=program.id,
                    batch_id=batch.id,
                    outcome_id=o.id,
                    run_id=run.id,
                    direct_level=d2(direct),
                    indirect_level=d2(ind),
                    final_level=d2(final),
                    target_level=d2(target),
                    gap=d2(gap),
                    contributing_courses=len(contribs),
                    breakdown={"courses": [c.model_dump() for c in contribs]},
                )
            )
            if gap is not None and gap > 0:
                gaps.append({"outcome": o.code, "gap": round(gap, 2)})
        run.status = "computed"
        run.config_snapshot = {
            **cfg,
            "_request": req,
            "_warnings": sorted(set(warnings)),
            "_coverage_pct": round(coverage, 2),
            "_mapped_courses": len(mapped_courses),
            "_courses_with_runs": len(latest),
            "_surveys": surveys_used,
            "_term_upto": term_upto,
        }
        await self.db.flush()
        await self._emit(
            "obe.po_attainment_computed",
            {"run_id": str(run.id), "program_id": str(program.id), "batch_id": str(batch.id), "gaps": gaps},
            "attainment_run",
            run.id,
        )
        if gaps:
            await self._emit(
                "obe.gap_detected",
                {"scope": "program", "scope_id": str(program.id), "batch_id": str(batch.id), "gaps": gaps},
                "attainment_run",
                run.id,
            )
            await self._notify(
                "obe.gap_detected",
                [],
                {"scope": f"{program.code} {batch.code}", "count": str(len(gaps))},
                audience={"roles": ["hod", "obe_coordinator"]},
            )
        return run

    # ---- reads ------------------------------------------------------------------------------------------------------
    async def latest_run(self, program_id: uuid.UUID, batch_id: uuid.UUID) -> AttainmentRun | None:
        return (
            await self.db.execute(
                select(AttainmentRun)
                .where(
                    AttainmentRun.institution_id == self.inst,
                    AttainmentRun.scope_type == "program_batch",
                    AttainmentRun.scope_id == program_id,
                    AttainmentRun.batch_id == batch_id,
                    AttainmentRun.status == "computed",
                )
                .order_by(AttainmentRun.run_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def get(self, program_id: uuid.UUID, batch_id: uuid.UUID) -> PoAttainmentResponse:
        program = await self.att_program(program_id)
        batch = await self.batch_of(program, batch_id)
        run = await self.latest_run(program.id, batch.id)
        out = PoAttainmentResponse(program=self.program_ref(program), batch=self.batch_ref(batch), run=run_summary(run))
        if run is None:
            return out
        out.coverage_pct = (run.config_snapshot or {}).get("_coverage_pct")
        rows = (
            await self.db.execute(
                select(PoAttainment, OutcomeDefinition)
                .join(OutcomeDefinition, OutcomeDefinition.id == PoAttainment.outcome_id)
                .where(PoAttainment.run_id == run.id)
                .order_by(OutcomeDefinition.outcome_type, OutcomeDefinition.sequence, OutcomeDefinition.code)
            )
        ).all()
        out.outcomes = [
            PoRow(
                outcome_id=o.id,
                outcome=o.code,
                outcome_type=o.outcome_type,
                statement=o.statement,
                direct=f2(r.direct_level),
                indirect=f2(r.indirect_level),
                final=f2(r.final_level),
                target=f2(r.target_level),
                gap=f2(r.gap),
                contributing_courses=r.contributing_courses,
                breakdown=(r.breakdown or {}).get("courses") or [],
            )
            for r, o in rows
        ]
        finals = {r.outcome_id: f2(r.final_level) for r, _ in rows}
        peos = [x for x in await self.outcomes(program) if x.outcome_type == "PEO"]
        if peos:
            links = (
                await self.db.execute(
                    select(PeoPoMapping.peo_id, PeoPoMapping.po_id, PeoPoMapping.level).where(
                        PeoPoMapping.peo_id.in_([p.id for p in peos])
                    )
                )
            ).all()
            code = {o.id: o.code for _, o in rows}
            for p in peos:
                num = den = 0.0
                via = []
                for peo_id, po_id, lvl in links:
                    if peo_id == p.id and finals.get(po_id) is not None:
                        num += float(finals[po_id]) * lvl  # type: ignore[arg-type]
                        den += lvl
                        via.append(code.get(po_id, "?"))
                out.peos.append(
                    PeoRow(outcome_id=p.id, outcome=p.code, level=round(num / den, 2) if den else None, via=via)
                )
        return out

    async def trend(self, program_id: uuid.UUID) -> ProgramAttainmentTrend:
        program = await self.att_program(program_id)
        batches = (
            (await self.db.execute(select(Batch).where(Batch.program_id == program.id).order_by(Batch.admission_year)))
            .scalars()
            .all()
        )
        codes: list[str] = []
        out: list[TrendBatch] = []
        for b in batches:
            run = await self.latest_run(program.id, b.id)
            if run is None:
                continue
            rows = (
                await self.db.execute(
                    select(OutcomeDefinition.code, PoAttainment.final_level)
                    .join(OutcomeDefinition, OutcomeDefinition.id == PoAttainment.outcome_id)
                    .where(PoAttainment.run_id == run.id)
                    .order_by(OutcomeDefinition.outcome_type, OutcomeDefinition.sequence)
                )
            ).all()
            for c, _ in rows:
                if c not in codes:
                    codes.append(c)
            out.append(TrendBatch(batch=self.batch_ref(b), run_at=run.run_at, outcomes={c: f2(v) for c, v in rows}))
        return ProgramAttainmentTrend(program=self.program_ref(program), outcomes=codes, batches=out)

    async def heatmap(self, program_id: uuid.UUID, batch_id: uuid.UUID) -> CoPoHeatmap:
        data = await self.get(program_id, batch_id)
        columns = [o.outcome for o in data.outcomes]
        courses: dict[str, dict[str, float]] = {}
        ids: dict[str, str] = {}
        for o in data.outcomes:
            for c in o.breakdown:
                courses.setdefault(c["course_code"], {})[o.outcome] = c["contribution"]
                ids[c["course_code"]] = c["course_id"]
        rows = sorted(courses)
        return CoPoHeatmap(
            rows=rows,
            columns=columns,
            cells=[[courses[r].get(c) for c in columns] for r in rows],
            row_ids=[ids[r] for r in rows],
        )

    async def gaps(self, program_id: uuid.UUID, batch_id: uuid.UUID | None, threshold: float = 0.0) -> list[GapListRow]:
        program = await self.att_program(program_id)
        out: list[GapListRow] = []
        counts = await self._open_action_counts()
        batches = (
            [batch_id]
            if batch_id
            else list((await self.db.execute(select(Batch.id).where(Batch.program_id == program.id))).scalars().all())
        )
        for bid in batches:
            run = await self.latest_run(program.id, bid)
            if run is None:
                continue
            for r, o in (
                await self.db.execute(
                    select(PoAttainment, OutcomeDefinition)
                    .join(OutcomeDefinition, OutcomeDefinition.id == PoAttainment.outcome_id)
                    .where(PoAttainment.run_id == run.id, PoAttainment.gap > threshold)
                )
            ).all():
                out.append(
                    GapListRow(
                        scope="program",
                        scope_id=program.id,
                        label=f"{program.code}",
                        outcome=o.code,
                        outcome_id=o.id,
                        final=f2(r.final_level),
                        target=f2(r.target_level),
                        gap=float(r.gap),
                        suggested_action=suggest(o.code, float(r.gap)),
                        open_actions=counts.get((program.id, o.id), 0),
                    )
                )
        # CO gaps of the batch's (or programme's) offerings — latest computed run each
        offering_q = (
            select(CourseOffering.id, Course.code, CourseOffering.section_code)
            .join(Course, Course.id == CourseOffering.course_id)
            .join(CourseOfferingTarget, CourseOfferingTarget.offering_id == CourseOffering.id)
            .join(Batch, Batch.id == CourseOfferingTarget.batch_id)
            .where(Batch.program_id == program.id, offering_predicate(self.principal))
            .distinct()
        )
        if batch_id:
            offering_q = offering_q.where(CourseOfferingTarget.batch_id == batch_id)
        for oid, code, section in (await self.db.execute(offering_q)).all():
            co_run = (
                await self.db.execute(
                    select(AttainmentRun.id)
                    .where(
                        AttainmentRun.scope_type == "offering",
                        AttainmentRun.scope_id == oid,
                        AttainmentRun.status == "computed",
                    )
                    .order_by(AttainmentRun.run_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if co_run is None:
                continue
            for r, co in (
                await self.db.execute(
                    select(CoAttainment, CourseOutcome)
                    .join(CourseOutcome, CourseOutcome.id == CoAttainment.course_outcome_id)
                    .where(CoAttainment.run_id == co_run, CoAttainment.gap > threshold)
                )
            ).all():
                out.append(
                    GapListRow(
                        scope="offering",
                        scope_id=oid,
                        label=f"{code} {section}",
                        outcome=co.code,
                        co_id=co.id,
                        final=f2(r.final_level),
                        target=f2(r.target_level),
                        gap=float(r.gap),
                        suggested_action=suggest(f"{code} {co.code}", float(r.gap)),
                        open_actions=counts.get((oid, None), 0),
                    )
                )
        return sorted(out, key=lambda g: -g.gap)

    async def _open_action_counts(self) -> dict[tuple[uuid.UUID, uuid.UUID | None], int]:
        rows = (
            await self.db.execute(
                select(CqiAction.scope_id, CqiAction.outcome_id, func.count())
                .where(CqiAction.institution_id == self.inst, CqiAction.status != "verified")
                .group_by(CqiAction.scope_id, CqiAction.outcome_id)
            )
        ).all()
        out: dict[tuple[uuid.UUID, uuid.UUID | None], int] = {}
        for sid, oid, n in rows:
            out[(sid, oid)] = int(n)
            out[(sid, None)] = out.get((sid, None), 0) + int(n)
        return out

    async def dashboard(self, program_id: uuid.UUID, batch_id: uuid.UUID) -> DashboardResponse:
        data = await self.get(program_id, batch_id)
        heat = await self.heatmap(program_id, batch_id)
        gaps = await self.gaps(program_id, batch_id, 0.0)
        cqi: dict[Any, Any] = dict(
            (
                await self.db.execute(
                    select(CqiAction.status, func.count())
                    .where(
                        CqiAction.institution_id == self.inst,
                        CqiAction.scope_type == "program",
                        CqiAction.scope_id == program_id,
                    )
                    .group_by(CqiAction.status)
                )
            ).all()  # type: ignore[arg-type]
        )
        return DashboardResponse(
            program=data.program,
            batch=data.batch,
            radar=[{"outcome": o.outcome, "final": o.final, "target": o.target} for o in data.outcomes],
            heatmap=heat,
            gaps=gaps,
            coverage_pct=data.coverage_pct,
            direct_vs_indirect=[
                {"outcome": o.outcome, "direct": o.direct, "indirect": o.indirect} for o in data.outcomes
            ],
            cqi={str(k): int(v) for k, v in cqi.items()},
            run=data.run,
        )

    async def batches_for_recompute(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
        return [
            (p, b)
            for p, b in (
                await self.db.execute(
                    select(Batch.program_id, Batch.id).where(
                        Batch.institution_id == self.inst, Batch.status.in_(("active", "graduating", "graduated"))
                    )
                )
            ).all()
        ]
