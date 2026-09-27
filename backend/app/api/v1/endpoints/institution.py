"""Institution structure — Prompts/03 §03.8 (router included with ``feature_required("core.institution")``).

Reads are institution-wide: every route that lists or reads structure accepts ``institutions:view`` (granted to every
role — Prompts/03 "Visibility rules") next to the module's own ``view``; writes need the module permission and are
narrowed to the caller's college scope inside the services. Faculties add ``{institution.faculties}``, holidays
``{institution.holidays}``, number sequences ``{institution.number_sequences_custom}``.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.institution import (
    CollegeCreate,
    CollegeResponse,
    CollegeUpdate,
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
    FacultyCreate,
    FacultyResponse,
    FacultyUpdate,
    HodAssign,
    HolidayBulkImport,
    HolidayBulkResult,
    HolidayCreate,
    HolidayResponse,
    HolidayUpdate,
    InstitutionProfileResponse,
    InstitutionProfileUpdate,
    LogoUploadResponse,
    NumberSequenceCreate,
    NumberSequencePreview,
    NumberSequencePreviewRequest,
    NumberSequenceResponse,
    NumberSequenceUpdate,
)
from app.services.college_service import CollegeService
from app.services.department_service import DepartmentService
from app.services.holiday_service import HolidayService
from app.services.institution_service import InstitutionService
from app.services.sequence_service import SequenceService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["institution"])

INSTITUTION_READ = ("institutions", "view")
SCOPE_PATTERN = "^(college|all)$"
FACULTIES = [feature_required("institution.faculties")]
HOLIDAYS = [feature_required("institution.holidays")]
SEQUENCES = [feature_required("institution.number_sequences_custom")]


# ---- profile ---------------------------------------------------------------------------------------------------------
@router.get("/institution/profile", summary="Institution profile", response_model=Envelope[InstitutionProfileResponse])
async def get_profile(
    request: Request,
    principal: Principal = Depends(permission_required("institutions", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InstitutionService(db, principal, request).get_profile())


@router.put(
    "/institution/profile",
    summary="Update the institution profile (audited diff)",
    response_model=Envelope[InstitutionProfileResponse],
)
async def update_profile(
    body: InstitutionProfileUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("institutions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InstitutionService(db, principal, request).update_profile(body), message="Profile saved")


@router.post(
    "/institution/profile/logo",
    summary="Upload the logo / seal / head signature / letterhead",
    response_model=Envelope[LogoUploadResponse],
)
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form(default="logo", pattern="^(logo|seal|signature|letterhead)$"),
    principal: Principal = Depends(permission_required("institutions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await InstitutionService(db, principal, request).upload_logo(file, kind), message="Image uploaded")


# ---- colleges --------------------------------------------------------------------------------------------------------
@router.get("/colleges", summary="Colleges / campuses / study centres", response_model=Envelope[list[CollegeResponse]])
async def list_colleges(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern=SCOPE_PATTERN),
    q: str | None = Query(default=None, max_length=120),
    college_type: str | None = Query(default=None, max_length=30),
    is_exam_centre: bool | None = None,
    include_inactive: bool = False,
    principal: Principal = Depends(any_permission_required(("colleges", "view"), INSTITUTION_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await CollegeService(db, principal, request).list_page(
        params, scope, q, college_type, is_exam_centre, include_inactive
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post("/colleges", status_code=201, summary="Create a college", response_model=Envelope[CollegeResponse])
async def create_college(
    body: CollegeCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("colleges", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await CollegeService(db, principal, request).create(body), message="College created")
    await store(request, response, db, 201)
    return response


@router.get("/colleges/{id}", summary="College detail", response_model=Envelope[CollegeResponse])
async def get_college(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required(("colleges", "view"), INSTITUTION_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CollegeService(db, principal, request).get(id))


@router.put("/colleges/{id}", summary="Update a college (college scope)", response_model=Envelope[CollegeResponse])
async def update_college(
    id: uuid.UUID,
    body: CollegeUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("colleges", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CollegeService(db, principal, request).update(id, body), message="College updated")


@router.delete("/colleges/{id}", summary="Delete a college (soft)", response_model=Envelope[None])
async def delete_college(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("colleges", "delete")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await CollegeService(db, principal, request).delete(id)
    return ok(None, message="College deleted")


# ---- faculties -------------------------------------------------------------------------------------------------------
@router.get(
    "/faculties", summary="Faculties / schools", dependencies=FACULTIES, response_model=Envelope[list[FacultyResponse]]
)
async def list_faculties(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern=SCOPE_PATTERN),
    college_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(any_permission_required(("faculties", "view"), INSTITUTION_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await DepartmentService(db, principal, request).list_faculties(
        params, scope, college_id, q
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/faculties",
    status_code=201,
    summary="Create a faculty (optional dean → dean @faculty)",
    dependencies=FACULTIES,
    response_model=Envelope[FacultyResponse],
)
async def create_faculty(
    body: FacultyCreate,
    request: Request,
    principal: Principal = Depends(permission_required("departments", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DepartmentService(db, principal, request).create_faculty(body), message="Faculty created")


@router.put(
    "/faculties/{id}",
    summary="Update a faculty / assign the dean",
    dependencies=FACULTIES,
    response_model=Envelope[FacultyResponse],
)
async def update_faculty(
    id: uuid.UUID,
    body: FacultyUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("departments", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DepartmentService(db, principal, request).update_faculty(id, body), message="Faculty updated")


@router.delete(
    "/faculties/{id}", summary="Delete a faculty (soft)", dependencies=FACULTIES, response_model=Envelope[None]
)
async def delete_faculty(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("departments", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await DepartmentService(db, principal, request).delete_faculty(id)
    return ok(None, message="Faculty deleted")


# ---- departments -----------------------------------------------------------------------------------------------------
@router.get("/departments", summary="Departments", response_model=Envelope[list[DepartmentResponse]])
async def list_departments(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern=SCOPE_PATTERN),
    college_id: uuid.UUID | None = None,
    faculty_id: uuid.UUID | None = None,
    department_type: str | None = Query(default=None, max_length=30),
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(any_permission_required(("departments", "view"), INSTITUTION_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await DepartmentService(db, principal, request).list_page(
        params, scope, college_id, faculty_id, department_type, q
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/departments", status_code=201, summary="Create a department", response_model=Envelope[DepartmentResponse]
)
async def create_department(
    body: DepartmentCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("departments", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await DepartmentService(db, principal, request).create(body), message="Department created")
    await store(request, response, db, 201)
    return response


@router.get("/departments/{id}", summary="Department detail", response_model=Envelope[DepartmentResponse])
async def get_department(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required(("departments", "view"), INSTITUTION_READ)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DepartmentService(db, principal, request).get(id))


@router.put("/departments/{id}", summary="Update a department", response_model=Envelope[DepartmentResponse])
async def update_department(
    id: uuid.UUID,
    body: DepartmentUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("departments", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DepartmentService(db, principal, request).update(id, body), message="Department updated")


@router.delete("/departments/{id}", summary="Delete a department (soft)", response_model=Envelope[None])
async def delete_department(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("departments", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await DepartmentService(db, principal, request).delete(id)
    return ok(None, message="Department deleted")


@router.put(
    "/departments/{id}/hod",
    summary="Assign the HOD (grants hod @department)",
    response_model=Envelope[DepartmentResponse],
)
async def assign_hod(
    id: uuid.UUID,
    body: HodAssign,
    request: Request,
    principal: Principal = Depends(permission_required("departments", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DepartmentService(db, principal, request).assign_hod(id, body), message="HOD assigned")


# ---- holidays --------------------------------------------------------------------------------------------------------
@router.get(
    "/holidays", summary="Holiday calendar", dependencies=HOLIDAYS, response_model=Envelope[list[HolidayResponse]]
)
async def list_holidays(
    request: Request,
    params: PageParams = Depends(page_params),
    college_id: uuid.UUID | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    holiday_type: str | None = Query(default=None, max_length=30),
    applies_to: str | None = Query(default=None, pattern="^(all|students|staff)$"),
    principal: Principal = Depends(permission_required("institutions", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await HolidayService(db, principal, request).list_page(
        params, college_id, date_from, date_to, holiday_type, applies_to
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/holidays",
    status_code=201,
    summary="Add a holiday",
    dependencies=HOLIDAYS,
    response_model=Envelope[HolidayResponse],
)
async def create_holiday(
    body: HolidayCreate,
    request: Request,
    principal: Principal = Depends(permission_required("institutions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await HolidayService(db, principal, request).create(body)
    return ok(HolidayResponse.model_validate(row), message="Holiday added")


@router.post(
    "/holidays/bulk-import",
    summary="Bulk import holidays from CSV (partial success)",
    dependencies=HOLIDAYS,
    response_model=Envelope[HolidayBulkResult],
)
async def bulk_import_holidays(
    body: HolidayBulkImport,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("institutions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await HolidayService(db, principal, request).bulk_import(body)
    response = ok(result, message=f"{result.succeeded} imported, {len(result.failed)} failed")
    await store(request, response, db)
    return response


@router.get(
    "/holidays/export.ics",
    summary="Holiday calendar as iCal (RFC 5545)",
    dependencies=HOLIDAYS,
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
)
async def export_holidays_ics(
    request: Request,
    college_id: uuid.UUID | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    principal: Principal = Depends(permission_required("institutions", "view")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    body = await HolidayService(db, principal, request).export_ics(college_id, date_from, date_to)
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="holidays.ics"'},
    )


@router.put(
    "/holidays/{id}", summary="Update a holiday", dependencies=HOLIDAYS, response_model=Envelope[HolidayResponse]
)
async def update_holiday(
    id: uuid.UUID,
    body: HolidayUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("institutions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HolidayService(db, principal, request).update(id, body), message="Holiday updated")


@router.delete("/holidays/{id}", summary="Delete a holiday", dependencies=HOLIDAYS, response_model=Envelope[None])
async def delete_holiday(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("institutions", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await HolidayService(db, principal, request).delete(id)
    return ok(None, message="Holiday deleted")


# ---- number sequences ------------------------------------------------------------------------------------------------
@router.get(
    "/number-sequences",
    summary="Number sequences (registration / hall-ticket / receipt numbers)",
    dependencies=SEQUENCES,
    response_model=Envelope[list[NumberSequenceResponse]],
)
async def list_sequences(
    request: Request,
    params: PageParams = Depends(page_params),
    college_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await SequenceService(db, principal, request).list_page(params, college_id, q)
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/number-sequences",
    status_code=201,
    summary="Create a number sequence",
    dependencies=SEQUENCES,
    response_model=Envelope[NumberSequenceResponse],
)
async def create_sequence(
    body: NumberSequenceCreate,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SequenceService(db, principal, request).create(body), message="Sequence created")


@router.put(
    "/number-sequences/{id}",
    summary="Update a number sequence (pattern, next value, padding, reset policy)",
    dependencies=SEQUENCES,
    response_model=Envelope[NumberSequenceResponse],
)
async def update_sequence(
    id: uuid.UUID,
    body: NumberSequenceUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SequenceService(db, principal, request).update(id, body), message="Sequence updated")


@router.post(
    "/number-sequences/{id}/preview",
    summary="Preview the next values (nothing is consumed)",
    dependencies=SEQUENCES,
    response_model=Envelope[NumberSequencePreview],
)
async def preview_sequence(
    id: uuid.UUID,
    request: Request,
    body: NumberSequencePreviewRequest | None = None,
    principal: Principal = Depends(permission_required("settings", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SequenceService(db, principal, request).preview(id, body or NumberSequencePreviewRequest()))
