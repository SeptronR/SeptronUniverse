"""Evaluation & results — Prompts/15 §15.8.

``router`` (included with ``feature_required("exams.sessions")``): coding / custody {exams.coding_dummy,
exams.script_custody}, valuation {exams.coding_dummy} (+ {exams.double_valuation} third assignment,
{exams.onscreen_valuation} scans), moderation {exams.moderation}, decode (``exams:decode`` + IP allow-list),
result runs {results.processing}, own / ward / student / offering results {results.publication_portal}, registers
{results.rank_lists}, grade cards {results.grade_cards}, legacy import {results.legacy_import}. Result compute and
grade-card generation answer ``202`` + ``job_id``. ``public_router``: the public result lookup (rate-limited, captcha;
only for sessions published with ``audience='public'`` and setting ``exams.result_public_lookup``). Grade-card QR
verification is served by the Phase 07 ``GET /verify/{token}`` route. Fixed paths precede parameterised ones.
"""

import math
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.authz.ip_allowlist import ip_allowlisted
from app.core.features import feature_required
from app.core.rate_limit import rate_limited, verify_captcha
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.results import (
    AnomalyRow,
    CourseResultResponse,
    GradeCardResponse,
    LegacyImportCreate,
    LegacyImportResponse,
    MyResultsResponse,
    PublicLookupRequest,
    PublicLookupResponse,
    PublishRequest,
    ResultAnalysis,
    RunAction,
    RunCreateRequest,
    RunResponse,
    TabulationRow,
)
from app.schemas.valuation import (
    AssignValuationRequest,
    BulkValuationSubmit,
    BundleCreateRequest,
    BundleResponse,
    CodeBundleResponse,
    CustodyLogCreate,
    CustodyLogResponse,
    DecodeResponse,
    EvaluatorBundleResponse,
    EvaluatorScript,
    ModerationDecision,
    ModerationProposal,
    ModerationResponse,
    OnlineImportResponse,
    ReassignRequest,
    ReconcileSummary,
    ScriptRegisterRow,
    ScriptRetentionRequest,
    ScriptValuationResponse,
    ThirdValuationAssign,
    ValuationAssignmentResponse,
    ValuationStatus,
    ValuationSubmit,
)
from app.services.results.coding_service import CodingService
from app.services.results.grade_card_service import GradeCardService
from app.services.results.legacy_import_service import LegacyImportService
from app.services.results.query_service import ResultQueryService
from app.services.results.result_service import ResultRunService
from app.services.results.valuation_service import ValuationService
from app.utils.pagination import PageParams, page_params
from app.utils.response import PaginationMeta, ok

router = APIRouter(tags=["results"])
public_router = APIRouter(tags=["public"])

E, R = "exams", "results"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CODE = permission_required(E, "code")
CUSTODY = permission_required(E, "custody")
BUNDLE_READ = any_permission_required((E, "code"), (E, "custody"), (E, "view_all"), (E, "manage"))
ASSIGN = permission_required(E, "valuation_assign")
VAL_READ = any_permission_required((E, "valuation_assign"), (E, "view_all"), (E, "manage"), (E, "moderate"))
EVAL = permission_required(E, "evaluate")
MODERATE = permission_required(E, "moderate")
MOD_APPROVE = any_permission_required((E, "moderate"), (E, "manage"))
DECODE = permission_required(E, "decode")
COMPUTE = permission_required(R, "compute")
RUN_READ = any_permission_required(
    (R, "compute"), (R, "verify"), (R, "view_all"), (R, "manage"), (R, "approve"), (R, "view")
)
VERIFY = permission_required(R, "verify")
APPROVE = any_permission_required((R, "approve"), (R, "manage"))
ROLLBACK = any_permission_required((R, "compute"), (R, "manage"))
PUBLISH = any_permission_required((R, "publish"), (R, "manage"))
SELF = permission_required(R, "self")
VIEW = any_permission_required((R, "view"), (R, "view_all"), (R, "manage"))
VIEW_ALL = any_permission_required((R, "view_all"), (R, "manage"))
CARD_READ = any_permission_required((R, "view"), (R, "view_all"), (R, "self"), (R, "manage"))
CARD_GEN = any_permission_required((R, "compute"), (R, "publish"), (R, "manage"))
LEGACY = permission_required(R, "legacy_import")
CODING = [feature_required("exams.coding_dummy")]
CUSTODYF = [feature_required("exams.script_custody")]
DOUBLE = [feature_required("exams.double_valuation")]
ONSCREEN = [feature_required("exams.onscreen_valuation")]
MODF = [feature_required("exams.moderation")]
PROC = [feature_required("results.processing")]
PORTAL = [feature_required("results.publication_portal")]
RANKS = [feature_required("results.rank_lists")]
CARDS = [feature_required("results.grade_cards")]
LEGACYF = [feature_required("results.legacy_import")]


def _queued(data: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(data, message=message))


def _page(params: PageParams, total: int) -> PaginationMeta:
    return PaginationMeta(
        page=params.page,
        page_size=params.page_size,
        total=total,
        total_pages=max(1, math.ceil(total / params.page_size)) if params.page_size else 1,
    )


# ---- coding & custody ---------------------------------------------------------------------------------------------
@router.get(
    "/exam-papers/{id}/bundles",
    summary="Answer-script bundles of a paper",
    response_model=Envelope[list[BundleResponse]],
    dependencies=CODING,
)
async def list_bundles(
    id: uuid.UUID, request: Request, principal: Principal = Depends(BUNDLE_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CodingService(db, principal, request).list_bundles(id))


@router.post(
    "/exam-papers/{id}/bundles",
    status_code=201,
    summary="Create bundles from present candidates",
    response_model=Envelope[list[BundleResponse]],
    dependencies=CODING,
)
async def create_bundles(
    id: uuid.UUID,
    body: BundleCreateRequest,
    request: Request,
    principal: Principal = Depends(CODE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CodingService(db, principal, request).create_bundles(id, body), message="Bundles created")


@router.post(
    "/bundles/{id}/code",
    summary="Code a bundle with dummy numbers",
    response_model=Envelope[CodeBundleResponse],
    dependencies=CODING,
)
async def code_bundle(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CODE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CodingService(db, principal, request).code(id), message="Bundle coded")


@router.get("/bundles/{id}", summary="Bundle", response_model=Envelope[BundleResponse], dependencies=CODING)
async def get_bundle(
    id: uuid.UUID, request: Request, principal: Principal = Depends(BUNDLE_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CodingService(db, principal, request).get_bundle(id))


@router.post(
    "/bundles/{id}/custody",
    status_code=201,
    summary="Log a custody movement",
    response_model=Envelope[CustodyLogResponse],
    dependencies=CUSTODYF,
)
async def log_custody(
    id: uuid.UUID,
    body: CustodyLogCreate,
    request: Request,
    principal: Principal = Depends(CUSTODY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CodingService(db, principal, request).custody(id, body), message="Custody logged")


@router.get(
    "/bundles/{id}/custody",
    summary="Custody timeline",
    response_model=Envelope[list[CustodyLogResponse]],
    dependencies=CUSTODYF,
)
async def custody_log(
    id: uuid.UUID, request: Request, principal: Principal = Depends(BUNDLE_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CodingService(db, principal, request).custody_log(id))


# ---- valuation (exam cell) --------------------------------------------------------------------------------------------
@router.post(
    "/exam-papers/{id}/valuation/assign",
    status_code=201,
    summary="Assign bundles to an evaluator",
    response_model=Envelope[list[ValuationAssignmentResponse]],
    dependencies=CODING,
)
async def assign_valuation(
    id: uuid.UUID,
    body: AssignValuationRequest,
    request: Request,
    principal: Principal = Depends(ASSIGN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if body.evaluator_type == "external":
        from app.core.features import is_enabled

        if principal.institution_id and not await is_enabled(principal.institution_id, "exams.external_examiners"):
            from app.core.errors import APIError, ErrorCode

            raise APIError(403, ErrorCode.FEATURE_DISABLED, "External examiners are not enabled")
    return ok(await ValuationService(db, principal, request).assign(id, body), message="Valuation assigned")


@router.get(
    "/exam-papers/{id}/valuation/status",
    summary="Valuation progress of a paper",
    response_model=Envelope[ValuationStatus],
    dependencies=CODING,
)
async def valuation_status(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VAL_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).status(id))


@router.post(
    "/valuation-assignments/{id}/reassign",
    summary="Reassign a bundle round",
    response_model=Envelope[ValuationAssignmentResponse],
    dependencies=CODING,
)
async def reassign(
    id: uuid.UUID,
    body: ReassignRequest,
    request: Request,
    principal: Principal = Depends(ASSIGN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).reassign(id, body), message="Reassigned")


@router.post(
    "/exam-papers/{id}/valuation/reconcile",
    summary="Reconcile valuations (discrepancies, final marks)",
    response_model=Envelope[ReconcileSummary],
    dependencies=CODING,
)
async def reconcile(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ASSIGN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).reconcile(id), message="Reconciled")


@router.post(
    "/exam-papers/{id}/valuation/third-assign",
    status_code=201,
    summary="Assign third valuations",
    response_model=Envelope[list[ValuationAssignmentResponse]],
    dependencies=DOUBLE,
)
async def third_assign(
    id: uuid.UUID,
    body: ThirdValuationAssign,
    request: Request,
    principal: Principal = Depends(ASSIGN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).third_assign(id, body), message="Third valuation assigned")


@router.post(
    "/exam-papers/{id}/online-import",
    summary="Import online-paper totals as final marks",
    response_model=Envelope[OnlineImportResponse],
    dependencies=[feature_required("exams.online_proctored")],
)
async def online_import(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ASSIGN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).import_online(id))


# ---- evaluator ------------------------------------------------------------------------------------------------------
@router.get(
    "/valuation/me/bundles",
    summary="My valuation bundles",
    response_model=Envelope[list[EvaluatorBundleResponse]],
    dependencies=CODING,
)
async def my_bundles(
    request: Request, principal: Principal = Depends(EVAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).my_bundles())


@router.post(
    "/valuation/me/marks",
    summary="Submit several valuations",
    response_model=Envelope[list[ScriptValuationResponse]],
    dependencies=CODING,
)
async def bulk_marks(
    body: BulkValuationSubmit,
    request: Request,
    principal: Principal = Depends(EVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).submit_bulk(body), message="Saved")


@router.get(
    "/valuation/bundles/{id}/scripts",
    summary="Scripts of my bundle (dummy numbers only)",
    response_model=Envelope[list[EvaluatorScript]],
    dependencies=CODING,
)
async def bundle_scripts(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EVAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).bundle_scripts(id))


@router.post(
    "/valuation/bundles/{id}/submit",
    summary="Submit (lock) my bundle",
    response_model=Envelope[ValuationAssignmentResponse],
    dependencies=CODING,
)
async def submit_bundle(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EVAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).submit_bundle(id), message="Bundle submitted")


@router.post(
    "/answer-scripts/{id}/valuations/{round}",
    summary="Enter the marks of a script",
    response_model=Envelope[ScriptValuationResponse],
    dependencies=CODING,
)
async def submit_valuation(
    id: uuid.UUID,
    round: int,
    body: ValuationSubmit,
    request: Request,
    principal: Principal = Depends(EVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).submit_valuation(id, round, body), message="Saved")


@router.get("/answer-scripts/{id}/scan", summary="Signed scan URL", dependencies=ONSCREEN)
async def script_scan(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EVAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).scan_url(id))


# ---- moderation & decode --------------------------------------------------------------------------------------------
@router.get(
    "/exam-papers/{id}/moderation",
    summary="Moderation actions (with impact preview)",
    response_model=Envelope[list[ModerationResponse]],
    dependencies=MODF,
)
async def list_moderation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MOD_APPROVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).list_moderation(id))


@router.post(
    "/exam-papers/{id}/moderation",
    status_code=201,
    summary="Propose a moderation action",
    response_model=Envelope[ModerationResponse],
    dependencies=MODF,
)
async def propose_moderation(
    id: uuid.UUID,
    body: ModerationProposal,
    request: Request,
    principal: Principal = Depends(MODERATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).propose(id, body), message="Proposed")


@router.post(
    "/moderation-actions/{id}/approve",
    summary="Approve (controller of examinations)",
    response_model=Envelope[ModerationResponse],
    dependencies=MODF,
)
async def approve_moderation(
    id: uuid.UUID,
    request: Request,
    body: ModerationDecision | None = None,
    principal: Principal = Depends(MOD_APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).approve(id), message="Approved")


@router.post(
    "/moderation-actions/{id}/apply",
    summary="Apply an approved action",
    response_model=Envelope[ModerationResponse],
    dependencies=MODF,
)
async def apply_moderation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MOD_APPROVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).apply(id), message="Applied")


@router.post(
    "/moderation-actions/{id}/revert",
    summary="Revert an applied action (before decode)",
    response_model=Envelope[ModerationResponse],
    dependencies=MODF,
)
async def revert_moderation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MOD_APPROVE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).revert(id), message="Reverted")


@router.post(
    "/exam-papers/{id}/decode",
    summary="Decode dummy numbers (decoder; IP allow-list)",
    response_model=Envelope[DecodeResponse],
    dependencies=[*CODING, ip_allowlisted("exam_decode")],
)
async def decode(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DECODE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ValuationService(db, principal, request).decode(id), message="Decoded")


# ---- result runs ----------------------------------------------------------------------------------------------------
@router.get("/result-runs", summary="Result runs", response_model=Envelope[list[RunResponse]], dependencies=PROC)
async def list_runs(
    request: Request,
    exam_session_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(RUN_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultRunService(db, principal, request).list_runs(exam_session_id, status))


@router.post("/result-runs", status_code=202, summary="Create and compute a run (job)", dependencies=PROC)
async def create_run(
    body: RunCreateRequest,
    request: Request,
    principal: Principal = Depends(COMPUTE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    svc = ResultRunService(db, principal, request)
    run = await svc.create_run(body)
    j = await enqueue(db, principal, "results.compute_run", {"run_id": str(run.id)})
    run.job_id = j.id
    await db.flush()
    return _queued({"run_id": str(run.id), "job_id": str(j.id)}, "Result run queued")


@router.get("/result-runs/{id}", summary="Result run", response_model=Envelope[RunResponse], dependencies=PROC)
async def get_run(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RUN_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ResultRunService(db, principal, request).get_run(id))


@router.get(
    "/result-runs/{id}/anomalies",
    summary="Anomalies of a run",
    response_model=Envelope[list[AnomalyRow]],
    dependencies=PROC,
)
async def run_anomalies(
    id: uuid.UUID,
    request: Request,
    code: str | None = None,
    principal: Principal = Depends(RUN_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultRunService(db, principal, request).anomalies(id, code))


@router.post(
    "/result-runs/{id}/verify", summary="Verify (exam cell)", response_model=Envelope[RunResponse], dependencies=PROC
)
async def verify_run(
    id: uuid.UUID,
    body: RunAction,
    request: Request,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultRunService(db, principal, request).verify(id, body), message="Verified")


@router.post(
    "/result-runs/{id}/approve", summary="Approve (COE)", response_model=Envelope[RunResponse], dependencies=PROC
)
async def approve_run(
    id: uuid.UUID,
    body: RunAction,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultRunService(db, principal, request).approve(id, body), message="Approved")


@router.post(
    "/result-runs/{id}/rollback",
    summary="Roll back before publication",
    response_model=Envelope[RunResponse],
    dependencies=PROC,
)
async def rollback_run(
    id: uuid.UUID,
    body: RunAction,
    request: Request,
    principal: Principal = Depends(ROLLBACK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultRunService(db, principal, request).rollback(id, body), message="Rolled back")


@router.post("/result-runs/{id}/publish", summary="Publish", response_model=Envelope[RunResponse], dependencies=PROC)
async def publish_run(
    id: uuid.UUID,
    body: PublishRequest,
    request: Request,
    principal: Principal = Depends(PUBLISH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultRunService(db, principal, request).publish(id, body), message="Results published")


@router.get(
    "/result-runs/{id}/rows",
    summary="Rows of a run",
    response_model=Envelope[list[CourseResultResponse]],
    dependencies=PROC,
)
async def run_rows(
    id: uuid.UUID,
    request: Request,
    program_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    status: str | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(RUN_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, total = await ResultRunService(db, principal, request).run_rows(id, program_id, course_id, status, params)
    return ok(rows, pagination=_page(params, total))


@router.get("/result-runs/{id}/export", summary="Rows of a run as XLSX", dependencies=PROC)
async def run_export(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RUN_READ), db: AsyncSession = Depends(get_db)
) -> Response:
    import io

    from openpyxl import Workbook

    rows, _ = await ResultRunService(db, principal, request).run_rows(
        id, None, None, None, PageParams(page=1, page_size=100000)
    )
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "Reg. no",
            "Name",
            "Course",
            "Attempt",
            "CIA",
            "ESE",
            "Grace",
            "Total",
            "%",
            "Grade",
            "GP",
            "Status",
            "Version",
        ]
    )
    for r in rows:
        ws.append(
            [
                r.registration_number,
                r.student_name,
                r.course_code,
                r.attempt_number,
                float(r.cia_marks) if r.cia_marks is not None else None,
                float(r.ese_marks) if r.ese_marks is not None else None,
                float(r.grace_marks),
                float(r.total_marks) if r.total_marks is not None else None,
                float(r.percentage) if r.percentage is not None else None,
                r.letter_grade,
                float(r.grade_point) if r.grade_point is not None else None,
                r.result_status,
                r.version,
            ]
        )
    buf = io.BytesIO()
    wb.save(buf)
    return Response(
        buf.getvalue(), media_type=XLSX, headers={"Content-Disposition": f"attachment; filename=run-{id}.xlsx"}
    )


@router.post("/result-runs/{id}/grade-cards", status_code=202, summary="Generate grade cards (job)", dependencies=CARDS)
async def run_grade_cards(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CARD_GEN), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    await ResultRunService(db, principal, request).run(id)
    j = await enqueue(db, principal, "results.grade_cards", {"run_id": str(id)})
    return _queued({"job_id": str(j.id)}, "Grade cards queued")


# ---- result views ---------------------------------------------------------------------------------------------------
@router.get(
    "/results/me", summary="My published results", response_model=Envelope[MyResultsResponse], dependencies=PORTAL
)
async def my_results(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultQueryService(db, principal, request).my_results(term_id))


@router.get(
    "/results/me/summary",
    summary="My SGPA / CGPA summary",
    response_model=Envelope[MyResultsResponse],
    dependencies=PORTAL,
)
async def my_summary(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    out = await ResultQueryService(db, principal, request).my_results(None)
    for t in out.terms:
        t.courses = []
    return ok(out)


@router.get(
    "/results/tabulation",
    summary="Tabulation register",
    response_model=Envelope[list[TabulationRow]],
    dependencies=RANKS,
)
async def tabulation(
    request: Request,
    batch_id: uuid.UUID,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultQueryService(db, principal, request).tabulation(batch_id, term_id))


@router.get("/results/tabulation/export", summary="Tabulation register (XLSX)", dependencies=RANKS)
async def tabulation_export(
    request: Request,
    batch_id: uuid.UUID,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data = await ResultQueryService(db, principal, request).tabulation_xlsx(batch_id, term_id)
    return Response(data, media_type=XLSX, headers={"Content-Disposition": "attachment; filename=tabulation.xlsx"})


@router.get("/results/analysis", summary="Result analysis", response_model=Envelope[ResultAnalysis], dependencies=RANKS)
async def analysis(
    request: Request,
    session_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultQueryService(db, principal, request).analysis(session_id, batch_id))


@router.get("/results/rank-list", summary="Rank list", dependencies=RANKS)
async def rank_list(
    request: Request,
    batch_id: uuid.UUID,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ResultQueryService(db, principal, request).rank_list(batch_id, term_id))


@router.get(
    "/results/wards/{student_id}",
    summary="A ward's results",
    response_model=Envelope[MyResultsResponse],
    dependencies=PORTAL,
)
async def ward_results(
    student_id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ResultQueryService(db, principal, request).ward_results(student_id))


@router.get(
    "/students/{id}/results",
    summary="A student's published results",
    response_model=Envelope[MyResultsResponse],
    dependencies=PORTAL,
)
async def student_results(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ResultQueryService(db, principal, request).student_results(id))


@router.get(
    "/course-offerings/{id}/results",
    summary="Result sheet of an offering",
    response_model=Envelope[list[CourseResultResponse]],
    dependencies=PORTAL,
)
async def offering_results(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ResultQueryService(db, principal, request).offering_results(id))


# ---- grade cards ------------------------------------------------------------------------------------------------------
@router.get(
    "/grade-cards/me", summary="My grade cards", response_model=Envelope[list[GradeCardResponse]], dependencies=CARDS
)
async def my_cards(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GradeCardService(db, principal, request).my_cards(term_id))


@router.get(
    "/students/{id}/grade-cards",
    summary="A student's grade cards",
    response_model=Envelope[list[GradeCardResponse]],
    dependencies=CARDS,
)
async def student_cards(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CARD_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GradeCardService(db, principal, request).student_cards(id))


@router.get("/grade-cards/{id}.pdf", summary="Grade card PDF", dependencies=CARDS)
async def card_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CARD_READ), db: AsyncSession = Depends(get_db)
) -> Response:
    data, name = await GradeCardService(db, principal, request).pdf(id)
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename={name}.pdf"})


# ---- legacy import ------------------------------------------------------------------------------------------------------
@router.post(
    "/legacy-results/imports",
    status_code=201,
    summary="Upload legacy results",
    response_model=Envelope[LegacyImportResponse],
    dependencies=LEGACYF,
)
async def legacy_create(
    request: Request,
    batch_id: uuid.UUID = Form(...),
    term_number: int = Form(...),
    mapping: str | None = Form(default=None, description="JSON {field: column}"),
    file: UploadFile | None = File(default=None),
    principal: Principal = Depends(LEGACY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    import json

    body = LegacyImportCreate(
        batch_id=batch_id, term_number=term_number, mapping=json.loads(mapping) if mapping else {}
    )
    return ok(await LegacyImportService(db, principal, request).create(body, file), message="Uploaded")


@router.get(
    "/legacy-results/imports/{id}",
    summary="Legacy import",
    response_model=Envelope[LegacyImportResponse],
    dependencies=LEGACYF,
)
async def legacy_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LEGACY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LegacyImportService(db, principal, request).get(id))


@router.post(
    "/legacy-results/imports/{id}/validate",
    summary="Validate a legacy import",
    response_model=Envelope[LegacyImportResponse],
    dependencies=LEGACYF,
)
async def legacy_validate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LEGACY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LegacyImportService(db, principal, request).validate(id))


@router.post(
    "/legacy-results/imports/{id}/apply",
    summary="Apply a validated import",
    response_model=Envelope[LegacyImportResponse],
    dependencies=LEGACYF,
)
async def legacy_apply(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LEGACY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LegacyImportService(db, principal, request).apply(id), message="Applied")


@router.post(
    "/legacy-results/imports/{id}/rollback",
    summary="Roll back an applied import",
    response_model=Envelope[LegacyImportResponse],
    dependencies=LEGACYF,
)
async def legacy_rollback(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LEGACY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await LegacyImportService(db, principal, request).rollback(id), message="Rolled back")


# ---- script retention -------------------------------------------------------------------------------------------------
@router.post("/exam-sessions/{id}/scripts/archive", summary="Archive scripts", dependencies=CUSTODYF)
async def scripts_archive(
    id: uuid.UUID,
    request: Request,
    body: ScriptRetentionRequest | None = None,
    principal: Principal = Depends(CUSTODY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    req = ScriptRetentionRequest(action="archive", bundle_ids=body.bundle_ids if body else None)
    return ok(await CodingService(db, principal, request).retention(id, req), message="Archived")


@router.post("/exam-sessions/{id}/scripts/destroy", summary="Destroy archived scripts (COE)", dependencies=CUSTODYF)
async def scripts_destroy(
    id: uuid.UUID,
    request: Request,
    body: ScriptRetentionRequest | None = None,
    principal: Principal = Depends(CUSTODY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    req = ScriptRetentionRequest(
        action="destroy",
        bundle_ids=body.bundle_ids if body else None,
        approval_note=body.approval_note if body else None,
    )
    return ok(await CodingService(db, principal, request).retention(id, req), message="Destroyed")


@router.get(
    "/exam-sessions/{id}/scripts/register",
    summary="Script custody / retention register",
    response_model=Envelope[list[ScriptRegisterRow]],
    dependencies=CUSTODYF,
)
async def scripts_register(
    id: uuid.UUID, request: Request, principal: Principal = Depends(BUNDLE_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CodingService(db, principal, request).register(id))


# ---- public lookup ----------------------------------------------------------------------------------------------------
@public_router.post(
    "/public/results/lookup",
    summary="Public result lookup (registration no. + date of birth)",
    response_model=Envelope[PublicLookupResponse],
    dependencies=[rate_limited("results_lookup", limit=20, window=60)],
)
async def public_lookup_route(
    body: PublicLookupRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.errors import APIError, ErrorCode
    from app.core.features import is_enabled
    from app.db.session import bind_tenant, set_tenant
    from app.models.platform import Institution
    from app.services.results.query_service import public_lookup
    from app.services.settings_service import SettingsService

    await verify_captcha(request.headers.get("x-captcha-token"), request.client.host if request.client else None)
    slug = body.institution or request.query_params.get("institution") or request.headers.get("x-institution-slug")
    inst = (
        (
            await db.execute(select(Institution).where(Institution.slug == slug, Institution.deleted_at.is_(None)))
        ).scalar_one_or_none()
        if slug
        else None
    )
    if inst is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "No published result for these details")
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if not await is_enabled(inst.id, "results.publication_portal") or not await SettingsService(db).value(
        inst.id, "exams", "result_public_lookup"
    ):
        raise APIError(404, ErrorCode.NOT_FOUND, "No published result for these details")
    return ok(await public_lookup(db, inst.id, body.reg_no, body.dob))
