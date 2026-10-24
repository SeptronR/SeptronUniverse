"""Inventory, procurement & bills — Prompts/22 §22.8.

Each route carries its ``inventory.*`` feature; visibility narrows in the services (own / custodian / store keeper /
department / college / all / vendor; 404 otherwise, 403 for stock movements in a store that is not the caller's).
Stock movements and audit scans honour ``Idempotency-Key``; item import, depreciation runs, QR labels and XLSX reports
answer ``202`` with a ``job_id``. ``vendor_router`` serves the supplier portal (``procurement:quote`` + an active
supplier account); ``public_router`` holds the self-registration (rate-limited + captcha; ``PUBLIC_ROUTES``).
Fixed paths precede parameterised ones.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.core.rate_limit import rate_limited, verify_captcha
from app.db.session import get_db
from app.schemas.common import Envelope
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
    BillDecision,
    BillPay,
    ComparativeStatement,
    DepreciationRunRequest,
    DepreciationSummary,
    GrnCreate,
    GrnResponse,
    IndentCreate,
    IndentFulfil,
    IndentResponse,
    IndentUpdate,
    InvCategoryIn,
    InvCategoryOut,
    InvJobAccepted,
    InvReport,
    ItemImport,
    ItemIn,
    ItemOut,
    ItemUpdate,
    PoAction,
    PoCreate,
    PoResponse,
    PoUpdate,
    QuotationIn,
    QuotationOut,
    ReturnRequest,
    StockAdjust,
    StockIssueRequest,
    StockLevelOut,
    StockResult,
    StockTransfer,
    StockTxnOut,
    StoreIn,
    StoreOut,
    SupplierAction,
    SupplierIn,
    SupplierOut,
    SupplierRegister,
    SupplierUpdate,
    VendorBillIn,
    VendorBillOut,
    VendorStoreSale,
    WriteOffRequest,
)
from app.services.inventory.asset_service import AssetService
from app.services.inventory.bill_service import BillService
from app.services.inventory.common import visibility_scopes
from app.services.inventory.indent_service import IndentService
from app.services.inventory.master_service import MasterService
from app.services.inventory.procurement_service import ProcurementService
from app.services.inventory.reports_service import KINDS, InventoryReportsService
from app.services.inventory.stock_service import StockService
from app.services.inventory.vendor_service import VendorService, tenant_by_slug
from app.utils.response import ok

router = APIRouter(tags=["inventory"])
vendor_router = APIRouter(tags=["vendor-portal"])
public_router = APIRouter(tags=["vendor-portal"])

INV, PR = "inventory", "procurement"
ANY = any_permission_required(
    (INV, "view"),
    (INV, "view_all"),
    (INV, "manage"),
    (INV, "indent"),
    (INV, "issue"),
    (INV, "receive"),
    (INV, "approve_indent"),
    (INV, "asset_audit"),
)
MANAGE = any_permission_required((INV, "manage"))
READ = any_permission_required((INV, "view_all"), (INV, "manage"), (PR, "view_all"), (PR, "quote"))
STORE = any_permission_required((INV, "manage"), (INV, "view_all"), (INV, "receive"), (INV, "issue"), (INV, "approve_indent"))
MOVE = any_permission_required((INV, "issue"), (INV, "receive"), (INV, "manage"))
INDENT = any_permission_required((INV, "indent"), (INV, "approve_indent"), (INV, "issue"), (INV, "view_all"), (INV, "manage"))
QUOTE = any_permission_required((PR, "quote"), (PR, "manage"), (PR, "view_all"), (INV, "manage"))
PO = any_permission_required(
    (PR, "manage"),
    (PR, "po_approve"),
    (PR, "view"),
    (PR, "view_all"),
    (PR, "create"),
    (INV, "manage"),
    (INV, "approve_indent"),
)
PO_WRITE = any_permission_required((PR, "create"), (PR, "update"), (PR, "manage"), (INV, "manage"))
PO_APPROVE = any_permission_required((PR, "po_approve"))
RECEIVE = any_permission_required((INV, "receive"), (INV, "view_all"), (INV, "manage"), (PR, "view_all"))
ASSET = any_permission_required((INV, "manage"), (INV, "view_all"), (INV, "view"), (INV, "asset_audit"), (INV, "approve_indent"))
AUDIT = any_permission_required((INV, "asset_audit"), (INV, "manage"), (INV, "view_all"))
DEPR = any_permission_required((INV, "manage"), (INV, "view_all"), ("accounting", "view"))
BILL = any_permission_required(
    (PR, "bill_approve"), (INV, "manage"), (INV, "view_all"), ("accounting", "view"), (PR, "view_all")
)
BILL_PAY = any_permission_required((PR, "bill_approve"), ("accounting", "manage"))
EXPORT = any_permission_required((INV, "view_all"), (INV, "manage"), ("reports", "export"))
VENDOR = any_permission_required((PR, "quote"))
SALES = any_permission_required((INV, "issue"), (INV, "manage"))

CORE = [feature_required("inventory.core")]
PROC = [feature_required("inventory.procurement")]
ASSETS = [feature_required("inventory.assets")]
QR = [feature_required("inventory.asset_qr")]
BILLS = [feature_required("inventory.bills")]
PORTAL = [feature_required("inventory.vendor_portal")]
VSTORE = [feature_required("inventory.vendor_store")]


def _vis(principal: Principal, data: Any) -> dict[str, Any]:
    tabs = visibility_scopes(principal)
    res = ok(data)
    res.setdefault("meta", {})["visibility"] = {
        "self": True,
        "scopes": [t for t in tabs if t != "self"] or ["self"],
        "default": tabs[-1] if tabs else "self",
    }
    return res


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(InvJobAccepted(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


async def _idem(request: Request, db: AsyncSession, out: Any, message: str = "Recorded") -> dict[str, Any]:
    response = ok(out.model_dump(mode="json") if hasattr(out, "model_dump") else out, message=message)
    await store(request, response, db)
    return response


# ---- suppliers ----------------------------------------------------------------------------------------------------------------
@router.get("/inventory/suppliers", summary="Suppliers", response_model=Envelope[list[SupplierOut]], dependencies=CORE)
async def suppliers(
    request: Request,
    status: str | None = None,
    q: str | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).suppliers(status, q))


@router.post(
    "/inventory/suppliers",
    status_code=201,
    summary="Add a supplier",
    response_model=Envelope[SupplierOut],
    dependencies=CORE,
)
async def supplier_create(
    body: SupplierIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).create_supplier(body))


@router.get("/inventory/suppliers/{id}", summary="Supplier", response_model=Envelope[SupplierOut], dependencies=CORE)
async def supplier_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = MasterService(db, principal, request)
    return ok(svc.supplier_out(await svc.supplier(id)))


@router.put(
    "/inventory/suppliers/{id}", summary="Edit a supplier", response_model=Envelope[SupplierOut], dependencies=CORE
)
async def supplier_update(
    id: uuid.UUID,
    body: SupplierUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).update_supplier(id, body))


@router.post(
    "/inventory/suppliers/{id}/verify",
    summary="Verify a registered supplier",
    response_model=Envelope[SupplierOut],
    dependencies=CORE,
)
async def supplier_verify(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).verify(id))


@router.post(
    "/inventory/suppliers/{id}/blacklist",
    summary="Blacklist a supplier",
    response_model=Envelope[SupplierOut],
    dependencies=CORE,
)
async def supplier_blacklist(
    id: uuid.UUID,
    body: SupplierAction,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).blacklist(id, body.reason))


@router.get(
    "/inventory/suppliers/{id}/statement",
    summary="Supplier statement (POs, bills, outstanding)",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def supplier_statement(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BillService(db, principal, request).statement(id))


# ---- stores / categories / items --------------------------------------------------------------------------------------------------
@router.get("/inventory/stores", summary="Stores (scoped)", response_model=Envelope[list[StoreOut]], dependencies=CORE)
async def stores(
    request: Request, principal: Principal = Depends(STORE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return _vis(principal, await MasterService(db, principal, request).stores())


@router.post(
    "/inventory/stores", status_code=201, summary="Create a store", response_model=Envelope[StoreOut], dependencies=CORE
)
async def store_create(
    body: StoreIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).save_store(body))


@router.put("/inventory/stores/{id}", summary="Edit a store", response_model=Envelope[StoreOut], dependencies=CORE)
async def store_update(
    id: uuid.UUID,
    body: StoreIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).save_store(body, id))


@router.get(
    "/inventory/stores/{id}/stock",
    summary="Stock of a store (+ below-min chips)",
    response_model=Envelope[list[StockLevelOut]],
    dependencies=CORE,
)
async def store_stock(
    id: uuid.UUID,
    request: Request,
    below_min: bool | None = None,
    principal: Principal = Depends(STORE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StockService(db, principal, request).stock(id, below_min))


@router.get(
    "/inventory/categories", summary="Item categories", response_model=Envelope[list[InvCategoryOut]], dependencies=CORE
)
async def categories(
    request: Request, principal: Principal = Depends(ANY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).categories())


@router.post(
    "/inventory/categories",
    status_code=201,
    summary="Add a category",
    response_model=Envelope[InvCategoryOut],
    dependencies=CORE,
)
async def category_create(
    body: InvCategoryIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).create_category(body))


@router.post(
    "/inventory/items/import",
    status_code=202,
    summary="Import items from CSV (job)",
    response_model=Envelope[InvJobAccepted],
    dependencies=CORE,
)
async def items_import(
    body: ItemImport, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _job(db, principal, "inventory.item_import", {"csv": body.csv})


@router.get("/inventory/items", summary="Item catalogue", response_model=Envelope[list[ItemOut]], dependencies=CORE)
async def items(
    request: Request,
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    hazardous: bool | None = None,
    principal: Principal = Depends(ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).items(q, category_id, hazardous))


@router.post(
    "/inventory/items", status_code=201, summary="Add an item", response_model=Envelope[ItemOut], dependencies=CORE
)
async def item_create(
    body: ItemIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).create_item(body))


@router.get("/inventory/items/{id}", summary="Item", response_model=Envelope[ItemOut], dependencies=CORE)
async def item_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ANY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = MasterService(db, principal, request)
    return ok((await svc.item_outs([await svc.item(id)]))[0])


@router.put("/inventory/items/{id}", summary="Edit an item", response_model=Envelope[ItemOut], dependencies=CORE)
async def item_update(
    id: uuid.UUID,
    body: ItemUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MasterService(db, principal, request).update_item(id, body))


@router.delete(
    "/inventory/items/{id}",
    summary="Delete an item (no stock)",
    response_model=Envelope[dict[str, Any]],
    dependencies=CORE,
)
async def item_delete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await MasterService(db, principal, request).delete_item(id)
    return ok({"id": str(id)})


@router.get(
    "/inventory/items/{id}/ledger",
    summary="Stock ledger of an item",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=CORE,
)
async def item_ledger(
    id: uuid.UUID,
    request: Request,
    store_id: uuid.UUID | None = None,
    principal: Principal = Depends(STORE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StockService(db, principal, request).ledger(id, store_id))


# ---- stock ----------------------------------------------------------------------------------------------------------------------
@router.post(
    "/inventory/stock/issue",
    summary="Issue stock (Idempotency-Key)",
    response_model=Envelope[StockResult],
    dependencies=CORE,
)
async def stock_issue(
    body: StockIssueRequest,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(MOVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await StockService(db, principal, request).issue(body), "Issued")


@router.post(
    "/inventory/stock/return",
    summary="Return stock (Idempotency-Key)",
    response_model=Envelope[StockResult],
    dependencies=CORE,
)
async def stock_return(
    body: ReturnRequest,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(MOVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await StockService(db, principal, request).return_(body), "Returned")


@router.post(
    "/inventory/stock/transfer",
    summary="Transfer between stores (Idempotency-Key)",
    response_model=Envelope[StockResult],
    dependencies=CORE,
)
async def stock_transfer(
    body: StockTransfer,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(MOVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await StockService(db, principal, request).transfer(body), "Transferred")


@router.post(
    "/inventory/stock/adjust",
    summary="Adjust stock (Idempotency-Key)",
    response_model=Envelope[StockResult],
    dependencies=CORE,
)
async def stock_adjust(
    body: StockAdjust,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(MOVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await StockService(db, principal, request).adjust(body), "Adjusted")


@router.post(
    "/inventory/stock/write-off",
    summary="Write off stock (Idempotency-Key)",
    response_model=Envelope[StockResult],
    dependencies=CORE,
)
async def stock_write_off(
    body: WriteOffRequest,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(MOVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await StockService(db, principal, request).write_off(body), "Written off")


@router.get(
    "/inventory/stock/transactions",
    summary="Stock transactions",
    response_model=Envelope[list[StockTxnOut]],
    dependencies=CORE,
)
async def stock_transactions(
    request: Request,
    store_id: uuid.UUID | None = None,
    item_id: uuid.UUID | None = None,
    txn_type: str | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(STORE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StockService(db, principal, request).transactions(store_id, item_id, txn_type, date_from, date_to))


@router.get(
    "/inventory/stock/hazardous-register",
    summary="Chemical / hazardous register",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=[feature_required("inventory.lab_consumables")],
)
async def hazardous(
    request: Request, principal: Principal = Depends(STORE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StockService(db, principal, request).hazardous_register())


# ---- indents -------------------------------------------------------------------------------------------------------------------------
@router.get(
    "/inventory/indents/me", summary="My indents", response_model=Envelope[list[IndentResponse]], dependencies=PROC
)
async def my_indents(
    request: Request, principal: Principal = Depends(INDENT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IndentService(db, principal, request).list_indents(mine=True))


@router.get(
    "/inventory/indents",
    summary="Indents (ScopeTabs)",
    response_model=Envelope[list[IndentResponse]],
    dependencies=PROC,
)
async def indents(
    request: Request,
    department_id: uuid.UUID | None = None,
    status: str | None = None,
    scope: str | None = Query(None, pattern="^(self|department|college|all)$"),
    principal: Principal = Depends(INDENT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(
        principal,
        await IndentService(db, principal, request).list_indents(
            department_id=department_id, status=status, scope=scope
        ),
    )


@router.post(
    "/inventory/indents",
    status_code=201,
    summary="Raise an indent (draft)",
    response_model=Envelope[IndentResponse],
    dependencies=PROC,
)
async def indent_create(
    body: IndentCreate, request: Request, principal: Principal = Depends(INDENT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IndentService(db, principal, request).create(body))


@router.get("/inventory/indents/{id}", summary="Indent", response_model=Envelope[IndentResponse], dependencies=PROC)
async def indent_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(INDENT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IndentService(db, principal, request).get(id))


@router.put(
    "/inventory/indents/{id}", summary="Edit a draft indent", response_model=Envelope[IndentResponse], dependencies=PROC
)
async def indent_update(
    id: uuid.UUID,
    body: IndentUpdate,
    request: Request,
    principal: Principal = Depends(INDENT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await IndentService(db, principal, request).update(id, body))


@router.post(
    "/inventory/indents/{id}/submit",
    summary="Submit (workflow procurement.indent)",
    response_model=Envelope[IndentResponse],
    dependencies=PROC,
)
async def indent_submit(
    id: uuid.UUID, request: Request, principal: Principal = Depends(INDENT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IndentService(db, principal, request).submit(id))


@router.post(
    "/inventory/indents/{id}/fulfil",
    summary="Fulfil lines from stock",
    response_model=Envelope[IndentResponse],
    dependencies=PROC,
)
async def indent_fulfil(
    id: uuid.UUID,
    body: IndentFulfil,
    request: Request,
    principal: Principal = Depends(MOVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await IndentService(db, principal, request).fulfil(id, body))


@router.post(
    "/inventory/indents/{id}/close",
    summary="Close an indent",
    response_model=Envelope[IndentResponse],
    dependencies=PROC,
)
async def indent_close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(INDENT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IndentService(db, principal, request).close(id))


@router.get(
    "/inventory/indents/{id}/quotations",
    summary="Quotations of an indent",
    response_model=Envelope[list[QuotationOut]],
    dependencies=PROC,
)
async def quotations(
    id: uuid.UUID, request: Request, principal: Principal = Depends(QUOTE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).quotations(id))


@router.post(
    "/inventory/indents/{id}/quotations",
    status_code=201,
    summary="Record a quotation",
    response_model=Envelope[QuotationOut],
    dependencies=PROC,
)
async def quotation_add(
    id: uuid.UUID,
    body: QuotationIn,
    request: Request,
    principal: Principal = Depends(QUOTE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).add_quotation(id, body))


@router.get(
    "/inventory/indents/{id}/comparative-statement",
    summary="Comparative statement (L1 per line)",
    response_model=Envelope[ComparativeStatement],
    dependencies=PROC,
)
async def comparative(
    id: uuid.UUID, request: Request, principal: Principal = Depends(QUOTE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).comparative(id))


@router.put(
    "/inventory/quotations/{id}", summary="Edit a quotation", response_model=Envelope[QuotationOut], dependencies=PROC
)
async def quotation_update(
    id: uuid.UUID,
    body: QuotationIn,
    request: Request,
    principal: Principal = Depends(QUOTE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).update_quotation(id, body))


@router.post(
    "/inventory/quotations/{id}/select",
    summary="Select a quotation",
    response_model=Envelope[QuotationOut],
    dependencies=PROC,
)
async def quotation_select(
    id: uuid.UUID, request: Request, principal: Principal = Depends(QUOTE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).select_quotation(id))


# ---- purchase orders ------------------------------------------------------------------------------------------------------------------
@router.get(
    "/inventory/purchase-orders",
    summary="Purchase orders",
    response_model=Envelope[list[PoResponse]],
    dependencies=PROC,
)
async def pos(
    request: Request,
    status: str | None = None,
    supplier_id: uuid.UUID | None = None,
    principal: Principal = Depends(PO),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).list_pos(status, supplier_id))


@router.post(
    "/inventory/purchase-orders",
    status_code=201,
    summary="Create a PO (from a quotation or lines)",
    response_model=Envelope[PoResponse],
    dependencies=PROC,
)
async def po_create(
    body: PoCreate, request: Request, principal: Principal = Depends(PO_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).create_po(body))


@router.get("/inventory/purchase-orders/{id}.pdf", summary="PO (PDF)", dependencies=PROC)
async def po_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(PO), db: AsyncSession = Depends(get_db)
) -> Response:
    from app.utils.pdf import simple_pdf

    title, lines = await ProcurementService(db, principal, request).po_lines_text(id)
    return Response(content=simple_pdf(lines, title=title), media_type="application/pdf")


@router.get(
    "/inventory/purchase-orders/{id}", summary="Purchase order", response_model=Envelope[PoResponse], dependencies=PROC
)
async def po_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(PO), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).get_po(id))


@router.put(
    "/inventory/purchase-orders/{id}", summary="Edit a draft PO", response_model=Envelope[PoResponse], dependencies=PROC
)
async def po_update(
    id: uuid.UUID,
    body: PoUpdate,
    request: Request,
    principal: Principal = Depends(PO_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).update_po(id, body))


@router.post(
    "/inventory/purchase-orders/{id}/approve",
    summary="Approve a PO below the workflow threshold",
    response_model=Envelope[PoResponse],
    dependencies=PROC,
)
async def po_approve(
    id: uuid.UUID, request: Request, principal: Principal = Depends(PO_APPROVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).approve_po(id))


@router.post(
    "/inventory/purchase-orders/{id}/{action}",
    summary="Submit / send / amend / cancel / close",
    response_model=Envelope[PoResponse],
    dependencies=PROC,
)
async def po_action(
    id: uuid.UUID,
    action: str,
    request: Request,
    body: PoAction | None = None,
    principal: Principal = Depends(PO_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ProcurementService(db, principal, request)
    b = body or PoAction()
    if action == "submit":
        return ok(await svc.submit_po(id))
    if action == "send":
        return ok(await svc.send_po(id, b.email))
    if action == "amend":
        return ok(await svc.amend_po(id, b.reason))
    if action == "cancel":
        return ok(await svc.cancel_po(id, b.reason))
    if action == "close":
        return ok(await svc.close_po(id))
    raise APIError(404, ErrorCode.NOT_FOUND, "Unknown action")


# ---- goods receipts ---------------------------------------------------------------------------------------------------------------------
@router.get(
    "/inventory/goods-receipts", summary="Goods receipts", response_model=Envelope[list[GrnResponse]], dependencies=PROC
)
async def grns(
    request: Request,
    po_id: uuid.UUID | None = None,
    principal: Principal = Depends(RECEIVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).grns(po_id))


@router.post(
    "/inventory/goods-receipts",
    status_code=201,
    summary="Receive goods against a PO (partial allowed)",
    response_model=Envelope[GrnResponse],
    dependencies=PROC,
)
async def grn_create(
    body: GrnCreate, request: Request, principal: Principal = Depends(RECEIVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).receive(body))


@router.get("/inventory/goods-receipts/{id}.pdf", summary="GRN (PDF)", dependencies=PROC)
async def grn_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECEIVE), db: AsyncSession = Depends(get_db)
) -> Response:
    from app.utils.pdf import simple_pdf

    title, lines = await ProcurementService(db, principal, request).grn_lines_text(id)
    return Response(content=simple_pdf(lines, title=title), media_type="application/pdf")


@router.get(
    "/inventory/goods-receipts/{id}", summary="Goods receipt", response_model=Envelope[GrnResponse], dependencies=PROC
)
async def grn_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECEIVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProcurementService(db, principal, request).grn(id))


# ---- assets ------------------------------------------------------------------------------------------------------------------------------
@router.get(
    "/inventory/assets/me", summary="Assets in my custody", response_model=Envelope[list[AssetOut]], dependencies=ASSETS
)
async def my_assets(
    request: Request, principal: Principal = Depends(ASSET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).list_assets(mine=True))


@router.post(
    "/inventory/assets/from-grn",
    status_code=201,
    summary="Create assets from a GRN",
    response_model=Envelope[list[AssetOut]],
    dependencies=ASSETS,
)
async def assets_from_grn(
    body: AssetBulkFromGrn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).from_grn(body))


@router.post(
    "/inventory/assets/qr-labels",
    status_code=202,
    summary="QR label sheet (job → PDF)",
    response_model=Envelope[InvJobAccepted],
    dependencies=QR,
)
async def qr_labels(
    body: AssetQrLabelsRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _job(db, principal, "inventory.qr_labels", body.model_dump(mode="json"))


@router.get(
    "/inventory/assets/lookup/{qr_token}",
    summary="Look an asset up by its label",
    response_model=Envelope[AssetOut],
    dependencies=QR,
)
async def asset_lookup(
    qr_token: str, request: Request, principal: Principal = Depends(AUDIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).lookup(qr_token))


@router.post(
    "/inventory/assets/depreciation/run",
    status_code=202,
    summary="Depreciation run for a financial year (job; preview inline)",
    response_model=Envelope[InvJobAccepted],
    dependencies=ASSETS,
)
async def depreciation_run(
    body: DepreciationRunRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if body.preview:
        return ok(await AssetService(db, principal, request).depreciation(body.financial_year, preview=True))
    return await _job(db, principal, "inventory.depreciation_run", {"financial_year": body.financial_year})


@router.get(
    "/inventory/assets/depreciation",
    summary="Depreciation schedule of a financial year",
    response_model=Envelope[DepreciationSummary],
    dependencies=ASSETS,
)
async def depreciation(
    request: Request,
    fy: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(DEPR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).depreciation_schedule(fy))


@router.get(
    "/inventory/assets", summary="Asset register (scoped)", response_model=Envelope[list[AssetOut]], dependencies=ASSETS
)
async def assets(
    request: Request,
    department_id: uuid.UUID | None = None,
    status: str | None = None,
    category: str | None = None,
    q: str | None = None,
    principal: Principal = Depends(ASSET),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return _vis(
        principal,
        await AssetService(db, principal, request).list_assets(
            department_id=department_id, status=status, category=category, q=q
        ),
    )


@router.post(
    "/inventory/assets",
    status_code=201,
    summary="Register an asset",
    response_model=Envelope[AssetOut],
    dependencies=ASSETS,
)
async def asset_create(
    body: AssetIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).create(body))


@router.get("/inventory/assets/{id}", summary="Asset", response_model=Envelope[AssetOut], dependencies=ASSETS)
async def asset_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ASSET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).get(id))


@router.put("/inventory/assets/{id}", summary="Edit an asset", response_model=Envelope[AssetOut], dependencies=ASSETS)
async def asset_update(
    id: uuid.UUID,
    body: AssetUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).update(id, body))


@router.post(
    "/inventory/assets/{id}/transfer",
    summary="Transfer custody / location / department",
    response_model=Envelope[AssetOut],
    dependencies=ASSETS,
)
async def asset_transfer(
    id: uuid.UUID,
    body: AssetTransfer,
    request: Request,
    principal: Principal = Depends(AUDIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).transfer(id, body))


@router.post(
    "/inventory/assets/{id}/accept-custody",
    summary="Accept custody (new custodian)",
    response_model=Envelope[AssetOut],
    dependencies=ASSETS,
)
async def asset_accept(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ASSET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).accept_custody(id))


@router.post(
    "/inventory/assets/{id}/status",
    summary="Change status (repair / condemn / dispose)",
    response_model=Envelope[AssetOut],
    dependencies=ASSETS,
)
async def asset_status(
    id: uuid.UUID,
    body: AssetStatusChange,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).set_status(id, body))


@router.get(
    "/inventory/assets/{id}/history",
    summary="Custody, depreciation and audit history",
    response_model=Envelope[dict[str, Any]],
    dependencies=ASSETS,
)
async def asset_history(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ASSET), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).history(id))


# ---- asset audits --------------------------------------------------------------------------------------------------------------------------
@router.get(
    "/inventory/asset-audits", summary="Audit cycles", response_model=Envelope[list[AuditCycleOut]], dependencies=ASSETS
)
async def audit_cycles(
    request: Request, principal: Principal = Depends(AUDIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).cycles())


@router.post(
    "/inventory/asset-audits",
    status_code=201,
    summary="Start an audit cycle",
    response_model=Envelope[AuditCycleOut],
    dependencies=ASSETS,
)
async def audit_start(
    body: AssetAuditStart, request: Request, principal: Principal = Depends(AUDIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).start_audit(body))


@router.post(
    "/inventory/asset-audits/{id}/scan",
    summary="Record scans (bulk, Idempotency-Key)",
    response_model=Envelope[AuditCycleOut],
    dependencies=ASSETS,
)
async def audit_scan(
    id: uuid.UUID,
    body: AssetAuditScan,
    request: Request,
    _k: str | None = Depends(idempotency_key),
    principal: Principal = Depends(AUDIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _idem(request, db, await AssetService(db, principal, request).scan(id, body))


@router.post(
    "/inventory/asset-audits/{id}/complete",
    summary="Complete an audit cycle",
    response_model=Envelope[AuditReport],
    dependencies=ASSETS,
)
async def audit_complete(
    id: uuid.UUID, request: Request, principal: Principal = Depends(AUDIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).complete(id))


@router.get(
    "/inventory/asset-audits/{id}/report",
    summary="Audit report",
    response_model=Envelope[AuditReport],
    dependencies=ASSETS,
)
async def audit_report(
    id: uuid.UUID, request: Request, principal: Principal = Depends(AUDIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssetService(db, principal, request).report(id))


# ---- vendor bills ---------------------------------------------------------------------------------------------------------------------------
@router.get(
    "/inventory/vendor-bills/ageing",
    summary="Bill ageing buckets",
    response_model=Envelope[dict[str, Any]],
    dependencies=BILLS,
)
async def bills_ageing(
    request: Request, principal: Principal = Depends(BILL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BillService(db, principal, request).ageing())


@router.get(
    "/inventory/vendor-bills", summary="Vendor bills", response_model=Envelope[list[VendorBillOut]], dependencies=BILLS
)
async def bills(
    request: Request,
    status: str | None = None,
    supplier_id: uuid.UUID | None = None,
    principal: Principal = Depends(BILL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BillService(db, principal, request).list_bills(status, supplier_id))


@router.post(
    "/inventory/vendor-bills",
    status_code=201,
    summary="Record a bill (three-way match, GST / TDS)",
    response_model=Envelope[VendorBillOut],
    dependencies=BILLS,
)
async def bill_create(
    body: VendorBillIn, request: Request, principal: Principal = Depends(BILL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BillService(db, principal, request).create(body))


@router.get("/inventory/vendor-bills/{id}", summary="Bill", response_model=Envelope[VendorBillOut], dependencies=BILLS)
async def bill_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(BILL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BillService(db, principal, request).get(id))


@router.post(
    "/inventory/vendor-bills/{id}/verify",
    summary="Verify a bill (inventory manager)",
    response_model=Envelope[VendorBillOut],
    dependencies=BILLS,
)
async def bill_verify(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await BillService(db, principal, request).verify(id))


@router.post(
    "/inventory/vendor-bills/{id}/decide",
    summary="Approve / reject / hold / release",
    response_model=Envelope[VendorBillOut],
    dependencies=BILLS,
)
async def bill_decide(
    id: uuid.UUID,
    body: BillDecision,
    request: Request,
    principal: Principal = Depends(BILL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BillService(db, principal, request).decide(id, body))


@router.post(
    "/inventory/vendor-bills/{id}/pay",
    summary="Mark a bill paid",
    response_model=Envelope[VendorBillOut],
    dependencies=BILLS,
)
async def bill_pay(
    id: uuid.UUID,
    body: BillPay,
    request: Request,
    principal: Principal = Depends(BILL_PAY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BillService(db, principal, request).pay(id, body))


# ---- vendor store ------------------------------------------------------------------------------------------------------------------------------
@router.get(
    "/inventory/vendor-store/sales",
    summary="Campus store sales of a day",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=VSTORE,
)
async def vs_sales(
    request: Request,
    on: date | None = Query(None, alias="date"),
    principal: Principal = Depends(SALES),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await VendorService(db, principal, request).sales(on))


@router.post(
    "/inventory/vendor-store/sales",
    status_code=201,
    summary="Record a campus store sale",
    response_model=Envelope[dict[str, Any]],
    dependencies=VSTORE,
)
async def vs_sale(
    body: VendorStoreSale, request: Request, principal: Principal = Depends(SALES), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VendorService(db, principal, request).sale(body))


@router.get(
    "/inventory/vendor-store/report",
    summary="Daily campus store report",
    response_model=Envelope[dict[str, Any]],
    dependencies=VSTORE,
)
async def vs_report(
    request: Request,
    on: date | None = Query(None, alias="date"),
    principal: Principal = Depends(SALES),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await VendorService(db, principal, request).daily_report(on))


# ---- reports ----------------------------------------------------------------------------------------------------------------------------------
@router.get(
    "/inventory/reports/{kind}",
    summary="Inventory report (JSON inline, XLSX job)",
    response_model=Envelope[InvReport],
    dependencies=CORE,
)
async def report(
    kind: str,
    request: Request,
    format: str = Query("json", pattern="^(json|xlsx)$"),
    fy: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if kind not in KINDS:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
    if format == "xlsx":
        return await _job(db, principal, "inventory.reports_export", {"kind": kind})
    return ok(await InventoryReportsService(db, principal, request).report(kind, fy))


# ---- vendor portal ---------------------------------------------------------------------------------------------------------------------------------
@public_router.post(
    "/vendor/register",
    status_code=201,
    summary="Supplier self-registration (captcha)",
    response_model=Envelope[SupplierOut],
    dependencies=[rate_limited("vendor_register", limit=5, window=600)],
)
async def vendor_register(
    body: SupplierRegister, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.db.session import bind_tenant, set_tenant

    await verify_captcha(body.captcha_token, request.client.host if request.client else None)
    iid = await tenant_by_slug(body.institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "inventory.vendor_portal"):
        raise APIError(
            403,
            ErrorCode.FEATURE_DISABLED,
            "Feature 'inventory.vendor_portal' is not enabled",
            {"feature": "inventory.vendor_portal"},
        )
    return ok(
        await VendorService(db, None, request, iid).register(body),
        message="Registered — the stores office will verify your details",
    )


@vendor_router.get(
    "/vendor/me", summary="My supplier profile", response_model=Envelope[SupplierOut], dependencies=PORTAL
)
async def vendor_me(
    request: Request, principal: Principal = Depends(VENDOR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VendorService(db, principal, request).me())


@vendor_router.put(
    "/vendor/me", summary="Update my supplier profile", response_model=Envelope[SupplierOut], dependencies=PORTAL
)
async def vendor_me_update(
    body: SupplierUpdate, request: Request, principal: Principal = Depends(VENDOR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VendorService(db, principal, request).update_me(body.contact, body.address, body.categories))


@vendor_router.get(
    "/vendor/rfqs",
    summary="Open requests for quotation",
    response_model=Envelope[list[IndentResponse]],
    dependencies=PORTAL,
)
async def vendor_rfqs(
    request: Request, principal: Principal = Depends(VENDOR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await VendorService(db, principal, request).rfqs())


@vendor_router.post(
    "/vendor/rfqs/{indent_id}/quotations",
    status_code=201,
    summary="Submit a quotation",
    response_model=Envelope[QuotationOut],
    dependencies=PORTAL,
)
async def vendor_quote(
    indent_id: uuid.UUID,
    body: QuotationIn,
    request: Request,
    principal: Principal = Depends(VENDOR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    vs = VendorService(db, principal, request)
    supplier = await vs.my_supplier()
    return ok(await ProcurementService(db, principal, request).add_quotation(indent_id, body, vendor=supplier))


@vendor_router.get(
    "/vendor/pos", summary="My purchase orders", response_model=Envelope[list[PoResponse]], dependencies=PORTAL
)
async def vendor_pos(
    request: Request, principal: Principal = Depends(VENDOR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    supplier = await VendorService(db, principal, request).my_supplier()
    return ok(await ProcurementService(db, principal, request).list_pos(vendor=supplier))


@vendor_router.post(
    "/vendor/pos/{id}/acknowledge", summary="Acknowledge a PO", response_model=Envelope[PoResponse], dependencies=PORTAL
)
async def vendor_ack(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VENDOR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    supplier = await VendorService(db, principal, request).my_supplier()
    return ok(await ProcurementService(db, None, request, principal.institution_id).acknowledge(id, supplier))


@vendor_router.get(
    "/vendor/grns", summary="Goods receipts of my POs", response_model=Envelope[list[GrnResponse]], dependencies=PORTAL
)
async def vendor_grns(
    request: Request, principal: Principal = Depends(VENDOR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    supplier = await VendorService(db, principal, request).my_supplier()
    return ok(await ProcurementService(db, principal, request).grns(vendor=supplier))


@vendor_router.get(
    "/vendor/bills",
    summary="My bills and their status",
    response_model=Envelope[list[VendorBillOut]],
    dependencies=PORTAL,
)
async def vendor_bills(
    request: Request, principal: Principal = Depends(VENDOR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    supplier = await VendorService(db, principal, request).my_supplier()
    return ok(await BillService(db, principal, request).list_bills(vendor=supplier))
