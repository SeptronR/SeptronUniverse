"""Faculty workload and course-allocation proposals — Prompts/06 §06.8 (router included with
``feature_required("hr.workload")``; ``[faculty:workload_manage | self]``)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.hr import AllocationProposalIn, AllocationProposalOut, WorkloadResponse
from app.schemas.leaves import LeaveDecision
from app.services.workload_service import WorkloadService
from app.utils.response import ok

router = APIRouter(tags=["hr"])

MANAGE = permission_required("faculty", "workload_manage")


@router.get(
    "/faculty/{id}/workload",
    summary="Workload of a staff member for a term (own, or workload managers)",
    response_model=Envelope[WorkloadResponse],
)
async def staff_workload(
    id: uuid.UUID,
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(
        any_permission_required(("faculty", "workload_manage"), ("faculty", "view"), ("faculty", "view_all"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkloadService(db, principal, request).for_staff(id, term_id))


@router.get(
    "/workload", summary="Department workload grid vs cadre norms", response_model=Envelope[list[WorkloadResponse]]
)
async def department_workload(
    request: Request,
    department_id: uuid.UUID,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(any_permission_required(("faculty", "workload_manage"), ("faculty", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkloadService(db, principal, request).for_department(department_id, term_id))


@router.get(
    "/departments/{id}/course-allocation",
    summary="Course-allocation proposal of a department for a term",
    response_model=Envelope[AllocationProposalOut],
)
async def get_allocation(
    id: uuid.UUID,
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkloadService(db, principal, request).get_proposal(id, term_id))


@router.post(
    "/departments/{id}/course-allocation",
    summary="Save the draft proposal",
    response_model=Envelope[AllocationProposalOut],
)
async def save_allocation(
    id: uuid.UUID,
    body: AllocationProposalIn,
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkloadService(db, principal, request).save_proposal(id, term_id, body), message="Proposal saved")


@router.post(
    "/course-allocation/{id}/submit",
    summary="Submit to the dean (workflow hr.course_allocation)",
    response_model=Envelope[AllocationProposalOut],
)
async def submit_allocation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WorkloadService(db, principal, request).submit(id), message="Submitted to the dean")


@router.post(
    "/course-allocation/{id}/approve",
    summary="Dean approval (acts on the workflow step)",
    response_model=Envelope[AllocationProposalOut],
)
async def approve_allocation(
    id: uuid.UUID,
    request: Request,
    body: LeaveDecision | None = None,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WorkloadService(db, principal, request).approve(id, "approve", body.comment if body else None))


@router.post(
    "/course-allocation/{id}/apply",
    summary="Apply to the term's offerings (Phase 09; 409 until offerings exist)",
    response_model=Envelope[AllocationProposalOut],
)
async def apply_allocation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WorkloadService(db, principal, request).apply(id), message="Applied")
