"""Fundraising — Prompts/29 §29.8 {alumni.fundraising}: campaigns (goal / progress, restricted fund, close), online
donations through the Phase 12 gateway (alumni / signed-in donors on ``/fundraising/donate``; the website form on
``/fundraising/donate/public`` with captcha — ``PUBLIC_ROUTES``; both take ``Idempotency-Key``), offline donation
records, donor pages, refunds, and {alumni.donations_80g} receipts / reissue / register / Form 10BD statement.
``/fundraising/campaigns/public`` (website) is public, tenant by institution slug. Static paths are declared before
the ``/{id}`` routes of the same prefix.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.core.rate_limit import rate_limited, verify_captcha
from app.db.session import get_db
from app.schemas.alumni import (
    AlmJobQueued,
    CampaignIn,
    CampaignOut,
    CampaignUpdate,
    DonationCreate,
    DonationOut,
    DonationRefund,
    DonorPage,
    OnlineDonateRequest,
    OnlineDonateResponse,
    Receipt80GOut,
    Receipt80GReissue,
    Register80GRow,
)
from app.schemas.common import Envelope
from app.services.alumni.fundraising_service import FundraisingService
from app.utils.response import ok

router = APIRouter(tags=["fundraising"])
public_router = APIRouter(tags=["fundraising"])

F = "fundraising"
CAMPAIGN_READ = any_permission_required(
    ("alumni", "campaign"), (F, "manage"), (F, "view"), (F, "view_all"), (F, "receipt"), ("alumni", "self")
)
CAMPAIGN_WRITE = any_permission_required(("alumni", "campaign"), (F, "manage"))
DONATE = any_permission_required(("alumni", "self"), (F, "view"), (F, "manage"))
DONATIONS = any_permission_required((F, "manage"), (F, "receipt"), (F, "view_all"), ("accounting", "view"))
RECORD = any_permission_required((F, "manage"), (F, "receipt"))
RECEIPT = any_permission_required((F, "receipt"), (F, "manage"))

FEAT = [feature_required("alumni.core"), feature_required("alumni.fundraising")]
FEAT_80G = [*FEAT, feature_required("alumni.donations_80g")]


# ---- campaigns ------------------------------------------------------------------------------------------------------------
@router.get(
    "/fundraising/campaigns", summary="Campaigns", response_model=Envelope[list[CampaignOut]], dependencies=FEAT
)
async def campaigns(
    request: Request,
    status: str | None = Query(None, pattern="^(draft|active|closed|archived)$"),
    principal: Principal = Depends(CAMPAIGN_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).list_campaigns(status))


@router.post(
    "/fundraising/campaigns",
    status_code=201,
    summary="Create campaign (restricted fund → ledger mapping)",
    response_model=Envelope[CampaignOut],
    dependencies=FEAT,
)
async def create_campaign(
    body: CampaignIn,
    request: Request,
    principal: Principal = Depends(CAMPAIGN_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).create_campaign(body), message="Created")


async def _tenant(db: AsyncSession, institution: str) -> uuid.UUID:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    for key in ("alumni.core", "alumni.fundraising"):
        if not await is_enabled(iid, key):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{key}' is not enabled", {"feature": key})
    return iid


@public_router.get(
    "/fundraising/campaigns/public",
    summary="Active public campaigns (website)",
    response_model=Envelope[list[CampaignOut]],
    dependencies=[rate_limited("fundraising_public", limit=60, window=60)],
)
async def public_campaigns(
    request: Request, institution: str = Query(min_length=2, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    iid = await _tenant(db, institution)
    return ok(await FundraisingService(db, None, request, iid).public_campaigns())


@public_router.post(
    "/fundraising/donate/public",
    status_code=201,
    summary="Donate online from the website (captcha; Idempotency-Key)",
    response_model=Envelope[OnlineDonateResponse],
    dependencies=[rate_limited("fundraising_donate_public", limit=10, window=600)],
)
async def donate_public(
    body: OnlineDonateRequest,
    request: Request,
    institution: str = Query(min_length=2, max_length=60),
    idem: str | None = Depends(idempotency_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await verify_captcha(body.captcha_token, request.client.host if request.client else None)
    iid = await _tenant(db, institution)
    response = ok(await FundraisingService(db, None, request, iid).donate_online(body, idem), message="Order created")
    await store(request, response, db, 201)
    return response


@router.get("/fundraising/campaigns/{id}", summary="Campaign", response_model=Envelope[CampaignOut], dependencies=FEAT)
async def campaign(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CAMPAIGN_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).get_campaign(id))


@router.put(
    "/fundraising/campaigns/{id}", summary="Update campaign", response_model=Envelope[CampaignOut], dependencies=FEAT
)
async def update_campaign(
    id: uuid.UUID,
    body: CampaignUpdate,
    request: Request,
    principal: Principal = Depends(CAMPAIGN_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).update_campaign(id, body))


@router.post(
    "/fundraising/campaigns/{id}/close",
    summary="Close campaign (further donations 409)",
    response_model=Envelope[CampaignOut],
    dependencies=FEAT,
)
async def close_campaign(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CAMPAIGN_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).close_campaign(id), message="Closed")


# ---- donations -------------------------------------------------------------------------------------------------------------------
@router.post(
    "/fundraising/donate",
    status_code=201,
    summary="Donate online (alumni / signed-in donor; Idempotency-Key)",
    response_model=Envelope[OnlineDonateResponse],
    dependencies=FEAT,
)
async def donate(
    body: OnlineDonateRequest,
    request: Request,
    idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(DONATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await FundraisingService(db, principal, request).donate_online(body, idem), message="Order created")
    await store(request, response, db, 201)
    return response


@router.get(
    "/fundraising/donations/me", summary="My donations", response_model=Envelope[list[DonationOut]], dependencies=FEAT
)
async def my_donations(
    request: Request, principal: Principal = Depends(DONATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).mine())


@router.get(
    "/fundraising/donations", summary="Donations", response_model=Envelope[list[DonationOut]], dependencies=FEAT
)
async def donations(
    request: Request,
    campaign_id: uuid.UUID | None = None,
    donor_type: str | None = Query(None, pattern="^(alumni|corporate|individual)$"),
    mode: str | None = Query(None, pattern="^(online|bank_transfer|cheque|cash|upi)$"),
    fy: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(DONATIONS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await FundraisingService(db, principal, request).list_donations(
            campaign_id=campaign_id, donor_type=donor_type, mode=mode, fy=fy
        )
    )


@router.post(
    "/fundraising/donations",
    status_code=201,
    summary="Record an offline donation (bank transfer / cheque / cash / UPI)",
    response_model=Envelope[DonationOut],
    dependencies=FEAT,
)
async def record(
    body: DonationCreate, request: Request, principal: Principal = Depends(RECORD), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).record_offline(body), message="Recorded")


@router.get(
    "/fundraising/donors/{donor_key}", summary="Donor page", response_model=Envelope[DonorPage], dependencies=FEAT
)
async def donor(
    donor_key: str, request: Request, principal: Principal = Depends(DONATIONS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).donor_page(donor_key))


@router.get(
    "/fundraising/80g/register",
    summary="80G register",
    response_model=Envelope[list[Register80GRow]],
    dependencies=FEAT_80G,
)
async def register_80g(
    request: Request,
    fy: str = Query(pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(RECEIPT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).register(fy))


@router.get(
    "/fundraising/80g/10bd",
    status_code=202,
    summary="Form 10BD-style statement (job → xlsx)",
    response_model=Envelope[AlmJobQueued],
    dependencies=FEAT_80G,
)
async def statement_10bd(
    fy: str = Query(pattern=r"^\d{4}-\d{2}$"),
    principal: Principal = Depends(RECEIPT),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, "fundraising.10bd_statement", {"fy": fy})
    return JSONResponse(
        status_code=202, content=ok(AlmJobQueued(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


@router.get("/fundraising/donations/{id}", summary="Donation", response_model=Envelope[DonationOut], dependencies=FEAT)
async def donation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DONATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).get_donation(id))


@router.post(
    "/fundraising/donations/{id}/refund",
    summary="Refund (audited; reverses raised amount)",
    response_model=Envelope[DonationOut],
    dependencies=FEAT,
)
async def refund(
    id: uuid.UUID,
    body: DonationRefund,
    request: Request,
    principal: Principal = Depends(CAMPAIGN_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).refund(id, body), message="Refunded")


@router.post(
    "/fundraising/donations/{id}/receipt-80g",
    summary="Issue the 80G receipt",
    response_model=Envelope[Receipt80GOut],
    dependencies=FEAT_80G,
)
async def receipt_80g(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECEIPT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).issue_receipt(id), message="Issued")


@router.post(
    "/fundraising/donations/{id}/receipt-80g/reissue",
    summary="Reissue the 80G receipt (corrections; old document superseded)",
    response_model=Envelope[Receipt80GOut],
    dependencies=FEAT_80G,
)
async def reissue_80g(
    id: uuid.UUID,
    body: Receipt80GReissue,
    request: Request,
    principal: Principal = Depends(RECEIPT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await FundraisingService(db, principal, request).reissue(id, body), message="Reissued")
