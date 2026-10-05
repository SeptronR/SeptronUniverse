"""Payroll, salary structures, statutory registers, Form 16 and loans — Prompts/06 §06.8 (router included with
``feature_required("hr.payroll")``; registers / Form 16 add {hr.statutory_payroll}, loans {hr.loans_advances}).
``/payroll/generate`` enqueues the job ``payroll.generate``; ``mark-paid`` enqueues ``payroll.payslips``."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.hr import LoanStatus, PayrollStatus
from app.schemas.common import Envelope
from app.schemas.payroll import (
    Form16Data,
    LoanIn,
    LoanOut,
    PayrollBulkAction,
    PayrollBulkResult,
    PayrollComponentIn,
    PayrollComponentOut,
    PayrollGenerateRequest,
    PayrollMarkPaid,
    PayrollResponse,
    RegisterResponse,
    SalaryStructureIn,
    SalaryStructureOut,
)
from app.services.payroll_service import PayrollService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["hr"])

PAY_READ = any_permission_required(("payroll", "view"), ("payroll", "view_all"))
STATUTORY = [feature_required("hr.statutory_payroll")]
LOANS = [feature_required("hr.loans_advances")]


# ---- components -----------------------------------------------------------------------------------------------------
@router.get("/payroll/components", summary="Payroll components", response_model=Envelope[list[PayrollComponentOut]])
async def list_components(
    request: Request,
    include_inactive: bool = False,
    principal: Principal = Depends(
        any_permission_required(("payroll", "statutory"), ("payroll", "view_all"), ("payroll", "view"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).list_components(include_inactive))


@router.post(
    "/payroll/components",
    status_code=201,
    summary="Create a payroll component",
    response_model=Envelope[PayrollComponentOut],
)
async def create_component(
    body: PayrollComponentIn,
    request: Request,
    principal: Principal = Depends(permission_required("payroll", "statutory")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).create_component(body), message="Component created")


@router.put(
    "/payroll/components/{id}", summary="Update a payroll component", response_model=Envelope[PayrollComponentOut]
)
async def update_component(
    id: uuid.UUID,
    body: PayrollComponentIn,
    request: Request,
    principal: Principal = Depends(permission_required("payroll", "statutory")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).update_component(id, body))


# ---- salary structures ----------------------------------------------------------------------------------------------
@router.get(
    "/staff/{id}/salary-structures",
    summary="Salary structures of a member",
    response_model=Envelope[list[SalaryStructureOut]],
)
async def list_structures(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required(("payroll", "manage"), ("payroll", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).list_structures(id))


@router.post(
    "/staff/{id}/salary-structures",
    status_code=201,
    summary="New salary structure (increment / revision; past dates produce arrears)",
    response_model=Envelope[SalaryStructureOut],
)
async def add_structure(
    id: uuid.UUID,
    body: SalaryStructureIn,
    request: Request,
    principal: Principal = Depends(permission_required("payroll", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).add_structure(id, body), message="Salary structure saved")


# ---- runs -----------------------------------------------------------------------------------------------------------
@router.post(
    "/payroll/generate",
    status_code=202,
    summary="Generate payroll for a month (job)",
    response_model=Envelope[dict[str, Any]],
)
async def generate_payroll(
    body: PayrollGenerateRequest,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("payroll", "generate")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(
        await PayrollService(db, principal, request).enqueue_generate(body), message="Payroll generation queued"
    )
    await store(request, response, db, 202)
    return response


@router.get(
    "/payroll",
    summary="Payroll runs (self / team / all per visibility)",
    response_model=Envelope[list[PayrollResponse]],
)
async def list_payroll(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern="^(self|team|department|faculty|college|all)$"),
    month: int | None = Query(default=None, ge=1, le=12),
    year: int | None = Query(default=None, ge=2000, le=2100),
    status: PayrollStatus | None = None,
    staff_id: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(PAY_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await PayrollService(db, principal, request).list_page(
        params,
        scope,
        month=month,
        year=year,
        status=status.value if status else None,
        staff_id=staff_id,
        college_id=college_id,
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get("/payroll/me", summary="My payslips (approved / paid)", response_model=Envelope[list[PayrollResponse]])
async def my_payslips(
    request: Request,
    year: int | None = Query(default=None, ge=2000, le=2100),
    principal: Principal = Depends(permission_required("payroll", "self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).me(year))


@router.get(
    "/payroll/registers/{kind}",
    summary="Statutory register (pf | esi | pt | tds)",
    response_model=Envelope[RegisterResponse],
    dependencies=STATUTORY,
)
async def register(
    kind: str,
    request: Request,
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    principal: Principal = Depends(permission_required("payroll", "statutory")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).register(kind, month, year))


@router.get(
    "/payroll/form16",
    summary="Form 16 data (financial year starting April of ?year)",
    response_model=Envelope[Form16Data],
    dependencies=STATUTORY,
)
async def form16(
    request: Request,
    year: int = Query(ge=2000, le=2100),
    staff_id: uuid.UUID | None = None,
    principal: Principal = Depends(any_permission_required(("payroll", "statutory"), ("payroll", "self"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).form16(year, staff_id))


@router.get("/payroll/bank-advice", summary="Bank advice CSV (approved / paid runs of a month)")
async def bank_advice(
    request: Request,
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    principal: Principal = Depends(permission_required("payroll", "mark_paid")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content = await PayrollService(db, principal, request).bank_advice(month, year)
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="bank-advice-{year}-{month:02d}.csv"'},
    )


@router.post("/payroll/approve", summary="Approve several draft runs", response_model=Envelope[PayrollBulkResult])
async def approve_many(
    body: PayrollBulkAction,
    request: Request,
    principal: Principal = Depends(permission_required("payroll", "approve")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.core.errors import APIError

    service = PayrollService(db, principal, request)
    done: list[uuid.UUID] = []
    failed: list[dict[str, Any]] = []
    for pid in body.ids:
        try:
            async with db.begin_nested():
                await service.approve(pid)
            done.append(pid)
        except APIError as exc:
            failed.append({"id": str(pid), "code": exc.code, "message": exc.message})
    return ok(PayrollBulkResult(succeeded=done, failed=failed), message=f"{len(done)} approved")


@router.get("/payroll/{id}", summary="Payroll run with items", response_model=Envelope[PayrollResponse])
async def get_payroll(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(
        any_permission_required(("payroll", "view"), ("payroll", "view_all"), ("payroll", "self"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).get(id))


@router.post("/payroll/{id}/approve", summary="Approve a draft run", response_model=Envelope[PayrollResponse])
async def approve_payroll(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("payroll", "approve")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).approve(id), message="Payroll approved")


@router.post(
    "/payroll/{id}/mark-paid",
    summary="Mark an approved run paid (payslip job + notification)",
    response_model=Envelope[PayrollResponse],
)
async def mark_paid(
    id: uuid.UUID,
    body: PayrollMarkPaid,
    request: Request,
    principal: Principal = Depends(permission_required("payroll", "mark_paid")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).mark_paid(id, body), message="Marked paid")


@router.get("/payroll/{id}/payslip.pdf", summary="Payslip PDF")
async def payslip_pdf(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(
        any_permission_required(("payroll", "view"), ("payroll", "view_all"), ("payroll", "self"))
    ),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content, filename = await PayrollService(db, principal, request).payslip_pdf(id)
    return Response(
        content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )


# ---- loans ----------------------------------------------------------------------------------------------------------
@router.get(
    "/loans",
    summary="Loans & advances (self / all per visibility)",
    response_model=Envelope[list[LoanOut]],
    dependencies=LOANS,
)
async def list_loans(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern="^(self|team|department|faculty|college|all)$"),
    status: LoanStatus | None = None,
    principal: Principal = Depends(
        any_permission_required(("payroll", "view_all"), ("payroll", "self"), ("payroll", "view"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await PayrollService(db, principal, request).list_loans(
        params, scope, status.value if status else None
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/loans",
    status_code=201,
    summary="Record a loan (payroll manager) or request one (self → workflow hr.loan)",
    response_model=Envelope[LoanOut],
    dependencies=LOANS,
)
async def create_loan(
    body: LoanIn,
    request: Request,
    principal: Principal = Depends(any_permission_required(("payroll", "manage"), ("payroll", "self"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).create_loan(body), message="Loan saved")


@router.post(
    "/loans/{id}/foreclose", summary="Foreclose an active loan", response_model=Envelope[LoanOut], dependencies=LOANS
)
async def foreclose_loan(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("payroll", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PayrollService(db, principal, request).foreclose(id), message="Loan foreclosed")
