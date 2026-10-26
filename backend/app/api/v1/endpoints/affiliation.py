"""Affiliation — Prompts/34 §34.8: college registry / applications / decisions / programme approvals {affiliation.core},
scrutiny / inspections / deficiencies {affiliation.inspections}, fee schedules / dues / fee preview {affiliation.fees},
data submissions and session college status {affiliation.data_submissions}, exam centres {affiliation.exam_centres},
portfolio / returns and the public college list. Rows are narrowed by the services (college scope primary, inspector
ownership, faculty / department read, university office all). Fixed-path routes are declared before ``/{id}`` routes.
Job routes queue a ``jobs`` row (202) unless ``?inline=true``.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.db.session import get_db
from app.schemas.affiliation import (
    AffiliationJobQueued,
    AffiliationReturn,
    AllocationSummary,
    ApplicationAction,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
    CarryForwardIn,
    CarryForwardOut,
    CentreAllocationRun,
    CentreDashboard,
    Checklist,
    CollegeAffiliationProfile,
    CollegeDashboard,
    CollegeGatingStatus,
    CollegeProfileUpdate,
    CollegeRow,
    ComplianceRow,
    DecisionIn,
    DeficiencyClose,
    DeficiencyResponse,
    DocumentRef,
    DuesRow,
    ExamCentreIn,
    ExamCentreOut,
    FeeComputePreview,
    FeeScheduleIn,
    FeeScheduleOut,
    FeeScheduleUpdate,
    InspectionReportIn,
    InspectionRow,
    InspectionSchedule,
    ProgramApprovalCheck,
    ProgramApprovalOut,
    ProgramApprovalUpdate,
    PublicCollege,
    ReinspectRequest,
    ScrutinyDecision,
    SubmissionAction,
    SubmissionCreate,
    SubmissionImport,
    SubmissionOut,
    SubmissionWindowOut,
    UniversityPortfolio,
    ValidationReport,
    VaultDocument,
)
from app.schemas.common import Envelope
from app.services.affiliation.application_service import ApplicationService
from app.services.affiliation.college_registry_service import CollegeRegistryService
from app.services.affiliation.dashboard_service import DashboardService
from app.services.affiliation.exam_centre_service import ExamCentreService
from app.services.affiliation.program_approval_service import ProgramApprovalService
from app.services.affiliation.submission_service import SubmissionService
from app.utils.pdf import simple_pdf
from app.utils.response import PaginationMeta, VisibilityMeta, ok

router = APIRouter(tags=["affiliation"])
public_router = APIRouter(tags=["affiliation"])

A = "affiliation"
VIEW = any_permission_required(
    (A, "view"), (A, "view_all"), (A, "apply"), (A, "submit"), (A, "manage"), (A, "decide"), (A, "inspect")
)
OFFICE_VIEW = any_permission_required((A, "view_all"), (A, "manage"))
PROFILE_WRITE = any_permission_required((A, "manage"), (A, "apply"))
APPLY = any_permission_required((A, "apply"), (A, "manage"))
MANAGE = any_permission_required((A, "manage"))
INSPECT = any_permission_required((A, "inspect"), (A, "manage"), (A, "view_all"))
INSPECT_WRITE = any_permission_required((A, "inspect"), (A, "manage"))
DECIDE = any_permission_required((A, "decide"))
APPROVAL_WRITE = any_permission_required((A, "manage"), (A, "decide"))
FEES_VIEW = any_permission_required(
    (A, "manage"), (A, "view_all"), (A, "apply"), ("accounting", "view"), ("fees", "view_all")
)
SUB_VIEW = any_permission_required(
    (A, "submit"),
    (A, "verify_submission"),
    (A, "manage"),
    (A, "view_all"),
    (A, "view"),
    ("exams", "configure"),
    ("exams", "manage"),
)
SUB_WRITE = any_permission_required(
    (A, "submit"), (A, "verify_submission"), (A, "manage"), ("exams", "configure"), ("exams", "manage")
)
CENTRE_VIEW = any_permission_required(
    ("exams", "configure"),
    ("exams", "manage"),
    ("exams", "view_all"),
    (A, "manage"),
    (A, "view_all"),
    (A, "submit"),
    (A, "view"),
)
CENTRE_WRITE = any_permission_required(("exams", "configure"), ("exams", "manage"), (A, "manage"))
RETURNS = any_permission_required((A, "view_all"), (A, "manage"), ("reports", "statutory"))

CORE = [feature_required("affiliation.core")]
INSPECTIONS = [feature_required("affiliation.inspections")]
FEES = [feature_required("affiliation.fees")]
SUBMISSIONS = [feature_required("affiliation.data_submissions")]
CENTRES = [feature_required("affiliation.exam_centres")]

SCOPE = Query(None, pattern="^(college|all)$")


def _page(page: int, per_page: int, total: int) -> PaginationMeta:
    return PaginationMeta(page=page, page_size=per_page, total=total, total_pages=max(1, -(-total // per_page)))


def _vis(svc: Any) -> VisibilityMeta:
    allv = svc.system() or svc.office_reader()
    scopes = (["college"] if svc.my_college_ids() else []) + (["all"] if allv else [])
    return VisibilityMeta(self=False, scopes=scopes or ["college"], default="all" if allv else "college")


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(AffiliationJobQueued(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


# ======================================================================================================================
# college registry
# ======================================================================================================================
@router.get(
    "/affiliation/colleges",
    summary="College registry (type / status / faculty) with compliance score",
    response_model=Envelope[list[CollegeRow]],
    dependencies=CORE,
)
async def colleges(
    request: Request,
    type: str | None = Query(None, max_length=30),
    status: str | None = Query(None, pattern="^(active|inactive)$"),
    faculty_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CollegeRegistryService(db, principal, request).list_colleges(type, status, faculty_id))


@router.get(
    "/affiliation/colleges/me/dashboard",
    summary="My college's affiliation dashboard",
    response_model=Envelope[CollegeDashboard],
    dependencies=CORE,
)
async def my_dashboard(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DashboardService(db, principal, request).college_dashboard(None))


@router.get(
    "/affiliation/colleges/{id}/profile",
    summary="College affiliation profile",
    response_model=Envelope[CollegeAffiliationProfile],
    dependencies=CORE,
)
async def college_profile(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CollegeRegistryService(db, principal, request).profile(id))


@router.put(
    "/affiliation/colleges/{id}/profile",
    summary="Update the profile (office: all fields incl. type transition; college: principal / AISHE / AICTE)",
    response_model=Envelope[CollegeAffiliationProfile],
    dependencies=CORE,
)
async def update_college_profile(
    id: uuid.UUID,
    body: CollegeProfileUpdate,
    request: Request,
    principal: Principal = Depends(PROFILE_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CollegeRegistryService(db, principal, request).update_profile(id, body), message="Updated")


@router.get(
    "/affiliation/colleges/{id}/dashboard",
    summary="College affiliation dashboard",
    response_model=Envelope[CollegeDashboard],
    dependencies=CORE,
)
async def college_dashboard(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DashboardService(db, principal, request).college_dashboard(id))


@router.get(
    "/affiliation/colleges/{id}/documents",
    summary="College documents vault (statutory approvals with expiries)",
    response_model=Envelope[list[VaultDocument]],
    dependencies=CORE,
)
async def college_documents(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CollegeRegistryService(db, principal, request).documents(id))


@router.post(
    "/affiliation/colleges/{id}/documents",
    status_code=201,
    summary="Upload / replace a vault document",
    response_model=Envelope[list[VaultDocument]],
    dependencies=CORE,
)
async def add_college_document(
    id: uuid.UUID,
    body: VaultDocument,
    request: Request,
    principal: Principal = Depends(PROFILE_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CollegeRegistryService(db, principal, request).add_document(id, body), message="Saved")


# ======================================================================================================================
# applications
# ======================================================================================================================
@router.get(
    "/affiliation/applications",
    summary="Affiliation applications (ScopeTabs College | All)",
    response_model=Envelope[list[ApplicationOut]],
    dependencies=CORE,
)
async def applications(
    request: Request,
    college_id: uuid.UUID | None = None,
    year: uuid.UUID | None = None,
    type: str | None = Query(None, max_length=30),
    status: str | None = Query(None, max_length=30),
    scope: str | None = SCOPE,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ApplicationService(db, principal, request)
    rows, total = await svc.list_applications(college_id, year, type, status, scope, page, per_page)
    return ok(rows, pagination=_page(page, per_page, total), visibility=_vis(svc))


@router.post(
    "/affiliation/applications",
    status_code=201,
    summary="Create an application (college, per year / type, programmes, checklist documents)",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE,
)
async def create_application(
    body: ApplicationCreate,
    request: Request,
    principal: Principal = Depends(APPLY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).create(body), message="Created")


@router.get(
    "/affiliation/applications/{id}",
    summary="Application (checklist, fees, workflow, inspection, deficiencies, decision / order)",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE,
)
async def application(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).get(id))


@router.put(
    "/affiliation/applications/{id}",
    summary="Edit a draft application (programmes, documents, remarks)",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE,
)
async def update_application(
    id: uuid.UUID,
    body: ApplicationUpdate,
    request: Request,
    principal: Principal = Depends(APPLY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).update(id, body), message="Updated")


@router.post(
    "/affiliation/applications/{id}/action",
    summary="Submit (checklist complete → fees / invoice) or withdraw before a decision",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE,
)
async def application_action(
    id: uuid.UUID,
    body: ApplicationAction,
    request: Request,
    principal: Principal = Depends(APPLY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).action(id, body))


@router.get(
    "/affiliation/applications/{id}/checklist",
    summary="Document checklist for the application type",
    response_model=Envelope[Checklist],
    dependencies=CORE,
)
async def application_checklist(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).checklist(id))


@router.get(
    "/affiliation/applications/{id}/fee-preview",
    summary="Fee lines from the schedules (flat / per programme / per student)",
    response_model=Envelope[FeeComputePreview],
    dependencies=CORE + FEES,
)
async def application_fee_preview(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).fee_preview(id))


@router.post(
    "/affiliation/applications/{id}/scrutiny",
    summary="Registrar scrutiny: proceed or return with missing documents",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE + INSPECTIONS,
)
async def application_scrutiny(
    id: uuid.UUID,
    body: ScrutinyDecision,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).scrutiny(id, body))


@router.post(
    "/affiliation/applications/{id}/inspection/schedule",
    summary="Constitute the inspection committee (staff / external / Phase 33 committee) and schedule",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE + INSPECTIONS,
)
async def schedule_inspection(
    id: uuid.UUID,
    body: InspectionSchedule,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).schedule_inspection(id, body))


@router.post(
    "/affiliation/applications/{id}/inspection/report",
    summary="Inspection report with findings / deficiencies (assigned committee)",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE + INSPECTIONS,
)
async def inspection_report(
    id: uuid.UUID,
    body: InspectionReportIn,
    request: Request,
    principal: Principal = Depends(INSPECT_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).inspection_report(id, body))


@router.post(
    "/affiliation/applications/{id}/deficiencies/{did}/respond",
    summary="College response to a deficiency with evidence",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE + INSPECTIONS,
)
async def respond_deficiency(
    id: uuid.UUID,
    did: str,
    body: DeficiencyResponse,
    request: Request,
    principal: Principal = Depends(APPLY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).respond_deficiency(id, did, body))


@router.post(
    "/affiliation/applications/{id}/deficiencies/{did}/close",
    summary="Close (or send back) a deficiency",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE + INSPECTIONS,
)
async def close_deficiency(
    id: uuid.UUID,
    did: str,
    body: DeficiencyClose,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).close_deficiency(id, did, body))


@router.post(
    "/affiliation/applications/{id}/reinspect",
    summary="Re-inspection round (critical deficiencies left)",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE + INSPECTIONS,
)
async def reinspect(
    id: uuid.UUID,
    body: ReinspectRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).reinspect(id, body))


@router.post(
    "/affiliation/applications/{id}/decide",
    summary="Decision (approved / conditional / rejected) with intake / validity, resolution and order",
    response_model=Envelope[ApplicationOut],
    dependencies=CORE,
)
async def decide(
    id: uuid.UUID,
    body: DecisionIn,
    request: Request,
    principal: Principal = Depends(DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).decide(id, body), message="Decided")


@router.get(
    "/affiliation/applications/{id}/order.pdf",
    summary="Affiliation order (PDF)",
    response_class=Response,
    dependencies=CORE,
)
async def order_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> Response:
    name, lines = await ApplicationService(db, principal, request).order_lines(id)
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_") or "order"
    return Response(
        simple_pdf(lines, title="Affiliation order"),
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={safe}.pdf"},
    )


# ---- inspections --------------------------------------------------------------------------------------------------------
@router.get(
    "/affiliation/inspections/me",
    summary="My assigned inspections (committee member)",
    response_model=Envelope[list[InspectionRow]],
    dependencies=CORE + INSPECTIONS,
)
async def my_inspections(
    request: Request, principal: Principal = Depends(INSPECT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).inspections(None, None, mine=True))


@router.get(
    "/affiliation/inspections",
    summary="Inspection schedule (office: all; members: assigned)",
    response_model=Envelope[list[InspectionRow]],
    dependencies=CORE + INSPECTIONS,
)
async def inspections(
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(INSPECT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ApplicationService(db, principal, request).inspections(date_from, date_to))


# ======================================================================================================================
# programme approvals
# ======================================================================================================================
@router.get(
    "/affiliation/program-approvals",
    summary="Programme approvals (college × programme × year) with validity chips",
    response_model=Envelope[list[ProgramApprovalOut]],
    dependencies=CORE,
)
async def program_approvals(
    request: Request,
    college_id: uuid.UUID | None = None,
    year: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    status: str | None = Query(None, max_length=20),
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, total = await ProgramApprovalService(db, principal, request).list_approvals(
        college_id, year, program_id, status, page, per_page
    )
    return ok(rows, pagination=_page(page, per_page, total))


@router.get(
    "/affiliation/program-approvals/check",
    summary="Intake / validity check (internal: admissions, registration)",
    response_model=Envelope[ProgramApprovalCheck],
    dependencies=CORE,
)
async def program_approval_check(
    request: Request,
    college_id: uuid.UUID,
    program_id: uuid.UUID,
    year: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramApprovalService(db, principal, request).check(college_id, program_id, year))


@router.post(
    "/affiliation/program-approvals/carry-forward",
    summary="Carry permanent approvals forward to a year (provisional rows)",
    response_model=Envelope[CarryForwardOut],
    dependencies=CORE,
)
async def carry_forward(
    body: CarryForwardIn,
    request: Request,
    inline: bool = Query(False),
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not inline:
        return await _job(db, principal, "affiliation.carry_forward", {"academic_year_id": str(body.academic_year_id)})
    return ok(await ProgramApprovalService(db, principal, request).carry_forward(body.academic_year_id))


@router.get(
    "/affiliation/program-approvals/{id}",
    summary="Programme approval",
    response_model=Envelope[ProgramApprovalOut],
    dependencies=CORE,
)
async def program_approval(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProgramApprovalService(db, principal, request).get(id))


@router.put(
    "/affiliation/program-approvals/{id}",
    summary="Update intake / status / conditions / validity (reason, audited)",
    response_model=Envelope[ProgramApprovalOut],
    dependencies=CORE,
)
async def update_program_approval(
    id: uuid.UUID,
    body: ProgramApprovalUpdate,
    request: Request,
    principal: Principal = Depends(APPROVAL_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramApprovalService(db, principal, request).update(id, body), message="Updated")


# ======================================================================================================================
# fee schedules / dues
# ======================================================================================================================
@router.get(
    "/affiliation/fee-schedules",
    summary="Affiliation fee schedules per year",
    response_model=Envelope[list[FeeScheduleOut]],
    dependencies=CORE + FEES,
)
async def fee_schedules(
    request: Request,
    year: uuid.UUID | None = None,
    principal: Principal = Depends(FEES_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramApprovalService(db, principal, request).schedules(year))


@router.post(
    "/affiliation/fee-schedules",
    status_code=201,
    summary="Add a fee schedule row",
    response_model=Envelope[FeeScheduleOut],
    dependencies=CORE + FEES,
)
async def create_fee_schedule(
    body: FeeScheduleIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProgramApprovalService(db, principal, request).create_schedule(body), message="Created")


@router.put(
    "/affiliation/fee-schedules/{id}",
    summary="Update a fee schedule row",
    response_model=Envelope[FeeScheduleOut],
    dependencies=CORE + FEES,
)
async def update_fee_schedule(
    id: uuid.UUID,
    body: FeeScheduleUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramApprovalService(db, principal, request).update_schedule(id, body), message="Updated")


@router.get(
    "/affiliation/dues",
    summary="Dues by college (college invoices + exam-processing estimate)",
    response_model=Envelope[list[DuesRow]],
    dependencies=CORE + FEES,
)
async def dues(
    request: Request,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(FEES_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProgramApprovalService(db, principal, request).dues(college_id))


# ======================================================================================================================
# data submissions
# ======================================================================================================================
@router.get(
    "/affiliation/submissions/windows",
    summary="Submission windows for a term (due chips; autonomous colleges: non-exam types only)",
    response_model=Envelope[list[SubmissionWindowOut]],
    dependencies=CORE + SUBMISSIONS,
)
async def submission_windows(
    request: Request,
    term_id: uuid.UUID,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(SUB_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).windows(term_id, college_id))


@router.get(
    "/affiliation/submissions/compliance",
    summary="Submission compliance per college (on-time %, returns)",
    response_model=Envelope[list[ComplianceRow]],
    dependencies=CORE + SUBMISSIONS,
)
async def submission_compliance(
    request: Request, term_id: uuid.UUID, principal: Principal = Depends(SUB_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).compliance(term_id))


@router.get(
    "/affiliation/submissions",
    summary="College data submissions (ScopeTabs College | All)",
    response_model=Envelope[list[SubmissionOut]],
    dependencies=CORE + SUBMISSIONS,
)
async def submissions(
    request: Request,
    college_id: uuid.UUID | None = None,
    term_id: uuid.UUID | None = None,
    type: str | None = Query(None, max_length=30),
    status: str | None = Query(None, max_length=20),
    scope: str | None = SCOPE,
    principal: Principal = Depends(SUB_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = SubmissionService(db, principal, request)
    return ok(await svc.list_submissions(college_id, term_id, type, status, scope), visibility=_vis(svc))


@router.post(
    "/affiliation/submissions",
    status_code=201,
    summary="Prepare a submission (system data or file upload)",
    response_model=Envelope[SubmissionOut],
    dependencies=CORE + SUBMISSIONS,
)
async def create_submission(
    body: SubmissionCreate,
    request: Request,
    principal: Principal = Depends(SUB_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).create(body), message="Created")


@router.get(
    "/affiliation/submissions/{id}",
    summary="Submission (record count, validation, timeline, versions)",
    response_model=Envelope[SubmissionOut],
    dependencies=CORE + SUBMISSIONS,
)
async def submission(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SUB_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).get(id))


@router.post(
    "/affiliation/submissions/{id}/extract",
    summary="Extract from system data (job)",
    response_model=Envelope[SubmissionOut],
    dependencies=CORE + SUBMISSIONS,
)
async def extract_submission(
    id: uuid.UUID,
    request: Request,
    inline: bool = Query(False),
    principal: Principal = Depends(SUB_WRITE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not inline:
        return await _job(db, principal, "affiliation.submission_extract", {"submission_id": str(id)})
    return ok(await SubmissionService(db, principal, request).extract(id))


@router.post(
    "/affiliation/submissions/{id}/import",
    summary="Import a CSV / XLSX file (job)",
    response_model=Envelope[SubmissionOut],
    dependencies=CORE + SUBMISSIONS,
)
async def import_submission(
    id: uuid.UUID,
    body: SubmissionImport,
    request: Request,
    inline: bool = Query(False),
    principal: Principal = Depends(SUB_WRITE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not inline:
        return await _job(
            db,
            principal,
            "affiliation.submission_import",
            {"submission_id": str(id), "file_url": body.file_url, "mapping": body.mapping},
        )
    return ok(await SubmissionService(db, principal, request).import_file(id, body))


@router.post(
    "/affiliation/submissions/{id}/validate",
    summary="Validate against the rules (job)",
    response_model=Envelope[ValidationReport],
    dependencies=CORE + SUBMISSIONS,
)
async def validate_submission(
    id: uuid.UUID,
    request: Request,
    inline: bool = Query(False),
    principal: Principal = Depends(SUB_WRITE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not inline:
        return await _job(db, principal, "affiliation.submission_validate", {"submission_id": str(id)})
    return ok(await SubmissionService(db, principal, request).validate(id))


@router.get(
    "/affiliation/submissions/{id}/report",
    summary="Validation report (errors / warnings / summary)",
    response_model=Envelope[ValidationReport],
    dependencies=CORE + SUBMISSIONS,
)
async def submission_report(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SUB_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).report(id))


@router.post(
    "/affiliation/submissions/{id}/action",
    summary="submit | verify | return | accept | lock | unlock",
    response_model=Envelope[SubmissionOut],
    dependencies=CORE + SUBMISSIONS,
)
async def submission_action(
    id: uuid.UUID,
    body: SubmissionAction,
    request: Request,
    principal: Principal = Depends(SUB_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).action(id, body))


@router.get(
    "/affiliation/exam-sessions/{id}/college-status",
    summary="Result gating per college for a central session",
    response_model=Envelope[list[CollegeGatingStatus]],
    dependencies=CORE + SUBMISSIONS,
)
async def college_status(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SUB_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).college_status(id))


# ======================================================================================================================
# exam centres
# ======================================================================================================================
@router.get(
    "/affiliation/exam-centres/me",
    summary="My college's centre(s) with the centre dashboard (coordinator)",
    response_model=Envelope[list[CentreDashboard]],
    dependencies=CENTRES,
)
async def my_centres(
    request: Request, principal: Principal = Depends(CENTRE_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamCentreService(db, principal, request).mine())


@router.post(
    "/affiliation/exam-centres/allocate",
    summary="Allocation run: nearest | capacity | manual (job)",
    response_model=Envelope[AllocationSummary],
    dependencies=CENTRES,
)
async def allocate_centres(
    body: CentreAllocationRun,
    request: Request,
    inline: bool = Query(False),
    principal: Principal = Depends(CENTRE_WRITE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not inline:
        return await _job(db, principal, "affiliation.centre_allocation", body.model_dump(mode="json"))
    return ok(await ExamCentreService(db, principal, request).allocate(body))


@router.get(
    "/affiliation/exam-centres",
    summary="Centres per session (registrations routed, seating, bundles)",
    response_model=Envelope[list[ExamCentreOut]],
    dependencies=CENTRES,
)
async def exam_centres(
    request: Request,
    exam_session_id: uuid.UUID | None = None,
    principal: Principal = Depends(CENTRE_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamCentreService(db, principal, request).list_centres(exam_session_id))


@router.post(
    "/affiliation/exam-centres",
    status_code=201,
    summary="Create a centre for a central session",
    response_model=Envelope[ExamCentreOut],
    dependencies=CENTRES,
)
async def create_exam_centre(
    body: ExamCentreIn,
    request: Request,
    principal: Principal = Depends(CENTRE_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamCentreService(db, principal, request).save(body), message="Created")


@router.get(
    "/affiliation/exam-centres/{id}",
    summary="Centre",
    response_model=Envelope[ExamCentreOut],
    dependencies=CENTRES,
)
async def exam_centre(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CENTRE_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamCentreService(db, principal, request).get(id))


@router.put(
    "/affiliation/exam-centres/{id}",
    summary="Update a centre (capacity below routed → 409)",
    response_model=Envelope[ExamCentreOut],
    dependencies=CENTRES,
)
async def update_exam_centre(
    id: uuid.UUID,
    body: ExamCentreIn,
    request: Request,
    principal: Principal = Depends(CENTRE_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamCentreService(db, principal, request).save(body, id), message="Updated")


@router.post(
    "/affiliation/exam-centres/{id}/appointment",
    summary="Chief superintendent appointment letter (job)",
    response_model=Envelope[DocumentRef],
    dependencies=CENTRES,
)
async def centre_appointment(
    id: uuid.UUID,
    request: Request,
    inline: bool = Query(False),
    principal: Principal = Depends(CENTRE_WRITE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not inline:
        return await _job(db, principal, "affiliation.centre_appointment", {"centre_id": str(id)})
    return ok(await ExamCentreService(db, principal, request).appointment(id))


@router.get(
    "/affiliation/exam-centres/{id}/dashboard",
    summary="Centre dashboard (registrations by college, seating, bundles)",
    response_model=Envelope[CentreDashboard],
    dependencies=CENTRES,
)
async def centre_dashboard(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CENTRE_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExamCentreService(db, principal, request).dashboard(id))


# ======================================================================================================================
# portfolio / returns / public
# ======================================================================================================================
@router.get(
    "/affiliation/portfolio",
    summary="University portfolio (types, applications, inspections, deficiencies, dues, submissions, gating)",
    response_model=Envelope[UniversityPortfolio],
    dependencies=CORE,
)
async def portfolio(
    request: Request, principal: Principal = Depends(OFFICE_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DashboardService(db, principal, request).portfolio())


@router.get(
    "/affiliation/returns/{kind}",
    summary="Statutory returns: colleges_list | intake | results_by_college (job; ?inline=true for rows)",
    response_model=Envelope[AffiliationReturn],
    dependencies=CORE,
)
async def returns(
    kind: str,
    request: Request,
    year: uuid.UUID | None = None,
    inline: bool = Query(False),
    principal: Principal = Depends(RETURNS),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if kind not in ("colleges_list", "intake", "results_by_college"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown return")
    if not inline:
        return await _job(
            db, principal, "affiliation.returns_export", {"kind": kind, "year": str(year) if year else None}
        )
    return ok(await DashboardService(db, principal, request).returns(kind, year))


@public_router.get(
    "/affiliation/public/colleges",
    summary="Approved colleges and programmes (website; tenant by institution slug)",
    response_model=Envelope[list[PublicCollege]],
)
async def public_colleges(
    request: Request, institution: str = Query(min_length=2, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "affiliation.core"):
        raise APIError(
            403,
            ErrorCode.FEATURE_DISABLED,
            "Feature 'affiliation.core' is not enabled",
            {"feature": "affiliation.core"},
        )
    return ok(await DashboardService(db, None, request, iid).public_colleges())
