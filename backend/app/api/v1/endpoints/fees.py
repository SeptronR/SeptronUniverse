"""Fees — Prompts/12 §12.8 (router included with ``feature_required("fees.core")``; sub-features per route:
{fees.discounts}, {fees.fines}, {fees.online_payment}, {fees.upi_qr}, {fees.offline_challan_reconciliation},
{fees.receipt_cancellation_approval}, {fees.refunds}, {fees.accounting_export}, {fees.thermal_receipts}).

Bulk invoices (above 200 enrolments), statement uploads, report exports and the accounting export answer ``202`` +
``job_id``; dry runs answer inline. ``public_router`` holds the gateway webhook (``PUBLIC_ROUTES``; signature checked
in the service, the tenant is read from ``?institution=<slug>`` / the header). Fixed paths precede parameterised ones.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.fees import (
    AccountingExportRequest,
    ApplicableStructureResponse,
    BounceRequest,
    BulkInvoiceRequest,
    CancelReceiptRequest,
    CollectRequest,
    DayBookClose,
    DayBookResponse,
    DiscountAssign,
    DiscountAssignmentOut,
    DiscountIn,
    DiscountOut,
    DuesResponse,
    FeeAssignRequest,
    FeeAssignResult,
    FeeDashboard,
    FeeHeadIn,
    FeeHeadOut,
    FeePaymentOut,
    FeeReport,
    FeeStructureCreate,
    FeeStructureResponse,
    FeeStructureUpdate,
    FineConfigIn,
    FineConfigOut,
    InvoiceCancelRequest,
    InvoiceResponse,
    LedgerAccountOut,
    OfflineDeclare,
    OnlineInitiateRequest,
    OnlineInitiateResponse,
    OnlineVerifyRequest,
    OrderStatusResponse,
    ReceiptResponse,
    ReconcileMatch,
    ReconcileRowOut,
    ReconcileSummary,
    ReconcileUpload,
    RefundCreate,
    RefundDecision,
    RefundProcess,
    RefundResponse,
    StructureCloneRequest,
    ThermalReceipt,
    UpiQrRequest,
    UpiQrResponse,
)
from app.services.fees.invoice_service import InvoiceService
from app.services.fees.payment_service import PaymentService
from app.services.fees.refund_service import RefundService
from app.services.fees.report_service import FeeReportService
from app.services.fees.structure_service import INLINE_LIMIT, StructureService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["fees"])
public_router = APIRouter(tags=["public"])

F = "fees"
STRUCT = permission_required(F, "structure_manage")
STRUCT_VIEW = any_permission_required((F, "structure_manage"), (F, "view"), (F, "view_all"), (F, "collect"))
VIEW = any_permission_required((F, "view"), (F, "view_all"), (F, "self"), (F, "collect"))
STAFF_VIEW = any_permission_required((F, "view"), (F, "view_all"), (F, "collect"))
VIEW_ALL = any_permission_required((F, "view_all"), (F, "collect"))
SELF = permission_required(F, "self")
SELF_OR_COLLECT = any_permission_required((F, "self"), (F, "collect"))
COLLECT = permission_required(F, "collect")
CANCEL = permission_required(F, "cancel_receipt")
CANCEL_DECIDE = any_permission_required((F, "cancel_receipt"), (F, "approve"))
RECONCILE = permission_required(F, "reconcile")
RECONCILE_OR_SELF = any_permission_required((F, "reconcile"), (F, "self"))
REFUND = permission_required(F, "refund")
REFUND_VIEW = any_permission_required((F, "refund"), (F, "view_all"), (F, "approve"))
REFUND_DECIDE = any_permission_required((F, "refund"), (F, "approve"))
REFUND_REQUEST = any_permission_required((F, "self"), (F, "refund"))
CONCESSION = permission_required(F, "concession")
CONCESSION_VIEW = any_permission_required((F, "concession"), (F, "view"), (F, "view_all"))
CONCESSION_DECIDE = any_permission_required((F, "concession"), (F, "approve"))
EXPORT = any_permission_required((F, "view_all"), (F, "export"))
MANAGE = permission_required(F, "manage")
DISC = [feature_required("fees.discounts")]
FINES = [feature_required("fees.fines")]
ONLINE = [feature_required("fees.online_payment")]
UPI = [feature_required("fees.upi_qr")]
OFFLINE = [feature_required("fees.offline_challan_reconciliation")]
CANCELF = [feature_required("fees.receipt_cancellation_approval")]
REFUNDS = [feature_required("fees.refunds")]
ACCEXP = [feature_required("fees.accounting_export")]
THERMAL = [feature_required("fees.thermal_receipts")]


def _queued(data: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(data, message=message))


# ---- heads / ledger -----------------------------------------------------------------------------------------------------
@router.get("/fee-heads", summary="Fee heads", response_model=Envelope[list[FeeHeadOut]])
async def list_heads(
    request: Request, principal: Principal = Depends(STRUCT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).heads())


@router.post("/fee-heads", summary="Create a fee head", response_model=Envelope[FeeHeadOut])
async def create_head(
    body: FeeHeadIn, request: Request, principal: Principal = Depends(STRUCT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).create_head(body), message="Head created")


@router.put("/fee-heads/{id}", summary="Update a fee head", response_model=Envelope[FeeHeadOut])
async def update_head(
    id: uuid.UUID,
    body: FeeHeadIn,
    request: Request,
    principal: Principal = Depends(STRUCT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).update_head(id, body), message="Head updated")


@router.delete("/fee-heads/{id}", summary="Delete (or deactivate when used) a fee head", response_model=Envelope[None])
async def delete_head(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STRUCT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await StructureService(db, principal, request).delete_head(id)
    return ok(None, message="Head removed")


@router.get(
    "/fees/ledger-accounts",
    summary="Minimal ledger chart (Phase 23 extends it)",
    response_model=Envelope[list[LedgerAccountOut]],
)
async def ledger(
    request: Request, principal: Principal = Depends(STRUCT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).ledger())


# ---- structures ---------------------------------------------------------------------------------------------------------
@router.get("/fee-structures", summary="Fee structures", response_model=Envelope[list[FeeStructureResponse]])
async def list_structures(
    request: Request,
    program_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(STRUCT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await StructureService(db, principal, request).list_structures(
            program_id=program_id, batch_id=batch_id, status=status
        )
    )


@router.post(
    "/fee-structures",
    summary="Create a structure (overlapping identical dimensions → 409)",
    response_model=Envelope[FeeStructureResponse],
)
async def create_structure(
    body: FeeStructureCreate,
    request: Request,
    principal: Principal = Depends(STRUCT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).create(body), message="Structure created")


@router.get(
    "/fee-structures/applicable",
    summary="Most specific effective structure for an enrolment",
    response_model=Envelope[ApplicableStructureResponse],
)
async def applicable(
    request: Request,
    enrollment_id: uuid.UUID,
    term_number: int | None = None,
    principal: Principal = Depends(STRUCT_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).applicable(enrollment_id, term_number))


@router.get("/fee-structures/{id}", summary="Structure with items", response_model=Envelope[FeeStructureResponse])
async def get_structure(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STRUCT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).get(id))


@router.put(
    "/fee-structures/{id}", summary="Update a structure (items replace)", response_model=Envelope[FeeStructureResponse]
)
async def update_structure(
    id: uuid.UUID,
    body: FeeStructureUpdate,
    request: Request,
    principal: Principal = Depends(STRUCT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).update(id, body), message="Structure updated")


@router.post(
    "/fee-structures/{id}/clone", summary="Clone to the next year", response_model=Envelope[FeeStructureResponse]
)
async def clone_structure(
    id: uuid.UUID,
    body: StructureCloneRequest,
    request: Request,
    principal: Principal = Depends(STRUCT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).clone(id, body), message="Structure cloned")


@router.post(
    "/fee-structures/{id}/assign",
    summary="Assign to enrolments / a batch (+ term invoices; > 200 → job)",
    response_model=Envelope[FeeAssignResult],
)
async def assign_structure(
    id: uuid.UUID,
    body: FeeAssignRequest,
    request: Request,
    principal: Principal = Depends(STRUCT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = StructureService(db, principal, request)
    if not body.dry_run and await svc.count_targets(body) > INLINE_LIMIT:
        from app.core.jobs import enqueue

        job = await enqueue(
            db, principal, "fees.bulk_invoice", {"structure_id": str(id), "body": body.model_dump(mode="json")}
        )
        return _queued({"job_id": str(job.id)}, "Assignment queued")
    return ok(await svc.assign(id, body), message="Preview" if body.dry_run else "Assigned")


@router.post(
    "/fees/bulk-invoice",
    status_code=202,
    summary="Term invoices for a batch from its applicable structures (job; dry_run inline)",
    response_model=Envelope[dict[str, Any]],
)
async def bulk_invoice(
    body: BulkInvoiceRequest,
    request: Request,
    principal: Principal = Depends(STRUCT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from app.core.jobs import enqueue

    if body.dry_run:
        from app.tasks.fees import bulk_by_batch

        return ok(await bulk_by_batch(db, principal, body.batch_id, body.term_id, dry_run=True), message="Preview")
    job = await enqueue(
        db,
        principal,
        "fees.bulk_invoice",
        {"batch_id": str(body.batch_id), "term_id": str(body.term_id) if body.term_id else None},
    )
    return _queued({"job_id": str(job.id)}, "Bulk invoicing queued")


# ---- discounts / fines --------------------------------------------------------------------------------------------------
@router.get("/fee-discounts", summary="Discounts", dependencies=DISC, response_model=Envelope[list[DiscountOut]])
async def list_discounts(
    request: Request, principal: Principal = Depends(CONCESSION_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).discounts())


@router.post("/fee-discounts", summary="Create a discount", dependencies=DISC, response_model=Envelope[DiscountOut])
async def create_discount(
    body: DiscountIn, request: Request, principal: Principal = Depends(CONCESSION), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).save_discount(body), message="Discount created")


@router.get(
    "/fee-discounts/assignments/pending",
    summary="Concessions awaiting approval",
    dependencies=DISC,
    response_model=Envelope[list[DiscountAssignmentOut]],
)
async def pending_discounts(
    request: Request, principal: Principal = Depends(CONCESSION_DECIDE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).pending_discounts())


@router.post(
    "/fee-discounts/assignments/{id}/{decision}",
    summary="Approve / reject a concession (workflow fees.concession)",
    dependencies=DISC,
    response_model=Envelope[DiscountAssignmentOut],
)
async def decide_discount(
    id: uuid.UUID,
    decision: str,
    request: Request,
    principal: Principal = Depends(CONCESSION_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if decision not in ("approve", "reject"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown decision")
    return ok(
        await StructureService(db, principal, request).decide_discount(id, decision == "approve"),
        message=f"Concession {decision}d",
    )


@router.put("/fee-discounts/{id}", summary="Update a discount", dependencies=DISC, response_model=Envelope[DiscountOut])
async def update_discount(
    id: uuid.UUID,
    body: DiscountIn,
    request: Request,
    principal: Principal = Depends(CONCESSION),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).save_discount(body, id), message="Discount updated")


@router.post(
    "/fee-discounts/{id}/assign",
    summary="Assign a discount to an enrolment (workflow when it requires approval)",
    dependencies=DISC,
    response_model=Envelope[DiscountAssignmentOut],
)
async def assign_discount(
    id: uuid.UUID,
    body: DiscountAssign,
    request: Request,
    principal: Principal = Depends(CONCESSION),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).assign_discount(id, body), message="Discount assigned")


@router.get(
    "/students/{id}/discounts",
    summary="A student's discounts",
    dependencies=DISC,
    response_model=Envelope[list[DiscountAssignmentOut]],
)
async def student_discounts(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CONCESSION_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).student_discounts(id))


@router.get(
    "/fine-configurations",
    summary="Fine configuration",
    dependencies=FINES,
    response_model=Envelope[list[FineConfigOut]],
)
async def get_fines(
    request: Request, principal: Principal = Depends(STRUCT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).fines())


@router.put(
    "/fine-configurations",
    summary="Save fine configuration (one row per applies_to)",
    dependencies=FINES,
    response_model=Envelope[list[FineConfigOut]],
)
async def put_fines(
    body: list[FineConfigIn],
    request: Request,
    principal: Principal = Depends(STRUCT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StructureService(db, principal, request).save_fines(body), message="Fines saved")


# ---- dashboard / self ---------------------------------------------------------------------------------------------------
@router.get(
    "/fees/dashboard", summary="Collections today, dues, overdue, pending queues", response_model=Envelope[FeeDashboard]
)
async def dashboard(
    request: Request, principal: Principal = Depends(VIEW_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FeeReportService(db, principal, request).dashboard())


@router.get("/fees/me/dues", summary="My dues", response_model=Envelope[DuesResponse])
async def my_dues(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvoiceService(db, principal, request).my_dues())


@router.get("/fees/me/invoices", summary="My invoices", response_model=Envelope[list[InvoiceResponse]])
async def my_invoices(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvoiceService(db, principal, request).my_invoices())


@router.get("/fees/me/receipts", summary="My receipts", response_model=Envelope[list[FeePaymentOut]])
async def my_receipts(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).my_receipts())


@router.get(
    "/fees/wards/{student_id}/dues", summary="A consented ward's dues (parents)", response_model=Envelope[DuesResponse]
)
async def ward_dues(
    student_id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvoiceService(db, principal, request).ward_dues(student_id))


@router.get(
    "/fees/students/{enrollment_id}/dues",
    summary="Dues of an enrolment (counter / advisors)",
    response_model=Envelope[DuesResponse],
)
async def enrolment_dues(
    enrollment_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(STAFF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.models.students import StudentProgramEnrollment
    from app.repositories.fee_scope import enrollment_column_predicate

    visible = (
        await db.execute(
            select(StudentProgramEnrollment.id).where(
                StudentProgramEnrollment.id == enrollment_id,
                enrollment_column_predicate(principal, StudentProgramEnrollment.id, "all", "fees"),
            )
        )
    ).first()
    if visible is None and not principal.is_super_admin:
        raise APIError(404, ErrorCode.NOT_FOUND, "Enrolment not found")
    return ok(await InvoiceService(db, principal, request).dues_for(enrollment_id))


# ---- invoices -----------------------------------------------------------------------------------------------------------
@router.get(
    "/fees/invoices",
    summary="Invoices (scope = self | department | college | all)",
    response_model=Envelope[list[InvoiceResponse]],
)
async def list_invoices(
    request: Request,
    scope: str | None = None,
    payer_type: str | None = None,
    status: str | None = None,
    overdue: bool | None = None,
    batch_id: uuid.UUID | None = None,
    source_type: str | None = None,
    q: str | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await InvoiceService(db, principal, request).list_page(
        params,
        scope,
        payer_type=payer_type,
        status=status,
        overdue=overdue,
        batch_id=batch_id,
        q=q,
        source_type=source_type,
    )
    return ok(rows, pagination=page, visibility=vis)


@router.get(
    "/fees/invoices/{id}",
    summary="Invoice with items, payments and source link",
    response_model=Envelope[InvoiceResponse],
)
async def get_invoice(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvoiceService(db, principal, request).get(id))


@router.post(
    "/fees/invoices/{id}/cancel", summary="Cancel an invoice without payments", response_model=Envelope[InvoiceResponse]
)
async def cancel_invoice(
    id: uuid.UUID,
    body: InvoiceCancelRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InvoiceService(db, principal, request).cancel(id, body.reason), message="Invoice cancelled")


@router.post(
    "/fees/backfill-stubs",
    summary="Turn earlier phases' fee stubs into invoices (idempotent)",
    response_model=Envelope[dict[str, int]],
)
async def backfill(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InvoiceService(db, principal, request).backfill_stubs(), message="Stubs back-filled")


# ---- collection ---------------------------------------------------------------------------------------------------------
@router.post("/fees/collect", summary="Counter collection (Idempotency-Key)", response_model=Envelope[ReceiptResponse])
async def collect(
    body: CollectRequest,
    request: Request,
    idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(COLLECT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await PaymentService(db, principal, request).collect(body, idem)
    response = ok(out.model_dump(mode="json"), message=f"Receipt {', '.join(out.receipt_numbers)}")
    await store(request, response, db)
    return response


@router.get("/fees/payments", summary="Payment register", response_model=Envelope[list[FeePaymentOut]])
async def list_payments(
    request: Request,
    on: date | None = Query(None, alias="date"),
    date_from: date | None = None,
    date_to: date | None = None,
    mode: str | None = None,
    counter: str | None = None,
    status: str | None = None,
    scope: str | None = "all",
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page = await PaymentService(db, principal, request).list_payments(
        params, on=on, date_from=date_from, date_to=date_to, mode=mode, counter=counter, status=status, scope=scope
    )
    return ok(rows, pagination=page)


@router.get(
    "/fees/payments/cancel-requests",
    summary="Receipt cancellations awaiting approval",
    dependencies=CANCELF,
    response_model=Envelope[list[FeePaymentOut]],
)
async def cancel_requests(
    request: Request, principal: Principal = Depends(CANCEL_DECIDE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).cancel_queue())


@router.get("/fees/payments/{id}", summary="Payment", response_model=Envelope[FeePaymentOut])
async def get_payment(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).get_payment(id))


@router.get("/fees/payments/{id}/receipt.pdf", summary="Receipt PDF", response_class=Response)
async def receipt_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> Response:
    pdf, number = await PaymentService(db, principal, request).receipt_pdf(id)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{number.replace("/", "-")}.pdf"'},
    )


@router.get(
    "/fees/payments/{id}/thermal",
    summary="ESC/POS thermal payload",
    dependencies=THERMAL,
    response_model=Envelope[ThermalReceipt],
)
async def thermal(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).thermal(id))


@router.post(
    "/fees/payments/{id}/cancel-request",
    summary="Request receipt cancellation (workflow accountant → principal)",
    dependencies=CANCELF,
    response_model=Envelope[FeePaymentOut],
)
async def cancel_request(
    id: uuid.UUID,
    body: CancelReceiptRequest,
    request: Request,
    principal: Principal = Depends(CANCEL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await PaymentService(db, principal, request).cancel_request(id, body.reason), message="Cancellation requested"
    )


@router.post(
    "/fees/payments/{id}/cancel-request/{decision}",
    summary="Approve / reject a receipt cancellation (the current workflow step)",
    dependencies=CANCELF,
    response_model=Envelope[FeePaymentOut],
)
async def cancel_decide(
    id: uuid.UUID,
    decision: str,
    request: Request,
    body: RefundDecision | None = None,
    principal: Principal = Depends(CANCEL_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if decision not in ("approve", "reject"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown decision")
    return ok(
        await PaymentService(db, principal, request).decide_cancel(
            id, decision == "approve", body.comment if body else None
        ),
        message=f"Cancellation {decision}d",
    )


@router.post(
    "/fees/payments/{id}/bounce",
    summary="Cheque / DD bounce (+ bank charges, invoice reopened)",
    dependencies=CANCELF,
    response_model=Envelope[FeePaymentOut],
)
async def bounce(
    id: uuid.UUID,
    body: BounceRequest,
    request: Request,
    principal: Principal = Depends(CANCEL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).bounce(id, body), message="Marked bounced")


# ---- online / UPI -------------------------------------------------------------------------------------------------------
@router.post(
    "/fees/online/initiate",
    summary="Create a gateway order",
    dependencies=ONLINE,
    response_model=Envelope[OnlineInitiateResponse],
)
async def online_initiate(
    body: OnlineInitiateRequest,
    request: Request,
    principal: Principal = Depends(SELF_OR_COLLECT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).initiate(body), message="Order created")


@router.post(
    "/fees/online/verify",
    summary="Client-side verification (signature mandatory)",
    dependencies=ONLINE,
    response_model=Envelope[OrderStatusResponse],
)
async def online_verify(
    body: OnlineVerifyRequest,
    request: Request,
    principal: Principal = Depends(SELF_OR_COLLECT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).verify(body), message="Payment verified")


@router.get(
    "/fees/online/{order_id}/status",
    summary="Gateway order status",
    dependencies=ONLINE,
    response_model=Envelope[OrderStatusResponse],
)
async def online_status(
    order_id: str, request: Request, principal: Principal = Depends(SELF_OR_COLLECT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).order_status(order_id))


@router.post(
    "/fees/upi-qr", summary="Dynamic UPI QR for an invoice", dependencies=UPI, response_model=Envelope[UpiQrResponse]
)
async def upi_qr(
    body: UpiQrRequest,
    request: Request,
    principal: Principal = Depends(SELF_OR_COLLECT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).upi_qr(body))


@router.get(
    "/fees/upi-qr/{ref}/status",
    summary="UPI QR status (polled)",
    dependencies=UPI,
    response_model=Envelope[OrderStatusResponse],
)
async def upi_status(
    ref: str, request: Request, principal: Principal = Depends(SELF_OR_COLLECT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).upi_status(ref))


@public_router.post(
    "/webhooks/payments/{provider}",
    summary="Gateway webhook (signature verified; tenant from ?institution=)",
    response_model=Envelope[dict[str, Any]],
)
async def payment_webhook(
    provider: str,
    request: Request,
    institution: str | None = Query(None, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    import json

    from app.api.v1.endpoints.admissions import _resolve

    inst = await _resolve(request, db, institution, "fees.online_payment")
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except ValueError as exc:
        raise APIError(422, ErrorCode.VALIDATION, "Body is not JSON") from exc
    sig = request.headers.get("X-Razorpay-Signature") or request.headers.get("X-Signature")
    out = await PaymentService(db, None, request, inst.id).webhook(provider, raw, sig, payload)
    return ok(out, message="Webhook processed")


# ---- offline / reconciliation -------------------------------------------------------------------------------------------
@router.post(
    "/fees/offline/declare",
    summary="Declare an NEFT / challan / DD payment with UTR",
    dependencies=OFFLINE,
    response_model=Envelope[FeePaymentOut],
)
async def declare(
    body: OfflineDeclare,
    request: Request,
    principal: Principal = Depends(RECONCILE_OR_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await PaymentService(db, principal, request).declare(body), message="Payment declared — pending reconciliation"
    )


@router.post(
    "/fees/reconcile/upload",
    status_code=202,
    summary="Bank statement rows / CSV (job; dry_run inline)",
    dependencies=OFFLINE,
    response_model=Envelope[ReconcileSummary],
)
async def reconcile_upload(
    request: Request,
    body: ReconcileUpload | None = None,
    file: UploadFile | None = File(None),
    principal: Principal = Depends(RECONCILE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = PaymentService(db, principal, request)
    text = None
    if file is not None:
        from app.services.file_service import FileService

        raw = await file.read()
        saved = await FileService(db).save(
            raw,
            "fees/statements",
            ("text/csv", "text/plain", "application/vnd.ms-excel"),
            institution_id=svc.inst,
            filename=file.filename or "statement.csv",
        )
        text = raw.decode("utf-8-sig", errors="replace")
        url = saved.url if hasattr(saved, "url") else None
    else:
        url = body.file_url if body else None
    rows = svc.parse_statement(text) if text is not None else list(body.rows or []) if body else []
    if body and body.dry_run:
        return ok(await svc.reconcile_rows(rows, url, dry_run=True), message="Preview")
    from app.core.jobs import enqueue

    job = await enqueue(
        db, principal, "fees.reconcile_upload", {"rows": [r.model_dump(mode="json") for r in rows], "file_url": url}
    )
    return _queued({"job_id": str(job.id), "rows": len(rows)}, "Statement queued")


@router.get(
    "/fees/reconcile",
    summary="Statement rows (status = unmatched | matched | ignored) with proposed matches",
    dependencies=OFFLINE,
    response_model=Envelope[list[ReconcileRowOut]],
)
async def reconcile_list(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(RECONCILE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).reconcile_list(status))


@router.post(
    "/fees/reconcile/{id}/match",
    summary="Confirm a match (→ reconciled)",
    dependencies=OFFLINE,
    response_model=Envelope[ReconcileRowOut],
)
async def reconcile_match(
    id: uuid.UUID,
    body: ReconcileMatch,
    request: Request,
    principal: Principal = Depends(RECONCILE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await PaymentService(db, principal, request).reconcile_match(id, body.payment_id, body.invoice_id),
        message="Reconciled",
    )


@router.post(
    "/fees/reconcile/{id}/ignore",
    summary="Ignore a statement row",
    dependencies=OFFLINE,
    response_model=Envelope[ReconcileRowOut],
)
async def reconcile_ignore(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECONCILE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).reconcile_ignore(id), message="Ignored")


# ---- day-book -----------------------------------------------------------------------------------------------------------
@router.get(
    "/fees/day-book", summary="Day-book by counter / collector / mode", response_model=Envelope[DayBookResponse]
)
async def day_book(
    request: Request,
    on: date | None = Query(None, alias="date"),
    counter: str | None = None,
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = PaymentService(db, principal, request)
    return ok(await svc.day_book(on or await svc.today(), counter))


@router.post(
    "/fees/day-book/close", summary="Close the day / record the deposit", response_model=Envelope[DayBookResponse]
)
async def day_book_close(
    body: DayBookClose, request: Request, principal: Principal = Depends(COLLECT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PaymentService(db, principal, request).close_day(body), message="Day closed")


@router.get("/fees/day-book/export", summary="Cash-bank register CSV", response_class=Response)
async def day_book_export(
    request: Request,
    date_from: date,
    date_to: date,
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data = await PaymentService(db, principal, request).day_book_csv(date_from, date_to)
    return Response(
        data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="day-book-{date_from}-{date_to}.csv"'},
    )


# ---- refunds ------------------------------------------------------------------------------------------------------------
@router.get(
    "/fees/refunds/me", summary="My refunds", dependencies=REFUNDS, response_model=Envelope[list[RefundResponse]]
)
async def my_refunds(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RefundService(db, principal, request).mine())


@router.get(
    "/fees/refunds", summary="Refund queue", dependencies=REFUNDS, response_model=Envelope[list[RefundResponse]]
)
async def list_refunds(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(REFUND_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RefundService(db, principal, request).queue(status))


@router.post(
    "/fees/refunds",
    summary="Request a refund (workflow fees.refund)",
    dependencies=REFUNDS,
    response_model=Envelope[RefundResponse],
)
async def create_refund(
    body: RefundCreate,
    request: Request,
    principal: Principal = Depends(REFUND_REQUEST),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RefundService(db, principal, request).submit(body), message="Refund requested")


@router.post(
    "/fees/refunds/{id}/approve",
    summary="Approve (current workflow step)",
    dependencies=REFUNDS,
    response_model=Envelope[RefundResponse],
)
async def approve_refund(
    id: uuid.UUID,
    request: Request,
    body: RefundDecision | None = None,
    principal: Principal = Depends(REFUND_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RefundService(db, principal, request).decide(id, True, body.comment if body else None),
        message="Refund approved",
    )


@router.post(
    "/fees/refunds/{id}/reject", summary="Reject", dependencies=REFUNDS, response_model=Envelope[RefundResponse]
)
async def reject_refund(
    id: uuid.UUID,
    request: Request,
    body: RefundDecision | None = None,
    principal: Principal = Depends(REFUND_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RefundService(db, principal, request).decide(id, False, body.comment if body else None),
        message="Refund rejected",
    )


@router.post(
    "/fees/refunds/{id}/process",
    summary="Process an approved refund",
    dependencies=REFUNDS,
    response_model=Envelope[RefundResponse],
)
async def process_refund(
    id: uuid.UUID,
    body: RefundProcess,
    request: Request,
    principal: Principal = Depends(REFUND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RefundService(db, principal, request).process(id, body), message="Refund processed")


# ---- reports ------------------------------------------------------------------------------------------------------------
@router.post(
    "/fees/accounting-export",
    status_code=202,
    summary="Tally XML / CSV vouchers (job)",
    dependencies=ACCEXP,
    response_model=Envelope[dict[str, Any]],
)
async def accounting_export(
    body: AccountingExportRequest,
    request: Request,
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.features import is_enabled
    from app.core.jobs import enqueue

    if await is_enabled(principal.institution_id, "accounting.core"):
        # Phase 23: the accounting module owns voucher exports (same job id format)
        from app.schemas.accounting import ExportRequest
        from app.services.accounting.finance_service import FinanceService

        e = await FinanceService(db, principal, request).request_export(
            ExportRequest(
                target="tally" if body.format == "tally_xml" else "csv",
                period_from=body.date_from,
                period_to=body.date_to,
            )
        )
        return _queued({"job_id": str(e.job_id), "export_id": str(e.id)}, "Accounting export queued")
    job = await enqueue(db, principal, "fees.accounting_export", body.model_dump(mode="json"))
    return _queued({"job_id": str(job.id)}, "Accounting export queued")


@router.get(
    "/fees/reports/{report}",
    summary="collection | dues | defaulters | scholarships | refunds (format=csv → job)",
    response_model=Envelope[FeeReport],
)
async def report(
    report: str,
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    group_by: str | None = None,
    batch_id: uuid.UUID | None = None,
    batch_year: int | None = None,
    format: str | None = None,
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    params = {
        "date_from": date_from,
        "date_to": date_to,
        "group_by": group_by,
        "batch_id": batch_id,
        "batch_year": batch_year,
    }
    if format == "csv":
        from app.core.jobs import enqueue
        from app.services.reports.report_service import alias_params  # Phase 36: alias of POST /reports/run

        legacy = {
            "from": date_from,
            "to": date_to,
            "group_by": group_by,
            "batch_id": batch_id,
            "batch_year": batch_year,
        }
        job = await enqueue(
            db, principal, "report.run", await alias_params(db, principal, f"fees.{report}", legacy, "csv")
        )
        return _queued({"job_id": str(job.id)}, "Export queued")
    return ok(await FeeReportService(db, principal, request).run(report, params))


__all__ = ["is_enabled", "public_router", "router"]
