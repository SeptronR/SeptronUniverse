"""Appraisal (PBAS) and CAS promotions — Prompts/06 §06.6 ``appraisal_service.py``.

Appraisal ({hr.appraisal_pbas})
1. A member records the self-assessment for an academic year (default: the current one) against the pack's PBAS
   schema ``{category: {item: value}}``; research items marked ``auto`` are pre-filled from the Phase 30 tables
   (``publications``, ``research_projects``, ``faculty_developments`` of that year — 0 until they hold rows) unless
   the member typed a value. ``self_score = Σ_category min(max, Σ_item min(item max, value × per_unit))``.
2. **Submit** → ``submitted`` + workflow ``hr.appraisal`` (HOD of the department → HR); the HOD's staff row becomes the
   reviewer. **Review** acts on the workflow step (approvers only — engine 403 otherwise) with an optional reviewer
   score (the HOD step sets ``reviewed``); final approval → ``approved`` with ``final_score`` (reviewer score, else the
   self score); a rejection closes the cycle as ``reviewed`` (the workflow cannot restart for the same record).

CAS ({hr.cas_promotions})
3. A member applies for the next cadre of the pack path (``assistant → associate → professor``); the eligibility date
   is the start of the current cadre (last ``promotion`` service-book entry, else the joining date) + the pack years;
   the API breakdown comes from the latest appraisal (``research.api_score`` when Phase 30 publishes it). Only one
   open application per member (409).
4. **Submit** (eligible only, 422 before the date) → workflow ``hr.cas`` (HR); **screen** / interview statuses by HR;
   **decide** acts on the workflow — approval promotes: designation of the target cadre (or the chosen one), faculty
   profile cadre, a new salary structure (chosen basic, else +3 %), a ``promotion`` service-book entry, ``cas.approved``.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.hr import Appraisal, CasApplication, Staff
from app.models.platform import WorkflowInstance
from app.repositories.appraisal_repository import AcademicYearLookup, AppraisalRepository, CasRepository
from app.repositories.hr_scope import hr_visibility
from app.repositories.payroll_repository import SalaryStructureRepository
from app.repositories.staff_repository import DesignationRepository, StaffRecordsRepository
from app.schemas.payroll import SalaryStructureIn
from app.schemas.recruitment import (
    AppraisalOut,
    AppraisalReviewIn,
    AppraisalSelfIn,
    CasApplicationIn,
    CasApplicationOut,
    CasDecideIn,
    CasScreenIn,
)
from app.services.hr.common import HrServiceBase
from app.utils.pagination import PageParams
from app.utils.response import PaginationMeta, VisibilityMeta

APPRAISAL_KEY = "hr.appraisal"
CAS_KEY = "hr.cas"
AUTO_SQL = {
    "publications": "SELECT COUNT(*) FROM publications WHERE staff_id = :s AND (year IS NULL OR year BETWEEN :y1 AND :y2)",
    "research_projects": "SELECT COUNT(*) FROM research_projects WHERE pi_staff_id = :s AND (start_on IS NULL OR start_on <= :d2)",
    "faculty_developments": "SELECT COUNT(*) FROM faculty_developments WHERE staff_id = :s AND (from_on IS NULL OR from_on BETWEEN :d1 AND :d2)",
}


def pbas_score(schema: dict[str, Any], values: dict[str, dict[str, float]]) -> tuple[Decimal, dict[str, float]]:
    breakdown: dict[str, float] = {}
    for cat, spec in schema.items():
        cat_total = 0.0
        for item, ispec in (spec.get("items") or {}).items():
            v = float((values.get(cat) or {}).get(item, 0) or 0)
            cat_total += min(float(ispec.get("max", 0)), v * float(ispec.get("per_unit", 1)))
        breakdown[cat] = round(min(float(spec.get("max", cat_total)), cat_total), 2)
    return Decimal(str(round(sum(breakdown.values()), 2))), breakdown


class AppraisalService(HrServiceBase):
    audit_module = "hr"

    def __init__(self, db: Any, principal: Any, request: Any = None, institution_id: uuid.UUID | None = None):
        super().__init__(db, principal, request, institution_id)
        self.repo = AppraisalRepository(db, principal, self.inst)
        self.cas = CasRepository(db, principal, self.inst)
        self.years = AcademicYearLookup(db, self.inst)
        self.records = StaffRecordsRepository(db)

    # ---- appraisal ----------------------------------------------------------------------------------------------
    async def list_page(
        self, params: PageParams, scope: str | None, status: str | None, academic_year_id: uuid.UUID | None
    ) -> tuple[list[AppraisalOut], PaginationMeta, VisibilityMeta]:
        stmt = self.repo.filtered(scope=scope, status=status, academic_year_id=academic_year_id)
        if not params.sort:
            params = params.model_copy(update={"sort": "-updated_at"})
        rows, pagination = await self.repo.paginate(stmt, params)
        return await self._out(list(rows)), pagination, hr_visibility(self.principal, "appraisals")

    async def get(self, appraisal_id: uuid.UUID) -> AppraisalOut:
        return (await self._out([await self.repo.get_visible(appraisal_id)]))[0]

    async def _out(self, rows: list[Appraisal]) -> list[AppraisalOut]:
        names = await self.staff_repo.names([r.staff_id for r in rows])
        years = await self.years.names([r.academic_year_id for r in rows])
        schema = (await self.pack()).hr.pbas_schema
        out = []
        for r in rows:
            o = AppraisalOut.model_validate(r)
            o.staff_name, o.employee_id = names.get(r.staff_id, (None, None))
            o.academic_year = years.get(r.academic_year_id)
            _, o.breakdown = pbas_score(schema, (r.self_assessment or {}).get("values", {}))
            o.auto_filled = (r.self_assessment or {}).get("auto", {})
            out.append(o)
        return out

    async def save_self(self, body: AppraisalSelfIn) -> AppraisalOut:
        staff = await self.my_staff()
        assert staff is not None
        year = await (
            self.years.get(body.academic_year_id) if body.academic_year_id else self.years.current(staff.college_id)
        )
        if year is None:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "No academic year to appraise (set a current academic year)",
                {"field": "academic_year_id"},
            )
        schema = (await self.pack()).hr.pbas_schema
        unknown = sorted(
            f"{c}.{i}"
            for c, items in body.self_assessment.items()
            for i in items
            if i not in (schema.get(c, {}).get("items") or {})
        )
        if unknown:
            raise APIError(
                422, ErrorCode.VALIDATION, f"Unknown PBAS items: {', '.join(unknown)}", {"field": "self_assessment"}
            )
        values = {c: dict(v) for c, v in body.self_assessment.items()}
        auto = await self._auto_fill(staff, year.start_date, year.end_date)
        for cat, spec in schema.items():
            for item, ispec in (spec.get("items") or {}).items():
                src = ispec.get("auto")
                if src and item not in values.get(cat, {}):
                    values.setdefault(cat, {})[item] = auto.get(src, 0)
        score, _ = pbas_score(schema, values)
        row = await self.repo.for_year(staff.id, year.id)
        if row is not None and row.status != "draft":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The {year.name} appraisal is {row.status}")
        payload = {"values": values, "auto": auto}
        if row is None:
            row = await self.repo.create(
                institution_id=self.inst,
                staff_id=staff.id,
                academic_year_id=year.id,
                self_assessment=payload,
                self_score=score,
                status="draft",
            )
        else:
            row.self_assessment, row.self_score = payload, score
            await self.db.flush()
        await self._audit("appraisal_self", "appraisal", row.id, None, {"self_score": float(score), "year": year.name})
        return (await self._out([row]))[0]

    async def _auto_fill(self, staff: Staff, d1: date, d2: date) -> dict[str, int]:
        params = {"s": staff.id, "y1": d1.year, "y2": d2.year, "d1": d1, "d2": d2}
        return {key: await self.records.counts(sql, params) for key, sql in AUTO_SQL.items()}

    async def submit(self, appraisal_id: uuid.UUID) -> AppraisalOut:
        row = await self.repo.get_visible(appraisal_id, for_update=True)
        staff = await self.staff_repo.by_id(row.staff_id)
        if staff is None or staff.user_id != self.principal.id:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the appraisee submits the self-appraisal")
        if row.status != "draft":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The appraisal is {row.status}")
        instance = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=APPRAISAL_KEY,
            entity_type="appraisal",
            entity_id=row.id,
            started_by=self.principal.id,
            context={
                "department_id": str(staff.department_id) if staff.department_id else None,
                "college_id": str(staff.college_id) if staff.college_id else None,
                "staff_id": str(staff.id),
            },
            title=f"Appraisal — {staff.full_name}",
        )
        row.status, row.workflow_instance_id = "submitted", instance.id
        row.reviewer_staff_id = await self._first_approver_staff(instance.id)
        await self.db.flush()
        await self._audit("submit", "appraisal", row.id, {"status": "draft"}, {"status": "submitted"})
        await self._emit(
            "appraisal.submitted", {"appraisal_id": str(row.id), "staff_id": str(staff.id)}, "appraisal", row.id
        )
        return (await self._out([row]))[0]

    async def _first_approver_staff(self, instance_id: uuid.UUID) -> uuid.UUID | None:
        from sqlalchemy import select

        from app.models.platform import WorkflowStep

        uid = (
            await self.db.execute(
                select(WorkflowStep.approver_user_id)
                .where(WorkflowStep.instance_id == instance_id, WorkflowStep.step_order == 1)
                .limit(1)
            )
        ).scalar_one_or_none()
        if uid is None:
            return None
        s = await self.staff_repo.by_user(uid)
        return s.id if s else None

    async def review(self, appraisal_id: uuid.UUID, body: AppraisalReviewIn) -> AppraisalOut:
        row = await self.repo.get_visible(appraisal_id, for_update=True)
        if row.status not in ("submitted", "reviewed") or row.workflow_instance_id is None:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The appraisal is {row.status}")
        instance = await workflow_engine.act(
            self.db,
            instance_id=row.workflow_instance_id,
            actor=self.principal,
            decision=body.decision,
            comment=body.comment,
        )
        if body.reviewer_score is not None:
            row.reviewer_score = body.reviewer_score
        if instance.status == "pending" and row.status == "submitted":
            row.status = "reviewed"
            me = await self.staff_repo.by_user(self.principal.id)
            row.reviewer_staff_id = me.id if me else row.reviewer_staff_id
        await self.db.flush()
        await self.db.refresh(row)
        await self._audit(
            "review",
            "appraisal",
            row.id,
            None,
            {
                "decision": body.decision,
                "reviewer_score": float(body.reviewer_score) if body.reviewer_score is not None else None,
                "status": row.status,
            },
        )
        return (await self._out([row]))[0]

    # ---- CAS ----------------------------------------------------------------------------------------------------
    async def list_cas(
        self, params: PageParams, scope: str | None, status: str | None
    ) -> tuple[list[CasApplicationOut], PaginationMeta, VisibilityMeta]:
        stmt = self.cas.filtered(scope=scope, status=status)
        if not params.sort:
            params = params.model_copy(update={"sort": "-created_at"})
        rows, pagination = await self.cas.paginate(stmt, params)
        return await self._cas_out(list(rows)), pagination, hr_visibility(self.principal, "appraisals")

    async def _cas_out(self, rows: list[CasApplication]) -> list[CasApplicationOut]:
        names = await self.staff_repo.names([r.staff_id for r in rows])
        today = await self.today()
        out = []
        for r in rows:
            o = CasApplicationOut.model_validate(r)
            o.staff_name, o.employee_id = names.get(r.staff_id, (None, None))
            o.eligible_now = r.eligibility_date is not None and r.eligibility_date <= today
            out.append(o)
        return out

    async def current_cadre(self, staff: Staff) -> str | None:
        profile = await self.records.profile(staff.id)
        if profile is not None and profile.cadre:
            return profile.cadre
        if staff.designation_id:
            d = await DesignationRepository(self.db, self.principal, self.inst).get_one(staff.designation_id)
            return d.cadre
        return None

    async def create_cas(self, body: CasApplicationIn) -> CasApplicationOut:
        staff = await self.my_staff()
        assert staff is not None
        cadre = await self.current_cadre(staff)
        path = (await self.pack()).hr.cas_paths.get(cadre or "")
        if not path:
            raise APIError(422, ErrorCode.VALIDATION, f"No CAS path from cadre {cadre!r}", {"field": "to_cadre"})
        to = body.to_cadre.value if body.to_cadre else path["to"]
        if to != path["to"]:
            raise APIError(422, ErrorCode.VALIDATION, f"CAS moves {cadre} to {path['to']}", {"field": "to_cadre"})
        if await self.cas.open_for(staff.id):
            raise APIError(409, ErrorCode.CONFLICT, "You already have an open CAS application")
        promoted = await self.records.last_entry(staff.id, "promotion")
        start = promoted.effective_date if promoted else (staff.joining_date or await self.today())
        try:
            eligibility = start.replace(year=start.year + int(path["years"]))
        except ValueError:  # 29 Feb
            eligibility = start.replace(year=start.year + int(path["years"]), day=28)
        latest = await self.repo.latest_for(staff.id)
        breakdown: dict[str, Any] = {"source": "none"}
        if latest is not None:
            _, cats = pbas_score((await self.pack()).hr.pbas_schema, (latest.self_assessment or {}).get("values", {}))
            breakdown = {
                "source": "appraisal",
                "appraisal_id": str(latest.id),
                "categories": cats,
                "total": float(latest.reviewer_score or latest.self_score or 0),
            }
        row = await self.cas.create(
            institution_id=self.inst,
            staff_id=staff.id,
            from_cadre=cadre,
            to_cadre=to,
            eligibility_date=eligibility,
            api_breakdown=breakdown,
            documents=body.documents,
            status="draft",
        )
        await self._audit(
            "cas_create",
            "cas_application",
            row.id,
            None,
            {"from": cadre, "to": to, "eligibility_date": eligibility.isoformat()},
        )
        return (await self._cas_out([row]))[0]

    async def submit_cas(self, cas_id: uuid.UUID) -> CasApplicationOut:
        row = await self.cas.get_visible(cas_id, for_update=True)
        staff = await self.staff_repo.by_id(row.staff_id)
        if staff is None or staff.user_id != self.principal.id:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the applicant submits the CAS application")
        if row.status != "draft":
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The application is {row.status}")
        if row.eligibility_date and row.eligibility_date > await self.today():
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                f"Eligible from {row.eligibility_date.isoformat()}",
                {"field": "eligibility_date"},
            )
        instance = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key=CAS_KEY,
            entity_type="cas_application",
            entity_id=row.id,
            started_by=self.principal.id,
            context={
                "staff_id": str(staff.id),
                "department_id": str(staff.department_id) if staff.department_id else None,
                "college_id": str(staff.college_id) if staff.college_id else None,
                "to_cadre": row.to_cadre,
            },
            title=f"CAS {row.from_cadre} → {row.to_cadre} — {staff.full_name}",
        )
        row.status, row.workflow_instance_id = "submitted", instance.id
        await self.db.flush()
        await self._audit("cas_submit", "cas_application", row.id, {"status": "draft"}, {"status": "submitted"})
        return (await self._cas_out([row]))[0]

    async def screen_cas(self, cas_id: uuid.UUID, body: CasScreenIn) -> CasApplicationOut:
        row = await self.cas.get_visible(cas_id, for_update=True)
        allowed = {"screened": ("submitted",), "interviewed": ("submitted", "screened")}[body.status]
        if row.status not in allowed:
            raise APIError(409, ErrorCode.RULE_VIOLATION, f"Cannot mark a {row.status} application {body.status}")
        old = row.status
        row.status = body.status
        await self.db.flush()
        await self._audit(
            body.status, "cas_application", row.id, {"status": old}, {"status": body.status, "remarks": body.remarks}
        )
        return (await self._cas_out([row]))[0]

    async def decide_cas(self, cas_id: uuid.UUID, body: CasDecideIn) -> CasApplicationOut:
        row = await self.cas.get_visible(cas_id, for_update=True)
        if row.status not in ("submitted", "screened", "interviewed") or row.workflow_instance_id is None:
            raise APIError(409, ErrorCode.RECORD_LOCKED, f"The application is {row.status}")
        from sqlalchemy import select

        inst = (
            await self.db.execute(
                select(WorkflowInstance).where(WorkflowInstance.id == row.workflow_instance_id).with_for_update()
            )
        ).scalar_one()
        inst.context = {
            **(inst.context or {}),
            "new_designation_id": str(body.new_designation_id) if body.new_designation_id else None,
            "new_basic_paise": body.new_basic_paise,
            "effective_date": body.effective_date.isoformat() if body.effective_date else None,
        }
        await self.db.flush()
        await workflow_engine.act(
            self.db, instance_id=inst.id, actor=self.principal, decision=body.decision, comment=body.comment
        )
        await self.db.refresh(row)
        return (await self._cas_out([row]))[0]

    async def promote(self, row: CasApplication, ctx: dict[str, Any], actor: Any) -> None:
        from app.services.payroll_service import PayrollService
        from app.services.staff_service import StaffService

        staff = await self.staff_repo.by_id(row.staff_id)
        if staff is None:
            return
        designations = DesignationRepository(self.db, actor, self.inst)
        designation = (
            await designations.get_one(uuid.UUID(ctx["new_designation_id"]))
            if ctx.get("new_designation_id")
            else await designations.by_cadre(row.to_cadre)
        )
        effective = date.fromisoformat(ctx["effective_date"]) if ctx.get("effective_date") else await self.today()
        old_designation = staff.designation_id
        if designation is not None:
            staff.designation_id = designation.id
        profile = await self.records.profile(staff.id)
        if profile is not None:
            profile.cadre = row.to_cadre
            profile.max_scholars = (await self.pack()).hr.max_scholars_by_cadre.get(row.to_cadre, profile.max_scholars)
        current = await SalaryStructureRepository(self.db).effective(staff.id, effective)
        basic = int(ctx.get("new_basic_paise") or 0) or (
            int(round(current.basic_paise * 1.03 / 100)) * 100 if current else 0
        )
        if basic and (current is None or effective > current.effective_from):
            await PayrollService(self.db, actor, None, self.inst).add_structure(
                staff.id,
                SalaryStructureIn(
                    effective_from=effective,
                    basic_paise=basic,
                    components=dict(current.components) if current else {},
                    pay_level=designation.code if designation else None,
                ),
                reason=f"CAS promotion to {row.to_cadre}",
            )
        await StaffService(self.db, actor, None, self.inst).add_service_entry(
            staff,
            "promotion",
            effective,
            {
                "from_cadre": row.from_cadre,
                "to_cadre": row.to_cadre,
                "from_designation_id": str(old_designation) if old_designation else None,
                "to_designation_id": str(designation.id) if designation else None,
                "cas_application_id": str(row.id),
            },
        )
        row.status, row.decided_at = "approved", datetime.now(UTC)
        await self.db.flush()
        await self._audit(
            "cas_approve",
            "cas_application",
            row.id,
            None,
            {
                "to_cadre": row.to_cadre,
                "designation_id": str(designation.id) if designation else None,
                "basic_paise": basic,
            },
        )
        await self._emit(
            "cas.approved",
            {"cas_application_id": str(row.id), "staff_id": str(staff.id), "to_cadre": row.to_cadre},
            "cas_application",
            row.id,
        )


# ---- workflow hooks ------------------------------------------------------------------------------------------------
@workflow_engine.on(APPRAISAL_KEY, "approved")
async def _on_appraisal_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await AppraisalRepository(db).get_any(instance.entity_id)
    if row is None or row.status == "approved":
        return
    row.status = "approved"
    row.final_score = row.reviewer_score if row.reviewer_score is not None else row.self_score
    await db.flush()
    await AppraisalService(db, actor, institution_id=instance.institution_id)._emit(
        "appraisal.approved",
        {"appraisal_id": str(row.id), "staff_id": str(row.staff_id), "final_score": float(row.final_score or 0)},
        "appraisal",
        row.id,
    )


@workflow_engine.on(APPRAISAL_KEY, "rejected")
async def _on_appraisal_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await AppraisalRepository(db).get_any(instance.entity_id)
    if row is not None and row.status in ("submitted", "reviewed"):
        row.status = "reviewed"
        row.final_score = row.reviewer_score
        await db.flush()


@workflow_engine.on(CAS_KEY, "approved")
async def _on_cas_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await CasRepository(db).get_any(instance.entity_id)
    if row is None or row.status in ("approved", "rejected"):
        return
    await AppraisalService(db, actor, institution_id=instance.institution_id).promote(
        row, dict(instance.context or {}), actor
    )


@workflow_engine.on(CAS_KEY, "rejected")
async def _on_cas_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    row = await CasRepository(db).get_any(instance.entity_id)
    if row is not None and row.status not in ("approved", "rejected"):
        row.status, row.decided_at = "rejected", datetime.now(UTC)
        await db.flush()


@workflow_engine.summariser("appraisal")
async def _summarise_appraisal(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = await AppraisalRepository(db).get_any(entity_id)
    if row is None:
        return None, None
    return f"PBAS self-appraisal · score {float(row.self_score or 0):g}", "/admin/hr/appraisals"


@workflow_engine.summariser("cas_application")
async def _summarise_cas(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = await CasRepository(db).get_any(entity_id)
    if row is None:
        return None, None
    return f"CAS {row.from_cadre} → {row.to_cadre}", "/admin/hr/appraisals?tab=cas"
