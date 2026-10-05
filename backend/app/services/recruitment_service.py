"""Recruitment — Prompts/06 §06.6 ``recruitment_service.py`` ({hr.recruitment}).

Rules
1. **Postings** (``draft → open → closed | filled | cancelled``): the reservation JSON ``{roster, vacancies:{code: n},
   backlog}`` must use the pack's category codes and add up to ``vacancies`` (422); with {hr.reservation_roster} every
   reserved category must receive at least its roster entitlement ``⌊vacancies × pct ÷ 100⌋`` (100-/200-point roster
   helper, backlog added) → 422. ``publish`` opens it (``recruitment.posted``) and lists it on the public careers page.
2. **Public application** (``/public/careers/{posting_id}/apply``): open postings only (409 otherwise), one per e-mail
   per posting (409), acknowledgement e-mail to the applicant (direct contact).
3. **Pipeline**: applied → screened (screening score) → shortlisted (rule: minimum score / top N, or manual ids) →
   interviewed (panel scores: each member's criteria average, weighted by the member's weight) → selected → offered
   (offer terms kept on the application; the letter is rendered by Phase 26 templates) → joined (a ``staff`` row is
   created through ``StaffService.create`` and linked; the offered basic becomes the first salary structure; the
   posting is ``filled`` when every vacancy has joined). Any stage may be ``rejected``.
4. Panel members (``interview_panels.members[].user_id``) may score without ``hr:recruitment``.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.enums.hr import APPLICATION_PIPELINE
from app.models.hr import InterviewPanel, InterviewScore, JobApplication, JobPosting
from app.repositories.recruitment_repository import ApplicationRepository, PanelRepository, PostingRepository
from app.schemas.hr import StaffCreate
from app.schemas.payroll import SalaryStructureIn
from app.schemas.recruitment import (
    JobApplicationIn,
    JobApplicationOut,
    JobPostingIn,
    JobPostingOut,
    JoinIn,
    OfferIn,
    PanelIn,
    PanelOut,
    PublicApplicationResult,
    PublicPostingOut,
    ReservationIn,
    ScoreIn,
    ScoreOut,
    ScreenIn,
    ShortlistIn,
    StatusChangeResult,
)
from app.services.hr.common import HrServiceBase, snap
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta

POSTING_KEYS = ("title", "department_id", "cadre", "vacancies", "status", "opens_at", "closes_at")


def roster_entitlement(vacancies: int, roster: dict[str, Any]) -> dict[str, int]:
    """Cumulative 100-/200-point roster entitlement: ⌊v × pct / 100⌋ per reserved category, the rest unreserved."""
    pcts: dict[str, float] = roster.get("percentages") or {}
    out = {code: int(vacancies * pct // 100) for code, pct in pcts.items()}
    out[roster.get("unreserved", "GEN")] = vacancies - sum(out.values())
    return out


class RecruitmentService(HrServiceBase):
    audit_module = "recruitment"

    def __init__(self, db: Any, principal: Any, request: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, request, institution_id)
        self.postings = PostingRepository(db, principal, self.inst)
        self.applications = ApplicationRepository(db, principal, self.inst)
        self.panels = PanelRepository(db, principal, self.inst)

    # ---- rule 1 -------------------------------------------------------------------------------------------------
    async def _validate_reservation(self, vacancies: int, res: ReservationIn | None) -> dict[str, Any] | None:
        if res is None:
            return None
        pack = await self.pack()
        codes = {c.code for c in pack.categories}
        unknown = sorted(set(res.vacancies) - codes)
        if unknown:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Unknown categories: {', '.join(unknown)}",
                {"field": "reservation.vacancies", "allowed": sorted(codes)},
            )
        if any(n < 0 for n in res.vacancies.values()):
            raise APIError(
                422, ErrorCode.VALIDATION, "Category posts cannot be negative", {"field": "reservation.vacancies"}
            )
        if sum(res.vacancies.values()) != vacancies:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Reserved + unreserved posts ({sum(res.vacancies.values())}) must equal vacancies ({vacancies})",
                {"field": "reservation.vacancies"},
            )
        if res.roster != "none" and await is_enabled(self.inst, "hr.reservation_roster") and pack.hr.roster:
            due = roster_entitlement(vacancies, pack.hr.roster)
            unreserved = pack.hr.roster.get("unreserved", "GEN")
            short = {
                code: {"required": n + res.backlog.get(code, 0), "given": res.vacancies.get(code, 0)}
                for code, n in due.items()
                if code != unreserved and res.vacancies.get(code, 0) < n + res.backlog.get(code, 0)
            }
            if short:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"The {res.roster.replace('_', '-')} roster is not honoured",
                    {"field": "reservation.vacancies", "shortfall": short, "entitlement": due},
                )
        return res.model_dump()

    async def list_postings(
        self, params: PageParams, status: str | None, department_id: uuid.UUID | None, q: str | None
    ) -> tuple[list[JobPostingOut], PaginationMeta]:
        stmt = self.postings.filtered(status=status, department_id=department_id, q=q)
        if not params.sort:
            params = params.model_copy(update={"sort": "-created_at"})
        rows, pagination = await self.postings.paginate(stmt, params)
        return await self._postings_out(list(rows)), pagination

    async def _postings_out(self, rows: list[JobPosting]) -> list[JobPostingOut]:
        counts = await self.postings.application_counts([r.id for r in rows])
        depts = await self.staff_repo.department_rows([r.department_id for r in rows if r.department_id])
        out = []
        for r in rows:
            o = JobPostingOut.model_validate(r)
            o.pipeline = counts.get(r.id, {})
            o.department_code = depts[r.department_id].code if r.department_id in depts else None
            out.append(o)
        return out

    async def create_posting(self, body: JobPostingIn) -> JobPostingOut:
        values = await self._posting_values(body)
        row = await self.postings.create(
            institution_id=self.inst, status="draft", created_by=self.principal.id, **values
        )
        await self._audit("create", "job_posting", row.id, None, snap(row, POSTING_KEYS))
        return (await self._postings_out([row]))[0]

    async def update_posting(self, posting_id: uuid.UUID, body: JobPostingIn) -> JobPostingOut:
        row = await self.postings.get_one(posting_id, for_update=True)
        if row.status not in ("draft", "open"):
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The posting is {row.status}")
        values = await self._posting_values(body)
        old = snap(row, POSTING_KEYS)
        await self.postings.update(row, **values)
        await self._audit("update", "job_posting", row.id, old, snap(row, POSTING_KEYS))
        return (await self._postings_out([row]))[0]

    async def _posting_values(self, body: JobPostingIn) -> dict[str, Any]:
        if body.closes_at and body.opens_at and body.closes_at <= body.opens_at:
            raise APIError(422, ErrorCode.VALIDATION, "closes_at must be after opens_at", {"field": "closes_at"})
        college_id = body.college_id
        if body.department_id:
            dept = (await self.staff_repo.department_rows([body.department_id])).get(body.department_id)
            if dept is None:
                raise APIError(422, ErrorCode.VALIDATION, "Unknown department", {"field": "department_id"})
            college_id = dept.college_id
        return {
            "title": body.title,
            "college_id": college_id,
            "department_id": body.department_id,
            "cadre": body.cadre.value if body.cadre else None,
            "vacancies": body.vacancies,
            "reservation": await self._validate_reservation(body.vacancies, body.reservation),
            "qualifications": body.qualifications,
            "description": body.description,
            "opens_at": body.opens_at,
            "closes_at": body.closes_at,
        }

    async def set_posting_status(self, posting_id: uuid.UUID, action: str) -> JobPostingOut:
        row = await self.postings.get_one(posting_id, for_update=True)
        allowed = {"publish": ("draft", "closed"), "close": ("open",), "cancel": ("draft", "open", "closed")}
        if row.status not in allowed[action]:
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Cannot {action} a {row.status} posting")
        old = row.status
        row.status = {"publish": "open", "close": "closed", "cancel": "cancelled"}[action]
        if action == "publish" and row.opens_at is None:
            row.opens_at = datetime.now(UTC)
        await self.db.flush()
        await self._audit(action, "job_posting", row.id, {"status": old}, {"status": row.status})
        if action == "publish":
            await self._emit(
                "recruitment.posted",
                {"posting_id": str(row.id), "title": row.title, "vacancies": row.vacancies},
                "job_posting",
                row.id,
            )
            await self._notify(
                "recruitment.posted",
                [],
                {
                    "title": row.title,
                    "vacancies": str(row.vacancies),
                    "closes_at": row.closes_at.date().isoformat() if row.closes_at else "further notice",
                },
                audience={"roles": ["hr_officer"]},
            )
        return (await self._postings_out([row]))[0]

    # ---- rule 2: public -----------------------------------------------------------------------------------------
    async def public_postings(self) -> list[PublicPostingOut]:
        rows = await self.postings.open_postings()
        depts = await self.staff_repo.department_rows([r.department_id for r in rows if r.department_id])
        now = datetime.now(UTC)
        return [
            PublicPostingOut(
                id=r.id,
                title=r.title,
                department=depts[r.department_id].name if r.department_id in depts else None,
                cadre=r.cadre,
                vacancies=r.vacancies,
                reservation=r.reservation,
                qualifications=r.qualifications,
                description=r.description,
                closes_at=r.closes_at,
            )
            for r in rows
            if r.closes_at is None or r.closes_at > now
        ]

    async def public_apply(self, posting_id: uuid.UUID, body: JobApplicationIn) -> PublicApplicationResult:
        posting = await self.postings.get_one(posting_id)
        now = datetime.now(UTC)
        if posting.status != "open" or (posting.closes_at and posting.closes_at <= now):
            raise APIError(409, ErrorCode.RULE_VIOLATION, "This posting is not accepting applications")
        if body.category:
            codes = {c.code for c in (await self.pack()).categories}
            if body.category not in codes:
                raise APIError(
                    422, ErrorCode.VALIDATION, "Unknown category", {"field": "category", "allowed": sorted(codes)}
                )
        if await self.applications.duplicate(posting.id, str(body.applicant.email)):
            raise APIError(409, ErrorCode.CONFLICT, "You have already applied for this posting")
        applicant = body.applicant.model_dump(mode="json")
        app = await self.applications.create(
            institution_id=self.inst,
            posting_id=posting.id,
            applicant=applicant,
            documents=body.documents,
            category=body.category,
            api_score=body.api_score,
            status="applied",
        )
        reference = f"JA-{str(app.id)[:8].upper()}"
        app.applicant = {**applicant, "reference": reference}
        await self.db.flush()
        await self._audit(
            "apply", "job_application", app.id, None, {"posting_id": str(posting.id), "category": body.category}
        )
        await self._notify(
            "recruitment.application_received",
            [],
            {"name": body.applicant.name, "title": posting.title, "reference": reference},
            audience={"direct_contacts": [{"channel": "email", "to": str(body.applicant.email)}]},
        )
        return PublicApplicationResult(reference=reference, status="applied")

    # ---- rule 3: pipeline ---------------------------------------------------------------------------------------
    async def applications_for(self, posting_id: uuid.UUID, status: str | None) -> list[JobApplicationOut]:
        await self.postings.get_one(posting_id)
        return await self._apps_out(list(await self.applications.for_posting(posting_id, status)))

    async def _apps_out(self, rows: list[JobApplication]) -> list[JobApplicationOut]:
        from app.core.authz.masking import mask_pii

        totals = await self._interview_totals([r.posting_id for r in rows])
        out = []
        for r in rows:
            o = JobApplicationOut.model_validate(r)
            a = r.applicant or {}
            o.name, o.email, o.phone = a.get("name"), a.get("email"), a.get("phone")
            o.staff_id = uuid.UUID(a["staff_id"]) if a.get("staff_id") else None
            o.interview_total = totals.get(r.id)
            unmask = self.principal is not None and self.principal.has("recruitment", "manage")
            if not unmask:
                o.applicant = {
                    k: v
                    for k, v in a.items()
                    if k in ("name", "highest_qualification", "experience_months", "publications", "reference", "offer")
                }
                o = mask_pii(o, self.principal, "hr")
            out.append(o)
        return out

    async def _interview_totals(self, posting_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        panel_ids: list[uuid.UUID] = []
        for pid in set(posting_ids):
            panel_ids += [p.id for p in await self.panels.for_posting(pid)]
        scores: dict[uuid.UUID, list[Decimal]] = {}
        for s in await self.panels.scores_for(panel_ids):
            if s.total is not None:
                scores.setdefault(s.application_id, []).append(Decimal(s.total))
        return {k: (Decimal(sum(v)) / len(v)).quantize(Decimal("0.01")) for k, v in scores.items()}

    async def _transition(self, app: JobApplication, to: str, allowed_from: tuple[str, ...]) -> None:
        if app.status not in allowed_from:
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Cannot move a {app.status} application to {to}")
        old = app.status
        app.status = to
        await self.db.flush()
        await self._audit(to, "job_application", app.id, {"status": old}, {"status": to})

    async def screen(self, application_id: uuid.UUID, body: ScreenIn) -> StatusChangeResult:
        app = await self.applications.get_one(application_id, for_update=True)
        app.screening_score = body.screening_score
        if body.remarks:
            app.applicant = {**(app.applicant or {}), "screening_remarks": body.remarks}
        await self._transition(app, "screened", ("applied", "screened"))
        return StatusChangeResult(id=app.id, status=app.status)

    async def shortlist(self, application_id: uuid.UUID, body: ShortlistIn) -> StatusChangeResult:
        """``application_id`` names one application of the posting; the rule (or the manual ids) applies to the posting."""
        anchor = await self.applications.get_one(application_id)
        candidates = [a for a in await self.applications.for_posting(anchor.posting_id) if a.status == "screened"]
        if body.application_ids:
            picked = [a for a in candidates if a.id in set(body.application_ids)]
        elif body.min_screening_score is not None or body.limit is not None:
            picked = [
                a
                for a in candidates
                if body.min_screening_score is None or Decimal(a.screening_score or 0) >= body.min_screening_score
            ]
            picked.sort(key=lambda a: Decimal(a.screening_score or 0), reverse=True)
            if body.limit:
                picked = picked[: body.limit]
        else:
            picked = [a for a in candidates if a.id == anchor.id]
        if not picked:
            raise APIError(409, ErrorCode.RULE_VIOLATION, "No screened application matches the shortlist rule")
        for a in picked:
            await self._transition(a, "shortlisted", ("screened",))
        return StatusChangeResult(
            id=anchor.id, status="shortlisted" if anchor in picked else anchor.status, changed=len(picked)
        )

    async def select(self, application_id: uuid.UUID) -> StatusChangeResult:
        app = await self.applications.get_one(application_id, for_update=True)
        await self._transition(app, "selected", ("shortlisted", "interviewed"))
        await self._emit(
            "recruitment.selected",
            {"application_id": str(app.id), "posting_id": str(app.posting_id)},
            "job_application",
            app.id,
        )
        return StatusChangeResult(id=app.id, status=app.status)

    async def reject(self, application_id: uuid.UUID) -> StatusChangeResult:
        app = await self.applications.get_one(application_id, for_update=True)
        await self._transition(app, "rejected", tuple(s for s in APPLICATION_PIPELINE if s != "joined"))
        return StatusChangeResult(id=app.id, status=app.status)

    async def offer(self, application_id: uuid.UUID, body: OfferIn) -> StatusChangeResult:
        app = await self.applications.get_one(application_id, for_update=True)
        if body.designation_id:
            from app.repositories.staff_repository import DesignationRepository

            await DesignationRepository(self.db, self.principal, self.inst).get_one(body.designation_id)
        app.applicant = {**(app.applicant or {}), "offer": body.model_dump(mode="json")}
        await self._transition(app, "offered", ("selected",))
        return StatusChangeResult(id=app.id, status=app.status)

    async def join(self, application_id: uuid.UUID, body: JoinIn) -> StatusChangeResult:
        from app.repositories.staff_repository import DesignationRepository
        from app.services.payroll_service import PayrollService
        from app.services.staff_service import StaffService

        app = await self.applications.get_one(application_id, for_update=True)
        if app.status != "offered":
            raise APIError(
                409, ErrorCode.RULE_VIOLATION, f"Only an offered application can join (this one is {app.status})"
            )
        posting = await self.postings.get_one(app.posting_id, for_update=True)
        a = app.applicant or {}
        offer = a.get("offer") or {}
        designation_id = body.designation_id or (
            uuid.UUID(offer["designation_id"]) if offer.get("designation_id") else None
        )
        if designation_id is None and posting.cadre:
            d = await DesignationRepository(self.db, self.principal, self.inst).by_cadre(posting.cadre)
            designation_id = d.id if d else None
        parts = str(a.get("name", "")).split()
        result = await StaffService(self.db, self.principal, self.request, self.inst).create(
            StaffCreate(
                first_name=parts[0] if parts else "Applicant",
                last_name=" ".join(parts[1:]) or None,
                college_id=posting.college_id,
                department_id=posting.department_id,
                designation_id=designation_id,
                employment_type=body.employment_type,
                email=a.get("email"),
                phone=a.get("phone"),
                gender=a.get("gender"),
                dob=a.get("dob"),
                joining_date=body.joining_date,
            )
        )
        staff_id = result.staff.id
        if offer.get("basic_paise"):
            await PayrollService(self.db, self.principal, self.request, self.inst).add_structure(
                staff_id,
                SalaryStructureIn(effective_from=body.joining_date, basic_paise=int(offer["basic_paise"])),
                reason="appointment",
            )
        app.applicant = {**a, "staff_id": str(staff_id), "employee_id": result.staff.employee_id}
        await self._transition(app, "joined", ("offered",))
        if await self.applications.joined_count(posting.id) >= posting.vacancies:
            posting.status = "filled"
            await self.db.flush()
        await self._emit(
            "recruitment.joined",
            {"application_id": str(app.id), "staff_id": str(staff_id), "posting_id": str(posting.id)},
            "job_application",
            app.id,
        )
        return StatusChangeResult(id=app.id, status=app.status, staff_id=staff_id)

    # ---- panels -------------------------------------------------------------------------------------------------
    async def list_panels(self, posting_id: uuid.UUID) -> list[PanelOut]:
        await self.postings.get_one(posting_id)
        return [PanelOut.model_validate(p) for p in await self.panels.for_posting(posting_id)]

    async def create_panel(self, posting_id: uuid.UUID, body: PanelIn) -> PanelOut:
        if not self.principal.has("hr", "recruitment") and not self.principal.has("recruitment", "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Requires hr:recruitment")
        posting = await self.postings.get_one(posting_id)
        members = []
        for m in body.members:
            user = await self.staff_repo.user(m.user_id)
            if user is None or user.institution_id != self.inst:
                raise APIError(
                    422, ErrorCode.VALIDATION, "Unknown panel member", {"field": "members", "user_id": str(m.user_id)}
                )
            members.append(
                {
                    "user_id": str(user.id),
                    "name": user.display_name or user.username,
                    "role": m.role,
                    "weight": m.weight,
                }
            )
        panel = InterviewPanel(
            institution_id=self.inst,
            posting_id=posting.id,
            scheduled_at=body.scheduled_at,
            venue=body.venue,
            members=members,
        )
        await self.panels.add(panel)
        await self._audit(
            "panel", "job_posting", posting.id, None, {"panel_id": str(panel.id), "members": len(members)}
        )
        return PanelOut.model_validate(panel)

    async def score(self, panel_id: uuid.UUID, body: ScoreIn) -> ScoreOut:
        panel = await self.panels.get_one(panel_id)
        member_ids = {str(m.get("user_id")) for m in panel.members}
        is_member = str(self.principal.id) in member_ids
        if not is_member and not (
            self.principal.has("hr", "recruitment") or self.principal.has("recruitment", "manage")
        ):
            raise APIError(404, ErrorCode.NOT_FOUND, "Interview panel not found")
        app = await self.applications.get_one(body.application_id, for_update=True)
        if app.posting_id != panel.posting_id:
            raise APIError(
                422, ErrorCode.VALIDATION, "The application belongs to another posting", {"field": "application_id"}
            )
        if app.status not in ("shortlisted", "interviewed"):
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"A {app.status} application cannot be scored")
        if any(not 0 <= v <= 100 for v in body.scores.values()):
            raise APIError(422, ErrorCode.VALIDATION, "Scores range 0–100", {"field": "scores"})
        row = await self.panels.score(panel.id, app.id, for_update=True)
        scorer = str(self.principal.id) if is_member else f"hr:{self.principal.id}"
        per_member = dict(row.scores) if row else {}
        per_member[scorer] = {"scores": body.scores, "remarks": body.remarks}
        weights = {str(m.get("user_id")): float(m.get("weight") or 1) for m in panel.members}
        num = den = 0.0
        for who, entry in per_member.items():
            vals = list((entry.get("scores") or {}).values())
            if not vals:
                continue
            w = weights.get(who, 1.0)
            num += w * sum(vals) / len(vals)
            den += w
        total = Decimal(str(round(num / den, 2))) if den else None
        if row is None:
            row = InterviewScore(
                institution_id=self.inst,
                panel_id=panel.id,
                application_id=app.id,
                scores=per_member,
                total=total,
                remarks=body.remarks,
                recorded_by=self.principal.id,
            )
            await self.panels.add(row)
        else:
            row.scores, row.total, row.remarks, row.recorded_by = per_member, total, body.remarks, self.principal.id
            await self.db.flush()
        if app.status == "shortlisted":
            await self._transition(app, "interviewed", ("shortlisted",))
        return ScoreOut(
            panel_id=panel.id, application_id=app.id, scores=per_member, total=total, members_scored=len(per_member)
        )
