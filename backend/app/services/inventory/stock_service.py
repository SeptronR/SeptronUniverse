"""Stock — Prompts/22 §22.6 ``stock_service`` (``inventory.core``).

1. Every quantity change is a ``stock_transactions`` row plus an atomic ``stock_levels`` upsert under ``FOR UPDATE``;
   negative stock → 409 ``INSUFFICIENT_STOCK``; receipts keep the item's weighted-average ``unit_cost_paise``.
2. Issues (department / lab / staff / student / event, with a reference), returns, transfers (``transfer_out`` +
   ``transfer_in`` in one transaction), adjustments and write-offs with a reason (write-offs above
   ``inventory.write_off_approval_paise`` need an ``approval_ref``); hazardous issues need ``safety_ack`` and feed the
   chemical register.
3. Beat: low stock (``quantity < min_stock_level`` → ``inventory.low_stock`` to the keeper with a suggested indent of
   ``reorder_qty``), chemical expiry (``safety_data.expiry`` within 30 days).
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.errors import APIError, ErrorCode
from app.models.hr import Staff
from app.models.inventory import Item, StockLevel, StockTransaction, Store
from app.schemas.inventory import (
    ReturnRequest,
    StockAdjust,
    StockIssueRequest,
    StockLevelOut,
    StockLine,
    StockResult,
    StockTransfer,
    StockTxnOut,
    WriteOffRequest,
)
from app.services.inventory.common import (
    INV,
    InventoryBase,
    all_access,
    is_reader,
    kept_store_ids,
    pairs,
    rule,
    store_predicate,
)

D = Decimal


class StockService(InventoryBase):
    async def _item(self, item_id: uuid.UUID) -> Item:
        i = (
            await self.db.execute(select(Item).where(Item.id == item_id, Item.institution_id == self.inst))
        ).scalar_one_or_none()
        if i is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Item not found", {"item_id": str(item_id)})
        return i

    async def _level(self, store_id: uuid.UUID, item_id: uuid.UUID) -> StockLevel:
        lvl = (
            await self.db.execute(
                select(StockLevel)
                .where(StockLevel.store_id == store_id, StockLevel.item_id == item_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if lvl is None:
            lvl = StockLevel(institution_id=self.inst, store_id=store_id, item_id=item_id, quantity=D(0))
            self.db.add(lvl)
            await self.db.flush()
        return lvl

    async def move(
        self,
        store_id: uuid.UUID,
        item_id: uuid.UUID,
        qty: Decimal,
        txn_type: str,
        *,
        unit_cost: int | None = None,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        issued_to_type: str | None = None,
        issued_to_id: uuid.UUID | None = None,
        remarks: str | None = None,
    ) -> StockTransaction:
        """Signed ``qty`` (+ in, − out). The single choke point for every stock change."""
        item = await self._item(item_id)
        lvl = await self._level(store_id, item_id)
        new_qty = D(lvl.quantity) + qty
        if new_qty < 0:
            raise rule(
                "Not enough stock",
                "INSUFFICIENT_STOCK",
                item=item.name,
                available=float(lvl.quantity),
                requested=float(-qty),
            )
        if txn_type == "receipt" and unit_cost is not None and qty > 0:
            total_on_hand = sum(
                (
                    D(q)
                    for q in (
                        await self.db.execute(select(StockLevel.quantity).where(StockLevel.item_id == item_id))
                    ).scalars()
                ),
                D(0),
            )
            old = D(item.unit_cost_paise or unit_cost)
            item.unit_cost_paise = (
                int(((old * total_on_hand) + D(unit_cost) * qty) / (total_on_hand + qty))
                if total_on_hand + qty > 0
                else unit_cost
            )
        lvl.quantity = new_qty
        t = StockTransaction(
            institution_id=self.inst,
            store_id=store_id,
            item_id=item_id,
            txn_type=txn_type,
            quantity=qty,
            unit_cost_paise=unit_cost if unit_cost is not None else item.unit_cost_paise,
            reference_type=reference_type,
            reference_id=reference_id,
            issued_to_type=issued_to_type,
            issued_to_id=issued_to_id,
            remarks=remarks,
            performed_by=self.actor_id,
        )
        self.db.add(t)
        await self.db.flush()
        await self.db.refresh(t)
        await self._emit(
            "inventory.stock_changed",
            {
                "store_id": str(store_id),
                "item_id": str(item_id),
                "txn_type": txn_type,
                "quantity": float(qty),
                "balance": float(new_qty),
            },
            "stock_transaction",
            t.id,
        )
        return t

    async def txn_outs(self, rows: list[StockTransaction]) -> list[StockTxnOut]:
        names: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(Item.id, Item.name).where(Item.id.in_({r.item_id for r in rows} or {uuid.uuid4()}))
                )
            ).all()
        )
        out = []
        for r in rows:
            o = StockTxnOut.model_validate(r, from_attributes=True)
            o.item_name = names.get(r.item_id)
            out.append(o)
        return out

    # ---- operations ---------------------------------------------------------------------------------------------------
    async def issue(self, body: StockIssueRequest) -> StockResult:
        self.require("issue")
        await self.store(body.store_id, own=True)
        rows = []
        for line in body.items:
            item = await self._item(line.item_id)
            if item.is_hazardous and not body.safety_ack:
                raise APIError(
                    422,
                    ErrorCode.VALIDATION,
                    f"{item.name} is hazardous — the receiver must acknowledge the safety data",
                    {"field": "safety_ack"},
                )
            rows.append(
                await self.move(
                    body.store_id,
                    line.item_id,
                    -D(str(line.quantity)),
                    "issue",
                    reference_type=body.reference_type,
                    reference_id=body.reference_id,
                    issued_to_type=body.issued_to_type,
                    issued_to_id=body.issued_to_id,
                    remarks=("[safety_ack] " if item.is_hazardous else "") + (line.remarks or ""),
                )
            )
        await self._audit("issue", "stock", body.store_id, None, {"lines": len(rows), "to": body.issued_to_type})
        return StockResult(transactions=await self.txn_outs(rows))

    async def return_(self, body: ReturnRequest) -> StockResult:
        self.require("issue", "receive")
        await self.store(body.store_id, own=True)
        rows = [
            await self.move(
                body.store_id,
                line.item_id,
                D(str(line.quantity)),
                "return",
                reference_type=body.reference_type,
                reference_id=body.reference_id,
                issued_to_type=body.returned_by_type,
                issued_to_id=body.returned_by_id,
                remarks=line.remarks,
            )
            for line in body.items
        ]
        return StockResult(transactions=await self.txn_outs(rows))

    async def transfer(self, body: StockTransfer) -> StockResult:
        self.require("issue")
        if body.from_store_id == body.to_store_id:
            raise APIError(422, ErrorCode.VALIDATION, "Pick two different stores")
        await self.store(body.from_store_id, own=True)
        to = (
            await self.db.execute(select(Store).where(Store.id == body.to_store_id, Store.institution_id == self.inst))
        ).scalar_one_or_none()
        if to is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Destination store not found")
        rows: list[StockTransaction] = []
        ref = uuid.uuid4()
        for line in body.items:
            q = D(str(line.quantity))
            out = await self.move(
                body.from_store_id,
                line.item_id,
                -q,
                "transfer_out",
                reference_type="transfer",
                reference_id=ref,
                remarks=f"to {to.name}",
            )
            inn = await self.move(
                body.to_store_id,
                line.item_id,
                q,
                "transfer_in",
                unit_cost=out.unit_cost_paise,
                reference_type="transfer",
                reference_id=ref,
                remarks=line.remarks,
            )
            rows += [out, inn]
        return StockResult(transactions=await self.txn_outs(rows))

    async def adjust(self, body: StockAdjust) -> StockResult:
        self.require("manage", "receive")
        await self.store(body.store_id, own=True)
        t = await self.move(body.store_id, body.item_id, D(str(body.quantity)), "adjustment", remarks=body.reason)
        await self._audit(
            "adjust",
            "stock",
            body.store_id,
            None,
            {"item_id": str(body.item_id), "qty": body.quantity, "reason": body.reason},
        )
        return StockResult(transactions=await self.txn_outs([t]))

    async def write_off(self, body: WriteOffRequest) -> StockResult:
        self.require("manage", "issue")
        await self.store(body.store_id, own=True)
        limit = await self.threshold("write_off_approval_paise", 500000)
        value = 0
        for line in body.items:
            item = await self._item(line.item_id)
            value += int(D(str(line.quantity)) * D(item.unit_cost_paise or 0))
        if value > limit and not body.approval_ref:
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Write-offs above the threshold need an approval reference",
                {"field": "approval_ref", "value_paise": value},
            )
        rows = [
            await self.move(
                body.store_id,
                line.item_id,
                -D(str(line.quantity)),
                "write_off",
                remarks=f"{body.reason}{f' [{body.approval_ref}]' if body.approval_ref else ''}",
            )
            for line in body.items
        ]
        await self._audit(
            "write_off",
            "stock",
            body.store_id,
            None,
            {"value_paise": value, "reason": body.reason, "approval_ref": body.approval_ref},
        )
        return StockResult(transactions=await self.txn_outs(rows))

    # ---- reads ----------------------------------------------------------------------------------------------------------------
    async def stock(self, store_id: uuid.UUID, below_min: bool | None = None) -> list[StockLevelOut]:
        await self.store(store_id)
        cost = is_reader(self.principal) or self.can(INV, "issue")
        rows = (
            await self.db.execute(
                select(StockLevel, Item)
                .join(Item, Item.id == StockLevel.item_id)
                .where(StockLevel.store_id == store_id)
                .order_by(Item.name)
            )
        ).all()
        out = []
        for lvl, it in rows:
            below = it.min_stock_level is not None and D(lvl.quantity) < D(it.min_stock_level)
            if below_min and not below:
                continue
            out.append(
                StockLevelOut(
                    store_id=store_id,
                    item_id=it.id,
                    item_code=it.item_code,
                    item_name=it.name,
                    unit=it.unit,
                    quantity=float(lvl.quantity),
                    min_stock_level=float(it.min_stock_level) if it.min_stock_level is not None else None,
                    reorder_qty=float(it.reorder_qty) if it.reorder_qty is not None else None,
                    below_min=below,
                    is_hazardous=it.is_hazardous,
                    unit_cost_paise=it.unit_cost_paise if cost else None,
                )
            )
        return out

    async def transactions(
        self,
        store_id: uuid.UUID | None = None,
        item_id: uuid.UUID | None = None,
        txn_type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[StockTxnOut]:
        q = select(StockTransaction).where(
            StockTransaction.institution_id == self.inst,
            StockTransaction.store_id.in_(select(Store.id).where(store_predicate(self.principal))),
        )
        if store_id:
            q = q.where(StockTransaction.store_id == store_id)
        if item_id:
            q = q.where(StockTransaction.item_id == item_id)
        if txn_type:
            q = q.where(StockTransaction.txn_type == txn_type)
        if date_from:
            q = q.where(StockTransaction.occurred_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            q = q.where(
                StockTransaction.occurred_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time())
            )
        return await self.txn_outs(
            list((await self.db.execute(q.order_by(StockTransaction.occurred_at.desc()).limit(2000))).scalars())
        )

    async def ledger(self, item_id: uuid.UUID, store_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        rows = list(reversed(await self.transactions(store_id, item_id)))
        bal: dict[uuid.UUID, float] = {}
        out = []
        for r in rows:
            bal[r.store_id] = bal.get(r.store_id, 0.0) + r.quantity
            out.append(r.model_dump(mode="json") | {"balance": round(bal[r.store_id], 2)})
        return list(reversed(out))

    async def hazardous_register(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(StockTransaction, Item)
                .join(Item, Item.id == StockTransaction.item_id)
                .where(
                    StockTransaction.institution_id == self.inst,
                    Item.is_hazardous.is_(True),
                    StockTransaction.store_id.in_(select(Store.id).where(store_predicate(self.principal))),
                )
                .order_by(StockTransaction.occurred_at.desc())
                .limit(2000)
            )
        ).all()
        return [
            {
                "occurred_at": t.occurred_at.isoformat(),
                "item": i.name,
                "hazard_class": (i.safety_data or {}).get("hazard_class"),
                "txn_type": t.txn_type,
                "quantity": float(t.quantity),
                "unit": i.unit,
                "issued_to_type": t.issued_to_type,
                "issued_to_id": str(t.issued_to_id) if t.issued_to_id else None,
                "safety_ack": (t.remarks or "").startswith("[safety_ack]"),
            }
            for t, i in rows
        ]

    # ---- Beat --------------------------------------------------------------------------------------------------------------
    async def low_stock_scan(self) -> int:
        rows = (
            await self.db.execute(
                select(StockLevel, Item, Store)
                .join(Item, Item.id == StockLevel.item_id)
                .join(Store, Store.id == StockLevel.store_id)
                .where(
                    StockLevel.institution_id == self.inst,
                    Item.min_stock_level.is_not(None),
                    StockLevel.quantity < Item.min_stock_level,
                )
            )
        ).all()
        by_store: dict[uuid.UUID, list[dict[str, Any]]] = {}
        keepers: dict[uuid.UUID, uuid.UUID | None] = {}
        for lvl, it, st in rows:
            by_store.setdefault(st.id, []).append(
                {
                    "item_id": str(it.id),
                    "item": it.name,
                    "quantity": float(lvl.quantity),
                    "suggested_qty": float(it.reorder_qty or it.min_stock_level or 0),
                }
            )
            keepers[st.id] = st.keeper_staff_id
        for sid, lines in by_store.items():
            uid = (
                (await self.db.execute(select(Staff.user_id).where(Staff.id == keepers[sid]))).scalar_one_or_none()
                if keepers[sid]
                else None
            )
            await self._notify(
                "inventory.low_stock",
                [uid],
                {"count": len(lines), "items": ", ".join(x["item"] for x in lines[:5])},
                audience={"user_ids": [str(uid)] if uid else [], "roles": ["inventory_manager"]},
            )
            await self._emit("inventory.low_stock", {"store_id": str(sid), "suggested_indent": lines}, "store", sid)
        return len(rows)

    async def chemical_expiry_scan(self) -> int:
        today = await self.today()
        soon = (today + timedelta(days=30)).isoformat()
        items = (
            (
                await self.db.execute(
                    select(Item).where(
                        Item.institution_id == self.inst, Item.is_hazardous.is_(True), Item.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        expiring = [i for i in items if str((i.safety_data or {}).get("expiry") or "9999") <= soon]
        if expiring:
            await self._notify(
                "inventory.low_stock",
                [],
                {
                    "count": len(expiring),
                    "items": ", ".join(f"{i.name} (expires {(i.safety_data or {}).get('expiry')})" for i in expiring[:5]),
                },
                audience={"roles": ["inventory_manager"]},
            )
        return len(expiring)

    async def mine_store_ids(self) -> list[uuid.UUID]:
        if all_access(self.principal):
            return list((await self.db.execute(select(Store.id).where(Store.institution_id == self.inst))).scalars())
        return list((await self.db.execute(kept_store_ids(self.principal))).scalars())

    @staticmethod
    def lines(items: list[StockLine]) -> list[tuple[uuid.UUID, Decimal]]:
        return [(x.item_id, D(str(x.quantity))) for x in items]
