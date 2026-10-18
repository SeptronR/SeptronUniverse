"""No-dues clearance — Prompts/12 §12.8 (router included with ``feature_required("fees.no_dues")``).

``GET /no-dues?scope=department`` lists the requests carrying a sign-off of an office the caller owns (librarian →
library, warden → hostel, HOD → department / lab, accountant → accounts); a sign-off outside the caller's office →
403.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.no_dues import NoDuesCreate, NoDuesResponse, SignoffRequest
from app.services.fees.no_dues_service import NoDuesService
from app.utils.response import ok

router = APIRouter(tags=["no-dues"])

N = "no_dues"
REQUEST = any_permission_required((N, "request"), (N, "manage"))
VIEW = any_permission_required((N, "view"), (N, "view_all"), (N, "approve"), (N, "request"))
APPROVE = permission_required(N, "approve")


@router.post("/no-dues", summary="Request no-dues (parallel sign-offs)", response_model=Envelope[NoDuesResponse])
async def create(
    body: NoDuesCreate, request: Request, principal: Principal = Depends(REQUEST), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NoDuesService(db, principal, request).create(body), message="No-dues requested")


@router.get("/no-dues/me", summary="My (or my ward's) requests", response_model=Envelope[list[NoDuesResponse]])
async def mine(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NoDuesService(db, principal, request).mine())


@router.get(
    "/no-dues",
    summary="Requests (scope = mine | department | all; department_key filters)",
    response_model=Envelope[list[NoDuesResponse]],
)
async def list_requests(
    request: Request,
    scope: str | None = None,
    status: str | None = None,
    department_key: str | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, vis = await NoDuesService(db, principal, request).list_requests(scope, status, department_key)
    return ok(rows, visibility=vis)


@router.get("/no-dues/{id}", summary="Request with sign-offs", response_model=Envelope[NoDuesResponse])
async def get_request(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NoDuesService(db, principal, request).get(id))


@router.get("/no-dues/{id}/certificate.pdf", summary="No-dues certificate (cleared requests)", response_class=Response)
async def certificate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> Response:
    pdf, number = await NoDuesService(db, principal, request).certificate_pdf(id)
    name = number.replace("/", "-")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename={name}.pdf"})


@router.post(
    "/no-dues/{id}/signoff",
    summary="Sign off for your office (cleared | dues_pending)",
    response_model=Envelope[NoDuesResponse],
)
async def signoff(
    id: uuid.UUID,
    body: SignoffRequest,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await NoDuesService(db, principal, request).signoff(id, body), message="Signed off")
