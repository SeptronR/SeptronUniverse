"""Staff master, designations and staff records — Prompts/06 §06.8 (router included with
``feature_required("hr.staff")``; faculty profile / qualifications add {hr.faculty_profiles}, the service book
{hr.service_book}). ``/staff/me`` is any signed-in user's own record; ``/staff/export`` answers the XLSX directly and
``/staff/bulk-import`` enqueues the job ``hr.bulk_import``."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, authenticated, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.hr import EmploymentType, StaffCategory, StaffStatus
from app.schemas.common import Envelope
from app.schemas.hr import (
    DesignationIn,
    DesignationOut,
    FacultyProfileIn,
    FacultyProfileOut,
    QualificationIn,
    QualificationOut,
    ServiceBookEntryIn,
    ServiceBookEntryOut,
    StaffBulkImportRequest,
    StaffCreate,
    StaffCreateResult,
    StaffDetailResponse,
    StaffDocumentIn,
    StaffDocumentOut,
    StaffExitRequest,
    StaffResponse,
    StaffSelfUpdate,
    StaffUpdate,
)
from app.services.staff_service import StaffService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["hr"])

HR_READ = any_permission_required(("hr", "view"), ("hr", "view_all"))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SCOPE = Query(default=None, pattern="^(self|team|department|faculty|college|all)$")
FACULTY_PROFILES = [feature_required("hr.faculty_profiles")]


# ---- designations ---------------------------------------------------------------------------------------------------
@router.get("/designations", summary="Designations", response_model=Envelope[list[DesignationOut]])
async def list_designations(
    request: Request,
    include_inactive: bool = False,
    principal: Principal = Depends(HR_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).list_designations(include_inactive))


@router.post("/designations", status_code=201, summary="Create a designation", response_model=Envelope[DesignationOut])
async def create_designation(
    body: DesignationIn,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).create_designation(body), message="Designation created")


@router.put("/designations/{id}", summary="Update a designation", response_model=Envelope[DesignationOut])
async def update_designation(
    id: uuid.UUID,
    body: DesignationIn,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).update_designation(id, body))


@router.delete("/designations/{id}", summary="Delete an unused designation", response_model=Envelope[None])
async def delete_designation(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await StaffService(db, principal, request).delete_designation(id)
    return ok(None, message="Designation deleted")


# ---- staff ----------------------------------------------------------------------------------------------------------
def _filters(
    q: str | None = Query(default=None, max_length=120),
    department_id: uuid.UUID | None = None,
    designation_id: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    employment_type: EmploymentType | None = None,
    staff_category: StaffCategory | None = None,
    status: StaffStatus | None = None,
) -> dict[str, Any]:
    return {
        "q": q,
        "department_id": department_id,
        "designation_id": designation_id,
        "college_id": college_id,
        "employment_type": employment_type.value if employment_type else None,
        "staff_category": staff_category.value if staff_category else None,
        "status": status.value if status else None,
    }


@router.get(
    "/staff",
    summary="Staff (self / department / faculty / college / all per visibility)",
    response_model=Envelope[list[StaffResponse]],
)
async def list_staff(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = SCOPE,
    filters: dict[str, Any] = Depends(_filters),
    principal: Principal = Depends(HR_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await StaffService(db, principal, request).list_page(params, scope, **filters)
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get("/staff/export", summary="Export the filtered staff (XLSX; PII masked without hr:view_pii)")
async def export_staff(
    request: Request,
    scope: str | None = SCOPE,
    filters: dict[str, Any] = Depends(_filters),
    principal: Principal = Depends(any_permission_required(("hr", "export"), ("hr", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content = await StaffService(db, principal, request).export_xlsx(scope, **filters)
    return Response(content, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="staff.xlsx"'})


@router.post(
    "/staff/bulk-import",
    status_code=202,
    summary="Bulk import staff from CSV (job)",
    response_model=Envelope[dict[str, Any]],
)
async def bulk_import_staff(
    body: StaffBulkImportRequest,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).enqueue_bulk_import(body.csv), message="Import queued")


@router.get("/staff/me", summary="My staff profile", response_model=Envelope[StaffDetailResponse])
async def my_profile(
    request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).me())


@router.put(
    "/staff/me",
    summary="Update my contact details / photo / emergency contact",
    response_model=Envelope[StaffDetailResponse],
)
async def update_my_profile(
    body: StaffSelfUpdate,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).update_me(body), message="Profile updated")


@router.post(
    "/staff",
    status_code=201,
    summary="Create a staff member (+ user account)",
    response_model=Envelope[StaffCreateResult],
)
async def create_staff(
    body: StaffCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("hr", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await StaffService(db, principal, request).create(body), message="Staff member created")
    await store(request, response, db, 201)
    return response


@router.get(
    "/staff/{id}", summary="Staff detail (PII masked without hr:view_pii)", response_model=Envelope[StaffDetailResponse]
)
async def get_staff(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HR_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).get(id))


@router.put("/staff/{id}", summary="Update a staff member", response_model=Envelope[StaffDetailResponse])
async def update_staff(
    id: uuid.UUID,
    body: StaffUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).update(id, body), message="Staff member updated")


@router.post(
    "/staff/{id}/exit",
    summary="Exit a staff member (deactivates the account)",
    response_model=Envelope[StaffDetailResponse],
)
async def exit_staff(
    id: uuid.UUID,
    body: StaffExitRequest,
    request: Request,
    principal: Principal = Depends(permission_required("hr", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).exit(id, body), message="Staff member exited")


@router.post("/staff/{id}/photo", summary="Upload a staff photo", response_model=Envelope[StaffDetailResponse])
async def staff_photo(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(any_permission_required(("hr", "update"), ("hr", "view"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).set_photo(id, file), message="Photo updated")


# ---- records --------------------------------------------------------------------------------------------------------
@router.get(
    "/staff/{id}/faculty-profile",
    summary="Faculty profile",
    response_model=Envelope[FacultyProfileOut | None],
    dependencies=FACULTY_PROFILES,
)
async def get_faculty_profile(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HR_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).faculty_profile(id))


@router.put(
    "/staff/{id}/faculty-profile",
    summary="Create / update a faculty profile",
    response_model=Envelope[FacultyProfileOut],
    dependencies=FACULTY_PROFILES,
)
async def put_faculty_profile(
    id: uuid.UUID,
    body: FacultyProfileIn,
    request: Request,
    principal: Principal = Depends(any_permission_required(("hr", "manage"), ("faculty", "research"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await StaffService(db, principal, request).upsert_faculty_profile(id, body), message="Faculty profile saved"
    )


@router.get(
    "/staff/{id}/qualifications",
    summary="Qualifications",
    response_model=Envelope[list[QualificationOut]],
    dependencies=FACULTY_PROFILES,
)
async def list_qualifications(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HR_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).qualifications(id))


@router.post(
    "/staff/{id}/qualifications",
    status_code=201,
    summary="Add a qualification",
    response_model=Envelope[list[QualificationOut]],
    dependencies=FACULTY_PROFILES,
)
async def add_qualification(
    id: uuid.UUID,
    body: QualificationIn,
    request: Request,
    principal: Principal = Depends(any_permission_required(("hr", "manage"), ("faculty", "research"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).add_qualification(id, body), message="Qualification added")


@router.get("/staff/{id}/documents", summary="Staff documents", response_model=Envelope[list[StaffDocumentOut]])
async def list_documents(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HR_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).documents(id))


@router.post(
    "/staff/{id}/documents", status_code=201, summary="Add a staff document", response_model=Envelope[StaffDocumentOut]
)
async def add_document(
    id: uuid.UUID,
    body: StaffDocumentIn,
    request: Request,
    principal: Principal = Depends(HR_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).add_document(id, body), message="Document added")


@router.get(
    "/staff/{id}/service-book",
    summary="Service book",
    response_model=Envelope[list[ServiceBookEntryOut]],
    dependencies=[feature_required("hr.service_book")],
)
async def service_book(
    id: uuid.UUID, request: Request, principal: Principal = Depends(HR_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).service_book(id))


@router.post(
    "/staff/{id}/service-book",
    status_code=201,
    summary="Add a service-book entry",
    response_model=Envelope[ServiceBookEntryOut],
    dependencies=[feature_required("hr.service_book")],
)
async def add_service_book(
    id: uuid.UUID,
    body: ServiceBookEntryIn,
    request: Request,
    principal: Principal = Depends(any_permission_required(("hr", "service_book"), ("hr", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StaffService(db, principal, request).add_service_book(id, body), message="Entry added")
