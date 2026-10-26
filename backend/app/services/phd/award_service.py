"""PhD award — Prompts/31 §31.6 ``award_service`` ({phd.core}).

After a ``recommended`` viva the research cell requests the award: ``phd.award`` (research cell → dean → academic
council resolution step only when ``governance.minutes`` is on — then ``resolution_id`` is required, 422
``RESOLUTION_REQUIRED``). The approved hook writes the Phase 18 ``degrees_awarded(award_type='phd',
approval_resolution_id, status='council_approved')`` row (issued later with the convocation batch), renders the
provisional PhD certificate (Phase 26 ``phd_provisional_certificate``), sets the scholar ``awarded``, closes the
fellowship, starts the ETD deadline (``etd_deadline_days``), notifies scholar and guide and emits
``phd.thesis_awarded {scholar_id, thesis_id, degree_awarded_id, date_of_award}`` (Phase 30
``research.thesis_publications`` marks the scholar's publications; Phase 36 statutory returns).
"""

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import extract, select

from app.core.workflow import engine as workflow_engine
from app.models.academic import Program
from app.models.degrees import DegreeAwarded
from app.models.phd import ResearchScholar, ThesisSubmission, VivaVoce
from app.models.platform import WorkflowInstance
from app.models.students import StudentProgramEnrollment
from app.schemas.phd import PhdAwardOut, PhdAwardRequest
from app.services.phd.common import PhdBase, not_found, now_utc, rule

WF_KEY = "phd.award"
ENTITY = "thesis_submission"


class AwardService(PhdBase):
    async def _thesis(self, tid: uuid.UUID, *, lock: bool = False) -> tuple[ThesisSubmission, ResearchScholar]:
        stmt = select(ThesisSubmission).where(ThesisSubmission.id == tid, ThesisSubmission.institution_id == self.inst)
        if lock:
            stmt = stmt.with_for_update()
        t = (await self.db.execute(stmt)).scalar_one_or_none()
        if t is None:
            raise not_found("Thesis submission")
        return t, await self.scholar(t.scholar_id)

    async def out(self, t: ThesisSubmission, s: ResearchScholar) -> PhdAwardOut:
        m = (await self.meta("thesis", t.id)).get("award") or {}
        return PhdAwardOut(
            scholar_id=s.id,
            thesis_id=t.id,
            scholar_name=await self.scholar_name(s),
            title=t.title,
            status=m.get("status") or "requested",
            date_of_award=date.fromisoformat(m["date_of_award"]) if m.get("date_of_award") else None,
            degree_awarded_id=uuid.UUID(m["degree_awarded_id"]) if m.get("degree_awarded_id") else None,
            certificate_document_id=uuid.UUID(m["certificate"]) if m.get("certificate") else None,
            workflow_instance_id=uuid.UUID(m["workflow_instance_id"]) if m.get("workflow_instance_id") else None,
            etd_due_on=date.fromisoformat(m["etd_due_on"]) if m.get("etd_due_on") else None,
        )

    async def request_award(self, tid: uuid.UUID, body: PhdAwardRequest) -> PhdAwardOut:
        self.require_cell()
        t, s = await self._thesis(tid, lock=True)
        v = (await self.db.execute(select(VivaVoce).where(VivaVoce.thesis_id == t.id))).scalar_one_or_none()
        if v is None or v.result != "recommended":
            raise rule("The viva-voce has not recommended the award", "VIVA_NOT_RECOMMENDED")
        if s.status == "awarded":
            raise rule("The degree is already awarded", "ALREADY_AWARDED")
        council = await self.feature("governance.minutes")
        if council and body.resolution_id is None:
            raise rule("An academic council resolution is required", "RESOLUTION_REQUIRED", 422)
        tm = await self.meta("thesis", t.id)
        if (tm.get("award") or {}).get("status") == "requested":
            raise rule("The award is already requested", "AWARD_PENDING")
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == s.student_program_enrollment_id)
            )
        ).scalar_one()
        award: dict[str, Any] = {
            "status": "requested",
            "date_of_award": body.date_of_award.isoformat(),
            "resolution_id": str(body.resolution_id) if body.resolution_id else None,
        }
        tm["award"] = award
        await self.put_meta("thesis", t.id, tm)
        wf = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=WF_KEY,
            entity_type=ENTITY,
            entity_id=t.id,
            started_by=self.actor_id,
            context={
                "department_id": str(e.department_id),
                "college_id": str(e.college_id),
                "council_resolution": council,
            },
            title=f"PhD award · {await self.scholar_name(s)}"[:200],
        )
        tm = await self.meta("thesis", t.id)
        tm["award"]["workflow_instance_id"] = str(wf.id)
        await self.put_meta("thesis", t.id, tm)
        await self.db.flush()
        return await self.out(t, s)

    async def apply(self, tid: uuid.UUID, approved: bool) -> None:
        """Workflow hook body: award (Phase 18 row, certificate, fellowship close, ETD clock) or rejection."""
        from app.services.phd.fellowship_service import FellowshipService
        from app.services.phd.scholar_service import ScholarService

        t = (
            await self.db.execute(select(ThesisSubmission).where(ThesisSubmission.id == tid).with_for_update())
        ).scalar_one()
        s = await self.scholar_raw(t.scholar_id, lock=True)
        tm = await self.meta("thesis", t.id)
        award = dict(tm.get("award") or {})
        if award.get("status") != "requested":
            return
        if not approved:
            award["status"] = "rejected"
            tm["award"] = award
            await self.put_meta("thesis", t.id, tm)
            return
        e = (
            await self.db.execute(
                select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == s.student_program_enrollment_id)
            )
        ).scalar_one()
        prog = (await self.db.execute(select(Program).where(Program.id == e.program_id))).scalar_one()
        on = date.fromisoformat(award["date_of_award"])
        spec = s.research_area or prog.specialization
        d = DegreeAwarded(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            award_type="phd",
            degree_name=(prog.degree_name or "Doctor of Philosophy")[:120],
            specialization=spec[:120] if spec else None,
            date_of_award=on,
            status="council_approved",
            approved_by=self.actor_id,
            approval_resolution_id=uuid.UUID(award["resolution_id"]) if award.get("resolution_id") else None,
        )
        self.db.add(d)
        await self.db.flush()
        etd_days = await self.rule_int("etd_deadline_days")
        award.update(
            {
                "status": "awarded",
                "degree_awarded_id": str(d.id),
                "awarded_at": now_utc().isoformat(),
                "etd_due_on": (on + timedelta(days=etd_days)).isoformat(),
            }
        )
        svc = ScholarService(self.db, self.principal, self.request, self.inst)
        await svc.set_status(s, "awarded", reason="award approved", force=True)
        await FellowshipService(self.db, self.principal, self.request, self.inst).close_for(s)
        doc = await self.render_doc(
            "phd_provisional_certificate",
            "research_scholar",
            s.id,
            {"award": {"date": on.strftime("%d-%m-%Y")}},
        )
        if doc is not None:
            award["certificate"] = str(doc)
        tm["award"] = award
        await self.put_meta("thesis", t.id, tm)
        sm = await self.meta("scholar", s.id)
        sm["etd_due_on"] = award["etd_due_on"]
        await self.put_meta("scholar", s.id, sm)
        await self.db.flush()
        await self._emit(
            "phd.thesis_awarded",
            {
                "scholar_id": str(s.id),
                "thesis_id": str(t.id),
                "degree_awarded_id": str(d.id),
                "enrollment_id": str(e.id),
                "date_of_award": on.isoformat(),
            },
            "research_scholar",
            s.id,
        )
        await self._notify(
            "phd.awarded",
            [await self.scholar_user(s), *await self.guide_users(s)],
            {
                "scholar": await self.scholar_name(s),
                "date_of_award": on.strftime("%d-%m-%Y"),
                "repository": "Shodhganga",
                "etd_days": etd_days,
            },
        )

    async def get(self, tid: uuid.UUID) -> PhdAwardOut:
        t, s = await self._thesis(tid)
        return await self.out(t, s)

    async def awards(self, year: int | None = None) -> list[dict[str, Any]]:
        stmt = (
            select(DegreeAwarded, ResearchScholar)
            .join(
                ResearchScholar,
                ResearchScholar.student_program_enrollment_id == DegreeAwarded.student_program_enrollment_id,
            )
            .where(
                DegreeAwarded.institution_id == self.inst,
                DegreeAwarded.award_type == "phd",
                DegreeAwarded.status != "cancelled",
                await self.scholar_predicate(),
            )
        )
        if year:
            stmt = stmt.where(extract("year", DegreeAwarded.date_of_award) == year)
        rows = (await self.db.execute(stmt.order_by(DegreeAwarded.date_of_award.desc()))).all()
        cards = await self.enrollment_cards([s.student_program_enrollment_id for _, s in rows])
        return [
            {
                "degree_awarded_id": str(d.id),
                "scholar_id": str(s.id),
                "name": (cards.get(s.student_program_enrollment_id) or {}).get("name"),
                "degree_name": d.degree_name,
                "specialization": d.specialization,
                "date_of_award": d.date_of_award.isoformat() if d.date_of_award else None,
                "status": d.status,
                "etd_due_on": (await self.meta("scholar", s.id)).get("etd_due_on"),
            }
            for d, s in rows
        ]


@workflow_engine.on(WF_KEY, "approved")
async def _approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await AwardService(db, actor, institution_id=instance.institution_id).apply(instance.entity_id, True)


@workflow_engine.on(WF_KEY, "rejected")
async def _rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    await AwardService(db, actor, institution_id=instance.institution_id).apply(instance.entity_id, False)
