"""Seed grants, publication incentives, travel grants, patent filing support — Prompts/30 §30.6 ``incentive_service``
({research.seed_grants_incentives}).

* Eligible amount: publication incentive = slab of ``research.publication_incentive_slabs`` (rupees) by the linked
  *verified* publication's indexing and the requester's author position (first / corresponding → ``first_author``,
  else ``co_author``); travel grant ≤ ``research.travel_grant_max_paise`` (above → 422 ``TRAVEL_CAP``); seed grant ≤
  ``research.seed_grant_max_paise``; patent support for an own patent. One incentive per linked entity (409
  ``DUPLICATE_INCENTIVE`` unless the earlier one was rejected) and ``research.incentive_annual_cap_paise`` per faculty
  per calendar year (409 ``ANNUAL_CAP``).
* Workflow ``research.incentive``: HOD recommends → research cell → dean only when the amount is above
  ``research.incentive_dean_threshold_paise`` (``above_threshold`` in the start context). ``/decide`` acts on the
  caller's open step; the engine hooks set ``approved`` / ``rejected`` (a seed grant becomes an internal ``sanctioned``
  research project — agency = the institution).
* Disbursement (``FOR UPDATE``; research cell or accounts): payroll earning line (``payroll.earning_requested``) or a
  Phase 23 expense (``research.incentive_disbursed`` carries ``via``) → ``disbursed``. The register feeds NAAC 3.1.x /
  6.3.x evidence.
"""

import contextlib
import uuid
from typing import Any

from sqlalchemy import extract, func, select, true

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.enums.research import DEFAULT_INCENTIVE_SLABS
from app.models.platform import Department, WorkflowInstance
from app.models.research import Patent, Publication, ResearchIncentive
from app.schemas.research import (
    IncentiveDecision,
    IncentiveDisburse,
    IncentiveOut,
    IncentiveRequest,
    IncentiveSlabs,
    RschProjectIn,
)
from app.services.research.common import ResearchBase, forbidden, not_found, now_utc, rule, rupees, staff_name

WF_KEY = "research.incentive"


class IncentiveService(ResearchBase):
    async def slabs(self) -> IncentiveSlabs:
        return IncentiveSlabs(
            slabs=list(await self.json_setting("publication_incentive_slabs", DEFAULT_INCENTIVE_SLABS)),
            seed_grant_max_paise=await self.int_setting("research", "seed_grant_max_paise", 50000000),
            travel_grant_max_paise=await self.int_setting("research", "travel_grant_max_paise", 5000000),
            annual_cap_paise=await self.int_setting("research", "incentive_annual_cap_paise", 20000000),
            dean_threshold_paise=await self.int_setting("research", "incentive_dean_threshold_paise", 2000000),
        )

    # ---- reads ------------------------------------------------------------------------------------------------------------
    async def predicate(self, scope: str | None = None) -> Any:
        if scope in (None, "all") and (self.cell("incentives") or self.money_reader()):
            return true()
        return await self.owned_predicate(ResearchIncentive.staff_id, scope=scope)

    async def row(self, iid: uuid.UUID, *, lock: bool = False, visible: bool = True) -> ResearchIncentive:
        stmt = select(ResearchIncentive).where(
            ResearchIncentive.id == iid, ResearchIncentive.institution_id == self.inst
        )
        if visible:
            stmt = stmt.where(await self.predicate())
        r = (await self.db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Incentive request")
        return r

    async def outs(self, rows: list[ResearchIncentive]) -> list[IncentiveOut]:
        staff = await self.staff_map([r.staff_id for r in rows])
        metas = await self.metas("incentive", [r.id for r in rows]) if rows else {}
        wfs = await self.workflow_instances([r.workflow_instance_id for r in rows])
        act = await self.actionable([r.workflow_instance_id for r in rows])
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            wf = wfs.get(r.workflow_instance_id) if r.workflow_instance_id else None
            out.append(
                IncentiveOut(
                    id=r.id,
                    incentive_type=r.incentive_type,
                    staff_id=r.staff_id,
                    staff_name=staff_name(staff.get(r.staff_id)),
                    amount_paise=int(r.amount_paise),
                    eligible_paise=m.get("eligible_paise"),
                    justification=r.justification,
                    linked_entity=r.linked_entity,
                    status=r.status,
                    workflow_instance_id=r.workflow_instance_id,
                    workflow_status=wf.status if wf else None,
                    current_step=wf.current_step if wf else None,
                    can_act=bool(r.workflow_instance_id and r.workflow_instance_id in act),
                    timeline=list(m.get("timeline") or []),
                    created_at=r.created_at,
                )
            )
        return out

    async def query(
        self, *, status: str | None = None, incentive_type: str | None = None, scope: str | None = None
    ) -> list[IncentiveOut]:
        stmt = select(ResearchIncentive).where(
            ResearchIncentive.institution_id == self.inst, await self.predicate(scope)
        )
        if status:
            stmt = stmt.where(ResearchIncentive.status == status)
        if incentive_type:
            stmt = stmt.where(ResearchIncentive.incentive_type == incentive_type)
        rows = list((await self.db.execute(stmt.order_by(ResearchIncentive.created_at.desc()).limit(500))).scalars())
        # approvers see requests waiting on their step even outside their units
        return await self.outs(rows)

    async def mine(self) -> list[IncentiveOut]:
        me = await self.require_my_staff()
        rows = list(
            (
                await self.db.execute(
                    select(ResearchIncentive)
                    .where(ResearchIncentive.institution_id == self.inst, ResearchIncentive.staff_id == me.id)
                    .order_by(ResearchIncentive.created_at.desc())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def get(self, iid: uuid.UUID) -> IncentiveOut:
        r = (
            await self.db.execute(
                select(ResearchIncentive).where(
                    ResearchIncentive.id == iid, ResearchIncentive.institution_id == self.inst
                )
            )
        ).scalar_one_or_none()
        if r is None:
            raise not_found("Incentive request")
        visible = await self.db.execute(
            select(ResearchIncentive.id).where(ResearchIncentive.id == iid, await self.predicate())
        )
        if visible.first() is None and r.workflow_instance_id not in await self.actionable([r.workflow_instance_id]):
            raise not_found("Incentive request")
        return (await self.outs([r]))[0]

    # ---- request ----------------------------------------------------------------------------------------------------------
    async def _eligible(self, body: IncentiveRequest, staff_id: uuid.UUID) -> int:
        cfg = await self.slabs()
        le = body.linked_entity
        if body.incentive_type.value == "publication_incentive":
            if le is None or le.type != "publication" or le.id is None:
                raise rule("Link the verified publication", "LINK_REQUIRED", 422)
            p = (
                await self.db.execute(
                    select(Publication).where(Publication.id == le.id, Publication.institution_id == self.inst)
                )
            ).scalar_one_or_none()
            if p is None or not await self.is_mine(p.staff_id, p.authors):
                raise not_found("Publication")
            if not p.is_verified:
                raise rule("The publication is not verified yet", "NOT_VERIFIED")
            slab = next((s for s in cfg.slabs if s.get("indexing") == p.indexing), None)
            if slab is None:
                raise rule(f"No incentive slab for indexing {p.indexing}", "NO_SLAB", 422)
            authors = list(p.authors or [])
            idx = next((i for i, a in enumerate(authors) if str(a.get("staff_id")) == str(staff_id)), None)
            first = (
                (idx == 0)
                or (idx is not None and bool(authors[idx].get("is_corresponding")))
                or (idx is None and p.staff_id == staff_id and (p.author_position or 1) == 1)
            )
            return int(slab["first_author" if first else "co_author"]) * 100
        if body.amount_paise is None:
            raise rule("amount_paise is required", "AMOUNT_REQUIRED", 422)
        if body.incentive_type.value == "travel_grant":
            if body.amount_paise > cfg.travel_grant_max_paise:
                raise rule(
                    f"Travel grants are capped at Rs {rupees(cfg.travel_grant_max_paise)}",
                    "TRAVEL_CAP",
                    422,
                    cap_paise=cfg.travel_grant_max_paise,
                )
            return body.amount_paise
        if body.incentive_type.value == "seed_grant":
            if body.amount_paise > cfg.seed_grant_max_paise:
                raise rule(
                    f"Seed grants are capped at Rs {rupees(cfg.seed_grant_max_paise)}",
                    "SEED_CAP",
                    422,
                    cap_paise=cfg.seed_grant_max_paise,
                )
            return body.amount_paise
        if le is not None and le.type == "patent" and le.id:
            pat = (
                await self.db.execute(select(Patent).where(Patent.id == le.id, Patent.institution_id == self.inst))
            ).scalar_one_or_none()
            if pat is None or not await self.is_mine(pat.staff_id, pat.co_inventors):
                raise not_found("Patent")
        return body.amount_paise

    async def submit(self, body: IncentiveRequest) -> IncentiveOut:
        self.require_writer()
        me = await self.require_my_staff()
        eligible = await self._eligible(body, me.id)
        amount = eligible if body.incentive_type.value == "publication_incentive" else int(body.amount_paise or 0)
        le = body.linked_entity
        if le is not None and le.id is not None:
            dup = (
                await self.db.execute(
                    select(ResearchIncentive.id).where(
                        ResearchIncentive.institution_id == self.inst,
                        ResearchIncentive.status != "rejected",
                        ResearchIncentive.linked_entity["id"].astext == str(le.id),
                        ResearchIncentive.incentive_type == body.incentive_type.value,
                    )
                )
            ).first()
            if dup is not None:
                raise rule("An incentive was already requested for this record", "DUPLICATE_INCENTIVE")
        year = (await self.today()).year
        used = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(ResearchIncentive.amount_paise), 0)).where(
                        ResearchIncentive.institution_id == self.inst,
                        ResearchIncentive.staff_id == me.id,
                        ResearchIncentive.status != "rejected",
                        extract("year", ResearchIncentive.created_at) == year,
                    )
                )
            ).scalar_one()
        )
        cap = await self.int_setting("research", "incentive_annual_cap_paise", 20000000)
        if used + amount > cap:
            raise rule(f"The annual incentive cap of Rs {rupees(cap)} would be exceeded", "ANNUAL_CAP", used_paise=used)
        r = ResearchIncentive(
            institution_id=self.inst,
            incentive_type=body.incentive_type.value,
            staff_id=me.id,
            amount_paise=amount,
            justification=body.justification,
            linked_entity=le.model_dump(mode="json") if le else None,
            status="requested",
        )
        self.db.add(r)
        await self.db.flush()
        threshold = await self.int_setting("research", "incentive_dean_threshold_paise", 2000000)
        faculty_id = (
            (
                await self.db.execute(select(Department.faculty_id).where(Department.id == me.department_id))
            ).scalar_one_or_none()
            if me.department_id
            else None
        )
        wf = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WF_KEY,
            entity_type="research_incentive",
            entity_id=r.id,
            started_by=self.actor_id,
            context={
                "department_id": str(me.department_id) if me.department_id else None,
                "faculty_id": str(faculty_id) if faculty_id else None,
                "amount_paise": amount,
                "above_threshold": amount > threshold,
                "incentive_type": r.incentive_type,
            },
            title=f"{r.incentive_type.replace('_', ' ').title()} · ₹{amount / 100:,.0f} · {staff_name(me)}",
        )
        r.workflow_instance_id = wf.id
        await self.put_meta(
            "incentive",
            r.id,
            {
                "eligible_paise": eligible,
                "attachments": body.attachments,
                "timeline": [{"at": now_utc().isoformat(), "action": "requested", "by": str(self.actor_id)}],
            },
        )
        await self.db.flush()
        await self._emit(
            "research.incentive_requested",
            {"incentive_id": str(r.id), "staff_id": str(me.id), "amount_paise": amount, "type": r.incentive_type},
            "research_incentive",
            r.id,
        )
        return (await self.outs([r]))[0]

    # ---- decisions ----------------------------------------------------------------------------------------------------------
    async def decide(self, iid: uuid.UUID, body: IncentiveDecision) -> IncentiveOut:
        self.require_writer()
        r = (
            await self.db.execute(
                select(ResearchIncentive)
                .where(ResearchIncentive.id == iid, ResearchIncentive.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if r is None or r.workflow_instance_id is None:
            raise not_found("Incentive request")
        if r.status != "requested":
            raise rule("The request is already decided", "ALREADY_DECIDED")
        if r.workflow_instance_id not in await self.actionable([r.workflow_instance_id]):
            raise forbidden("No step of this request is waiting on you")
        if body.amount_paise is not None:
            if not self.cell("incentives") or body.amount_paise > r.amount_paise:
                raise forbidden("Only the research cell reduces the amount")
            r.amount_paise = body.amount_paise
        await self.timeline("incentive", r.id, body.decision, comment=body.comment)
        await workflow_engine.act(
            self.db,
            instance_id=r.workflow_instance_id,
            actor=self.principal,
            decision="approve" if body.decision == "approve" else "reject",
            comment=body.comment,
        )
        await self.db.flush()
        await self.db.refresh(r)
        return (await self.outs([r]))[0]

    async def apply(self, iid: uuid.UUID, approved: bool) -> None:
        r = await self.row(iid, lock=True, visible=False)
        if r.status != "requested":
            return
        r.status = "approved" if approved else "rejected"
        await self.timeline("incentive", r.id, r.status)
        await self.db.flush()
        event = "research.incentive_approved" if approved else "research.incentive_rejected"
        await self._emit(
            event,
            {"incentive_id": str(r.id), "staff_id": str(r.staff_id), "amount_paise": int(r.amount_paise)},
            "research_incentive",
            r.id,
        )
        await self._status_note(r)
        if approved and r.incentive_type == "seed_grant":
            await self._seed_project(r)

    async def _seed_project(self, r: ResearchIncentive) -> None:
        from app.services.research.project_service import ProjectService

        svc = ProjectService(self.db, None, self.request, self.inst)
        title = (r.linked_entity or {}).get("title") or (r.justification or "Seed grant project")
        out = await svc.create(
            RschProjectIn(
                title=str(title)[:500],
                pi_staff_id=r.staff_id,
                funding_agency=(await self.institution()).name[:200],
                scheme="Seed grant",
                sanctioned_paise=int(r.amount_paise),
                budget_heads=[{"name": "contingency", "allocated_paise": int(r.amount_paise)}],
            ),
            internal=True,
        )
        m = await svc.meta("project", out.id)
        m["pending_sanction"] = {
            "sanctioned_paise": int(r.amount_paise),
            "budget_heads": [{"name": "contingency", "allocated_paise": int(r.amount_paise), "utilised_paise": 0}],
            "start_on": (await self.today()).isoformat(),
        }
        m["seed_incentive_id"] = str(r.id)
        await svc.put_meta("project", out.id, m)
        await svc.apply_sanction(out.id)
        im = await self.meta("incentive", r.id)
        im["project_id"] = str(out.id)
        await self.put_meta("incentive", r.id, im)

    async def _status_note(self, r: ResearchIncentive) -> None:
        await self._notify(
            "research.incentive_status",
            [await self.staff_user(r.staff_id)],
            {
                "incentive_type": r.incentive_type.replace("_", " "),
                "amount": rupees(r.amount_paise),
                "status": r.status,
            },
        )

    async def disburse(self, iid: uuid.UUID, body: IncentiveDisburse) -> IncentiveOut:
        self.require_writer()
        if not (self.cell("incentives") or (self.money_reader() and self.can("accounting", "post"))):
            raise forbidden("research:incentives or accounting:post required")
        r = await self.row(iid, lock=True, visible=False)
        if r.status != "approved":
            raise rule("Only an approved incentive is disbursed", "NOT_APPROVED")
        r.status = "disbursed"
        await self.timeline("incentive", r.id, "disbursed", via=body.via, reference=body.reference)
        await self.db.flush()
        payload = {
            "incentive_id": str(r.id),
            "staff_id": str(r.staff_id),
            "amount_paise": int(r.amount_paise),
            "via": body.via,
            "type": r.incentive_type,
            "reference": body.reference,
        }
        await self._emit("research.incentive_disbursed", payload, "research_incentive", r.id)
        if body.via == "payroll":
            await self._emit(
                "payroll.earning_requested",
                {
                    "staff_id": str(r.staff_id),
                    "amount_paise": int(r.amount_paise),
                    "component": "RESEARCH_INCENTIVE",
                    "source_type": "research_incentive",
                    "source_id": str(r.id),
                    "description": r.incentive_type.replace("_", " ").title(),
                },
                "research_incentive",
                r.id,
            )
        await self._status_note(r)
        return (await self.outs([r]))[0]

    async def cap_reset(self) -> int:
        """Caps are counted per calendar year; the yearly Beat records the roll-over for the register."""
        m = await self.meta("cap_reset", (await self.today()).year)
        if m:
            return 0
        await self.put_meta("cap_reset", (await self.today()).year, {"at": now_utc().isoformat()})
        return 1


@workflow_engine.on(WF_KEY, "approved")
async def _approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await IncentiveService(db, actor, institution_id=instance.institution_id).apply(instance.entity_id, True)


@workflow_engine.on(WF_KEY, "rejected")
async def _rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    with contextlib.suppress(APIError):
        await IncentiveService(db, actor, institution_id=instance.institution_id).apply(instance.entity_id, False)
