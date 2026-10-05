"""Leave types and leaves — Prompts/06 §06.8 (router included with ``feature_required("hr.leaves")``; encashment
adds {hr.leave_encashment}). ``/leaves?scope=self|team|all`` is resolver-filtered and returns ``meta.visibility``;
approve / reject act on the ``leave.approval`` workflow step of the caller (403 for anyone else)."""

import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.hr import LeaveStatus
from app.schemas.common import Envelope
from app.schemas.leaves import (
    LeaveApply,
    LeaveBalanceResponse,
    LeaveCalendarItem,
    LeaveDecision,
    LeaveEncashRequest,
    LeaveEncashResult,
    LeaveResponse,
    LeaveTypeIn,
    LeaveTypeOut,
)
from app.services.leave_service import LeaveService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["hr"])

LEAVE_READ = any_permission_required(("leaves", "view"), ("leaves", "view_all"))


@router.get("/leave-types", summary="Leave types", response_model=Envelope[list[LeaveTypeOut]])
async def list_leave_types(
    request: Request,
    include_inactive: bool = False,
    principal: Principal = Depends(
        any_permission_required(("leaves", "view"), ("leaves", "view_all"), ("hr", "manage"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).list_types(include_inactive))


@router.post("/leave-types", status_code=201, summary="Create a leave type", response_model=Envelope[LeaveTypeOut])
async def create_leave_type(
    body: LeaveTypeIn,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).create_type(body), message="Leave type created")


@router.put("/leave-types/{id}", summary="Update a leave type", response_model=Envelope[LeaveTypeOut])
async def update_leave_type(
    id: uuid.UUID,
    body: LeaveTypeIn,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).update_type(id, body))


@router.get(
    "/leaves", summary="Leaves (self / team / all per visibility)", response_model=Envelope[list[LeaveResponse]]
)
async def list_leaves(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern="^(self|team|department|faculty|college|all)$"),
    status: LeaveStatus | None = None,
    staff_id: uuid.UUID | None = None,
    leave_type_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    principal: Principal = Depends(LEAVE_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await LeaveService(db, principal, request).list_page(
        params,
        scope,
        status=status.value if status else None,
        staff_id=staff_id,
        leave_type_id=leave_type_id,
        department_id=department_id,
        date_from=date_from,
        date_to=date_to,
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/leaves",
    status_code=201,
    summary="Apply for leave (self) — starts leave.approval",
    response_model=Envelope[LeaveResponse],
)
async def apply_leave(
    body: LeaveApply,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("leaves", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await LeaveService(db, principal, request).apply(body), message="Leave applied")
    await store(request, response, db, 201)
    return response


@router.get("/leaves/me/balance", summary="My leave balances", response_model=Envelope[list[LeaveBalanceResponse]])
async def my_balance(
    request: Request,
    year: int | None = Query(default=None, ge=2000, le=2100),
    principal: Principal = Depends(permission_required("leaves", "self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).balance_me(year))


@router.get(
    "/leaves/balances", summary="A staff member's leave balances", response_model=Envelope[list[LeaveBalanceResponse]]
)
async def staff_balance(
    request: Request,
    staff_id: uuid.UUID,
    year: int | None = Query(default=None, ge=2000, le=2100),
    principal: Principal = Depends(permission_required("leaves", "view_all")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = LeaveService(db, principal, request)
    staff = await service.staff_repo.get_visible(staff_id, module="leaves")
    return ok(await service.balances_for(staff, year or (await service.today()).year))


@router.get(
    "/leaves/calendar", summary="Leave calendar (pending + approved)", response_model=Envelope[list[LeaveCalendarItem]]
)
async def leave_calendar(
    request: Request,
    department_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    principal: Principal = Depends(LEAVE_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    service = LeaveService(db, principal, request)
    start = date_from or (await service.today()).replace(day=1)
    end = date_to or (start + timedelta(days=62))
    if end < start or (end - start).days > 366:
        raise APIError(422, ErrorCode.VALIDATION, "date range must be 0–366 days", {"field": "date_to"})
    return ok(await service.calendar(department_id, start, end))


@router.post(
    "/leaves/encash",
    status_code=201,
    summary="Request leave encashment (workflow hr.leave_encashment)",
    response_model=Envelope[LeaveEncashResult],
    dependencies=[feature_required("hr.leave_encashment")],
)
async def encash_leave(
    body: LeaveEncashRequest,
    request: Request,
    principal: Principal = Depends(permission_required("leaves", "encash")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).encash(body), message="Encashment requested")


@router.get("/leaves/{id}", summary="Leave detail", response_model=Envelope[LeaveResponse])
async def get_leave(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LEAVE_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).get(id))


@router.post(
    "/leaves/{id}/cancel",
    summary="Cancel a pending leave (or an approved one before it starts)",
    response_model=Envelope[LeaveResponse],
)
async def cancel_leave(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required(("leaves", "create"), ("leaves", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).cancel(id), message="Leave cancelled")


@router.post(
    "/leaves/{id}/approve", summary="Approve (acts on the workflow step)", response_model=Envelope[LeaveResponse]
)
async def approve_leave(
    id: uuid.UUID,
    request: Request,
    body: LeaveDecision | None = None,
    principal: Principal = Depends(permission_required("leaves", "approve")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).decide(id, "approve", body.comment if body else None))


@router.post(
    "/leaves/{id}/reject", summary="Reject (acts on the workflow step)", response_model=Envelope[LeaveResponse]
)
async def reject_leave(
    id: uuid.UUID,
    request: Request,
    body: LeaveDecision | None = None,
    principal: Principal = Depends(permission_required("leaves", "approve")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await LeaveService(db, principal, request).decide(id, "reject", body.comment if body else None))
