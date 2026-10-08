"""Enrolments, term records, promotion, NEP exit / re-entry, holds, academic standing and transfers — Prompts/07 §07.8
(router included with ``feature_required("students.core")``; per route {academics.nep_exit_reentry},
{students.holds}, {students.academic_standing}, {students.transfers_migration}).

``POST /batches/{id}/promote?dry_run=true`` answers the preview; without ``dry_run`` it queues the job
``students.promote`` (202 + ``job_id``; the tray shows the progress). Hold placement is open to ``students:holds`` and,
for their own hold type, to the library (``library:manage``) and hostel (``hostel:manage``) offices.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.students import HoldType, TransferStatus, TransferType
from app.schemas.common import Envelope
from app.schemas.students import (
    EnrollmentResponse,
    ExitRequest,
    HoldCreate,
    HoldReleaseRequest,
    HoldResponse,
    PromoteBatchRequest,
    PromotionPreview,
    ReentryRequest,
    RegulationChange,
    SectionChange,
    StandingResponse,
    TermRecordResponse,
    TransferComplete,
    TransferCreate,
    TransferDecision,
    TransferResponse,
)
from app.services.enrollment_service import EnrollmentService
from app.services.hold_service import HoldService
from app.services.transfer_service import TransferService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["students"])

STUDENT_READ = any_permission_required(("students", "view"), ("students", "view_all"))
NEP = [feature_required("academics.nep_exit_reentry")]
HOLDS = [feature_required("students.holds")]
STANDING = [feature_required("students.academic_standing")]
TRANSFERS = [feature_required("students.transfers_migration")]
# approvers: the registrar (students:transfer) and later steps (principal / VC hold students:view_all)
STEP_ACTOR = any_permission_required(("students", "transfer"), ("students", "view_all"))
SCOPE = Query(default=None, pattern="^(self|own|mine|department|faculty|college|all)$")
HOLD_WRITE = any_permission_required(("students", "holds"), ("library", "manage"), ("hostel", "manage"))


# ---- enrolments / term records ----------------------------------------------------------------------------------------
@router.get(
    "/students/{id}/enrollments", summary="Enrolment history", response_model=Envelope[list[EnrollmentResponse]]
)
async def student_enrollments(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STUDENT_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EnrollmentService(db, principal, request).for_student(id))


@router.get("/enrollments/{id}", summary="An enrolment", response_model=Envelope[EnrollmentResponse])
async def get_enrollment(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STUDENT_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EnrollmentService(db, principal, request).get(id))


@router.get(
    "/enrollments/{id}/term-records",
    summary="Term records of an enrolment",
    response_model=Envelope[list[TermRecordResponse]],
)
async def term_records(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STUDENT_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EnrollmentService(db, principal, request).term_records(id))


@router.post(
    "/enrollments/{id}/section",
    summary="Move to another section of the batch",
    response_model=Envelope[EnrollmentResponse],
)
async def change_section(
    id: uuid.UUID,
    body: SectionChange,
    request: Request,
    principal: Principal = Depends(permission_required("students", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnrollmentService(db, principal, request).change_section(id, body), message="Section changed")


@router.post(
    "/enrollments/{id}/change-regulation",
    summary="Re-pin the enrolment to another regulation (course equivalence → internal_prior credit transfers)",
    response_model=Envelope[EnrollmentResponse],
)
async def change_regulation(
    id: uuid.UUID,
    body: RegulationChange,
    request: Request,
    principal: Principal = Depends(permission_required("students", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnrollmentService(db, principal, request).change_regulation(id, body), message="Regulation changed")


@router.post(
    "/batches/{id}/promote",
    summary="Promote a batch to the next term (dry_run → preview; otherwise the students.promote job)",
    response_model=Envelope[PromotionPreview],
)
async def promote_batch(
    id: uuid.UUID,
    request: Request,
    body: PromoteBatchRequest | None = None,
    dry_run: bool | None = Query(default=None),
    principal: Principal = Depends(permission_required("batches", "promote")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    preview = await EnrollmentService(db, principal, request).promote(
        id, body or PromoteBatchRequest(), dry_run=dry_run
    )
    if preview.dry_run:
        return ok(preview, message="Promotion preview")
    return JSONResponse(status_code=202, content=ok(preview, message="Promotion queued"))


@router.post(
    "/enrollments/{id}/exit",
    summary="NEP exit with an award at an exit point",
    response_model=Envelope[EnrollmentResponse],
    dependencies=NEP,
)
async def exit_enrollment(
    id: uuid.UUID,
    body: ExitRequest,
    request: Request,
    principal: Principal = Depends(permission_required("students", "exit")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnrollmentService(db, principal, request).exit(id, body), message="Exit recorded")


@router.post(
    "/students/{id}/reentry",
    status_code=201,
    summary="NEP re-entry (new exit_reentry enrolment, prior credits carried)",
    response_model=Envelope[EnrollmentResponse],
    dependencies=NEP,
)
async def reentry(
    id: uuid.UUID,
    body: ReentryRequest,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("students", "exit")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await EnrollmentService(db, principal, request).reentry(id, body), message="Re-entry recorded")
    await store(request, response, db, 201)
    return response


# ---- holds ------------------------------------------------------------------------------------------------------------
@router.get(
    "/student-holds",
    summary="Holds queue (open / released)",
    response_model=Envelope[list[HoldResponse]],
    dependencies=HOLDS,
)
async def holds_queue(
    request: Request,
    params: PageParams = Depends(page_params),
    status: str | None = Query(default="open", pattern="^(open|released|all)$"),
    hold_type: HoldType | None = None,
    q: str | None = Query(default=None, max_length=120),
    scope: str | None = SCOPE,
    principal: Principal = Depends(
        any_permission_required(
            ("students", "holds"), ("students", "view_all"), ("library", "manage"), ("hostel", "manage")
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await HoldService(db, principal, request).queue(
        params,
        status=None if status == "all" else status,
        hold_type=hold_type.value if hold_type else None,
        q=q,
        scope=scope,
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get(
    "/students/{id}/holds",
    summary="A student's holds (open first)",
    response_model=Envelope[list[HoldResponse]],
    dependencies=HOLDS,
)
async def student_holds(
    id: uuid.UUID,
    request: Request,
    include_released: bool = True,
    principal: Principal = Depends(
        any_permission_required(("students", "holds"), ("students", "view"), ("students", "view_all"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HoldService(db, principal, request).for_student(id, include_released))


@router.post(
    "/students/{id}/holds",
    status_code=201,
    summary="Place a hold",
    response_model=Envelope[HoldResponse],
    dependencies=HOLDS,
)
async def place_hold(
    id: uuid.UUID,
    body: HoldCreate,
    request: Request,
    principal: Principal = Depends(HOLD_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HoldService(db, principal, request).place(id, body), message="Hold placed")


@router.post(
    "/student-holds/{id}/release",
    summary="Release a hold (reason required)",
    response_model=Envelope[HoldResponse],
    dependencies=HOLDS,
)
async def release_hold(
    id: uuid.UUID,
    body: HoldReleaseRequest,
    request: Request,
    principal: Principal = Depends(HOLD_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await HoldService(db, principal, request).release(id, body), message="Hold released")


# ---- standing ---------------------------------------------------------------------------------------------------------
@router.get(
    "/students/{id}/standing",
    summary="Academic standing + history",
    response_model=Envelope[StandingResponse],
    dependencies=STANDING,
)
async def standing(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STUDENT_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EnrollmentService(db, principal, request).standing(id))


# ---- transfers --------------------------------------------------------------------------------------------------------
@router.get(
    "/student-transfers",
    summary="Transfer / migration requests",
    response_model=Envelope[list[TransferResponse]],
    dependencies=TRANSFERS,
)
async def list_transfers(
    request: Request,
    params: PageParams = Depends(page_params),
    status: TransferStatus | None = None,
    transfer_type: TransferType | None = None,
    q: str | None = Query(default=None, max_length=120),
    scope: str | None = SCOPE,
    principal: Principal = Depends(any_permission_required(("students", "transfer"), ("students", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await TransferService(db, principal, request).list_page(
        params,
        status=status.value if status else None,
        transfer_type=transfer_type.value if transfer_type else None,
        q=q,
        scope=scope,
    )
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get(
    "/students/{id}/transfers",
    summary="A student's transfer requests",
    response_model=Envelope[list[TransferResponse]],
    dependencies=TRANSFERS,
)
async def student_transfers(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(
        any_permission_required(("students", "transfer"), ("students", "view"), ("students", "view_all"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TransferService(db, principal, request).for_student(id))


@router.post(
    "/students/{id}/transfers",
    status_code=201,
    summary="Request a transfer / migration (workflow students.transfer)",
    response_model=Envelope[TransferResponse],
    dependencies=TRANSFERS,
)
async def request_transfer(
    id: uuid.UUID,
    body: TransferCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(any_permission_required(("students", "transfer"), ("students", "self"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await TransferService(db, principal, request).create(id, body), message="Transfer requested")
    await store(request, response, db, 201)
    return response


@router.post(
    "/student-transfers/{id}/approve",
    summary="Approve the current step",
    response_model=Envelope[TransferResponse],
    dependencies=TRANSFERS,
)
async def approve_transfer(
    id: uuid.UUID,
    request: Request,
    body: TransferDecision | None = None,
    principal: Principal = Depends(STEP_ACTOR),  # the workflow engine checks the step assignee
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await TransferService(db, principal, request).decide(id, "approve", body.comment if body else None)
    return ok(out, message="Approved")


@router.post(
    "/student-transfers/{id}/reject",
    summary="Reject the request",
    response_model=Envelope[TransferResponse],
    dependencies=TRANSFERS,
)
async def reject_transfer(
    id: uuid.UUID,
    request: Request,
    body: TransferDecision | None = None,
    principal: Principal = Depends(STEP_ACTOR),  # the workflow engine checks the step assignee
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await TransferService(db, principal, request).decide(id, "reject", body.comment if body else None)
    return ok(out, message="Rejected")


@router.post(
    "/student-transfers/{id}/complete",
    summary="Complete an approved request (certificate numbers, student transferred)",
    response_model=Envelope[TransferResponse],
    dependencies=TRANSFERS,
)
async def complete_transfer(
    id: uuid.UUID,
    request: Request,
    body: TransferComplete | None = None,
    principal: Principal = Depends(permission_required("students", "transfer")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await TransferService(db, principal, request).complete(id, body or TransferComplete())
    return ok(out, message="Transfer completed")
