"""Course offerings, faculty allocation and registration — Prompts/09 §09.8 (router included with
``feature_required("registration.core")``; sub-features per route: {registration.self_service},
{registration.advisor_approval}, {registration.overrides}, {registration.waitlist},
{registration.elective_allocation}, {registration.arrears}).

Long-running work answers ``202`` + ``job_id`` (bulk generation above 200 offerings, roster export, bulk registration,
the real elective allocation run); dry runs answer inline. ``/registration/me…`` is the student cart.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, authenticated, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.enums.registration import AllocationMode, OfferingStatus, RegistrationStatus
from app.schemas.common import Envelope
from app.schemas.offerings import (
    BulkFromCurriculumRequest,
    BulkPreview,
    OfferingCreate,
    OfferingFacultyReplace,
    OfferingFacultyResult,
    OfferingResponse,
    OfferingStatusChange,
    OfferingTargetsReplace,
    OfferingUpdate,
    RosterItem,
    WindowCreate,
    WindowResponse,
    WindowStatusChange,
    WindowUpdate,
)
from app.schemas.registration import (
    AdvisorDecision,
    AllocationRunRequest,
    AllocationSummary,
    ArrearResponse,
    BulkRegisterRequest,
    CartItemAdd,
    CatalogResponse,
    ChoiceFormResponse,
    ChoiceFormSubmit,
    LockRequest,
    ManualAllocation,
    OverrideRequest,
    RegistrationListItem,
    RegistrationResponse,
    SubmitResponse,
    WaitlistResponse,
    WaiveRequest,
    WithdrawItemRequest,
)
from app.services.registration.elective_service import ArrearService, ElectiveService
from app.services.registration.offering_service import OfferingService, WindowService
from app.services.registration.registration_service import RegistrationService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["registration"])

OFF_VIEW = any_permission_required(("offerings", "view"), ("offerings", "view_all"))
OFF_CREATE = any_permission_required(("offerings", "create"), ("offerings", "manage"))
OFF_UPDATE = any_permission_required(("offerings", "update"), ("offerings", "manage"))
OFF_ALLOCATE = any_permission_required(("offerings", "allocate_faculty"), ("offerings", "manage"))
REG_MANAGE = permission_required("registration", "manage")
REG_SELF = permission_required("registration", "self")
REG_VIEW = any_permission_required(
    ("registration", "view"), ("registration", "view_all"), ("registration", "approve"), ("registration", "self")
)
REG_OVERRIDE = any_permission_required(("registration", "override"), ("registration", "manage"))
SELF_SERVICE = [feature_required("registration.self_service")]
ADVISOR = [feature_required("registration.advisor_approval")]
OVERRIDES = [feature_required("registration.overrides")]
WAITLIST = [feature_required("registration.waitlist")]
ELECTIVES = [feature_required("registration.elective_allocation")]
ARREARS = [feature_required("registration.arrears")]
SCOPE = Query(default=None, pattern="^(self|own|mine|advisees|department|faculty|college|all)$")


def _queued(data: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(data, message=message))


# ---- offerings --------------------------------------------------------------------------------------------------------
@router.get("/course-offerings", summary="Course offerings", response_model=Envelope[list[OfferingResponse]])
async def list_offerings(
    request: Request,
    term_id: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    staff_id: uuid.UUID | None = None,
    status: OfferingStatus | None = None,
    q: str | None = Query(default=None, max_length=60),
    scope: str | None = Query(default=None, pattern="^(mine|self|own|department|all)$"),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(OFF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await OfferingService(db, principal, request).list_page(
        params,
        scope,
        term_id=term_id,
        college_id=college_id,
        department_id=department_id,
        course_id=course_id,
        staff_id=staff_id,
        status=status.value if status else None,
        q=q,
    )
    return ok(rows, pagination=page, visibility=vis)


@router.post(
    "/course-offerings", status_code=201, summary="Create an offering", response_model=Envelope[OfferingResponse]
)
async def create_offering(
    body: OfferingCreate,
    request: Request,
    principal: Principal = Depends(OFF_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferingService(db, principal, request).create(body), message="Offering created")


@router.post(
    "/course-offerings/bulk-from-curriculum",
    summary="Generate offerings from the curriculum (dry_run → preview; > 200 new → job)",
    response_model=Envelope[BulkPreview],
)
async def bulk_from_curriculum(
    body: BulkFromCurriculumRequest,
    request: Request,
    dry_run: bool = Query(default=True),
    principal: Principal = Depends(any_permission_required(("offerings", "bulk_create"), ("offerings", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = OfferingService(db, principal, request)
    if dry_run:
        return ok(await svc.bulk_from_curriculum(body, dry_run=True), message="Preview")
    out = await svc.enqueue_bulk(body)
    if out.job_id:
        return _queued(out.model_dump(mode="json"), "Bulk generation queued")
    return ok(out, message=f"{out.to_create} offering(s) created")


@router.get("/course-offerings/mine", summary="My offerings (faculty)", response_model=Envelope[list[OfferingResponse]])
async def my_offerings(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferingService(db, principal, request).mine(term_id))


@router.get("/course-offerings/{id}", summary="An offering", response_model=Envelope[OfferingResponse])
async def get_offering(
    id: uuid.UUID, request: Request, principal: Principal = Depends(OFF_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OfferingService(db, principal, request).get(id))


@router.put("/course-offerings/{id}", summary="Update an offering", response_model=Envelope[OfferingResponse])
async def update_offering(
    id: uuid.UUID,
    body: OfferingUpdate,
    request: Request,
    principal: Principal = Depends(OFF_UPDATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferingService(db, principal, request).update(id, body), message="Offering updated")


@router.post(
    "/course-offerings/{id}/status", summary="Change the offering status", response_model=Envelope[OfferingResponse]
)
async def offering_status(
    id: uuid.UUID,
    body: OfferingStatusChange,
    request: Request,
    principal: Principal = Depends(OFF_UPDATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferingService(db, principal, request).change_status(id, body), message="Status changed")


@router.delete("/course-offerings/{id}", summary="Cancel an offering", response_model=Envelope[OfferingResponse])
async def cancel_offering(
    id: uuid.UUID, request: Request, principal: Principal = Depends(OFF_UPDATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    body = OfferingStatusChange(status=OfferingStatus.CANCELLED, reason="cancelled")
    return ok(await OfferingService(db, principal, request).change_status(id, body), message="Offering cancelled")


@router.put(
    "/course-offerings/{id}/faculty", summary="Replace the faculty", response_model=Envelope[OfferingFacultyResult]
)
async def offering_faculty(
    id: uuid.UUID,
    body: OfferingFacultyReplace,
    request: Request,
    principal: Principal = Depends(OFF_ALLOCATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferingService(db, principal, request).replace_faculty(id, body), message="Faculty saved")


@router.put(
    "/course-offerings/{id}/targets", summary="Replace the target batches", response_model=Envelope[OfferingResponse]
)
async def offering_targets(
    id: uuid.UUID,
    body: OfferingTargetsReplace,
    request: Request,
    principal: Principal = Depends(OFF_ALLOCATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferingService(db, principal, request).replace_targets(id, body), message="Targets saved")


@router.get("/course-offerings/{id}/roster", summary="Roster", response_model=Envelope[list[RosterItem]])
async def offering_roster(
    id: uuid.UUID,
    request: Request,
    include_waitlist: bool = False,
    principal: Principal = Depends(OFF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferingService(db, principal, request).roster(id, include_waitlist))


@router.get(
    "/course-offerings/{id}/roster/export",
    status_code=202,
    summary="Roster XLSX (job)",
    response_model=Envelope[dict[str, str]],
)
async def offering_roster_export(
    id: uuid.UUID, request: Request, principal: Principal = Depends(OFF_VIEW), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    job_id = await OfferingService(db, principal, request).enqueue_roster_export(id)
    return _queued({"job_id": str(job_id)}, "Roster export queued")


# ---- windows ----------------------------------------------------------------------------------------------------------
@router.get("/registration-windows", summary="Registration windows", response_model=Envelope[list[WindowResponse]])
async def list_windows(
    request: Request,
    term_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(scheduled|open|closed)$"),
    principal: Principal = Depends(any_permission_required(("registration", "manage"), ("registration", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WindowService(db, principal, request).list_windows(term_id, status))


@router.post(
    "/registration-windows", status_code=201, summary="Create a window", response_model=Envelope[WindowResponse]
)
async def create_window(
    body: WindowCreate, request: Request, principal: Principal = Depends(REG_MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await WindowService(db, principal, request).create(body), message="Window created")


@router.put("/registration-windows/{id}", summary="Update a window", response_model=Envelope[WindowResponse])
async def update_window(
    id: uuid.UUID,
    body: WindowUpdate,
    request: Request,
    principal: Principal = Depends(REG_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WindowService(db, principal, request).update(id, body), message="Window updated")


@router.post(
    "/registration-windows/{id}/status", summary="Open / close a window", response_model=Envelope[WindowResponse]
)
async def window_status(
    id: uuid.UUID,
    body: WindowStatusChange,
    request: Request,
    principal: Principal = Depends(REG_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await WindowService(db, principal, request).change_status(id, body.status.value), message="Window updated"
    )


# ---- student cart -------------------------------------------------------------------------------------------------------
@router.get(
    "/registration/me/catalog",
    summary="My registration catalog",
    response_model=Envelope[CatalogResponse],
    dependencies=SELF_SERVICE,
)
async def my_catalog(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(REG_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).catalog(term_id))


@router.get(
    "/registration/me",
    summary="My registration",
    response_model=Envelope[RegistrationResponse | None],
    dependencies=SELF_SERVICE,
)
async def my_registration(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(REG_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).mine(term_id))


@router.get(
    "/registration/me/history",
    summary="My registrations",
    response_model=Envelope[list[RegistrationResponse]],
    dependencies=SELF_SERVICE,
)
async def my_history(
    request: Request, principal: Principal = Depends(REG_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).history_me())


@router.post(
    "/registration/me/items",
    status_code=201,
    summary="Add to the cart",
    response_model=Envelope[RegistrationResponse],
    dependencies=SELF_SERVICE,
)
async def add_item(
    body: CartItemAdd, request: Request, principal: Principal = Depends(REG_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).add_item(body), message="Added")


@router.delete(
    "/registration/me/items/{item_id}",
    summary="Drop from the cart",
    response_model=Envelope[RegistrationResponse],
    dependencies=SELF_SERVICE,
)
async def remove_item(
    item_id: uuid.UUID, request: Request, principal: Principal = Depends(REG_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).remove_item(item_id), message="Dropped")


@router.post(
    "/registration/me/submit",
    summary="Submit (Idempotency-Key)",
    response_model=Envelope[SubmitResponse],
    dependencies=SELF_SERVICE,
)
async def submit(
    request: Request,
    term_id: uuid.UUID | None = None,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(REG_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await RegistrationService(db, principal, request).submit(term_id)
    response = ok(out.model_dump(mode="json"), message="Submitted")
    await store(request, response, db)
    return response


@router.get(
    "/registration/me/waitlist",
    summary="My waitlist entries",
    response_model=Envelope[list[WaitlistResponse]],
    dependencies=WAITLIST,
)
async def my_waitlist(
    request: Request, principal: Principal = Depends(REG_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).my_waitlists())


@router.post(
    "/registration/me/waitlist/{id}/accept",
    summary="Accept a seat offer",
    response_model=Envelope[RegistrationResponse],
    dependencies=WAITLIST,
)
async def accept_waitlist(
    id: uuid.UUID, request: Request, principal: Principal = Depends(REG_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).accept_waitlist(id), message="Seat accepted")


# ---- staff views ------------------------------------------------------------------------------------------------------------
@router.get(
    "/registration",
    summary="Registrations (advisees | department | all)",
    response_model=Envelope[list[RegistrationListItem]],
)
async def list_registrations(
    request: Request,
    scope: str | None = SCOPE,
    term_id: uuid.UUID | None = None,
    status: RegistrationStatus | None = None,
    batch_id: uuid.UUID | None = None,
    section_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=60),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(REG_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await RegistrationService(db, principal, request).list_page(
        params,
        scope,
        term_id=term_id,
        status=status.value if status else None,
        batch_id=batch_id,
        section_id=section_id,
        department_id=department_id,
        q=q,
    )
    return ok(rows, pagination=page, visibility=vis)


@router.post(
    "/registration/bulk-register",
    status_code=202,
    summary="Bulk register a batch (job)",
    response_model=Envelope[dict[str, str]],
)
async def bulk_register(
    body: BulkRegisterRequest,
    request: Request,
    principal: Principal = Depends(any_permission_required(("registration", "bulk"), ("registration", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    job_id = await RegistrationService(db, principal, request).enqueue_bulk(body)
    return _queued({"job_id": str(job_id)}, "Bulk registration queued")


@router.get("/registration/{id}", summary="A registration", response_model=Envelope[RegistrationResponse])
async def get_registration(
    id: uuid.UUID, request: Request, principal: Principal = Depends(REG_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).get(id))


async def _decide(
    id: uuid.UUID, body: AdvisorDecision, request: Request, principal: Principal, db: AsyncSession
) -> dict[str, Any]:
    out = await RegistrationService(db, principal, request).decide(id, body)
    return ok(out, message=f"Registration {out.status.replace('_', ' ')}")


APPROVER = permission_required("registration", "approve")


@router.post(
    "/registration/{id}/approve",
    summary="Advisor approves",
    response_model=Envelope[RegistrationResponse],
    dependencies=ADVISOR,
)
async def approve_registration(
    id: uuid.UUID,
    request: Request,
    body: AdvisorDecision | None = None,
    principal: Principal = Depends(APPROVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    body = AdvisorDecision(
        decision="approve", comment=body.comment if body else None, item_decisions=body.item_decisions if body else []
    )
    return await _decide(id, body, request, principal, db)


@router.post(
    "/registration/{id}/reject",
    summary="Advisor rejects",
    response_model=Envelope[RegistrationResponse],
    dependencies=ADVISOR,
)
async def reject_registration(
    id: uuid.UUID,
    body: AdvisorDecision,
    request: Request,
    principal: Principal = Depends(APPROVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    body = AdvisorDecision(decision="reject", comment=body.comment, item_decisions=body.item_decisions)
    return await _decide(id, body, request, principal, db)


@router.post(
    "/registration/{id}/request-changes",
    summary="Advisor requests changes",
    response_model=Envelope[RegistrationResponse],
    dependencies=ADVISOR,
)
async def request_changes(
    id: uuid.UUID,
    body: AdvisorDecision,
    request: Request,
    principal: Principal = Depends(APPROVER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    body = AdvisorDecision(decision="request_changes", comment=body.comment, item_decisions=body.item_decisions)
    return await _decide(id, body, request, principal, db)


@router.post(
    "/registration/{id}/override",
    summary="Registrar override",
    response_model=Envelope[RegistrationResponse],
    dependencies=OVERRIDES,
)
async def override(
    id: uuid.UUID,
    body: OverrideRequest,
    request: Request,
    principal: Principal = Depends(REG_OVERRIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).override(id, body), message="Override recorded")


@router.post(
    "/registration/{id}/withdraw-item/{item_id}",
    summary="Withdraw an item (W)",
    response_model=Envelope[RegistrationResponse],
    dependencies=OVERRIDES,
)
async def withdraw_item(
    id: uuid.UUID,
    item_id: uuid.UUID,
    body: WithdrawItemRequest,
    request: Request,
    principal: Principal = Depends(REG_OVERRIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RegistrationService(db, principal, request).withdraw_item(id, item_id, body.reason), message="Withdrawn"
    )


@router.post(
    "/registration/{id}/lock", summary="Lock", response_model=Envelope[RegistrationResponse], dependencies=OVERRIDES
)
async def lock(
    id: uuid.UUID,
    request: Request,
    body: LockRequest | None = None,
    principal: Principal = Depends(REG_OVERRIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RegistrationService(db, principal, request).set_lock(id, True, body.reason if body else None),
        message="Locked",
    )


@router.post(
    "/registration/{id}/unlock", summary="Unlock", response_model=Envelope[RegistrationResponse], dependencies=OVERRIDES
)
async def unlock(
    id: uuid.UUID,
    request: Request,
    body: LockRequest | None = None,
    principal: Principal = Depends(REG_OVERRIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RegistrationService(db, principal, request).set_lock(id, False, body.reason if body else None),
        message="Unlocked",
    )


# ---- electives ------------------------------------------------------------------------------------------------------------
@router.get(
    "/elective-baskets/{id}/choices/me",
    summary="My choice form",
    response_model=Envelope[ChoiceFormResponse | None],
    dependencies=ELECTIVES,
)
async def my_choices(
    id: uuid.UUID,
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(REG_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ElectiveService(db, principal, request).my_form(id, term_id))


@router.post(
    "/elective-baskets/{id}/choices/me",
    status_code=201,
    summary="Submit choices",
    response_model=Envelope[ChoiceFormResponse],
    dependencies=ELECTIVES,
)
async def submit_choices(
    id: uuid.UUID,
    body: ChoiceFormSubmit,
    request: Request,
    principal: Principal = Depends(REG_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await ElectiveService(db, principal, request).submit_form(id, body, replace=False), message="Choices submitted"
    )


@router.put(
    "/elective-baskets/{id}/choices/me",
    summary="Replace choices",
    response_model=Envelope[ChoiceFormResponse],
    dependencies=ELECTIVES,
)
async def replace_choices(
    id: uuid.UUID,
    body: ChoiceFormSubmit,
    request: Request,
    principal: Principal = Depends(REG_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await ElectiveService(db, principal, request).submit_form(id, body, replace=True), message="Choices replaced"
    )


ALLOCATOR = any_permission_required(("registration", "allocate"), ("registration", "manage"))


@router.get(
    "/elective-baskets/{id}/choices",
    summary="Choice forms of a basket",
    response_model=Envelope[list[ChoiceFormResponse]],
    dependencies=ELECTIVES,
)
async def basket_choices(
    id: uuid.UUID,
    term_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(ALLOCATOR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ElectiveService(db, principal, request).basket_forms(id, term_id))


@router.post(
    "/elective-baskets/{id}/allocate",
    summary="Allocation run (dry_run inline; real → job)",
    response_model=Envelope[AllocationSummary],
    dependencies=ELECTIVES,
)
async def allocate(
    id: uuid.UUID,
    request: Request,
    term_id: uuid.UUID,
    dry_run: bool = Query(default=True),
    mode: AllocationMode | None = None,
    body: AllocationRunRequest | None = None,
    principal: Principal = Depends(ALLOCATOR),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ElectiveService(db, principal, request)
    m = mode or (body.mode if body else None)
    seed = body.seed if body else None
    if dry_run:
        return ok(await svc.allocate(id, term_id, m.value if m else None, dry_run=True, seed=seed), message="Dry run")
    job_id = await svc.enqueue_allocate(id, term_id, m.value if m else None, seed)
    return _queued({"job_id": str(job_id), "basket_id": str(id), "term_id": str(term_id)}, "Allocation queued")


@router.post(
    "/elective-baskets/{id}/manual",
    summary="Manually allocate a form",
    response_model=Envelope[ChoiceFormResponse],
    dependencies=ELECTIVES,
)
async def manual_allocate(
    id: uuid.UUID,
    body: ManualAllocation,
    request: Request,
    principal: Principal = Depends(ALLOCATOR),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ElectiveService(db, principal, request).manual_assign(id, body), message="Allocated")


@router.get(
    "/elective-allocation-runs/{id}",
    summary="An allocation run",
    response_model=Envelope[dict[str, Any]],
    dependencies=ELECTIVES,
)
async def allocation_run(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ALLOCATOR), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ElectiveService(db, principal, request).get_run(id))


# ---- arrears / history -------------------------------------------------------------------------------------------------------
STUDENT_VIEW = any_permission_required(("students", "view"), ("students", "view_all"))


@router.get("/arrears", summary="Arrears register", response_model=Envelope[list[ArrearResponse]], dependencies=ARREARS)
async def list_arrears(
    request: Request,
    scope: str | None = SCOPE,
    status: str | None = Query(default=None, pattern="^(open|registered|cleared|waived)$"),
    q: str | None = Query(default=None, max_length=60),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(
        any_permission_required(
            ("registration", "view"),
            ("registration", "view_all"),
            ("registration", "approve"),
            ("students", "view_all"),
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await ArrearService(db, principal, request).list_page(params, scope, status=status, q=q)
    return ok(rows, pagination=page, visibility=vis)


@router.get("/arrears/me", summary="My arrears", response_model=Envelope[list[ArrearResponse]], dependencies=ARREARS)
async def my_arrears(
    request: Request,
    principal: Principal = Depends(permission_required("students", "self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ArrearService(db, principal, request).mine_list())


@router.post(
    "/arrears/{id}/waive", summary="Waive an arrear", response_model=Envelope[ArrearResponse], dependencies=ARREARS
)
async def waive_arrear(
    id: uuid.UUID,
    body: WaiveRequest,
    request: Request,
    principal: Principal = Depends(permission_required("students", "manage")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ArrearService(db, principal, request).waive(id, body), message="Arrear waived")


@router.get(
    "/students/{id}/arrears",
    summary="A student's arrears",
    response_model=Envelope[list[ArrearResponse]],
    dependencies=ARREARS,
)
async def student_arrears(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STUDENT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ArrearService(db, principal, request).for_student(id))


@router.get(
    "/students/{id}/registrations",
    summary="A student's registration history",
    response_model=Envelope[list[RegistrationResponse]],
)
async def student_registrations(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STUDENT_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RegistrationService(db, principal, request).history(id))
