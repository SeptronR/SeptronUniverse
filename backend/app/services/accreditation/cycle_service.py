"""Accreditation cycles & criterion responses — Prompts/32 §32.6 ``cycle_service`` (and ``cycle_repository``).

1. Cycles per framework (NAAC institutional {accreditation.iqac_cycles}; NBA per programme with ``program_id``
   {accreditation.nba}; AQAR yearly) with the forward-only machine ``planning → data_collection → drafting →
   internal_review → submitted → peer_visit → result`` (score / grade at ``result``); moving to ``submitted`` makes
   every response ``final`` (immutable).
2. Criterion responses — one per (cycle, criterion) (UNIQUE): narrative with the framework word limit, linked
   ``metric_value_ids`` auto-filled from the criterion's ``metric_key`` for the cycle period (NBA criteria 3–4 read the
   Phase 17 attainment keys ``obe.co_attainment`` / ``obe.po_attainment``), ``evidence_ids``; assignment with due dates
   (``accreditation.response_assigned``); submission starts the ``accreditation.response_review`` workflow (owner's HOD
   → IQAC → principal) whose approval marks the response ``approved``; versions on every save; best practices (7.2.1)
   and distinctiveness (7.3.1) are structured responses. An approved / final response is locked for its owner (409).
3. Exports (job) through ``export_service``.

Visibility: IQAC / institution readers all; ``college_admin`` their college's cycles; HOD cycles of their programmes
and the responses owned by their department's staff; faculty the responses they own (others → 404).
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.enums.accreditation import CYCLE_FLOW, WORD_LIMITS
from app.models.accreditation import (
    AccreditationCycle,
    AccreditationFramework,
    CriterionResponse,
    FrameworkCriterion,
    MetricValue,
)
from app.models.hr import Staff
from app.models.platform import WorkflowInstance
from app.schemas.accreditation import (
    BestPracticeIn,
    CriterionResponseIn,
    CriterionResponseOut,
    CycleIn,
    CycleOut,
    CycleStatusChange,
    CycleUpdate,
    DistinctivenessIn,
    ResponseAssign,
    ResponseReview,
    ResponseVersion,
)
from app.services.accreditation.common import AccreditationBase, forbidden, not_found, now_utc, rule, word_count

WF_KEY = "accreditation.response_review"
ENTITY = "criterion_response"
BEST_PRACTICE, DISTINCTIVENESS = "7.2.1", "7.3.1"


def cycle_period_label(c: AccreditationCycle) -> str | None:
    """NAAC window ``2020-25`` (multi-year), else the academic year of ``period_from`` (``2025-26``)."""
    if c.period_from is None:
        return None
    start = c.period_from.year
    end = c.period_to.year if c.period_to else start + 1
    if end - start > 1:
        return f"{start}-{str(end)[-2:]}"
    return f"{start}-{str(start + 1)[-2:]}"


class CycleService(AccreditationBase):
    # ---- visibility -----------------------------------------------------------------------------------------------------
    def require_reader(self) -> None:
        if not (self.can(self.module, "view") or self.can(self.module, "view_all") or self.can(self.module, "manage")):
            raise forbidden("accreditation:view required")

    async def _cycle_predicate(self) -> Any:
        from sqlalchemy import false, true

        if self.reader_all():
            return true()
        parts: list[Any] = []
        if self.college_ids():
            parts.append(AccreditationCycle.college_id.in_(self.college_ids() or []))
        depts = await self.resolved_dept_ids()
        if depts:
            parts.append(AccreditationCycle.program_id.in_(await self.dept_program_ids(depts) or [uuid.uuid4()]))
            owners = await self.dept_staff_ids(depts)
            parts.append(
                AccreditationCycle.id.in_(
                    select(CriterionResponse.cycle_id).where(
                        CriterionResponse.owner_staff_id.in_(owners or [uuid.uuid4()])
                    )
                )
            )
        me = await self.my_staff_id()
        if me:
            parts.append(
                AccreditationCycle.id.in_(
                    select(CriterionResponse.cycle_id).where(CriterionResponse.owner_staff_id == me)
                )
            )
            parts.append(AccreditationCycle.coordinator_staff_id == me)
        if "obe_coordinator" in self.roles():
            parts.append(AccreditationCycle.program_id.is_not(None))
        return or_(*parts) if parts else false()

    async def _response_visible(self, r: CriterionResponse | None, cycle: AccreditationCycle) -> bool:
        if self.reader_all() or self.iqac():
            return True
        if self.college_ids() and cycle.college_id in (self.college_ids() or []):
            return True
        if r is None:
            return False
        me = await self.my_staff_id()
        if me and (r.owner_staff_id == me or cycle.coordinator_staff_id == me):
            return True
        depts = await self.resolved_dept_ids()
        if depts and r.owner_staff_id and r.owner_staff_id in await self.dept_staff_ids(depts):
            return True
        return "obe_coordinator" in self.roles() and cycle.program_id is not None

    async def cycle(self, cid: uuid.UUID) -> AccreditationCycle:
        self.require_reader()
        c = (
            await self.db.execute(
                select(AccreditationCycle).where(
                    AccreditationCycle.id == cid,
                    AccreditationCycle.institution_id == self.inst,
                    await self._cycle_predicate(),
                )
            )
        ).scalar_one_or_none()
        if c is None:
            raise not_found("Cycle")
        return c

    async def _feature_for(self, fw: AccreditationFramework) -> None:
        if fw.code == "NBA_UG_ENGG":
            await self.require_feature("accreditation.nba")
        elif fw.code == "NAAC_2024":
            await self.require_feature("accreditation.iqac_cycles")
        else:
            await self.require_framework(fw)

    # ---- outputs ----------------------------------------------------------------------------------------------------------
    async def _leaves(self, framework_id: uuid.UUID) -> list[FrameworkCriterion]:
        rows = await self.criteria(framework_id)
        parents = {r.parent_id for r in rows if r.parent_id}
        leaves = [r for r in rows if r.id not in parents]
        return leaves or rows

    async def out(self, c: AccreditationCycle, codes: dict[uuid.UUID, str] | None = None) -> CycleOut:
        leaves = await self._leaves(c.framework_id)
        statuses: dict[str, int] = {
            str(k): int(v)
            for k, v in (
                await self.db.execute(
                    select(CriterionResponse.status, func.count())
                    .where(CriterionResponse.cycle_id == c.id)
                    .group_by(CriterionResponse.status)
                )
            ).all()
        }
        done = int(statuses.get("approved", 0)) + int(statuses.get("final", 0))
        progress = {
            "total": len(leaves),
            "not_started": max(len(leaves) - sum(int(v) for v in statuses.values()), 0),
            **{k: int(v) for k, v in statuses.items()},
        }
        fw_code = (codes or {}).get(c.framework_id)
        if fw_code is None:
            fw_code = (await self.framework(c.framework_id)).code
        return CycleOut(
            id=c.id,
            framework_id=c.framework_id,
            framework_code=fw_code,
            college_id=c.college_id,
            program_id=c.program_id,
            name=c.name,
            period_from=c.period_from,
            period_to=c.period_to,
            submission_due_on=c.submission_due_on,
            coordinator_staff_id=c.coordinator_staff_id,
            status=c.status,  # type: ignore[arg-type]
            score=c.score,
            grade=c.grade,
            completion_pct=round(100 * done / len(leaves), 1) if leaves else 0.0,
            criteria_progress=progress,
            created_at=c.created_at,
        )

    # ---- cycles -------------------------------------------------------------------------------------------------------------
    async def query(self, framework: str | None = None, status: str | None = None) -> list[CycleOut]:
        self.require_reader()
        stmt = select(AccreditationCycle).where(
            AccreditationCycle.institution_id == self.inst, await self._cycle_predicate()
        )
        if framework:
            stmt = stmt.where(AccreditationCycle.framework_id == (await self.framework(framework)).id)
        if status:
            stmt = stmt.where(AccreditationCycle.status == status)
        rows = list((await self.db.execute(stmt.order_by(AccreditationCycle.created_at.desc()))).scalars().all())
        codes: dict[uuid.UUID, str] = {
            i: str(code)
            for i, code in (await self.db.execute(select(AccreditationFramework.id, AccreditationFramework.code))).all()
        }
        return [await self.out(c, codes) for c in rows]

    async def create(self, body: CycleIn) -> CycleOut:
        self.require_iqac()
        if body.framework_id is None and not body.framework_code:
            raise rule("framework_id or framework_code is required", "FRAMEWORK_REQUIRED", 422)
        fw = await self.framework(body.framework_id or str(body.framework_code))
        await self._feature_for(fw)
        if fw.code == "NBA_UG_ENGG" and body.program_id is None:
            raise rule("An NBA SAR cycle is per programme — program_id is required", "PROGRAM_REQUIRED", 422)
        if body.period_from and body.period_to and body.period_to < body.period_from:
            raise rule("period_to is before period_from", "INVALID_PERIOD", 422)
        c = AccreditationCycle(
            institution_id=self.inst,
            framework_id=fw.id,
            college_id=body.college_id,
            program_id=body.program_id,
            name=body.name,
            period_from=body.period_from,
            period_to=body.period_to,
            submission_due_on=body.submission_due_on,
            coordinator_staff_id=body.coordinator_staff_id,
        )
        self.db.add(c)
        await self.db.flush()
        await self.timeline("cycle", c.id, "created", status="planning")
        await self._audit("cycle_created", "accreditation_cycle", c.id, None, {"name": c.name, "framework": fw.code})
        await self._emit(
            "accreditation.cycle_created", {"cycle_id": str(c.id), "framework": fw.code}, "accreditation_cycle", c.id
        )
        return await self.out(c)

    async def get(self, cid: uuid.UUID) -> CycleOut:
        return await self.out(await self.cycle(cid))

    async def update(self, cid: uuid.UUID, body: CycleUpdate) -> CycleOut:
        self.require_iqac()
        c = await self.cycle(cid)
        if c.status in ("submitted", "peer_visit", "result"):
            raise rule("The cycle is submitted — details are locked", "LOCKED")
        for f in ("name", "period_from", "period_to", "submission_due_on", "coordinator_staff_id"):
            v = getattr(body, f)
            if v is not None:
                setattr(c, f, v)
        await self.db.flush()
        return await self.out(c)

    async def change_status(self, cid: uuid.UUID, body: CycleStatusChange) -> CycleOut:
        self.require_iqac()
        c = await self.cycle(cid)
        cur, new = CYCLE_FLOW.index(c.status), CYCLE_FLOW.index(body.status.value)
        if new != cur + 1:
            raise rule(
                f"Cycle moves forward one step at a time ({c.status} → {CYCLE_FLOW[min(cur + 1, len(CYCLE_FLOW) - 1)]})",
                "INVALID_TRANSITION",
            )
        if body.status.value == "result":
            if body.score is None and not body.grade:
                raise rule("Record the score and / or grade with the result", "RESULT_REQUIRED", 422)
            c.score, c.grade = body.score, body.grade
        if body.status.value == "submitted":
            for r in (
                await self.db.execute(select(CriterionResponse).where(CriterionResponse.cycle_id == c.id))
            ).scalars():
                r.status = "final"
                await self._emit("accreditation.response_final", {"response_id": str(r.id)}, ENTITY, r.id)
        old = c.status
        c.status = body.status.value
        await self.db.flush()
        await self.timeline("cycle", c.id, "status", **{"from": old, "to": c.status, "remarks": body.remarks})
        await self._emit(
            "accreditation.cycle_status_changed",
            {"cycle_id": str(c.id), "from": old, "to": c.status},
            "accreditation_cycle",
            c.id,
        )
        return await self.out(c)

    async def progress(self, cid: uuid.UUID) -> dict[str, Any]:
        c = await self.cycle(cid)
        out = await self.out(c)
        rows = await self.responses(cid)
        by_criterion: dict[str, dict[str, int]] = {}
        for r in rows:
            top = r.code.split(".")[0]
            slot = by_criterion.setdefault(top, {"total": 0, "done": 0})
            slot["total"] += 1
            slot["done"] += 1 if r.status in ("approved", "final") else 0
        return {
            "cycle_id": str(c.id),
            "completion_pct": out.completion_pct,
            "criteria_progress": out.criteria_progress,
            "by_criterion": {
                k: {**v, "pct": round(100 * v["done"] / v["total"], 1) if v["total"] else 0}
                for k, v in by_criterion.items()
            },
        }

    # ---- responses ----------------------------------------------------------------------------------------------------------
    async def _response_rows(self, c: AccreditationCycle) -> dict[uuid.UUID, CriterionResponse]:
        return {
            r.framework_criterion_id: r
            for r in (
                await self.db.execute(select(CriterionResponse).where(CriterionResponse.cycle_id == c.id))
            ).scalars()
        }

    async def _response_out(
        self,
        c: AccreditationCycle,
        crit: FrameworkCriterion,
        r: CriterionResponse | None,
        fw_code: str,
        *,
        detail: bool = False,
    ) -> CriterionResponseOut:
        m = await self.meta("response", r.id) if r is not None else {}
        values = []
        if detail and r is not None and r.metric_value_ids:
            from app.services.accreditation.metric_service import MetricService

            mv = list(
                (
                    await self.db.execute(
                        select(MetricValue).where(MetricValue.id.in_([uuid.UUID(x) for x in r.metric_value_ids]))
                    )
                )
                .scalars()
                .all()
            )
            values = await MetricService(self.db, self.principal, self.request, self.inst).outs(mv)
        names = await self.staff_names([r.owner_staff_id] if r and r.owner_staff_id else [])
        trail = list(m.get("review_trail") or [])
        return CriterionResponseOut(
            id=r.id if r else None,
            cycle_id=c.id,
            criterion_id=crit.id,
            code=crit.code,
            title=crit.title,
            metric_type=crit.metric_type,
            max_score=crit.max_score,
            narrative=r.narrative if r else None,
            word_count=word_count(r.narrative if r else None),
            word_limit=WORD_LIMITS.get(fw_code),
            metric_value_ids=[str(x) for x in (r.metric_value_ids or [])] if r else [],
            metric_values=values,
            evidence_ids=[str(x) for x in (r.evidence_ids or [])] if r else [],
            owner_staff_id=r.owner_staff_id if r else None,
            owner_name=names.get(r.owner_staff_id) if r and r.owner_staff_id else None,
            due_on=date.fromisoformat(m["due_on"]) if m.get("due_on") else None,
            status=r.status if r else "not_started",
            reviewed_by=r.reviewed_by if r else None,
            last_reviewed_at=trail[-1]["at"] if trail else None,
            review_trail=trail,
            updated_at=r.updated_at if r else None,
        )

    async def responses(self, cid: uuid.UUID) -> list[CriterionResponseOut]:
        c = await self.cycle(cid)
        fw = await self.framework(c.framework_id)
        existing = await self._response_rows(c)
        out = []
        for crit in await self._leaves(c.framework_id):
            r = existing.get(crit.id)
            if not await self._response_visible(r, c):
                continue
            out.append(await self._response_out(c, crit, r, fw.code))
        return out

    async def _criterion_and_row(
        self, cid: uuid.UUID, code: str, *, lock: bool = False
    ) -> tuple[AccreditationCycle, FrameworkCriterion, CriterionResponse | None, str]:
        c = await self.cycle(cid)
        fw = await self.framework(c.framework_id)
        crit = await self.criterion_by_code(c.framework_id, code)
        stmt = select(CriterionResponse).where(
            CriterionResponse.cycle_id == c.id, CriterionResponse.framework_criterion_id == crit.id
        )
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if not await self._response_visible(r, c):
            raise not_found(f"Criterion {code}")
        return c, crit, r, fw.code

    async def response(self, cid: uuid.UUID, code: str) -> CriterionResponseOut:
        c, crit, r, fw_code = await self._criterion_and_row(cid, code)
        return await self._response_out(c, crit, r, fw_code, detail=True)

    async def _autofill(self, c: AccreditationCycle, crit: FrameworkCriterion) -> list[str]:
        label = cycle_period_label(c)
        if not crit.metric_key or not label:
            return []
        stmt = select(MetricValue.id).where(
            MetricValue.institution_id == self.inst,
            MetricValue.metric_key == crit.metric_key,
            MetricValue.period_label == label,
        )
        if c.program_id:
            stmt = stmt.where(or_(MetricValue.program_id == c.program_id, MetricValue.program_id.is_(None)))
        return [str(x) for x in (await self.db.execute(stmt)).scalars().all()]

    async def _ensure_row(
        self, c: AccreditationCycle, crit: FrameworkCriterion, r: CriterionResponse | None
    ) -> CriterionResponse:
        if r is not None:
            return r
        r = CriterionResponse(
            institution_id=self.inst,
            cycle_id=c.id,
            framework_criterion_id=crit.id,
            metric_value_ids=await self._autofill(c, crit),
            evidence_ids=[],
        )
        self.db.add(r)
        await self.db.flush()
        return r

    async def _may_edit(self, c: AccreditationCycle, r: CriterionResponse | None) -> None:
        self.require_writer()
        if c.status in ("submitted", "peer_visit", "result"):
            raise rule("The cycle is submitted — responses are final", "LOCKED")
        if self.iqac():
            return
        me = await self.my_staff_id()
        depts = await self.resolved_dept_ids()
        owner_ok = r is not None and me is not None and r.owner_staff_id == me
        hod_ok = bool(depts) and r is not None and r.owner_staff_id in await self.dept_staff_ids(depts or [])
        if not (owner_ok or hod_ok):
            raise forbidden("Only the assigned owner, their HOD or IQAC edits this response")
        if r is not None and r.status in ("approved", "final", "in_review"):
            raise rule(f"The response is {r.status} — locked for editing", "LOCKED")

    async def _version(self, r: CriterionResponse) -> None:
        m = await self.meta("response", r.id)
        versions = list(m.get("versions") or [])
        versions.append(
            {
                "version": len(versions) + 1,
                "at": now_utc().isoformat(),
                "by": str(self.actor_id) if self.actor_id else None,
                "status": r.status,
                "word_count": word_count(r.narrative),
                "narrative": r.narrative,
            }
        )
        m["versions"] = versions[-50:]
        await self.put_meta("response", r.id, m)

    async def save(self, cid: uuid.UUID, code: str, body: CriterionResponseIn) -> CriterionResponseOut:
        c, crit, r, fw_code = await self._criterion_and_row(cid, code, lock=True)
        await self._may_edit(c, r)
        r = await self._ensure_row(c, crit, r)
        limit = WORD_LIMITS.get(fw_code)
        if body.narrative is not None:
            if limit and word_count(body.narrative) > limit:
                raise rule(f"Narrative exceeds the {limit}-word limit", "WORD_LIMIT", 422, limit=limit)
            r.narrative = body.narrative
        if body.metric_value_ids is not None:
            r.metric_value_ids = [str(x) for x in body.metric_value_ids]
        elif not r.metric_value_ids:
            r.metric_value_ids = await self._autofill(c, crit)
        if body.evidence_ids is not None:
            r.evidence_ids = [str(x) for x in body.evidence_ids]
        if body.owner_staff_id is not None:
            if not self.iqac():
                raise forbidden("Only IQAC reassigns the owner")
            r.owner_staff_id = body.owner_staff_id
        if c.status in ("planning", "data_collection"):
            c.status = "drafting" if c.status == "data_collection" else c.status
        await self.db.flush()
        await self._version(r)
        return await self._response_out(c, crit, r, fw_code, detail=True)

    async def best_practice(self, cid: uuid.UUID, body: BestPracticeIn) -> CriterionResponseOut:
        text = (
            f"<h3>{body.title}</h3><h4>Objectives</h4><p>{body.objectives or ''}</p><h4>The context</h4><p>{body.context or ''}</p>"
            f"<h4>The practice</h4><p>{body.practice}</p><h4>Evidence of success</h4><p>{body.evidence_of_success or ''}</p>"
            f"<h4>Problems encountered and resources required</h4><p>{body.problems or ''}</p>"
        )
        c, crit, r, fw_code = await self._criterion_and_row(cid, BEST_PRACTICE, lock=True)
        await self._may_edit(c, r)
        r = await self._ensure_row(c, crit, r)
        existing = r.narrative or ""
        r.narrative = (existing + "\n" + text) if existing.count("<h3>") == 1 else text
        await self.db.flush()
        await self._version(r)
        m = await self.meta("response", r.id)
        m.setdefault("best_practices", []).append(body.model_dump())
        m["best_practices"] = m["best_practices"][-2:]
        await self.put_meta("response", r.id, m)
        return await self._response_out(c, crit, r, fw_code, detail=True)

    async def distinctiveness(self, cid: uuid.UUID, body: DistinctivenessIn) -> CriterionResponseOut:
        c, crit, r, fw_code = await self._criterion_and_row(cid, DISTINCTIVENESS, lock=True)
        await self._may_edit(c, r)
        r = await self._ensure_row(c, crit, r)
        r.narrative = f"<h3>{body.area}</h3><p>{body.narrative}</p>"
        await self.db.flush()
        await self._version(r)
        return await self._response_out(c, crit, r, fw_code, detail=True)

    async def assign(self, cid: uuid.UUID, body: ResponseAssign) -> list[CriterionResponseOut]:
        self.require_iqac()
        c = await self.cycle(cid)
        fw = await self.framework(c.framework_id)
        owner = (
            await self.db.execute(
                select(Staff).where(Staff.id == body.owner_staff_id, Staff.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if owner is None:
            raise not_found("Owner staff")
        out = []
        for code in body.criterion_codes:
            crit = await self.criterion_by_code(c.framework_id, code)
            r = (
                await self.db.execute(
                    select(CriterionResponse)
                    .where(CriterionResponse.cycle_id == c.id, CriterionResponse.framework_criterion_id == crit.id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            r = await self._ensure_row(c, crit, r)
            if r.status in ("approved", "final"):
                raise rule(f"Criterion {code} is {r.status}", "LOCKED")
            r.owner_staff_id = owner.id
            m = await self.meta("response", r.id)
            m["due_on"] = body.due_on.isoformat() if body.due_on else None
            await self.put_meta("response", r.id, m)
            out.append(await self._response_out(c, crit, r, fw.code))
        await self.db.flush()
        if c.status == "planning":
            c.status = "data_collection"
        await self._notify(
            "accreditation.response_assigned",
            [owner.user_id],
            {
                "cycle": c.name,
                "criteria": ", ".join(body.criterion_codes),
                "due_on": body.due_on.isoformat() if body.due_on else "",
            },
        )
        await self._emit(
            "accreditation.response_assigned",
            {"cycle_id": str(c.id), "criteria": body.criterion_codes, "owner_staff_id": str(owner.id)},
            "accreditation_cycle",
            c.id,
        )
        return out

    async def submit(self, cid: uuid.UUID, code: str) -> CriterionResponseOut:
        c, crit, r, fw_code = await self._criterion_and_row(cid, code, lock=True)
        await self._may_edit(c, r)
        if r is None or not (r.narrative or r.metric_value_ids):
            raise rule("Write the narrative or link metric values before submitting", "EMPTY_RESPONSE", 422)
        owner = (
            (await self.db.execute(select(Staff).where(Staff.id == r.owner_staff_id))).scalar_one_or_none()
            if r.owner_staff_id
            else None
        )
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_KEY,
                entity_type=ENTITY,
                entity_id=r.id,
                started_by=self.actor_id,
                context={
                    "department_id": str(owner.department_id) if owner and owner.department_id else "",
                    "college_id": str(c.college_id or (owner.college_id if owner else "") or ""),
                    "criterion": code,
                },
                title=f"{fw_code} {code} · {c.name}"[:200],
            )
            m = await self.meta("response", r.id)
            m["workflow_instance_id"] = str(wf.id)
            await self.put_meta("response", r.id, m)
        except APIError:
            pass  # no workflow definition seeded — IQAC reviews directly through /review
        r.status = "in_review"
        if c.status in ("data_collection", "drafting"):
            c.status = "internal_review" if c.status == "drafting" else c.status
        await self.db.flush()
        await self._version(r)
        await self._emit(
            "accreditation.response_submitted", {"response_id": str(r.id), "criterion": code}, ENTITY, r.id
        )
        return await self._response_out(c, crit, r, fw_code, detail=True)

    async def review(self, cid: uuid.UUID, code: str, body: ResponseReview) -> CriterionResponseOut:
        self.require_writer()
        c, crit, r, fw_code = await self._criterion_and_row(cid, code, lock=True)
        if r is None or r.status != "in_review":
            raise rule("The response is not in review", "NOT_IN_REVIEW")
        m = await self.meta("response", r.id)
        wf_id = m.get("workflow_instance_id")
        if wf_id:
            wf = (
                await self.db.execute(select(WorkflowInstance).where(WorkflowInstance.id == uuid.UUID(wf_id)))
            ).scalar_one_or_none()
            if wf is not None and wf.status in ("pending", "escalated"):
                await workflow_engine.act(
                    self.db, instance_id=wf.id, actor=self.principal, decision=body.action, comment=body.remarks
                )
                await self.db.refresh(r)
                return await self._record_review(c, crit, r, fw_code, body, terminal=r.status != "in_review")
        if not (self.iqac() or self.verifier()):
            raise forbidden("accreditation:manage or approve required")
        await self.finish(r, approve=body.action == "approve", remarks=body.remarks)
        return await self._record_review(c, crit, r, fw_code, body, terminal=True)

    async def _record_review(
        self,
        c: AccreditationCycle,
        crit: FrameworkCriterion,
        r: CriterionResponse,
        fw_code: str,
        body: ResponseReview,
        *,
        terminal: bool,
    ) -> CriterionResponseOut:
        m = await self.meta("response", r.id)
        m.setdefault("review_trail", []).append(
            {
                "at": now_utc().isoformat(),
                "by": str(self.actor_id),
                "action": body.action,
                "remarks": body.remarks,
                "terminal": terminal,
            }
        )
        await self.put_meta("response", r.id, m)
        await self._emit(
            "accreditation.response_reviewed", {"response_id": str(r.id), "action": body.action}, ENTITY, r.id
        )
        return await self._response_out(c, crit, r, fw_code, detail=True)

    async def finish(self, r: CriterionResponse, *, approve: bool, remarks: str | None = None) -> None:
        r.status = "approved" if approve else "draft"
        r.reviewed_by = self.actor_id
        await self.db.flush()
        owner_user = await self.staff_user(r.owner_staff_id) if r.owner_staff_id else None
        await self._notify(
            "accreditation.response_reviewed",
            [owner_user],
            {"status": r.status, "remarks": remarks or ""},
        )
        if approve:
            await self._emit("accreditation.response_approved", {"response_id": str(r.id)}, ENTITY, r.id)

    async def versions(self, cid: uuid.UUID, code: str) -> list[ResponseVersion]:
        _, _, r, _ = await self._criterion_and_row(cid, code)
        if r is None:
            return []
        return [ResponseVersion(**v) for v in (await self.meta("response", r.id)).get("versions") or []]

    # ---- reminders ------------------------------------------------------------------------------------------------------------
    async def due_reminders(self) -> int:
        today = await self.today()
        n = 0
        rows = (
            await self.db.execute(
                select(CriterionResponse).where(
                    CriterionResponse.institution_id == self.inst,
                    CriterionResponse.status == "draft",
                    CriterionResponse.owner_staff_id.is_not(None),
                )
            )
        ).scalars()
        metas = await self.metas("response")
        for r in rows:
            due = (metas.get(str(r.id)) or {}).get("due_on")
            if due and 0 <= (date.fromisoformat(due) - today).days <= 3:
                await self._notify(
                    "accreditation.response_due", [await self.staff_user(r.owner_staff_id)], {"due_on": due}
                )
                n += 1
        return n


async def _instance_response(db: Any, instance: WorkflowInstance) -> CriterionResponse | None:
    r: CriterionResponse | None = (
        await db.execute(select(CriterionResponse).where(CriterionResponse.id == instance.entity_id).with_for_update())
    ).scalar_one_or_none()
    return r


@workflow_engine.on(WF_KEY, "approved")
async def _approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    r = await _instance_response(db, instance)
    if r is not None and r.status == "in_review":
        await CycleService(db, actor, institution_id=instance.institution_id).finish(r, approve=True)


@workflow_engine.on(WF_KEY, "rejected")
async def _rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    r = await _instance_response(db, instance)
    if r is not None and r.status == "in_review":
        await CycleService(db, actor, institution_id=instance.institution_id).finish(r, approve=False)
