"""Programme-regulations, structure and elective baskets — Prompts/05 §05.8.

Router included with ``feature_required("academics.curriculum")``; the basket routes add
``{academics.elective_baskets}``. Structure writes are frozen under an active regulation (409 ``RECORD_LOCKED``).
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.enums.academics import BasketType, ProgramRegulationStatus
from app.schemas.academics import ProgramRegulationCreate, ProgramRegulationResponse, ProgramRegulationUpdate
from app.schemas.common import Envelope
from app.schemas.curriculum import (
    BasketCoursesReplace,
    BasketCreate,
    BasketOut,
    BasketUpdate,
    StructureReplaceRequest,
    StructureResponse,
    StructureValidationResponse,
)
from app.services.curriculum_service import CurriculumService
from app.services.program_service import ProgramService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["academics"])

CURRICULUM_READ = any_permission_required(("curriculum", "view"), ("curriculum", "view_all"))
# Phase 07: students / parents read the programme-regulation of their (wards') enrolment — narrowed in the services
CURRICULUM_OR_ENROLLED = any_permission_required(
    ("curriculum", "view"), ("curriculum", "view_all"), ("students", "self"), ("students", "view")
)
BASKETS = [feature_required("academics.elective_baskets")]


# ---- programme-regulations -------------------------------------------------------------------------------------------
@router.get(
    "/program-regulations",
    summary="Programme ↔ regulation bindings",
    response_model=Envelope[list[ProgramRegulationResponse]],
)
async def list_program_regulations(
    request: Request,
    params: PageParams = Depends(page_params),
    program_id: uuid.UUID | None = None,
    regulation_id: uuid.UUID | None = None,
    status: ProgramRegulationStatus | None = None,
    principal: Principal = Depends(CURRICULUM_OR_ENROLLED),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await ProgramService(db, principal, request).list_bindings(
        params, program_id, regulation_id, status.value if status else None
    )
    return ok(rows, pagination=pagination)


@router.post(
    "/program-regulations",
    status_code=201,
    summary="Bind a programme to a regulation",
    response_model=Envelope[ProgramRegulationResponse],
)
async def create_program_regulation(
    body: ProgramRegulationCreate,
    request: Request,
    principal: Principal = Depends(permission_required("curriculum", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramService(db, principal, request).create_binding(body), message="Programme bound")


@router.put(
    "/program-regulations/{id}",
    summary="Credits required / rules override / status",
    response_model=Envelope[ProgramRegulationResponse],
)
async def update_program_regulation(
    id: uuid.UUID,
    body: ProgramRegulationUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("curriculum", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramService(db, principal, request).update_binding(id, body), message="Saved")


# ---- structure -------------------------------------------------------------------------------------------------------
@router.get(
    "/program-regulations/{id}/structure",
    summary="Structure terms, curriculum courses and baskets",
    response_model=Envelope[StructureResponse],
)
async def get_structure(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(CURRICULUM_OR_ENROLLED),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CurriculumService(db, principal, request).get_structure(id))


@router.put(
    "/program-regulations/{id}/structure",
    summary="Replace the structure (transactional)",
    response_model=Envelope[StructureResponse],
)
async def replace_structure(
    id: uuid.UUID,
    body: StructureReplaceRequest,
    request: Request,
    principal: Principal = Depends(permission_required("curriculum", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CurriculumService(db, principal, request).replace_structure(id, body), message="Structure saved")


@router.post(
    "/program-regulations/{id}/structure/validate",
    summary="Credit totals and issues",
    response_model=Envelope[StructureValidationResponse],
)
async def validate_structure(
    id: uuid.UUID,
    request: Request,
    for_approval: bool = Query(default=False, description="report the credit mismatch as an error"),
    principal: Principal = Depends(CURRICULUM_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CurriculumService(db, principal, request).validate(id, for_approval=for_approval))


# ---- elective baskets ------------------------------------------------------------------------------------------------
@router.get(
    "/elective-baskets", summary="Elective baskets", dependencies=BASKETS, response_model=Envelope[list[BasketOut]]
)
async def list_baskets(
    request: Request,
    params: PageParams = Depends(page_params),
    program_regulation_id: uuid.UUID | None = None,
    basket_type: BasketType | None = None,
    principal: Principal = Depends(CURRICULUM_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await CurriculumService(db, principal, request).list_baskets(
        params, program_regulation_id, basket_type.value if basket_type else None
    )
    return ok(rows, pagination=pagination)


@router.post(
    "/elective-baskets",
    status_code=201,
    summary="Create a basket",
    dependencies=BASKETS,
    response_model=Envelope[BasketOut],
)
async def create_basket(
    body: BasketCreate,
    request: Request,
    principal: Principal = Depends(permission_required("curriculum", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CurriculumService(db, principal, request).create_basket(body), message="Basket created")


@router.put(
    "/elective-baskets/{id}", summary="Update a basket", dependencies=BASKETS, response_model=Envelope[BasketOut]
)
async def update_basket(
    id: uuid.UUID,
    body: BasketUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("curriculum", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CurriculumService(db, principal, request).update_basket(id, body), message="Basket saved")


@router.delete("/elective-baskets/{id}", summary="Delete a basket", dependencies=BASKETS, response_model=Envelope[None])
async def delete_basket(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("curriculum", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await CurriculumService(db, principal, request).delete_basket(id)
    return ok(None, message="Basket deleted")


@router.put(
    "/elective-baskets/{id}/courses",
    summary="Replace the basket's courses",
    dependencies=BASKETS,
    response_model=Envelope[BasketOut],
)
async def replace_basket_courses(
    id: uuid.UUID,
    body: BasketCoursesReplace,
    request: Request,
    principal: Principal = Depends(permission_required("curriculum", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CurriculumService(db, principal, request).replace_basket_courses(id, body), message="Courses saved")
