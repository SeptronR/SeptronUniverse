"""Inventory tasks — Prompts/22 §22.7.

Jobs (run as the requesting user): ``inventory.item_import``, ``inventory.qr_labels``, ``inventory.depreciation_run``,
``inventory.reports_export``. Beat: ``inventory.low_stock_scan`` / ``inventory.po_overdue_scan`` /
``inventory.bill_due_reminders`` (daily), ``inventory.chemical_expiry_scan`` / ``inventory.warranty_expiry`` (weekly),
``inventory.audit_due`` (monthly). PO / GRN PDFs are rendered inline by their endpoints.
"""

import uuid
from datetime import date
from typing import Any

from app.core.aio import run_async
from app.core.jobs import JobContext, job
from app.tasks.celery_app import celery
from app.tasks.hr import _for_institutions, _principal


@celery.task(name="jobs.inventory.item_import", queue="reports")
@job("inventory.item_import", queue="reports")
async def item_import(ctx: JobContext, db: Any, csv: str, **_: Any) -> dict[str, Any]:
    from app.services.inventory.master_service import MasterService

    principal = await _principal(db, ctx)
    out = await MasterService(db, principal).import_items(csv)
    await ctx.progress(db, 100, f"{out['created']} created / {len(out['failed'])} failed")
    return out


@celery.task(name="jobs.inventory.qr_labels", queue="reports")
@job("inventory.qr_labels", queue="reports")
async def qr_labels(ctx: JobContext, db: Any, **params: Any) -> dict[str, Any]:
    from app.core.files import build_key, storage
    from app.schemas.inventory import AssetQrLabelsRequest
    from app.services.inventory.asset_service import AssetService

    principal = await _principal(db, ctx)
    svc = AssetService(db, principal)
    pdf = await svc.qr_labels(
        AssetQrLabelsRequest(**{k: v for k, v in params.items() if k in AssetQrLabelsRequest.model_fields})
    )
    key = build_key(svc.inst, "asset-labels", f"labels-{uuid.uuid4().hex[:8]}.pdf")
    await storage.put(key, pdf, "application/pdf")
    await ctx.progress(db, 100, "Labels ready")
    return {"result_url": key}


@celery.task(name="jobs.inventory.depreciation_run", queue="reports")
@job("inventory.depreciation_run", queue="reports")
async def depreciation_run(ctx: JobContext, db: Any, financial_year: str, **_: Any) -> dict[str, Any]:
    from app.services.inventory.asset_service import AssetService

    principal = await _principal(db, ctx)
    out = await AssetService(db, principal).depreciation(financial_year)
    await ctx.progress(db, 100, f"{out.assets} assets · ₹{out.depreciation_paise / 100:,.0f}")
    return out.model_dump(mode="json") | {"rows": out.rows[:50]}


@celery.task(name="jobs.inventory.reports_export", queue="reports")
@job("inventory.reports_export", queue="reports")
async def reports_export(ctx: JobContext, db: Any, kind: str, **_: Any) -> dict[str, Any]:
    from app.services.inventory.reports_service import InventoryReportsService

    principal = await _principal(db, ctx)
    out = await InventoryReportsService(db, principal).report_xlsx(kind)
    await ctx.progress(db, 100, f"{out['rows']} rows")
    return out


def _beat(label: str, feature: str, fn: Any) -> dict[str, int]:
    async def one(db: Any, iid: uuid.UUID, today: date) -> int:
        return int(await fn(db, iid))

    return run_async(_for_institutions(feature, one, label))


@celery.task(name="beat.inventory.low_stock_scan", queue="scheduled")
def low_stock_scan() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.inventory.stock_service import StockService

        return await StockService(db, None, institution_id=iid).low_stock_scan()

    return _beat("inventory_low_stock_scan", "inventory.core", fn)


@celery.task(name="beat.inventory.chemical_expiry_scan", queue="scheduled")
def chemical_expiry_scan() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.inventory.stock_service import StockService

        return await StockService(db, None, institution_id=iid).chemical_expiry_scan()

    return _beat("inventory_chemical_expiry_scan", "inventory.lab_consumables", fn)


@celery.task(name="beat.inventory.po_overdue_scan", queue="scheduled")
def po_overdue_scan() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.inventory.procurement_service import ProcurementService

        return await ProcurementService(db, None, institution_id=iid).overdue_scan()

    return _beat("inventory_po_overdue_scan", "inventory.procurement", fn)


@celery.task(name="beat.inventory.bill_due_reminders", queue="scheduled")
def bill_due_reminders() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.inventory.bill_service import BillService

        return await BillService(db, None, institution_id=iid).due_reminders()

    return _beat("inventory_bill_due_reminders", "inventory.bills", fn)


@celery.task(name="beat.inventory.audit_due", queue="scheduled")
def audit_due() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.inventory.asset_service import AssetService

        return await AssetService(db, None, institution_id=iid).audit_due()

    return _beat("inventory_audit_due", "inventory.assets", fn)


@celery.task(name="beat.inventory.warranty_expiry", queue="scheduled")
def warranty_expiry() -> dict[str, int]:
    async def fn(db: Any, iid: uuid.UUID) -> int:
        from app.services.inventory.asset_service import AssetService

        return await AssetService(db, None, institution_id=iid).warranty_scan()

    return _beat("inventory_warranty_expiry", "inventory.assets", fn)
