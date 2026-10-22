"""Refunds — Prompts/12 §12.6 ``refund_service``: request (student / admissions withdrawal / hostel caution deposit)
→ workflow ``fees.refund`` (accountant → principal) → process (mode / reference) → ``processed``; the invoice becomes
``refunded`` when the refunds cover everything paid. The queue endpoints act on the engine so the inbox and the queue
stay consistent; the ``approved`` hook marks the refund approved."""

import uuid
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.fees import FeeInvoice, FeeRefund
from app.models.platform import WorkflowInstance
from app.schemas.fees import RefundCreate, RefundProcess, RefundResponse
from app.services.fees.common import FeesBase, now_utc, rule, rupees

WF = "fees.refund"
ENTITY = "fee_refund"


class RefundService(FeesBase):
    async def outs(self, rows: list[FeeRefund]) -> list[RefundResponse]:
        invs = (
            {
                i.id: i
                for i in (
                    await self.db.execute(
                        select(FeeInvoice).where(FeeInvoice.id.in_([r.invoice_id for r in rows if r.invoice_id]))
                    )
                ).scalars()
            }
            if rows
            else {}
        )
        names = await self.payer_names(list(invs.values()))
        acts = await self.actionable([r.workflow_instance_id for r in rows])
        out = []
        for r in rows:
            o = RefundResponse.model_validate(r)
            inv = invs.get(r.invoice_id) if r.invoice_id else None
            if inv is not None:
                o.invoice_number = inv.invoice_number
                o.payer_name = names.get(inv.student_program_enrollment_id or inv.payer_id, (None, None))[0]
            o.can_act = bool(r.workflow_instance_id in acts) or (r.status == "approved" and self.can("fees", "refund"))
            out.append(o)
        return out

    async def submit(self, body: RefundCreate) -> RefundResponse:
        inv = None
        if body.payment_id:
            p = await self.fees.payment(body.payment_id)
            inv = await self.fees.get_visible(p.invoice_id, for_update=True)
        elif body.invoice_id:
            inv = await self.fees.get_visible(body.invoice_id, for_update=True)
        else:
            raise APIError(422, ErrorCode.VALIDATION, "invoice_id or payment_id is required")
        await self.recompute(inv)
        already = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(FeeRefund.amount_paise), 0)).where(
                        FeeRefund.invoice_id == inv.id, FeeRefund.status.in_(("requested", "approved", "processed"))
                    )
                )
            ).scalar_one()
        )
        if body.amount_paise + already > inv.paid_paise:
            raise APIError(
                422, ErrorCode.VALIDATION, f"Refundable is {rupees(inv.paid_paise - already)}", {"code": "EXCEEDS_PAID"}
            )
        r = FeeRefund(
            institution_id=self.inst,
            invoice_id=inv.id,
            payment_id=body.payment_id,
            payer_type=inv.payer_type,
            payer_id=inv.payer_id,
            amount_paise=body.amount_paise,
            reason=body.reason,
            status="requested",
        )
        self.db.add(r)
        await self.db.flush()
        try:
            wf = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key=WF,
                entity_type=ENTITY,
                entity_id=r.id,
                started_by=self.actor_id,
                context={},
                title=f"Refund {rupees(r.amount_paise)} · {inv.invoice_number}",
            )
            r.workflow_instance_id = wf.id
        except APIError:
            pass
        await self.db.flush()
        await self._audit("request", ENTITY, r.id, None, {"invoice_id": str(inv.id), "amount_paise": r.amount_paise})
        await self._emit(
            "fees.refund_requested",
            {"refund_id": str(r.id), "invoice_id": str(inv.id), "amount_paise": r.amount_paise},
            ENTITY,
            r.id,
        )
        return (await self.outs([r]))[0]

    async def _row(self, rid: uuid.UUID) -> FeeRefund:
        r = (
            await self.db.execute(
                select(FeeRefund).where(FeeRefund.id == rid, FeeRefund.institution_id == self.inst).with_for_update()
            )
        ).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Refund not found")
        return r

    async def queue(self, status: str | None = None) -> list[RefundResponse]:
        q = select(FeeRefund).where(FeeRefund.institution_id == self.inst)
        if status:
            q = q.where(FeeRefund.status == status)
        return await self.outs(
            list((await self.db.execute(q.order_by(FeeRefund.created_at.desc()).limit(500))).scalars().all())
        )

    async def mine(self) -> list[RefundResponse]:
        q = select(FeeRefund).where(FeeRefund.invoice_id.in_(self.fees.scoped("self").with_only_columns(FeeInvoice.id)))
        return await self.outs(list((await self.db.execute(q.order_by(FeeRefund.created_at.desc()))).scalars().all()))

    async def decide(
        self, rid: uuid.UUID, approve: bool, comment: str | None, *, via_workflow: bool = False
    ) -> RefundResponse:
        r = await self._row(rid)
        if r.status != "requested":
            raise APIError(409, ErrorCode.CONFLICT, f"Refund is {r.status}")
        if not via_workflow and r.workflow_instance_id:
            await workflow_engine.act(
                self.db,
                instance_id=r.workflow_instance_id,
                actor=self.principal,
                decision="approve" if approve else "reject",
                comment=comment,
            )
            return (await self.outs([r]))[0]
        r.status = "approved" if approve else "rejected"
        r.approved_by = self.actor_id
        await self.db.flush()
        await self._audit(
            "approve" if approve else "reject",
            ENTITY,
            r.id,
            {"status": "requested"},
            {"status": r.status, "comment": comment},
        )
        return (await self.outs([r]))[0]

    async def process(self, rid: uuid.UUID, body: RefundProcess) -> RefundResponse:
        r = await self._row(rid)
        if r.status != "approved":
            raise rule("Only an approved refund can be processed", "NOT_APPROVED")
        r.status, r.refund_mode, r.reference_no, r.processed_at = (
            "processed",
            body.refund_mode,
            body.reference_no,
            now_utc(),
        )
        await self.db.flush()
        if r.invoice_id:
            inv = await self.fees.get_any(r.invoice_id, for_update=True)
            refunded = int(
                (
                    await self.db.execute(
                        select(func.coalesce(func.sum(FeeRefund.amount_paise), 0)).where(
                            FeeRefund.invoice_id == inv.id, FeeRefund.status == "processed"
                        )
                    )
                ).scalar_one()
            )
            if refunded >= inv.paid_paise:
                inv.status = "refunded"
                await self.db.flush()
        await self._audit(
            "process",
            ENTITY,
            r.id,
            {"status": "approved"},
            {"status": "processed", "mode": body.refund_mode, "reference": body.reference_no},
        )
        await self._emit(
            "fees.refund_processed",
            {
                "refund_id": str(r.id),
                "invoice_id": str(r.invoice_id) if r.invoice_id else None,
                "amount_paise": r.amount_paise,
            },
            ENTITY,
            r.id,
        )
        if r.invoice_id:
            from app.services.fees.invoice_service import InvoiceService

            inv = await self.fees.get_any(r.invoice_id)
            await self._notify(
                "fees.refund_processed",
                await InvoiceService(self.db, self.principal, self.request, self.inst).payer_user_ids(inv),
                {"amount": rupees(r.amount_paise), "reference": body.reference_no},
            )
        return (await self.outs([r]))[0]


def _svc(db: Any, instance: WorkflowInstance, actor: Any) -> RefundService:
    from app.services.fees.payment_service import _Actor

    return RefundService(db, _Actor(instance.institution_id, getattr(actor, "id", None)), None, instance.institution_id)


@workflow_engine.on(WF, "approved")
async def _approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == ENTITY:
        await _svc(db, instance, actor).decide(instance.entity_id, True, None, via_workflow=True)


@workflow_engine.on(WF, "rejected")
async def _rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    if instance.entity_type == ENTITY:
        await _svc(db, instance, actor).decide(instance.entity_id, False, None, via_workflow=True)


@workflow_engine.summariser(ENTITY)
async def _summarise(db: Any, entity_id: uuid.UUID) -> tuple[str | None, str | None]:
    r = (await db.execute(select(FeeRefund).where(FeeRefund.id == entity_id))).scalar_one_or_none()
    return (f"Refund {rupees(r.amount_paise)} — {r.reason[:80]}", "/admin/fees/refunds") if r else (None, None)
