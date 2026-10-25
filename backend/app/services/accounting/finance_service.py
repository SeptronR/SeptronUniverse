"""GST, voucher exports, statements, ledger, periods and the dashboard — Prompts/23 §23.6 ``gst_service`` /
``export_service`` / ``statements_service``.

* **GST** (``accounting.gst_reports``): output tax = fee invoice item GST of the period (Phase 12) + vendor-store sales;
  input tax = vendor bill tax (Phase 22) + expense GST captured on manual expenses; GSTR-3B style net; CSV export job.
* **Exports** (``accounting.tally_export``): receipts (income records), payments (paid expenses) for a period as Tally
  XML vouchers (ledger names from ``external_ref``), Zoho Books CSV or generic CSV; exported rows are remembered per
  record (``accounting_meta`` ``exported:<kind>``) so re-exports only carry new rows unless ``include_exported``.
* **Statements**: receipts & payments (cash basis), income & expenditure, balance summary, trial balance (income credits
  its account and debits bank; paid expenses debit their account and credit bank — the synthetic *Bank / cash* line
  balances the book). Segment filter by college.
* **Periods**: ``close`` locks records dated on / before a day (``PERIOD_CLOSED``; reversals post on later dates); year
  close freezes the year's budgets (+ carry-forward) via the budget service.
"""

import csv
import io
import uuid
from datetime import date, datetime, timedelta
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.models.accounting import AccountingExport, BankReconciliation, ExpenseRecord, IncomeRecord
from app.models.fees import FeeInvoice, FeeInvoiceItem, FeePayment, LedgerAccount
from app.schemas.accounting import (
    AcctDashboard,
    ExportOut,
    ExportRequest,
    GstReportOut,
    LedgerLine,
    StatementOut,
    TrialBalanceOut,
    TrialBalanceRow,
)
from app.services.accounting.common import AccountingBase, rule

STATEMENTS = ("receipts_payments", "income_expenditure", "balance_summary")


def month_bounds(period: str) -> tuple[date, date]:
    y, m = int(period[:4]), int(period[5:7])
    start = date(y, m, 1)
    return start, (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)


class FinanceService(AccountingBase):
    async def _accounts(self) -> dict[uuid.UUID, LedgerAccount]:
        return {
            a.id: a
            for a in (
                await self.db.execute(select(LedgerAccount).where(LedgerAccount.institution_id == self.inst))
            ).scalars()
        }

    def _inc(self, date_from: date | None, date_to: date | None, college_id: uuid.UUID | None = None) -> Any:
        q = select(IncomeRecord).where(IncomeRecord.institution_id == self.inst)
        if date_from:
            q = q.where(IncomeRecord.received_on >= date_from)
        if date_to:
            q = q.where(IncomeRecord.received_on <= date_to)
        if college_id:
            q = q.where(IncomeRecord.college_id == college_id)
        return q

    def _exp(
        self,
        date_from: date | None,
        date_to: date | None,
        college_id: uuid.UUID | None = None,
        statuses: tuple[str, ...] = ("paid",),
    ) -> Any:
        q = select(ExpenseRecord).where(ExpenseRecord.institution_id == self.inst, ExpenseRecord.status.in_(statuses))
        if date_from:
            q = q.where(ExpenseRecord.spent_on >= date_from)
        if date_to:
            q = q.where(ExpenseRecord.spent_on <= date_to)
        if college_id:
            q = q.where(ExpenseRecord.college_id == college_id)
        return q

    def _college(self, college_id: uuid.UUID | None) -> uuid.UUID | None:
        from app.services.accounting.common import _ids, all_access

        if all_access(self.principal):
            return college_id
        mine = _ids(self.principal, "college")
        if not mine:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "accounting:view_all required")
        if college_id and college_id not in mine:
            raise APIError(403, ErrorCode.PERMISSION_DENIED, "Not your college")
        return college_id or mine[0]

    # ---- ledger / trial balance ---------------------------------------------------------------------------------------------
    async def ledger(self, account_id: uuid.UUID, date_from: date | None, date_to: date | None) -> list[LedgerLine]:
        self.require("view_all")
        acct = (
            await self.db.execute(
                select(LedgerAccount).where(LedgerAccount.id == account_id, LedgerAccount.institution_id == self.inst)
            )
        ).scalar_one_or_none()
        if acct is None:
            raise APIError(404, ErrorCode.NOT_FOUND, "Ledger account not found")
        lines: list[LedgerLine] = []
        for r in (
            await self.db.execute(self._inc(date_from, date_to).where(IncomeRecord.ledger_account_id == account_id))
        ).scalars():
            lines.append(
                LedgerLine(
                    id=r.id,
                    kind="income",
                    on=r.received_on,
                    amount_paise=int(r.amount_paise),
                    debit_paise=0,
                    credit_paise=int(r.amount_paise),
                    source_type=r.source_type,
                    source_id=r.source_id,
                    description=r.description,
                    reference_no=r.reference_no,
                )
            )
        for r in (
            await self.db.execute(
                self._exp(date_from, date_to, statuses=("approved", "paid")).where(
                    ExpenseRecord.ledger_account_id == account_id
                )
            )
        ).scalars():
            src = (r.payee or "")[1:-1] if (r.payee or "").startswith("[") else "manual_expense"
            sid = None
            if src != "manual_expense":
                try:
                    sid = uuid.UUID(r.reference_no or "")
                except ValueError:
                    sid = None
            lines.append(
                LedgerLine(
                    id=r.id,
                    kind="expense",
                    on=r.spent_on,
                    amount_paise=int(r.amount_paise),
                    debit_paise=int(r.amount_paise),
                    credit_paise=0,
                    source_type=src,
                    source_id=sid or r.id,
                    description=r.description,
                    reference_no=r.reference_no,
                )
            )
        lines.sort(key=lambda x: (x.on, x.kind))
        bal = 0
        natural_debit = acct.account_type in ("asset", "expense")
        for ln in lines:
            bal += (ln.debit_paise - ln.credit_paise) if natural_debit else (ln.credit_paise - ln.debit_paise)
            ln.balance_paise = bal
        return lines

    async def trial_balance(
        self, date_from: date, date_to: date, college_id: uuid.UUID | None = None
    ) -> TrialBalanceOut:
        college_id = self._college(college_id)
        accts = await self._accounts()
        debit: dict[uuid.UUID, int] = {}
        credit: dict[uuid.UUID, int] = {}
        bank_d = bank_c = 0
        for r in (await self.db.execute(self._inc(date_from, date_to, college_id))).scalars():
            credit[r.ledger_account_id] = credit.get(r.ledger_account_id, 0) + int(r.amount_paise)
            bank_d += int(r.amount_paise)
        for r in (await self.db.execute(self._exp(date_from, date_to, college_id))).scalars():
            debit[r.ledger_account_id] = debit.get(r.ledger_account_id, 0) + int(r.amount_paise)
            bank_c += int(r.amount_paise)
        rows = []
        for aid in sorted(set(debit) | set(credit), key=lambda a: accts[a].code if a in accts else ""):
            a = accts.get(aid)
            d, c = debit.get(aid, 0), credit.get(aid, 0)
            net = d - c
            rows.append(
                TrialBalanceRow(
                    account_id=aid,
                    code=a.code if a else "?",
                    name=a.name if a else "?",
                    account_type=a.account_type if a else "?",
                    debit_paise=max(net, 0),
                    credit_paise=max(-net, 0),
                )
            )
        net_bank = bank_d - bank_c
        rows.append(
            TrialBalanceRow(
                account_id=None,
                code="BANK",
                name="Bank / cash (receipts − payments)",
                account_type="asset",
                debit_paise=max(net_bank, 0),
                credit_paise=max(-net_bank, 0),
            )
        )
        td, tc = sum(r.debit_paise for r in rows), sum(r.credit_paise for r in rows)
        return TrialBalanceOut(
            period_from=date_from,
            period_to=date_to,
            rows=rows,
            total_debit_paise=td,
            total_credit_paise=tc,
            balanced=td == tc,
        )

    # ---- statements -----------------------------------------------------------------------------------------------------------
    async def statement(
        self, kind: str, date_from: date, date_to: date, college_id: uuid.UUID | None = None
    ) -> StatementOut:
        if kind not in STATEMENTS:
            raise APIError(404, ErrorCode.NOT_FOUND, "Unknown statement")
        college_id = self._college(college_id)
        accts = await self._accounts()
        income: dict[str, int] = {}
        expense: dict[str, int] = {}
        for r in (await self.db.execute(self._inc(date_from, date_to, college_id))).scalars():
            a = accts.get(r.ledger_account_id)
            key = f"{a.code} {a.name}" if a else "?"
            if kind == "income_expenditure" and a is not None and a.account_type != "income":
                continue
            income[key] = income.get(key, 0) + int(r.amount_paise)
        statuses = ("approved", "paid") if kind == "income_expenditure" else ("paid",)
        for r in (await self.db.execute(self._exp(date_from, date_to, college_id, statuses))).scalars():
            a = accts.get(r.ledger_account_id)
            key = f"{a.code} {a.name}" if a else "?"
            if kind == "income_expenditure" and a is not None and a.account_type != "expense":
                continue
            expense[key] = expense.get(key, 0) + int(r.amount_paise)
        if kind == "balance_summary":
            ti, te = sum(income.values()), sum(expense.values())
            receivable = int(
                (
                    await self.db.execute(
                        select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0)).where(
                            FeeInvoice.institution_id == self.inst,
                            FeeInvoice.status.in_(("pending", "partial", "overdue")),
                        )
                    )
                ).scalar_one()
            )
            liab: dict[str, int] = {}
            for r in (await self.db.execute(self._inc(None, date_to, college_id))).scalars():
                a = accts.get(r.ledger_account_id)
                if a is not None and a.account_type == "liability":
                    liab[f"{a.code} {a.name}"] = liab.get(f"{a.code} {a.name}", 0) + int(r.amount_paise)
            sections = [
                {
                    "title": "Cash & bank (net receipts − payments)",
                    "rows": [{"label": "Bank / cash", "amount_paise": ti - te}],
                },
                {"title": "Receivables", "rows": [{"label": "Fees receivable", "amount_paise": receivable}]},
                {"title": "Liabilities", "rows": [{"label": k, "amount_paise": v} for k, v in sorted(liab.items())]},
            ]
            totals = {
                "cash_bank_paise": ti - te,
                "receivables_paise": receivable,
                "liabilities_paise": sum(liab.values()),
            }
        else:
            title_in, title_out = ("Receipts", "Payments") if kind == "receipts_payments" else ("Income", "Expenditure")
            sections = [
                {"title": title_in, "rows": [{"label": k, "amount_paise": v} for k, v in sorted(income.items())]},
                {"title": title_out, "rows": [{"label": k, "amount_paise": v} for k, v in sorted(expense.items())]},
            ]
            ti, te = sum(income.values()), sum(expense.values())
            totals = {"in_paise": ti, "out_paise": te, "surplus_paise": ti - te}
        return StatementOut(
            kind=kind, period_from=date_from, period_to=date_to, college_id=college_id, sections=sections, totals=totals
        )

    async def statement_lines(self, s: StatementOut) -> list[str]:
        inst = await self.institution()
        lines = [inst.name, f"{s.kind.replace('_', ' ').title()} — {s.period_from} to {s.period_to}", ""]
        for sec in s.sections:
            lines.append(sec["title"])
            lines += [f"  {r['label'][:60]:<60} Rs {r['amount_paise'] / 100:>16,.2f}" for r in sec["rows"]]
            lines.append("")
        lines += [
            f"{k.replace('_paise', '').replace('_', ' ').title():<62} Rs {v / 100:>16,.2f}" for k, v in s.totals.items()
        ]
        return lines

    async def statement_xlsx(self, s: StatementOut) -> bytes:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = s.kind[:30]
        ws.append([s.kind, str(s.period_from), str(s.period_to)])
        for sec in s.sections:
            ws.append([sec["title"]])
            for r in sec["rows"]:
                ws.append(["", r["label"], r["amount_paise"] / 100])
        for k, v in s.totals.items():
            ws.append([k, "", v / 100])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # ---- GST -------------------------------------------------------------------------------------------------------------------
    async def gst(self, period: str) -> GstReportOut:
        self.require("view_all")
        lo, hi = month_bounds(period)
        out_rows: dict[str, dict[str, int]] = {}
        for desc, taxable, tax in (
            await self.db.execute(
                select(FeeInvoiceItem.description, FeeInvoiceItem.amount_paise, FeeInvoiceItem.tax_paise)
                .join(FeeInvoice, FeeInvoice.id == FeeInvoiceItem.invoice_id)
                .where(
                    FeeInvoice.institution_id == self.inst,
                    FeeInvoiceItem.tax_paise > 0,
                    FeeInvoice.created_at >= datetime.combine(lo, datetime.min.time()),
                    FeeInvoice.created_at < datetime.combine(hi + timedelta(days=1), datetime.min.time()),
                )
            )
        ).all():
            key = (desc or "Taxable fee").split(" — ")[0][:60]
            row = out_rows.setdefault(key, {"taxable_paise": 0, "tax_paise": 0})
            row["taxable_paise"] += int(taxable)
            row["tax_paise"] += int(tax)
        in_rows: list[dict[str, Any]] = []
        try:
            from app.models.inventory import Supplier, VendorBill

            for num, sup, gstin, sub, tax in (
                await self.db.execute(
                    select(
                        VendorBill.bill_number,
                        Supplier.name,
                        Supplier.gstin,
                        VendorBill.subtotal_paise,
                        VendorBill.tax_paise,
                    )
                    .join(Supplier, Supplier.id == VendorBill.supplier_id)
                    .where(
                        VendorBill.institution_id == self.inst,
                        VendorBill.bill_date.between(lo, hi),
                        VendorBill.tax_paise > 0,
                        VendorBill.status != "rejected",
                    )
                )
            ).all():
                in_rows.append(
                    {"bill": num, "supplier": sup, "gstin": gstin, "taxable_paise": int(sub), "tax_paise": int(tax)}
                )
        except ImportError:  # pragma: no cover - Phase 22 absent
            pass
        for k, v in (await self.metas("expense_gst")).items():
            e = (
                await self.db.execute(select(ExpenseRecord).where(ExpenseRecord.id == uuid.UUID(k)))
            ).scalar_one_or_none()
            if e is not None and lo <= e.spent_on <= hi and e.status in ("approved", "paid"):
                in_rows.append(
                    {
                        "bill": e.reference_no,
                        "supplier": e.payee,
                        "gstin": None,
                        "taxable_paise": int(e.amount_paise),
                        "tax_paise": int(v.get("input_paise", 0)),
                    }
                )
        output: list[dict[str, Any]] = [{"head": k, **v} for k, v in sorted(out_rows.items())]
        ot, it = sum(int(r["tax_paise"]) for r in output), sum(int(r["tax_paise"]) for r in in_rows)
        return GstReportOut(
            period=period,
            output_tax=output,
            input_tax=in_rows,
            output_total_paise=ot,
            input_total_paise=it,
            net_paise=ot - it,
        )

    async def gst_csv(self, period: str) -> dict[str, Any]:
        from app.core.files import build_key, storage

        rep = await self.gst(period)
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["section", "head / bill", "supplier", "gstin", "taxable (Rs)", "tax (Rs)"])
        for r in rep.output_tax:
            w.writerow(["output", r["head"], "", "", r["taxable_paise"] / 100, r["tax_paise"] / 100])
        for r in rep.input_tax:
            w.writerow(
                ["input", r["bill"], r["supplier"], r["gstin"] or "", r["taxable_paise"] / 100, r["tax_paise"] / 100]
            )
        w.writerow(["net", "", "", "", "", rep.net_paise / 100])
        key = build_key(self.inst, "gst", f"gst-{period}-{uuid.uuid4().hex[:6]}.csv")
        await storage.put(key, buf.getvalue().encode(), "text/csv")
        return {"result_url": key, "net_paise": rep.net_paise}

    # ---- exports ---------------------------------------------------------------------------------------------------------------
    async def exports(self) -> list[ExportOut]:
        from app.core.files import storage

        self.require("export", "view_all")
        rows = (
            await self.db.execute(
                select(AccountingExport)
                .where(AccountingExport.institution_id == self.inst)
                .order_by(AccountingExport.created_at.desc())
            )
        ).scalars()
        out = []
        for r in rows:
            o = ExportOut.model_validate(r, from_attributes=True)
            o.file_url = storage.signed_url(r.file_url) if r.file_url else None
            out.append(o)
        return out

    async def request_export(self, body: ExportRequest) -> AccountingExport:
        from app.core.jobs import enqueue

        self.require("export")
        if body.period_to < body.period_from:
            raise APIError(422, ErrorCode.VALIDATION, "period_to is before period_from")
        e = AccountingExport(
            institution_id=self.inst,
            target=body.target,
            period_from=body.period_from,
            period_to=body.period_to,
            status="queued",
            requested_by=self.actor_id,
        )
        self.db.add(e)
        await self.db.flush()
        j = await enqueue(
            self.db, self.principal, "accounting.export", {"export_id": str(e.id), **body.model_dump(mode="json")}
        )
        e.job_id = j.id
        await self.db.flush()
        return e

    async def run_export(self, export_id: uuid.UUID, body: ExportRequest) -> dict[str, Any]:
        from app.core.files import build_key, storage

        e = (await self.db.execute(select(AccountingExport).where(AccountingExport.id == export_id))).scalar_one()
        e.status = "running"
        accts = await self._accounts()
        done_inc = set((await self.meta("exported", "income")).get("ids", []))
        done_exp = set((await self.meta("exported", "expense")).get("ids", []))
        vouchers: list[dict[str, Any]] = []
        if "receipt" in body.voucher_types:
            for r in (await self.db.execute(self._inc(body.period_from, body.period_to))).scalars():
                if str(r.id) in done_inc and not body.include_exported:
                    continue
                a = accts.get(r.ledger_account_id)
                vouchers.append(
                    {
                        "type": "Receipt",
                        "id": str(r.id),
                        "date": r.received_on,
                        "ledger": (a.external_ref or a.name) if a else "?",
                        "amount": int(r.amount_paise),
                        "narration": r.description or "",
                        "ref": r.reference_no or "",
                    }
                )
        if "payment" in body.voucher_types:
            for r in (await self.db.execute(self._exp(body.period_from, body.period_to))).scalars():
                if str(r.id) in done_exp and not body.include_exported:
                    continue
                a = accts.get(r.ledger_account_id)
                vouchers.append(
                    {
                        "type": "Payment",
                        "id": str(r.id),
                        "date": r.spent_on,
                        "ledger": (a.external_ref or a.name) if a else "?",
                        "amount": int(r.amount_paise),
                        "narration": r.description or "",
                        "ref": r.reference_no or "",
                    }
                )
        company = await self.setting("accounting", "tally_company_name") or (await self.institution()).name
        if body.target == "tally":
            parts = [
                f"<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>{escape(str(company))}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>"
            ]
            for v in vouchers:
                sign = "-" if v["type"] == "Receipt" else ""
                parts.append(
                    f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="{v["type"]}" ACTION="Create"><DATE>{v["date"]:%Y%m%d}</DATE>'
                    f"<VOUCHERTYPENAME>{v['type']}</VOUCHERTYPENAME><REFERENCE>{escape(v['ref'])}</REFERENCE><NARRATION>{escape(v['narration'])}</NARRATION>"
                    f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(v['ledger'])}</LEDGERNAME><AMOUNT>{sign}{v['amount'] / 100:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                    f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>Bank</LEDGERNAME><AMOUNT>{'' if sign else '-'}{v['amount'] / 100:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST></VOUCHER></TALLYMESSAGE>"
                )
            parts.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
            content, ext, ctype = "".join(parts).encode(), "xml", "application/xml"
        else:
            buf = io.StringIO()
            w = csv.writer(buf)
            if body.target == "zoho":
                w.writerow(
                    ["Journal Date", "Reference Number", "Journal Number Prefix", "Notes", "Account", "Debit", "Credit"]
                )
                for v in vouchers:
                    debit, credit = (0, v["amount"] / 100) if v["type"] == "Receipt" else (v["amount"] / 100, 0)
                    w.writerow(
                        [
                            v["date"].isoformat(),
                            v["ref"],
                            v["type"][:3].upper(),
                            v["narration"],
                            v["ledger"],
                            debit,
                            credit,
                        ]
                    )
            else:
                w.writerow(["type", "date", "ledger", "amount", "reference", "narration", "record_id"])
                for v in vouchers:
                    w.writerow(
                        [
                            v["type"],
                            v["date"].isoformat(),
                            v["ledger"],
                            v["amount"] / 100,
                            v["ref"],
                            v["narration"],
                            v["id"],
                        ]
                    )
            content, ext, ctype = buf.getvalue().encode(), "csv", "text/csv"
        key = build_key(
            self.inst,
            "accounting-exports",
            f"{body.target}-{body.period_from}-{body.period_to}-{uuid.uuid4().hex[:6]}.{ext}",
        )
        await storage.put(key, content, ctype)
        await self.put_meta(
            "exported", "income", {"ids": sorted(done_inc | {v["id"] for v in vouchers if v["type"] == "Receipt"})}
        )
        await self.put_meta(
            "exported", "expense", {"ids": sorted(done_exp | {v["id"] for v in vouchers if v["type"] == "Payment"})}
        )
        e.status, e.file_url = "ready", key
        await self.db.flush()
        await self._emit(
            "accounting.export_ready", {"export_id": str(e.id), "vouchers": len(vouchers)}, "accounting_export", e.id
        )
        if e.requested_by:
            await self._notify(
                "accounting.export_ready", [e.requested_by], {"target": e.target, "count": len(vouchers)}
            )
        return {"result_url": key, "vouchers": len(vouchers)}

    # ---- periods ------------------------------------------------------------------------------------------------------------------
    async def close_period(self, upto: date) -> dict[str, Any]:
        self.require("manage")
        current = await self.closed_upto()
        if current and upto < current:
            raise rule(
                "The books are already closed beyond this date", "ALREADY_CLOSED", closed_upto=current.isoformat()
            )
        await self.put_meta("period", "lock", {"upto": upto.isoformat(), "by": str(self.actor_id)})
        await self._audit("period_close", "accounting_period", None, None, {"upto": upto.isoformat()})
        await self._emit("accounting.period_closed", {"upto": upto.isoformat()}, "accounting_period", None)
        return {"closed_upto": upto.isoformat()}

    # ---- dashboard / metrics ------------------------------------------------------------------------------------------------------
    async def dashboard(self) -> AcctDashboard:
        from app.services.accounting.budget_service import BudgetService
        from app.services.accounting.posting_service import PostingService

        self.require("view_all")
        today = await self.today()
        first = today.replace(day=1)
        cash = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(IncomeRecord.amount_paise), 0)).where(
                        IncomeRecord.institution_id == self.inst, IncomeRecord.payment_mode == "cash"
                    )
                )
            ).scalar_one()
        )
        inc_all = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(IncomeRecord.amount_paise), 0)).where(
                        IncomeRecord.institution_id == self.inst
                    )
                )
            ).scalar_one()
        )
        exp_all = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(ExpenseRecord.amount_paise), 0)).where(
                        ExpenseRecord.institution_id == self.inst, ExpenseRecord.status == "paid"
                    )
                )
            ).scalar_one()
        )
        receivable = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0)).where(
                        FeeInvoice.institution_id == self.inst, FeeInvoice.status.in_(("pending", "partial", "overdue"))
                    )
                )
            ).scalar_one()
        )
        inc_m = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(IncomeRecord.amount_paise), 0)).where(
                        IncomeRecord.institution_id == self.inst, IncomeRecord.received_on >= first
                    )
                )
            ).scalar_one()
        )
        exp_m = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(ExpenseRecord.amount_paise), 0)).where(
                        ExpenseRecord.institution_id == self.inst,
                        ExpenseRecord.status == "paid",
                        ExpenseRecord.spent_on >= first,
                    )
                )
            ).scalar_one()
        )
        pending = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(ExpenseRecord)
                    .where(ExpenseRecord.institution_id == self.inst, ExpenseRecord.status == "submitted")
                )
            ).scalar_one()
        )
        recon = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(BankReconciliation)
                    .where(BankReconciliation.institution_id == self.inst, BankReconciliation.status == "open")
                )
            ).scalar_one()
        )
        alerts = []
        try:
            for h in await BudgetService(self.db, self.principal, self.request, self.inst).heads():
                if h.pct >= 80:  # noqa: PLR2004
                    alerts.append({"head": h.name, "department": h.department_code, "pct": h.pct})
        except APIError:
            pass
        gaps = len(await PostingService(self.db, self.principal, self.request, self.inst).gaps())
        return AcctDashboard(
            cash_paise=cash,
            bank_paise=inc_all - exp_all - cash,
            receivables_paise=receivable,
            income_month_paise=inc_m,
            expense_month_paise=exp_m,
            pending_expenses=pending,
            budget_alerts=sorted(alerts, key=lambda a: -float(a["pct"] or 0))[:20],
            open_reconciliations=recon,
            posting_gaps=gaps,
        )

    async def metrics(self, date_from: date, date_to: date) -> dict[str, int]:
        accts = await self._accounts()
        capex = opex = library = research = 0
        for r in (await self.db.execute(self._exp(date_from, date_to, statuses=("approved", "paid")))).scalars():
            a = accts.get(r.ledger_account_id)
            if a is None:
                continue
            if a.account_type == "asset" or a.code.startswith("14"):
                capex += int(r.amount_paise)
            else:
                opex += int(r.amount_paise)
            if a.code == "5400":
                library += int(r.amount_paise)
            if (r.payee or "").startswith("[grant:"):
                research += int(r.amount_paise)
        return {"capex_paise": capex, "opex_paise": opex, "library_spend": library, "research_spend": research}

    async def fee_payment_ids(self, date_from: date, date_to: date) -> list[uuid.UUID]:
        return list(
            (
                await self.db.execute(
                    select(FeePayment.id).where(
                        FeePayment.institution_id == self.inst, FeePayment.payment_date.between(date_from, date_to)
                    )
                )
            ).scalars()
        )
