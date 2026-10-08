"""Credit transfers — Prompts/07 §07.8 (router included with ``feature_required("academics.credit_transfer_mooc")``).

``POST /credit-transfers`` (student; the office may pass ``student_id``) starts the ``students.credit_transfer``
workflow; ``verify`` (HOD of the student's department, step 1) maps an equivalent course, ``approve`` (registrar,
step 2) completes it, ``reject`` closes it at either step. Approved transfers become results in Phase 15.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.students import CreditTransferSource, CreditTransferStatus
from app.schemas.common import Envelope
from app.schemas.students import CreditTransferCreate, CreditTransferDecision, CreditTransferResponse
from app.services.credit_transfer_service import CreditTransferService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["students"])

SCOPE = Query(default=None, pattern="^(self|own|mine|department|faculty|college|all)$")
CT_READ = any_permission_required(
    ("credit_transfers", "view"),
    ("credit_transfers", "view_all"),
    ("credit_transfers", "verify"),
    ("credit_transfers", "approve"),
)


@router.get(
    "/credit-transfers",
    summary="Credit transfers (verification queue / visible students)",
    response_model=Envelope[list[CreditTransferResponse]],
)
async def list_credit_transfers(
    request: Request,
    params: PageParams = Depends(page_params),
    status: CreditTransferStatus | None = None,
    source: CreditTransferSource | None = None,
    department_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    scope: str | None = SCOPE,
    principal: Principal = Depends(CT_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await CreditTransferService(db, principal, request).list_page(
        params,
        status=status.value if status else None,
        source=source.value if source else None,
        department_id=department_id,
        q=q,
        scope=scope,
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get(
    "/credit-transfers/me", summary="My credit transfers", response_model=Envelope[list[CreditTransferResponse]]
)
async def my_credit_transfers(
    request: Request,
    principal: Principal = Depends(permission_required("credit_transfers", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CreditTransferService(db, principal, request).mine())


@router.get(
    "/students/{id}/credit-transfers",
    summary="A student's credit transfers",
    response_model=Envelope[list[CreditTransferResponse]],
)
async def student_credit_transfers(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CT_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CreditTransferService(db, principal, request).for_student(id))


@router.post(
    "/credit-transfers",
    status_code=201,
    summary="Submit a credit transfer (MOOC cap enforced; workflow students.credit_transfer)",
    response_model=Envelope[CreditTransferResponse],
)
async def create_credit_transfer(
    body: CreditTransferCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(
        any_permission_required(("credit_transfers", "create"), ("credit_transfers", "approve"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await CreditTransferService(db, principal, request).create(body), message="Credit transfer submitted")
    await store(request, response, db, 201)
    return response


@router.post(
    "/credit-transfers/{id}/certificate",
    summary="Attach the certificate (PDF / image)",
    response_model=Envelope[CreditTransferResponse],
)
async def attach_certificate(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(
        any_permission_required(("credit_transfers", "create"), ("credit_transfers", "verify"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await CreditTransferService(db, principal, request).attach_certificate(id, file), message="Certificate attached"
    )


@router.post(
    "/credit-transfers/{id}/verify",
    summary="Department verification (equivalent course / basket)",
    response_model=Envelope[CreditTransferResponse],
)
async def verify_credit_transfer(
    id: uuid.UUID,
    body: CreditTransferDecision,
    request: Request,
    principal: Principal = Depends(permission_required("credit_transfers", "verify")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CreditTransferService(db, principal, request).decide(id, "verify", body), message="Verified")


@router.post(
    "/credit-transfers/{id}/approve", summary="Registrar approval", response_model=Envelope[CreditTransferResponse]
)
async def approve_credit_transfer(
    id: uuid.UUID,
    request: Request,
    body: CreditTransferDecision | None = None,
    principal: Principal = Depends(permission_required("credit_transfers", "approve")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await CreditTransferService(db, principal, request).decide(id, "approve", body or CreditTransferDecision())
    return ok(out, message="Approved")


@router.post(
    "/credit-transfers/{id}/reject", summary="Reject at either step", response_model=Envelope[CreditTransferResponse]
)
async def reject_credit_transfer(
    id: uuid.UUID,
    request: Request,
    body: CreditTransferDecision | None = None,
    principal: Principal = Depends(
        any_permission_required(("credit_transfers", "verify"), ("credit_transfers", "approve"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await CreditTransferService(db, principal, request).decide(id, "reject", body or CreditTransferDecision())
    return ok(out, message="Rejected")
