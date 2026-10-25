"""Training programmes — Prompts/28 §28.8 {placement.training}: programmes, sessions, attendance and scores in bulk
(partial-success reports) and the student's own programmes."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.placement import (
    PlcBulkReport,
    TrnAttendanceBulk,
    TrnMyRow,
    TrnProgramIn,
    TrnProgramOut,
    TrnProgramUpdate,
    TrnScoresBulk,
)
from app.services.placement.training_service import TrainingService
from app.utils.response import ok

router = APIRouter(tags=["training"])

P = "placement"
MANAGE = any_permission_required((P, "manage"))
READ = any_permission_required((P, "manage"), (P, "view_all"), (P, "view"))
SELF = any_permission_required((P, "self"), (P, "wards"))

FEAT = [feature_required("placement.core"), feature_required("placement.training")]


@router.get(
    "/training/programs", summary="Training programmes", response_model=Envelope[list[TrnProgramOut]], dependencies=FEAT
)
async def programs(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TrainingService(db, principal, request).list_programs())


@router.post(
    "/training/programs",
    status_code=201,
    summary="Create programme",
    response_model=Envelope[TrnProgramOut],
    dependencies=FEAT,
)
async def create(
    body: TrnProgramIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TrainingService(db, principal, request).create(body), message="Created")


@router.get("/training/me", summary="My training", response_model=Envelope[list[TrnMyRow]], dependencies=FEAT)
async def mine(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TrainingService(db, principal, request).mine())


@router.put(
    "/training/programs/{id}", summary="Update programme", response_model=Envelope[TrnProgramOut], dependencies=FEAT
)
async def update(
    id: uuid.UUID,
    body: TrnProgramUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TrainingService(db, principal, request).update(id, body))


@router.post(
    "/training/programs/{id}/attendance",
    summary="Attendance (bulk)",
    response_model=Envelope[PlcBulkReport],
    dependencies=FEAT,
)
async def attendance(
    id: uuid.UUID,
    body: TrnAttendanceBulk,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TrainingService(db, principal, request).attendance(id, body))


@router.post(
    "/training/programs/{id}/scores", summary="Scores (bulk)", response_model=Envelope[PlcBulkReport], dependencies=FEAT
)
async def scores(
    id: uuid.UUID,
    body: TrnScoresBulk,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TrainingService(db, principal, request).scores(id, body))
