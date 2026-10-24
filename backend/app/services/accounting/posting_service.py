"""Automatic postings — Prompts/23 §23.6 ``posting_service`` (the single write path for automatic entries).

Every posting is an ``income_records`` (credit) or ``expense_records`` (debit, status ``paid``) row carrying
``source_type`` / ``source_id``; a source already posted is skipped, so event replays never duplicate:

* ``fees.payment_received`` → one income row per invoice line, the payment split pro rata over the lines: the fee head's
  account (``fee_heads.ledger_account_id``, else 4000), caution-deposit heads to the liability ``caution_deposit``, the
  line GST to ``gst_payable`` (``source_type='fee_payment'``);
* ``fees.receipt_cancelled`` / ``fees.payment_bounced`` → negated copies (``fee_payment_reversal``);
* ``fees.refund_processed`` → refund expense, or a negative caution-deposit liability row for deposit refunds;
* ``inventory.bill_paid`` → expense of the subtotal on the item-category account (``inventory_categories`` mapping),
  input GST against ``gst_payable`` and TDS credited to ``tds_payable``;
* ``payroll.paid`` → salaries (gross) + employer contribution expenses, PF / ESI and TDS deductions credited to their
  payables;
* ``asset.depreciated`` → depreciation expense; ``inventory.asset_disposed`` → asset-sale income;
  ``alumni.donation_received`` → donations income.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.models.accounting import ExpenseRecord, IncomeRecord
from app.models.fees import FeeHead, FeeInvoice, FeeInvoiceItem, FeePayment, FeeRefund, LedgerAccount
from app.services.accounting.common import AccountingBase

D = Decimal
SOURCES = (
    "fee_payment",
    "fee_payment_reversal",
    "fee_refund",
    "vendor_bill",
    "payroll",
    "asset_depreciation",
    "asset_disposal",
    "donation",
)


class PostingService(AccountingBase):
    async def posted(self, source_type: str, source_id: uuid.UUID) -> bool:
        inc = (
            await self.db.execute(
                select(IncomeRecord.id)
                .where(
                    IncomeRecord.institution_id == self.inst,
                    IncomeRecord.source_type == source_type,
                    IncomeRecord.source_id == source_id,
                )
                .limit(1)
            )
        ).first()
        if inc:
            return True
        exp2 = (
            await self.db.execute(
                select(ExpenseRecord.id)
                .where(
                    ExpenseRecord.institution_id == self.inst,
                    ExpenseRecord.payee == f"[{source_type}]",
                    ExpenseRecord.reference_no == str(source_id),
                )
                .limit(1)
            )
        ).first()
        return exp2 is not None

    async def _income(
        self,
        acct: LedgerAccount,
        amount: int,
        on: date,
        source_type: str,
        source_id: uuid.UUID,
        desc: str,
        *,
        college_id: uuid.UUID | None = None,
        ref: str | None = None,
        mode: str | None = None,
    ) -> IncomeRecord:
        r = IncomeRecord(
            institution_id=self.inst,
            college_id=college_id,
            ledger_account_id=acct.id,
            amount_paise=amount,
            received_on=on,
            source_type=source_type,
            source_id=source_id,
            description=desc[:255],
            reference_no=(ref or "")[:80] or None,
            payment_mode=mode,
            recorded_by=None,
        )
        self.db.add(r)
        return r

    async def _expense(
        self,
        acct: LedgerAccount,
        amount: int,
        on: date,
        source_type: str,
        source_id: uuid.UUID,
        desc: str,
        *,
        college_id: uuid.UUID | None = None,
        department_id: uuid.UUID | None = None,
        vendor_bill_id: uuid.UUID | None = None,
    ) -> ExpenseRecord:
        """Automatic expenses mark their source in ``payee='[<source_type>]'`` + ``reference_no=<source id>`` (the
        section 22 expense row has no source columns)."""
        r = ExpenseRecord(
            institution_id=self.inst,
            college_id=college_id,
            department_id=department_id,
            ledger_account_id=acct.id,
            amount_paise=amount,
            spent_on=on,
            payee=f"[{source_type}]",
            description=desc[:255],
            reference_no=str(source_id),
            vendor_bill_id=vendor_bill_id,
            status="paid",
        )
        self.db.add(r)
        return r

    async def _done(self, source_type: str, source_id: uuid.UUID, n: int) -> int:
        await self.db.flush()
        if n:
            await self._emit(
                "accounting.posted",
                {"source_type": source_type, "source_id": str(source_id), "rows": n},
                "posting",
                source_id,
            )
        return n

    # ---- fees ---------------------------------------------------------------------------------------------------------------
    async def fee_payment(self, payment_id: uuid.UUID) -> int:
        if await self.posted("fee_payment", payment_id):
            return 0
        p = (await self.db.execute(select(FeePayment).where(FeePayment.id == payment_id))).scalar_one_or_none()
        if p is None or p.status not in ("success", "cleared", "realised"):
            return 0
        inv = (await self.db.execute(select(FeeInvoice).where(FeeInvoice.id == p.invoice_id))).scalar_one()
        items = (
            await self.db.execute(
                select(FeeInvoiceItem, FeeHead)
                .outerjoin(FeeHead, FeeHead.id == FeeInvoiceItem.fee_head_id)
                .where(FeeInvoiceItem.invoice_id == inv.id)
            )
        ).all()
        gross = sum(int(i.amount_paise) + int(i.tax_paise or 0) for i, _ in items) or p.amount_paise
        share = D(p.amount_paise) / D(gross) if gross else D(1)
        default = await self.account("4000")
        n = 0
        lines: list[tuple[LedgerAccount, int, str]] = []
        for it, head in items:
            if head is not None and head.head_type == "caution_deposit":
                acct = await self.account("caution_deposit")
            elif head is not None and head.ledger_account_id:
                acct = (
                    await self.db.execute(select(LedgerAccount).where(LedgerAccount.id == head.ledger_account_id))
                ).scalar_one()
            else:
                acct = default
            lines.append((acct, int(D(it.amount_paise) * share), it.description))
            if it.tax_paise:
                lines.append(
                    (await self.account("gst_payable"), int(D(it.tax_paise) * share), f"GST on {it.description}")
                )
        if not lines:
            lines = [(default, p.amount_paise, inv.description or "Fee collection")]
        posted = sum(amt for _, amt, _ in lines)
        if lines and posted != p.amount_paise:  # rounding residue onto the first line
            acct, amt, desc = lines[0]
            lines[0] = (acct, amt + (p.amount_paise - posted), desc)
        for acct, amt, desc in lines:
            if amt:
                await self._income(
                    acct,
                    amt,
                    p.payment_date,
                    "fee_payment",
                    p.id,
                    f"{p.receipt_number} · {desc}",
                    college_id=inv.college_id,
                    ref=p.receipt_number,
                    mode=p.payment_mode,
                )
                n += 1
        return await self._done("fee_payment", p.id, n)

    async def fee_reversal(self, payment_id: uuid.UUID) -> int:
        if await self.posted("fee_payment_reversal", payment_id):
            return 0
        rows = (
            (
                await self.db.execute(
                    select(IncomeRecord).where(
                        IncomeRecord.source_type == "fee_payment", IncomeRecord.source_id == payment_id
                    )
                )
            )
            .scalars()
            .all()
        )
        today = await self.today()
        for r in rows:
            acct = (
                await self.db.execute(select(LedgerAccount).where(LedgerAccount.id == r.ledger_account_id))
            ).scalar_one()
            await self._income(
                acct,
                -int(r.amount_paise),
                today,
                "fee_payment_reversal",
                payment_id,
                f"Reversal · {r.description or ''}",
                college_id=r.college_id,
                ref=r.reference_no,
                mode=r.payment_mode,
            )
        return await self._done("fee_payment_reversal", payment_id, len(rows))

    async def fee_refund(self, refund_id: uuid.UUID) -> int:
        if await self.posted("fee_refund", refund_id):
            return 0
        r = (await self.db.execute(select(FeeRefund).where(FeeRefund.id == refund_id))).scalar_one_or_none()
        if r is None:
            return 0
        on = r.processed_at.date() if r.processed_at else await self.today()
        deposit = False
        if r.invoice_id:
            deposit = (
                await self.db.execute(
                    select(func.count())
                    .select_from(FeeInvoiceItem)
                    .join(FeeHead, FeeHead.id == FeeInvoiceItem.fee_head_id)
                    .where(FeeInvoiceItem.invoice_id == r.invoice_id, FeeHead.head_type == "caution_deposit")
                )
            ).scalar_one() > 0
        if deposit:
            await self._income(
                await self.account("caution_deposit"),
                -int(r.amount_paise),
                on,
                "fee_refund",
                r.id,
                f"Caution deposit refund · {r.reason[:120]}",
                ref=r.reference_no,
            )
        else:
            await self._expense(
                await self.account("refunds"),
                int(r.amount_paise),
                on,
                "fee_refund",
                r.id,
                f"Fee refund · {r.reason[:120]}",
            )
        return await self._done("fee_refund", r.id, 1)

    # ---- inventory --------------------------------------------------------------------------------------------------------
    async def vendor_bill(self, bill_id: uuid.UUID) -> int:
        from app.models.inventory import InventoryCategory, Item, PurchaseOrderItem, VendorBill

        if await self.posted("vendor_bill", bill_id):
            return 0
        b = (await self.db.execute(select(VendorBill).where(VendorBill.id == bill_id))).scalar_one_or_none()
        if b is None:
            return 0
        on = b.paid_at.date() if b.paid_at else await self.today()
        maps = await self.mappings()
        code = maps.get("inventory_default", "5300")
        if b.po_id:
            cat = (
                await self.db.execute(
                    select(InventoryCategory.name)
                    .join(Item, Item.category_id == InventoryCategory.id)
                    .join(PurchaseOrderItem, PurchaseOrderItem.item_id == Item.id)
                    .where(PurchaseOrderItem.po_id == b.po_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            code = (maps.get("inventory_categories") or {}).get(cat or "", code)
        n = 0
        await self._expense(
            await self.account(str(code)),
            int(b.subtotal_paise),
            on,
            "vendor_bill",
            b.id,
            f"Bill {b.bill_number}",
            vendor_bill_id=b.id,
        )
        n += 1
        if b.tax_paise:
            await self._expense(
                await self.account("gst_payable"),
                int(b.tax_paise),
                on,
                "vendor_bill",
                b.id,
                f"Input GST · bill {b.bill_number}",
                vendor_bill_id=b.id,
            )
            n += 1
        if b.tds_paise:
            await self._income(
                await self.account("tds_payable"),
                int(b.tds_paise),
                on,
                "vendor_bill",
                b.id,
                f"TDS deducted · bill {b.bill_number}",
                ref=b.payment_ref,
            )
            n += 1
        return await self._done("vendor_bill", b.id, n)

    async def depreciation(self, run_key: str, amount: int, on: date) -> int:
        sid = uuid.uuid5(uuid.NAMESPACE_URL, f"depreciation:{self.inst}:{run_key}")
        if amount <= 0 or await self.posted("asset_depreciation", sid):
            return 0
        await self._expense(
            await self.account("depreciation"), amount, on, "asset_depreciation", sid, f"Depreciation {run_key}"
        )
        return await self._done("asset_depreciation", sid, 1)

    async def asset_disposal(self, asset_id: uuid.UUID, sale_paise: int) -> int:
        if sale_paise <= 0 or await self.posted("asset_disposal", asset_id):
            return 0
        await self._income(
            await self.account("asset_sale"),
            sale_paise,
            await self.today(),
            "asset_disposal",
            asset_id,
            "Asset sale proceeds",
        )
        return await self._done("asset_disposal", asset_id, 1)

    # ---- payroll / donations ----------------------------------------------------------------------------------------------
    async def payroll(self, payroll_id: uuid.UUID) -> int:
        from app.models.hr import Staff, StaffPayroll, StaffPayrollItem

        if await self.posted("payroll", payroll_id):
            return 0
        run = (await self.db.execute(select(StaffPayroll).where(StaffPayroll.id == payroll_id))).scalar_one_or_none()
        if run is None:
            return 0
        staff = (await self.db.execute(select(Staff).where(Staff.id == run.staff_id))).scalar_one_or_none()
        on = run.paid_at.date() if run.paid_at else await self.today()
        label = f"Salary {run.month:02d}/{run.year} · {staff.full_name if staff else ''}"
        n = 0
        await self._expense(
            await self.account("salaries"),
            int(run.gross_paise),
            on,
            "payroll",
            run.id,
            label,
            college_id=staff.college_id if staff else None,
            department_id=staff.department_id if staff else None,
        )
        n += 1
        if run.employer_contrib_paise:
            await self._expense(
                await self.account("employer_contrib"),
                int(run.employer_contrib_paise),
                on,
                "payroll",
                run.id,
                f"Employer contribution · {label}",
            )
            await self._income(
                await self.account("pf_payable"),
                int(run.employer_contrib_paise),
                on,
                "payroll",
                run.id,
                f"Employer PF / ESI payable · {label}",
            )
            n += 2
        for it in (
            await self.db.execute(
                select(StaffPayrollItem).where(
                    StaffPayrollItem.payroll_id == run.id, StaffPayrollItem.component_type == "deduction"
                )
            )
        ).scalars():
            key = (
                "pf_payable"
                if any(k in it.label.upper() for k in ("PF", "ESI", "EPF"))
                else "tds_payable"
                if "TDS" in it.label.upper() or "TAX" in it.label.upper()
                else None
            )
            if key and it.amount_paise:
                await self._income(
                    await self.account(key), int(it.amount_paise), on, "payroll", run.id, f"{it.label} · {label}"
                )
                n += 1
        return await self._done("payroll", run.id, n)

    async def donation(self, donation_id: uuid.UUID, amount: int, on: date, restricted: bool = False) -> int:
        if amount <= 0 or await self.posted("donation", donation_id):
            return 0
        acct = await self.account("3200" if restricted else "donations")
        await self._income(
            acct, amount, on, "donation", donation_id, "Donation" + (" (restricted fund)" if restricted else "")
        )
        return await self._done("donation", donation_id, 1)

    # ---- replay / gaps -------------------------------------------------------------------------------------------------------
    async def replay(self, date_from: date, date_to: date) -> dict[str, int]:
        from app.models.hr import StaffPayroll
        from app.models.inventory import VendorBill

        out = {"fee_payment": 0, "fee_payment_reversal": 0, "fee_refund": 0, "vendor_bill": 0, "payroll": 0}
        for pid, status in (
            await self.db.execute(
                select(FeePayment.id, FeePayment.status).where(
                    FeePayment.institution_id == self.inst, FeePayment.payment_date.between(date_from, date_to)
                )
            )
        ).all():
            out["fee_payment"] += await self.fee_payment(pid)
            if status in ("cancelled", "bounced"):
                out["fee_payment_reversal"] += await self.fee_reversal(pid)
        for rid in (
            await self.db.execute(
                select(FeeRefund.id).where(FeeRefund.institution_id == self.inst, FeeRefund.status == "processed")
            )
        ).scalars():
            out["fee_refund"] += await self.fee_refund(rid)
        for bid in (
            await self.db.execute(
                select(VendorBill.id).where(VendorBill.institution_id == self.inst, VendorBill.status == "paid")
            )
        ).scalars():
            out["vendor_bill"] += await self.vendor_bill(bid)
        for rid in (
            await self.db.execute(
                select(StaffPayroll.id).where(StaffPayroll.institution_id == self.inst, StaffPayroll.status == "paid")
            )
        ).scalars():
            out["payroll"] += await self.payroll(rid)
        await self._audit(
            "posting_replay", "posting", None, None, out | {"from": date_from.isoformat(), "to": date_to.isoformat()}
        )
        return out

    async def gaps(self) -> list[dict[str, Any]]:
        """Sources that should have postings but have none (payments ok, bills paid, payroll paid, refunds processed)."""
        from app.models.hr import StaffPayroll
        from app.models.inventory import VendorBill

        inc_src = select(IncomeRecord.source_id).where(
            IncomeRecord.institution_id == self.inst, IncomeRecord.source_type == "fee_payment"
        )
        out: list[dict[str, Any]] = []
        for pid, rec in (
            await self.db.execute(
                select(FeePayment.id, FeePayment.receipt_number)
                .where(
                    FeePayment.institution_id == self.inst,
                    FeePayment.status == "success",
                    FeePayment.id.notin_(inc_src),
                )
                .limit(500)
            )
        ).all():
            out.append({"source_type": "fee_payment", "source_id": str(pid), "ref": rec})
        exp_src = select(ExpenseRecord.reference_no).where(
            ExpenseRecord.institution_id == self.inst,
            or_(
                ExpenseRecord.payee == "[vendor_bill]",
                ExpenseRecord.payee == "[payroll]",
                ExpenseRecord.payee == "[fee_refund]",
            ),
        )
        mine = set((await self.db.execute(exp_src)).scalars())
        for bid, num in (
            await self.db.execute(
                select(VendorBill.id, VendorBill.bill_number).where(
                    VendorBill.institution_id == self.inst, VendorBill.status == "paid"
                )
            )
        ).all():
            if str(bid) not in mine:
                out.append({"source_type": "vendor_bill", "source_id": str(bid), "ref": num})
        for rid, m, y in (
            await self.db.execute(
                select(StaffPayroll.id, StaffPayroll.month, StaffPayroll.year).where(
                    StaffPayroll.institution_id == self.inst, StaffPayroll.status == "paid"
                )
            )
        ).all():
            if str(rid) not in mine:
                out.append({"source_type": "payroll", "source_id": str(rid), "ref": f"{m:02d}/{y}"})
        return out
