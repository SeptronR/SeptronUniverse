"""Thesis examiners — Prompts/31 §31.6 ``examiner_service`` ({phd.external_examiners}).

The guide proposes a panel for a DC-approved thesis: ≥ ``examiners_min_external`` external examiners (422
``EXTERNAL_REQUIRED``), ≥ ``examiners_outside_state`` outside the institution's state or country (422
``OUTSIDE_STATE_REQUIRED``), a conflict-of-interest declaration each, and no co-author of the scholar in the last
``coi_coauthor_years`` (Phase 30 ``publications.authors`` names / ``scholar_id`` → 409 ``CONFLICT_OF_INTEREST``). The
proposal starts ``phd.examiner_panel`` (dean → VC when ``phd.panel_vc_approval``); the sealed panel is hidden from the
scholar (``phd.rules.hide_examiners_from_scholar``) until the viva is held. Approved examiners are invited by the
research cell (tokenised accept / decline link — ``/phd/examiners/respond/{token}``, no login; an external examiner
may also be given a Phase 02 ``external_examiner`` account), accepted examiners get a signed, watermarked thesis link
(dispatch), upload a report (``accept | minor | major | reject``) and are paid a remuneration line
(``phd.examiner_remuneration_requested`` → Phase 06 / Phase 23). A decline or no response → replacement (a new
proposed row approved under the same panel). Consolidated: all ``accept | minor`` → viva eligible; any ``major`` →
revised-thesis cycle (re-examined by the same examiners); ``reject`` → research board decision.
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from app.core.workflow import engine as workflow_engine
from app.models.phd import ResearchScholar, ThesisExaminer, ThesisSubmission, VivaVoce
from app.models.platform import WorkflowInstance
from app.schemas.phd import (
    ExaminerIn,
    ExaminerInvite,
    ExaminerOut,
    ExaminerPanelPropose,
    ExaminerRemuneration,
    ExaminerReplace,
    ExaminerReportUpload,
    ExaminerResponse,
    ExaminerTokenView,
    PanelDecision,
    RecommendationsOut,
)
from app.services.phd.common import PhdBase, forbidden, new_token, not_found, now_utc, rule, token_hash

WF_KEY = "phd.examiner_panel"
ENTITY = "thesis_examiner"
LIVE = ("proposed", "approved", "invited", "accepted", "report_received")


class ExaminerService(PhdBase):
    async def _hidden(self, t: ThesisSubmission, s: ResearchScholar) -> bool:
        if not (await self.rules()).get("hide_examiners_from_scholar", True):
            return False
        if not await self.is_self(s) or self.cell():
            return False
        v = (await self.db.execute(select(VivaVoce).where(VivaVoce.thesis_id == t.id))).scalar_one_or_none()
        return v is None or v.held_at is None

    async def outs(self, rows: list[ThesisExaminer], *, hidden: bool = False) -> list[ExaminerOut]:
        metas = await self.metas("examiner", [r.id for r in rows])
        out = []
        for r in rows:
            m = metas.get(str(r.id)) or {}
            ex = r.examiner or {}
            out.append(
                ExaminerOut(
                    id=r.id,
                    thesis_id=r.thesis_id,
                    name=None if hidden else ex.get("name"),
                    affiliation=None if hidden else ex.get("affiliation"),
                    email=None if hidden else ex.get("email"),
                    is_external=r.is_external,
                    state=None if hidden else r.state,
                    country=None if hidden else r.country,
                    status=r.status,
                    invited_at=r.invited_at,
                    accepted_at=r.accepted_at,
                    report_url=None if hidden else r.report_url,
                    report_received_at=r.report_received_at,
                    recommendation=r.recommendation,
                    remuneration_paise=None if hidden else r.remuneration_paise,
                    due_on=date.fromisoformat(m["due_on"]) if m.get("due_on") else None,
                    replaced_by=m.get("replaced_by"),
                    hidden=hidden,
                )
            )
        return out

    async def _thesis(self, tid: uuid.UUID, *, lock: bool = False) -> tuple[ThesisSubmission, ResearchScholar]:
        stmt = select(ThesisSubmission).where(ThesisSubmission.id == tid, ThesisSubmission.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        t = (await self.db.execute(stmt)).scalar_one_or_none()
        if t is None:
            raise not_found("Thesis submission")
        return t, await self.scholar(t.scholar_id)

    async def panel(self, tid: uuid.UUID) -> list[ExaminerOut]:
        t, s = await self._thesis(tid)
        rows = list(
            (
                await self.db.execute(
                    select(ThesisExaminer).where(ThesisExaminer.thesis_id == t.id).order_by(ThesisExaminer.created_at)
                )
            ).scalars()
        )
        return await self.outs(rows, hidden=await self._hidden(t, s))

    async def _home_state(self) -> str | None:
        addr = (await self.institution()).address
        return str(addr.get("state")) if isinstance(addr, dict) and addr.get("state") else None

    async def _coi(self, s: ResearchScholar, examiners: list[ExaminerIn]) -> list[str]:
        """Names of proposed examiners who co-authored a publication with the scholar in the COI window."""
        from app.models.research import Publication

        years = await self.rule_int("coi_coauthor_years")
        since = (await self.today()).year - years
        names = {e.name.strip().lower(): e.name for e in examiners}
        hits: set[str] = set()
        for (authors,) in (
            await self.db.execute(
                select(Publication.authors).where(
                    Publication.institution_id == self.inst,
                    Publication.scholar_id == s.id,
                    (Publication.year.is_(None)) | (Publication.year >= since),
                )
            )
        ).all():
            for a in authors or []:
                n = str((a or {}).get("name") or "").strip().lower()
                if n in names:
                    hits.add(names[n])
        return sorted(hits)

    async def _check_policy(self, s: ResearchScholar, examiners: list[ExaminerIn]) -> None:
        r = await self.rules()
        need_ext = int(r.get("examiners_min_external") or 2)
        need_out = int(r.get("examiners_outside_state") or 1)
        ext = [e for e in examiners if e.is_external]
        if len(ext) < need_ext:
            raise rule(f"At least {need_ext} external examiners are required", "EXTERNAL_REQUIRED", 422)
        home = (await self._home_state() or "").strip().lower()
        outside = [
            e
            for e in ext
            if (e.country or "India").strip().lower() != "india" or (e.state or "").strip().lower() != home
        ]
        if not home:
            outside = [e for e in ext if e.state or (e.country or "India").lower() != "india"]
        if len(outside) < need_out:
            raise rule(
                f"At least {need_out} examiner(s) from outside the state / country are required",
                "OUTSIDE_STATE_REQUIRED",
                422,
            )
        if any(not e.coi_declaration for e in examiners):
            raise rule("Every examiner needs a conflict-of-interest declaration", "COI_DECLARATION_REQUIRED", 422)
        coi = await self._coi(s, examiners)
        if coi:
            raise rule("A proposed examiner co-authored with the scholar", "CONFLICT_OF_INTEREST", 409, examiners=coi)

    def _row(self, t: ThesisSubmission, e: ExaminerIn) -> ThesisExaminer:
        return ThesisExaminer(
            institution_id=self.inst,
            thesis_id=t.id,
            examiner={"name": e.name, "affiliation": e.affiliation, "email": str(e.email)},
            is_external=e.is_external,
            state=e.state,
            country=e.country,
        )

    async def propose(self, tid: uuid.UUID, body: ExaminerPanelPropose) -> list[ExaminerOut]:
        t, s = await self._thesis(tid, lock=True)
        await self.require_relation(s, "guide")
        if t.stage not in ("thesis", "revised_thesis") or t.status != "dc_approved":
            raise rule("Panels are proposed for a DC-approved thesis", "THESIS_NOT_APPROVED")
        live = (
            await self.db.execute(
                select(ThesisExaminer.id).where(ThesisExaminer.thesis_id == t.id, ThesisExaminer.status.in_(LIVE))
            )
        ).first()
        if live is not None:
            raise rule("A panel exists for this thesis — replace examiners instead", "PANEL_EXISTS")
        await self._check_policy(s, body.examiners)
        rows = [self._row(t, e) for e in body.examiners]
        self.db.add_all(rows)
        await self.db.flush()
        from app.models.students import StudentProgramEnrollment

        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == s.student_program_enrollment_id)
            )
        ).scalar_one()
        wf = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WF_KEY,
            entity_type="thesis_submission",
            entity_id=t.id,
            started_by=self.actor_id,
            context={
                "department_id": str(e.department_id),
                "college_id": str(e.college_id),
                "vc_approval": bool(await self.setting("phd", "panel_vc_approval")),
                "examiners": len(rows),
            },
            title=f"Examiner panel · {t.title or 'thesis'}"[:200],
        )
        m = await self.meta("thesis", t.id)
        m["panel_workflow_id"] = str(wf.id)
        await self.put_meta("thesis", t.id, m)
        await self._emit(
            "phd.examiner_panel_proposed", {"thesis_id": str(t.id), "examiners": len(rows)}, "thesis_submission", t.id
        )
        return await self.outs(rows)

    async def decide(self, tid: uuid.UUID, body: PanelDecision, *, via_workflow: bool = False) -> list[ExaminerOut]:
        if via_workflow:
            t = (await self.db.execute(select(ThesisSubmission).where(ThesisSubmission.id == tid))).scalar_one()
        else:
            self.require_writer()
            if not self.approver():
                raise forbidden("The dean (or the research cell) decides panels")
            t, _ = await self._thesis(tid, lock=True)
            m = await self.meta("thesis", t.id)
            await self.close_workflow(
                uuid.UUID(m["panel_workflow_id"]) if m.get("panel_workflow_id") else None,
                "approved" if body.approve else "rejected",
            )
        rows = list(
            (
                await self.db.execute(
                    select(ThesisExaminer)
                    .where(ThesisExaminer.thesis_id == t.id, ThesisExaminer.status == "proposed")
                    .with_for_update()
                )
            ).scalars()
        )
        for r in rows:
            r.status = "approved" if body.approve else "declined"
        await self.db.flush()
        if body.approve:
            await self._emit(
                "phd.examiner_panel_approved",
                {"thesis_id": str(t.id), "examiners": len(rows)},
                "thesis_submission",
                t.id,
            )
        return await self.outs(rows)

    async def _examiner(
        self, eid: uuid.UUID, *, lock: bool = True
    ) -> tuple[ThesisExaminer, ThesisSubmission, ResearchScholar]:
        stmt = select(ThesisExaminer).where(ThesisExaminer.id == eid, ThesisExaminer.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Examiner")
        t, s = await self._thesis(r.thesis_id)
        return r, t, s

    async def invite(self, eid: uuid.UUID, body: ExaminerInvite) -> ExaminerOut:
        self.require_cell("examine")
        r, t, s = await self._examiner(eid)
        if r.status not in ("approved", "invited"):
            raise rule("Only an approved examiner is invited", "NOT_APPROVED")
        token = new_token()
        due_days = body.due_days or await self.rule_int("examiner_report_due_days")
        m = await self.meta("examiner", r.id)
        old = m.get("token_hash")
        if old:
            await self.put_meta("token", old, {})
        m.update(
            {"token_hash": token_hash(token), "due_on": ((await self.today()) + timedelta(days=due_days)).isoformat()}
        )
        await self.put_meta("examiner", r.id, m)
        await self.put_meta("token", token_hash(token), {"examiner_id": str(r.id)})
        r.status, r.invited_at = "invited", now_utc()
        await self.db.flush()
        doc = await self.render_doc(
            "examiner_invitation", "thesis_submission", t.id, {"examiner": {**(r.examiner or {}), "due_days": due_days}},
            allow_multiple=True,
        )  # fmt: skip
        link = f"/examiner/respond/{token}"
        await self._emit(
            "phd.examiner_invited",
            {"examiner_id": str(r.id), "thesis_id": str(t.id), "email": (r.examiner or {}).get("email"), "link": link},
            ENTITY,
            r.id,
        )
        from app.core.notifications.notify import notify_event

        ex = r.examiner or {}
        if ex.get("email"):
            await notify_event(
                self.db,
                self.inst,
                "phd.examiner_invite",
                audience={
                    "direct_contacts": [{"to": str(ex["email"]), "channel": "email", "name": str(ex.get("name") or "")}]
                },
                context={"title": t.title or "", "link": link},
                actor_user_id=self.actor_id,
            )
        out = (await self.outs([r]))[0]
        if doc is not None:
            m["invitation_document_id"] = str(doc)
            await self.put_meta("examiner", r.id, m)
        return out

    # ---- token pages (external examiner, no login) --------------------------------------------------------------------
    async def by_token(self, token: str, *, lock: bool = False) -> tuple[ThesisExaminer, ThesisSubmission]:
        ref = await self.meta("token", token_hash(token))
        if not ref.get("examiner_id"):
            raise not_found("Invitation")
        stmt = select(ThesisExaminer).where(ThesisExaminer.id == uuid.UUID(ref["examiner_id"]))
        if lock:
            stmt = stmt.with_for_update()
        r = (await self.db.execute(stmt)).scalar_one_or_none()
        if r is None:
            raise not_found("Invitation")
        t = (await self.db.execute(select(ThesisSubmission).where(ThesisSubmission.id == r.thesis_id))).scalar_one()
        return r, t

    async def token_view(self, token: str) -> ExaminerTokenView:
        r, t = await self.by_token(token)
        m = await self.meta("examiner", r.id)
        return ExaminerTokenView(
            examiner_id=r.id,
            name=str((r.examiner or {}).get("name") or ""),
            thesis_title=t.title,
            institution=(await self.institution()).name,
            status=r.status,
            due_on=date.fromisoformat(m["due_on"]) if m.get("due_on") else None,
            download_url=m.get("dispatch_url") if r.status in ("accepted", "report_received") else None,
        )

    async def respond(self, token: str, body: ExaminerResponse) -> ExaminerTokenView:
        r, t = await self.by_token(token, lock=True)
        if r.status != "invited":
            raise rule("This invitation is already answered", "ALREADY_ANSWERED")
        if body.accept:
            r.status, r.accepted_at = "accepted", now_utc()
            ev = "phd.examiner_accepted"
        else:
            r.status = "declined"
            ev = "phd.examiner_declined"
        m = await self.meta("examiner", r.id)
        m["response_remarks"] = body.remarks
        await self.put_meta("examiner", r.id, m)
        await self.db.flush()
        await self._emit(ev, {"examiner_id": str(r.id), "thesis_id": str(t.id)}, ENTITY, r.id)
        return await self.token_view(token)

    async def token_report(self, token: str, body: ExaminerReportUpload) -> ExaminerTokenView:
        r, _ = await self.by_token(token, lock=True)
        await self._record_report(r, body)
        return await self.token_view(token)

    async def dispatch(self, eid: uuid.UUID) -> ExaminerOut:
        """Signed, watermarked thesis link for an accepted examiner (``phd.examiner_dispatch`` job body)."""
        self.require_cell("examine")
        r, t, s = await self._examiner(eid)
        if r.status != "accepted":
            raise rule("Only an accepted examiner receives the thesis", "NOT_ACCEPTED")
        from app.core.files import get_storage

        storage = get_storage()
        try:
            url = storage.signed_url(t.file_url)
        except Exception:  # noqa: BLE001 - external URLs are dispatched as-is (mock storage)
            url = t.file_url
        m = await self.meta("examiner", r.id)
        m.update(
            {
                "dispatch_url": url,
                "dispatched_at": now_utc().isoformat(),
                "watermark": f"Examiner copy · {r.id.hex[:8]}",
            }
        )
        await self.put_meta("examiner", r.id, m)
        if s.status in ("thesis_submitted",):
            from app.services.phd.scholar_service import ScholarService

            await ScholarService(self.db, self.principal, self.request, self.inst).set_status(
                s, "under_evaluation", reason="thesis dispatched"
            )
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def report(self, eid: uuid.UUID, body: ExaminerReportUpload) -> ExaminerOut:
        self.require_cell("examine")
        r, _, _ = await self._examiner(eid)
        await self._record_report(r, body)
        return (await self.outs([r]))[0]

    async def _record_report(self, r: ThesisExaminer, body: ExaminerReportUpload) -> None:
        if r.status not in ("accepted", "report_received"):
            raise rule("Reports come from an accepted examiner", "NOT_ACCEPTED")
        r.report_url, r.recommendation = body.report_url, body.recommendation.value
        r.report_received_at, r.status = now_utc(), "report_received"
        m = await self.meta("examiner", r.id)
        m["remarks"] = body.remarks
        await self.put_meta("examiner", r.id, m)
        await self.db.flush()
        t = (await self.db.execute(select(ThesisSubmission).where(ThesisSubmission.id == r.thesis_id))).scalar_one()
        rec = await self._consolidate(t)
        await self._emit(
            "phd.examiner_report_received",
            {"examiner_id": str(r.id), "thesis_id": str(t.id), "recommendation": r.recommendation},
            ENTITY,
            r.id,
        )
        await self._notify(
            "phd.examiner_report_received",
            [],
            {"title": t.title or "", "received": rec.received, "total": rec.total},
            audience={"roles": ["research_cell"]},
        )

    async def replace(self, eid: uuid.UUID, body: ExaminerReplace) -> ExaminerOut:
        self.require_cell("examine")
        r, t, s = await self._examiner(eid)
        if r.status not in ("declined", "invited", "approved", "accepted"):
            raise rule("Only a declined / unresponsive examiner is replaced", "NOT_REPLACEABLE")
        others = [
            ExaminerIn(
                name=str((x.examiner or {}).get("name") or "x"),
                affiliation=str((x.examiner or {}).get("affiliation") or "x"),
                email=str((x.examiner or {}).get("email") or "x@example.org"),
                is_external=x.is_external,
                state=x.state,
                country=x.country or "India",
            )
            for x in (
                await self.db.execute(
                    select(ThesisExaminer).where(
                        ThesisExaminer.thesis_id == t.id, ThesisExaminer.id != r.id, ThesisExaminer.status.in_(LIVE)
                    )
                )
            ).scalars()
        ]
        await self._check_policy(s, [*others, body.replacement])
        prev = r.status
        r.status = "declined"
        new = self._row(t, body.replacement)
        new.status = "approved"  # the replacement joins the already-approved panel
        self.db.add(new)
        await self.db.flush()
        m = await self.meta("examiner", r.id)
        m.update({"replaced_by": str(new.id), "replaced_from_status": prev})
        await self.put_meta("examiner", r.id, m)
        await self.put_meta("examiner", new.id, {"replaces": str(r.id)})
        return (await self.outs([new]))[0]

    async def remuneration(self, eid: uuid.UUID, body: ExaminerRemuneration) -> ExaminerOut:
        p = self.principal
        self.require_writer()
        if not (self.cell("examine") or (p is not None and (p.has("phd", "examine") or p.has("accounting", "post")))):
            raise forbidden("phd:examine or accounting:post required")
        r, t, _ = await self._examiner(eid)
        if r.status != "report_received":
            raise rule("Remuneration follows the report", "REPORT_PENDING")
        r.remuneration_paise = body.amount_paise
        await self.db.flush()
        await self._emit(
            "phd.examiner_remuneration_requested",
            {
                "examiner_id": str(r.id),
                "thesis_id": str(t.id),
                "amount_paise": body.amount_paise,
                "via": body.via,
                "payee": r.examiner,
                "source_type": "phd_examiner",
                "source_id": str(r.id),
            },
            ENTITY,
            r.id,
        )
        return (await self.outs([r]))[0]

    # ---- consolidation ------------------------------------------------------------------------------------------------
    async def _consolidate(self, t: ThesisSubmission) -> RecommendationsOut:
        rows = list(
            (
                await self.db.execute(
                    select(ThesisExaminer).where(
                        ThesisExaminer.thesis_id == t.id,
                        ThesisExaminer.status.in_(("approved", "invited", "accepted", "report_received")),
                    )
                )
            ).scalars()
        )
        recs = [r.recommendation for r in rows if r.status == "report_received" and r.recommendation]
        viva_after = set((await self.rules()).get("viva_after") or ["accept", "minor"])
        if len(recs) < len(rows) or not rows:
            consolidated = "pending"
        elif "reject" in recs:
            consolidated = "board_decision"
        elif "major" in recs:
            consolidated = "revise"
        elif all(r in viva_after for r in recs):
            consolidated = "viva_eligible"
        else:
            consolidated = "pending"
        m = await self.meta("thesis", t.id)
        if m.get("consolidated") != consolidated:
            m["consolidated"] = consolidated
            await self.put_meta("thesis", t.id, m)
        return RecommendationsOut(
            thesis_id=t.id, received=len(recs), total=len(rows), recommendations=recs, consolidated=consolidated
        )

    async def recommendations(self, tid: uuid.UUID) -> RecommendationsOut:
        t, s = await self._thesis(tid)
        if await self.is_self(s) and not self.cell():
            out = await self._consolidate(t)
            return out.model_copy(update={"recommendations": []})
        return await self._consolidate(t)

    async def tracker(self, status: str | None = None) -> list[ExaminerOut]:
        if not (
            self.cell("examine")
            or self.approver()
            or (self.principal is not None and self.principal.has("phd", "examine"))
        ):
            raise forbidden("phd:examine required")
        stmt = select(ThesisExaminer).where(ThesisExaminer.institution_id == self.inst)
        if status:
            stmt = stmt.where(ThesisExaminer.status == status)
        rows = list((await self.db.execute(stmt.order_by(ThesisExaminer.created_at.desc()).limit(500))).scalars())
        return await self.outs(rows)

    async def report_reminders(self) -> int:
        today = await self.today()
        n = 0
        for r in (
            await self.db.execute(
                select(ThesisExaminer).where(
                    ThesisExaminer.institution_id == self.inst, ThesisExaminer.status.in_(("invited", "accepted"))
                )
            )
        ).scalars():
            m = await self.meta("examiner", r.id)
            due = m.get("due_on")
            if not due or date.fromisoformat(due) > today + timedelta(days=7):
                continue
            if m.get("reminded") == today.isoformat():
                continue
            m["reminded"] = today.isoformat()
            await self.put_meta("examiner", r.id, m)
            await self._emit(
                "phd.examiner_report_reminder",
                {"examiner_id": str(r.id), "email": (r.examiner or {}).get("email"), "due_on": due},
                ENTITY,
                r.id,
            )
            n += 1
        return n

    async def panel_rejected(self, tid: uuid.UUID) -> None:
        await self.decide(tid, PanelDecision(approve=False), via_workflow=True)


@workflow_engine.on(WF_KEY, "approved")
async def _panel_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await ExaminerService(db, actor, institution_id=instance.institution_id).decide(
        instance.entity_id, PanelDecision(approve=True), via_workflow=True
    )


@workflow_engine.on(WF_KEY, "rejected")
async def _panel_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await ExaminerService(db, actor, institution_id=instance.institution_id).panel_rejected(instance.entity_id)
