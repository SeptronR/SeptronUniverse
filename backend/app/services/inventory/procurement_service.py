"""Procurement — Prompts/22 §22.6 ``procurement_service`` (``inventory.procurement``).

1. Quotations: manual entry or vendor-portal submission against an approved indent; comparative statement (per-line
   prices per supplier, L1 per line and overall); select one (audited).
2. PO: number from the ``po`` sequence, lines with tax → subtotal / tax / total. A PO above
   ``inventory.three_quotes_above_paise`` needs ≥ 3 quotations or a GeM / tender reference (409 ``QUOTES_REQUIRED``)
   unless the indent is an emergency with an approval reference; blacklisted suppliers → 409 ``SUPPLIER_BLACKLISTED``.
   ``submit``: up to ``inventory.po_approval_threshold_paise`` a ``procurement:po_approve`` holder approves directly
   (``/approve``); above it the ``procurement.po`` workflow runs (accounts → vice-chancellor / principal). ``send``
   (supplier email + portal), ``amend`` (before any receipt; version + 1, back to ``draft``), ``cancel`` (releases the
   budget commitment), ``close``.
3. GRN: per PO and store; partial receipts raise ``received_qty`` (``partially_received`` → ``received``); rejected
   quantities recorded; each accepted line is a ``receipt`` stock transaction at the PO price; non-consumable lines are
   offered for asset creation.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.enums.inventory import RECEIVABLE_PO
from app.models.inventory import GoodsReceipt, Indent, Item, PurchaseOrder, PurchaseOrderItem, Quotation, Supplier
from app.models.platform import WorkflowInstance
from app.schemas.inventory import (
    ComparativeStatement,
    GrnCreate,
    GrnResponse,
    PoCreate,
    PoItemOut,
    PoLine,
    PoResponse,
    PoUpdate,
    QuotationIn,
    QuotationOut,
)
from app.services.inventory.common import INV, InventoryBase, all_access, now_utc, pairs, rule
from app.services.inventory.indent_service import IndentService
from app.services.students.common import snap

D = Decimal
PO_KEYS = ("po_number", "status", "total_paise", "supplier_id")


class ProcurementService(InventoryBase):
    def _vendor_scope(self) -> bool:
        return (
            not all_access(self.principal)
            and not self.can(INV, "manage")
            and not self.can("procurement", "view_all")
            and not self.can("procurement", "po_approve")
        )

    # ---- quotations ---------------------------------------------------------------------------------------------------
    async def quote_outs(self, rows: list[Quotation]) -> list[QuotationOut]:
        names: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(Supplier.id, Supplier.name).where(
                        Supplier.id.in_({q.supplier_id for q in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        out = []
        for q in rows:
            o = QuotationOut.model_validate(q, from_attributes=True)
            o.supplier_name = names.get(q.supplier_id)
            out.append(o)
        return out

    async def _indent(self, indent_id: uuid.UUID, *, any_scope: bool = False) -> Indent:
        if any_scope:
            r = (
                await self.db.execute(select(Indent).where(Indent.id == indent_id, Indent.institution_id == self.inst))
            ).scalar_one_or_none()
            if r is None:
                raise APIError(404, ErrorCode.NOT_FOUND, "Indent not found")
            return r
        return await IndentService(self.db, self.principal, self.request, self.inst).get_row(indent_id)

    async def quotations(self, indent_id: uuid.UUID) -> list[QuotationOut]:
        await self._indent(indent_id)
        rows = (
            await self.db.execute(
                select(Quotation).where(Quotation.indent_id == indent_id).order_by(Quotation.total_paise)
            )
        ).scalars()
        return await self.quote_outs(list(rows))

    @staticmethod
    def _total(lines: list[dict[str, Any]]) -> int:
        return int(
            sum(D(str(x["qty"])) * D(x["unit_price_paise"]) * (1 + D(str(x.get("tax_rate") or 0)) / 100) for x in lines)
        )

    async def add_quotation(
        self, indent_id: uuid.UUID, body: QuotationIn, *, vendor: Supplier | None = None
    ) -> QuotationOut:
        if vendor is None:
            self.require("procurement:quote")
        r = await self._indent(indent_id, any_scope=vendor is not None)
        if r.status != "approved":
            raise rule("Quotations are taken for approved indents only", "NOT_APPROVED")
        supplier_id = vendor.id if vendor else body.supplier_id
        if supplier_id is None:
            raise APIError(422, ErrorCode.VALIDATION, "supplier_id is required", {"field": "supplier_id"})
        s = (
            await self.db.execute(
                select(Supplier).where(Supplier.id == supplier_id, Supplier.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Supplier not found")
        if s.status == "blacklisted":
            raise rule("The supplier is blacklisted", "SUPPLIER_BLACKLISTED")
        lines = [x.model_dump(mode="json") for x in body.items]
        for x in lines:
            if x["line"] >= len(r.items):
                raise APIError(422, ErrorCode.VALIDATION, f"Indent has no line {x['line'] + 1}")
            x.setdefault("item_id", r.items[x["line"]].get("item_id"))
        q = Quotation(
            institution_id=self.inst,
            indent_id=r.id,
            supplier_id=s.id,
            reference=body.reference,
            tender_ref=body.tender_ref,
            gem_ref=body.gem_ref,
            items=lines,
            total_paise=self._total(lines),
            valid_until=body.valid_until,
            file_url=body.file_url,
            comparison_notes=body.comparison_notes,
        )
        self.db.add(q)
        await self.db.flush()
        await self._audit(
            "create",
            "quotation",
            q.id,
            None,
            {"indent_id": str(r.id), "supplier_id": str(s.id), "total": q.total_paise},
        )
        await self._emit(
            "inventory.quotation_submitted",
            {"quotation_id": str(q.id), "indent_id": str(r.id), "via_portal": vendor is not None},
            "quotation",
            q.id,
        )
        return (await self.quote_outs([q]))[0]

    async def update_quotation(self, quotation_id: uuid.UUID, body: QuotationIn) -> QuotationOut:
        self.require("procurement:quote")
        q = (
            await self.db.execute(
                select(Quotation).where(Quotation.id == quotation_id, Quotation.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if q is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Quotation not found")
        lines = [x.model_dump(mode="json") for x in body.items]
        q.items, q.total_paise = lines, self._total(lines)
        for k in ("reference", "tender_ref", "gem_ref", "valid_until", "file_url", "comparison_notes"):
            setattr(q, k, getattr(body, k))
        await self.db.flush()
        return (await self.quote_outs([q]))[0]

    async def select_quotation(self, quotation_id: uuid.UUID) -> QuotationOut:
        self.require("procurement:quote", "procurement:manage")
        q = (
            await self.db.execute(
                select(Quotation).where(Quotation.id == quotation_id, Quotation.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if q is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Quotation not found")
        for other in (await self.db.execute(select(Quotation).where(Quotation.indent_id == q.indent_id))).scalars():
            other.is_selected = other.id == q.id
        await self.db.flush()
        await self._audit("select", "quotation", q.id, None, {"indent_id": str(q.indent_id), "total": q.total_paise})
        await self._emit(
            "inventory.quotation_selected",
            {"quotation_id": str(q.id), "indent_id": str(q.indent_id)},
            "quotation",
            q.id,
        )
        return (await self.quote_outs([q]))[0]

    async def comparative(self, indent_id: uuid.UUID) -> ComparativeStatement:
        r = await self._indent(indent_id)
        quotes = await self.quotations(indent_id)
        rows, lowest = [], {}
        for n, line in enumerate(r.items):
            per: dict[str, Any] = {}
            for q in quotes:
                hit = next((x for x in q.items if x["line"] == n), None)
                if hit:
                    per[str(q.supplier_id)] = {
                        "price": hit["unit_price_paise"],
                        "total": int(D(str(hit["qty"])) * D(hit["unit_price_paise"])),
                    }
            if per:
                lowest[str(n)] = min(per, key=lambda k: per[k]["price"])
            rows.append(
                {
                    "line": n,
                    "item": line.get("name") or line.get("free_text"),
                    "qty": line.get("qty"),
                    "per_supplier": per,
                }
            )
        return ComparativeStatement(
            indent_id=r.id,
            suppliers=[
                {
                    "supplier_id": str(q.supplier_id),
                    "name": q.supplier_name,
                    "total_paise": q.total_paise,
                    "is_selected": q.is_selected,
                    "quotation_id": str(q.id),
                }
                for q in quotes
            ],
            rows=rows,
            lowest_by_item=lowest,
            lowest_total_supplier_id=quotes[0].supplier_id if quotes else None,
        )

    # ---- purchase orders ------------------------------------------------------------------------------------------------
    async def po_outs(self, rows: list[PurchaseOrder]) -> list[PoResponse]:
        ids = [p.id for p in rows]
        names: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(Supplier.id, Supplier.name).where(
                        Supplier.id.in_({p.supplier_id for p in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        lines: dict[uuid.UUID, list[PoItemOut]] = {i: [] for i in ids}
        items: dict[Any, Any] = {}
        po_items = list(
            (
                await self.db.execute(
                    select(PurchaseOrderItem).where(PurchaseOrderItem.po_id.in_(ids or [uuid.uuid4()]))
                )
            ).scalars()
        )
        if po_items:
            items = pairs(
                (
                    await self.db.execute(select(Item.id, Item.name).where(Item.id.in_({x.item_id for x in po_items})))
                ).all()
            )
        for x in po_items:
            lines[x.po_id].append(
                PoItemOut(
                    id=x.id,
                    item_id=x.item_id,
                    item_name=items.get(x.item_id),
                    quantity=float(x.quantity),
                    unit_price_paise=x.unit_price_paise,
                    tax_rate=float(x.tax_rate) if x.tax_rate is not None else None,
                    received_qty=float(x.received_qty),
                )
            )
        receipts: dict[uuid.UUID, list[dict[str, Any]]] = {i: [] for i in ids}
        for g in (
            await self.db.execute(
                select(GoodsReceipt)
                .where(GoodsReceipt.po_id.in_(ids or [uuid.uuid4()]))
                .order_by(GoodsReceipt.received_on)
            )
        ).scalars():
            receipts[g.po_id].append(
                {"id": str(g.id), "grn_number": g.grn_number, "received_on": g.received_on.isoformat()}
            )
        metas = await self.metas("po") if rows else {}
        out = []
        for p in rows:
            m = metas.get(str(p.id), {})
            out.append(
                PoResponse(
                    id=p.id,
                    po_number=p.po_number,
                    supplier_id=p.supplier_id,
                    supplier_name=names.get(p.supplier_id),
                    indent_id=p.indent_id,
                    quotation_id=p.quotation_id,
                    order_date=p.order_date,
                    expected_date=p.expected_date,
                    terms=p.terms,
                    subtotal_paise=p.subtotal_paise,
                    tax_paise=p.tax_paise,
                    total_paise=p.total_paise,
                    status=p.status,
                    version=int(m.get("version", 1)),
                    workflow_instance_id=p.workflow_instance_id,
                    items=lines[p.id],
                    receipts=receipts[p.id],
                    acknowledged_at=m.get("acknowledged_at"),
                )
            )
        return out

    async def list_pos(
        self, status: str | None = None, supplier_id: uuid.UUID | None = None, *, vendor: Supplier | None = None
    ) -> list[PoResponse]:
        q = select(PurchaseOrder).where(PurchaseOrder.institution_id == self.inst)
        if vendor is not None:
            q = q.where(
                PurchaseOrder.supplier_id == vendor.id, PurchaseOrder.status.notin_(("draft", "submitted", "approved"))
            )
        elif self._vendor_scope():
            # HOD / requester: POs raised for indents they can see
            from app.services.inventory.indent_service import indent_predicate

            q = q.where(PurchaseOrder.indent_id.in_(select(Indent.id).where(indent_predicate(self.principal))))
        if status:
            q = q.where(PurchaseOrder.status == status)
        if supplier_id:
            q = q.where(PurchaseOrder.supplier_id == supplier_id)
        return await self.po_outs(
            list((await self.db.execute(q.order_by(PurchaseOrder.created_at.desc()).limit(1000))).scalars())
        )

    async def po_row(self, po_id: uuid.UUID, *, for_update: bool = False) -> PurchaseOrder:
        q = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.institution_id == self.inst)
        if for_update:
            q = q.with_for_update()
        p = (await self.db.execute(q)).scalar_one_or_none()
        if p is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Purchase order not found")
        if self._vendor_scope():
            from app.services.inventory.indent_service import indent_predicate

            ok = (
                p.indent_id is not None
                and (
                    await self.db.execute(
                        select(Indent.id).where(Indent.id == p.indent_id, indent_predicate(self.principal))
                    )
                ).first()
            )
            if not ok:
                raise APIError(404, ErrorCode.NOT_FOUND, "Purchase order not found")
        return p

    async def get_po(self, po_id: uuid.UUID) -> PoResponse:
        return (await self.po_outs([await self.po_row(po_id)]))[0]

    async def _set_lines(self, p: PurchaseOrder, lines: list[PoLine]) -> None:
        for old in (await self.db.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == p.id))).scalars():
            await self.db.delete(old)
        sub = tax = 0
        for ln in lines:
            amount = int(D(str(ln.qty)) * D(ln.unit_price_paise))
            sub += amount
            tax += int(D(amount) * D(str(ln.tax_rate)) / 100)
            self.db.add(
                PurchaseOrderItem(
                    institution_id=self.inst,
                    po_id=p.id,
                    item_id=ln.item_id,
                    quantity=D(str(ln.qty)),
                    unit_price_paise=ln.unit_price_paise,
                    tax_rate=D(str(ln.tax_rate)),
                )
            )
        p.subtotal_paise, p.tax_paise, p.total_paise = sub, tax, sub + tax
        await self.db.flush()

    async def _quotes_rule(self, indent: Indent | None, total: int) -> None:
        if indent is None or total <= await self.threshold("three_quotes_above_paise", 2500000):
            return
        quotes = list((await self.db.execute(select(Quotation).where(Quotation.indent_id == indent.id))).scalars())
        if len(quotes) >= 3 or any(q.gem_ref or q.tender_ref for q in quotes):  # noqa: PLR2004
            return
        if indent.priority == "emergency" and (await self.meta("indent", indent.id)).get("emergency_approval_ref"):
            return
        raise rule(
            "At least three quotations (or a GeM / tender reference) are required",
            "QUOTES_REQUIRED",
            quotations=len(quotes),
        )

    async def create_po(self, body: PoCreate) -> PoResponse:
        self.require("procurement:create", "procurement:manage")
        s = (
            await self.db.execute(
                select(Supplier).where(Supplier.id == body.supplier_id, Supplier.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Supplier not found")
        if s.status == "blacklisted":
            raise rule("The supplier is blacklisted", "SUPPLIER_BLACKLISTED")
        indent = await self._indent(body.indent_id, any_scope=True) if body.indent_id else None
        if indent is not None and indent.status != "approved":
            raise rule("The indent is not approved", "NOT_APPROVED")
        lines = body.items
        if lines is None and body.quotation_id:
            q = (await self.db.execute(select(Quotation).where(Quotation.id == body.quotation_id))).scalar_one()
            lines = [
                PoLine(
                    item_id=uuid.UUID(x["item_id"]),
                    qty=x["qty"],
                    unit_price_paise=x["unit_price_paise"],
                    tax_rate=x.get("tax_rate") or 0,
                )
                for x in q.items
                if x.get("item_id")
            ]
        if not lines:
            raise APIError(422, ErrorCode.VALIDATION, "A PO needs lines (or a quotation with stock items)")
        total = int(sum(D(str(x.qty)) * D(x.unit_price_paise) * (1 + D(str(x.tax_rate)) / 100) for x in lines))
        await self._quotes_rule(indent, total)
        p = PurchaseOrder(
            institution_id=self.inst,
            po_number=await self.sequence("po", "PO"),
            supplier_id=s.id,
            indent_id=indent.id if indent else None,
            quotation_id=body.quotation_id,
            order_date=await self.today(),
            expected_date=body.expected_date,
            terms=body.terms,
            created_by=self.actor_id,
        )
        self.db.add(p)
        await self.db.flush()
        await self._set_lines(p, lines)
        await self._audit("create", "purchase_order", p.id, None, snap(p, PO_KEYS))
        return (await self.po_outs([p]))[0]

    async def update_po(self, po_id: uuid.UUID, body: PoUpdate) -> PoResponse:
        self.require("procurement:update", "procurement:manage")
        p = await self.po_row(po_id, for_update=True)
        if p.status != "draft":
            raise rule("Only a draft PO can be edited (amend a sent one)", "NOT_DRAFT")
        if body.items is not None:
            await self._set_lines(p, body.items)
        if body.terms is not None:
            p.terms = body.terms
        if body.expected_date is not None:
            p.expected_date = body.expected_date
        await self.db.flush()
        return (await self.po_outs([p]))[0]

    async def submit_po(self, po_id: uuid.UUID) -> PoResponse:
        self.require("procurement:create", "procurement:manage")
        p = await self.po_row(po_id, for_update=True)
        if p.status != "draft":
            raise rule("Only a draft PO can be submitted", "NOT_DRAFT")
        p.status = "submitted"
        if p.total_paise > await self.threshold("po_approval_threshold_paise", 10000000):
            inst = await workflow_engine.start(
                self.db,
                institution_id=self.inst,
                key="procurement.po",
                entity_type="purchase_order",
                entity_id=p.id,
                started_by=self.actor_id,
                context={"amount_paise": p.total_paise},
                title=f"PO {p.po_number} · ₹{p.total_paise / 100:,.0f}",
            )
            p.workflow_instance_id = inst.id
        await self.db.flush()
        await self._audit("submit", "purchase_order", p.id, None, snap(p, PO_KEYS))
        return (await self.po_outs([p]))[0]

    async def approve_po(self, po_id: uuid.UUID, *, via_workflow: bool = False) -> PoResponse:
        if not via_workflow:
            self.require("procurement:po_approve")
        p = await self.po_row(po_id, for_update=True)
        if p.status != "submitted":
            raise rule("The PO is not awaiting approval", "NOT_SUBMITTED")
        if p.workflow_instance_id and not via_workflow:
            raise rule("This PO is above the threshold — approve it in the workflow inbox", "WORKFLOW_REQUIRED")
        p.status, p.approved_by = "approved", self.actor_id
        await self.db.flush()
        await self._audit("approve", "purchase_order", p.id, None, snap(p, PO_KEYS))
        await self._emit(
            "inventory.po_approved", {"po_id": str(p.id), "total_paise": p.total_paise}, "purchase_order", p.id
        )
        return (await self.po_outs([p]))[0]

    async def send_po(self, po_id: uuid.UUID, email: str | None = None) -> PoResponse:
        self.require("procurement:create", "procurement:manage")
        p = await self.po_row(po_id, for_update=True)
        if p.status != "approved":
            raise rule("Only an approved PO can be sent", "NOT_APPROVED")
        p.status = "sent"
        s = (await self.db.execute(select(Supplier).where(Supplier.id == p.supplier_id))).scalar_one()
        to = email or (s.contact or {}).get("email")
        await self._notify(
            "inventory.po_sent",
            [s.portal_user_id],
            {"po": p.po_number, "supplier": s.name, "total": f"{p.total_paise / 100:,.2f}"},
            audience={
                "user_ids": [str(s.portal_user_id)] if s.portal_user_id else [],
                "roles": ["inventory_manager"],
                "direct_contacts": [{"to": to, "channel": "email", "name": s.name}] if to else [],
            },
        )
        await self._audit("send", "purchase_order", p.id, None, {"email": to})
        await self._emit("inventory.po_sent", {"po_id": str(p.id), "email": to}, "purchase_order", p.id)
        if p.indent_id:
            indent = await self._indent(p.indent_id, any_scope=True)
            await IndentService(self.db, self.principal, self.request, self.inst).mark_procured(
                indent,
                {
                    str(x.item_id): float(x.quantity)
                    for x in (
                        await self.db.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == p.id))
                    ).scalars()
                },
            )
        return (await self.po_outs([p]))[0]

    async def amend_po(self, po_id: uuid.UUID, reason: str | None) -> PoResponse:
        self.require("procurement:update", "procurement:manage")
        p = await self.po_row(po_id, for_update=True)
        if p.status not in ("approved", "sent"):
            raise rule("Only an approved / sent PO can be amended", "NOT_AMENDABLE")
        received = (
            await self.db.execute(
                select(func.coalesce(func.sum(PurchaseOrderItem.received_qty), 0)).where(
                    PurchaseOrderItem.po_id == p.id
                )
            )
        ).scalar_one()
        if D(received) > 0:
            raise rule("Goods were received against this PO", "ALREADY_RECEIVED")
        m = await self.meta("po", p.id)
        m["version"] = int(m.get("version", 1)) + 1
        m.setdefault("amendments", []).append(
            {"at": now_utc().isoformat(), "reason": reason, "status_before": p.status}
        )
        await self.put_meta("po", p.id, m)
        p.status, p.workflow_instance_id = "draft", None
        await self._audit("amend", "purchase_order", p.id, None, {"version": m["version"], "reason": reason})
        await self._emit("inventory.po_amended", {"po_id": str(p.id), "version": m["version"]}, "purchase_order", p.id)
        return (await self.po_outs([p]))[0]

    async def cancel_po(self, po_id: uuid.UUID, reason: str | None) -> PoResponse:
        self.require("procurement:update", "procurement:manage")
        if not reason:
            raise APIError(422, ErrorCode.VALIDATION, "A reason is required", {"field": "reason"})
        p = await self.po_row(po_id, for_update=True)
        if p.status in ("partially_received", "received", "closed", "cancelled"):
            raise rule("The PO can no longer be cancelled", "NOT_CANCELLABLE")
        p.status = "cancelled"
        if p.indent_id:
            indent = await self._indent(p.indent_id, any_scope=True)
            await IndentService(self.db, self.principal, self.request, self.inst).release_commitment(
                indent, p.total_paise
            )
        await self._audit("cancel", "purchase_order", p.id, None, {"reason": reason})
        await self._emit("inventory.po_cancelled", {"po_id": str(p.id), "reason": reason}, "purchase_order", p.id)
        return (await self.po_outs([p]))[0]

    async def close_po(self, po_id: uuid.UUID) -> PoResponse:
        self.require("procurement:update", "procurement:manage")
        p = await self.po_row(po_id, for_update=True)
        if p.status not in ("received", "partially_received", "sent"):
            raise rule("Only a sent / received PO can be closed", "NOT_CLOSABLE")
        p.status = "closed"
        await self._audit("close", "purchase_order", p.id, None, None)
        return (await self.po_outs([p]))[0]

    async def acknowledge(self, po_id: uuid.UUID, vendor: Supplier) -> PoResponse:
        p = await self.po_row(po_id)
        if p.supplier_id != vendor.id:
            raise APIError(404, ErrorCode.NOT_FOUND, "Purchase order not found")
        m = await self.meta("po", p.id)
        m["acknowledged_at"] = now_utc().isoformat()
        await self.put_meta("po", p.id, m)
        await self._audit("acknowledge", "purchase_order", p.id, None, {"supplier_id": str(vendor.id)})
        return (await self.po_outs([p]))[0]

    async def po_lines_text(self, po_id: uuid.UUID) -> tuple[str, list[str]]:
        o = await self.get_po(po_id)
        lines = [
            f"Purchase order {o.po_number}   date {o.order_date}   version {o.version}",
            f"Supplier: {o.supplier_name}",
            f"Expected by: {o.expected_date or '-'}",
            "",
            "Item                                   Qty      Rate (Rs)   Tax %    Amount (Rs)",
        ]
        for x in o.items:
            amt = x.quantity * x.unit_price_paise / 100
            lines.append(
                f"{(x.item_name or '')[:38]:<38} {x.quantity:>7.2f} {x.unit_price_paise / 100:>11.2f} {x.tax_rate or 0:>7.2f} {amt:>13.2f}"
            )
        lines += [
            "",
            f"Subtotal Rs {o.subtotal_paise / 100:,.2f}   Tax Rs {o.tax_paise / 100:,.2f}   Total Rs {o.total_paise / 100:,.2f}",
            "",
            f"Terms: {o.terms or '-'}",
        ]
        return f"PO {o.po_number}", lines

    # ---- goods receipts ----------------------------------------------------------------------------------------------------
    async def grn_outs(self, rows: list[GoodsReceipt]) -> list[GrnResponse]:
        pos: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(PurchaseOrder.id, PurchaseOrder.po_number).where(
                        PurchaseOrder.id.in_({g.po_id for g in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        out = []
        for g in rows:
            o = GrnResponse.model_validate(g, from_attributes=True)
            o.po_number = pos.get(g.po_id)
            o.asset_lines = [x for x in g.items if not x.get("is_consumable", True) and x.get("qty_received", 0) > 0]
            out.append(o)
        return out

    async def grns(self, po_id: uuid.UUID | None = None, *, vendor: Supplier | None = None) -> list[GrnResponse]:
        from app.models.inventory import Store
        from app.services.inventory.common import store_predicate

        q = select(GoodsReceipt).where(GoodsReceipt.institution_id == self.inst)
        if vendor is not None:
            q = q.where(GoodsReceipt.po_id.in_(select(PurchaseOrder.id).where(PurchaseOrder.supplier_id == vendor.id)))
        elif not self.can("procurement", "view_all"):
            q = q.where(GoodsReceipt.store_id.in_(select(Store.id).where(store_predicate(self.principal))))
        if po_id:
            q = q.where(GoodsReceipt.po_id == po_id)
        return await self.grn_outs(
            list((await self.db.execute(q.order_by(GoodsReceipt.created_at.desc()).limit(1000))).scalars())
        )

    async def grn(self, grn_id: uuid.UUID) -> GrnResponse:
        g = (
            await self.db.execute(
                select(GoodsReceipt).where(GoodsReceipt.id == grn_id, GoodsReceipt.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if g is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Goods receipt not found")
        return (await self.grn_outs([g]))[0]

    async def receive(self, body: GrnCreate) -> GrnResponse:
        from app.services.inventory.stock_service import StockService

        self.require("receive")
        await self.store(body.store_id, own=True)
        p = (
            await self.db.execute(
                select(PurchaseOrder)
                .where(PurchaseOrder.id == body.po_id, PurchaseOrder.institution_id == self.inst)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if p is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Purchase order not found")
        if p.status not in RECEIVABLE_PO:
            raise rule("The PO is not open for receipt", "PO_NOT_RECEIVABLE", status_=p.status)
        po_items = {
            x.id: x
            for x in (
                await self.db.execute(
                    select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == p.id).with_for_update()
                )
            ).scalars()
        }
        grn = GoodsReceipt(
            institution_id=self.inst,
            grn_number=await self.sequence("grn", "GRN"),
            po_id=p.id,
            store_id=body.store_id,
            received_on=body.received_on,
            received_by=self.actor_id,
            invoice_no=body.invoice_no,
            items=[],
            remarks=body.remarks,
        )
        self.db.add(grn)
        await self.db.flush()
        stock = StockService(self.db, self.principal, self.request, self.inst)
        lines = []
        for ln in body.items:
            pi = po_items.get(ln.po_item_id)
            if pi is None:
                raise APIError(422, ErrorCode.VALIDATION, "Line is not on this PO", {"po_item_id": str(ln.po_item_id)})
            accepted = D(str(ln.qty_received)) - D(str(ln.qty_rejected))
            if accepted < 0:
                raise APIError(422, ErrorCode.VALIDATION, "Rejected quantity exceeds the received quantity")
            if D(pi.received_qty) + accepted > D(pi.quantity):
                raise rule(
                    "More than ordered", "OVER_RECEIPT", ordered=float(pi.quantity), received=float(pi.received_qty)
                )
            item = (await self.db.execute(select(Item).where(Item.id == pi.item_id))).scalar_one()
            if accepted > 0:
                await stock.move(
                    body.store_id,
                    pi.item_id,
                    accepted,
                    "receipt",
                    unit_cost=pi.unit_price_paise,
                    reference_type="grn",
                    reference_id=grn.id,
                    remarks=ln.remarks,
                )
            pi.received_qty = D(pi.received_qty) + accepted
            lines.append(
                {
                    "po_item_id": str(pi.id),
                    "item_id": str(pi.item_id),
                    "item": item.name,
                    "qty_received": float(ln.qty_received),
                    "qty_rejected": float(ln.qty_rejected),
                    "accepted": float(accepted),
                    "unit_price_paise": pi.unit_price_paise,
                    "is_consumable": item.is_consumable,
                    "remarks": ln.remarks,
                }
            )
        grn.items = lines
        done = all(D(x.received_qty) >= D(x.quantity) for x in po_items.values())
        p.status = "received" if done else "partially_received"
        await self.db.flush()
        await self._audit(
            "receive", "goods_receipt", grn.id, None, {"po": p.po_number, "lines": len(lines), "po_status": p.status}
        )
        await self._emit(
            "inventory.grn_received",
            {"grn_id": str(grn.id), "po_id": str(p.id), "po_status": p.status},
            "goods_receipt",
            grn.id,
        )
        if done:
            await self._emit("inventory.po_received", {"po_id": str(p.id)}, "purchase_order", p.id)
        await self._notify("inventory.grn_received", [p.created_by], {"po": p.po_number, "grn": grn.grn_number})
        return (await self.grn_outs([grn]))[0]

    async def grn_lines_text(self, grn_id: uuid.UUID) -> tuple[str, list[str]]:
        g = await self.grn(grn_id)
        lines = [
            f"Goods receipt {g.grn_number}   PO {g.po_number}   received {g.received_on}   invoice {g.invoice_no or '-'}",
            "",
            "Item                                   Received  Rejected  Accepted",
        ]
        for x in g.items:
            lines.append(
                f"{x['item'][:38]:<38} {x['qty_received']:>8.2f} {x['qty_rejected']:>9.2f} {x['accepted']:>9.2f}"
            )
        return f"GRN {g.grn_number}", lines

    # ---- Beat --------------------------------------------------------------------------------------------------------------
    async def overdue_scan(self) -> int:
        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(PurchaseOrder).where(
                        PurchaseOrder.institution_id == self.inst,
                        PurchaseOrder.status.in_(("sent", "partially_received")),
                        PurchaseOrder.expected_date < today,
                    )
                )
            )
            .scalars()
            .all()
        )
        for p in rows:
            await self._notify(
                "inventory.po_sent",
                [p.created_by],
                {"po": p.po_number, "supplier": "overdue", "total": f"{p.total_paise / 100:,.2f}"},
            )
        return len(rows)


@workflow_engine.on("procurement.po", "approved")
async def _po_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    p = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == instance.entity_id))).scalar_one_or_none()
    if p is not None and p.status == "submitted":
        await ProcurementService(db, actor, institution_id=instance.institution_id).approve_po(p.id, via_workflow=True)


@workflow_engine.on("procurement.po", "rejected")
async def _po_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    p = (await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == instance.entity_id))).scalar_one_or_none()
    if p is not None and p.status == "submitted":
        p.status, p.workflow_instance_id = "draft", None
