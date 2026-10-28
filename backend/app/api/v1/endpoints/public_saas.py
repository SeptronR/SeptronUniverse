"""Public SaaS routes — Prompts/38 §38.8 (Phase 40 marketing-site forms; listed in ``PUBLIC_ROUTES``).

Self-serve registration (captcha + 5 per IP per 10 minutes), its status / e-mail verification / payment, the demo
request form, the plan list for the pricing page and the platform payment-gateway webhook (provider signature
verified). All run on the platform session: the rows belong to no tenant yet.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.saas_deps import client_ip
from app.core.rate_limit import rate_limited
from app.db.session import get_platform_db
from app.schemas.common import Envelope
from app.schemas.saas import (
    DemoRequestIn,
    GatewayWebhook,
    PlanOut,
    PublicRegistrationIn,
    PublicRegistrationOut,
)
from app.services.saas.registration_service import RegistrationService
from app.services.saas.subscription_service import SubscriptionService
from app.utils.response import ok

router = APIRouter(tags=["public-saas"])


@router.get("/public/plans", summary="Active plans (pricing page)", response_model=Envelope[list[PlanOut]])
async def public_plans(db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await SubscriptionService(db, None).plans(public=True))


@router.post(
    "/public/registrations",
    status_code=201,
    summary="Self-serve registration (captcha; 5 per IP per 10 minutes)",
    dependencies=[rate_limited("registration", limit=5, window=600)],
    response_model=Envelope[PublicRegistrationOut],
)
async def register(
    body: PublicRegistrationIn, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(
        await RegistrationService(db, None, request).create(body, client_ip(request)),
        message="Check your e-mail to verify",
    )


@router.get(
    "/public/registrations/{id}/status",
    summary="Registration status and next step",
    response_model=Envelope[PublicRegistrationOut],
)
async def registration_status(id: uuid.UUID, db: AsyncSession = Depends(get_platform_db)) -> dict[str, Any]:
    return ok(await RegistrationService(db, None).status(id))


@router.post(
    "/public/registrations/{id}/verify",
    summary="Verify the e-mail (signed single-use token)",
    dependencies=[rate_limited("registration_verify", limit=20, window=600)],
    response_model=Envelope[PublicRegistrationOut],
)
async def registration_verify(
    id: uuid.UUID,
    request: Request,
    token: str = Query(min_length=10, max_length=200),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    return ok(await RegistrationService(db, None, request).verify(id, token), message="E-mail verified")


@router.post(
    "/public/registrations/{id}/pay",
    summary="Start the payment (platform gateway order)",
    dependencies=[rate_limited("registration_pay", limit=10, window=600)],
    response_model=Envelope[dict[str, Any]],
)
async def registration_pay(
    id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await RegistrationService(db, None, request).pay(id))


@router.post(
    "/public/demo-requests",
    status_code=201,
    summary="Request a demo (captcha)",
    dependencies=[rate_limited("demo_request", limit=5, window=600)],
    response_model=Envelope[dict[str, Any]],
)
async def demo_request(
    body: DemoRequestIn, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    out = await RegistrationService(db, None, request).demo_create(body, client_ip(request))
    return ok({"id": str(out.id), "status": out.status}, message="Thanks — our team will contact you")


@router.post(
    "/public/billing/webhook",
    summary="Platform payment-gateway webhook (signature verified)",
    response_model=Envelope[dict[str, Any]],
)
async def billing_webhook(
    body: GatewayWebhook, request: Request, db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    raw = await request.body()
    return ok(
        await SubscriptionService(db, None, request).gateway_webhook(
            body.order_id,
            body.payment_ref,
            body.status,
            raw,
            request.headers.get("x-signature") or body.signature or "",
        )
    )
