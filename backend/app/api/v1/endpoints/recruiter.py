"""Recruiter portal — Prompts/28 §28.8 {placement.recruiter_portal} [placement:recruiter]: own companies, draft drives,
consented applicant fields, watermarked shortlist download (audited), rounds, results, offers pending officer
confirmation and feedback. Another company's drive is a 404 (service ownership check)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.placement import (
    PlcBulkReport,
    PlcDriveOut,
    PlcFeedbackIn,
    PlcFeedbackOut,
    PlcPendingOffer,
    PlcRoundIn,
    PlcRoundOut,
    PlcRoundResultsBulk,
    RecruiterApplicantOut,
    RecruiterDriveIn,
    RecruiterMe,
    RecruiterOfferIn,
)
from app.services.placement.recruiter_service import RecruiterService
from app.utils.response import ok

router = APIRouter(tags=["recruiter"])

RECRUITER = any_permission_required(("placement", "recruiter"))
FEAT = [feature_required("placement.core"), feature_required("placement.recruiter_portal")]


@router.get("/recruiter/me", summary="My companies", response_model=Envelope[RecruiterMe], dependencies=FEAT)
async def me(
    request: Request, principal: Principal = Depends(RECRUITER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).me())


@router.get(
    "/recruiter/drives", summary="My company drives", response_model=Envelope[list[PlcDriveOut]], dependencies=FEAT
)
async def drives(
    request: Request, principal: Principal = Depends(RECRUITER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).list_drives())


@router.post(
    "/recruiter/drives",
    status_code=201,
    summary="Post a drive (draft until published)",
    response_model=Envelope[PlcDriveOut],
    dependencies=FEAT,
)
async def create_drive(
    body: RecruiterDriveIn,
    request: Request,
    principal: Principal = Depends(RECRUITER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).create_drive(body), message="Created")


@router.put(
    "/recruiter/drives/{id}", summary="Edit a draft drive", response_model=Envelope[PlcDriveOut], dependencies=FEAT
)
async def update_drive(
    id: uuid.UUID,
    body: RecruiterDriveIn,
    request: Request,
    principal: Principal = Depends(RECRUITER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).update_drive(id, body))


@router.get(
    "/recruiter/drives/{id}/applicants",
    summary="Applicants (consented fields only)",
    response_model=Envelope[list[RecruiterApplicantOut]],
    dependencies=FEAT,
)
async def applicants(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECRUITER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).applicants(id))


@router.get("/recruiter/drives/{id}/shortlist.xlsx", summary="Shortlist (watermarked, audited)", dependencies=FEAT)
async def shortlist_xlsx(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECRUITER), db: AsyncSession = Depends(get_db)
) -> Response:
    content, name = await RecruiterService(db, principal, request).shortlist_xlsx(id)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post(
    "/recruiter/drives/{id}/rounds",
    status_code=201,
    summary="Schedule a round",
    response_model=Envelope[PlcRoundOut],
    dependencies=FEAT,
)
async def add_round(
    id: uuid.UUID,
    body: PlcRoundIn,
    request: Request,
    principal: Principal = Depends(RECRUITER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).add_round(id, body), message="Created")


@router.post(
    "/recruiter/rounds/{id}/results",
    summary="Upload round results",
    response_model=Envelope[PlcBulkReport],
    dependencies=FEAT,
)
async def round_results(
    id: uuid.UUID,
    body: PlcRoundResultsBulk,
    request: Request,
    principal: Principal = Depends(RECRUITER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).round_results(id, body))


@router.post(
    "/recruiter/drives/{id}/offers",
    status_code=202,
    summary="Submit an offer (pending officer confirmation)",
    response_model=Envelope[PlcPendingOffer],
    dependencies=FEAT,
)
async def submit_offer(
    id: uuid.UUID,
    body: RecruiterOfferIn,
    request: Request,
    principal: Principal = Depends(RECRUITER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).submit_offer(id, body), message="Submitted")


@router.post(
    "/recruiter/drives/{id}/feedback",
    status_code=201,
    summary="Feedback",
    response_model=Envelope[PlcFeedbackOut],
    dependencies=FEAT,
)
async def feedback(
    id: uuid.UUID,
    body: PlcFeedbackIn,
    request: Request,
    principal: Principal = Depends(RECRUITER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruiterService(db, principal, request).feedback(id, body), message="Saved")
