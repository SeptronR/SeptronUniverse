"""Academic years and terms — Prompts/03 §03.8 (router included with ``feature_required("core.institution")``).

Reads accept ``sessions:view`` or ``institutions:view`` (institution-wide readable); ``GET /academic-terms/current``
is open to every signed-in user. Writes: ``sessions:manage`` (``manage`` also implies ``lock`` / ``rollover`` /
``close`` for holders of the wildcard), ``sessions:lock``, ``sessions:rollover``; the ``closed`` transition
additionally checks ``sessions:close`` in the service.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, authenticated, permission_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.academic_sessions import (
    AcademicTermCreate,
    AcademicTermResponse,
    AcademicTermUpdate,
    AcademicYearCreate,
    AcademicYearResponse,
    AcademicYearUpdate,
    RolloverRequest,
    RolloverResponse,
    TermStatusChange,
)
from app.schemas.common import Envelope
from app.services.academic_session_service import AcademicSessionService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["academic-sessions"])

READ = any_permission_required(("sessions", "view"), ("institutions", "view"))


# ---- years -----------------------------------------------------------------------------------------------------------
@router.get(
    "/academic-years", summary="Academic years (with their terms)", response_model=Envelope[list[AcademicYearResponse]]
)
async def list_years(
    request: Request,
    params: PageParams = Depends(page_params),
    college_id: uuid.UUID | None = Query(default=None, description="the college's years + institution-wide years"),
    current: bool = False,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await AcademicSessionService(db, principal, request).list_years(
        params, college_id, current
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/academic-years", status_code=201, summary="Create an academic year", response_model=Envelope[AcademicYearResponse]
)
async def create_year(
    body: AcademicYearCreate,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).create_year(body), message="Academic year created")


@router.post(
    "/academic-years/rollover",
    status_code=201,
    summary="Roll over to the next academic year (+ terms, optional batch promotion)",
    response_model=Envelope[RolloverResponse],
)
async def rollover(
    body: RolloverRequest,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("sessions", "rollover")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await AcademicSessionService(db, principal, request).rollover(body), message="Rolled over")
    await store(request, response, db, 201)
    return response


@router.get("/academic-years/{id}", summary="Academic year detail", response_model=Envelope[AcademicYearResponse])
async def get_year(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).get_year(id))


@router.put("/academic-years/{id}", summary="Update an academic year", response_model=Envelope[AcademicYearResponse])
async def update_year(
    id: uuid.UUID,
    body: AcademicYearUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await AcademicSessionService(db, principal, request).update_year(id, body), message="Academic year updated"
    )


@router.post(
    "/academic-years/{id}/set-current",
    summary="Make the year current in its scope (the previous one is cleared)",
    response_model=Envelope[AcademicYearResponse],
)
async def set_current_year(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).set_current_year(id), message="Current year set")


@router.post("/academic-years/{id}/lock", summary="Lock the year", response_model=Envelope[AcademicYearResponse])
async def lock_year(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "lock")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).lock_year(id, True), message="Year locked")


@router.post("/academic-years/{id}/unlock", summary="Unlock the year", response_model=Envelope[AcademicYearResponse])
async def unlock_year(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "lock")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).lock_year(id, False), message="Year unlocked")


# ---- terms -----------------------------------------------------------------------------------------------------------
@router.get("/academic-terms", summary="Academic terms", response_model=Envelope[list[AcademicTermResponse]])
async def list_terms(
    request: Request,
    params: PageParams = Depends(page_params),
    academic_year_id: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, max_length=30),
    current: bool = False,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await AcademicSessionService(db, principal, request).list_terms(
        params, academic_year_id, college_id, status, current
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get(
    "/academic-terms/current",
    summary="Current term (the college's, else the institution-wide one)",
    response_model=Envelope[AcademicTermResponse | None],
)
async def current_term(
    request: Request,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).current_term(college_id))


@router.post("/academic-terms", status_code=201, summary="Create a term", response_model=Envelope[AcademicTermResponse])
async def create_term(
    body: AcademicTermCreate,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).create_term(body), message="Term created")


@router.get(
    "/academic-terms/{id}",
    summary="Term detail (next status + blocking close checks)",
    response_model=Envelope[AcademicTermResponse],
)
async def get_term(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).get_term(id))


@router.put(
    "/academic-terms/{id}", summary="Update a term (dates and windows)", response_model=Envelope[AcademicTermResponse]
)
async def update_term(
    id: uuid.UUID,
    body: AcademicTermUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).update_term(id, body), message="Term updated")


@router.post(
    "/academic-terms/{id}/status",
    summary="Advance the term status (forward only; closed needs sessions:close)",
    response_model=Envelope[AcademicTermResponse],
)
async def change_term_status(
    id: uuid.UUID,
    body: TermStatusChange,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await AcademicSessionService(db, principal, request).change_status(id, body), message="Term status changed"
    )


@router.post(
    "/academic-terms/{id}/set-current",
    summary="Make the term current (emits academic_term.changed)",
    response_model=Envelope[AcademicTermResponse],
)
async def set_current_term(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("sessions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AcademicSessionService(db, principal, request).set_current_term(id), message="Current term set")
