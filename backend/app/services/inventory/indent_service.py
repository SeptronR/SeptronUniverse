"""Indents — Prompts/22 §22.6 ``indent_service`` (``inventory.procurement``).

Draft → submit → workflow ``procurement.indent`` (HOD of ``context.department_id`` → inventory manager → accountant).
Hooks mirror the workflow: step 1 approved → ``hod_approved``; final approval → **budget check** when a
``budget_head_id`` is set and ``accounting.budgets`` is on (``allocated − utilised − committed ≥ estimated``, else the
indent returns to ``draft`` with ``changes_requested`` recorded and the workflow reason); approved → ``committed_paise``
increased (``budget.commit_requested``); rejected → ``rejected``. An approved indent is **fulfilled from stock** (the
keeper issues lines; ``fulfilled`` when every line is issued) or **converted to procurement** (quotations / PO).
Emergency indents carry the principal's approval reference and skip the three-quote rule.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text

from app.core.errors import APIError, ErrorCode
from app.core.workflow import engine as workflow_engine
from app.models.hr import Staff
from app.models.inventory import Indent, Item, PurchaseOrder, Quotation
from app.models.platform import Department, User, WorkflowInstance
from app.schemas.inventory import IndentCreate, IndentFulfil, IndentResponse, IndentUpdate, StockIssueRequest, StockLine
from app.services.inventory.common import INV, InventoryBase, kept_store_ids, now_utc, pairs, rule, unit_predicate
from app.services.students.common import snap

ENTITY = "indent"
KEYS = ("indent_number", "status", "estimated_paise", "department_id", "priority")


def indent_predicate(p: Any) -> Any:
    from sqlalchemy import or_

    base = unit_predicate(p, Indent.department_id, None, Indent.requested_by, getattr(p, "id", None) or uuid.uuid4())
    if p is not None and getattr(p, "id", None) is not None and (p.has(INV, "issue") or p.has(INV, "receive")):
        return or_(
            base, Indent.store_id.in_(kept_store_ids(p)) & Indent.status.in_(("approved", "fulfilled", "closed"))
        )
    return base


class IndentService(InventoryBase):
    async def outs(self, rows: list[Indent]) -> list[IndentResponse]:
        ids = [r.id for r in rows]
        users: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(User.id, User.display_name).where(
                        User.id.in_({r.requested_by for r in rows} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        depts: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(Department.id, Department.code).where(
                        Department.id.in_({r.department_id for r in rows if r.department_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        quotes: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(Quotation.indent_id, func.count())
                    .where(Quotation.indent_id.in_(ids or [uuid.uuid4()]))
                    .group_by(Quotation.indent_id)
                )
            ).all()
        )
        pos: dict[uuid.UUID, list[uuid.UUID]] = {}
        for pid, iid in (
            await self.db.execute(
                select(PurchaseOrder.id, PurchaseOrder.indent_id).where(
                    PurchaseOrder.indent_id.in_(ids or [uuid.uuid4()])
                )
            )
        ).all():
            pos.setdefault(iid, []).append(pid)
        steps: dict[Any, Any] = {}
        wf = [r.workflow_instance_id for r in rows if r.workflow_instance_id]
        if wf:
            for wid, step, status in (
                await self.db.execute(
                    select(WorkflowInstance.id, WorkflowInstance.current_step, WorkflowInstance.status).where(
                        WorkflowInstance.id.in_(wf)
                    )
                )
            ).all():
                steps[wid] = f"step {step} · {status}"
        out = []
        for r in rows:
            lines = r.items or []
            need = sum(Decimal(str(x.get("qty", 0))) for x in lines) or Decimal(1)
            done = sum(Decimal(str(x.get("issued", 0))) + Decimal(str(x.get("procured", 0))) for x in lines)
            out.append(
                IndentResponse(
                    id=r.id,
                    indent_number=r.indent_number,
                    department_id=r.department_id,
                    department_code=depts.get(r.department_id),
                    store_id=r.store_id,
                    requested_by=r.requested_by,
                    requester_name=users.get(r.requested_by),
                    purpose=r.purpose,
                    priority=r.priority,
                    items=lines,
                    estimated_paise=r.estimated_paise,
                    budget_head_id=r.budget_head_id,
                    workflow_instance_id=r.workflow_instance_id,
                    workflow_step=steps.get(r.workflow_instance_id),
                    status=r.status,
                    fulfilment_pct=min(100, int(100 * done / need)),
                    quotations=int(quotes.get(r.id, 0)),
                    po_ids=pos.get(r.id, []),
                    created_at=r.created_at,
                )
            )
        return out

    async def list_indents(
        self,
        *,
        mine: bool = False,
        department_id: uuid.UUID | None = None,
        status: str | None = None,
        scope: str | None = None,
    ) -> list[IndentResponse]:
        q = select(Indent).where(Indent.institution_id == self.inst)
        if mine or scope == "self":
            q = q.where(Indent.requested_by == self.actor_id)
        else:
            q = q.where(indent_predicate(self.principal))
        if department_id:
            q = q.where(Indent.department_id == department_id)
        if status:
            q = q.where(Indent.status == status)
        return await self.outs(
            list((await self.db.execute(q.order_by(Indent.created_at.desc()).limit(1000))).scalars())
        )

    async def get_row(self, indent_id: uuid.UUID, *, for_update: bool = False) -> Indent:
        q = select(Indent).where(
            Indent.id == indent_id, Indent.institution_id == self.inst, indent_predicate(self.principal)
        )
        if for_update:
            q = q.with_for_update()
        r = (await self.db.execute(q)).scalar_one_or_none()
        if r is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Indent not found")
        return r

    async def get(self, indent_id: uuid.UUID) -> IndentResponse:
        return (await self.outs([await self.get_row(indent_id)]))[0]

    async def _lines(self, items: list[Any]) -> tuple[list[dict[str, Any]], int]:
        out, total = [], 0
        for n, line in enumerate(items):
            d = line.model_dump(mode="json")
            if not d.get("item_id") and not d.get("free_text"):
                raise APIError(422, ErrorCode.VALIDATION, f"Line {n + 1}: pick an item or describe it", {"line": n})
            if d.get("item_id"):
                it = (
                    await self.db.execute(
                        select(Item).where(Item.id == uuid.UUID(d["item_id"]), Item.institution_id == self.inst)
                    )
                ).scalar_one_or_none()
                if it is None:
                    raise APIError(422, ErrorCode.VALIDATION, f"Line {n + 1}: unknown item", {"line": n})
                d["name"] = it.name
                d["unit"] = d.get("unit") or it.unit
                if not d.get("est_unit_cost_paise"):
                    d["est_unit_cost_paise"] = it.unit_cost_paise or 0
            d.setdefault("issued", 0)
            d.setdefault("procured", 0)
            total += int(Decimal(str(d["qty"])) * Decimal(d["est_unit_cost_paise"] or 0))
            out.append(d)
        return out, total

    async def _department(self, department_id: uuid.UUID | None) -> uuid.UUID | None:
        if department_id:
            return department_id
        return (
            await self.db.execute(select(Staff.department_id).where(Staff.user_id == self.actor_id))
        ).scalar_one_or_none()

    async def create(self, body: IndentCreate) -> IndentResponse:
        self.require("indent")
        lines, total = await self._lines(body.items)
        r = Indent(
            institution_id=self.inst,
            indent_number=await self.sequence("indent", "IND"),
            department_id=await self._department(body.department_id),
            store_id=body.store_id,
            requested_by=self.actor_id or uuid.uuid4(),
            purpose=body.purpose,
            priority=body.priority,
            items=lines,
            estimated_paise=total,
            budget_head_id=body.budget_head_id,
            status="draft",
        )
        self.db.add(r)
        await self.db.flush()
        if body.emergency_approval_ref:
            await self.put_meta("indent", r.id, {"emergency_approval_ref": body.emergency_approval_ref})
        await self._audit("create", ENTITY, r.id, None, snap(r, KEYS))
        return (await self.outs([r]))[0]

    async def update(self, indent_id: uuid.UUID, body: IndentUpdate) -> IndentResponse:
        r = await self.get_row(indent_id, for_update=True)
        if r.requested_by != self.actor_id and not self.can(INV, "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the requester edits an indent")
        if r.status != "draft":
            raise rule("Only a draft indent can be edited", "NOT_DRAFT")
        data = body.model_dump(exclude_unset=True)
        if "items" in data:
            r.items, r.estimated_paise = await self._lines(body.items or [])
            data.pop("items")
        if "emergency_approval_ref" in data:
            await self.put_meta(
                "indent",
                r.id,
                (await self.meta("indent", r.id)) | {"emergency_approval_ref": data.pop("emergency_approval_ref")},
            )
        for k, v in data.items():
            setattr(r, k, v)
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def submit(self, indent_id: uuid.UUID) -> IndentResponse:
        r = await self.get_row(indent_id, for_update=True)
        if r.requested_by != self.actor_id and not self.can(INV, "manage"):
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Only the requester submits an indent")
        if r.status != "draft":
            raise rule("The indent is already submitted", "NOT_DRAFT")
        inst = await workflow_engine.start(
            self.db,
            institution_id=self.inst,
            key="procurement.indent",
            entity_type=ENTITY,
            entity_id=r.id,
            started_by=self.actor_id,
            context={
                "department_id": str(r.department_id) if r.department_id else None,
                "amount_paise": r.estimated_paise,
                "priority": r.priority,
            },
            title=f"Indent {r.indent_number}",
        )
        r.workflow_instance_id, r.status = inst.id, "submitted"
        await self.db.flush()
        await self._audit("submit", ENTITY, r.id, None, snap(r, KEYS))
        await self._emit(
            "inventory.indent_submitted", {"indent_id": str(r.id), "estimated_paise": r.estimated_paise}, ENTITY, r.id
        )
        return (await self.outs([r]))[0]

    # ---- workflow outcomes --------------------------------------------------------------------------------------------------
    async def budget_ok(self, r: Indent) -> tuple[bool, str | None]:
        if r.budget_head_id is None or not await self.feature("accounting.budgets"):
            return True, None
        row = (
            await self.db.execute(
                text("SELECT allocated_paise, utilised_paise, committed_paise, name FROM budget_heads WHERE id = :i"),
                {"i": r.budget_head_id},
            )
        ).first()
        if row is None:
            return False, "Budget head not found"
        available = int(row.allocated_paise) - int(row.utilised_paise) - int(row.committed_paise)
        if available < int(r.estimated_paise or 0):
            return (
                False,
                f"Budget {row.name}: available ₹{available / 100:,.2f} < estimate ₹{(r.estimated_paise or 0) / 100:,.2f}",
            )
        return True, None

    async def approved(self, r: Indent) -> None:
        ok, reason = await self.budget_ok(r)
        if not ok:
            r.status = "draft"
            await self.put_meta("indent", r.id, (await self.meta("indent", r.id)) | {"changes_requested": reason})
            await self._audit("changes_requested", ENTITY, r.id, None, {"reason": reason})
            await self._notify(
                "inventory.indent_rejected", [r.requested_by], {"indent": r.indent_number, "reason": reason}
            )
            return
        r.status = "approved"
        if r.budget_head_id and await self.feature("accounting.budgets"):
            await self.db.execute(
                text("UPDATE budget_heads SET committed_paise = committed_paise + :a WHERE id = :i"),
                {"a": int(r.estimated_paise or 0), "i": r.budget_head_id},
            )
            await self._emit(
                "budget.commit_requested",
                {"budget_head_id": str(r.budget_head_id), "amount_paise": r.estimated_paise, "indent_id": str(r.id), "applied": True},
                ENTITY,
                r.id,
            )
        await self._audit("approve", ENTITY, r.id, None, snap(r, KEYS))
        await self._emit("inventory.indent_approved", {"indent_id": str(r.id)}, ENTITY, r.id)
        await self._notify("inventory.indent_approved", [r.requested_by], {"indent": r.indent_number})

    async def release_commitment(self, r: Indent, amount: int | None = None) -> None:
        if r.budget_head_id and await self.feature("accounting.budgets"):
            amt = int(amount if amount is not None else r.estimated_paise or 0)
            await self.db.execute(
                text("UPDATE budget_heads SET committed_paise = GREATEST(committed_paise - :a, 0) WHERE id = :i"),
                {"a": amt, "i": r.budget_head_id},
            )
            await self._emit(
                "budget.commit_released",
                {"budget_head_id": str(r.budget_head_id), "amount_paise": amt, "indent_id": str(r.id), "applied": True},
                ENTITY,
                r.id,
            )

    # ---- fulfilment -------------------------------------------------------------------------------------------------------
    async def fulfil(self, indent_id: uuid.UUID, body: IndentFulfil) -> IndentResponse:
        from app.services.inventory.stock_service import StockService

        self.require("issue")
        r = await self.get_row(indent_id, for_update=True)
        if r.status != "approved":
            raise rule("Only an approved indent can be fulfilled", "NOT_APPROVED")
        store_id = body.store_id or r.store_id
        if store_id is None:
            raise APIError(422, ErrorCode.VALIDATION, "Pick the issuing store", {"field": "store_id"})
        lines = [dict(x) for x in r.items]
        issue: list[StockLine] = []
        for f in body.items:
            if f.line >= len(lines) or not lines[f.line].get("item_id"):
                raise APIError(422, ErrorCode.VALIDATION, f"Line {f.line + 1} has no stock item", {"line": f.line})
            ln = lines[f.line]
            left = Decimal(str(ln["qty"])) - Decimal(str(ln.get("issued", 0))) - Decimal(str(ln.get("procured", 0)))
            if Decimal(str(f.qty_from_stock)) > left:
                raise APIError(
                    422, ErrorCode.VALIDATION, f"Line {f.line + 1}: only {left} left to fulfil", {"line": f.line}
                )
            ln["issued"] = float(Decimal(str(ln.get("issued", 0))) + Decimal(str(f.qty_from_stock)))
            issue.append(StockLine(item_id=uuid.UUID(ln["item_id"]), quantity=f.qty_from_stock))
        await StockService(self.db, self.principal, self.request, self.inst).issue(
            StockIssueRequest(
                store_id=store_id,
                items=issue,
                issued_to_type="department",
                issued_to_id=r.department_id,
                reference_type="indent",
                reference_id=r.id,
                safety_ack=body.safety_ack,
            )
        )
        r.items = lines
        if all(
            Decimal(str(x.get("issued", 0))) + Decimal(str(x.get("procured", 0))) >= Decimal(str(x["qty"]))
            for x in lines
        ):
            r.status = "fulfilled"
            await self._emit("inventory.indent_fulfilled", {"indent_id": str(r.id)}, ENTITY, r.id)
            await self._notify("inventory.indent_fulfilled", [r.requested_by], {"indent": r.indent_number})
        await self.db.flush()
        return (await self.outs([r]))[0]

    async def mark_procured(self, r: Indent, item_qty: dict[str, float]) -> None:
        lines = [dict(x) for x in r.items]
        for ln in lines:
            if ln.get("item_id") in item_qty:
                ln["procured"] = float(Decimal(str(ln.get("procured", 0))) + Decimal(str(item_qty[ln["item_id"]])))
        r.items = lines

    async def close(self, indent_id: uuid.UUID) -> IndentResponse:
        r = await self.get_row(indent_id, for_update=True)
        if r.requested_by != self.actor_id and not self.can(INV, "manage"):
            raise APIError(
                403, ErrorCode.PERMISSION_DENIED, "Only the requester or the inventory manager closes an indent"
            )
        if r.status in ("closed", "rejected"):
            raise rule("The indent is already closed", "CLOSED")
        if r.status == "approved" and not any((x.get("procured") or 0) for x in r.items):
            await self.release_commitment(r)
        r.status = "closed"
        await self._audit("close", ENTITY, r.id, None, {"at": now_utc().isoformat()})
        await self._emit("inventory.indent_closed", {"indent_id": str(r.id)}, ENTITY, r.id)
        return (await self.outs([r]))[0]


@workflow_engine.on("procurement.indent", "step_approved")
async def _indent_step(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    r = (await db.execute(select(Indent).where(Indent.id == instance.entity_id).with_for_update())).scalar_one_or_none()
    if r is not None and r.status == "submitted":
        r.status = "hod_approved"


@workflow_engine.on("procurement.indent", "approved")
async def _indent_approved(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    r = (await db.execute(select(Indent).where(Indent.id == instance.entity_id).with_for_update())).scalar_one_or_none()
    if r is not None and r.status in ("submitted", "hod_approved"):
        await IndentService(db, actor, institution_id=instance.institution_id).approved(r)


@workflow_engine.on("procurement.indent", "rejected")
async def _indent_rejected(db: Any, instance: WorkflowInstance, actor: Any) -> None:
    r = (await db.execute(select(Indent).where(Indent.id == instance.entity_id))).scalar_one_or_none()
    if r is not None and r.status in ("submitted", "hod_approved"):
        r.status = "rejected"
        svc = IndentService(db, actor, institution_id=instance.institution_id)
        await svc._emit("inventory.indent_rejected", {"indent_id": str(r.id)}, ENTITY, r.id)
        await svc._notify(
            "inventory.indent_rejected", [r.requested_by], {"indent": r.indent_number, "reason": "rejected"}
        )
