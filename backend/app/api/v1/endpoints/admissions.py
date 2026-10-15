"""Admissions — Prompts/08 §08.8 (router included with ``feature_required("admissions.cycles")``; sub-features per
route: {admissions.seat_matrix}, {admissions.online_application}, {admissions.document_verification},
{admissions.merit_lists}, {admissions.counselling_allotment}, {admissions.offers}, {admissions.entrance_import},
{admissions.enquiry_crm}).

Long-running work answers ``202`` + ``job_id`` (merit generation, the real allotment run, the counselling CSV import,
the export); the allotment and import dry runs answer inline. ``/applicants/me…`` is the applicant portal (the
``applicant`` role holds ``admissions:create|view``; a staff caller without an application gets 404).

``public_router`` (``PUBLIC_ROUTES``): cycle listing / details, the account start with OTP, the masked public merit
list and the website enquiry form — the tenant is resolved from ``?institution=<slug>`` / the host / ``X-Institution-Id``
and pinned for RLS here; the feature is checked by the tenant dependency.
"""

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.core.rate_limit import rate_limited, verify_captcha
from app.db.session import bind_tenant, get_db, set_tenant
from app.enums.admissions import ApplicantStatus, CycleLevel, CycleStatus, EnquirySource, EnquiryStage
from app.models.platform import Institution
from app.repositories.institution_repository import InstitutionRepository
from app.schemas.admissions import (
    AdmitRequest,
    AdmitResult,
    AllotmentDecision,
    AllotmentResponse,
    AllotmentSummary,
    ApplicantListItem,
    ApplicantResponse,
    ApplicantSelfResponse,
    ApplicantStatusChange,
    ApplicantUpdate,
    CycleCreate,
    CycleProgramOut,
    CycleProgramsReplace,
    CycleResponse,
    CycleStatusChange,
    CycleUpdate,
    DocumentVerifyRequest,
    EnquiryAssign,
    EnquiryConvert,
    EnquiryCreate,
    EnquiryResponse,
    EnquiryStats,
    EnquiryUpdate,
    ImportResult,
    MeritGenerateRequest,
    MeritListDetail,
    MeritListResponse,
    OfferCreate,
    OfferResponse,
    PaymentResult,
    PreferencesReplace,
    PublicCycleInfo,
    PublicEnquiryCreate,
    PublicMeritList,
    PublicStartRequest,
    PublicStartResult,
    RoundCreate,
    RoundResponse,
    RoundStatusChange,
    RoundUpdate,
    SeatMatrixReplace,
    SeatStatusResponse,
    TimelineEntry,
    WithdrawalRequest,
    WithdrawalResult,
)
from app.schemas.common import Envelope
from app.services.admissions.application_service import ApplicationService
from app.services.admissions.counselling_service import CounsellingService
from app.services.admissions.cycle_service import CycleService
from app.services.admissions.enquiry_service import EnquiryService
from app.services.admissions.merit_service import MeritService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["admissions"])
public_router = APIRouter(prefix="/public", tags=["public"])

VIEW = permission_required("admissions", "view")
MANAGE = permission_required("admissions", "manage")
VIEW_ALL = permission_required("admissions", "view_all")
SELF_READ = permission_required("admissions", "view")
SELF_WRITE = permission_required("admissions", "create")
SCOPE = Query(default=None, pattern="^(self|own|mine|department|faculty|college|all)$")
SEATS = [feature_required("admissions.seat_matrix")]
ONLINE = [feature_required("admissions.online_application")]
VERIFY = [feature_required("admissions.document_verification")]
MERIT = [feature_required("admissions.merit_lists")]
COUNSEL = [feature_required("admissions.counselling_allotment")]
OFFERS = [feature_required("admissions.offers")]
IMPORT = [feature_required("admissions.entrance_import")]
CRM = [feature_required("admissions.enquiry_crm")]


def _queued(data: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(data, message=message))


# ---- cycles ---------------------------------------------------------------------------------------------------------
@router.get("/admissions/cycles", summary="Admission cycles", response_model=Envelope[list[CycleResponse]])
async def list_cycles(
    request: Request,
    status: CycleStatus | None = None,
    level: CycleLevel | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = CycleService(db, principal, request)
    return ok(await svc.list_all(status.value if status else None, level.value if level else None))


@router.post("/admissions/cycles", status_code=201, summary="Create a cycle", response_model=Envelope[CycleResponse])
async def create_cycle(
    body: CycleCreate, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).create(body), message="Cycle created")


@router.get("/admissions/cycles/{id}", summary="A cycle", response_model=Envelope[CycleResponse])
async def get_cycle(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).get(id))


@router.put("/admissions/cycles/{id}", summary="Update a cycle", response_model=Envelope[CycleResponse])
async def update_cycle(
    id: uuid.UUID,
    body: CycleUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).update(id, body), message="Cycle updated")


@router.post(
    "/admissions/cycles/{id}/status",
    summary="Cycle status (open needs Σ seats = intake)",
    response_model=Envelope[CycleResponse],
)
async def cycle_status(
    id: uuid.UUID,
    body: CycleStatusChange,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).change_status(id, body), message=f"Cycle {body.status.value}")


@router.get(
    "/admissions/cycles/{id}/programs", summary="Programmes & intake", response_model=Envelope[list[CycleProgramOut]]
)
async def cycle_programs(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).programs_out(id))


@router.put(
    "/admissions/cycles/{id}/programs",
    summary="Replace programmes & intake",
    response_model=Envelope[list[CycleProgramOut]],
)
async def replace_programs(
    id: uuid.UUID,
    body: CycleProgramsReplace,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).replace_programs(id, body), message="Programmes saved")


@router.get(
    "/admissions/cycles/{id}/seat-matrix",
    summary="Seat matrix",
    response_model=Envelope[SeatStatusResponse],
    dependencies=SEATS,
)
async def seat_matrix(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).seat_status(id))


@router.put(
    "/admissions/cycles/{id}/seat-matrix",
    summary="Replace the seat matrix (quota × category per programme)",
    response_model=Envelope[SeatStatusResponse],
    dependencies=SEATS,
)
async def replace_seat_matrix(
    id: uuid.UUID,
    body: SeatMatrixReplace,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).replace_seat_matrix(id, body), message="Seat matrix saved")


@router.get(
    "/admissions/cycles/{id}/seat-status",
    summary="Filled / vacant seats by quota × category",
    response_model=Envelope[SeatStatusResponse],
    dependencies=SEATS,
)
async def seat_status(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).seat_status(id))


# ---- applicant portal (self) -----------------------------------------------------------------------------------------
@router.get(
    "/applicants/me", summary="My application", response_model=Envelope[ApplicantSelfResponse], dependencies=ONLINE
)
async def my_application(
    request: Request, principal: Principal = Depends(SELF_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).me())


@router.put(
    "/applicants/me",
    summary="Save my application (draft / documents rejected)",
    response_model=Envelope[ApplicantSelfResponse],
    dependencies=ONLINE,
)
async def update_my_application(
    body: ApplicantUpdate,
    request: Request,
    principal: Principal = Depends(SELF_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).update_me(body), message="Saved")


@router.post(
    "/applicants/me/documents",
    summary="Upload a document (type from the cycle's required documents)",
    response_model=Envelope[ApplicantSelfResponse],
    dependencies=ONLINE,
)
async def upload_my_document(
    request: Request,
    doc_type: str = Form(..., max_length=60),
    file: UploadFile = File(...),
    principal: Principal = Depends(SELF_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    return ok(await svc.upload_document(await svc.mine(for_update=True), doc_type, file), message="Document uploaded")


@router.put(
    "/applicants/me/preferences",
    summary="Programme preferences (order = priority)",
    response_model=Envelope[ApplicantSelfResponse],
    dependencies=ONLINE,
)
async def my_preferences(
    body: PreferencesReplace,
    request: Request,
    principal: Principal = Depends(SELF_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).preferences_me(body), message="Preferences saved")


@router.get(
    "/applicants/me/eligibility",
    summary="Eligibility per preference",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=ONLINE,
)
async def my_eligibility(
    request: Request, principal: Principal = Depends(SELF_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    return ok(await svc.eligibility(await svc.mine()))


@router.post(
    "/applicants/me/submit",
    summary="Submit (validates documents + eligibility; creates the application-fee payment)",
    response_model=Envelope[ApplicantSelfResponse],
    dependencies=ONLINE,
)
async def submit_my_application(
    request: Request, principal: Principal = Depends(SELF_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    return ok(await svc.submit(await svc.mine(for_update=True)), message="Application submitted")


@router.post(
    "/applicants/me/pay",
    summary="Pay a due fee (mock gateway until Phase 12)",
    response_model=Envelope[PaymentResult],
    dependencies=ONLINE,
)
async def pay_my_fee(
    request: Request,
    purpose: str = Query(default="application", pattern="^(application|admission)$"),
    principal: Principal = Depends(SELF_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).pay_me(purpose), message="Payment received")


@router.post(
    "/applicants/me/withdraw",
    summary="Withdraw (refund per policy)",
    response_model=Envelope[WithdrawalResult],
    dependencies=ONLINE,
)
async def withdraw_my_application(
    body: WithdrawalRequest,
    request: Request,
    principal: Principal = Depends(SELF_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    return ok(await svc.withdraw(await svc.mine(for_update=True), body, self_view=True), message="Withdrawn")


@router.get(
    "/applicants/me/timeline", summary="My timeline", response_model=Envelope[list[TimelineEntry]], dependencies=ONLINE
)
async def my_timeline(
    request: Request, principal: Principal = Depends(SELF_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    return ok(await svc.timeline(await svc.mine()))


@router.get(
    "/applicants/me/allotment",
    summary="My seat allotment",
    response_model=Envelope[AllotmentResponse | None],
    dependencies=ONLINE,
)
async def my_allotment(
    request: Request, principal: Principal = Depends(SELF_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = CounsellingService(db, principal, request)
    a = await ApplicationService(db, principal, request).mine()
    return ok(await svc.my_allotment(a))


@router.post(
    "/applicants/me/allotment/{id}/decision",
    summary="Accept / float / freeze / decline an allotment",
    response_model=Envelope[AllotmentResponse],
    dependencies=COUNSEL,
)
async def decide_allotment(
    id: uuid.UUID,
    body: AllotmentDecision,
    request: Request,
    principal: Principal = Depends(SELF_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    a = await ApplicationService(db, principal, request).mine(for_update=True)
    out = await CounsellingService(db, principal, request).decide(a, id, body)
    return ok(out, message=f"Allotment {body.action.value}")


@router.put(
    "/applicants/me/choices",
    summary="Choice filling (inside the round's window)",
    response_model=Envelope[ApplicantSelfResponse],
    dependencies=COUNSEL,
)
async def my_choices(
    body: PreferencesReplace,
    request: Request,
    principal: Principal = Depends(SELF_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    a = await svc.mine(for_update=True)
    await CounsellingService(db, principal, request).choice_filling(a, body)
    return ok(await svc.respond(a, self_view=True), message="Choices saved")


# ---- applicants (office) ------------------------------------------------------------------------------------------------
def _app_filters(
    cycle_id: uuid.UUID | None = None,
    status: ApplicantStatus | None = None,
    program_id: uuid.UUID | None = None,
    category: str | None = Query(default=None, max_length=20),
    quota: str | None = Query(default=None, max_length=30),
    entry_type: str | None = Query(default=None, pattern="^(regular|lateral|migration)$"),
    verified: bool | None = None,
    search: str | None = Query(default=None, max_length=120),
    scope: str | None = SCOPE,
) -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "status": status.value if status else None,
        "program_id": program_id,
        "category": category,
        "quota": quota,
        "entry_type": entry_type,
        "verified": verified,
        "q": search,
        "scope": scope,
    }


@router.get("/admissions/applicants", summary="Applicants", response_model=Envelope[list[ApplicantListItem]])
async def list_applicants(
    request: Request,
    params: PageParams = Depends(page_params),
    filters: dict[str, Any] = Depends(_app_filters),
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination, visibility = await ApplicationService(db, principal, request).list_page(params, **filters)
    return ok(rows, pagination=pagination, visibility=visibility)


@router.get(
    "/admissions/applicants/export",
    status_code=202,
    summary="Export applicants (XLSX job; PII masked without view_pii)",
    response_model=Envelope[dict[str, Any]],
)
async def export_applicants(
    request: Request,
    filters: dict[str, Any] = Depends(_app_filters),
    principal: Principal = Depends(permission_required("admissions", "export")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    job_id = await ApplicationService(db, principal, request).enqueue_export(filters)
    return _queued({"job_id": str(job_id)}, "Export queued")


@router.post(
    "/admissions/applicants/import",
    summary="Import a counselling CSV (dry_run=true → report; false → job)",
    response_model=Envelope[ImportResult],
    dependencies=IMPORT,
)
async def import_applicants(
    request: Request,
    cycle_id: uuid.UUID = Form(...),
    mapping: str | None = Form(default=None, description="JSON {field: csv column}"),
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    principal: Principal = Depends(permission_required("admissions", "import")),
    db: AsyncSession = Depends(get_db),
) -> Any:
    try:
        mapped = json.loads(mapping) if mapping else None
    except ValueError as exc:
        raise APIError(422, ErrorCode.VALIDATION, "mapping must be JSON", {"field": "mapping"}) from exc
    svc = ApplicationService(db, principal, request)
    content = await file.read()
    if dry_run:
        return ok(await svc.import_dry_run(cycle_id, content, mapped), message="Dry run")
    return _queued(await svc.enqueue_import(cycle_id, content, mapped), "Import queued")


@router.get(
    "/admissions/verification-queue",
    summary="Applications awaiting document verification",
    response_model=Envelope[list[ApplicantResponse]],
    dependencies=VERIFY,
)
async def verification_queue(
    request: Request,
    params: PageParams = Depends(page_params),
    cycle_id: uuid.UUID | None = None,
    principal: Principal = Depends(permission_required("admissions", "verify")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await ApplicationService(db, principal, request).verification_queue(cycle_id, params)
    return ok(rows, pagination=pagination)


@router.get("/admissions/applicants/{id}", summary="An applicant", response_model=Envelope[ApplicantResponse])
async def get_applicant(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).get(id))


@router.put("/admissions/applicants/{id}", summary="Edit an applicant", response_model=Envelope[ApplicantResponse])
async def update_applicant(
    id: uuid.UUID,
    body: ApplicantUpdate,
    request: Request,
    principal: Principal = Depends(permission_required("admissions", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).update(id, body), message="Saved")


@router.get(
    "/admissions/applicants/{id}/timeline", summary="Applicant timeline", response_model=Envelope[list[TimelineEntry]]
)
async def applicant_timeline(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW_ALL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    return ok(await svc.timeline(await svc.applicants.get_visible(id)))


@router.post(
    "/admissions/applicants/{id}/documents/{doc_type}/verify",
    summary="Verify / reject / ask to resubmit a document",
    response_model=Envelope[ApplicantResponse],
    dependencies=VERIFY,
)
async def verify_document(
    id: uuid.UUID,
    doc_type: str,
    body: DocumentVerifyRequest,
    request: Request,
    principal: Principal = Depends(permission_required("admissions", "verify")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await ApplicationService(db, principal, request).verify_document(id, doc_type, body)
    return ok(out, message=f"Document {body.status}")


@router.post(
    "/admissions/applicants/{id}/status",
    summary="Manual transition with a reason",
    response_model=Envelope[ApplicantResponse],
)
async def applicant_status(
    id: uuid.UUID,
    body: ApplicantStatusChange,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).manual_status(id, body), message="Status changed")


@router.post(
    "/admissions/applicants/{id}/withdraw",
    summary="Withdraw on the applicant's behalf (refund per policy)",
    response_model=Envelope[WithdrawalResult],
)
async def withdraw_applicant(
    id: uuid.UUID,
    body: WithdrawalRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    return ok(await svc.withdraw(await svc.applicants.get_visible(id, for_update=True), body), message="Withdrawn")


@router.post(
    "/admissions/applicants/{id}/offer",
    status_code=201,
    summary="Issue an offer",
    response_model=Envelope[OfferResponse],
    dependencies=OFFERS,
)
async def issue_offer(
    id: uuid.UUID,
    body: OfferCreate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).offer(id, body), message="Offer issued")


@router.get("/admissions/offers", summary="Offers", response_model=Envelope[list[OfferResponse]], dependencies=OFFERS)
async def list_offers(
    request: Request,
    cycle_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).offers(cycle_id))


@router.post(
    "/admissions/applicants/{id}/admit",
    status_code=201,
    summary="Admit → student + enrolment + registration number (Phase 07 student service)",
    response_model=Envelope[AdmitResult],
)
async def admit_applicant(
    id: uuid.UUID,
    request: Request,
    body: AdmitRequest | None = None,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(permission_required("admissions", "admit")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await CounsellingService(db, principal, request).admit(id, body or AdmitRequest())
    response = ok(out, message="Admitted")
    await store(request, response, db, 201)
    return response


# ---- merit lists ---------------------------------------------------------------------------------------------------------
@router.post(
    "/admissions/cycles/{id}/merit-lists",
    status_code=202,
    summary="Generate a merit list (job)",
    response_model=Envelope[MeritListResponse],
    dependencies=MERIT,
)
async def generate_merit(
    id: uuid.UUID,
    body: MeritGenerateRequest,
    request: Request,
    principal: Principal = Depends(permission_required("admissions", "merit")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return _queued(await MeritService(db, principal, request).generate(id, body), "Merit list queued")


@router.get(
    "/admissions/merit-lists",
    summary="Merit lists",
    response_model=Envelope[list[MeritListResponse]],
    dependencies=MERIT,
)
async def list_merit(
    request: Request,
    cycle_id: uuid.UUID | None = None,
    status: str | None = Query(default=None, pattern="^(draft|published|superseded)$"),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeritService(db, principal, request).lists(cycle_id, status))


@router.get(
    "/admissions/merit-lists/{id}",
    summary="A merit list with ranks",
    response_model=Envelope[MeritListDetail],
    dependencies=MERIT,
)
async def get_merit(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MeritService(db, principal, request).detail(id))


@router.post(
    "/admissions/merit-lists/{id}/publish",
    summary="Publish (notifies; public masked list)",
    response_model=Envelope[MeritListResponse],
    dependencies=MERIT,
)
async def publish_merit(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(permission_required("admissions", "merit")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MeritService(db, principal, request).publish(id), message="Published")


# ---- counselling -------------------------------------------------------------------------------------------------------
ALLOT = permission_required("admissions", "allot")
ALLOT_READ = any_permission_required(("admissions", "allot"), ("admissions", "view_all"))


@router.get(
    "/admissions/cycles/{id}/rounds",
    summary="Counselling rounds",
    response_model=Envelope[list[RoundResponse]],
    dependencies=COUNSEL,
)
async def list_rounds(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).rounds(id))


@router.post(
    "/admissions/cycles/{id}/rounds",
    status_code=201,
    summary="Create a round",
    response_model=Envelope[RoundResponse],
    dependencies=COUNSEL,
)
async def create_round(
    id: uuid.UUID,
    body: RoundCreate,
    request: Request,
    principal: Principal = Depends(ALLOT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).create_round(id, body), message="Round created")


@router.put(
    "/admissions/rounds/{id}", summary="Update a round", response_model=Envelope[RoundResponse], dependencies=COUNSEL
)
async def update_round(
    id: uuid.UUID,
    body: RoundUpdate,
    request: Request,
    principal: Principal = Depends(ALLOT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).update_round(id, body), message="Round saved")


@router.post(
    "/admissions/rounds/{id}/status",
    summary="Round status (planned → choice_filling → allotted → reporting → closed)",
    response_model=Envelope[RoundResponse],
    dependencies=COUNSEL,
)
async def round_status(
    id: uuid.UUID,
    body: RoundStatusChange,
    request: Request,
    principal: Principal = Depends(ALLOT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await CounsellingService(db, principal, request).round_status(id, body), message=f"Round {body.status.value}"
    )


@router.post(
    "/admissions/rounds/{id}/run-allotment",
    summary="Seat allotment — dry run inline, real run as a job (202)",
    response_model=Envelope[AllotmentSummary],
    dependencies=COUNSEL,
)
async def run_allotment(
    id: uuid.UUID,
    request: Request,
    dry_run: bool = Query(default=True),
    principal: Principal = Depends(ALLOT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    out = await CounsellingService(db, principal, request).run_allotment(id, dry_run)
    if dry_run:
        return ok(out, message="Allotment preview")
    return _queued(out, "Allotment queued")


@router.get(
    "/admissions/rounds/{id}/allotments",
    summary="Allotments of a round",
    response_model=Envelope[list[AllotmentResponse]],
    dependencies=COUNSEL,
)
async def round_allotments(
    id: uuid.UUID,
    request: Request,
    status: str | None = Query(default=None, max_length=20),
    principal: Principal = Depends(ALLOT_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).allotments(id, status))


@router.get(
    "/admissions/rounds/{id}/summary",
    summary="Round summary (programme × quota × category)",
    response_model=Envelope[AllotmentSummary],
    dependencies=COUNSEL,
)
async def round_summary(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ALLOT_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CounsellingService(db, principal, request).summary(id))


# ---- enquiries ------------------------------------------------------------------------------------------------------------
@router.get(
    "/admissions/enquiries", summary="Enquiries", response_model=Envelope[list[EnquiryResponse]], dependencies=CRM
)
async def list_enquiries(
    request: Request,
    params: PageParams = Depends(page_params),
    stage: EnquiryStage | None = None,
    source: EnquirySource | None = None,
    assigned_to: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    scope: str | None = SCOPE,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await EnquiryService(db, principal, request).list_page(
        params,
        stage=stage.value if stage else None,
        source=source.value if source else None,
        assigned_to=assigned_to,
        q=q,
        scope=scope,
    )
    return ok(rows, pagination=pagination)


@router.get("/admissions/enquiries/stats", summary="Funnel", response_model=Envelope[EnquiryStats], dependencies=CRM)
async def enquiry_stats(
    request: Request,
    scope: str | None = SCOPE,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).stats(scope))


@router.post(
    "/admissions/enquiries",
    status_code=201,
    summary="Record an enquiry",
    response_model=Envelope[EnquiryResponse],
    dependencies=CRM,
)
async def create_enquiry(
    body: EnquiryCreate,
    request: Request,
    principal: Principal = Depends(permission_required("admissions", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).create(body), message="Enquiry recorded")


ENQ_WRITE = any_permission_required(("admissions", "update"), ("admissions", "create"))


@router.put(
    "/admissions/enquiries/{id}",
    summary="Update stage / notes",
    response_model=Envelope[EnquiryResponse],
    dependencies=CRM,
)
async def update_enquiry(
    id: uuid.UUID,
    body: EnquiryUpdate,
    request: Request,
    principal: Principal = Depends(ENQ_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).update(id, body), message="Enquiry saved")


@router.post(
    "/admissions/enquiries/{id}/assign",
    summary="Assign to a counsellor",
    response_model=Envelope[EnquiryResponse],
    dependencies=CRM,
)
async def assign_enquiry(
    id: uuid.UUID,
    body: EnquiryAssign,
    request: Request,
    principal: Principal = Depends(permission_required("admissions", "update")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).assign(id, body), message="Assigned")


@router.post(
    "/admissions/enquiries/{id}/convert",
    summary="Link an applicant (stage → applied)",
    response_model=Envelope[EnquiryResponse],
    dependencies=CRM,
)
async def convert_enquiry(
    id: uuid.UUID,
    body: EnquiryConvert,
    request: Request,
    principal: Principal = Depends(ENQ_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EnquiryService(db, principal, request).convert(id, body), message="Converted")


# ---- public ---------------------------------------------------------------------------------------------------------------
async def _resolve(request: Request, db: AsyncSession, slug: str | None, feature: str) -> Institution:
    repo = InstitutionRepository(db)
    slug = slug or getattr(request.state, "institution_slug", None)
    inst = await repo.by_slug(slug) if slug else None
    if inst is None and getattr(request.state, "institution_id", None):
        try:
            inst = await repo.get(uuid.UUID(str(request.state.institution_id)))
        except ValueError:
            inst = None
    if inst is None or inst.status != "active":
        raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if not await is_enabled(inst.id, feature):
        raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{feature}' is not enabled", {"feature": feature})
    return inst


async def cycles_tenant(
    request: Request,
    institution: str | None = Query(default=None, max_length=60, description="institution slug"),
    db: AsyncSession = Depends(get_db),
) -> Institution:
    return await _resolve(request, db, institution, "admissions.cycles")


async def apply_tenant(
    request: Request,
    institution: str | None = Query(default=None, max_length=60, description="institution slug"),
    db: AsyncSession = Depends(get_db),
) -> Institution:
    return await _resolve(request, db, institution, "admissions.online_application")


async def merit_tenant(
    request: Request,
    institution: str | None = Query(default=None, max_length=60, description="institution slug"),
    db: AsyncSession = Depends(get_db),
) -> Institution:
    return await _resolve(request, db, institution, "admissions.merit_lists")


cycles_tenant.__feature_key__ = "admissions.cycles"  # type: ignore[attr-defined]
apply_tenant.__feature_key__ = "admissions.online_application"  # type: ignore[attr-defined]
merit_tenant.__feature_key__ = "admissions.merit_lists"  # type: ignore[attr-defined]


@public_router.get(
    "/admissions/cycles", summary="Open admission cycles (public)", response_model=Envelope[list[dict[str, Any]]]
)
async def public_cycles(
    inst: Institution = Depends(cycles_tenant), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, None, institution_id=inst.id).public_cycles())


@public_router.get(
    "/admissions/cycles/{slug}", summary="Cycle details (public)", response_model=Envelope[PublicCycleInfo]
)
async def public_cycle(
    slug: str, inst: Institution = Depends(cycles_tenant), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, None, institution_id=inst.id).public_info(slug))


@public_router.post(
    "/admissions/{slug}/start",
    summary="Start an application: send the OTP, then verify it to create the applicant account + draft",
    response_model=Envelope[PublicStartResult],
    dependencies=[rate_limited("admissions_start", limit=20, window=60)],
)
async def public_start(
    slug: str,
    body: PublicStartRequest,
    request: Request,
    inst: Institution = Depends(apply_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await verify_captcha(body.captcha_token, request.client.host if request.client else None)
    out = await ApplicationService(db, None, request, institution_id=inst.id).public_start(slug, body)
    return ok(out, message="Code sent" if out.otp_sent else "Application started")


@public_router.get(
    "/admissions/{slug}/merit-lists/{id}",
    summary="Published merit list (application number + rank only)",
    response_model=Envelope[PublicMeritList],
)
async def public_merit(
    slug: str, id: uuid.UUID, inst: Institution = Depends(merit_tenant), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MeritService(db, None, institution_id=inst.id).public_list(slug, id))


@public_router.post(
    "/enquiries",
    status_code=201,
    summary="Website enquiry form (public, captcha)",
    response_model=Envelope[dict[str, Any]],
    dependencies=[rate_limited("public_enquiry", limit=10, window=60)],
)
async def public_enquiry(
    body: PublicEnquiryCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await verify_captcha(body.captcha_token, request.client.host if request.client else None)
    inst = await _resolve(request, db, body.institution or request.query_params.get("institution"), "website.enquiry")
    if not await is_enabled(inst.id, "admissions.enquiry_crm"):
        raise APIError(
            403, ErrorCode.FEATURE_DISABLED, "Enquiries are not enabled", {"feature": "admissions.enquiry_crm"}
        )
    return ok(await EnquiryService(db, None, request, institution_id=inst.id).public_create(body), message="Thank you")
