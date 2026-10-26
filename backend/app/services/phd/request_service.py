"""Scholar requests — Prompts/31 §31.6 ``request_service`` ({phd.extensions_guide_change}).

``extension`` (months ≤ ``phd.rules.extension_max_months`` cumulative, 422 ``EXTENSION_LIMIT``) extends
``max_duration_end`` on approval; ``change_of_guide`` checks the new guide's load at request time and again on
approval (409 ``GUIDE_LOAD_EXCEEDED``), needs the old guide's NOC (``/guide-noc``) before the research cell step, then
reassigns and prompts DC reconstitution; ``mode_change`` (full ↔ part-time) flags the fellowship implication (a
part-time scholar holds no fellowship — the active one is closed on approval); ``leave`` (maternity / medical / other)
applies the fellowship hold rule of ``phd.rules.leave_fellowship_hold``; ``coursework_exemption`` → ``exempted``;
``cancellation_review`` is opened by the progress service. All run on ``phd.request`` (guide → research cell → dean;
the guide is ``context.guide``); the approved / rejected hooks apply the decision and notify the scholar.
"""

import contextlib
import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.models.phd import ResearchScholar, ScholarFellowship, ScholarRequest
from app.models.platform import WorkflowInstance
from app.models.students import StudentProgramEnrollment
from app.schemas.phd import GuideAllocate, GuideNoc, ScholarRequestCreate, ScholarRequestOut
from app.services.phd.common import PhdBase, add_months, forbidden, not_found, now_utc, rule

WF_KEY = "phd.request"
ENTITY = "scholar_request"


class RequestService(PhdBase):
    async def outs(self, rows: list[ScholarRequest]) -> list[ScholarRequestOut]:
        wfs = await self.workflow_instances([r.workflow_instance_id for r in rows])
        acts = await self.actionable([r.workflow_instance_id for r in rows])
        scholars = (
            {
                s.id: s
                for s in (
                    await self.db.execute(
                        select(ResearchScholar).where(ResearchScholar.id.in_([r.scholar_id for r in rows]))
                    )
                ).scalars()
            }
            if rows
            else {}
        )
        cards = await self.enrollment_cards([s.student_program_enrollment_id for s in scholars.values()])
        metas = await self.metas("request", [r.id for r in rows])
        out = []
        for r in rows:
            wf = wfs.get(r.workflow_instance_id) if r.workflow_instance_id else None
            s = scholars.get(r.scholar_id)
            out.append(
                ScholarRequestOut(
                    id=r.id,
                    scholar_id=r.scholar_id,
                    scholar_name=(cards.get(s.student_program_enrollment_id) or {}).get("name") if s else None,
                    request_type=r.request_type,
                    details=dict(r.details or {}),
                    status=r.status,
                    workflow_instance_id=r.workflow_instance_id,
                    workflow_status=getattr(wf, "status", None),
                    current_step=getattr(wf, "current_step", None),
                    actionable=r.workflow_instance_id in acts,
                    implications=list((metas.get(str(r.id)) or {}).get("implications") or []),
                    decided_at=r.decided_at,
                    created_at=r.created_at,
                )
            )
        return out

    async def row(self, rid: uuid.UUID, *, lock: bool = False) -> ScholarRequest:
        stmt = select(ScholarRequest).where(ScholarRequest.id == rid, ScholarRequest.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Scholar request")
        await self.scholar(r.scholar_id)  # visibility (404 outside reach)
        return r

    async def get(self, rid: uuid.UUID) -> ScholarRequestOut:
        return (await self.outs([await self.row(rid)]))[0]

    async def for_scholar(self, sid: uuid.UUID) -> list[ScholarRequestOut]:
        s = await self.scholar(sid)
        rows = list(
            (
                await self.db.execute(
                    select(ScholarRequest)
                    .where(ScholarRequest.scholar_id == s.id)
                    .order_by(ScholarRequest.created_at.desc())
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def query(
        self, *, request_type: str | None = None, status: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[ScholarRequestOut], int]:
        stmt = select(ScholarRequest).where(
            ScholarRequest.institution_id == self.inst,
            ScholarRequest.scholar_id.in_(
                select(ResearchScholar.id).where(
                    ResearchScholar.institution_id == self.inst, await self.scholar_predicate()
                )
            ),
        )
        if request_type:
            stmt = stmt.where(ScholarRequest.request_type == request_type)
        if status:
            stmt = stmt.where(ScholarRequest.status == status)
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(stmt.order_by(ScholarRequest.created_at.desc()).limit(limit).offset(offset))
            ).scalars()
        )
        return await self.outs(rows), total

    # ---- create -------------------------------------------------------------------------------------------------------
    async def _validate(self, s: ResearchScholar, body: ScholarRequestCreate) -> tuple[dict[str, Any], list[str]]:
        r = await self.rules()
        d = body.details.model_dump(mode="json", exclude_none=True)
        implications: list[str] = []
        t = body.request_type.value
        if t == "extension":
            if not body.details.months:
                raise rule("months is required", "MONTHS_REQUIRED", 422)
            sm = await self.meta("scholar", s.id)
            used = int(sm.get("extension_months") or 0)
            cap = int(r.get("extension_max_months") or 24)
            if used + body.details.months > cap:
                raise rule(
                    f"Extensions total {used + body.details.months} months (limit {cap})",
                    "EXTENSION_LIMIT",
                    422,
                    used=used,
                    max=cap,
                )
            if s.max_duration_end is None:
                raise rule("Extensions apply after registration", "NOT_REGISTERED")
        elif t == "change_of_guide":
            if not body.details.new_guide_staff_id:
                raise rule("new_guide_staff_id is required", "GUIDE_REQUIRED", 422)
            if body.details.new_guide_staff_id == s.guide_staff_id:
                raise rule("The new guide is the current guide", "SAME_GUIDE", 422)
            await self.staff_row(body.details.new_guide_staff_id)
            mx, _ = await self.guide_max(body.details.new_guide_staff_id)
            if await self.guide_current(body.details.new_guide_staff_id) >= mx:
                raise rule("The new guide has no free load", "GUIDE_LOAD_EXCEEDED", 409)
            implications.append("Old guide NOC required before the research cell step")
            implications.append("Doctoral committee to be reconstituted by the new guide")
        elif t == "mode_change":
            if not body.details.new_mode or body.details.new_mode.value == s.mode:
                raise rule("new_mode must differ from the current mode", "SAME_MODE", 422)
            if body.details.new_mode.value == "part_time" and s.fellowship_type != "none":
                implications.append("Part-time scholars hold no fellowship — the active fellowship closes on approval")
        elif t == "leave":
            if not (body.details.from_on and body.details.to_on) or body.details.to_on < body.details.from_on:
                raise rule("from_on / to_on are required", "DATES_REQUIRED", 422)
            hold = (r.get("leave_fellowship_hold") or {}).get(body.details.leave_type or "other", True)
            if hold and s.fellowship_type != "none":
                implications.append("Fellowship disbursements are held for the leave period")
        elif t == "coursework_exemption":
            if s.coursework_status in ("completed", "exempted"):
                raise rule("Coursework is already closed", "COURSEWORK_CLOSED")
        elif t == "cancellation_review":
            raise forbidden("Cancellation reviews are opened by the system")
        if body.attachments:
            d["attachments"] = body.attachments
        return d, implications

    async def create(self, sid: uuid.UUID, body: ScholarRequestCreate) -> ScholarRequestOut:
        s = await self.scholar(sid, lock=True)
        self.require_writer()
        if not (await self.is_self(s) or await self.is_guide_of(s) or self.cell()):
            raise forbidden("The scholar (or the guide / research cell) raises requests")
        if s.status in ("awarded", "discontinued"):
            raise rule(f"The scholar is {s.status}", "SCHOLAR_CLOSED")
        open_same = (
            await self.db.execute(
                select(ScholarRequest.id).where(
                    ScholarRequest.scholar_id == s.id,
                    ScholarRequest.request_type == body.request_type.value,
                    ScholarRequest.status.in_(("requested", "in_review")),
                )
            )
        ).scalar_one_or_none()
        if open_same is not None:
            raise rule("A request of this type is already open", "REQUEST_OPEN", 409, request_id=str(open_same))
        details, implications = await self._validate(s, body)
        req = ScholarRequest(
            institution_id=self.inst, scholar_id=s.id, request_type=body.request_type.value, details=details
        )
        self.db.add(req)
        await self.db.flush()
        await self.put_meta("request", req.id, {"implications": implications})
        await self._start(s, req)
        await self._emit(
            "phd.request_created",
            {"request_id": str(req.id), "scholar_id": str(s.id), "request_type": req.request_type},
            ENTITY,
            req.id,
        )
        return (await self.outs([req]))[0]

    async def open_system(self, s: ResearchScholar, request_type: str, details: dict[str, Any]) -> ScholarRequest:
        req = (
            await self.db.execute(
                select(ScholarRequest).where(
                    ScholarRequest.scholar_id == s.id,
                    ScholarRequest.request_type == request_type,
                    ScholarRequest.status.in_(("requested", "in_review")),
                )
            )
        ).scalar_one_or_none()
        if req is not None:
            return req
        req = ScholarRequest(institution_id=self.inst, scholar_id=s.id, request_type=request_type, details=details)
        self.db.add(req)
        await self.db.flush()
        await self._start(s, req)
        return req

    async def _start(self, s: ResearchScholar, req: ScholarRequest) -> None:
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == s.student_program_enrollment_id)
            )
        ).scalar_one()
        guide_user = await self.staff_user(s.guide_staff_id)
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF_KEY,
                entity_type=ENTITY,
                entity_id=req.id,
                started_by=self.actor_id,
                context={
                    "guide": str(guide_user or ""),
                    "request_type": req.request_type,
                    "department_id": str(e.department_id),
                    "college_id": str(e.college_id),
                },
                title=f"PhD {req.request_type.replace('_', ' ')} · {await self.scholar_name(s)}"[:200],
            )
            req.workflow_instance_id, req.status = wf.id, "in_review"
        except APIError:
            # no resolvable approver (e.g. the guide has no user account) — decided at the research cell desk
            req.status = "requested"
        await self.db.flush()

    # ---- steps --------------------------------------------------------------------------------------------------------
    async def guide_noc(self, rid: uuid.UUID, body: GuideNoc) -> ScholarRequestOut:
        req = await self.row(rid, lock=True)
        s = await self.scholar_raw(req.scholar_id)
        self.require_writer()
        if req.request_type != "change_of_guide":
            raise rule("A NOC applies to guide changes only", "WRONG_REQUEST_TYPE", 422)
        sid = await self.my_staff_id()
        if not (self.cell() or (sid is not None and sid == s.guide_staff_id)):
            raise forbidden("The current guide grants the NOC")
        d = dict(req.details or {})
        d["noc"] = {
            "granted": body.granted,
            "remarks": body.remarks,
            "by": str(self.actor_id),
            "at": now_utc().isoformat(),
        }
        req.details = d
        await self.db.flush()
        if not body.granted:
            await self.finish(req, approve=False, remarks=body.remarks or "NOC refused by the guide")
        return (await self.outs([req]))[0]

    async def decide_desk(self, rid: uuid.UUID, approve: bool, remarks: str | None) -> ScholarRequestOut:
        """Research cell desk decision when no workflow could start (or to close one)."""
        self.require_cell()
        req = await self.row(rid, lock=True)
        await self.close_workflow(req.workflow_instance_id, "approved" if approve else "rejected")
        await self.finish(req, approve=approve, remarks=remarks)
        return (await self.outs([req]))[0]

    async def finish(
        self, req: ScholarRequest, *, approve: bool, remarks: str | None = None, decision: str | None = None
    ) -> None:
        if req.status in ("approved", "rejected", "cancelled"):
            return
        s = await self.scholar_raw(req.scholar_id, lock=True)
        if approve and req.request_type != "cancellation_review":
            await self._apply(s, req)
        req.status = "approved" if approve else "rejected"
        req.decided_at = now_utc()
        m = await self.meta("request", req.id)
        m["decision"] = {"approve": approve, "remarks": remarks, "decision": decision, "at": now_utc().isoformat()}
        await self.put_meta("request", req.id, m)
        await self.scholar_timeline(s, f"request_{req.status}", request_type=req.request_type, request_id=str(req.id))
        await self.db.flush()
        await self._emit(
            "phd.request_decided",
            {
                "request_id": str(req.id),
                "scholar_id": str(s.id),
                "request_type": req.request_type,
                "status": req.status,
            },
            ENTITY,
            req.id,
        )
        await self._notify(
            "phd.request_decided",
            [await self.scholar_user(s)],
            {
                "request_type": req.request_type.replace("_", " "),
                "decision": decision or req.status,
                "remarks": remarks or "",
            },
        )

    async def _apply(self, s: ResearchScholar, req: ScholarRequest) -> None:
        from app.services.phd.coursework_service import CourseworkService
        from app.services.phd.scholar_service import ScholarService

        d = dict(req.details or {})
        args = (self.db, self.principal, self.request, self.inst)
        t = req.request_type
        if t == "extension":
            months = int(d.get("months") or 0)
            sm = await self.meta("scholar", s.id)
            sm["extension_months"] = int(sm.get("extension_months") or 0) + months
            await self.put_meta("scholar", s.id, sm)
            if s.max_duration_end:
                s.max_duration_end = add_months(s.max_duration_end, months)
        elif t == "change_of_guide":
            if not (d.get("noc") or {}).get("granted"):
                raise rule("The old guide's NOC is pending", "NOC_REQUIRED")
            await ScholarService(*args).allocate_guide(
                s.id,
                GuideAllocate(guide_staff_id=uuid.UUID(str(d["new_guide_staff_id"])), reason=d.get("reason")),
                via_request=True,
            )
        elif t == "mode_change":
            s.mode = str(d.get("new_mode"))
            if s.mode == "part_time":
                for f in (
                    await self.db.execute(
                        select(ScholarFellowship).where(
                            ScholarFellowship.scholar_id == s.id, ScholarFellowship.status != "closed"
                        )
                    )
                ).scalars():
                    f.status, f.to_on = "closed", await self.today()
                s.fellowship_type = "none"
        elif t == "leave":
            hold = ((await self.rules()).get("leave_fellowship_hold") or {}).get(d.get("leave_type") or "other", True)
            sm = await self.meta("scholar", s.id)
            sm.setdefault("leaves", []).append(
                {"from_on": d.get("from_on"), "to_on": d.get("to_on"), "type": d.get("leave_type"), "hold": bool(hold)}
            )
            await self.put_meta("scholar", s.id, sm)
        elif t == "coursework_exemption":
            await CourseworkService(*args).exempt(s, str(d.get("reason") or "prior coursework"), d.get("attachments"))
        await self.db.flush()

    async def scholar_for(self, req: ScholarRequest) -> ResearchScholar:
        return await self.scholar_raw(req.scholar_id)


async def _instance_request(db: Any, instance: WorkflowInstance) -> ScholarRequest | None:
    req: ScholarRequest | None = (
        await db.execute(select(ScholarRequest).where(ScholarRequest.id == instance.entity_id).with_for_update())
    ).scalar_one_or_none()
    return req


@workflow_engine.on(WF_KEY, "approved")
async def _approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    req = await _instance_request(db, instance)
    if req is None or req.request_type == "cancellation_review":
        return  # cancellation reviews are decided with an explicit warning / discontinue body
    svc = RequestService(db, actor, institution_id=instance.institution_id)
    try:
        await svc.finish(req, approve=True)
    except APIError:
        # a precondition failed at approval time (e.g. NOC pending / guide load) — recorded as rejected
        with contextlib.suppress(APIError):
            await svc.finish(req, approve=False, remarks="Approval preconditions not met")


@workflow_engine.on(WF_KEY, "rejected")
async def _rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    req = await _instance_request(db, instance)
    if req is not None:
        await RequestService(db, actor, institution_id=instance.institution_id).finish(req, approve=False)
