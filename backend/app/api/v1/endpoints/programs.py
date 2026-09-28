"""Programmes and batches — Prompts/05 §05.8 (router included with ``feature_required("academics.programs")``).

Reads are institution-wide for staff (``programs:view`` / ``batches:view`` are staff self-service grants); writes
need the module permission and are narrowed to the caller's departments inside the services.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.academics import BatchStatus, ProgramLevel, ProgramStatus
from app.schemas.academics import (
    AdvisorAssign,
    BatchCreate,
    BatchResponse,
    BatchSectionsReplace,
    BatchUpdate,
    ProgramCreate,
    ProgramResponse,
    ProgramUpdate,
)
from app.schemas.common import Envelope
from app.services.batch_service import BatchService
from app.services.program_service import ProgramService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["academics"])

SCOPE_PATTERN = "^(department|college|all)$"
PROGRAM_READ = any_permission_required(("programs", "view"), ("programs", "view_all"))
BATCH_READ = any_permission_required(("batches", "view"), ("batches", "view_all"))


# ---- programmes ------------------------------------------------------------------------------------------------------
@router.get("/programs", summary="Programmes (institution-wide)", response_model=Envelope[list[ProgramResponse]])
async def list_programs(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern=SCOPE_PATTERN),
    college_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    level: ProgramLevel | None = None,
    status: ProgramStatus | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(PROGRAM_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await ProgramService(db, principal, request).list_page(
        params,
        scope,
        college_id=college_id,
        department_id=department_id,
        level=level.value if level else None,
        status=status.value if status else None,
        q=q,
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post("/programs", status_code=201, summary="Create a programme", response_model=Envelope[ProgramResponse])
async def create_program(
    body: ProgramCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("programs", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await ProgramService(db, principal, request).create(body), message="Programme created")
    await store(request, response, db, 201)
    return response


@router.get("/programs/{id}", summary="Programme detail", response_model=Envelope[ProgramResponse])
async def get_program(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(PROGRAM_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramService(db, principal, request).get(id))


@router.put("/programs/{id}", summary="Update a programme", response_model=Envelope[ProgramResponse])
async def update_program(
    id: uuid.UUID,
    body: ProgramUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("programs", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramService(db, principal, request).update(id, body), message="Programme updated")


@router.delete("/programs/{id}", summary="Delete a programme (soft)", response_model=Envelope[None])
async def delete_program(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("programs", "delete")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await ProgramService(db, principal, request).delete(id)
    return ok(None, message="Programme deleted")


@router.post(
    "/programs/{id}/close",
    summary="Close a programme (no active batches)",
    response_model=Envelope[ProgramResponse],
)
async def close_program(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("programs", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramService(db, principal, request).close(id), message="Programme closed")


# ---- batches ---------------------------------------------------------------------------------------------------------
@router.get("/batches", summary="Batches with their sections", response_model=Envelope[list[BatchResponse]])
async def list_batches(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern=SCOPE_PATTERN),
    program_id: uuid.UUID | None = None,
    admission_year: int | None = Query(default=None, ge=1950, le=2100),
    status: BatchStatus | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(BATCH_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await BatchService(db, principal, request).list_page(
        params,
        scope,
        program_id=program_id,
        admission_year=admission_year,
        status=status.value if status else None,
        q=q,
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/batches", status_code=201, summary="Create a batch (sections A…N)", response_model=Envelope[BatchResponse]
)
async def create_batch(
    body: BatchCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("batches", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await BatchService(db, principal, request).create(body), message="Batch created")
    await store(request, response, db, 201)
    return response


@router.get("/batches/{id}", summary="Batch detail", response_model=Envelope[BatchResponse])
async def get_batch(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(BATCH_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BatchService(db, principal, request).get(id))


@router.put("/batches/{id}", summary="Update a batch", response_model=Envelope[BatchResponse])
async def update_batch(
    id: uuid.UUID,
    body: BatchUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("batches", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BatchService(db, principal, request).update(id, body), message="Batch updated")


@router.put("/batches/{id}/sections", summary="Replace the sections", response_model=Envelope[BatchResponse])
async def replace_sections(
    id: uuid.UUID,
    body: BatchSectionsReplace,
    request: Request,
    principal: Principal = Depends(permission_required("batches", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await BatchService(db, principal, request).replace_sections(id, body), message="Sections saved")


@router.put(
    "/batches/{id}/sections/{sid}/advisor",
    summary="Assign the class advisor (class_advisor @offering:<section>)",
    response_model=Envelope[BatchResponse],
)
async def assign_advisor(
    id: uuid.UUID,
    sid: uuid.UUID,
    body: AdvisorAssign,
    request: Request,
    principal: Principal = Depends(permission_required("batches", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await BatchService(db, principal, request).assign_advisor(id, sid, body), message="Class advisor assigned"
    )
