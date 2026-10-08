"""Students — Prompts/07 §07.8 (router included with ``feature_required("students.core")``; sub-features per route:
{portals.student} for ``/students/me*``, {students.self_service_profile} for the self update, {students.bulk_import},
{students.id_cards}, {students.guardians_portal}, {students.documents}, {students.undertakings}).

Static paths (``/students/me``, ``/stats``, ``/export``, ``/import-template``, ``/bulk-import``, ``/id-cards``) are
declared before ``/students/{id}``. ``POST /students`` is the real create (the Phase 02 stub is gone) — it enforces
the plan's student seat limit first. Holds, standing, enrolments, promotion, exit / re-entry and transfers live in
``enrollments.py``; credit transfers in ``credit_transfers.py``; the public ``/verify/{token}`` in ``verify.py``.
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
from app.enums.students import AcademicStanding, Gender, StudentStatus
from app.schemas.common import Envelope
from app.schemas.students import (
    BulkImportResult,
    DocumentOut,
    DocumentVerifyRequest,
    GuardianIn,
    GuardianOut,
    GuardianPortalConsentUpdate,
    GuardianUpdate,
    IdCardRequest,
    IdCardResponse,
    StatusChangeRequest,
    StudentCreate,
    StudentCreateResult,
    StudentDashboard,
    StudentDetailResponse,
    StudentListItem,
    StudentSelfUpdate,
    StudentStats,
    StudentUpdate,
    UndertakingAccept,
    UndertakingOut,
    UndertakingStatus,
    WardSummary,
)
from app.services.student_portal_service import StudentPortalService
from app.services.student_records_service import StudentRecordsService
from app.services.student_service import StudentService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["students"])

STUDENT_READ = any_permission_required(("students", "view"), ("students", "view_all"))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SCOPE = Query(default=None, pattern="^(self|own|mine|department|faculty|college|all)$")
PORTAL = [feature_required("portals.student")]
BULK = [feature_required("students.bulk_import")]
ID_CARDS = [feature_required("students.id_cards")]
GUARDIANS = [feature_required("students.guardians_portal")]
DOCUMENTS = [feature_required("students.documents")]
UNDERTAKINGS = [feature_required("students.undertakings")]


def _filters(
    q: str | None = Query(default=None, max_length=120),
    college_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    section_id: uuid.UUID | None = None,
    status: StudentStatus | None = None,
    category: str | None = Query(default=None, max_length=20),
    gender: Gender | None = None,
    standing: AcademicStanding | None = None,
    has_holds: bool | None = None,
) -> dict[str, Any]:
    return {
        "q": q,
        "college_id": college_id,
        "department_id": department_id,
        "program_id": program_id,
        "batch_id": batch_id,
        "section_id": section_id,
        "status": status.value if status else None,
        "category": category,
        "gender": gender.value if gender else None,
        "standing": standing.value if standing else None,
        "has_holds": has_holds,
    }


def _ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


# ---- list / create ----------------------------------------------------------------------------------------------------
@router.get(
    "/students",
    summary="Students (self / wards / advisees / department / faculty / college / all per visibility)",
    response_model=Envelope[list[StudentListItem]],
)
async def list_students(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = SCOPE,
    filters: dict[str, Any] = Depends(_filters),
    principal: Principal = Depends(STUDENT_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await StudentService(db, principal, request).list_page(params, scope, **filters)
    return ok(rows, pagination=pagination, visibility=visibility)


@router.post(
    "/students",
    status_code=201,
    summary="Create a student (+ user, enrolment, term record, guardians) — seat limit enforced",
    response_model=Envelope[StudentCreateResult],
)
async def create_student(
    body: StudentCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("students", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await StudentService(db, principal, request).create(body), message="Student created")
    await store(request, response, db, 201)
    return response


# ---- self service (student portal) -----------------------------------------------------------------------------------
@router.get(
    "/students/me", summary="My student profile", response_model=Envelope[StudentDetailResponse], dependencies=PORTAL
)
async def my_profile(
    request: Request,
    principal: Principal = Depends(permission_required("students", "self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentService(db, principal, request).me())


@router.put(
    "/students/me",
    summary="Update my contact details / current address / emergency contact",
    response_model=Envelope[StudentDetailResponse],
    dependencies=[*PORTAL, feature_required("students.self_service_profile")],
)
async def update_my_profile(
    body: StudentSelfUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("students", "self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentService(db, principal, request).self_update(body), message="Profile updated")


@router.get(
    "/students/me/dashboard",
    summary="Student portal dashboard (profile, enrolment, term, holds, undertakings, quick links)",
    response_model=Envelope[StudentDashboard],
    dependencies=PORTAL,
)
async def my_dashboard(
    request: Request,
    principal: Principal = Depends(permission_required("students", "self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentPortalService(db, principal, request).my_dashboard())


@router.get(
    "/students/me/undertakings/pending",
    summary="Undertakings I still have to accept this academic year",
    response_model=Envelope[list[UndertakingStatus]],
    dependencies=UNDERTAKINGS,
)
async def my_pending_undertakings(
    request: Request,
    principal: Principal = Depends(any_permission_required(("students", "undertakings"), ("students", "self"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentRecordsService(db, principal, request).my_pending())


@router.post(
    "/students/me/undertakings",
    status_code=201,
    summary="E-accept an undertaking (records IP, user agent, optional signature)",
    response_model=Envelope[UndertakingOut],
    dependencies=UNDERTAKINGS,
)
async def accept_undertaking(
    body: UndertakingAccept,
    request: Request,
    principal: Principal = Depends(any_permission_required(("students", "undertakings"), ("students", "self"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await StudentRecordsService(db, principal, request).accept(
        body, _ip(request), request.headers.get("user-agent")
    )
    return ok(out, message="Undertaking accepted")


@router.get(
    "/students/me/id-card",
    summary="My ID card (QR token)",
    response_model=Envelope[IdCardResponse],
    dependencies=ID_CARDS,
)
async def my_id_card(
    request: Request,
    principal: Principal = Depends(permission_required("students", "id_card")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentRecordsService(db, principal, request).id_card())


@router.get("/students/me/id-card.pdf", summary="My ID card (PDF)", dependencies=ID_CARDS)
async def my_id_card_pdf(
    request: Request,
    principal: Principal = Depends(permission_required("students", "id_card")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content, name = await StudentRecordsService(db, principal, request).id_card_pdf()
    return Response(
        content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'}
    )


# ---- office tools -----------------------------------------------------------------------------------------------------
@router.get(
    "/students/stats",
    summary="Counts by status / programme / batch / category / gender / standing",
    response_model=Envelope[StudentStats],
)
async def student_stats(
    request: Request,
    college_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    principal: Principal = Depends(permission_required("students", "view_all")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentService(db, principal, request).stats(college_id, program_id, batch_id))


@router.get(
    "/students/export",
    summary="Export the filtered students (XLSX; PII masked without students:view_pii)",
    dependencies=BULK,
)
async def export_students(
    request: Request,
    scope: str | None = SCOPE,
    background: bool = Query(default=False, description="run as the students.export job (large exports)"),
    filters: dict[str, Any] = Depends(_filters),
    principal: Principal = Depends(any_permission_required(("students", "export"), ("students", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> Any:
    service = StudentService(db, principal, request)
    if background:
        return ok({"job_id": str(await service.enqueue_export(scope, filters))}, message="Export queued")
    content = await service.export_xlsx(scope, **filters)
    return Response(content, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="students.xlsx"'})


@router.get("/students/import-template", summary="Bulk-import template (XLSX)", dependencies=BULK)
async def import_template(principal: Principal = Depends(permission_required("students", "bulk_import"))) -> Response:
    return Response(
        StudentService.import_template(),
        media_type=XLSX,
        headers={"Content-Disposition": 'attachment; filename="students-import-template.xlsx"'},
    )


@router.post(
    "/students/bulk-import",
    summary="Bulk import from CSV / XLSX: dry_run=true validates (report), otherwise queues students.bulk_import",
    response_model=Envelope[BulkImportResult],
    dependencies=BULK,
)
async def bulk_import(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Query(default=False),
    principal: Principal = Depends(permission_required("students", "bulk_import")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read()
    service = StudentService(db, principal, request)
    if dry_run:
        return ok(await service.dry_run(content, file.filename), message="Dry run")
    return ok(await service.enqueue_import(content, file.filename), message="Import queued")


@router.post(
    "/students/id-cards",
    status_code=202,
    summary="Generate ID cards for the selected students (job → ZIP)",
    response_model=Envelope[dict[str, Any]],
    dependencies=ID_CARDS,
)
async def generate_id_cards(
    body: IdCardRequest,
    request: Request,
    principal: Principal = Depends(permission_required("students", "id_card")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    job_id = await StudentRecordsService(db, principal, request).enqueue_id_cards(body.student_ids)
    return ok({"job_id": str(job_id)}, message="ID cards queued")


# ---- one student ------------------------------------------------------------------------------------------------------
@router.get(
    "/students/{id}",
    summary="Student 360° (PII masked without students:view_pii)",
    response_model=Envelope[StudentDetailResponse],
)
async def get_student(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STUDENT_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await StudentService(db, principal, request).get(id))


@router.put(
    "/students/{id}",
    summary="Update a student (registrar; optimistic version)",
    response_model=Envelope[StudentDetailResponse],
)
async def update_student(
    id: uuid.UUID,
    body: StudentUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("students", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentService(db, principal, request).update(id, body), message="Student updated")


@router.post(
    "/students/{id}/status",
    summary="Change the status (allowed transitions only)",
    response_model=Envelope[StudentDetailResponse],
)
async def change_status(
    id: uuid.UUID,
    body: StatusChangeRequest,
    request: Request,
    principal: Principal = Depends(permission_required("students", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentService(db, principal, request).change_status(id, body), message="Status changed")


@router.post(
    "/students/{id}/photo",
    summary="Upload a student photo (office or the student)",
    response_model=Envelope[StudentDetailResponse],
)
async def student_photo(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(any_permission_required(("students", "update"), ("students", "self"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentService(db, principal, request).set_photo(id, file), message="Photo updated")


@router.get(
    "/students/{id}/id-card",
    summary="ID card data with the QR token",
    response_model=Envelope[IdCardResponse],
    dependencies=ID_CARDS,
)
async def student_id_card(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("students", "id_card")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentRecordsService(db, principal, request).id_card(id))


@router.get("/students/{id}/id-card.pdf", summary="ID card (PDF)", dependencies=ID_CARDS)
async def student_id_card_pdf(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("students", "id_card")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content, name = await StudentRecordsService(db, principal, request).id_card_pdf(id)
    return Response(
        content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'}
    )


# ---- guardians --------------------------------------------------------------------------------------------------------
@router.get(
    "/students/{id}/guardians", summary="Guardians", response_model=Envelope[list[GuardianOut]], dependencies=GUARDIANS
)
async def list_guardians(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(
        any_permission_required(("students", "view"), ("students", "view_all"), ("students", "self"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentRecordsService(db, principal, request).list_guardians(id))


@router.post(
    "/students/{id}/guardians",
    status_code=201,
    summary="Add a guardian (+ parent-portal user, reused across siblings)",
    response_model=Envelope[dict[str, Any]],
    dependencies=GUARDIANS,
)
async def add_guardian(
    id: uuid.UUID,
    body: GuardianIn,
    request: Request,
    principal: Principal = Depends(permission_required("students", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentRecordsService(db, principal, request).add_guardian(id, body), message="Guardian added")


@router.put(
    "/students/{id}/guardians/{gid}",
    summary="Update a guardian",
    response_model=Envelope[list[GuardianOut]],
    dependencies=GUARDIANS,
)
async def update_guardian(
    id: uuid.UUID,
    gid: uuid.UUID,
    body: GuardianUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("students", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await StudentRecordsService(db, principal, request).update_guardian(id, gid, body), message="Guardian updated"
    )


@router.delete(
    "/students/{id}/guardians/{gid}",
    summary="Remove a guardian",
    response_model=Envelope[list[GuardianOut]],
    dependencies=GUARDIANS,
)
async def delete_guardian(
    id: uuid.UUID,
    gid: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("students", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentRecordsService(db, principal, request).delete_guardian(id, gid), message="Guardian removed")


@router.put(
    "/students/{id}/guardian-consent",
    summary="Guardian-portal consent (registrar, or the adult student)",
    response_model=Envelope[dict[str, Any]],
    dependencies=GUARDIANS,
)
async def guardian_consent(
    id: uuid.UUID,
    body: GuardianPortalConsentUpdate,
    request: Request,
    principal: Principal = Depends(any_permission_required(("students", "update"), ("students", "self"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await StudentRecordsService(db, principal, request).set_consent(id, body.guardian_portal_consent)
    return ok(out, message="Consent updated")


@router.get(
    "/guardians/me/wards",
    summary="My wards (guardian-portal consent only)",
    response_model=Envelope[list[WardSummary]],
    dependencies=[feature_required("portals.parent")],
)
async def my_wards(
    request: Request,
    principal: Principal = Depends(permission_required("students", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentPortalService(db, principal, request).wards())


@router.get(
    "/guardians/me/wards/{student_id}/dashboard",
    summary="A ward's dashboard",
    response_model=Envelope[StudentDashboard],
    dependencies=[feature_required("portals.parent")],
)
async def ward_dashboard(
    student_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("students", "view")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentPortalService(db, principal, request).ward_dashboard(student_id))


# ---- documents --------------------------------------------------------------------------------------------------------
@router.get(
    "/students/{id}/documents",
    summary="Student documents",
    response_model=Envelope[list[DocumentOut]],
    dependencies=DOCUMENTS,
)
async def list_documents(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required(("students", "view"), ("students", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StudentRecordsService(db, principal, request).list_documents(id))


@router.post(
    "/students/{id}/documents",
    status_code=201,
    summary="Upload a document (office uploads are verified; own uploads wait for verification)",
    response_model=Envelope[DocumentOut],
    dependencies=DOCUMENTS,
)
async def add_document(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    doc_type: str = Form(..., max_length=60),
    expires_on: date | None = Form(default=None),
    remarks: str | None = Form(default=None, max_length=1000),
    principal: Principal = Depends(any_permission_required(("students", "update"), ("students", "view"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await StudentRecordsService(db, principal, request).add_document(id, file, doc_type, expires_on, remarks)
    return ok(out, message="Document uploaded")


@router.post(
    "/documents/{id}/verify",
    summary="Verify a student document",
    response_model=Envelope[DocumentOut],
    dependencies=DOCUMENTS,
)
async def verify_document(
    id: uuid.UUID,
    body: DocumentVerifyRequest,
    request: Request,
    principal: Principal = Depends(permission_required("students", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await StudentRecordsService(db, principal, request).verify_document(id, body.remarks),
        message="Document verified",
    )


@router.delete(
    "/documents/{id}", summary="Delete a student document", response_model=Envelope[None], dependencies=DOCUMENTS
)
async def delete_document(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required(("students", "update"), ("students", "view"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await StudentRecordsService(db, principal, request).delete_document(id)
    return ok(None, message="Document deleted")
