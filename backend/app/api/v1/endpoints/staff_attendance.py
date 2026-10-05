"""Staff attendance and attendance devices — Prompts/06 §06.8 (router included with
``feature_required("attendance.staff")``; devices add {attendance.biometric}).

``POST /attendance-devices/{id}/punches`` is **token-authenticated** (``PUBLIC_ROUTES``): the tenant is the
device's institution (looked up on the platform session by the device id, then pinned for RLS) and the feature is
checked here, like the public catalogue."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.db.session import bind_tenant, get_db, set_tenant
from app.enums.hr import AttendanceStatus
from app.repositories.staff_attendance_repository import device_institution
from app.schemas.common import Envelope
from app.schemas.hr import (
    AttendanceDeviceIn,
    AttendanceDeviceOut,
    AttendanceSummaryRow,
    PunchIngest,
    PunchIngestResult,
    RegulariseRequest,
    SelfCheckinRequest,
    StaffAttendanceMark,
    StaffAttendanceOut,
)
from app.services.staff_attendance_service import StaffAttendanceService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["hr"])
public_router = APIRouter(tags=["public"])

ATT_READ = any_permission_required(("attendance", "staff_self"), ("attendance", "staff_view_all"))
MONTH = Query(default=None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM (default: current month)")
BIOMETRIC = [feature_required("attendance.biometric")]


@router.get(
    "/staff-attendance",
    summary="Staff attendance (self / team / all per visibility)",
    response_model=Envelope[list[StaffAttendanceOut]],
)
async def list_attendance(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern="^(self|team|department|faculty|college|all)$"),
    month: str | None = MONTH,
    staff_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    status: AttendanceStatus | None = None,
    principal: Principal = Depends(ATT_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await StaffAttendanceService(db, principal, request).list_page(
        params, scope, month, staff_id=staff_id, department_id=department_id, status=status.value if status else None
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/staff-attendance/mark", summary="Mark a member's attendance (HR)", response_model=Envelope[StaffAttendanceOut]
)
async def mark_attendance(
    body: StaffAttendanceMark,
    request: Request,
    principal: Principal = Depends(any_permission_required(("hr", "manage"), ("attendance", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row, created = await StaffAttendanceService(db, principal, request).mark(body)
    return ok(row, message="Attendance recorded" if created else "Attendance updated")


@router.post(
    "/staff-attendance/self-checkin",
    status_code=201,
    summary="Check in (geo-fenced with attendance.geo_app)",
    response_model=Envelope[StaffAttendanceOut],
)
async def self_checkin(
    request: Request,
    body: SelfCheckinRequest | None = None,
    principal: Principal = Depends(permission_required("attendance", "staff_self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await StaffAttendanceService(db, principal, request).self_checkin(body or SelfCheckinRequest()),
        message="Checked in",
    )


@router.post("/staff-attendance/self-checkout", summary="Check out", response_model=Envelope[StaffAttendanceOut])
async def self_checkout(
    request: Request,
    body: SelfCheckinRequest | None = None,
    principal: Principal = Depends(permission_required("attendance", "staff_self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await StaffAttendanceService(db, principal, request).self_checkout(body or SelfCheckinRequest()),
        message="Checked out",
    )


@router.post(
    "/staff-attendance/regularise",
    status_code=201,
    summary="Ask to regularise a past day (workflow attendance.regularise)",
    response_model=Envelope[dict[str, Any]],
)
async def regularise(
    body: RegulariseRequest,
    request: Request,
    principal: Principal = Depends(permission_required("attendance", "staff_self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffAttendanceService(db, principal, request).regularise(body), message="Regularisation requested")


@router.get(
    "/staff-attendance/summary",
    summary="Monthly summary per staff member (LOP feeds payroll)",
    response_model=Envelope[list[AttendanceSummaryRow]],
)
async def attendance_summary(
    request: Request,
    month: str | None = MONTH,
    scope: str | None = Query(default=None, pattern="^(self|team|department|faculty|college|all)$"),
    staff_id: uuid.UUID | None = None,
    principal: Principal = Depends(ATT_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffAttendanceService(db, principal, request).summary(month, scope, staff_id))


@router.get(
    "/attendance-devices",
    summary="Attendance devices",
    response_model=Envelope[list[AttendanceDeviceOut]],
    dependencies=BIOMETRIC,
)
async def list_devices(
    request: Request,
    principal: Principal = Depends(permission_required("attendance", "device_manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffAttendanceService(db, principal, request).list_devices())


@router.post(
    "/attendance-devices",
    status_code=201,
    summary="Register a device (token shown once)",
    response_model=Envelope[AttendanceDeviceOut],
    dependencies=BIOMETRIC,
)
async def create_device(
    body: AttendanceDeviceIn,
    request: Request,
    principal: Principal = Depends(permission_required("attendance", "device_manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffAttendanceService(db, principal, request).create_device(body), message="Device registered")


@public_router.post(
    "/attendance-devices/{id}/punches",
    summary="Device punch ingest (device token)",
    response_model=Envelope[PunchIngestResult],
)
async def ingest_punches(id: uuid.UUID, body: PunchIngest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    institution_id = await device_institution(id)
    if institution_id is None:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid device token")
    bind_tenant(db, institution_id)
    await set_tenant(db, institution_id)
    if not await is_enabled(institution_id, "attendance.biometric"):
        raise APIError(
            403,
            ErrorCode.FEATURE_DISABLED,
            "Feature 'attendance.biometric' is not enabled",
            {"feature": "attendance.biometric"},
        )
    return ok(await StaffAttendanceService(db, None, institution_id=institution_id).ingest_punches(id, body))
