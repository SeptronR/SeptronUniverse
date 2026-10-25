"""Assets — Prompts/22 §22.6 ``asset_service`` (``inventory.assets``, ``inventory.asset_qr``).

1. Register manually or in bulk from a GRN (one asset per accepted unit of a non-consumable line); ``asset_tag`` from
   the ``asset`` sequence (``AST/<CAT>/<n>`` fallback), depreciation method / rate from
   ``inventory.depreciation_defaults`` by category. QR labels (CR80 cards) encode a signed lookup token
   (``hex(asset id) + HMAC``); custody transfers wait for the new custodian's acceptance (pending transfer kept in
   ``inventory_meta``); ``condemned`` needs an approval reference, ``disposed`` records the sale value
   (``inventory.asset_disposed`` → Phase 23 income).
2. Depreciation per financial year (Apr–Mar): SLM ``cost × rate``, WDV ``current value × rate``, never below the salvage
   floor ``inventory.salvage_pct`` of cost; a second run for the same year → 409; ``asset.depreciated`` per run.
3. Physical audits: a cycle (scope department / room / category) lists the expected assets, scans add ``asset_audits``
   rows (``cycle:<id>`` in remarks), completion reports found / missing / unexpected / conditions; assets missing in two
   consecutive cycles are flagged.
"""

import hashlib
import hmac
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.errors import APIError, ErrorCode
from app.models.inventory import Asset, AssetAudit, GoodsReceipt, Item, PurchaseOrder
from app.models.platform import Department
from app.models.timetable import Room
from app.schemas.inventory import (
    AssetAuditScan,
    AssetAuditStart,
    AssetBulkFromGrn,
    AssetIn,
    AssetOut,
    AssetQrLabelsRequest,
    AssetStatusChange,
    AssetTransfer,
    AssetUpdate,
    AuditCycleOut,
    AuditReport,
    DepreciationSummary,
)
from app.services.inventory.common import INV, InventoryBase, my_staff_ids, now_utc, pairs, rule, unit_predicate
from app.services.students.common import snap

D = Decimal
KEYS = ("asset_tag", "status", "custodian_staff_id", "location_room_id", "department_id", "current_value_paise")
DEFAULT_DEPRECIATION = {"furniture": {"method": "wdv", "rate": 10}, "it": {"method": "slm", "rate": 33.33}}


def asset_token(asset_id: uuid.UUID) -> str:
    sig = hmac.new(settings.SECRET_KEY.encode(), f"asset:{asset_id}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"{asset_id.hex}{sig}"


def parse_asset_token(token: str) -> uuid.UUID | None:
    if len(token) != 48:  # noqa: PLR2004
        return None
    try:
        aid = uuid.UUID(token[:32])
    except ValueError:
        return None
    return aid if hmac.compare_digest(asset_token(aid), token) else None


def asset_predicate(p: Any) -> Any:
    return unit_predicate(p, Asset.department_id, Asset.college_id, Asset.custodian_staff_id, my_staff_ids(p))


def fy_bounds(fy: str) -> tuple[date, date]:
    start = int(fy[:4])
    return date(start, 4, 1), date(start + 1, 3, 31)


class AssetService(InventoryBase):
    async def outs(self, rows: list[Asset]) -> list[AssetOut]:
        names = await self.staff_names({a.custodian_staff_id for a in rows})
        rooms: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(Room.id, Room.name).where(
                        Room.id.in_({a.location_room_id for a in rows if a.location_room_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        depts: dict[Any, Any] = pairs(
            (
                await self.db.execute(
                    select(Department.id, Department.code).where(
                        Department.id.in_({a.department_id for a in rows if a.department_id} or {uuid.uuid4()})
                    )
                )
            ).all()
        )
        pending = await self.metas("asset_transfer") if rows else {}
        cost = self.can(INV, "view_all") or self.can(INV, "manage") or self.can("accounting", "view")
        out = []
        for a in rows:
            o = AssetOut.model_validate(a, from_attributes=True)
            o.custodian_name = names.get(a.custodian_staff_id) if a.custodian_staff_id else None
            o.location = rooms.get(a.location_room_id)
            o.department_code = depts.get(a.department_id)
            pt = pending.get(str(a.id), {})
            if pt.get("custodian_staff_id") and not pt.get("accepted_at"):
                o.pending_custodian_staff_id = uuid.UUID(pt["custodian_staff_id"])
            if not cost:
                o.cost_paise = o.current_value_paise = None
            out.append(o)
        return out

    async def list_assets(
        self,
        *,
        mine: bool = False,
        department_id: uuid.UUID | None = None,
        status: str | None = None,
        category: str | None = None,
        q: str | None = None,
    ) -> list[AssetOut]:
        stmt = select(Asset).where(Asset.institution_id == self.inst, Asset.deleted_at.is_(None))
        if mine:
            stmt = stmt.where(Asset.custodian_staff_id.in_(my_staff_ids(self.principal)))
        else:
            stmt = stmt.where(asset_predicate(self.principal))
        if department_id:
            stmt = stmt.where(Asset.department_id == department_id)
        if status:
            stmt = stmt.where(Asset.status == status)
        if category:
            stmt = stmt.where(Asset.category == category)
        if q:
            stmt = stmt.where(Asset.name.ilike(f"%{q}%") | Asset.asset_tag.ilike(f"%{q}%"))
        return await self.outs(list((await self.db.execute(stmt.order_by(Asset.asset_tag).limit(3000))).scalars()))

    async def row(self, asset_id: uuid.UUID, *, for_update: bool = False, any_scope: bool = False) -> Asset:
        q = select(Asset).where(Asset.id == asset_id, Asset.institution_id == self.inst, Asset.deleted_at.is_(None))
        if not any_scope:
            q = q.where(asset_predicate(self.principal))
        if for_update:
            q = q.with_for_update()
        a = (await self.db.execute(q)).scalar_one_or_none()
        if a is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Asset not found")
        return a

    async def get(self, asset_id: uuid.UUID) -> AssetOut:
        return (await self.outs([await self.row(asset_id)]))[0]

    async def _defaults(self, category: str | None) -> tuple[str, Decimal]:
        conf = await self.setting("inventory", "depreciation_defaults") or DEFAULT_DEPRECIATION
        key = (category or "").lower()
        hit = conf.get(key) or next((v for k, v in conf.items() if k in key), None) or {"method": "slm", "rate": 10}
        return str(hit.get("method", "slm")), D(str(hit.get("rate", 10)))

    async def _tag(self, category: str | None) -> str:
        from app.services.sequence_service import SequenceService

        try:
            return (
                await SequenceService(self.db, self.principal, self.request, self.inst).next("asset", None)
            ).rendered[:40]
        except APIError:
            cat = "".join(ch for ch in (category or "GEN").upper() if ch.isalnum())[:4] or "GEN"
            return f"AST/{cat}/{uuid.uuid4().hex[:8].upper()}"

    async def create(self, body: AssetIn, *, po_id: uuid.UUID | None = None) -> AssetOut:
        self.require("manage")
        method, rate = await self._defaults(body.category)
        a = Asset(
            institution_id=self.inst,
            asset_tag=await self._tag(body.category),
            **body.model_dump(exclude={"depreciation_method", "depreciation_rate"}),
            po_id=po_id,
            depreciation_method=body.depreciation_method or method,
            depreciation_rate=D(str(body.depreciation_rate)) if body.depreciation_rate is not None else rate,
            current_value_paise=body.cost_paise,
        )
        self.db.add(a)
        await self.db.flush()
        await self._audit("create", "asset", a.id, None, snap(a, KEYS))
        await self._emit("inventory.asset_created", {"asset_id": str(a.id), "tag": a.asset_tag}, "asset", a.id)
        return (await self.outs([a]))[0]

    async def from_grn(self, body: AssetBulkFromGrn) -> list[AssetOut]:
        self.require("manage")
        g = (
            await self.db.execute(
                select(GoodsReceipt).where(GoodsReceipt.id == body.grn_id, GoodsReceipt.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if g is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Goods receipt not found")
        po = (await self.db.execute(select(PurchaseOrder).where(PurchaseOrder.id == g.po_id))).scalar_one()
        made = (await self.meta("grn_assets", g.id)).get("item_ids", [])
        wanted = {str(i) for i in body.item_ids}
        out: list[AssetOut] = []
        for ln in g.items:
            if ln["item_id"] not in wanted or ln["item_id"] in made:
                continue
            item = (await self.db.execute(select(Item).where(Item.id == uuid.UUID(ln["item_id"])))).scalar_one()
            for _ in range(int(D(str(ln["accepted"])))):
                out.append(
                    await self.create(
                        AssetIn(
                            name=item.name,
                            category=body.category,
                            item_id=item.id,
                            location_room_id=body.location_room_id,
                            custodian_staff_id=body.custodian_staff_id,
                            department_id=body.department_id,
                            purchase_date=g.received_on,
                            cost_paise=int(ln["unit_price_paise"]),
                        ),
                        po_id=po.id,
                    )
                )
            made.append(ln["item_id"])
        if not out:
            raise rule("No new asset lines on this GRN", "NOTHING_TO_CREATE")
        await self.put_meta("grn_assets", g.id, {"item_ids": made})
        return out

    async def update(self, asset_id: uuid.UUID, body: AssetUpdate) -> AssetOut:
        self.require("manage")
        a = await self.row(asset_id, for_update=True)
        if body.version is not None and body.version != a.version:
            raise APIError(409, ErrorCode.CONFLICT, "The asset was changed by someone else", {"version": a.version})
        for k, v in body.model_dump(exclude_unset=True, exclude={"version"}).items():
            setattr(a, k, v)
        a.version += 1
        await self.db.flush()
        return (await self.outs([a]))[0]

    async def transfer(self, asset_id: uuid.UUID, body: AssetTransfer) -> AssetOut:
        self.require("manage", "asset_audit")
        a = await self.row(asset_id, for_update=True)
        old = snap(a, KEYS)
        if body.location_room_id is not None:
            a.location_room_id = body.location_room_id
        if body.department_id is not None:
            a.department_id = body.department_id
        if body.custodian_staff_id is not None and body.custodian_staff_id != a.custodian_staff_id:
            await self.put_meta(
                "asset_transfer",
                a.id,
                {
                    "custodian_staff_id": str(body.custodian_staff_id),
                    "requested_at": now_utc().isoformat(),
                    "by": str(self.actor_id),
                },
            )
            from app.models.hr import Staff

            uid = (
                await self.db.execute(select(Staff.user_id).where(Staff.id == body.custodian_staff_id))
            ).scalar_one_or_none()
            await self._notify("inventory.asset_assigned", [uid], {"asset": f"{a.asset_tag} {a.name}"})
        await self.db.flush()
        await self._audit(
            "transfer",
            "asset",
            a.id,
            old,
            snap(a, KEYS) | {"pending_custodian": str(body.custodian_staff_id) if body.custodian_staff_id else None},
        )
        await self._emit("inventory.asset_transferred", {"asset_id": str(a.id)}, "asset", a.id)
        return (await self.outs([a]))[0]

    async def accept_custody(self, asset_id: uuid.UUID) -> AssetOut:
        a = await self.row(asset_id, for_update=True, any_scope=True)
        pt = await self.meta("asset_transfer", a.id)
        mine = [str(x) for x in (await self.db.execute(my_staff_ids(self.principal))).scalars()]
        if not pt.get("custodian_staff_id") or pt.get("accepted_at") or pt["custodian_staff_id"] not in mine:
            raise APIError(404, ErrorCode.NOT_FOUND, "No custody transfer awaits you for this asset")
        old = snap(a, KEYS)
        a.custodian_staff_id = uuid.UUID(pt["custodian_staff_id"])
        pt["accepted_at"] = now_utc().isoformat()
        hist = (await self.meta("asset_history", a.id)).get("custody", [])
        hist.append({"from": old["custodian_staff_id"], "to": pt["custodian_staff_id"], "at": pt["accepted_at"]})
        await self.put_meta("asset_history", a.id, {"custody": hist})
        await self.put_meta("asset_transfer", a.id, pt)
        await self._audit("accept_custody", "asset", a.id, old, snap(a, KEYS))
        return (await self.outs([a]))[0]

    async def set_status(self, asset_id: uuid.UUID, body: AssetStatusChange) -> AssetOut:
        self.require("manage")
        a = await self.row(asset_id, for_update=True)
        if a.status == "disposed":
            raise rule("The asset is disposed", "DISPOSED")
        if body.status in ("condemned", "disposed") and not body.approval_ref and a.status != "condemned":
            raise APIError(
                422,
                ErrorCode.VALIDATION,
                "Condemnation needs a committee / approval reference",
                {"field": "approval_ref"},
            )
        old = snap(a, KEYS)
        a.status = body.status
        if body.status == "disposed":
            a.is_active = False
            await self._emit(
                "inventory.asset_disposed",
                {
                    "asset_id": str(a.id),
                    "sale_value_paise": body.sale_value_paise or 0,
                    "book_value_paise": a.current_value_paise or 0,
                },
                "asset",
                a.id,
            )
            a.current_value_paise = 0
        await self.db.flush()
        await self._audit(
            "status",
            "asset",
            a.id,
            old,
            snap(a, KEYS)
            | {
                "reason": body.reason,
                "approval_ref": body.approval_ref,
                "service_request_id": str(body.service_request_id) if body.service_request_id else None,
            },
        )
        await self._emit(
            "inventory.asset_status_changed",
            {
                "asset_id": str(a.id),
                "status": a.status,
                "service_request_id": str(body.service_request_id) if body.service_request_id else None,
            },
            "asset",
            a.id,
        )
        return (await self.outs([a]))[0]

    async def history(self, asset_id: uuid.UUID) -> dict[str, Any]:
        a = await self.row(asset_id)
        audits = (
            await self.db.execute(
                select(AssetAudit).where(AssetAudit.asset_id == a.id).order_by(AssetAudit.audited_on.desc())
            )
        ).scalars()
        return {
            "custody": (await self.meta("asset_history", a.id)).get("custody", []),
            "pending_transfer": await self.meta("asset_transfer", a.id),
            "depreciation": (await self.meta("asset_depreciation", a.id)).get("runs", []),
            "audits": [
                {"on": x.audited_on.isoformat(), "found": x.found, "condition": x.condition, "remarks": x.remarks}
                for x in audits
            ],
            "schedule": self.schedule(a, 5),
        }

    @staticmethod
    def schedule(a: Asset, years: int) -> list[dict[str, Any]]:
        value = D(a.current_value_paise or a.cost_paise or 0)
        cost = D(a.cost_paise or 0)
        rate = D(a.depreciation_rate or 0) / 100
        out = []
        for n in range(1, years + 1):
            dep = (
                (cost * rate)
                if a.depreciation_method == "slm"
                else (value * rate)
                if a.depreciation_method == "wdv"
                else D(0)
            )
            dep = min(dep, value)
            value -= dep
            out.append({"year": n, "depreciation_paise": int(dep), "closing_paise": int(value)})
        return out

    # ---- QR -------------------------------------------------------------------------------------------------------------
    async def lookup(self, token: str) -> AssetOut:
        aid = parse_asset_token(token)
        if aid is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Unknown asset label")
        return (await self.outs([await self.row(aid, any_scope=True)]))[0]

    async def qr_labels(self, body: AssetQrLabelsRequest) -> bytes:
        from app.utils.pdf import id_card_pdf

        self.require("manage")
        q = select(Asset).where(Asset.institution_id == self.inst, Asset.deleted_at.is_(None))
        if body.asset_ids:
            q = q.where(Asset.id.in_(body.asset_ids))
        if body.department_id:
            q = q.where(Asset.department_id == body.department_id)
        if body.category:
            q = q.where(Asset.category == body.category)
        rows = list((await self.db.execute(q.order_by(Asset.asset_tag).limit(1000))).scalars())
        base = settings.frontend_url
        inst = await self.institution()
        cards = []
        for a in rows:
            url = f"{base}/assets/scan/{asset_token(a.id)}"
            a.qr_code_url = url
            cards.append(
                {
                    "institution": inst.name,
                    "college": "Asset label",
                    "name": a.name,
                    "registration_number": a.asset_tag,
                    "program": a.category or "",
                    "batch": a.serial_no or "",
                    "valid_until": a.purchase_date.isoformat() if a.purchase_date else "",
                    "verify_url": url,
                }
            )
        await self.db.flush()
        return id_card_pdf(cards)

    # ---- depreciation ------------------------------------------------------------------------------------------------------
    async def depreciation(self, fy: str, *, preview: bool = False) -> DepreciationSummary:
        if not preview:
            self.require("manage")
        runs = await self.meta("depreciation_run", fy)
        if runs.get("run_at") and not preview:
            raise rule(f"Depreciation for {fy} has already run", "ALREADY_RUN", run_at=runs["run_at"])
        _, end = fy_bounds(fy)
        salvage = D(str(await self.setting("inventory", "salvage_pct") or 5)) / 100
        rows = (
            (
                await self.db.execute(
                    select(Asset).where(
                        Asset.institution_id == self.inst,
                        Asset.deleted_at.is_(None),
                        Asset.status.notin_(("disposed",)),
                        (Asset.purchase_date.is_(None)) | (Asset.purchase_date <= end),
                        Asset.depreciation_method.in_(("slm", "wdv")),
                    )
                )
            )
            .scalars()
            .all()
        )
        total, out = 0, []
        for a in rows:
            cost = D(a.cost_paise or 0)
            value = D(a.current_value_paise if a.current_value_paise is not None else cost)
            rate = D(a.depreciation_rate or 0) / 100
            dep = cost * rate if a.depreciation_method == "slm" else value * rate
            floor = cost * salvage
            dep = max(D(0), min(dep, value - floor))
            if dep <= 0:
                continue
            total += int(dep)
            out.append(
                {
                    "asset_id": str(a.id),
                    "tag": a.asset_tag,
                    "method": a.depreciation_method,
                    "opening_paise": int(value),
                    "depreciation_paise": int(dep),
                    "closing_paise": int(value - dep),
                }
            )
            if not preview:
                a.current_value_paise = int(value - dep)
                h = await self.meta("asset_depreciation", a.id)
                h.setdefault("runs", []).append(
                    {"fy": fy, "depreciation_paise": int(dep), "closing_paise": int(value - dep)}
                )
                await self.put_meta("asset_depreciation", a.id, h)
        if not preview:
            await self.put_meta(
                "depreciation_run",
                fy,
                {"run_at": now_utc().isoformat(), "assets": len(out), "depreciation_paise": total, "rows": out[:2000]},
            )
            await self._audit("depreciation_run", "asset", None, None, {"fy": fy, "assets": len(out), "total": total})
            await self._emit(
                "asset.depreciated",
                {"financial_year": fy, "depreciation_paise": total, "assets": len(out)},
                "asset",
                None,
            )
            await self._emit(
                "inventory.asset_depreciated", {"financial_year": fy, "depreciation_paise": total}, "asset", None
            )
        return DepreciationSummary(
            financial_year=fy, assets=len(out), depreciation_paise=total, rows=out[:500], preview=preview
        )

    async def depreciation_schedule(self, fy: str) -> DepreciationSummary:
        stored = await self.meta("depreciation_run", fy)
        if stored.get("run_at"):
            return DepreciationSummary(
                financial_year=fy,
                assets=int(stored["assets"]),
                depreciation_paise=int(stored["depreciation_paise"]),
                rows=stored.get("rows", [])[:500],
            )
        return await self.depreciation(fy, preview=True)

    # ---- audits --------------------------------------------------------------------------------------------------------------
    def _scope_q(self, scope: dict[str, Any]) -> Any:
        q = select(Asset).where(
            Asset.institution_id == self.inst, Asset.deleted_at.is_(None), Asset.status != "disposed"
        )
        if scope.get("department_id"):
            q = q.where(Asset.department_id == uuid.UUID(scope["department_id"]))
        if scope.get("location_room_id"):
            q = q.where(Asset.location_room_id == uuid.UUID(scope["location_room_id"]))
        if scope.get("category"):
            q = q.where(Asset.category == scope["category"])
        return q

    async def cycle(self, audit_id: uuid.UUID) -> dict[str, Any]:
        c = await self.meta("audit_cycle", audit_id)
        if not c:
            raise APIError(404, ErrorCode.NOT_FOUND, "Audit cycle not found")
        return c

    def cycle_out(self, cid: str, c: dict[str, Any]) -> AuditCycleOut:
        return AuditCycleOut(
            id=uuid.UUID(cid),
            name=c.get("name") or "Asset audit",
            scope=c.get("scope", {}),
            started_on=date.fromisoformat(c["started_on"]),
            status=c.get("status", "open"),
            expected=len(c.get("expected", [])),
            scanned=len(c.get("scanned", {})),
            completed_on=date.fromisoformat(c["completed_on"]) if c.get("completed_on") else None,
        )

    async def cycles(self) -> list[AuditCycleOut]:
        self.require("asset_audit", "view_all")
        return sorted(
            (self.cycle_out(k, v) for k, v in (await self.metas("audit_cycle")).items()),
            key=lambda x: x.started_on,
            reverse=True,
        )

    async def start_audit(self, body: AssetAuditStart) -> AuditCycleOut:
        self.require("asset_audit")
        scope = {k: (str(v) if v else None) for k, v in body.model_dump(exclude={"name"}).items()}
        expected = [
            str(a.id)
            for a in (await self.db.execute(self._scope_q(scope).where(asset_predicate(self.principal)))).scalars()
        ]
        cid = uuid.uuid4()
        c = {
            "name": body.name or "Asset audit",
            "scope": scope,
            "started_on": (await self.today()).isoformat(),
            "status": "open",
            "expected": expected,
            "scanned": {},
            "by": str(self.actor_id),
        }
        await self.put_meta("audit_cycle", cid, c)
        await self._emit(
            "inventory.audit_started", {"audit_id": str(cid), "expected": len(expected)}, "asset_audit", cid
        )
        return self.cycle_out(str(cid), c)

    async def scan(self, audit_id: uuid.UUID, body: AssetAuditScan) -> AuditCycleOut:
        self.require("asset_audit")
        c = await self.cycle(audit_id)
        if c.get("status") != "open":
            raise rule("The audit cycle is closed", "AUDIT_CLOSED")
        today = await self.today()
        for s in body.scans:
            aid: uuid.UUID | None = parse_asset_token(s.qr) if s.qr else None
            if aid is None and s.asset_tag:
                aid = (
                    await self.db.execute(
                        select(Asset.id).where(Asset.institution_id == self.inst, Asset.asset_tag == s.asset_tag)
                    )
                ).scalar_one_or_none()
            if aid is None:
                continue
            if str(aid) in c["scanned"]:
                continue
            self.db.add(
                AssetAudit(
                    institution_id=self.inst,
                    asset_id=aid,
                    audited_on=today,
                    audited_by=self.actor_id,
                    found=True,
                    condition=s.condition,
                    remarks=f"cycle:{audit_id}" + (f" | {s.remarks}" if s.remarks else ""),
                    scanned_qr=bool(s.qr),
                )
            )
            c["scanned"][str(aid)] = s.condition
        await self.db.flush()
        await self.put_meta("audit_cycle", audit_id, c)
        return self.cycle_out(str(audit_id), c)

    async def complete(self, audit_id: uuid.UUID) -> AuditReport:
        self.require("asset_audit")
        c = await self.cycle(audit_id)
        if c.get("status") != "open":
            raise rule("The audit cycle is already complete", "AUDIT_CLOSED")
        today = await self.today()
        expected, scanned = set(c["expected"]), set(c["scanned"])
        missing = expected - scanned
        for aid in missing:
            self.db.add(
                AssetAudit(
                    institution_id=self.inst,
                    asset_id=uuid.UUID(aid),
                    audited_on=today,
                    audited_by=self.actor_id,
                    found=False,
                    remarks=f"cycle:{audit_id} | missing",
                )
            )
        # missing in the previous closed cycle of the same scope too → flagged
        flagged: list[str] = []
        prev = [
            v
            for k, v in (await self.metas("audit_cycle")).items()
            if k != str(audit_id) and v.get("status") == "completed" and v.get("scope") == c.get("scope")
        ]
        if prev:
            last = max(prev, key=lambda v: v.get("completed_on", ""))
            flagged = sorted(missing & set(last.get("missing", [])))
        c.update(status="completed", completed_on=today.isoformat(), missing=sorted(missing), flagged=flagged)
        await self.put_meta("audit_cycle", audit_id, c)
        await self.db.flush()
        await self._emit(
            "inventory.audit_completed",
            {"audit_id": str(audit_id), "missing": len(missing), "flagged": len(flagged)},
            "asset_audit",
            audit_id,
        )
        return await self.report(audit_id)

    async def report(self, audit_id: uuid.UUID) -> AuditReport:
        c = await self.cycle(audit_id)
        expected, scanned = set(c["expected"]), set(c["scanned"])
        missing, unexpected = expected - scanned, scanned - expected
        conds: dict[str, int] = {}
        for v in c["scanned"].values():
            conds[v] = conds.get(v, 0) + 1
        tags = {
            str(a.id): {"id": str(a.id), "tag": a.asset_tag, "name": a.name}
            for a in (
                await self.db.execute(
                    select(Asset).where(Asset.id.in_([uuid.UUID(x) for x in missing | unexpected] or [uuid.uuid4()]))
                )
            ).scalars()
        }
        return AuditReport(
            audit_id=audit_id,
            expected=len(expected),
            found=len(scanned & expected),
            missing=len(missing),
            unexpected=len(unexpected),
            conditions=conds,
            missing_assets=[tags[x] for x in sorted(missing) if x in tags],
            unexpected_assets=[tags[x] for x in sorted(unexpected) if x in tags],
            flagged=c.get("flagged", []),
        )

    # ---- Beat ------------------------------------------------------------------------------------------------------------------
    async def warranty_scan(self) -> int:
        from datetime import timedelta

        today = await self.today()
        rows = (
            (
                await self.db.execute(
                    select(Asset).where(
                        Asset.institution_id == self.inst,
                        Asset.warranty_until.between(today, today + timedelta(days=30)),
                        Asset.status != "disposed",
                    )
                )
            )
            .scalars()
            .all()
        )
        if rows:
            await self._notify(
                "inventory.audit_due",
                [],
                {"count": len(rows), "what": "warranties expiring within 30 days"},
                audience={"roles": ["inventory_manager"]},
            )
        return len(rows)

    async def audit_due(self) -> int:
        months = int(await self.setting("inventory", "audit_cycle_months") or 12)
        today = await self.today()
        done = [str(v["completed_on"]) for v in (await self.metas("audit_cycle")).values() if v.get("completed_on")]
        last = max(done) if done else None
        if last and (today - date.fromisoformat(last)).days < months * 30:
            return 0
        await self._notify(
            "inventory.audit_due",
            [],
            {"count": 1, "what": f"physical asset audit (last {last or 'never'})"},
            audience={"roles": ["inventory_manager"]},
        )
        return 1
