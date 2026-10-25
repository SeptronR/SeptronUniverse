"""Inventory reports — Prompts/22 §22.6 ``reports_service``.

Stock ledger, valuation, consumption by department, indent cycle time, PO / GRN registers, supplier performance
(on-time receipts, rejections), asset register, depreciation, hazardous register, audit summary; inline JSON or an
XLSX job; ``metrics`` feeds Phase 32 (NAAC 4.1 / 4.4 spend: POs received, assets added, maintenance).
"""

import io
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.inventory import (
    Asset,
    GoodsReceipt,
    Indent,
    Item,
    PurchaseOrder,
    StockLevel,
    StockTransaction,
    Store,
    Supplier,
)
from app.models.platform import Department
from app.schemas.inventory import InvReport
from app.services.inventory.common import InventoryBase, pairs

KINDS = (
    "stock_ledger",
    "valuation",
    "consumption",
    "indent_cycle",
    "po_register",
    "grn_register",
    "supplier_performance",
    "asset_register",
    "depreciation",
    "hazardous",
    "audit",
)


class InventoryReportsService(InventoryBase):
    async def report(self, kind: str, fy: str | None = None) -> InvReport:
        if kind not in KINDS:
            raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
        self.require("view_all", "reports:export")
        rows: list[dict[str, Any]] = []
        if kind == "stock_ledger":
            for t, item, store in (
                await self.db.execute(
                    select(StockTransaction, Item.name, Store.name)
                    .join(Item, Item.id == StockTransaction.item_id)
                    .join(Store, Store.id == StockTransaction.store_id)
                    .where(StockTransaction.institution_id == self.inst)
                    .order_by(StockTransaction.occurred_at.desc())
                    .limit(5000)
                )
            ).all():
                rows.append(
                    {
                        "at": t.occurred_at.isoformat(),
                        "store": store,
                        "item": item,
                        "type": t.txn_type,
                        "quantity": float(t.quantity),
                        "unit_cost_paise": t.unit_cost_paise,
                    }
                )
        elif kind == "valuation":
            for store, item, qty, cost in (
                await self.db.execute(
                    select(Store.name, Item.name, StockLevel.quantity, Item.unit_cost_paise)
                    .join(Store, Store.id == StockLevel.store_id)
                    .join(Item, Item.id == StockLevel.item_id)
                    .where(StockLevel.institution_id == self.inst, StockLevel.quantity > 0)
                    .order_by(Store.name, Item.name)
                )
            ).all():
                rows.append(
                    {
                        "store": store,
                        "item": item,
                        "quantity": float(qty),
                        "unit_cost_paise": cost or 0,
                        "value_paise": int(Decimal(qty) * Decimal(cost or 0)),
                    }
                )
        elif kind == "consumption":
            for code, n, value in (
                await self.db.execute(
                    select(
                        Department.code,
                        func.count(),
                        func.coalesce(
                            func.sum(-StockTransaction.quantity * func.coalesce(StockTransaction.unit_cost_paise, 0)), 0
                        ),
                    )
                    .join(Department, Department.id == StockTransaction.issued_to_id)
                    .where(
                        StockTransaction.institution_id == self.inst,
                        StockTransaction.txn_type == "issue",
                        StockTransaction.issued_to_type == "department",
                    )
                    .group_by(Department.code)
                )
            ).all():
                rows.append({"department": code, "issues": n, "value_paise": int(value)})
        elif kind == "indent_cycle":
            for r in (
                await self.db.execute(
                    select(Indent).where(
                        Indent.institution_id == self.inst, Indent.status.in_(("fulfilled", "closed", "approved"))
                    )
                )
            ).scalars():
                rows.append(
                    {
                        "indent": r.indent_number,
                        "status": r.status,
                        "days": (r.updated_at - r.created_at).days,
                        "estimated_paise": r.estimated_paise,
                    }
                )
        elif kind == "po_register":
            for p, s in (
                await self.db.execute(
                    select(PurchaseOrder, Supplier.name)
                    .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
                    .where(PurchaseOrder.institution_id == self.inst)
                    .order_by(PurchaseOrder.order_date.desc())
                )
            ).all():
                rows.append(
                    {
                        "po": p.po_number,
                        "date": p.order_date.isoformat(),
                        "supplier": s,
                        "total_paise": p.total_paise,
                        "status": p.status,
                    }
                )
        elif kind == "grn_register":
            for g, po in (
                await self.db.execute(
                    select(GoodsReceipt, PurchaseOrder.po_number)
                    .join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id)
                    .where(GoodsReceipt.institution_id == self.inst)
                    .order_by(GoodsReceipt.received_on.desc())
                )
            ).all():
                rows.append(
                    {
                        "grn": g.grn_number,
                        "po": po,
                        "received_on": g.received_on.isoformat(),
                        "lines": len(g.items),
                        "rejected": sum(x.get("qty_rejected", 0) for x in g.items),
                    }
                )
        elif kind == "supplier_performance":
            stats: dict[uuid.UUID, dict[str, Any]] = {}
            for p, g in (
                await self.db.execute(
                    select(PurchaseOrder, GoodsReceipt)
                    .join(GoodsReceipt, GoodsReceipt.po_id == PurchaseOrder.id)
                    .where(PurchaseOrder.institution_id == self.inst)
                )
            ).all():
                st = stats.setdefault(p.supplier_id, {"grns": 0, "on_time": 0, "received": 0.0, "rejected": 0.0})
                st["grns"] += 1
                st["on_time"] += int(p.expected_date is None or g.received_on <= p.expected_date)
                st["received"] += sum(x.get("qty_received", 0) for x in g.items)
                st["rejected"] += sum(x.get("qty_rejected", 0) for x in g.items)
            names: dict[Any, Any] = pairs(
                (
                    await self.db.execute(
                        select(Supplier.id, Supplier.name).where(Supplier.id.in_(list(stats) or [uuid.uuid4()]))
                    )
                ).all()
            )
            for sid, st in stats.items():
                rows.append(
                    {
                        "supplier": names.get(sid),
                        "grns": st["grns"],
                        "on_time_pct": round(100 * st["on_time"] / st["grns"], 1),
                        "rejection_pct": round(100 * st["rejected"] / st["received"], 1) if st["received"] else 0,
                    }
                )
        elif kind == "asset_register":
            for a in (
                await self.db.execute(
                    select(Asset)
                    .where(Asset.institution_id == self.inst, Asset.deleted_at.is_(None))
                    .order_by(Asset.asset_tag)
                )
            ).scalars():
                rows.append(
                    {
                        "tag": a.asset_tag,
                        "name": a.name,
                        "category": a.category,
                        "purchase_date": a.purchase_date.isoformat() if a.purchase_date else None,
                        "cost_paise": a.cost_paise,
                        "current_value_paise": a.current_value_paise,
                        "status": a.status,
                    }
                )
        elif kind == "depreciation":
            from app.services.inventory.asset_service import AssetService

            today = await self.today()
            year = today.year if today.month >= 4 else today.year - 1  # noqa: PLR2004
            summary = await AssetService(self.db, self.principal, self.request, self.inst).depreciation_schedule(
                fy or f"{year}-{str(year + 1)[2:]}"
            )
            rows = summary.rows
        elif kind == "hazardous":
            from app.services.inventory.stock_service import StockService

            rows = await StockService(self.db, self.principal, self.request, self.inst).hazardous_register()
        elif kind == "audit":
            from app.services.inventory.asset_service import AssetService

            rows = [
                c.model_dump(mode="json")
                for c in await AssetService(self.db, self.principal, self.request, self.inst).cycles()
            ]
        return InvReport(kind=kind, columns=list(rows[0]) if rows else [], rows=rows)

    async def report_xlsx(self, kind: str) -> dict[str, Any]:
        from openpyxl import Workbook

        from app.core.files import build_key, storage

        rep = await self.report(kind)
        wb = Workbook()
        ws = wb.active
        ws.title = kind[:30]
        ws.append(rep.columns)
        for r in rep.rows:
            ws.append([r.get(c) if not isinstance(r.get(c), dict | list) else str(r.get(c)) for c in rep.columns])
        buf = io.BytesIO()
        wb.save(buf)
        key = build_key(self.inst, "inventory-reports", f"{kind}-{uuid.uuid4().hex[:8]}.xlsx")
        await storage.put(key, buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        return {"result_url": key, "rows": len(rep.rows), "report": kind}

    async def metrics(self) -> dict[str, int]:
        po = (
            await self.db.execute(
                select(func.coalesce(func.sum(PurchaseOrder.total_paise), 0)).where(
                    PurchaseOrder.institution_id == self.inst, PurchaseOrder.status.in_(("received", "closed"))
                )
            )
        ).scalar_one()
        assets = (
            await self.db.execute(
                select(func.coalesce(func.sum(Asset.cost_paise), 0)).where(
                    Asset.institution_id == self.inst, Asset.deleted_at.is_(None)
                )
            )
        ).scalar_one()
        return {"procurement_spend_paise": int(po or 0), "asset_cost_paise": int(assets or 0)}
