"""Regulations — Prompts/05 §05.8 (router included with ``feature_required("academics.regulations")``).

``POST /regulations/{id}/approve`` accepts ``regulations:approve`` (direct approval) or ``regulations:update``
(submission to the ``regulation.approval`` workflow when ``academics.bos_approval_workflow`` is on) — the service
decides which applies; ``/activate`` needs ``regulations:publish``, ``/clone`` ``regulations:clone``.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.academics import RegulationStatus
from app.schemas.academics import (
    RegulationApproveRequest,
    RegulationApproveResponse,
    RegulationCloneRequest,
    RegulationCreate,
    RegulationResponse,
    RegulationUpdate,
    RulesEffectiveResponse,
    RulesHelpItem,
    rules_help,
)
from app.schemas.common import Envelope
from app.schemas.curriculum import RegulationDiffResponse
from app.services.regulation_service import RegulationService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["academics"])

REG_READ = any_permission_required(("regulations", "view"), ("regulations", "view_all"))


@router.get("/regulations", summary="Regulations (status chips)", response_model=Envelope[list[RegulationResponse]])
async def list_regulations(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern="^(college|all)$"),
    status: RegulationStatus | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(REG_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await RegulationService(db, principal, request).list_page(
        params, scope, status.value if status else None, q
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get(
    "/regulations/rules-schema",
    summary="Every rules key with its default and help text (Rules tab)",
    response_model=Envelope[list[RulesHelpItem]],
)
async def rules_schema(principal: Principal = Depends(REG_READ)) -> dict[str, Any]:
    return ok(rules_help())


@router.post(
    "/regulations", status_code=201, summary="Create a draft regulation", response_model=Envelope[RegulationResponse]
)
async def create_regulation(
    body: RegulationCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("regulations", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await RegulationService(db, principal, request).create(body), message="Regulation created")
    await store(request, response, db, 201)
    return response


@router.get("/regulations/{id}", summary="Regulation detail", response_model=Envelope[RegulationResponse])
async def get_regulation(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(REG_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegulationService(db, principal, request).get(id))


@router.put(
    "/regulations/{id}", summary="Update (rules locked after approval)", response_model=Envelope[RegulationResponse]
)
async def update_regulation(
    id: uuid.UUID,
    body: RegulationUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("regulations", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegulationService(db, principal, request).update(id, body), message="Regulation saved")


@router.post(
    "/regulations/{id}/approve",
    summary="Approve (or submit to the BoS workflow)",
    response_model=Envelope[RegulationApproveResponse],
)
async def approve_regulation(
    id: uuid.UUID,
    request: Request,
    body: RegulationApproveRequest | None = None,
    principal: Principal = Depends(any_permission_required(("regulations", "approve"), ("regulations", "update"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await RegulationService(db, principal, request).approve(id, body or RegulationApproveRequest())
    return ok(result, message="Submitted for approval" if result.pending_workflow else "Regulation approved")


@router.post(
    "/regulations/{id}/activate",
    summary="Activate (locks courses & structure)",
    response_model=Envelope[RegulationResponse],
)
async def activate_regulation(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("regulations", "publish")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegulationService(db, principal, request).activate(id), message="Regulation activated")


@router.post(
    "/regulations/{id}/clone",
    status_code=201,
    summary="Deep-clone into a new draft",
    response_model=Envelope[RegulationResponse],
)
async def clone_regulation(
    id: uuid.UUID,
    body: RegulationCloneRequest,
    request: Request,
    principal: Principal = Depends(permission_required("regulations", "clone")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegulationService(db, principal, request).clone(id, body), message="Regulation cloned")


@router.get(
    "/regulations/{id}/diff", summary="Diff vs the predecessor", response_model=Envelope[RegulationDiffResponse]
)
async def regulation_diff(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(REG_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegulationService(db, principal, request).diff(id))


@router.get(
    "/regulations/{id}/rules-effective",
    summary="rules ⊕ programme rules_override",
    response_model=Envelope[RulesEffectiveResponse],
)
async def rules_effective(
    id: uuid.UUID,
    request: Request,
    program_id: uuid.UUID | None = None,
    principal: Principal = Depends(permission_required("regulations", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegulationService(db, principal, request).rules_effective(id, program_id))
