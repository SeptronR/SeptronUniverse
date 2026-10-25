"""Vendor bills — Prompts/22 §22.6 ``bill_service`` (``inventory.bills``).

Entry against a PO / GRN with a **three-way match** (bill subtotal vs GRN accepted quantity × PO price; variance beyond
``inventory.bill_variance_pct`` is flagged), GST from the PO tax when not given, **TDS** by supplier type
(``inventory.tds_rates`` — company 2 %, individual / firm 1 %, government 0 % by default — above
``inventory.tds_threshold_paise``). ``verify`` (inventory manager) → ``decide``: up to
``inventory.bill_approval_threshold_paise`` a ``procurement:bill_approve`` holder approves directly, above it the
``procurement.bill`` workflow runs (accountant → vice-chancellor / principal); ``hold`` with a reason, ``release``,
``reject``; ``pay`` with a reference → ``inventory.bill_paid`` (Phase 23 expense / ledger posting). Ageing buckets
0–30 / 31–60 / 61–90 / 90+ days past due.
"""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.inventory import GoodsReceipt, PurchaseOrder, PurchaseOrderItem, Supplier, VendorBill
from app.models.platform import WorkflowInstance
from app.schemas.inventory import BillDecision, BillPay, VendorBillIn, VendorBillOut
from app.services.inventory.common import InventoryBase, now_utc, pairs, rule
from app.services.students.common import snap

D = Decimal
KEYS = ("bill_number", "status", "total_paise", "tds_paise")
TDS_DEFAULT = {"company": 2.0, "individual": 1.0, "firm": 1.0, "government": 0.0}


class BillService(InventoryBase):
    async def outs(self, rows: list[VendorBill]) -> list[VendorBillOut]:
        names: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(Supplier.id, Supplier.name).where(
                        Supplier.id.in_({b.supplier_id for b in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        pos: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(PurchaseOrder.id, PurchaseOrder.po_number).where(
                        PurchaseOrder.id.in_({b.po_id for b in rows if b.po_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        metas = await self.metas("bill") if rows else {}
        out = []
        for b in rows:
            m = metas.get(str(b.id), {})
            o = VendorBillOut.model_validate(b, from_attributes=True)
            o.supplier_name = names.get(b.supplier_id)
            o.po_number = pos.get(b.po_id) if b.po_id else None
            o.net_payable_paise = b.total_paise - b.tds_paise
            o.match = m.get("match", {})
            o.hold_reason = m.get("hold_reason")
            out.append(o)
        return out

    async def list_bills(
        self, status: str | None = None, supplier_id: uuid.UUID | None = None, *, vendor: Supplier | None = None
    ) -> list[VendorBillOut]:
        if vendor is None:
            self.require("procurement:bill_approve", "procurement:view_all", "accounting:view", "view_all")
        q = select(VendorBill).where(VendorBill.institution_id == self.inst)
        if vendor is not None:
            q = q.where(VendorBill.supplier_id == vendor.id)
        if status:
            q = q.where(VendorBill.status == status)
        if supplier_id:
            q = q.where(VendorBill.supplier_id == supplier_id)
        return await self.outs(
            list((await self.db.execute(q.order_by(VendorBill.bill_date.desc()).limit(2000))).scalars())
        )

    async def row(self, bill_id: uuid.UUID, *, for_update: bool = False) -> VendorBill:
        q = select(VendorBill).where(VendorBill.id == bill_id, VendorBill.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        b = (await self.db.execute(q)).scalar_one_or_none()
        if b is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Bill not found")
        return b

    async def get(self, bill_id: uuid.UUID) -> VendorBillOut:
        self.require("procurement:bill_approve", "procurement:view_all", "accounting:view", "view_all")
        return (await self.outs([await self.row(bill_id)]))[0]

    async def _match(self, body: VendorBillIn) -> tuple[dict[str, Any], int]:
        """Three-way match → (report, PO tax for the matched value)."""
        if body.po_id is None:
            return {"matched": False, "reason": "no PO"}, 0
        po = (
            await self.db.execute(
                select(PurchaseOrder).where(PurchaseOrder.id == body.po_id, PurchaseOrder.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if po is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Purchase order not found")
        if po.supplier_id != body.supplier_id:
            raise APIError(422, ErrorCode.VALIDATION, "The PO belongs to another supplier")
        items = {
            str(x.id): x
            for x in (
                await self.db.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po.id))
            ).scalars()
        }
        grns = list((await self.db.execute(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id))).scalars())
        if body.grn_id:
            grns = [g for g in grns if g.id == body.grn_id]
            if not grns:
                raise APIError(422, ErrorCode.VALIDATION, "The GRN is not on this PO")
        received = D(0)
        tax = D(0)
        for g in grns:
            for ln in g.items:
                pi = items.get(ln["po_item_id"])
                if pi is None:
                    continue
                val = D(str(ln["accepted"])) * D(pi.unit_price_paise)
                received += val
                tax += val * D(pi.tax_rate or 0) / 100
        tol = D(str(await self.setting("inventory", "bill_variance_pct") or 2))
        variance = D(body.subtotal_paise) - received
        pct = (abs(variance) / received * 100) if received else D(100)
        report = {
            "matched": True,
            "po_number": po.po_number,
            "received_value_paise": int(received),
            "billed_paise": body.subtotal_paise,
            "variance_paise": int(variance),
            "variance_pct": round(float(pct), 2),
            "flagged": pct > tol,
            "tolerance_pct": float(tol),
        }
        return report, int(tax)

    async def _tds(self, s: Supplier, subtotal: int) -> int:
        if subtotal < await self.threshold("tds_threshold_paise", 3000000):
            return 0
        rates = await self.setting("inventory", "tds_rates") or TDS_DEFAULT
        kind = (s.contact or {}).get("supplier_type") or "company"
        return int(D(subtotal) * D(str(rates.get(kind, 2.0))) / 100)

    async def create(self, body: VendorBillIn) -> VendorBillOut:
        self.require("manage", "procurement:bill_approve")
        s = (
            await self.db.execute(
                select(Supplier).where(Supplier.id == body.supplier_id, Supplier.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Supplier not found")
        if (
            await self.db.execute(
                select(VendorBill.id).where(VendorBill.supplier_id == s.id, VendorBill.bill_number == body.bill_number)
            )
        ).first():
            raise rule("This bill number is already recorded for the supplier", "DUPLICATE_BILL")
        match, po_tax = await self._match(body)
        tax = body.tax_paise if body.tax_paise is not None else po_tax
        tds = await self._tds(s, body.subtotal_paise)
        b = VendorBill(
            institution_id=self.inst,
            supplier_id=s.id,
            po_id=body.po_id,
            grn_id=body.grn_id,
            bill_number=body.bill_number,
            bill_date=body.bill_date,
            due_date=body.due_date or body.bill_date + timedelta(days=30),
            subtotal_paise=body.subtotal_paise,
            tax_paise=tax,
            tds_paise=tds,
            total_paise=body.subtotal_paise + tax,
            file_url=body.file_url,
        )
        self.db.add(b)
        await self.db.flush()
        await self.put_meta("bill", b.id, {"match": match})
        await self._audit("create", "vendor_bill", b.id, None, snap(b, KEYS) | {"match": match})
        await self._emit(
            "inventory.bill_received",
            {"bill_id": str(b.id), "flagged": match.get("flagged", False)},
            "vendor_bill",
            b.id,
        )
        return (await self.outs([b]))[0]

    async def _status(
        self, b: VendorBill, status: str, event: str, extra: dict[str, Any] | None = None
    ) -> VendorBillOut:
        old = snap(b, KEYS)
        b.status = status
        await self.db.flush()
        await self._audit(status, "vendor_bill", b.id, old, snap(b, KEYS) | (extra or {}))
        await self._emit(event, {"bill_id": str(b.id), "status": status, **(extra or {})}, "vendor_bill", b.id)
        s = (await self.db.execute(select(Supplier).where(Supplier.id == b.supplier_id))).scalar_one()
        if s.portal_user_id:
            await self._notify("inventory.bill_status", [s.portal_user_id], {"bill": b.bill_number, "status": status})
        return (await self.outs([b]))[0]

    async def verify(self, bill_id: uuid.UUID) -> VendorBillOut:
        self.require("manage")
        b = await self.row(bill_id, for_update=True)
        if b.status != "received":
            raise rule("Only a received bill can be verified", "NOT_RECEIVED")
        return await self._status(b, "verified", "inventory.bill_verified")

    async def decide(self, bill_id: uuid.UUID, body: BillDecision) -> VendorBillOut:
        b = await self.row(bill_id, for_update=True)
        m = await self.meta("bill", b.id)
        if body.action == "hold":
            self.require("procurement:bill_approve", "manage")
            if not body.hold_reason:
                raise APIError(422, ErrorCode.VALIDATION, "A hold reason is required", {"field": "hold_reason"})
            if b.status in ("paid", "rejected"):
                raise rule("The bill is closed", "CLOSED")
            await self.put_meta("bill", b.id, m | {"hold_reason": body.hold_reason, "held_from": b.status})
            return await self._status(b, "on_hold", "inventory.bill_on_hold", {"reason": body.hold_reason})
        if body.action == "release":
            self.require("procurement:bill_approve", "manage")
            if b.status != "on_hold":
                raise rule("The bill is not on hold", "NOT_ON_HOLD")
            back = m.pop("held_from", "verified")
            m.pop("hold_reason", None)
            await self.put_meta("bill", b.id, m)
            return await self._status(b, back, "inventory.bill_verified", {"released": True})
        self.require("procurement:bill_approve")
        if body.action == "reject":
            if b.status in ("paid", "rejected"):
                raise rule("The bill is closed", "CLOSED")
            return await self._status(b, "rejected", "inventory.bill_rejected", {"remarks": body.remarks})
        if b.status != "verified":
            raise rule("Verify the bill before approving it", "NOT_VERIFIED")
        if b.total_paise > await self.threshold("bill_approval_threshold_paise", 10000000):
            if b.workflow_instance_id:
                raise rule("The bill is awaiting the workflow approval", "WORKFLOW_PENDING")
            inst = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="procurement.bill",
                entity_type="vendor_bill",
                entity_id=b.id,
                started_by=self.actor_id,
                context={"amount_paise": b.total_paise},
                title=f"Bill {b.bill_number} · ₹{b.total_paise / 100:,.0f}",
            )
            b.workflow_instance_id = inst.id
            await self.db.flush()
            return (await self.outs([b]))[0]
        return await self._status(b, "approved", "inventory.bill_approved", {"remarks": body.remarks})

    async def pay(self, bill_id: uuid.UUID, body: BillPay) -> VendorBillOut:
        self.require("procurement:bill_approve", "accounting:manage")
        b = await self.row(bill_id, for_update=True)
        if b.status != "approved":
            raise rule("Only an approved bill can be paid", "NOT_APPROVED")
        b.payment_ref, b.paid_at = body.payment_ref, body.paid_at or now_utc()
        out = await self._status(
            b,
            "paid",
            "inventory.bill_paid",
            {
                "mode": body.mode,
                "payment_ref": body.payment_ref,
                "amount_paise": b.total_paise - b.tds_paise,
                "tds_paise": b.tds_paise,
                "po_id": str(b.po_id) if b.po_id else None,
            },
        )
        return out

    async def ageing(self) -> dict[str, Any]:
        self.require("procurement:bill_approve", "accounting:view", "view_all")
        today = await self.today()
        buckets = {"current": 0, "0_30": 0, "31_60": 0, "61_90": 0, "90_plus": 0}
        rows = []
        for b in (
            await self.db.execute(
                select(VendorBill).where(
                    VendorBill.institution_id == self.inst, VendorBill.status.notin_(("paid", "rejected"))
                )
            )
        ).scalars():
            days = (today - (b.due_date or b.bill_date)).days
            key = (
                "current"
                if days <= 0
                else "0_30"
                if days <= 30
                else "31_60"
                if days <= 60
                else "61_90"
                if days <= 90
                else "90_plus"
            )  # noqa: PLR2004
            buckets[key] += b.total_paise - b.tds_paise
            rows.append(
                {
                    "bill_id": str(b.id),
                    "bill_number": b.bill_number,
                    "days_overdue": max(days, 0),
                    "bucket": key,
                    "due_paise": b.total_paise - b.tds_paise,
                }
            )
        return {"buckets": buckets, "rows": rows}

    async def statement(self, supplier_id: uuid.UUID) -> dict[str, Any]:
        self.require("view_all", "procurement:view_all", "procurement:bill_approve")
        pos = list(
            (
                await self.db.execute(
                    select(PurchaseOrder).where(
                        PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.institution_id == self.inst
                    )
                )
            ).scalars()
        )
        bills = await self.list_bills(supplier_id=supplier_id)
        return {
            "purchase_orders": [
                {
                    "po_number": p.po_number,
                    "date": p.order_date.isoformat(),
                    "total_paise": p.total_paise,
                    "status": p.status,
                }
                for p in pos
            ],
            "bills": [b.model_dump(mode="json") for b in bills],
            "billed_paise": sum(b.total_paise for b in bills),
            "paid_paise": sum(b.net_payable_paise for b in bills if b.status == "paid"),
            "outstanding_paise": sum(b.net_payable_paise for b in bills if b.status not in ("paid", "rejected")),
        }

    async def due_reminders(self) -> int:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(VendorBill).where(
                        VendorBill.institution_id == self.inst,
                        VendorBill.status.in_(("verified", "approved")),
                        VendorBill.due_date <= today + timedelta(days=3),
                    )
                )
            )
            .scalars()
            .all()
        )
        if rows:
            await self._notify(
                "inventory.bill_status",
                [],
                {"bill": f"{len(rows)} bill(s)", "status": "due within 3 days"},
                audience={"roles": ["accountant"]},
            )
        return len(rows)


@workflow_engine.on("procurement.bill", "approved")
async def _bill_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    b = (await db.execute(select(VendorBill).where(VendorBill.id == instance.entity_id))).scalar_one_or_none()
    if b is not None and b.status == "verified":
        await BillService(db, actor, institution_id=instance.institution_id)._status(
            b, "approved", "inventory.bill_approved", {"via": "workflow"}
        )


@workflow_engine.on("procurement.bill", "rejected")
async def _bill_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    b = (await db.execute(select(VendorBill).where(VendorBill.id == instance.entity_id))).scalar_one_or_none()
    if b is not None and b.status == "verified":
        await BillService(db, actor, institution_id=instance.institution_id)._status(
            b, "rejected", "inventory.bill_rejected", {"via": "workflow"}
        )
