"""Courses — Prompts/05 §05.8 (router included with ``feature_required("academics.regulations")`` — a course is
owned by a regulation). ``/courses/export`` answers the XLSX directly; ``/courses/bulk-import`` enqueues the job
``courses.bulk_import`` (202 + job id, report in ``background_jobs.result``)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.academics import CourseStatus, CourseType
from app.schemas.common import Envelope
from app.schemas.curriculum import (
    CourseBulkImportRequest,
    CourseCreate,
    CourseResponse,
    CourseStatusChange,
    CourseUpdate,
    PrerequisiteSet,
)
from app.services.course_service import CourseService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["academics"])

COURSE_READ = any_permission_required(("courses", "view"), ("courses", "view_all"))
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/courses", summary="Courses (search code/title, filters)", response_model=Envelope[list[CourseResponse]])
async def list_courses(
    request: Request,
    params: PageParams = Depends(page_params),
    scope: str | None = Query(default=None, pattern="^(department|college|all)$"),
    regulation_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    course_type: CourseType | None = None,
    status: CourseStatus | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(COURSE_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await CourseService(db, principal, request).list_page(
        params,
        scope,
        regulation_id=regulation_id,
        department_id=department_id,
        course_type=course_type.value if course_type else None,
        status=status.value if status else None,
        q=q,
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get("/courses/export", summary="Export the filtered courses (XLSX)")
async def export_courses(
    request: Request,
    regulation_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    course_type: CourseType | None = None,
    status: CourseStatus | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(any_permission_required(("courses", "export"), ("courses", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content = await CourseService(db, principal, request).export_xlsx(
        regulation_id=regulation_id,
        department_id=department_id,
        course_type=course_type.value if course_type else None,
        status=status.value if status else None,
        q=q,
    )
    return Response(content, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="courses.xlsx"'})


@router.post(
    "/courses/bulk-import",
    status_code=202,
    summary="Bulk import courses from CSV (job)",
    response_model=Envelope[dict[str, Any]],
)
async def bulk_import_courses(
    body: CourseBulkImportRequest,
    request: Request,
    principal: Principal = Depends(permission_required("courses", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CourseService(db, principal, request).enqueue_bulk_import(body), message="Import queued")


@router.post("/courses", status_code=201, summary="Create a course (draft)", response_model=Envelope[CourseResponse])
async def create_course(
    body: CourseCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("courses", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await CourseService(db, principal, request).create(body), message="Course created")
    await store(request, response, db, 201)
    return response


@router.get("/courses/{id}", summary="Course detail (with prerequisites)", response_model=Envelope[CourseResponse])
async def get_course(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(COURSE_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CourseService(db, principal, request).get(id))


@router.put("/courses/{id}", summary="Update a course", response_model=Envelope[CourseResponse])
async def update_course(
    id: uuid.UUID,
    body: CourseUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("courses", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CourseService(db, principal, request).update(id, body), message="Course saved")


@router.delete("/courses/{id}", summary="Delete a draft course (soft)", response_model=Envelope[None])
async def delete_course(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("courses", "delete")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await CourseService(db, principal, request).delete(id)
    return ok(None, message="Course deleted")


@router.post("/courses/{id}/status", summary="Move draft → approved → retired", response_model=Envelope[CourseResponse])
async def change_course_status(
    id: uuid.UUID,
    body: CourseStatusChange,
    request: Request,
    principal: Principal = Depends(any_permission_required(("courses", "update"), ("courses", "approve"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CourseService(db, principal, request).change_status(id, body), message="Status changed")


@router.put(
    "/courses/{id}/prerequisites",
    summary="Replace pre-/co-/anti-requisites (acyclic)",
    response_model=Envelope[CourseResponse],
)
async def set_prerequisites(
    id: uuid.UUID,
    body: PrerequisiteSet,
    request: Request,
    principal: Principal = Depends(permission_required("courses", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CourseService(db, principal, request).set_prerequisites(id, body), message="Prerequisites saved")
