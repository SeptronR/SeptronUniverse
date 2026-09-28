"""Workflow engine API — Prompts/04 §04.8 (router included with ``feature_required("workflow.engine")``).

Definitions: ``settings:view`` / ``settings:manage`` (the catalogue has no ``workflow`` module). Inbox, instances,
act and cancel are open to every signed-in user and authorised by the engine / instance visibility (requester,
approvers, ``settings:manage``). Delegations add ``{workflow.delegation}``.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, authenticated, permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.workflow import (
    DelegationCreate,
    DelegationResponse,
    InboxItem,
    WorkflowActRequest,
    WorkflowCancelRequest,
    WorkflowDefinitionCreate,
    WorkflowDefinitionResponse,
    WorkflowDefinitionUpdate,
    WorkflowInstanceResponse,
)
from app.services.workflow_service import WorkflowService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(prefix="/workflow", tags=["workflow"])
DELEGATION = [feature_required("workflow.delegation")]


@router.get(
    "/definitions",
    summary="Workflow definitions (latest version per key)",
    response_model=Envelope[list[WorkflowDefinitionResponse]],
)
async def definitions(
    request: Request,
    module: str | None = Query(default=None, max_length=60),
    principal: Principal = Depends(permission_required("settings", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).definitions(module))


@router.post(
    "/definitions",
    status_code=201,
    summary="Create a workflow definition",
    response_model=Envelope[WorkflowDefinitionResponse],
)
async def create_definition(
    body: WorkflowDefinitionCreate,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).create_definition(body), message="Workflow created")


@router.get("/definitions/{id}", summary="Workflow definition", response_model=Envelope[WorkflowDefinitionResponse])
async def definition(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).definition(id))


@router.put(
    "/definitions/{id}", summary="Edit (creates a new version)", response_model=Envelope[WorkflowDefinitionResponse]
)
async def update_definition(
    id: uuid.UUID,
    body: WorkflowDefinitionUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).update_definition(id, body), message="New version saved")


@router.get(
    "/definitions/{id}/versions",
    summary="Every version of the definition's key",
    response_model=Envelope[list[WorkflowDefinitionResponse]],
)
async def definition_versions(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).definition_versions(id))


@router.post(
    "/definitions/{id}/versions",
    status_code=201,
    summary="Save a new version",
    response_model=Envelope[WorkflowDefinitionResponse],
)
async def new_version(
    id: uuid.UUID,
    body: WorkflowDefinitionUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).update_definition(id, body), message="New version saved")


@router.get("/inbox", summary="My pending approvals", response_model=Envelope[list[InboxItem]])
async def inbox(
    request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    items = await WorkflowService(db, principal, request).inbox()
    return ok(items, extra={"count": len(items)})


@router.get(
    "/instances", summary="Workflow instances I can see", response_model=Envelope[list[WorkflowInstanceResponse]]
)
async def instances(
    request: Request,
    params: PageParams = Depends(page_params),
    entity_type: str | None = Query(default=None, max_length=60),
    entity_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(pending|approved|rejected|cancelled|escalated)$"),
    mine: bool = False,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await WorkflowService(db, principal, request).instances(
        params, entity_type, entity_id, status, mine
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get(
    "/instances/{id}",
    summary="Workflow instance with its step timeline",
    response_model=Envelope[WorkflowInstanceResponse],
)
async def instance(
    id: uuid.UUID, request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).instance(id))


@router.post(
    "/instances/{id}/act",
    summary="Approve / reject / delegate the current step",
    response_model=Envelope[WorkflowInstanceResponse],
)
async def act(
    id: uuid.UUID,
    body: WorkflowActRequest,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).act(id, body), message=f"{body.decision.title()}d")


@router.post(
    "/instances/{id}/cancel",
    summary="Requester cancels while pending",
    response_model=Envelope[WorkflowInstanceResponse],
)
async def cancel(
    id: uuid.UUID,
    request: Request,
    body: WorkflowCancelRequest | None = None,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await WorkflowService(db, principal, request).cancel(id, body.reason if body else None), message="Cancelled"
    )


@router.get(
    "/delegations",
    summary="My delegations (given and received)",
    dependencies=DELEGATION,
    response_model=Envelope[list[DelegationResponse]],
)
async def delegations(
    request: Request,
    all: bool = False,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).delegations(all))


@router.post(
    "/delegations",
    status_code=201,
    summary="Delegate my approvals",
    dependencies=DELEGATION,
    response_model=Envelope[DelegationResponse],
)
async def create_delegation(
    body: DelegationCreate,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkflowService(db, principal, request).create_delegation(body), message="Delegation saved")


@router.delete(
    "/delegations/{id}", summary="Revoke a delegation", dependencies=DELEGATION, response_model=Envelope[None]
)
async def delete_delegation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await WorkflowService(db, principal, request).delete_delegation(id)
    return ok(None, message="Delegation revoked")
