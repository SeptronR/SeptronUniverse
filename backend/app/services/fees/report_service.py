"""Fee reports — Prompts/12 §12.6 ``fee_report_service``: collection by mode / head / college, dues by programme /
batch / category, defaulters, scholarship summary, refunds, the dashboard tiles and ``accounting_export`` (Tally XML
vouchers or CSV) when ``fees.accounting_export`` is on. Exports run as jobs (``fees.reports_export`` /
``fees.accounting_export``)."""

import csv
import io
from datetime import date
from typing import Any
from xml.sax.saxutils import escape

from sqlalchemy import func, select

from app.core.errors import APIError, ErrorCode
from app.enums.fees import OPEN_INVOICE, SETTLED_PAYMENT
from app.models.academic import Batch, Program
from app.models.fees import FeeHead, FeeInvoice, FeeInvoiceItem, FeePayment, FeeRefund, OfflinePaymentReconciliation
from app.models.platform import WorkflowInstance
from app.models.students import Student, StudentProgramEnrollment
from app.schemas.fees import FeeDashboard, FeeReport, FeeReportRow
from app.services.fees.common import FeesBase, student_name

REPORTS = ("collection", "dues", "defaulters", "scholarships", "refunds")


class FeeReportService(FeesBase):
    async def dashboard(self) -> FeeDashboard:
        today = await self.today()
        inst = FeeInvoice.institution_id == self.inst
        by_mode = {
            m: int(s)
            for m, s in (
                await self.db.execute(
                    select(FeePayment.payment_mode, func.sum(FeePayment.amount_paise))
                    .where(
                        FeePayment.institution_id == self.inst,
                        FeePayment.payment_date == today,
                        FeePayment.status.in_(tuple(SETTLED_PAYMENT)),
                    )
                    .group_by(FeePayment.payment_mode)
                )
            ).all()
        }
        dues = (
            await self.db.execute(
                select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0)).where(
                    inst, FeeInvoice.status.in_(tuple(OPEN_INVOICE))
                )
            )
        ).scalar_one()
        od = (
            await self.db.execute(
                select(func.coalesce(func.sum(FeeInvoice.balance_paise), 0), func.count()).where(
                    inst, FeeInvoice.status.in_(tuple(OPEN_INVOICE)), FeeInvoice.due_date < today
                )
            )
        ).one()
        rec = (
            await self.db.execute(
                select(func.count())
                .select_from(OfflinePaymentReconciliation)
                .where(
                    OfflinePaymentReconciliation.institution_id == self.inst,
                    OfflinePaymentReconciliation.status == "unmatched",
                )
            )
        ).scalar_one()
        ref = (
            await self.db.execute(
                select(func.count())
                .select_from(FeeRefund)
                .where(FeeRefund.institution_id == self.inst, FeeRefund.status.in_(("requested", "approved")))
            )
        ).scalar_one()
        canc = (
            await self.db.execute(
                select(func.count())
                .select_from(FeePayment)
                .join(WorkflowInstance, WorkflowInstance.id == FeePayment.cancel_workflow_instance_id)
                .where(FeePayment.institution_id == self.inst, WorkflowInstance.status.in_(("pending", "escalated")))
            )
        ).scalar_one()
        online = (
            await self.db.execute(
                select(func.count())
                .select_from(FeePayment)
                .where(FeePayment.institution_id == self.inst, FeePayment.status == "initiated")
            )
        ).scalar_one()
        return FeeDashboard(
            today_by_mode=by_mode,
            today_total=sum(by_mode.values()),
            dues_total=int(dues),
            overdue_total=int(od[0]),
            overdue_count=int(od[1]),
            reconcile_pending=int(rec),
            refunds_pending=int(ref),
            cancel_pending=int(canc),
            online_initiated=int(online),
        )

    async def run(self, report: str, params: dict[str, Any]) -> FeeReport:
        if report not in REPORTS:
            raise APIError(404, ErrorCode.NOT_FOUND, f"Unknown report {report}")
        rows: list[FeeReportRow] = await getattr(self, f"_{report}")(params)
        return FeeReport(report=report, rows=rows, total_paise=sum(r.amount_paise for r in rows))

    async def _collection(self, p: dict[str, Any]) -> list[FeeReportRow]:
        today = await self.today()
        d_from = p.get("date_from") or today.replace(day=1)
        d_to = p.get("date_to") or today
        group = p.get("group_by") or "mode"
        base = [
            FeePayment.institution_id == self.inst,
            FeePayment.status.in_(tuple(SETTLED_PAYMENT)),
            FeePayment.payment_date >= d_from,
            FeePayment.payment_date <= d_to,
        ]
        if group == "head":
            # payments are per invoice — attribute by the invoice's item mix (first head)
            q: Any = (
                select(
                    FeeHead.code,
                    FeeHead.name,
                    func.count(func.distinct(FeePayment.id)),
                    func.sum(FeePayment.amount_paise),
                )
                .select_from(FeePayment)
                .join(FeeInvoiceItem, FeeInvoiceItem.invoice_id == FeePayment.invoice_id)
                .join(FeeHead, FeeHead.id == FeeInvoiceItem.fee_head_id)
                .where(*base)
                .group_by(FeeHead.code, FeeHead.name)
            )
            return [
                FeeReportRow(key=c, label=n, count=int(k), amount_paise=int(s or 0))
                for c, n, k, s in (await self.db.execute(q)).all()
            ]
        if group == "college":
            q = (
                select(FeeInvoice.college_id, func.count(), func.sum(FeePayment.amount_paise))
                .join(FeeInvoice, FeeInvoice.id == FeePayment.invoice_id)
                .where(*base)
                .group_by(FeeInvoice.college_id)
            )
            return [
                FeeReportRow(key=str(c), count=int(k), amount_paise=int(s or 0))
                for c, k, s in (await self.db.execute(q)).all()
            ]
        if group == "day":
            q = (
                select(FeePayment.payment_date, func.count(), func.sum(FeePayment.amount_paise))
                .where(*base)
                .group_by(FeePayment.payment_date)
                .order_by(FeePayment.payment_date)
            )
            return [
                FeeReportRow(key=d.isoformat(), count=int(k), amount_paise=int(s or 0))
                for d, k, s in (await self.db.execute(q)).all()
            ]
        q = (
            select(FeePayment.payment_mode, func.count(), func.sum(FeePayment.amount_paise))
            .where(*base)
            .group_by(FeePayment.payment_mode)
        )
        return [
            FeeReportRow(key=m, count=int(k), amount_paise=int(s or 0)) for m, k, s in (await self.db.execute(q)).all()
        ]

    async def _dues(self, p: dict[str, Any]) -> list[FeeReportRow]:
        group = p.get("group_by") or "program"
        col = {"program": Program.code, "batch": Batch.name, "category": Student.category}.get(group, Program.code)
        q = (
            select(col, func.count(), func.sum(FeeInvoice.balance_paise))
            .select_from(FeeInvoice)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.id == FeeInvoice.student_program_enrollment_id)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .join(Program, Program.id == StudentProgramEnrollment.program_id)
            .join(Batch, Batch.id == StudentProgramEnrollment.batch_id)
            .where(FeeInvoice.institution_id == self.inst, FeeInvoice.status.in_(tuple(OPEN_INVOICE)))
            .group_by(col)
        )
        return [
            FeeReportRow(key=str(k or "—"), count=int(c), amount_paise=int(s or 0))
            for k, c, s in (await self.db.execute(q)).all()
        ]

    async def _defaulters(self, p: dict[str, Any]) -> list[FeeReportRow]:
        today = await self.today()
        q = (
            select(
                Student, func.count(FeeInvoice.id), func.sum(FeeInvoice.balance_paise), func.min(FeeInvoice.due_date)
            )
            .select_from(FeeInvoice)
            .join(StudentProgramEnrollment, StudentProgramEnrollment.id == FeeInvoice.student_program_enrollment_id)
            .join(Student, Student.id == StudentProgramEnrollment.student_id)
            .where(
                FeeInvoice.institution_id == self.inst,
                FeeInvoice.status.in_(tuple(OPEN_INVOICE)),
                FeeInvoice.due_date < today,
            )
            .group_by(Student.id)
            .order_by(func.sum(FeeInvoice.balance_paise).desc())
            .limit(1000)
        )
        if p.get("batch_id"):
            q = q.where(StudentProgramEnrollment.batch_id == p["batch_id"])
        if p.get("batch_year"):
            q = q.where(
                StudentProgramEnrollment.batch_id.in_(
                    select(Batch.id).where(Batch.admission_year == int(p["batch_year"]))
                )
            )
        return [
            FeeReportRow(
                key=s.registration_number,
                label=student_name(s),
                count=int(c),
                amount_paise=int(b or 0),
                extra={"oldest_due": d.isoformat() if d else None, "days_overdue": (today - d).days if d else 0},
            )
            for s, c, b, d in (await self.db.execute(q)).all()
        ]

    async def _scholarships(self, p: dict[str, Any]) -> list[FeeReportRow]:
        from app.services.fees.scholarship_service import ScholarshipService

        rows = await ScholarshipService(self.db, self.principal, self.request, self.inst).summary()
        return [
            FeeReportRow(
                key=f"{r['scholarship']} · {r['status']}",
                label=r["provider"],
                count=r["count"],
                amount_paise=r["amount_paise"],
            )
            for r in rows
        ]

    async def _refunds(self, p: dict[str, Any]) -> list[FeeReportRow]:
        q = (
            select(FeeRefund.status, func.count(), func.sum(FeeRefund.amount_paise))
            .where(FeeRefund.institution_id == self.inst)
            .group_by(FeeRefund.status)
        )
        return [
            FeeReportRow(key=s, count=int(c), amount_paise=int(a or 0)) for s, c, a in (await self.db.execute(q)).all()
        ]

    @staticmethod
    def to_csv(rep: FeeReport) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["key", "label", "count", "amount"])
        for r in rep.rows:
            w.writerow([r.key, r.label or "", r.count, f"{r.amount_paise / 100:.2f}"])
        return buf.getvalue().encode("utf-8-sig")

    async def accounting_export(self, d_from: date, d_to: date, fmt: str) -> tuple[bytes, str, str]:
        rows = (
            await self.db.execute(
                select(FeePayment, FeeInvoice)
                .join(FeeInvoice, FeeInvoice.id == FeePayment.invoice_id)
                .where(
                    FeePayment.institution_id == self.inst,
                    FeePayment.status.in_(tuple(SETTLED_PAYMENT)),
                    FeePayment.payment_date >= d_from,
                    FeePayment.payment_date <= d_to,
                )
                .order_by(FeePayment.payment_date)
            )
        ).all()
        if fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["date", "voucher", "debit_ledger", "credit_ledger", "amount", "narration"])
            for p, inv in rows:
                w.writerow(
                    [
                        p.payment_date.isoformat(),
                        p.receipt_number,
                        "Cash" if p.payment_mode == "cash" else "Bank",
                        "Fees receivable",
                        f"{p.amount_paise / 100:.2f}",
                        f"{inv.invoice_number} {p.payment_mode}",
                    ]
                )
            return buf.getvalue().encode("utf-8-sig"), "text/csv", "csv"
        inst = await self.institution()
        parts = [
            "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>",
            f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(inst.name)}</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>",
        ]
        for p, inv in rows:
            amt = f"{p.amount_paise / 100:.2f}"
            debit = "Cash" if p.payment_mode == "cash" else "Bank"
            parts.append(
                f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="Receipt" ACTION="Create"><DATE>{p.payment_date.strftime("%Y%m%d")}</DATE>'
                f"<VOUCHERNUMBER>{escape(p.receipt_number)}</VOUCHERNUMBER><NARRATION>{escape(inv.invoice_number)} {escape(p.payment_mode)}</NARRATION>"
                f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{debit}</LEDGERNAME><ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-{amt}</AMOUNT></ALLLEDGERENTRIES.LIST>"
                f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>Fees receivable</LEDGERNAME><ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>{amt}</AMOUNT></ALLLEDGERENTRIES.LIST></VOUCHER></TALLYMESSAGE>"
            )
        parts.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
        return "".join(parts).encode("utf-8"), "application/xml", "xml"
