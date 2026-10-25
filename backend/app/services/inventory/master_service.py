"""Masters — Prompts/22 §22.6 ``master_service``.

Suppliers (GSTIN / PAN validated by the schema; GSTIN must embed the PAN; bank details encrypted, shown masked unless
``inventory:view_pii``; blacklist with reason blocks new POs; ``supplier_type`` drives the TDS rate and lives in
``contact.supplier_type``), stores (type, keeper), categories tree, items (code from the ``item`` sequence or manual,
hazardous items need ``safety_data`` when ``inventory.lab_consumables`` is on), CSV import with a partial-success report.
"""

import csv
import io
import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.authz.masking import mask_value
from app.core.errors import APIError, ErrorCode
from app.models.inventory import InventoryCategory, Item, StockLevel, Store, Supplier
from app.schemas.inventory import (
    InvCategoryIn,
    InvCategoryOut,
    ItemIn,
    ItemOut,
    ItemUpdate,
    StoreIn,
    StoreOut,
    SupplierIn,
    SupplierOut,
    SupplierUpdate,
)
from app.services.inventory.common import INV, InventoryBase, is_reader, now_utc, pairs, rule, store_predicate
from app.services.students.common import snap

UNITS = {"nos", "kg", "g", "l", "ml", "m", "box", "pack", "set", "pair", "ream", "roll", "bottle", "dozen"}


class MasterService(InventoryBase):
    # ---- suppliers ---------------------------------------------------------------------------------------------------
    def supplier_out(self, s: Supplier) -> SupplierOut:
        bank: dict[str, Any] | None = None
        if s.bank_details_encrypted:
            try:
                bank = json.loads(s.bank_details_encrypted)
            except (TypeError, ValueError):
                bank = None
            if bank and not self.can(INV, "view_pii"):
                bank = {k: (mask_value(v, "generic") if k == "account_no" else v) for k, v in bank.items()}
        return SupplierOut(
            id=s.id,
            name=s.name,
            code=s.code,
            gstin=s.gstin,
            pan=s.pan,
            contact=s.contact,
            address=s.address,
            categories=s.categories,
            bank_details=bank,
            rating=float(s.rating) if s.rating is not None else None,
            status=s.status,
            portal_user_id=s.portal_user_id,
            is_active=s.is_active,
        )

    async def suppliers(self, status: str | None = None, q: str | None = None) -> list[SupplierOut]:
        self.require("view_all", "procurement:view_all", "procurement:quote")
        stmt = select(Supplier).where(Supplier.institution_id == self.inst)
        if status:
            stmt = stmt.where(Supplier.status == status)
        if q:
            stmt = stmt.where(Supplier.name.ilike(f"%{q}%"))
        return [self.supplier_out(s) for s in (await self.db.execute(stmt.order_by(Supplier.name))).scalars()]

    async def supplier(self, supplier_id: uuid.UUID) -> Supplier:
        s = (
            await self.db.execute(
                select(Supplier).where(Supplier.id == supplier_id, Supplier.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if s is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Supplier not found")
        return s

    @staticmethod
    def _check_tax_ids(gstin: str | None, pan: str | None) -> None:
        if gstin and pan and gstin[2:12] != pan:
            raise APIError(422, ErrorCode.VALIDATION, "The GSTIN must contain the PAN", {"field": "gstin"})

    async def create_supplier(self, body: SupplierIn, *, status: str = "active") -> SupplierOut:
        self._check_tax_ids(body.gstin, body.pan)
        if (
            await self.db.execute(
                select(Supplier.id).where(
                    Supplier.institution_id == self.inst, func.lower(Supplier.name) == body.name.lower()
                )
            )
        ).first():
            raise rule("A supplier with this name exists", "DUPLICATE_SUPPLIER")
        contact = dict(body.contact or {})
        if body.supplier_type:
            contact["supplier_type"] = body.supplier_type
        s = Supplier(
            institution_id=self.inst,
            name=body.name,
            code=body.code,
            gstin=body.gstin,
            pan=body.pan or (body.gstin[2:12] if body.gstin else None),
            contact=contact,
            address=body.address,
            categories=body.categories,
            bank_details_encrypted=json.dumps(body.bank_details.model_dump()) if body.bank_details else None,
            status=status,
        )
        self.db.add(s)
        await self.db.flush()
        await self._audit("create", "supplier", s.id, None, snap(s, ("name", "gstin", "status")))
        await self._emit(
            "inventory.supplier_registered", {"supplier_id": str(s.id), "status": status}, "supplier", s.id
        )
        return self.supplier_out(s)

    async def update_supplier(self, supplier_id: uuid.UUID, body: SupplierUpdate) -> SupplierOut:
        self.require("manage")
        s = await self.supplier(supplier_id)
        data = body.model_dump(exclude_unset=True)
        self._check_tax_ids(data.get("gstin", s.gstin), data.get("pan", s.pan))
        old = snap(s, ("gstin", "pan", "rating"))
        if "bank_details" in data:
            bd = data.pop("bank_details")
            s.bank_details_encrypted = json.dumps(bd) if bd else None
        for k, v in data.items():
            setattr(s, k, v)
        await self.db.flush()
        await self._audit("update", "supplier", s.id, old, snap(s, ("gstin", "pan", "rating")))
        return self.supplier_out(s)

    async def verify(self, supplier_id: uuid.UUID) -> SupplierOut:
        self.require("manage")
        s = await self.supplier(supplier_id)
        if s.status == "blacklisted":
            raise rule("A blacklisted supplier cannot be verified", "SUPPLIER_BLACKLISTED")
        s.status = "active"
        from app.services.inventory.vendor_service import VendorService

        await VendorService(self.db, self.principal, self.request, self.inst).provision_user(s)
        await self._audit("verify", "supplier", s.id, None, {"status": "active"})
        await self._emit("inventory.supplier_verified", {"supplier_id": str(s.id)}, "supplier", s.id)
        if s.portal_user_id:
            await self._notify("vendor.verified", [s.portal_user_id], {"supplier": s.name})
        return self.supplier_out(s)

    async def blacklist(self, supplier_id: uuid.UUID, reason: str | None) -> SupplierOut:
        self.require("manage")
        if not reason:
            raise APIError(422, ErrorCode.VALIDATION, "A reason is required", {"field": "reason"})
        s = await self.supplier(supplier_id)
        s.status = "blacklisted"
        await self.put_meta("supplier", s.id, {"blacklist_reason": reason, "at": now_utc().isoformat()})
        await self._audit("blacklist", "supplier", s.id, None, {"reason": reason})
        await self._emit(
            "inventory.supplier_blacklisted", {"supplier_id": str(s.id), "reason": reason}, "supplier", s.id
        )
        return self.supplier_out(s)

    # ---- stores ------------------------------------------------------------------------------------------------------
    async def store_outs(self, rows: list[Store]) -> list[StoreOut]:
        ids = [s.id for s in rows]
        stats: dict[uuid.UUID, tuple[int, int, int]] = {}
        if ids:
            for sid, n, below, value in (
                await self.db.execute(
                    select(
                        StockLevel.store_id,
                        func.count(),
                        func.count().filter(StockLevel.quantity < func.coalesce(Item.min_stock_level, -1)),
                        func.coalesce(func.sum(StockLevel.quantity * func.coalesce(Item.unit_cost_paise, 0)), 0),
                    )
                    .join(Item, Item.id == StockLevel.item_id)
                    .where(StockLevel.store_id.in_(ids))
                    .group_by(StockLevel.store_id)
                )
            ).all():
                stats[sid] = (int(n), int(below), int(value))
        names = await self.staff_names({s.keeper_staff_id for s in rows})
        out = []
        for s in rows:
            n, below, value = stats.get(s.id, (0, 0, 0))
            out.append(
                StoreOut(
                    id=s.id,
                    name=s.name,
                    store_type=s.store_type,
                    college_id=s.college_id,
                    department_id=s.department_id,
                    keeper_staff_id=s.keeper_staff_id,
                    keeper_name=names.get(s.keeper_staff_id) if s.keeper_staff_id else None,
                    is_active=s.is_active,
                    items=n,
                    below_min=below,
                    value_paise=value if is_reader(self.principal) else 0,
                )
            )
        return out

    async def stores(self) -> list[StoreOut]:
        rows = (
            await self.db.execute(
                select(Store)
                .where(Store.institution_id == self.inst, store_predicate(self.principal))
                .order_by(Store.name)
            )
        ).scalars()
        return await self.store_outs(list(rows))

    async def save_store(self, body: StoreIn, store_id: uuid.UUID | None = None) -> StoreOut:
        self.require("manage")
        if store_id:
            s = await self.store(store_id)
            for k, v in body.model_dump().items():
                setattr(s, k, v)
        else:
            s = Store(institution_id=self.inst, **body.model_dump())
            self.db.add(s)
        await self.db.flush()
        await self._audit("save", "store", s.id, None, snap(s, ("name", "store_type", "keeper_staff_id")))
        return (await self.store_outs([s]))[0]

    # ---- categories / items -----------------------------------------------------------------------------------------------
    async def categories(self) -> list[InvCategoryOut]:
        rows = (
            await self.db.execute(
                select(InventoryCategory)
                .where(InventoryCategory.institution_id == self.inst)
                .order_by(InventoryCategory.name)
            )
        ).scalars()
        return [InvCategoryOut.model_validate(c, from_attributes=True) for c in rows]

    async def create_category(self, body: InvCategoryIn) -> InvCategoryOut:
        self.require("manage")
        c = InventoryCategory(institution_id=self.inst, **body.model_dump())
        self.db.add(c)
        await self.db.flush()
        return InvCategoryOut.model_validate(c, from_attributes=True)

    async def item_outs(self, rows: list[Item]) -> list[ItemOut]:
        cats: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(InventoryCategory.id, InventoryCategory.name).where(
                        InventoryCategory.id.in_({i.category_id for i in rows if i.category_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        on_hand: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(StockLevel.item_id, func.sum(StockLevel.quantity))
                    .where(StockLevel.item_id.in_([i.id for i in rows] or [uuid.uuid4()]))
                    .group_by(StockLevel.item_id)
                )
            ).all()
        )
        cost = is_reader(self.principal) or self.can(INV, "issue") or self.can(INV, "receive")
        out = []
        for i in rows:
            o = ItemOut.model_validate(i, from_attributes=True)
            o.category = cats.get(i.category_id)
            o.on_hand = float(on_hand.get(i.id) or 0)
            if not cost:
                o.unit_cost_paise = None
            out.append(o)
        return out

    async def items(
        self, q: str | None = None, category_id: uuid.UUID | None = None, hazardous: bool | None = None
    ) -> list[ItemOut]:
        stmt = select(Item).where(Item.institution_id == self.inst, Item.deleted_at.is_(None))
        if q:
            stmt = stmt.where(Item.name.ilike(f"%{q}%") | Item.item_code.ilike(f"%{q}%"))
        if category_id:
            stmt = stmt.where(Item.category_id == category_id)
        if hazardous is not None:
            stmt = stmt.where(Item.is_hazardous.is_(hazardous))
        return await self.item_outs(list((await self.db.execute(stmt.order_by(Item.name).limit(2000))).scalars()))

    async def item(self, item_id: uuid.UUID) -> Item:
        i = (
            await self.db.execute(
                select(Item).where(Item.id == item_id, Item.institution_id == self.inst, Item.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if i is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Item not found")
        return i

    async def _hazard_rules(self, hazardous: bool, safety: Any) -> None:
        if hazardous and safety is None and await self.feature("inventory.lab_consumables"):
            raise APIError(422, ErrorCode.VALIDATION, "Hazardous items need safety data", {"field": "safety_data"})

    async def create_item(self, body: ItemIn) -> ItemOut:
        self.require("manage")
        await self._hazard_rules(body.is_hazardous, body.safety_data)
        code = body.item_code or await self.sequence("item", "ITM")
        if (
            await self.db.execute(select(Item.id).where(Item.institution_id == self.inst, Item.item_code == code))
        ).first():
            raise rule("Item code already used", "DUPLICATE_ITEM_CODE")
        i = Item(
            institution_id=self.inst,
            **body.model_dump(exclude={"item_code", "safety_data"}),
            item_code=code,
            safety_data=body.safety_data.model_dump(mode="json") if body.safety_data else None,
        )
        self.db.add(i)
        await self.db.flush()
        await self._audit("create", "item", i.id, None, snap(i, ("item_code", "name", "is_hazardous")))
        await self._emit("inventory.item_created", {"item_id": str(i.id), "code": code}, "item", i.id)
        return (await self.item_outs([i]))[0]

    async def update_item(self, item_id: uuid.UUID, body: ItemUpdate) -> ItemOut:
        self.require("manage")
        i = await self.item(item_id)
        if body.version is not None and body.version != i.version:
            raise APIError(409, ErrorCode.CONFLICT, "The item was changed by someone else", {"version": i.version})
        data = body.model_dump(exclude_unset=True, exclude={"version"})
        await self._hazard_rules(data.get("is_hazardous", i.is_hazardous), data.get("safety_data", i.safety_data))
        old = snap(i, ("name", "min_stock_level", "is_hazardous"))
        for k, v in data.items():
            setattr(i, k, v)
        i.version += 1
        await self.db.flush()
        await self._audit("update", "item", i.id, old, snap(i, ("name", "min_stock_level", "is_hazardous")))
        return (await self.item_outs([i]))[0]

    async def delete_item(self, item_id: uuid.UUID) -> None:
        self.require("manage")
        i = await self.item(item_id)
        held = (
            await self.db.execute(
                select(func.coalesce(func.sum(StockLevel.quantity), 0)).where(StockLevel.item_id == i.id)
            )
        ).scalar_one()
        if Decimal(held) > 0:
            raise rule("The item still has stock", "ITEM_IN_STOCK", quantity=float(held))
        i.deleted_at, i.deleted_by, i.is_active = now_utc(), self.actor_id, False
        await self._audit("delete", "item", i.id, None, None)

    async def import_items(self, csv_text: str) -> dict[str, Any]:
        """``code,name,unit,category,consumable,min_stock,reorder_qty,unit_cost_paise,gst_rate`` (header row required)."""
        self.require("manage")
        cats = {
            c.name.lower(): c.id
            for c in (
                await self.db.execute(select(InventoryCategory).where(InventoryCategory.institution_id == self.inst))
            ).scalars()
        }
        report: dict[str, Any] = {"created": 0, "failed": []}
        for n, row in enumerate(csv.DictReader(io.StringIO(csv_text)), start=2):
            try:
                unit = (row.get("unit") or "nos").strip().lower()
                if unit not in UNITS:
                    raise APIError(422, ErrorCode.VALIDATION, f"Unknown unit {unit!r}")
                async with self.db.begin_nested():
                    await self.create_item(
                        ItemIn(
                            item_code=(row.get("code") or "").strip() or None,
                            name=(row.get("name") or "").strip(),
                            unit=unit,
                            category_id=cats.get((row.get("category") or "").strip().lower()),
                            is_consumable=(row.get("consumable") or "yes").strip().lower() in ("1", "yes", "true", "y"),
                            min_stock_level=float(row["min_stock"]) if row.get("min_stock") else None,
                            reorder_qty=float(row["reorder_qty"]) if row.get("reorder_qty") else None,
                            unit_cost_paise=int(row["unit_cost_paise"]) if row.get("unit_cost_paise") else None,
                            gst_rate=float(row["gst_rate"]) if row.get("gst_rate") else None,
                        )
                    )
                report["created"] += 1
            except (APIError, ValueError) as exc:
                report["failed"].append({"row": n, "message": getattr(exc, "message", str(exc))[:200]})
        return report
