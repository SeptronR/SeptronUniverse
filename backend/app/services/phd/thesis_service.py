"""Thesis submissions & plagiarism — Prompts/31 §31.6 ``thesis_service`` ({phd.thesis_plagiarism}).

Stages ``pre_synopsis`` (DC presentation) → ``synopsis`` (after ``min_duration_months`` from registration — 409
``MIN_DURATION``; coursework done; ``pre_submission_requirements`` met — N verified journal papers tagged to the
scholar in Phase 30 ``publications.scholar_id`` and M conference presentations, else 409
``PRE_SUBMISSION_REQUIREMENTS``) → ``thesis`` (after a DC-approved synopsis) → ``revised_thesis`` (after an examiner
``major``). The AI-content declaration is mandatory (422 ``AI_DECLARATION_REQUIRED``).

Plagiarism: on submit the ``phd.plagiarism_check`` job calls the ``plagiarism`` adapter (mock until Phase 41 — a
deterministic similarity from the file URL; a ``#sim=<pct>`` fragment pins it for demos) or the provider calls back
``POST /webhooks/plagiarism/{connection_id}``. ``similarity_pct ≤ phd.rules.similarity_max_pct`` → ``plagiarism_checked``
(certificate of plagiarism check through Phase 26), above → stays ``submitted`` with flag ``SIMILARITY_EXCEEDED``
(resubmission after revision). DC approval runs ``phd.thesis_dc_approval`` (DC members in parallel → convenor); the
approved hook sets ``dc_approved`` and moves the scholar to ``synopsis_submitted`` / ``thesis_submitted`` (synopsis
acknowledgement letter). A thesis fee invoice is raised through Phase 12 when ``phd.thesis_fee_invoice`` is on.
"""

import contextlib
import hashlib
import re
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError
from app.core.workflow import engine as workflow_engine
from app.models.phd import DcMeeting, ResearchScholar, ThesisSubmission
from app.models.platform import WorkflowInstance
from app.schemas.phd import PlagiarismResult, ThesisOut, ThesisReject, ThesisSubmit
from app.services.documents.render_service import RenderService, register_resolver
from app.services.phd.common import PhdBase, add_months, forbidden, not_found, rule

WF_KEY = "phd.thesis_dc_approval"
ENTITY = "thesis_submission"
_SIM = re.compile(r"#sim=(\d+(?:\.\d+)?)")


class ThesisService(PhdBase):
    async def outs(self, rows: list[ThesisSubmission]) -> list[ThesisOut]:
        metas = await self.metas("thesis", [r.id for r in rows])
        limit = float((await self.rules()).get("similarity_max_pct") or 10)
        out = []
        for r in rows:
            m = metas.get(str(r.id)) or {}
            out.append(
                ThesisOut(
                    id=r.id,
                    scholar_id=r.scholar_id,
                    stage=r.stage,
                    title=r.title,
                    file_url=r.file_url,
                    submitted_at=r.submitted_at,
                    similarity_pct=r.similarity_pct,
                    similarity_limit_pct=limit,
                    plagiarism_report_url=r.plagiarism_report_url,
                    ai_generated_pct=r.ai_generated_pct,
                    ai_declaration=bool(m.get("ai_declaration")),
                    status=r.status,
                    flags=list(m.get("flags") or []),
                    workflow_instance_id=(
                        uuid.UUID(m["workflow_instance_id"]) if m.get("workflow_instance_id") else None
                    ),
                    certificate_document_id=uuid.UUID(m["certificate"]) if m.get("certificate") else None,
                    consolidated=m.get("consolidated"),
                )
            )
        return out

    async def latest(self, s: ResearchScholar, stage: str | None = None) -> ThesisSubmission | None:
        stmt = select(ThesisSubmission).where(ThesisSubmission.scholar_id == s.id)
        if stage:
            stmt = stmt.where(ThesisSubmission.stage == stage)
        return (
            await self.db.execute(stmt.order_by(ThesisSubmission.submitted_at.desc()).limit(1))
        ).scalar_one_or_none()

    async def latest_out(self, s: ResearchScholar) -> ThesisOut | None:
        t = await self.latest(s)
        return (await self.outs([t]))[0] if t is not None else None

    async def row(self, tid: uuid.UUID, *, lock: bool = False) -> tuple[ThesisSubmission, ResearchScholar]:
        stmt = select(ThesisSubmission).where(ThesisSubmission.id == tid, ThesisSubmission.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        t = (await self.db.execute(stmt)).scalar_one_or_none()
        if t is None:
            raise not_found("Thesis submission")
        return t, await self.scholar(t.scholar_id)

    async def for_scholar(self, sid: uuid.UUID) -> list[ThesisOut]:
        s = await self.scholar(sid)
        rows = list(
            (
                await self.db.execute(
                    select(ThesisSubmission)
                    .where(ThesisSubmission.scholar_id == s.id)
                    .order_by(ThesisSubmission.submitted_at)
                )
            ).scalars()
        )
        return await self.outs(rows)

    async def get(self, tid: uuid.UUID) -> ThesisOut:
        t, _ = await self.row(tid)
        return (await self.outs([t]))[0]

    # ---- submission ---------------------------------------------------------------------------------------------------
    async def _pre_submission(self, s: ResearchScholar) -> dict[str, Any]:
        from app.models.research import Publication

        req = (await self.rules()).get("pre_submission_requirements") or {}
        pubs = (
            await self.db.execute(
                select(Publication.pub_type, func.count())
                .where(
                    Publication.institution_id == self.inst,
                    Publication.scholar_id == s.id,
                    Publication.is_verified.is_(True),
                )
                .group_by(Publication.pub_type)
            )
        ).all()
        have = {k: int(v) for k, v in pubs}
        journals = have.get("journal", 0)
        confs = have.get("conference", 0)
        need_j, need_c = int(req.get("journal_papers") or 0), int(req.get("conference_presentations") or 0)
        return {
            "journal_papers": journals,
            "conference_presentations": confs,
            "need_journal_papers": need_j,
            "need_conference_presentations": need_c,
            "ok": journals >= need_j and confs >= need_c,
        }

    async def submit(self, sid: uuid.UUID, body: ThesisSubmit) -> ThesisOut:
        s = await self.scholar(sid, lock=True)
        self.require_writer()
        if not (await self.is_self(s) or self.cell()):
            raise forbidden("The scholar submits the thesis")
        rules = await self.rules()
        if rules.get("ai_declaration_required", True) and not body.ai_declaration:
            raise rule("The AI-content declaration is required", "AI_DECLARATION_REQUIRED", 422)
        if s.status in ("awarded", "discontinued", "viva_scheduled"):
            raise rule(f"The scholar is {s.status}", "SCHOLAR_CLOSED")
        if s.registration_date is None:
            raise rule("Thesis stages start after registration", "NOT_REGISTERED")
        stage = body.stage.value
        today = await self.today()
        if stage in ("synopsis", "thesis"):
            min_m = int(rules.get("min_duration_months") or 24)
            earliest = add_months(s.registration_date, min_m)
            if today < earliest:
                raise rule(
                    f"The minimum duration ends on {earliest}", "MIN_DURATION", 409, earliest=earliest.isoformat()
                )
            if s.coursework_status not in ("completed", "exempted"):
                raise rule("Coursework is not complete", "COURSEWORK_INCOMPLETE")
        if stage == "synopsis":
            check = await self._pre_submission(s)
            if not check["ok"]:
                raise rule("Pre-submission requirements are not met", "PRE_SUBMISSION_REQUIREMENTS", 409, **check)
        if stage == "thesis":
            syn = await self.latest(s, "synopsis")
            if syn is None or syn.status != "dc_approved":
                raise rule("The synopsis is not DC-approved", "SYNOPSIS_REQUIRED")
        if stage == "revised_thesis":
            m_th = await self.latest(s, "thesis")
            if m_th is None or (await self.meta("thesis", m_th.id)).get("consolidated") != "revise":
                raise rule("A revised thesis follows a 'major' recommendation", "REVISION_NOT_REQUESTED")
        open_same = (
            (
                await self.db.execute(
                    select(ThesisSubmission).where(
                        ThesisSubmission.scholar_id == s.id,
                        ThesisSubmission.stage == stage,
                        ThesisSubmission.status.in_(("submitted", "plagiarism_checked")),
                    )
                )
            )
            .scalars()
            .all()
        )
        for prev in open_same:  # a resubmission after revision supersedes the open one
            prev.status = "rejected"
            pm = await self.meta("thesis", prev.id)
            pm.setdefault("flags", []).append("SUPERSEDED")
            await self.put_meta("thesis", prev.id, pm)
        t = ThesisSubmission(
            institution_id=self.inst,
            scholar_id=s.id,
            stage=stage,
            title=body.title,
            file_url=body.file_url,
            ai_generated_pct=body.ai_generated_pct,
        )
        self.db.add(t)
        await self.db.flush()
        await self.put_meta(
            "thesis",
            t.id,
            {"ai_declaration": body.ai_declaration, "abstract": body.abstract, "keywords": body.keywords, "flags": []},
        )
        await self.scholar_timeline(s, "thesis_submitted", stage=stage, thesis_id=str(t.id))
        await self._emit(
            "phd.thesis_submitted", {"thesis_id": str(t.id), "scholar_id": str(s.id), "stage": stage}, ENTITY, t.id
        )
        if stage in ("thesis", "revised_thesis") and await self.setting("phd", "thesis_fee_invoice"):
            await self._fee(s, t)
        return (await self.outs([t]))[0]

    async def _fee(self, s: ResearchScholar, t: ThesisSubmission) -> None:
        amount = await self.rule_int("thesis_fee_paise")
        if amount <= 0:
            return
        from app.schemas.fees import InvoiceCreate, InvoiceItemIn
        from app.services.fees.invoice_service import InvoiceService

        with contextlib.suppress(APIError):
            inv = await InvoiceService(self.db, None, None, self.inst).create_invoice(
                InvoiceCreate(
                    enrollment_id=s.student_program_enrollment_id,
                    source_type="thesis_submission",
                    source_id=t.id,
                    description="PhD thesis submission fee",
                    items=[InvoiceItemIn(description="Thesis submission fee", amount_paise=amount, head_code="OTHER")],
                    due_date=await self.today(),
                ),
                notify=True,
            )
            m = await self.meta("thesis", t.id)
            m["fee_invoice_id"] = str(inv.id)
            await self.put_meta("thesis", t.id, m)

    # ---- plagiarism ---------------------------------------------------------------------------------------------------
    async def check(self, tid: uuid.UUID) -> ThesisOut:
        """Body of the ``phd.plagiarism_check`` job (``PlagiarismProvider`` — mock: deterministic %)."""
        from app.integrations.registry import get_adapter

        t, _ = await self.row(tid, lock=True)
        if t.status != "submitted":
            raise rule("Only a submitted thesis is checked", "NOT_SUBMITTED")
        provider = get_adapter("plagiarism", "mock")
        res = await provider.send(thesis_id=str(t.id), file_url=t.file_url)
        pin = _SIM.search(t.file_url or "")
        if pin:
            pct = Decimal(pin.group(1))
        else:
            digest = hashlib.sha256(f"{t.id}{t.file_url}".encode()).digest()
            pct = Decimal(digest[0] % 16) + Decimal(digest[1] % 100) / 100
        ai = Decimal(digest_pct(t.file_url, "ai") % 12)
        return await self.apply_result(
            PlagiarismResult(
                thesis_id=t.id,
                similarity_pct=pct,
                report_url=f"mock://plagiarism/{t.id}",
                ai_generated_pct=ai,
                reference=str(res.get("reference") if isinstance(res, dict) else ""),
            ),
            system=True,
        )

    async def apply_result(self, body: PlagiarismResult, *, system: bool = False) -> ThesisOut:
        t = (
            await self.db.execute(
                select(ThesisSubmission)
                .where(ThesisSubmission.id == body.thesis_id, ThesisSubmission.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if t is None:
            raise not_found("Thesis submission")
        s = await self.scholar_raw(t.scholar_id)
        limit = Decimal(str((await self.rules()).get("similarity_max_pct") or 10))
        t.similarity_pct = body.similarity_pct
        t.plagiarism_report_url = body.report_url
        if body.ai_generated_pct is not None:
            t.ai_generated_pct = body.ai_generated_pct
        m = await self.meta("thesis", t.id)
        flags = [f for f in m.get("flags") or [] if f != "SIMILARITY_EXCEEDED"]
        if body.similarity_pct <= limit:
            t.status = "plagiarism_checked"
            outcome = "within the limit"
        else:
            flags.append("SIMILARITY_EXCEEDED")
            outcome = "above the limit — revise and resubmit"
        m["flags"] = flags
        m["plagiarism_reference"] = body.reference
        await self.put_meta("thesis", t.id, m)
        await self.db.flush()
        if t.status == "plagiarism_checked":
            doc = await self.render_doc(
                "custom",
                ENTITY,
                t.id,
                {
                    "title": "Certificate of plagiarism check",
                    "body": f"The {t.stage.replace('_', ' ')} “{t.title}” was checked for similarity on "
                    f"{(await self.today()).strftime('%d-%m-%Y')}: {body.similarity_pct} % (limit {limit} %), "
                    "excluding references and quotes.",
                },
                allow_multiple=True,
            )
            if doc is not None:
                m["certificate"] = str(doc)
                await self.put_meta("thesis", t.id, m)
        await self._emit(
            "phd.thesis_plagiarism_checked",
            {
                "thesis_id": str(t.id),
                "similarity_pct": str(body.similarity_pct),
                "passed": t.status == "plagiarism_checked",
            },
            ENTITY,
            t.id,
        )
        await self._notify(
            "phd.thesis_similarity_result",
            [await self.scholar_user(s), *await self.guide_users(s)],
            {
                "stage": t.stage.replace("_", " "),
                "similarity": str(body.similarity_pct),
                "limit": str(limit),
                "outcome": outcome,
            },
        )
        return (await self.outs([t]))[0]

    async def certificate(self, tid: uuid.UUID) -> bytes:
        t, _ = await self.row(tid)
        m = await self.meta("thesis", t.id)
        if not m.get("certificate"):
            raise rule("No plagiarism certificate yet", "NO_CERTIFICATE", 404)
        from app.models.documents import IssuedDocument

        d = (
            await self.db.execute(select(IssuedDocument).where(IssuedDocument.id == uuid.UUID(m["certificate"])))
        ).scalar_one()
        return await RenderService(self.db, self.principal, self.request, self.inst).original_pdf(d)

    # ---- DC approval --------------------------------------------------------------------------------------------------
    async def start_dc_approval(self, tid: uuid.UUID) -> ThesisOut:
        from app.services.phd.dc_service import DcService

        t, s = await self.row(tid, lock=True)
        await self.require_relation(s, "guide", "convenor")
        if t.status != "plagiarism_checked":
            raise rule("The similarity check must pass first", "PLAGIARISM_PENDING")
        dc = DcService(self.db, self.principal, self.request, self.inst)
        if await dc.committee_row(s.id) is None:
            raise rule("Constitute the doctoral committee first", "DC_REQUIRED")
        members = await dc.member_user_ids(s)
        convenor = await dc.convenor_user(s)
        if convenor is None:
            raise rule("The convenor has no user account", "NO_CONVENOR", 422)
        ctx: dict[str, Any] = {"convenor": str(convenor), "stage": t.stage}
        for i, u in enumerate((members or [convenor])[:6], start=1):
            ctx[f"dc_member_{i}"] = str(u)
        wf = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WF_KEY,
            entity_type=ENTITY,
            entity_id=t.id,
            started_by=self.actor_id,
            context=ctx,
            title=f"DC approval · {t.stage.replace('_', ' ')} · {await self.scholar_name(s)}"[:200],
        )
        m = await self.meta("thesis", t.id)
        m["workflow_instance_id"] = str(wf.id)
        await self.put_meta("thesis", t.id, m)
        await self.db.flush()
        return (await self.outs([t]))[0]

    async def dc_approved(self, tid: uuid.UUID) -> None:
        from app.services.phd.scholar_service import ScholarService

        t = (
            await self.db.execute(select(ThesisSubmission).where(ThesisSubmission.id == tid).with_for_update())
        ).scalar_one_or_none()
        if t is None or t.status == "dc_approved":
            return
        s = await self.scholar_raw(t.scholar_id, lock=True)
        t.status = "dc_approved"
        svc = ScholarService(self.db, self.principal, self.request, self.inst)
        target = {"synopsis": "synopsis_submitted", "thesis": "thesis_submitted", "revised_thesis": "thesis_submitted"}
        if t.stage in target:
            await svc.set_status(s, target[t.stage], reason=f"{t.stage} DC-approved", force=t.stage == "revised_thesis")
        if t.stage == "pre_synopsis":
            # pre-synopsis presentations are recorded as DC meetings
            n = int(
                (
                    await self.db.execute(
                        select(func.coalesce(func.max(DcMeeting.meeting_no), 0)).where(DcMeeting.scholar_id == s.id)
                    )
                ).scalar_one()
            )
            mt = DcMeeting(institution_id=self.inst, scholar_id=s.id, meeting_no=n + 1, held_on=await self.today(), status="approved", minutes=f"Pre-synopsis presentation “{t.title}” approved.")  # fmt: skip
            self.db.add(mt)
            await self.db.flush()
            await self.put_meta("dcm", mt.id, {"kind": "pre_synopsis", "thesis_id": str(t.id)})
        await self.db.flush()
        if t.stage == "synopsis":
            doc = await self.render_doc("phd_synopsis_ack", "research_scholar", s.id, allow_multiple=False)
            if doc is not None:
                m = await self.meta("thesis", t.id)
                m["acknowledgement"] = str(doc)
                await self.put_meta("thesis", t.id, m)
        await self._emit("phd.thesis_dc_approved", {"thesis_id": str(t.id), "stage": t.stage}, ENTITY, t.id)

    async def reject(self, tid: uuid.UUID, body: ThesisReject, *, via_workflow: bool = False) -> ThesisOut:
        if via_workflow:
            t = (
                await self.db.execute(select(ThesisSubmission).where(ThesisSubmission.id == tid).with_for_update())
            ).scalar_one()
        else:
            t, s = await self.row(tid, lock=True)
            await self.require_relation(s, "guide", "convenor")
        if t.status == "dc_approved" and not via_workflow:
            raise rule("A DC-approved submission is not rejected here", "ALREADY_APPROVED")
        t.status = "rejected"
        m = await self.meta("thesis", t.id)
        m.setdefault("flags", []).append("REJECTED")
        m["reject_reason"] = body.reason
        await self.put_meta("thesis", t.id, m)
        if not via_workflow:
            await self.close_workflow(uuid.UUID(m["workflow_instance_id"]) if m.get("workflow_instance_id") else None)
        await self.db.flush()
        await self._emit("phd.thesis_rejected", {"thesis_id": str(t.id), "reason": body.reason}, ENTITY, t.id)
        return (await self.outs([t]))[0]

    async def queue(self, status: str | None = None) -> list[ThesisOut]:
        """Research cell queue: plagiarism checks / DC approvals pending."""
        stmt = select(ThesisSubmission).where(
            ThesisSubmission.institution_id == self.inst,
            ThesisSubmission.scholar_id.in_(select(ResearchScholar.id).where(await self.scholar_predicate())),
        )
        if status:
            stmt = stmt.where(ThesisSubmission.status == status)
        rows = list((await self.db.execute(stmt.order_by(ThesisSubmission.submitted_at.desc()).limit(500))).scalars())
        return await self.outs(rows)


def digest_pct(text: str | None, salt: str) -> int:
    return hashlib.sha256(f"{salt}:{text}".encode()).digest()[0]


@workflow_engine.on(WF_KEY, "approved")
async def _dc_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await ThesisService(db, actor, institution_id=instance.institution_id).dc_approved(instance.entity_id)


@workflow_engine.on(WF_KEY, "rejected")
async def _dc_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    with contextlib.suppress(APIError):
        await ThesisService(db, actor, institution_id=instance.institution_id).reject(
            instance.entity_id, ThesisReject(reason="Not approved by the doctoral committee"), via_workflow=True
        )


@register_resolver(ENTITY)
async def _thesis_ctx(svc: RenderService, tid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    from app.services.phd.scholar_service import _scholar_ctx

    t = (await svc.db.execute(select(ThesisSubmission).where(ThesisSubmission.id == tid))).scalar_one()
    ctx, ptype, pid = await _scholar_ctx(svc, t.scholar_id)
    ctx["thesis"] = {
        "title": t.title or "",
        "stage": t.stage,
        "submitted_on": t.submitted_at.strftime("%d-%m-%Y"),
        "similarity": str(t.similarity_pct) if t.similarity_pct is not None else "",
    }
    return ctx, ptype, pid
