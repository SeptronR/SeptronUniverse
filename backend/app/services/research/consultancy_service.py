"""Consultancy — Prompts/30 §30.6 ``consultancy_service`` ({research.consultancy}).

Agreements per faculty member; ``institution_share_paise`` is computed from ``research.consultancy_share_pct``
(default institution 30 / faculty 70) under ``FOR UPDATE``; an override needs the research cell (403 for faculty —
the approval is recorded in the side store). Receipts go through a Phase 12 invoice (``payer_type='company'``,
``payer_id`` = the consultancy, ``source_type='consultancy'``, head ``OTHER``); the accountant collects offline modes
at once, online / pending invoices settle through ``fees.payment_received``. A settled receipt books the institution
share as income (Phase 23 fee posting + ``research.consultancy_receipt``) and requests the faculty share through
``payroll.earning_requested`` (TDS by payroll). NAAC 3.5.x revenue counts come from ``stats_service``.
"""

import contextlib
import uuid
from typing import Any

from sqlalchemy import extract, func, select, true

from app.core.errors import APIError
from app.models.research import Consultancy
from app.schemas.research import (
    ConsultancyIn,
    ConsultancyOut,
    ConsultancyReceipt,
    ConsultancyShares,
    ConsultancyUpdate,
)
from app.services.research.common import ResearchBase, forbidden, not_found, now_utc, rule, staff_name

MODE = {"bank_transfer": "neft", "online": "gateway", "cheque": "cheque", "upi": "upi", "cash": "cash"}


class ConsultancyService(ResearchBase):
    async def predicate(self, scope: str | None = None) -> Any:
        if scope in (None, "all") and self.money_reader():
            return true()
        return await self.owned_predicate(Consultancy.staff_id, scope=scope)

    async def row(self, cid: uuid.UUID, *, lock: bool = False, visible: bool = True) -> Consultancy:
        stmt = select(Consultancy).where(Consultancy.id == cid, Consultancy.institution_id == self.inst)
        if visible:
            stmt = stmt.where(await self.predicate())
        c = (await self.db.execute(stmt.with_for_update() if lock else stmt)).scalar_one_or_none()
        if c is None:
            raise not_found("Consultancy")
        return c

    async def pct(self) -> float:
        v = await self.json_setting("consultancy_share_pct", {"institution": 30, "faculty": 70})
        try:
            return float(v.get("institution", 30))
        except (AttributeError, TypeError, ValueError):
            return 30.0

    async def outs(self, rows: list[Consultancy]) -> list[ConsultancyOut]:
        staff = await self.staff_map([r.staff_id for r in rows])
        metas = await self.metas("consultancy", [r.id for r in rows]) if rows else {}
        out = []
        for r in rows:
            m = metas.get(str(r.id), {})
            receipts = list(m.get("receipts") or [])
            inst = int(r.institution_share_paise or 0)
            out.append(
                ConsultancyOut(
                    id=r.id,
                    staff_id=r.staff_id,
                    staff_name=staff_name(staff.get(r.staff_id)),
                    client=r.client,
                    title=r.title,
                    amount_paise=r.amount_paise,
                    institution_share_paise=inst,
                    faculty_share_paise=int(r.amount_paise or 0) - inst,
                    share_overridden=bool(m.get("override")),
                    received_paise=sum(int(x.get("amount_paise", 0)) for x in receipts if x.get("status") == "paid"),
                    start_on=r.start_on,
                    end_on=r.end_on,
                    status=r.status,
                    agreement_url=m.get("agreement_url"),
                    receipts=receipts,
                )
            )
        return out

    async def query(
        self, *, staff_id: uuid.UUID | None = None, status: str | None = None, scope: str | None = None
    ) -> list[ConsultancyOut]:
        stmt = select(Consultancy).where(Consultancy.institution_id == self.inst, await self.predicate(scope))
        if staff_id:
            stmt = stmt.where(Consultancy.staff_id == staff_id)
        if status:
            stmt = stmt.where(Consultancy.status == status)
        return await self.outs(list((await self.db.execute(stmt.order_by(Consultancy.created_at.desc()))).scalars()))

    async def create(self, body: ConsultancyIn) -> ConsultancyOut:
        self.require_writer()
        owner = (
            (await self.staff_row(body.staff_id)).id
            if body.staff_id and self.cell()
            else (await self.require_my_staff()).id
        )
        auto = round(body.amount_paise * await self.pct() / 100)
        override = body.institution_share_paise is not None and body.institution_share_paise != auto
        if override and not self.cell():
            raise forbidden("Overriding the institution share needs the research cell's approval")
        c = Consultancy(
            institution_id=self.inst,
            staff_id=owner,
            client=body.client,
            title=body.title,
            amount_paise=body.amount_paise,
            institution_share_paise=body.institution_share_paise if override else auto,
            start_on=body.start_on,
            end_on=body.end_on,
            status="ongoing",
        )
        self.db.add(c)
        await self.db.flush()
        await self.put_meta(
            "consultancy",
            c.id,
            {
                "agreement_url": body.agreement_url,
                "client_gstin": body.client_gstin,
                "override": {"by": str(self.actor_id), "auto_paise": auto} if override else None,
                "receipts": [],
            },
        )
        await self._audit("create", "consultancy", c.id, None, body.model_dump(mode="json"))
        await self._emit(
            "research.consultancy_created",
            {"consultancy_id": str(c.id), "staff_id": str(owner), "amount_paise": c.amount_paise},
            "consultancy",
            c.id,
        )
        return (await self.outs([c]))[0]

    async def update(self, cid: uuid.UUID, body: ConsultancyUpdate) -> ConsultancyOut:
        self.require_writer()
        c = await self.row(cid, lock=True)
        if not self.cell() and not await self.is_mine(c.staff_id):
            raise forbidden("Only the consultant or the research cell edits the agreement")
        data = body.model_dump(exclude_unset=True)
        m = await self.meta("consultancy", c.id)
        if "agreement_url" in data:
            m["agreement_url"] = data.pop("agreement_url")
        share = data.pop("institution_share_paise", None)
        for k, v in data.items():
            setattr(c, k, v)
        auto = round(int(c.amount_paise or 0) * await self.pct() / 100)
        if share is not None and share != auto:
            if not self.cell():
                raise forbidden("Overriding the institution share needs the research cell's approval")
            c.institution_share_paise = share
            m["override"] = {"by": str(self.actor_id), "auto_paise": auto, "at": now_utc().isoformat()}
        elif not m.get("override"):
            c.institution_share_paise = auto
        await self.put_meta("consultancy", c.id, m)
        await self.db.flush()
        await self._audit("update", "consultancy", c.id, None, body.model_dump(exclude_unset=True, mode="json"))
        return (await self.outs([c]))[0]

    async def receipt(self, cid: uuid.UUID, body: ConsultancyReceipt) -> ConsultancyOut:
        self.require_writer()
        c = await self.row(cid, lock=True)
        if not (self.cell() or self.money_reader() or await self.is_mine(c.staff_id)):
            raise forbidden("Receipts are raised by the consultant, the research cell or accounts")
        m = await self.meta("consultancy", c.id)
        receipts = list(m.get("receipts") or [])
        billed = sum(int(r.get("amount_paise", 0)) for r in receipts if r.get("status") != "cancelled")
        if billed + body.amount_paise > int(c.amount_paise or 0):
            raise rule("Receipts would exceed the agreement value", "OVER_AGREEMENT")
        from app.schemas.fees import InvoiceCreate, InvoiceItemIn
        from app.services.fees.invoice_service import InvoiceService

        rid = uuid.uuid4()
        inv = await InvoiceService(self.db, None, None, self.inst).create_invoice(
            InvoiceCreate(
                payer_type="company",
                payer_id=c.id,
                source_type="consultancy",
                source_id=c.id,
                description=f"Consultancy · {c.client}"[:200],
                items=[
                    InvoiceItemIn(
                        description=f"Consultancy · {c.title or c.client}"[:200],
                        amount_paise=body.amount_paise,
                        head_code="OTHER",
                    )
                ],
                due_date=await self.today(),
                allow_multiple=True,
            ),
            notify=False,
        )
        entry: dict[str, Any] = {
            "id": str(rid),
            "invoice_id": str(inv.id),
            "amount_paise": body.amount_paise,
            "mode": body.mode,
            "reference": body.reference,
            "status": "invoiced",
            "at": now_utc().isoformat(),
        }
        receipts.append(entry)
        m["receipts"] = receipts
        await self.put_meta("consultancy", c.id, m)
        if body.mode != "online" and self.can("fees", "collect"):
            from app.schemas.fees import CollectRequest
            from app.services.fees.payment_service import PaymentService

            with contextlib.suppress(APIError):
                await PaymentService(self.db, self.principal, self.request, self.inst).collect(
                    CollectRequest(
                        invoice_id=inv.id,
                        amount_paise=body.amount_paise,
                        mode=MODE[body.mode],
                        reference=body.reference or f"CONS-{str(c.id)[:8]}",
                    ),
                    None,
                )
        return (await self.outs([await self.row(c.id)]))[0]

    async def on_payment(self, p: dict[str, Any]) -> bool:
        """``fees.payment_received(source_type=consultancy)``: mark the receipt paid, book the shares."""
        if not p.get("source_id") or not p.get("invoice_id"):
            return False
        c = await self.row(uuid.UUID(str(p["source_id"])), lock=True, visible=False)
        m = await self.meta("consultancy", c.id)
        receipts = list(m.get("receipts") or [])
        entry = next((r for r in receipts if r.get("invoice_id") == str(p["invoice_id"])), None)
        if entry is None or entry.get("status") == "paid":
            return False
        if p.get("invoice_status") not in (None, "paid"):
            return False
        amount = int(entry["amount_paise"])
        total = int(c.amount_paise or 0) or amount
        inst_share = round(amount * int(c.institution_share_paise or 0) / total)
        faculty_share = amount - inst_share
        entry.update(
            status="paid",
            receipt_no=p.get("receipt_no"),
            paid_at=now_utc().isoformat(),
            institution_share_paise=inst_share,
            faculty_share_paise=faculty_share,
        )
        m["receipts"] = receipts
        await self.put_meta("consultancy", c.id, m)
        await self._emit(
            "research.consultancy_receipt",
            {
                "consultancy_id": str(c.id),
                "invoice_id": str(p["invoice_id"]),
                "amount_paise": amount,
                "institution_share_paise": inst_share,
                "faculty_share_paise": faculty_share,
                "staff_id": str(c.staff_id),
            },
            "consultancy",
            c.id,
        )
        if faculty_share > 0:
            await self._emit(
                "payroll.earning_requested",
                {
                    "staff_id": str(c.staff_id),
                    "amount_paise": faculty_share,
                    "component": "CONSULTANCY",
                    "source_type": "consultancy",
                    "source_id": str(c.id),
                    "description": f"Consultancy share · {c.client}"[:120],
                },
                "consultancy",
                c.id,
            )
        return True

    async def shares(self, cid: uuid.UUID) -> ConsultancyShares:
        c = await self.row(cid)
        out = (await self.outs([c]))[0]
        paid = [r for r in out.receipts if r.get("status") == "paid"]
        return ConsultancyShares(
            consultancy_id=c.id,
            amount_paise=int(c.amount_paise or 0),
            institution_pct=round(100 * int(c.institution_share_paise or 0) / int(c.amount_paise or 1), 2),
            institution_share_paise=int(c.institution_share_paise or 0),
            faculty_share_paise=int(c.amount_paise or 0) - int(c.institution_share_paise or 0),
            received_paise=sum(int(r["amount_paise"]) for r in paid),
            institution_received_paise=sum(int(r.get("institution_share_paise", 0)) for r in paid),
            faculty_paid_paise=sum(int(r.get("faculty_share_paise", 0)) for r in paid),
        )

    async def revenue(self, year: int | None = None) -> int:
        stmt = select(func.coalesce(func.sum(Consultancy.amount_paise), 0)).where(
            Consultancy.institution_id == self.inst
        )
        if year:
            stmt = stmt.where(extract("year", Consultancy.start_on) == year)
        return int((await self.db.execute(stmt)).scalar_one() or 0)
