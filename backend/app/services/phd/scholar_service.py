"""Research scholars — Prompts/31 §31.6 ``scholar_service`` ({phd.core}).

A scholar row is created on admission into a ``level='phd'`` programme (``student.created`` / ``student.admitted``
consumer: the shell takes the department guide with the most free load) or manually by the research cell. Guide /
co-guide allocation checks the load (``current < max`` — ``faculty_profiles.max_scholars`` when set, else the cadre
rule of ``phd.rules``) under ``FOR UPDATE`` on the guide's ``faculty_profiles`` row (409 ``GUIDE_LOAD_EXCEEDED``).

Status machine ``admitted → coursework → registered → synopsis_submitted → thesis_submitted → under_evaluation →
viva_scheduled → awarded``; ``discontinued`` from any pre-award state (unsatisfactory progress ×2, max duration
exceeded without extension, voluntary). ``registration_date`` is set when coursework completes and
``max_duration_end = registration_date + max_duration_months (+ relaxation for women / PwD)``; the weekly duration
scan warns at max − ``duration_warning_months`` and flags exceeded scholars for a cancellation review. The registration
letter is rendered through Phase 26 ``documents.render('phd_registration_letter', 'research_scholar', id)``.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select

from app.enums.phd import PRE_AWARD, STATUS_ORDER, ScholarStatus
from app.models.academic import Program
from app.models.hr import FacultyProfile, Staff
from app.models.phd import (
    DcMeeting,
    ResearchScholar,
    ScholarFellowship,
    ScholarProgressReport,
    ScholarRequest,
    ThesisSubmission,
    VivaVoce,
)
from app.models.students import StudentProgramEnrollment
from app.schemas.phd import (
    Chip,
    Deadline,
    Discontinue,
    GuideAllocate,
    GuideLoadOut,
    Scholar360,
    ScholarCreate,
    ScholarOut,
    ScholarPortalDashboard,
    ScholarUpdate,
    TimelineEntry,
)
from app.services.documents.render_service import RenderService, register_resolver
from app.services.phd.common import (
    PhdBase,
    add_months,
    forbidden,
    months_between,
    not_found,
    rule,
    staff_name,
)

ENTITY = "research_scholar"


class ScholarService(PhdBase):
    # ---- builders -----------------------------------------------------------------------------------------------------
    async def outs(self, rows: list[ResearchScholar], *, with_relation: bool = False) -> list[ScholarOut]:
        if not rows:
            return []
        cards = await self.enrollment_cards([r.student_program_enrollment_id for r in rows])
        staff = await self.staff_map([x for r in rows for x in (r.guide_staff_id, r.co_guide_staff_id)])
        metas = await self.metas("scholar", [r.id for r in rows])
        today = await self.today()
        warn = await self.rule_int("duration_warning_months")
        out: list[ScholarOut] = []
        for r in rows:
            c = cards.get(r.student_program_enrollment_id) or {}
            m = metas.get(str(r.id)) or {}
            chips: list[Chip] = []
            elapsed = months_between(r.registration_date, today) if r.registration_date else None
            left = months_between(today, r.max_duration_end) if r.max_duration_end else None
            if left is not None and r.status in PRE_AWARD:
                tone = "danger" if left < 0 else "warn" if left <= warn else "ok"
                chips.append(Chip(label="Exceeded" if left < 0 else f"{left} mo left", tone=tone))
            if elapsed is not None:
                chips.append(Chip(label=f"{elapsed} mo since registration", tone="info"))
            if m.get("cancellation_review"):
                chips.append(Chip(label="Cancellation review", tone="danger"))
            out.append(
                ScholarOut(
                    id=r.id,
                    enrollment_id=r.student_program_enrollment_id,
                    student_id=c.get("student_id"),
                    name=c.get("name"),
                    registration_number=c.get("registration_number"),
                    department_id=c.get("department_id"),
                    college_id=c.get("college_id"),
                    guide_staff_id=r.guide_staff_id,
                    guide_name=staff_name(staff.get(r.guide_staff_id)),
                    co_guide_staff_id=r.co_guide_staff_id,
                    co_guide_name=staff_name(staff.get(r.co_guide_staff_id)) if r.co_guide_staff_id else None,
                    external_co_guide=r.external_co_guide,
                    mode=r.mode,
                    fellowship_type=r.fellowship_type,
                    research_area=r.research_area,
                    registration_date=r.registration_date,
                    max_duration_end=r.max_duration_end,
                    coursework_status=r.coursework_status,
                    coursework_exemption_reason=r.coursework_exemption_reason,
                    status=r.status,
                    months_elapsed=elapsed,
                    months_left=left,
                    chips=chips,
                    cancellation_review=bool(m.get("cancellation_review")),
                    relation=await self.relation(r) if with_relation else [],
                    created_at=r.created_at,
                )
            )
        return out

    # ---- queries ------------------------------------------------------------------------------------------------------
    async def query(
        self,
        *,
        status: str | None = None,
        guide_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        q: str | None = None,
        scope: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ScholarOut], int]:
        p = self.principal
        staff_reader = p is None or any(p.has("phd", a) for a in ("guide", "dc", "view_all", "manage"))
        if p is not None and p.has("phd", "self") and not (staff_reader or self.unit_reader() or self.cell()):
            raise forbidden("Scholars use /phd/me")
        stmt = select(ResearchScholar).where(
            ResearchScholar.institution_id == self.inst, await self.scholar_predicate(scope)
        )
        if status:
            stmt = stmt.where(ResearchScholar.status == status)
        if guide_id:
            stmt = stmt.where(
                (ResearchScholar.guide_staff_id == guide_id) | (ResearchScholar.co_guide_staff_id == guide_id)
            )
        if department_id or q:
            stmt = stmt.join(
                StudentProgramEnrollment, StudentProgramEnrollment.id == ResearchScholar.student_program_enrollment_id
            )
            if department_id:
                stmt = stmt.where(StudentProgramEnrollment.department_id == department_id)
            if q:
                from app.models.students import Student

                like = f"%{q.strip()}%"
                stmt = stmt.join(Student, Student.id == StudentProgramEnrollment.student_id).where(
                    Student.first_name.ilike(like)
                    | Student.last_name.ilike(like)
                    | Student.registration_number.ilike(like)
                    | ResearchScholar.research_area.ilike(like)
                )
        total = int((await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        rows = list(
            (
                await self.db.execute(stmt.order_by(ResearchScholar.created_at.desc()).limit(limit).offset(offset))
            ).scalars()
        )
        return await self.outs(rows), total

    async def get(self, sid: uuid.UUID) -> Scholar360:
        s = await self.scholar(sid)
        base = (await self.outs([s], with_relation=True))[0]
        m = await self.meta("scholar", s.id)
        from app.services.phd.coursework_service import CourseworkService
        from app.services.phd.dc_service import DcService
        from app.services.phd.fellowship_service import FellowshipService
        from app.services.phd.thesis_service import ThesisService

        cw = await CourseworkService(self.db, self.principal, self.request, self.inst).summary(s)
        dc = await DcService(self.db, self.principal, self.request, self.inst).committee_out(s)
        fs = await FellowshipService(self.db, self.principal, self.request, self.inst).current_out(s)
        th = await ThesisService(self.db, self.principal, self.request, self.inst).latest_out(s)
        pubs = await self._publications(s)
        ethics = await self._ethics(m.get("ethics_approval_id"))
        return Scholar360(
            **base.model_dump(),
            timeline=[
                TimelineEntry(
                    at=str(t.get("at")),
                    action=str(t.get("action")),
                    by=t.get("by"),
                    detail={k: v for k, v in t.items() if k not in ("at", "action", "by")},
                )
                for t in m.get("timeline") or []
            ],
            coursework=cw,
            committee=dc,
            fellowship=fs,
            thesis=th,
            publications=pubs,
            ethics_approval=ethics,
            documents=[{"kind": k, "document_id": v} for k, v in (m.get("documents") or {}).items()],
        )

    async def timeline_of(self, sid: uuid.UUID) -> list[TimelineEntry]:
        return (await self.get(sid)).timeline

    async def _publications(self, s: ResearchScholar) -> list[dict[str, Any]]:
        from app.models.research import Publication

        rows = (
            await self.db.execute(
                select(Publication)
                .where(Publication.institution_id == self.inst, Publication.scholar_id == s.id)
                .order_by(Publication.year.desc().nullslast())
                .limit(50)
            )
        ).scalars()
        return [
            {
                "id": str(p.id),
                "title": p.title,
                "pub_type": p.pub_type,
                "venue": p.venue,
                "year": p.year,
                "indexing": p.indexing,
                "is_verified": p.is_verified,
            }
            for p in rows
        ]

    async def _ethics(self, aid: Any) -> dict[str, Any] | None:
        if not aid:
            return None
        from app.models.research import EthicsApproval

        a = (
            await self.db.execute(select(EthicsApproval).where(EthicsApproval.id == uuid.UUID(str(aid))))
        ).scalar_one_or_none()
        if a is None:
            return None
        return {
            "id": str(a.id),
            "project_title": a.project_title,
            "decision": a.decision,
            "approval_no": a.approval_no,
            "valid_to": a.valid_to.isoformat() if a.valid_to else None,
        }

    # ---- create / update ----------------------------------------------------------------------------------------------
    async def _phd_enrollment(self, eid: uuid.UUID) -> StudentProgramEnrollment:
        e = await self.enrollment(eid)
        level = (await self.db.execute(select(Program.level).where(Program.id == e.program_id))).scalar_one_or_none()
        if level != "phd":
            raise rule("The enrolment is not in a PhD programme", "NOT_PHD_PROGRAMME", 422)
        return e

    async def create(self, body: ScholarCreate, *, system: bool = False) -> ScholarOut:
        if not system:
            self.require_cell()
        e = await self._phd_enrollment(body.enrollment_id)
        exists = (
            await self.db.execute(
                select(ResearchScholar.id).where(ResearchScholar.student_program_enrollment_id == e.id)
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise rule("A scholar record exists for this enrolment", "SCHOLAR_EXISTS", 409, scholar_id=str(exists))
        await self.staff_row(body.guide_staff_id)
        await self.check_guide_load(body.guide_staff_id)
        if body.co_guide_staff_id:
            if body.co_guide_staff_id == body.guide_staff_id:
                raise rule("The co-guide must differ from the guide", "SAME_GUIDE", 422)
            await self.staff_row(body.co_guide_staff_id)
        s = ResearchScholar(
            institution_id=self.inst,
            student_program_enrollment_id=e.id,
            guide_staff_id=body.guide_staff_id,
            co_guide_staff_id=body.co_guide_staff_id,
            external_co_guide=body.external_co_guide.model_dump(mode="json") if body.external_co_guide else None,
            mode=body.mode.value,
            fellowship_type=body.fellowship_type.value,
            research_area=body.research_area,
            status=ScholarStatus.ADMITTED.value,
        )
        self.db.add(s)
        await self.db.flush()
        await self.scholar_timeline(s, "created", guide_staff_id=str(s.guide_staff_id))
        if body.registration_date:
            await self.register(s, body.registration_date)
        await self._emit(
            "phd.scholar_created",
            {"scholar_id": str(s.id), "enrollment_id": str(e.id), "guide_staff_id": str(s.guide_staff_id)},
            ENTITY,
            s.id,
        )
        await self._guide_allocated(s)
        await self.letter(s)
        await self._audit("create", ENTITY, s.id, None, {"enrollment_id": str(e.id)})
        return (await self.outs([s]))[0]

    async def update(self, sid: uuid.UUID, body: ScholarUpdate) -> ScholarOut:
        s = await self.scholar(sid, lock=True)
        rel = await self.require_relation(s, "guide")
        data = body.model_dump(exclude_unset=True, mode="json")
        m = await self.meta("scholar", s.id)
        if "research_area" in data:
            s.research_area = data["research_area"]
        cell_fields = {"co_guide_staff_id", "external_co_guide", "fellowship_type", "relaxation"}
        if cell_fields & set(data) and not self.cell():
            raise forbidden("Co-guide, fellowship type and relaxations are set by the research cell")
        if "co_guide_staff_id" in data:
            cid = body.co_guide_staff_id
            if cid is not None:
                if cid == s.guide_staff_id:
                    raise rule("The co-guide must differ from the guide", "SAME_GUIDE", 422)
                await self.staff_row(cid)
            s.co_guide_staff_id = cid
        if "external_co_guide" in data:
            s.external_co_guide = data["external_co_guide"]
        if "fellowship_type" in data and data["fellowship_type"]:
            s.fellowship_type = data["fellowship_type"]
        if "relaxation" in data:
            m["relaxation"] = data["relaxation"]
            if s.registration_date:
                s.max_duration_end = await self.max_end(s.registration_date, data["relaxation"], m)
        if "ethics_approval_id" in data:
            m["ethics_approval_id"] = data["ethics_approval_id"]
            if data["ethics_approval_id"]:
                await self._link_ethics(s, uuid.UUID(data["ethics_approval_id"]))
        await self.put_meta("scholar", s.id, m)
        await self.scholar_timeline(s, "updated", fields=sorted(data), by_role=rel[:1])
        await self.db.flush()
        return (await self.outs([s]))[0]

    async def _link_ethics(self, s: ResearchScholar, aid: uuid.UUID) -> None:
        """Phase 30 ethics approvals link to scholars through the ethics side store (``ethics:<id>.scholar_id``)."""
        from app.models.research import EthicsApproval
        from app.services.research.common import ResearchBase

        a = (
            await self.db.execute(
                select(EthicsApproval).where(EthicsApproval.id == aid, EthicsApproval.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if a is None:
            raise not_found("Ethics approval")
        rb = ResearchBase(self.db, None, institution_id=self.inst)
        em = await rb.meta("ethics", a.id)
        em["scholar_id"] = str(s.id)
        await rb.put_meta("ethics", a.id, em)

    async def max_end(self, reg: date, relaxation: str | None, m: dict[str, Any] | None = None) -> date:
        r = await self.rules()
        months = int(r.get("max_duration_months") or 72)
        relax = (r.get("relaxation_months") or {}).get(relaxation or "") if relaxation else None
        months += int(relax or 0)
        months += int((m or {}).get("extension_months") or 0)
        return add_months(reg, months)

    async def register(self, s: ResearchScholar, on: date | None = None) -> None:
        """Coursework done → ``registered`` with ``registration_date`` and ``max_duration_end``."""
        reg = on or await self.today()
        m = await self.meta("scholar", s.id)
        if m.get("relaxation") is None:
            m["relaxation"] = await self._default_relaxation(s)
            await self.put_meta("scholar", s.id, m)
        s.registration_date = reg
        s.max_duration_end = await self.max_end(reg, m.get("relaxation"), m)
        if s.status in STATUS_ORDER and STATUS_ORDER.index(s.status) < STATUS_ORDER.index("registered"):
            await self.set_status(s, ScholarStatus.REGISTERED.value, reason="coursework")
        await self.db.flush()

    async def _default_relaxation(self, s: ResearchScholar) -> str:
        from app.models.students import Student

        st = (
            await self.db.execute(
                select(Student)
                .join(StudentProgramEnrollment, StudentProgramEnrollment.student_id == Student.id)
                .where(StudentProgramEnrollment.id == s.student_program_enrollment_id)
            )
        ).scalar_one_or_none()
        if st is None:
            return "none"
        if st.is_pwd:
            return "pwd"
        return "women" if (st.gender or "").lower() in ("f", "female") else "none"

    async def set_status(self, s: ResearchScholar, to: str, *, reason: str | None = None, force: bool = False) -> None:
        """Forward-only along the lifecycle (``discontinued`` from any pre-award state; a revised thesis may step
        back from ``under_evaluation`` to ``thesis_submitted``)."""
        frm = s.status
        if frm == to:
            return
        if frm in ("awarded", "discontinued") and not force:
            raise rule(f"The scholar is already {frm}", "SCHOLAR_CLOSED")
        backwards = frm in STATUS_ORDER and to in STATUS_ORDER and STATUS_ORDER.index(to) < STATUS_ORDER.index(frm)
        if to != "discontinued" and not force and backwards:
            raise rule(f"Cannot move from {frm} back to {to}", "INVALID_TRANSITION")
        s.status = to
        await self.scholar_timeline(s, "status", **{"from": frm, "to": to, "reason": reason})
        await self.db.flush()
        await self._emit(
            "phd.status_changed", {"scholar_id": str(s.id), "from": frm, "to": to, "reason": reason}, ENTITY, s.id
        )

    # ---- guide --------------------------------------------------------------------------------------------------------
    async def allocate_guide(self, sid: uuid.UUID, body: GuideAllocate, *, via_request: bool = False) -> ScholarOut:
        if not via_request:
            self.require_cell()
        s = await self.scholar_raw(sid, lock=True)
        if s.status not in PRE_AWARD:
            raise rule("Guides change only before the award", "SCHOLAR_CLOSED")
        old = s.guide_staff_id
        if body.guide_staff_id != old:
            await self.staff_row(body.guide_staff_id)
            await self.check_guide_load(body.guide_staff_id, exclude=s.id)
            s.guide_staff_id = body.guide_staff_id
        if body.co_guide_staff_id is not None:
            if body.co_guide_staff_id == s.guide_staff_id:
                raise rule("The co-guide must differ from the guide", "SAME_GUIDE", 422)
            s.co_guide_staff_id = body.co_guide_staff_id
        await self.scholar_timeline(s, "guide_changed", old=str(old), new=str(s.guide_staff_id), reason=body.reason)
        await self.db.flush()
        if old != s.guide_staff_id:
            await self._emit(
                "phd.guide_changed",
                {"scholar_id": str(s.id), "old_guide_staff_id": str(old), "new_guide_staff_id": str(s.guide_staff_id)},
                ENTITY,
                s.id,
            )
            # the DC is reconstituted by the new guide (convenor prompt)
            m = await self.meta("scholar", s.id)
            m["dc_reconstitution_required"] = True
            await self.put_meta("scholar", s.id, m)
        await self._guide_allocated(s)
        return (await self.outs([s]))[0]

    async def _guide_allocated(self, s: ResearchScholar) -> None:
        staff = await self.staff_map([s.guide_staff_id, s.co_guide_staff_id])
        await self._emit(
            "phd.guide_allocated",
            {"scholar_id": str(s.id), "guide_staff_id": str(s.guide_staff_id)},
            ENTITY,
            s.id,
        )
        await self._notify(
            "phd.guide_allocated",
            [await self.scholar_user(s), *await self.guide_users(s)],
            {
                "guide": staff_name(staff.get(s.guide_staff_id)) or "",
                "co_guide": (staff_name(staff.get(s.co_guide_staff_id)) if s.co_guide_staff_id else None) or "",
            },
        )

    async def guide_loads(self, department_id: uuid.UUID | None = None) -> list[GuideLoadOut]:
        p = self.principal
        if not (
            self.cell() or self.unit_reader() or (p is not None and (p.has("phd", "view_all") or p.has("phd", "guide")))
        ):
            raise forbidden("phd:manage, guide, dc or view_all required")
        stmt = (
            select(Staff, FacultyProfile)
            .join(FacultyProfile, FacultyProfile.staff_id == Staff.id)
            .where(Staff.institution_id == self.inst, FacultyProfile.is_phd_guide.is_(True), Staff.deleted_at.is_(None))
        )
        if department_id:
            stmt = stmt.where(Staff.department_id == department_id)
        own_only = not (self.cell() or self.unit_reader() or (p is not None and p.has("phd", "view_all")))
        if own_only:
            stmt = stmt.where(Staff.id == await self.my_staff_id())
        counts: dict[Any, int] = {
            k: int(v)
            for k, v in (
                await self.db.execute(
                    select(ResearchScholar.guide_staff_id, func.count())
                    .where(
                        ResearchScholar.institution_id == self.inst,
                        ResearchScholar.status.not_in(("awarded", "discontinued")),
                    )
                    .group_by(ResearchScholar.guide_staff_id)
                )
            ).all()
        }
        out: list[GuideLoadOut] = []
        for st, fp in (await self.db.execute(stmt.order_by(Staff.first_name))).all():
            mx, cadre = await self.guide_max(st.id)
            cur = int(counts.get(st.id, 0))
            out.append(
                GuideLoadOut(
                    staff_id=st.id,
                    name=staff_name(st),
                    department_id=st.department_id,
                    cadre=cadre or fp.cadre,
                    max=mx,
                    current=cur,
                    available=max(0, mx - cur),
                )
            )
        return out

    # ---- discontinuation ----------------------------------------------------------------------------------------------
    async def discontinue(self, sid: uuid.UUID, body: Discontinue, *, system: bool = False) -> ScholarOut:
        if not system:
            self.require_cell()
        s = await self.scholar_raw(sid, lock=True)
        if s.status not in PRE_AWARD:
            raise rule(f"A {s.status} scholar cannot be discontinued", "SCHOLAR_CLOSED")
        await self.set_status(s, ScholarStatus.DISCONTINUED.value, reason=body.reason)
        await self.scholar_timeline(s, "discontinued", reason=body.reason, remarks=body.remarks)
        for f in (
            await self.db.execute(
                select(ScholarFellowship).where(
                    ScholarFellowship.scholar_id == s.id, ScholarFellowship.status != "closed"
                )
            )
        ).scalars():
            f.status = "closed"
            f.to_on = f.to_on or await self.today()
        await self.db.flush()
        await self._emit("phd.discontinued", {"scholar_id": str(s.id), "reason": body.reason}, ENTITY, s.id)
        return (await self.outs([s]))[0]

    # ---- documents ----------------------------------------------------------------------------------------------------
    async def letter(self, s: ResearchScholar) -> uuid.UUID | None:
        doc = await self.render_doc("phd_registration_letter", ENTITY, s.id)
        if doc is not None:
            m = await self.meta("scholar", s.id)
            m.setdefault("documents", {})["registration_letter"] = str(doc)
            await self.put_meta("scholar", s.id, m)
        return doc

    # ---- portal -------------------------------------------------------------------------------------------------------
    async def me(self) -> Scholar360:
        s = await self.require_my_scholar()
        return await self.get(s.id)

    async def dashboard(self) -> ScholarPortalDashboard:
        from app.services.phd.coursework_service import CourseworkService
        from app.services.phd.fellowship_service import FellowshipService
        from app.services.phd.progress_service import ProgressService
        from app.services.phd.thesis_service import ThesisService
        from app.services.phd.viva_service import VivaService

        s = await self.require_my_scholar()
        base = (await self.outs([s]))[0]
        args = (self.db, self.principal, self.request, self.inst)
        cw = await CourseworkService(*args).summary(s)
        prog = ProgressService(*args)
        periods = await prog.periods(s)
        deadlines = [
            Deadline(label=f"Progress report {p.period_label}", due_on=p.due_on, kind="progress")
            for p in periods
            if p.status == "due"
        ]
        if cw and cw.status in ("pending", "in_progress") and cw.deadline:
            deadlines.append(Deadline(label="Coursework completion", due_on=cw.deadline, kind="coursework"))
        if s.max_duration_end and s.status in PRE_AWARD:
            deadlines.append(Deadline(label="Maximum duration", due_on=s.max_duration_end, kind="duration"))
        etd_due = (await self.meta("scholar", s.id)).get("etd_due_on")
        if etd_due and s.status == "awarded":
            deadlines.append(Deadline(label="ETD upload", due_on=date.fromisoformat(etd_due), kind="etd"))
        pct = None
        if s.registration_date and s.max_duration_end:
            span = max(1, (s.max_duration_end - s.registration_date).days)
            pct = max(0, min(100, round(((await self.today()) - s.registration_date).days * 100 / span)))
        latest = (
            await self.db.execute(
                select(ScholarProgressReport)
                .where(ScholarProgressReport.scholar_id == s.id)
                .order_by(ScholarProgressReport.submitted_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        recs: list[dict[str, Any]] = []
        for mt in (
            await self.db.execute(select(DcMeeting).where(DcMeeting.scholar_id == s.id, DcMeeting.status == "approved"))
        ).scalars():
            recs += [dict(r, meeting_no=mt.meeting_no) for r in mt.recommendations or [] if not r.get("done")]
        th = await ThesisService(*args).latest_out(s)
        viva = None
        if th is not None:
            v = (await self.db.execute(select(VivaVoce).where(VivaVoce.thesis_id == th.id))).scalar_one_or_none()
            if v is not None:
                viva = (await VivaService(*args).outs([v]))[0]
        open_req = int(
            (
                await self.db.execute(
                    select(func.count()).where(
                        ScholarRequest.scholar_id == s.id, ScholarRequest.status.in_(("requested", "in_review"))
                    )
                )
            ).scalar_one()
        )
        return ScholarPortalDashboard(
            scholar=base,
            coursework=cw,
            deadlines=sorted(deadlines, key=lambda d: d.due_on),
            duration_pct=pct,
            latest_report=(await prog.outs([latest]))[0] if latest is not None else None,
            open_recommendations=recs[:20],
            fellowship=await FellowshipService(*args).current_out(s),
            thesis=th,
            viva=viva,
            open_requests=open_req,
        )

    # ---- admission consumer -------------------------------------------------------------------------------------------
    async def on_admitted(self, enrollment_id: uuid.UUID) -> uuid.UUID | None:
        """A PhD admission → scholar shell with the department guide holding the most free load (none free → the
        research cell is told to allocate manually)."""
        e = (
            await self.db.execute(select(StudentProgramEnrollment).where(StudentProgramEnrollment.id == enrollment_id))
        ).scalar_one_or_none()
        if e is None:
            return None
        level = (await self.db.execute(select(Program.level).where(Program.id == e.program_id))).scalar_one_or_none()
        if level != "phd":
            return None
        if (
            await self.db.execute(
                select(ResearchScholar.id).where(ResearchScholar.student_program_enrollment_id == e.id)
            )
        ).scalar_one_or_none():
            return None
        best: tuple[int, uuid.UUID] | None = None
        for gl in await ScholarService(self.db, None, institution_id=self.inst).guide_loads(e.department_id):
            if gl.available > 0 and (best is None or gl.available > best[0]):
                best = (gl.available, gl.staff_id)
        if best is None:
            # no guide with free load in the department — the research cell allocates manually
            await self._emit("phd.guide_unallocated", {"enrollment_id": str(e.id)}, "student_program_enrollment", e.id)
            return None
        out = await self.create(
            ScholarCreate(enrollment_id=e.id, guide_staff_id=best[1]),
            system=True,
        )
        return out.id

    # ---- Beat ---------------------------------------------------------------------------------------------------------
    async def duration_scan(self) -> int:
        """Weekly: warn at max − ``duration_warning_months``; exceeded without extension → cancellation review."""
        today = await self.today()
        warn = await self.rule_int("duration_warning_months")
        n = 0
        rows = (
            await self.db.execute(
                select(ResearchScholar).where(
                    ResearchScholar.institution_id == self.inst,
                    ResearchScholar.status.in_(tuple(PRE_AWARD)),
                    ResearchScholar.max_duration_end.is_not(None),
                    ResearchScholar.max_duration_end <= add_months(today, warn),
                )
            )
        ).scalars()
        for s in rows:
            m = await self.meta("scholar", s.id)
            left = months_between(today, s.max_duration_end) if s.max_duration_end else 0
            key = f"warned_{s.max_duration_end}"
            if not m.get(key):
                m[key] = today.isoformat()
                await self.put_meta("scholar", s.id, m)
                name = await self.scholar_name(s)
                await self._emit(
                    "phd.duration_warning",
                    {"scholar_id": str(s.id), "max_duration_end": str(s.max_duration_end), "months_left": left},
                    ENTITY,
                    s.id,
                )
                await self._notify(
                    "phd.duration_warning",
                    [await self.scholar_user(s), *await self.guide_users(s)],
                    {"scholar": name, "max_end": str(s.max_duration_end), "months": max(0, left)},
                )
                n += 1
            if s.max_duration_end and s.max_duration_end < today and not m.get("cancellation_review"):
                from app.services.phd.progress_service import ProgressService

                await ProgressService(self.db, None, institution_id=self.inst).flag_cancellation(
                    s, reason="max_duration_exceeded"
                )
        await self.db.flush()
        return n


@register_resolver(ENTITY)
async def _scholar_ctx(svc: RenderService, sid: uuid.UUID) -> tuple[dict[str, Any], str | None, uuid.UUID | None]:
    s = (await svc.db.execute(select(ResearchScholar).where(ResearchScholar.id == sid))).scalar_one()
    ctx, ptype, pid = await svc.enrolment_ctx(s.student_program_enrollment_id)
    staff = {
        x.id: x
        for x in (
            await svc.db.execute(
                select(Staff).where(Staff.id.in_([i for i in (s.guide_staff_id, s.co_guide_staff_id) if i]))
            )
        ).scalars()
    }
    ctx["scholar"] = {
        "mode": s.mode.replace("_", "-"),
        "guide": staff_name(staff.get(s.guide_staff_id)) or "",
        "co_guide": (
            staff_name(staff.get(s.co_guide_staff_id))
            if s.co_guide_staff_id
            else (s.external_co_guide or {}).get("name", "")
        ),
        "research_area": s.research_area or "",
        "registration_date": s.registration_date.strftime("%d-%m-%Y") if s.registration_date else "",
        "max_duration_end": s.max_duration_end.strftime("%d-%m-%Y") if s.max_duration_end else "",
        "fellowship": s.fellowship_type.upper(),
        "status": s.status,
    }
    th = (
        await svc.db.execute(
            select(ThesisSubmission)
            .where(ThesisSubmission.scholar_id == s.id)
            .order_by(ThesisSubmission.submitted_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ctx["thesis"] = {
        "title": th.title if th else "",
        "submitted_on": th.submitted_at.strftime("%d-%m-%Y") if th else "",
        "similarity": str(th.similarity_pct) if th and th.similarity_pct is not None else "",
    }
    ctx.setdefault("award", {"date": ""})
    return ctx, ptype, pid
