"""Accounting tasks — Prompts/23 §23.7.

Consumers (``accounting.core`` on): fee payments / cancellations / bounces / refunds, vendor bills paid, payroll paid,
asset depreciation / disposal and donations → ``posting_service`` (idempotent per source); ``budget.commit_requested`` /
``released`` → commitments (events marked ``applied`` were already applied by their producer); Phase 30
``research.project_sanctioned`` → grant ledger. Jobs: ``accounting.posting_replay``, ``accounting.export``,
``accounting.gst_export``, ``accounting.year_close``. Beat: ``accounting.budget_threshold_scan`` (daily),
``accounting.reconciliation_reminder`` (monthly), ``accounting.posting_gap_check`` (nightly).
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal
from app.tasks.outbox import consumer


async def _on(iid: uuid.UUID, key: str = "accounting.core") -> bool:
    from app.core.features import is_enabled

    return await is_enabled(iid, key)


def _ids(event: dict[str, Any]) -> tuple[uuid.UUID, dict[str, Any]]:
    return uuid.UUID(str(event["institution_id"])), event.get("payload") or {}


def _svc(db: Any, iid: uuid.UUID) -> Any:
    from app.services.accounting.posting_service import PostingService

    return PostingService(db, None, institution_id=iid)


@consumer("accounting.fee_payment", events=["fees.payment_received"])
async def on_fee_payment(db: Any, event: dict[str, Any]) -> None:
    iid, p = _ids(event)
    if p.get("payment_id") and await _on(iid):
        await _svc(db, iid).fee_payment(uuid.UUID(str(p["payment_id"])))


@consumer("accounting.fee_reversal", events=["fees.receipt_cancelled", "fees.payment_bounced"])
async def on_fee_reversal(db: Any, event: dict[str, Any]) -> None:
    iid, p = _ids(event)
    if p.get("payment_id") and await _on(iid):
        await _svc(db, iid).fee_reversal(uuid.UUID(str(p["payment_id"])))


@consumer("accounting.fee_refund", events=["fees.refund_processed"])
async def on_fee_refund(db: Any, event: dict[str, Any]) -> None:
    iid, p = _ids(event)
    if p.get("refund_id") and await _on(iid):
        await _svc(db, iid).fee_refund(uuid.UUID(str(p["refund_id"])))


@consumer("accounting.vendor_bill", events=["inventory.bill_paid"])
async def on_bill_paid(db: Any, event: dict[str, Any]) -> None:
    iid, p = _ids(event)
    if p.get("bill_id") and await _on(iid):
        await _svc(db, iid).vendor_bill(uuid.UUID(str(p["bill_id"])))


@consumer("accounting.payroll", events=["payroll.paid"])
async def on_payroll(db: Any, event: dict[str, Any]) -> None:
    iid, p = _ids(event)
    if p.get("payroll_id") and await _on(iid):
        await _svc(db, iid).payroll(uuid.UUID(str(p["payroll_id"])))


@consumer("accounting.depreciation", events=["asset.depreciated"])
async def on_depreciation(db: Any, event: dict[str, Any]) -> None:
    iid, p = _ids(event)
    if await _on(iid):
        svc = _svc(db, iid)
        await svc.depreciation(str(p.get("financial_year")), int(p.get("depreciation_paise") or 0), await svc.today())


@consumer("accounting.asset_disposal", events=["inventory.asset_disposed"])
async def on_disposal(db: Any, event: dict[str, Any]) -> None:
    iid, p = _ids(event)
    if p.get("asset_id") and await _on(iid):
        await _svc(db, iid).asset_disposal(uuid.UUID(str(p["asset_id"])), int(p.get("sale_value_paise") or 0))


@consumer("accounting.donation", events=["alumni.donation_received"])
async def on_donation(db: Any, event: dict[str, Any]) -> None:
    iid, p = _ids(event)
    if p.get("donation_id") and await _on(iid):
        svc = _svc(db, iid)
        on = date.fromisoformat(p["received_on"]) if p.get("received_on") else await svc.today()
        await svc.donation(
            uuid.UUID(str(p["donation_id"])), int(p.get("amount_paise") or 0), on, bool(p.get("restricted"))
        )


@consumer("accounting.budget_commit", events=["budget.commit_requested", "budget.commit_released"])
async def on_budget_commit(db: Any, event: dict[str, Any]) -> None:
    from app.services.accounting.budget_service import BudgetService

    iid, p = _ids(event)
    if p.get("applied") or not p.get("budget_head_id") or not await _on(iid, "accounting.budgets"):
        return
    await BudgetService(db, None, institution_id=iid).commit(
        uuid.UUID(str(p["budget_head_id"])),
        int(p.get("amount_paise") or 0),
        release=event.get("event_type") == "budget.commit_released",
    )


@consumer("accounting.grant_from_project", events=["research.project_sanctioned"])
async def on_project(db: Any, event: dict[str, Any]) -> None:
    from app.services.accounting.grant_service import GrantService

    iid, p = _ids(event)
    if not p.get("project_id") or not await _on(iid, "accounting.grants_ledger"):
        return
    await GrantService(db, None, institution_id=iid).from_project(
        uuid.UUID(str(p["project_id"])),
        str(p.get("title") or "Research grant"),
        p.get("funding_agency"),
        int(p.get("sanctioned_paise") or 0),
        uuid.UUID(str(p["pi_staff_id"])) if p.get("pi_staff_id") else None,
        p.get("budget_heads"),
    )


# ---- jobs -----------------------------------------------------------------------------------------------------------------
@celery.task(name="jobs.accounting.posting_replay", queue="reports")
@job("accounting.posting_replay", queue="reports")
async def posting_replay(ctx: JobContext, db: Any, date_from: str, date_to: str, **_: Any) -> dict[str, Any]:
    from app.services.accounting.posting_service import PostingService

    principal = await _principal(db, ctx)
    out = await PostingService(db, principal).replay(date.fromisoformat(date_from), date.fromisoformat(date_to))
    await ctx.progress(db, 100, f"{sum(out.values())} posting row(s)")
    return out


@celery.task(name="jobs.accounting.export", queue="reports")
@job("accounting.export", queue="reports")
async def export(ctx: JobContext, db: Any, export_id: str, **params: Any) -> dict[str, Any]:
    from app.schemas.accounting import ExportRequest
    from app.services.accounting.finance_service import FinanceService

    principal = await _principal(db, ctx)
    body = ExportRequest(**{k: v for k, v in params.items() if k in ExportRequest.model_fields})
    out = await FinanceService(db, principal).run_export(uuid.UUID(export_id), body)
    await ctx.progress(db, 100, f"{out['vouchers']} voucher(s)")
    return out


@celery.task(name="jobs.accounting.gst_export", queue="reports")
@job("accounting.gst_export", queue="reports")
async def gst_export(ctx: JobContext, db: Any, period: str, **_: Any) -> dict[str, Any]:
    from app.services.accounting.finance_service import FinanceService

    principal = await _principal(db, ctx)
    out = await FinanceService(db, principal).gst_csv(period)
    await ctx.progress(db, 100, "GST CSV ready")
    return out


@celery.task(name="jobs.accounting.year_close", queue="reports")
@job("accounting.year_close", queue="reports")
async def year_close(
    ctx: JobContext, db: Any, academic_year_id: str, carry_forward: str = "none", **_: Any
) -> dict[str, Any]:
    from app.services.accounting.budget_service import BudgetService

    principal = await _principal(db, ctx)
    out = await BudgetService(db, principal).year_close(uuid.UUID(academic_year_id), carry_forward)
    await ctx.progress(db, 100, f"{out['frozen']} head(s) frozen")
    return out


# ---- Beat ---------------------------------------------------------------------------------------------------------------------
def _beat(label: str, feature: str, fn: Any) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        return int(await fn(db, iid))

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.accounting.budget_threshold_scan", queue="scheduled")
def budget_threshold_scan() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.accounting.budget_service import BudgetService

        return await BudgetService(db, None, institution_id=iid).threshold_scan()

    return _beat("accounting_budget_threshold_scan", "accounting.budgets", fn)


@celery.task(name="beat.accounting.reconciliation_reminder", queue="scheduled")
def reconciliation_reminder() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.accounting.reconciliation_service import ReconciliationService

        return await ReconciliationService(db, None, institution_id=iid).reminder()

    return _beat("accounting_reconciliation_reminder", "accounting.core", fn)


@celery.task(name="beat.accounting.posting_gap_check", queue="scheduled")
def posting_gap_check() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.accounting.posting_service import PostingService

        svc = PostingService(db, None, institution_id=iid)
        gaps = await svc.gaps()
        if gaps:
            await svc._notify(
                "accounting.reconciliation_pending", [], {"count": len(gaps)}, audience={"roles": ["accountant"]}
            )
        return len(gaps)

    return _beat("accounting_posting_gap_check", "accounting.core", fn)
