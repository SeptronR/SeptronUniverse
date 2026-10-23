"""Post-result services — Prompts/16 §16.8.

``router`` (each route carries its feature): revaluation family {results.revaluation} (photocopy {results.photocopy},
challenge panel {results.challenge_valuation}), supplementary {results.supplementary}, malpractice
{results.malpractice}, withheld (results:approve), detention / readmission {students.core}, transcripts
{results.transcripts}, rank lists / medals {results.rank_lists}, corrections (``marks.change`` workflow).
``public_router``: masked public rank lists. Transcript QR verification is served by ``GET /verify/{token}``.
Reval / transcript requests honour ``Idempotency-Key``; ``reval/apply`` answers ``202`` + ``job_id``. Fixed paths
precede parameterised ones.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.post_result import (
    AppealCreate,
    AppealDecision,
    ChallengePanelRequest,
    CorrectionRequestCreate,
    CorrectionResponse,
    DetentionRow,
    InquiryUpdate,
    MalpracticeCaseCreate,
    MalpracticeCaseResponse,
    MalpracticeDecision,
    MedalAwardCreate,
    MedalResponse,
    RankListPublish,
    RankListResponse,
    ReadmissionRequest,
    ReadmissionResponse,
    RetotalRequest,
    RevalApplyResponse,
    RevalAssignRequest,
    RevalCreate,
    RevalDecision,
    RevalEligibilityResponse,
    RevalMarks,
    RevalResponse,
    RevalScript,
    StudentStatementSubmit,
    SupplementaryCreateRequest,
    SupplementaryPreview,
    TranscriptIssueRequest,
    TranscriptRequestCreate,
    TranscriptResponse,
    TranscriptTypeOut,
    WithheldReleaseRequest,
    WithheldRow,
    WorkflowDecisionBody,
)
from app.services.post_result.malpractice_service import MalpracticeService
from app.services.post_result.rank_service import CorrectionService, RankService, public_rank_list
from app.services.post_result.reval_service import RevalService
from app.services.post_result.supplementary_service import SupplementaryService
from app.services.post_result.transcript_service import TranscriptService
from app.services.post_result.withheld_service import DetentionService, WithheldService
from app.utils.response import ok

router = APIRouter(tags=["post-results"])
public_router = APIRouter(tags=["public"])

E, R, S, M = "exams", "results", "students", "marks"
EXAM_SELF = any_permission_required((E, "self"), (E, "view"))
REVAL = permission_required(E, "reval")
REVAL_READ = any_permission_required((E, "reval"), (E, "view_all"), (E, "manage"))
EVAL = permission_required(E, "evaluate")
APPLY = any_permission_required((R, "compute"), (R, "approve"), (R, "manage"))
EXAM_MANAGE = permission_required(E, "manage")
MAL = permission_required(E, "malpractice")
MAL_READ = any_permission_required((E, "malpractice"), (E, "view_all"), (E, "manage"), (E, "view"))
MAL_DECIDE = any_permission_required((E, "malpractice"), (E, "manage"), (E, "view"))
WITHHELD_READ = any_permission_required((R, "approve"), (R, "manage"), (R, "view_all"))
WITHHELD_RELEASE = any_permission_required((R, "approve"), (R, "manage"))
DETAINED = any_permission_required((S, "manage"), (S, "view_all"))
READMIT = any_permission_required((S, "manage"), (S, "self"))
READMIT_DECIDE = permission_required(S, "manage")
TR_SELF = any_permission_required((R, "transcript"), (R, "self"), (R, "view"))
TR_OFFICE = permission_required(R, "transcript")
RANK_READ = any_permission_required((R, "view_all"), (R, "manage"))
RANK_PUBLISH = any_permission_required((R, "publish"), (R, "approve"), (R, "manage"))
RANK_SELF = any_permission_required((R, "self"), (R, "view"))
MEDAL_READ = any_permission_required((R, "view_all"), (R, "approve"), (R, "manage"))
MEDAL = any_permission_required((R, "approve"), (R, "manage"))
CORR_CREATE = any_permission_required((M, "correct"), (R, "verify"), (M, "enter"))
CORR_READ = any_permission_required((M, "correct"), (R, "verify"), (R, "manage"))
CORR_DECIDE = any_permission_required((M, "correct"), (R, "approve"), (R, "manage"))

REVALF = [feature_required("results.revaluation")]
PHOTOF = [feature_required("results.photocopy")]
CHALLENGEF = [feature_required("results.challenge_valuation")]
SUPPF = [feature_required("results.supplementary")]
MALF = [feature_required("results.malpractice")]
TRF = [feature_required("results.transcripts")]
RANKF = [feature_required("results.rank_lists")]
PROCF = [feature_required("results.processing")]
STUF = [feature_required("students.core")]


def _pdf(data: bytes, name: str) -> Response:
    return Response(
        content=data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'}
    )


# ---- revaluation family --------------------------------------------------------------------------------------------------
@router.get(
    "/reval/eligibility",
    summary="Results open for retotaling / photocopy / revaluation",
    response_model=Envelope[RevalEligibilityResponse],
    dependencies=REVALF,
)
async def reval_eligibility(
    session_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(EXAM_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).eligibility(session_id))


@router.post(
    "/reval-requests",
    summary="Raise a request (Idempotency-Key)",
    response_model=Envelope[RevalResponse],
    dependencies=REVALF,
)
async def reval_create(
    body: RevalCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(EXAM_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await RevalService(db, principal, request).create(body)
    response = ok(out.model_dump(mode="json"), message="Request raised")
    await store(request, response, db)
    return response


@router.get(
    "/reval-requests/me", summary="My requests", response_model=Envelope[list[RevalResponse]], dependencies=REVALF
)
async def reval_mine(
    request: Request, principal: Principal = Depends(EXAM_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).my_requests())


@router.get(
    "/valuation/me/reval-scripts",
    summary="Revaluation scripts assigned to me (dummy numbers)",
    response_model=Envelope[list[RevalScript]],
    dependencies=REVALF,
)
async def reval_scripts(
    request: Request, principal: Principal = Depends(EVAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).my_scripts())


@router.get(
    "/exam-sessions/{id}/reval-requests",
    summary="Requests of a session",
    response_model=Envelope[list[RevalResponse]],
    dependencies=REVALF,
)
async def reval_session(
    id: uuid.UUID,
    request: Request,
    type: str | None = None,
    status: str | None = None,
    principal: Principal = Depends(REVAL_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).session_requests(id, type, status))


@router.post(
    "/exam-sessions/{id}/reval/apply",
    status_code=202,
    summary="Apply changed marks → revaluation run (job)",
    response_model=Envelope[RevalApplyResponse],
    dependencies=REVALF,
)
async def reval_apply(
    id: uuid.UUID, request: Request, principal: Principal = Depends(APPLY), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    out = await RevalService(db, principal, request).apply(id)
    return JSONResponse(
        status_code=202, content=ok(out.model_dump(mode="json"), message=f"{out.requests} request(s) applied")
    )


@router.post(
    "/exam-sessions/{id}/challenge-panel",
    summary="Assign a two-evaluator challenge panel",
    response_model=Envelope[list[RevalResponse]],
    dependencies=CHALLENGEF,
)
async def challenge_panel(
    id: uuid.UUID,
    body: ChallengePanelRequest,
    request: Request,
    principal: Principal = Depends(REVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).challenge_panel(id, body))


@router.get("/reval-requests/{id}", summary="Request", response_model=Envelope[RevalResponse], dependencies=REVALF)
async def reval_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EXAM_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).get(id))


@router.get("/reval-requests/{id}/photocopy.pdf", summary="Watermarked photocopy", dependencies=PHOTOF)
async def reval_photocopy(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EXAM_SELF), db: AsyncSession = Depends(get_db)
) -> Response:
    return _pdf(await RevalService(db, principal, request).photocopy(id), f"photocopy-{id.hex[:8]}")


@router.post(
    "/reval-requests/{id}/assign",
    summary="Assign a revaluation evaluator",
    response_model=Envelope[RevalResponse],
    dependencies=REVALF,
)
async def reval_assign(
    id: uuid.UUID,
    body: RevalAssignRequest,
    request: Request,
    principal: Principal = Depends(REVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).assign(id, body))


@router.post(
    "/reval-requests/{id}/retotal",
    summary="Retotal (exam cell)",
    response_model=Envelope[RevalResponse],
    dependencies=PHOTOF,
)
async def reval_retotal(
    id: uuid.UUID,
    body: RetotalRequest,
    request: Request,
    principal: Principal = Depends(REVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).retotal(id, body))


@router.post(
    "/reval-requests/{id}/valuation",
    summary="Submit revaluation marks (assigned evaluator)",
    response_model=Envelope[RevalScript],
    dependencies=REVALF,
)
async def reval_valuation(
    id: uuid.UUID,
    body: RevalMarks,
    request: Request,
    principal: Principal = Depends(EVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).submit_valuation(id, body))


@router.post(
    "/reval-requests/{id}/decide", summary="Decide", response_model=Envelope[RevalResponse], dependencies=REVALF
)
async def reval_decide(
    id: uuid.UUID,
    body: RevalDecision,
    request: Request,
    principal: Principal = Depends(REVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).decide(id, body))


@router.post(
    "/reval-requests/{id}/challenge/decide",
    summary="Decide a challenge (panel mean)",
    response_model=Envelope[RevalResponse],
    dependencies=CHALLENGEF,
)
async def challenge_decide(
    id: uuid.UUID,
    body: RevalDecision,
    request: Request,
    principal: Principal = Depends(REVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).decide(id, body))


@router.post(
    "/reval-requests/{id}/reject", summary="Reject", response_model=Envelope[RevalResponse], dependencies=REVALF
)
async def reval_reject(
    id: uuid.UUID,
    body: WorkflowDecisionBody,
    request: Request,
    principal: Principal = Depends(REVAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RevalService(db, principal, request).reject(id, body.comment or "Rejected"))


# ---- supplementary ----------------------------------------------------------------------------------------------------------
@router.post(
    "/exam-sessions/supplementary/preview",
    summary="Open arrears by course",
    response_model=Envelope[SupplementaryPreview],
    dependencies=SUPPF,
)
async def supplementary_preview(
    body: SupplementaryCreateRequest,
    request: Request,
    principal: Principal = Depends(EXAM_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SupplementaryService(db, principal, request).preview(body))


@router.post(
    "/exam-sessions/supplementary",
    status_code=202,
    summary="Create a supplementary / arrear session with registrations",
    response_model=Envelope[dict[str, Any]],
    dependencies=SUPPF,
)
async def supplementary_create(
    body: SupplementaryCreateRequest,
    request: Request,
    principal: Principal = Depends(EXAM_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await SupplementaryService(db, principal, request).create(body)
    return JSONResponse(status_code=202, content=ok(out, message=f"Session created with {out['papers']} paper(s)"))


# ---- malpractice ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/malpractice-cases", summary="Cases", response_model=Envelope[list[MalpracticeCaseResponse]], dependencies=MALF
)
async def mal_list(
    request: Request,
    session_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(MAL_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).list_cases(session_id, status))


@router.post(
    "/malpractice-cases", summary="Register a case", response_model=Envelope[MalpracticeCaseResponse], dependencies=MALF
)
async def mal_create(
    body: MalpracticeCaseCreate,
    request: Request,
    principal: Principal = Depends(MAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).create(body))


@router.get(
    "/malpractice-cases/me",
    summary="My cases (student / ward)",
    response_model=Envelope[list[MalpracticeCaseResponse]],
    dependencies=MALF,
)
async def mal_mine(
    request: Request, principal: Principal = Depends(EXAM_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).my_cases())


@router.get(
    "/malpractice-cases/{id}", summary="Case", response_model=Envelope[MalpracticeCaseResponse], dependencies=MALF
)
async def mal_get(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(
        any_permission_required((E, "malpractice"), (E, "view_all"), (E, "manage"), (E, "view"), (E, "self"))
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).get(id))


@router.post(
    "/malpractice-cases/{id}/inquiry",
    summary="Assign the inquiry committee / hearing",
    response_model=Envelope[MalpracticeCaseResponse],
    dependencies=MALF,
)
async def mal_inquiry(
    id: uuid.UUID,
    body: InquiryUpdate,
    request: Request,
    principal: Principal = Depends(MAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).inquiry(id, body))


@router.post(
    "/malpractice-cases/{id}/notice",
    summary="Send the notice (student + guardians)",
    response_model=Envelope[MalpracticeCaseResponse],
    dependencies=MALF,
)
async def mal_notice(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).notice(id))


@router.post(
    "/malpractice-cases/{id}/hearing",
    summary="Schedule the hearing (sends the notice)",
    response_model=Envelope[MalpracticeCaseResponse],
    dependencies=MALF,
)
async def mal_hearing(
    id: uuid.UUID,
    body: InquiryUpdate,
    request: Request,
    principal: Principal = Depends(MAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).hearing(id, body))


@router.post(
    "/malpractice-cases/{id}/statement",
    summary="Submit the student's statement",
    response_model=Envelope[MalpracticeCaseResponse],
    dependencies=MALF,
)
async def mal_statement(
    id: uuid.UUID,
    body: StudentStatementSubmit,
    request: Request,
    principal: Principal = Depends(permission_required(E, "self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).statement(id, body))


@router.post(
    "/malpractice-cases/{id}/decide",
    summary="Decide the punishment (COE / committee chair)",
    response_model=Envelope[MalpracticeCaseResponse],
    dependencies=MALF,
)
async def mal_decide(
    id: uuid.UUID,
    body: MalpracticeDecision,
    request: Request,
    principal: Principal = Depends(MAL_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).decide(id, body))


@router.post(
    "/malpractice-cases/{id}/appeal",
    summary="Appeal",
    response_model=Envelope[MalpracticeCaseResponse],
    dependencies=MALF,
)
async def mal_appeal(
    id: uuid.UUID,
    body: AppealCreate,
    request: Request,
    principal: Principal = Depends(permission_required(E, "self")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).appeal(id, body))


@router.post(
    "/malpractice-cases/{id}/appeal/decide",
    summary="Decide the appeal (committee / COE)",
    response_model=Envelope[MalpracticeCaseResponse],
    dependencies=MALF,
)
async def mal_appeal_decide(
    id: uuid.UUID,
    body: AppealDecision,
    request: Request,
    principal: Principal = Depends(MAL_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).appeal_decide(id, body))


@router.post(
    "/malpractice-cases/{id}/close",
    summary="Close",
    response_model=Envelope[MalpracticeCaseResponse],
    dependencies=MALF,
)
async def mal_close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MalpracticeService(db, principal, request).close(id))


# ---- withheld ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/results/withheld",
    summary="Withheld rows with reasons",
    response_model=Envelope[list[WithheldRow]],
    dependencies=PROCF,
)
async def withheld(
    request: Request,
    session_id: uuid.UUID | None = None,
    principal: Principal = Depends(WITHHELD_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WithheldService(db, principal, request).list_withheld(session_id))


@router.post(
    "/results/withheld/release",
    summary="Release withheld rows (correction run, published)",
    response_model=Envelope[dict[str, Any]],
    dependencies=PROCF,
)
async def withheld_release(
    body: WithheldReleaseRequest,
    request: Request,
    principal: Principal = Depends(WITHHELD_RELEASE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await WithheldService(db, principal, request).release(body))


# ---- detention / readmission ----------------------------------------------------------------------------------------------------
@router.get(
    "/terms/{id}/detained",
    summary="Detained students of a term",
    response_model=Envelope[list[DetentionRow]],
    dependencies=STUF,
)
async def detained(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DETAINED), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DetentionService(db, principal, request).detained(id))


@router.get(
    "/readmissions",
    summary="Readmission requests",
    response_model=Envelope[list[ReadmissionResponse]],
    dependencies=STUF,
)
async def readmissions(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(READMIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DetentionService(db, principal, request).list_readmissions(status))


@router.post(
    "/readmissions",
    summary="Request readmission (workflow students.readmission)",
    response_model=Envelope[ReadmissionResponse],
    dependencies=STUF,
)
async def readmission_create(
    body: ReadmissionRequest,
    request: Request,
    principal: Principal = Depends(READMIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DetentionService(db, principal, request).submit(body))


@router.post(
    "/readmissions/{id}/approve", summary="Approve", response_model=Envelope[ReadmissionResponse], dependencies=STUF
)
async def readmission_approve(
    id: uuid.UUID,
    body: WorkflowDecisionBody,
    request: Request,
    principal: Principal = Depends(READMIT_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DetentionService(db, principal, request).decide(id, True, body.comment))


@router.post(
    "/readmissions/{id}/reject", summary="Reject", response_model=Envelope[ReadmissionResponse], dependencies=STUF
)
async def readmission_reject(
    id: uuid.UUID,
    body: WorkflowDecisionBody,
    request: Request,
    principal: Principal = Depends(READMIT_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DetentionService(db, principal, request).decide(id, False, body.comment))


# ---- transcripts ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/transcripts/types",
    summary="Transcript types and fees",
    response_model=Envelope[list[TranscriptTypeOut]],
    dependencies=TRF,
)
async def transcript_types(
    request: Request, principal: Principal = Depends(TR_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TranscriptService(db, principal, request).types())


@router.post(
    "/transcripts/requests",
    summary="Request a transcript (Idempotency-Key)",
    response_model=Envelope[TranscriptResponse],
    dependencies=TRF,
)
async def transcript_request(
    body: TranscriptRequestCreate,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(TR_SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await TranscriptService(db, principal, request).request_transcript(body)
    response = ok(out.model_dump(mode="json"), message="Transcript requested")
    await store(request, response, db)
    return response


@router.get(
    "/transcripts/requests",
    summary="Transcript queue",
    response_model=Envelope[list[TranscriptResponse]],
    dependencies=TRF,
)
async def transcript_queue(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(TR_OFFICE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TranscriptService(db, principal, request).queue(status))


@router.get(
    "/transcripts/me", summary="My transcripts", response_model=Envelope[list[TranscriptResponse]], dependencies=TRF
)
async def transcript_mine(
    request: Request, principal: Principal = Depends(TR_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TranscriptService(db, principal, request).mine_list())


@router.get(
    "/transcripts/{id}/checks",
    summary="Holds / no-dues checks",
    dependencies=TRF,
    response_model=Envelope[dict[str, Any]],
)
async def transcript_checks(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TR_OFFICE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = TranscriptService(db, principal, request)
    return ok(await svc.checks(await svc.tr(id)))


@router.get("/transcripts/{id}/download", summary="Transcript PDF", dependencies=TRF)
async def transcript_download(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TR_SELF), db: AsyncSession = Depends(get_db)
) -> Response:
    data, name = await TranscriptService(db, principal, request).download(id)
    return _pdf(data, name)


@router.post(
    "/transcripts/{id}/approve",
    summary="Approve (registrar)",
    response_model=Envelope[TranscriptResponse],
    dependencies=TRF,
)
async def transcript_approve(
    id: uuid.UUID,
    body: WorkflowDecisionBody,
    request: Request,
    principal: Principal = Depends(TR_OFFICE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TranscriptService(db, principal, request).approve(id, body.comment))


@router.post(
    "/transcripts/{id}/generate",
    summary="Generate the PDF",
    response_model=Envelope[TranscriptResponse],
    dependencies=TRF,
)
async def transcript_generate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TR_OFFICE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TranscriptService(db, principal, request).generate(id))


@router.post("/transcripts/{id}/issue", summary="Issue", response_model=Envelope[TranscriptResponse], dependencies=TRF)
async def transcript_issue(
    id: uuid.UUID,
    body: TranscriptIssueRequest,
    request: Request,
    principal: Principal = Depends(TR_OFFICE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await TranscriptService(db, principal, request).issue(id, body))


@router.post(
    "/transcripts/{id}/reissue",
    summary="Reissue with a new token",
    response_model=Envelope[TranscriptResponse],
    dependencies=TRF,
)
async def transcript_reissue(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TR_OFFICE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TranscriptService(db, principal, request).reissue(id))


@router.post(
    "/transcripts/{id}/cancel", summary="Cancel", response_model=Envelope[TranscriptResponse], dependencies=TRF
)
async def transcript_cancel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(TR_OFFICE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await TranscriptService(db, principal, request).cancel(id))


# ---- rank lists / medals -------------------------------------------------------------------------------------------------------
@router.get(
    "/results/rank-lists",
    summary="Compute a rank list (term SGPA or cumulative CGPA)",
    response_model=Envelope[RankListResponse],
    dependencies=RANKF,
)
async def rank_lists(
    batch_id: uuid.UUID,
    request: Request,
    term_id: uuid.UUID | None = None,
    cumulative: bool = False,
    program_id: uuid.UUID | None = None,
    top_n: int = 50,
    principal: Principal = Depends(RANK_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await RankService(db, principal, request).compute(
            batch_id, None if cumulative else term_id, program_id, max(1, min(top_n, 500))
        )
    )


@router.get(
    "/results/rank-lists/published",
    summary="Published rank lists",
    response_model=Envelope[list[RankListResponse]],
    dependencies=RANKF,
)
async def rank_lists_published(
    request: Request, principal: Principal = Depends(RANK_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RankService(db, principal, request).published_lists())


@router.get(
    "/results/rank-lists/me", summary="My ranks", response_model=Envelope[list[dict[str, Any]]], dependencies=RANKF
)
async def rank_mine(
    request: Request, principal: Principal = Depends(RANK_SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RankService(db, principal, request).my_ranks())


@router.post(
    "/results/rank-lists/publish",
    summary="Publish a rank list",
    response_model=Envelope[RankListResponse],
    dependencies=RANKF,
)
async def rank_publish(
    body: RankListPublish,
    request: Request,
    principal: Principal = Depends(RANK_PUBLISH),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RankService(db, principal, request).publish(body))


@router.get("/results/medals", summary="Medals", response_model=Envelope[list[MedalResponse]], dependencies=RANKF)
async def medals(
    request: Request,
    batch_id: uuid.UUID | None = None,
    principal: Principal = Depends(MEDAL_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RankService(db, principal, request).medals(batch_id))


@router.post("/results/medals", summary="Award a medal", response_model=Envelope[MedalResponse], dependencies=RANKF)
async def medal_award(
    body: MedalAwardCreate, request: Request, principal: Principal = Depends(MEDAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RankService(db, principal, request).award(body))


@router.post(
    "/results/medals/{id}/revoke", summary="Revoke a medal", response_model=Envelope[dict[str, Any]], dependencies=RANKF
)
async def medal_revoke(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MEDAL), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RankService(db, principal, request).revoke(id))


# ---- corrections ------------------------------------------------------------------------------------------------------------------
@router.post(
    "/results/corrections",
    summary="Raise a correction on a published row (workflow marks.change)",
    response_model=Envelope[CorrectionResponse],
    dependencies=PROCF,
)
async def correction_create(
    body: CorrectionRequestCreate,
    request: Request,
    principal: Principal = Depends(CORR_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CorrectionService(db, principal, request).create(body))


@router.get(
    "/results/corrections",
    summary="Correction requests",
    response_model=Envelope[list[CorrectionResponse]],
    dependencies=PROCF,
)
async def corrections(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(CORR_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CorrectionService(db, principal, request).list_corrections(status))


@router.post(
    "/results/corrections/{id}/approve",
    summary="Approve the current step",
    response_model=Envelope[CorrectionResponse],
    dependencies=PROCF,
)
async def correction_approve(
    id: uuid.UUID,
    body: WorkflowDecisionBody,
    request: Request,
    principal: Principal = Depends(CORR_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CorrectionService(db, principal, request).decide(id, True, body.comment))


@router.post(
    "/results/corrections/{id}/reject",
    summary="Reject",
    response_model=Envelope[CorrectionResponse],
    dependencies=PROCF,
)
async def correction_reject(
    id: uuid.UUID,
    body: WorkflowDecisionBody,
    request: Request,
    principal: Principal = Depends(CORR_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CorrectionService(db, principal, request).decide(id, False, body.comment))


# ---- public ---------------------------------------------------------------------------------------------------------------------------
@public_router.get(
    "/public/results/rank-lists/{id}",
    summary="Published rank list (masked; public when allowed)",
    response_model=Envelope[dict[str, Any]],
)
async def public_rank(id: uuid.UUID) -> dict[str, Any]:
    return ok(await public_rank_list(id))
