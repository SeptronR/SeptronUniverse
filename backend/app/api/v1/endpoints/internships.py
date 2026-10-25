"""Internships — Prompts/28 §28.8 {placement.internships}: records (student / officer), NOC letter (Phase 26), mentor /
department evaluation (marks → Phase 13 internal mark for the mapped course), PPO from an internship, my list and the
ScopeTabs list. Ownership (self / wards / department / course faculty) is narrowed by the service.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.placement import (
    InternshipEvaluation,
    InternshipIn,
    InternshipNocRequest,
    InternshipOut,
    InternshipUpdate,
    PlcOfferCreate,
    PlcOfferOut,
)
from app.services.placement.internship_service import InternshipService
from app.utils.response import ok

router = APIRouter(tags=["internships"])

P = "placement"
READ = any_permission_required((P, "self"), (P, "wards"), (P, "manage"), (P, "view_all"), (P, "evaluate"))
WRITE = any_permission_required((P, "self"), (P, "manage"))
SELF = any_permission_required((P, "self"), (P, "wards"))
EVALUATE = any_permission_required((P, "evaluate"), (P, "manage"))
STAFF = any_permission_required((P, "manage"), (P, "view_all"), (P, "evaluate"))
OFFER = any_permission_required((P, "offer_manage"), (P, "manage"))

FEAT = [feature_required("placement.core"), feature_required("placement.internships")]


@router.get(
    "/internships", summary="Internships (ScopeTabs)", response_model=Envelope[list[InternshipOut]], dependencies=FEAT
)
async def internships(
    request: Request,
    department_id: uuid.UUID | None = None,
    status: str | None = None,
    scope: str | None = None,
    principal: Principal = Depends(STAFF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = InternshipService(db, principal, request)
    res = ok(await svc.list_internships(department_id, status, scope))
    res["meta"]["visibility"] = svc.visibility(self_tab=False, own_tab=True)
    return res


@router.post(
    "/internships",
    status_code=201,
    summary="Record an internship",
    response_model=Envelope[InternshipOut],
    dependencies=FEAT,
)
async def create(
    body: InternshipIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InternshipService(db, principal, request).create(body), message="Created")


@router.get(
    "/internships/me", summary="My / ward internships", response_model=Envelope[list[InternshipOut]], dependencies=FEAT
)
async def mine(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InternshipService(db, principal, request).mine())


@router.get("/internships/{id}", summary="Internship", response_model=Envelope[InternshipOut], dependencies=FEAT)
async def get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await InternshipService(db, principal, request).get(id))


@router.put("/internships/{id}", summary="Update internship", response_model=Envelope[InternshipOut], dependencies=FEAT)
async def update(
    id: uuid.UUID,
    body: InternshipUpdate,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InternshipService(db, principal, request).update(id, body))


@router.post(
    "/internships/{id}/noc",
    summary="Request / issue the NOC letter",
    response_model=Envelope[InternshipOut],
    dependencies=FEAT,
)
async def noc(
    id: uuid.UUID,
    body: InternshipNocRequest,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InternshipService(db, principal, request).noc(id, body), message="NOC requested")


@router.post(
    "/internships/{id}/evaluate",
    summary="Evaluate (rubric → marks)",
    response_model=Envelope[InternshipOut],
    dependencies=FEAT,
)
async def evaluate(
    id: uuid.UUID,
    body: InternshipEvaluation,
    request: Request,
    principal: Principal = Depends(EVALUATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InternshipService(db, principal, request).evaluate(id, body))


@router.post(
    "/internships/{id}/ppo",
    status_code=201,
    summary="Pre-placement offer from the internship",
    response_model=Envelope[PlcOfferOut],
    dependencies=FEAT,
)
async def ppo(
    id: uuid.UUID,
    body: PlcOfferCreate,
    request: Request,
    principal: Principal = Depends(OFFER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InternshipService(db, principal, request).ppo(id, body), message="PPO offered")
