"""Tenant billing — Prompts/38 §38.8 ``/billing/*`` (institution side; RLS tenant session).

Reads need ``settings:view`` (the subscription card, invoices, usage vs limits); paying and the tenant export are the
institution admin's (``settings:manage`` + the ``institution_admin`` role, checked in the services; the export also
needs ``data.export_portability``). College admins hold ``settings:view`` in their college only and are refused the
institution-wide billing data (403).
"""

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.saas import (
    InvoiceOut,
    InvoicePayOut,
    InvoicePayRequest,
    JobAccepted,
    PlanOut,
    SubscriptionOut,
    TenantExportRequest,
    TicketCreate,
    TicketOut,
    UsageOut,
)
from app.services.saas.institution_admin_service import InstitutionAdminService
from app.services.saas.subscription_service import SubscriptionService
from app.services.saas.support_service import SupportService
from app.services.saas.usage_service import UsageService
from app.utils.response import ok

router = APIRouter(prefix="/billing", tags=["billing"])


def _institution_admin(principal: Principal) -> None:
    if not principal.is_super_admin and not any(t == "institution" for t, _ in principal.scopes):
        raise APIError(
            403,
            ErrorCode.PERMISSION_DENIED,
            "Billing is managed by the institution admin",
            {"reason": "institution_scope"},
        )


@router.get(
    "/subscription", summary="Own subscription, invoices and usage vs limits", response_model=Envelope[SubscriptionOut]
)
async def subscription(
    request: Request,
    principal: Principal = Depends(permission_required("settings", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _institution_admin(principal)
    return ok(await SubscriptionService(db, principal, request).subscription())


@router.get("/plans", summary="Plan comparison (active plans)", response_model=Envelope[list[PlanOut]])
async def plans(
    principal: Principal = Depends(permission_required("settings", "view")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubscriptionService(db, principal).plans(public=True))


@router.get("/invoices", summary="Own invoices", response_model=Envelope[list[InvoiceOut]])
async def invoices(
    request: Request,
    principal: Principal = Depends(permission_required("settings", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _institution_admin(principal)
    return ok(await SubscriptionService(db, principal, request).invoices())


@router.get("/invoices/{number:path}.pdf", summary="Invoice PDF (platform letterhead, own GSTIN)")
async def invoice_pdf(
    number: str,
    principal: Principal = Depends(permission_required("settings", "view")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _institution_admin(principal)
    pdf = await SubscriptionService(db, principal).invoice_pdf(number)
    name = number.replace("/", "-")
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'}
    )


@router.post(
    "/invoices/{number:path}/pay",
    summary="Pay an invoice online (platform gateway order)",
    response_model=Envelope[InvoicePayOut],
)
async def pay(
    number: str,
    request: Request,
    body: InvoicePayRequest | None = None,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _institution_admin(principal)
    return ok(
        await SubscriptionService(db, principal, request).pay(number, body or InvoicePayRequest()),
        message="Payment started",
    )


@router.get("/usage", summary="Own usage by month (cost, caps, overage)", response_model=Envelope[UsageOut])
async def usage(
    request: Request,
    from_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    to_month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(permission_required("settings", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _institution_admin(principal)
    return ok(await UsageService(db, principal, request).months(None, from_month, to_month))


@router.post(
    "/export",
    status_code=202,
    summary="Tenant data export (job; encrypted zip)",
    dependencies=[feature_required("data.export_portability")],
    response_model=Envelope[JobAccepted],
)
async def export(
    body: TenantExportRequest,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _institution_admin(principal)
    return ok(
        await InstitutionAdminService(db, principal, request).request_export(
            principal.institution_id, body, tenant=True
        ),
        message="Export queued",
    )


@router.post(
    "/upgrade-request",
    status_code=201,
    summary="Ask for a plan change (opens a billing support ticket)",
    response_model=Envelope[TicketOut],
)
async def upgrade_request(
    request: Request,
    plan_code: str = Query(max_length=30),
    note: str | None = Query(default=None, max_length=2000),
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _institution_admin(principal)
    body = TicketCreate(
        subject=f"Plan change request: {plan_code}",
        description=note or f"Please move us to the {plan_code} plan.",
        priority="normal",
        category="billing",
        module="billing",
    )
    return ok(await SupportService(db, principal, request).create(body), message="Request sent")
