"""Scholarships — Prompts/12 §12.6 ``scholarship_service``.

Schemes carry eligibility rules ``{categories, income_cap_paise, min_cgpa, program_ids}`` checked on apply (422
``NOT_ELIGIBLE`` with the failing rules). Pipeline: applied → verified (accountant, ``scholarships:verify``) →
recommended (HOD, ``scholarships:approve``) → sanctioned (registrar / principal, ``scholarships:sanction``; workflow
``scholarship.sanction`` started on recommend) → disbursed (accountant): ``fee_credit`` creates a
``scholarship_credit`` payment against the student's open invoices, ``bank_transfer`` records the reference,
``external_portal`` keeps the NSP reference (``fees.nsp_integration`` adapter sync). Reports feed NAAC 5.1.1.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.fees import OPEN_INVOICE
from app.models.fees import FeeInvoice, Scholarship, ScholarshipApplication
from app.models.platform import WorkflowInstance
from app.repositories.fee_repository import ScholarshipRepository
from app.repositories.fee_scope import visibility
from app.schemas.scholarships import (
    DisburseRequest,
    ScholarshipApplicationOut,
    ScholarshipApply,
    ScholarshipDecision,
    ScholarshipIn,
    ScholarshipOut,
)
from app.services.fees.common import FeesBase, rule, rupees, student_name
from app.utils.response import VisibilityMeta

WF = "scholarship.sanction"
ENTITY = "scholarship_application"


class ScholarshipService(FeesBase):
    audit_module = "scholarships"

    def __init__(self, *a: Any, **kw: Any):
        super().__init__(*a, **kw)
        self.apps = ScholarshipRepository(self.db, self.principal, self.inst)

    async def schemes(self, active_only: bool = False) -> list[ScholarshipOut]:
        q = select(Scholarship).where(Scholarship.institution_id == self.inst)
        if active_only:
            q = q.where(Scholarship.is_active.is_(True))
        rows = (await self.db.execute(q.order_by(Scholarship.name))).scalars().all()
        counts: dict[Any, Any] = dict(
            (  # type: ignore[arg-type]
                await self.db.execute(
                    select(ScholarshipApplication.scholarship_id, func.count()).group_by(
                        ScholarshipApplication.scholarship_id
                    )
                )
            ).all()
        )
        out = []
        for r in rows:
            o = ScholarshipOut.model_validate(r)
            o.applications = int(counts.get(r.id, 0))
            out.append(o)
        return out

    async def save(self, body: ScholarshipIn, sid: uuid.UUID | None = None) -> ScholarshipOut:
        data = {**body.model_dump(), "provider": str(body.provider), "amount_type": str(body.amount_type)}
        if sid is None:
            s = Scholarship(institution_id=self.inst, **data)
            self.db.add(s)
        else:
            s = await self._scheme(sid)
            for k, v in data.items():
                setattr(s, k, v)
        await self.db.flush()
        await self._audit("save", "scholarship", s.id, None, body.model_dump(mode="json"))
        return ScholarshipOut.model_validate(s)

    async def _scheme(self, sid: uuid.UUID) -> Scholarship:
        s = (
            await self.db.execute(
                select(Scholarship).where(Scholarship.id == sid, Scholarship.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Scholarship not found")
        return s

    async def outs(self, rows: list[ScholarshipApplication]) -> list[ScholarshipApplicationOut]:
        schemes = (
            {
                s.id: s
                for s in (
                    await self.db.execute(
                        select(Scholarship).where(Scholarship.id.in_([r.scholarship_id for r in rows]))
                    )
                ).scalars()
            }
            if rows
            else {}
        )
        acts = await self.actionable([r.workflow_instance_id for r in rows])
        out = []
        for r in rows:
            o = ScholarshipApplicationOut.model_validate(r)
            sch = schemes.get(r.scholarship_id)
            o.scholarship_name = sch.name if sch else None
            _, st = await self.enrolment(r.student_program_enrollment_id)
            o.student_name, o.registration_number = student_name(st), st.registration_number
            o.can_act = r.workflow_instance_id in acts
            out.append(o)
        return out

    def check_rules(self, rules: dict[str, Any] | None, enrol: Any, student: Any, income: int | None) -> list[str]:
        rules = rules or {}
        bad = []
        cats = [c.lower() for c in rules.get("categories") or []]
        if cats and (student.category or "").lower() not in cats:
            bad.append("category")
        cap = rules.get("income_cap_paise")
        if cap is not None and (income is None or income > int(cap)):
            bad.append("income")
        min_cgpa = rules.get("min_cgpa")
        if min_cgpa is not None and enrol.cgpa is not None and Decimal(str(enrol.cgpa)) < Decimal(str(min_cgpa)):
            bad.append("cgpa")
        progs = [str(p) for p in rules.get("program_ids") or []]
        if progs and str(enrol.program_id) not in progs:
            bad.append("programme")
        return bad

    async def apply(self, sid: uuid.UUID, body: ScholarshipApply) -> ScholarshipApplicationOut:
        s = await self._scheme(sid)
        enrol, student = (
            await self.my_enrollment(body.enrollment_id)
            if not self.can("scholarships", "manage") or body.enrollment_id is None
            else await self.enrolment(body.enrollment_id)
        )
        today = await self.today()
        if (
            not s.is_active
            or (s.applications_open and today < s.applications_open)
            or (s.applications_close and today > s.applications_close)
        ):
            raise rule("Applications are closed for this scholarship", "WINDOW_CLOSED")
        bad = self.check_rules(s.eligibility_rules, enrol, student, body.income_paise)
        if bad:
            raise APIError(
                422, ErrorCode.RULE_VIOLATION, "Not eligible: " + ", ".join(bad), {"code": "NOT_ELIGIBLE", "rules": bad}
            )
        if (
            await self.db.execute(
                select(ScholarshipApplication.id).where(
                    ScholarshipApplication.scholarship_id == s.id,
                    ScholarshipApplication.student_program_enrollment_id == enrol.id,
                )
            )
        ).first():
            raise APIError(409, ErrorCode.CONFLICT, "Already applied")
        a = ScholarshipApplication(
            institution_id=self.inst,
            scholarship_id=s.id,
            student_program_enrollment_id=enrol.id,
            income_paise=body.income_paise,
            documents=body.documents,
            status="applied",
        )
        self.db.add(a)
        await self.db.flush()
        await self._audit("apply", ENTITY, a.id, None, {"scholarship": s.name})
        await self._emit(
            "scholarship.applied", {"application_id": str(a.id), "scholarship_id": str(s.id)}, ENTITY, a.id
        )
        return (await self.outs([a]))[0]

    async def list_apps(
        self, status: str | None, scope: str | None, scholarship_id: uuid.UUID | None = None
    ) -> tuple[list[ScholarshipApplicationOut], VisibilityMeta]:
        q = self.apps.scoped(scope)
        if status:
            q = q.where(ScholarshipApplication.status == status)
        if scholarship_id:
            q = q.where(ScholarshipApplication.scholarship_id == scholarship_id)
        rows = list(
            (await self.db.execute(q.order_by(ScholarshipApplication.created_at.desc()).limit(500))).scalars().all()
        )
        return await self.outs(rows), visibility(self.principal, "scholarships")

    async def mine(self) -> list[ScholarshipApplicationOut]:
        rows = list(
            (await self.db.execute(self.apps.scoped("self").order_by(ScholarshipApplication.created_at.desc())))
            .scalars()
            .all()
        )
        return await self.outs(rows)

    async def _move(
        self, aid: uuid.UUID, frm: tuple[str, ...], to: str, body: ScholarshipDecision
    ) -> ScholarshipApplication:
        a = await self.apps.get_visible(aid, for_update=True)
        if a.status not in frm:
            raise APIError(409, ErrorCode.CONFLICT, f"Application is {a.status}")
        old = a.status
        a.status = to
        if body.sanctioned_paise is not None:
            a.sanctioned_paise = body.sanctioned_paise
        await self.db.flush()
        await self._audit(
            to,
            ENTITY,
            a.id,
            {"status": old},
            {"status": to, "comment": body.comment, "sanctioned_paise": a.sanctioned_paise},
        )
        return a

    async def verify(self, aid: uuid.UUID, body: ScholarshipDecision) -> ScholarshipApplicationOut:
        return (await self.outs([await self._move(aid, ("applied",), "verified", body)]))[0]

    async def recommend(self, aid: uuid.UUID, body: ScholarshipDecision) -> ScholarshipApplicationOut:
        a = await self._move(aid, ("verified", "applied"), "recommended", body)
        enrol, _ = await self.enrolment(a.student_program_enrollment_id)
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF,
                entity_type=ENTITY,
                entity_id=a.id,
                started_by=self.actor_id,
                context={"college_id": str(enrol.college_id)},
                title="Scholarship sanction",
            )
            a.workflow_instance_id = wf.id
            await self.db.flush()
        except APIError:
            pass
        return (await self.outs([a]))[0]

    async def sanction(
        self, aid: uuid.UUID, body: ScholarshipDecision, *, via_workflow: bool = False
    ) -> ScholarshipApplicationOut:
        a = (
            await self.apps.get_visible(aid, for_update=True)
            if self.principal is not None and not via_workflow
            else await self._any(aid)
        )
        if a.status != "recommended":
            raise APIError(409, ErrorCode.CONFLICT, f"Application is {a.status}")
        s = await self._scheme(a.scholarship_id)
        amount = body.sanctioned_paise if body.sanctioned_paise is not None else await self._amount(s, a)
        a.status, a.sanctioned_paise = "sanctioned", amount
        await self.db.flush()
        await self._close_instance(a)
        await self._audit(
            "sanction", ENTITY, a.id, {"status": "recommended"}, {"status": "sanctioned", "sanctioned_paise": amount}
        )
        await self._emit(
            "scholarship.sanctioned", {"application_id": str(a.id), "sanctioned_paise": amount}, ENTITY, a.id
        )
        _, st = await self.enrolment(a.student_program_enrollment_id)
        await self._notify("scholarship.sanctioned", [st.user_id], {"scholarship": s.name, "amount": rupees(amount)})
        return (await self.outs([a]))[0]

    async def _any(self, aid: uuid.UUID) -> ScholarshipApplication:
        a = (
            await self.db.execute(
                select(ScholarshipApplication).where(ScholarshipApplication.id == aid).with_for_update()
            )
        ).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Scholarship application not found")
        return a

    async def _close_instance(self, a: ScholarshipApplication) -> None:
        if not a.workflow_instance_id:
            return
        inst = (
            await self.db.execute(
                select(WorkflowInstance).where(WorkflowInstance.id == a.workflow_instance_id).with_for_update()
            )
        ).scalar_one_or_none()
        if inst is not None and inst.status in ("pending", "escalated"):
            from app.models.platform import WorkflowStep

            for st in (
                await self.db.execute(
                    select(WorkflowStep).where(
                        WorkflowStep.instance_id == inst.id, WorkflowStep.status.in_(("pending", "escalated"))
                    )
                )
            ).scalars():
                st.status = "skipped"
            inst.status, inst.closed_at = "approved", datetime.now(UTC)
            await self.db.flush()

    async def _amount(self, s: Scholarship, a: ScholarshipApplication) -> int:
        if s.amount_type == "fixed":
            return int(s.amount_paise or 0)
        tuition = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(FeeInvoice.total_paise), 0)).where(
                        FeeInvoice.student_program_enrollment_id == a.student_program_enrollment_id,
                        FeeInvoice.status != "cancelled",
                        FeeInvoice.source_type == "structure",
                    )
                )
            ).scalar_one()
        )
        if s.amount_type == "fee_full":
            return tuition
        return int(tuition * int(s.amount_paise or 0) / 10000)  # fee_pct: amount_paise holds basis points × 100

    async def reject(self, aid: uuid.UUID, body: ScholarshipDecision) -> ScholarshipApplicationOut:
        a = await self._move(aid, ("applied", "verified", "recommended"), "rejected", body)
        return (await self.outs([a]))[0]

    async def disburse(self, aid: uuid.UUID, body: DisburseRequest) -> ScholarshipApplicationOut:
        a = await self.apps.get_visible(aid, for_update=True)
        if a.status != "sanctioned":
            raise rule("Only a sanctioned application can be disbursed", "NOT_SANCTIONED")
        amount = int(a.sanctioned_paise or 0)
        if body.mode == "fee_credit":
            from app.services.fees.payment_service import PaymentService

            q = (
                select(FeeInvoice)
                .where(
                    FeeInvoice.student_program_enrollment_id == a.student_program_enrollment_id,
                    FeeInvoice.status.in_(tuple(OPEN_INVOICE)),
                )
                .order_by(FeeInvoice.due_date.nulls_last())
                .with_for_update()
            )
            if body.invoice_id:
                q = q.where(FeeInvoice.id == body.invoice_id)
            left = amount
            ps = PaymentService(self.db, self.principal, self.request, self.inst)
            for inv in (await self.db.execute(q)).scalars().all():
                await self.recompute(inv)
                share = min(left, inv.balance_paise)
                if share <= 0:
                    continue
                await ps.record(inv, share, "scholarship_credit", reference=f"SCH-{str(a.id)[:8]}")
                left -= share
                if left <= 0:
                    break
            if left == amount:
                raise rule("No open invoice to credit", "NO_OPEN_INVOICE")
        elif body.mode == "external_portal":
            a.external_ref = body.reference
        a.status, a.disbursement_mode, a.disbursed_at = "disbursed", str(body.mode), datetime.now(UTC)
        if body.reference:
            a.external_ref = body.reference[:60]
        await self.db.flush()
        await self._audit(
            "disburse",
            ENTITY,
            a.id,
            {"status": "sanctioned"},
            {"mode": str(body.mode), "amount_paise": amount, "reference": body.reference},
        )
        await self._emit(
            "scholarship.disbursed",
            {"application_id": str(a.id), "mode": str(body.mode), "amount_paise": amount},
            ENTITY,
            a.id,
        )
        return (await self.outs([a]))[0]

    async def summary(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    Scholarship.name,
                    Scholarship.provider,
                    ScholarshipApplication.status,
                    func.count(),
                    func.coalesce(func.sum(ScholarshipApplication.sanctioned_paise), 0),
                )
                .join(ScholarshipApplication, ScholarshipApplication.scholarship_id == Scholarship.id)
                .where(Scholarship.institution_id == self.inst)
                .group_by(Scholarship.name, Scholarship.provider, ScholarshipApplication.status)
            )
        ).all()
        return [
            {"scholarship": n, "provider": p, "status": s, "count": int(c), "amount_paise": int(a)}
            for n, p, s, c, a in rows
        ]


def _svc(db: Any, instance: WorkflowInstance, actor: Any) -> ScholarshipService:
    from app.services.fees.payment_service import _Actor

    return ScholarshipService(
        db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id
    )


@workflow_engine.on(WF, "approved")
async def _approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    svc = _svc(db, instance, actor)
    a = await svc._any(instance.entity_id)
    if a.status == "recommended":
        await svc.sanction(a.id, ScholarshipDecision(), via_workflow=True)


@workflow_engine.on(WF, "rejected")
async def _rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type != ENTITY:
        return
    a = (
        await db.execute(
            select(ScholarshipApplication).where(ScholarshipApplication.id == instance.entity_id).with_for_update()
        )
    ).scalar_one_or_none()
    if a is not None and a.status == "recommended":
        a.status = "rejected"
        await db.flush()


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    row = (
        await db.execute(
            select(ScholarshipApplication, Scholarship)
            .join(Scholarship, Scholarship.id == ScholarshipApplication.scholarship_id)
            .where(ScholarshipApplication.id == entity_id)
        )
    ).first()
    return (f"Scholarship sanction · {row[1].name}", "/admin/fees/scholarships") if row else (None, None)
