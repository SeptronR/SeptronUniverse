"""Internal assessment + OBE definitions — Prompts/13 §13.8 (router included with
``feature_required("assessment.internal_marks")``; per-route {assessment.question_wise_co}, {assessment.marks_workflow},
{assessment.marks_change_requests}; the OBE routes live on ``obe_router`` with {obe.definitions}).

Marks import / export answer ``202`` + ``job_id``. Fixed paths precede parameterised ones.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.assessment import (
    AssessmentQuestionOut,
    ChangeRequestCreate,
    ChangeRequestDecision,
    ChangeRequestOut,
    ConsolidateResponse,
    InstantiateRequest,
    InstantiateResult,
    MarksBulkUpsert,
    MarksGridResponse,
    MarksResult,
    MyMarksRow,
    OfferingAssessmentResponse,
    QuestionMapReplace,
    ReasonRequest,
    VerifyRequest,
)
from app.schemas.common import Envelope
from app.schemas.obe import (
    CoPoMatrixReplace,
    CoReplace,
    CourseOutcomes,
    OutcomesReplace,
    PeoPoMatrix,
    ProgramOutcomes,
    TemplateImport,
)
from app.services.assessment.assessment_service import AssessmentService
from app.services.assessment.obe_service import ObeService
from app.utils.response import ok

router = APIRouter(tags=["assessment"])
obe_router = APIRouter(tags=["obe"])

M = "marks"
VIEW = any_permission_required((M, "view"), (M, "view_all"), (M, "enter"), (M, "verify"), (M, "lock"))
ENTER = permission_required(M, "enter")
VERIFY = permission_required(M, "verify")
LOCK = permission_required(M, "lock")
EXPORT = any_permission_required((M, "export"), (M, "enter"), (M, "view_all"))
CIA_WRITE = any_permission_required((M, "enter"), (M, "verify"), (M, "lock"))
CR_CREATE = any_permission_required((M, "enter"), (M, "correct"), (M, "verify"))
CR_VIEW = any_permission_required((M, "enter"), (M, "correct"), (M, "verify"), (M, "lock"), (M, "view_all"))
CR_DECIDE = any_permission_required((M, "correct"), (M, "verify"), (M, "lock"))
CR_APPLY = any_permission_required((M, "correct"), (M, "lock"))
QWISE = [feature_required("assessment.question_wise_co")]
FLOW = [feature_required("assessment.marks_workflow")]
CRF = [feature_required("assessment.marks_change_requests")]
OBE_VIEW = any_permission_required(("obe", "view"), ("obe", "view_all"), ("obe", "manage"), (M, "enter"), (M, "verify"))
OBE_MANAGE = permission_required("obe", "manage")
CO_WRITE = any_permission_required(("obe", "manage"), (M, "enter"))


def _queued(data: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(data, message=message))


# ---- assessments ------------------------------------------------------------------------------------------------------------
@router.get("/marks/me", summary="My internal marks per offering", response_model=Envelope[list[MyMarksRow]])
async def my_marks(
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).my_marks(term_id))


@router.get(
    "/offering-assessments",
    summary="Assessments across visible offerings (status / scope filters — verification and lock queues)",
    response_model=Envelope[list[OfferingAssessmentResponse]],
)
async def assessment_queue(
    request: Request,
    status: str | None = None,
    scope: str | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).queue(status, scope))


@router.get(
    "/course-offerings/{id}/assessments",
    summary="Assessments of an offering",
    response_model=Envelope[list[OfferingAssessmentResponse]],
)
async def list_assessments(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).list_for(id))


@router.post(
    "/course-offerings/{id}/assessments/instantiate",
    summary="Instantiate from the assessment scheme (idempotent)",
    response_model=Envelope[InstantiateResult],
)
async def instantiate(
    id: uuid.UUID,
    request: Request,
    body: InstantiateRequest | None = None,
    principal: Principal = Depends(ENTER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await AssessmentService(db, principal, request).instantiate(id, body)
    return ok(out, message=f"{out.created} created, {out.existing} existing")


@router.get(
    "/offering-assessments/{id}/questions",
    summary="Question → CO map",
    dependencies=QWISE,
    response_model=Envelope[list[AssessmentQuestionOut]],
)
async def get_questions(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).questions(id))


@router.put(
    "/offering-assessments/{id}/questions",
    summary="Replace the question map (sums to max marks)",
    dependencies=QWISE,
    response_model=Envelope[list[AssessmentQuestionOut]],
)
async def put_questions(
    id: uuid.UUID,
    body: QuestionMapReplace,
    request: Request,
    principal: Principal = Depends(ENTER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).replace_questions(id, body), message="Question map saved")


@router.get(
    "/offering-assessments/{id}/marks",
    summary="Marks grid (learners / parents see their own row)",
    response_model=Envelope[MarksGridResponse],
)
async def grid(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).grid(id))


@router.post(
    "/offering-assessments/{id}/marks", summary="Bulk upsert (Idempotency-Key)", response_model=Envelope[MarksResult]
)
async def bulk(
    id: uuid.UUID,
    body: MarksBulkUpsert,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(ENTER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await AssessmentService(db, principal, request).bulk_upsert(id, body)
    response = ok(out.model_dump(mode="json"), message=f"{out.saved} saved, {len(out.rejected)} rejected")
    await store(request, response, db)
    return response


@router.post(
    "/offering-assessments/{id}/marks/import",
    status_code=202,
    summary="Import marks XLSX / CSV (job)",
    response_model=Envelope[dict[str, Any]],
)
async def import_marks(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(ENTER),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    import base64

    from app.core.jobs import enqueue

    await AssessmentService(db, principal, request).get_assessment(id)
    raw = await file.read()
    job = await enqueue(
        db,
        principal,
        "assessment.import_marks",
        {
            "assessment_id": str(id),
            "filename": file.filename or "marks.xlsx",
            "content_b64": base64.b64encode(raw).decode(),
        },
    )
    return _queued({"job_id": str(job.id)}, "Import queued")


@router.get(
    "/offering-assessments/{id}/export",
    status_code=202,
    summary="Export the marks grid (XLSX job)",
    response_model=Envelope[dict[str, Any]],
)
async def export_marks(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EXPORT), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    await AssessmentService(db, principal, request).get_assessment(id)
    job = await enqueue(db, principal, "assessment.export", {"assessment_id": str(id)})
    return _queued({"job_id": str(job.id)}, "Export queued")


@router.post(
    "/offering-assessments/{id}/submit",
    summary="Submit for verification (all rostered students marked)",
    dependencies=FLOW,
    response_model=Envelope[OfferingAssessmentResponse],
)
async def submit(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ENTER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).submit(id), message="Submitted")


@router.post(
    "/offering-assessments/{id}/verify",
    summary="HOD verify / reject",
    dependencies=FLOW,
    response_model=Envelope[OfferingAssessmentResponse],
)
async def verify(
    id: uuid.UUID,
    body: VerifyRequest,
    request: Request,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await AssessmentService(db, principal, request).verify(id, body),
        message="Verified" if body.decision == "approve" else "Returned for correction",
    )


@router.post(
    "/offering-assessments/{id}/lock",
    summary="Lock (exam cell / COE)",
    dependencies=FLOW,
    response_model=Envelope[OfferingAssessmentResponse],
)
async def lock(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LOCK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).lock(id), message="Locked")


@router.post(
    "/offering-assessments/{id}/reopen",
    summary="Reopen for correction (exam cell / COE)",
    dependencies=FLOW,
    response_model=Envelope[OfferingAssessmentResponse],
)
async def reopen(
    id: uuid.UUID,
    body: ReasonRequest,
    request: Request,
    principal: Principal = Depends(LOCK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).reopen(id, body.reason), message="Reopened")


# ---- CIA ---------------------------------------------------------------------------------------------------------------------
@router.get(
    "/course-offerings/{id}/cia/consolidate",
    summary="CIA consolidation (stored rows)",
    response_model=Envelope[ConsolidateResponse],
)
async def get_cia(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).consolidation(id))


@router.post(
    "/course-offerings/{id}/cia/consolidate",
    summary="Recompute CIA (best-of + scaling)",
    response_model=Envelope[ConsolidateResponse],
)
async def post_cia(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CIA_WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).consolidation(id, recompute=True), message="Consolidated")


@router.post(
    "/cia/{id}/approve", summary="HOD approve the offering's CIA", response_model=Envelope[ConsolidateResponse]
)
async def approve_cia(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VERIFY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).approve_cia(id), message="Approved")


@router.post("/cia/{id}/lock", summary="Lock the offering's CIA", response_model=Envelope[ConsolidateResponse])
async def lock_cia(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LOCK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).lock_cia(id), message="Locked")


@router.post(
    "/cia/{id}/submit-to-university",
    summary="Submit CIA to the affiliating university",
    response_model=Envelope[ConsolidateResponse],
)
async def submit_cia(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LOCK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(
        await AssessmentService(db, principal, request).submit_to_university(id), message="Submitted to the university"
    )


# ---- change requests ------------------------------------------------------------------------------------------------------------
@router.get(
    "/marks-change-requests",
    summary="Change requests",
    dependencies=CRF,
    response_model=Envelope[list[ChangeRequestOut]],
)
async def list_cr(
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(CR_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).list_changes(status))


@router.post(
    "/marks-change-requests",
    summary="Request a post-lock change (workflow marks.change)",
    dependencies=CRF,
    response_model=Envelope[ChangeRequestOut],
)
async def create_cr(
    body: ChangeRequestCreate,
    request: Request,
    principal: Principal = Depends(CR_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).create_change(body), message="Change requested")


@router.post(
    "/marks-change-requests/{id}/approve",
    summary="Approve (current workflow step)",
    dependencies=CRF,
    response_model=Envelope[ChangeRequestOut],
)
async def approve_cr(
    id: uuid.UUID,
    request: Request,
    body: ChangeRequestDecision | None = None,
    principal: Principal = Depends(CR_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await AssessmentService(db, principal, request).decide_change(id, True, body.comment if body else None),
        message="Approved",
    )


@router.post(
    "/marks-change-requests/{id}/reject", summary="Reject", dependencies=CRF, response_model=Envelope[ChangeRequestOut]
)
async def reject_cr(
    id: uuid.UUID,
    request: Request,
    body: ChangeRequestDecision | None = None,
    principal: Principal = Depends(CR_DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await AssessmentService(db, principal, request).decide_change(id, False, body.comment if body else None),
        message="Rejected",
    )


@router.post(
    "/marks-change-requests/{id}/apply",
    summary="Apply an approved change",
    dependencies=CRF,
    response_model=Envelope[ChangeRequestOut],
)
async def apply_cr(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CR_APPLY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AssessmentService(db, principal, request).apply_change(id), message="Applied")


# ---- OBE definitions ----------------------------------------------------------------------------------------------------------
@obe_router.get(
    "/programs/{id}/outcomes", summary="PEO / PO / PSO + PEO-PO matrix", response_model=Envelope[ProgramOutcomes]
)
async def program_outcomes(
    id: uuid.UUID, request: Request, principal: Principal = Depends(OBE_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ObeService(db, principal, request).program_outcomes(id))


@obe_router.put(
    "/programs/{id}/outcomes", summary="Replace programme outcomes", response_model=Envelope[ProgramOutcomes]
)
async def put_program_outcomes(
    id: uuid.UUID,
    body: OutcomesReplace,
    request: Request,
    principal: Principal = Depends(OBE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ObeService(db, principal, request).replace_outcomes(id, body), message="Outcomes saved")


@obe_router.post(
    "/programs/{id}/outcomes/import-template",
    summary="Import the NBA / generic PO template",
    response_model=Envelope[ProgramOutcomes],
)
async def import_template(
    id: uuid.UUID,
    request: Request,
    body: TemplateImport | None = None,
    principal: Principal = Depends(OBE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await ObeService(db, principal, request).import_template(id, body or TemplateImport()),
        message="Template imported",
    )


@obe_router.put(
    "/programs/{id}/peo-po-matrix", summary="Replace the PEO-PO matrix", response_model=Envelope[ProgramOutcomes]
)
async def peo_po(
    id: uuid.UUID,
    body: PeoPoMatrix,
    request: Request,
    principal: Principal = Depends(OBE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ObeService(db, principal, request).replace_peo_po(id, body), message="Matrix saved")


@obe_router.get("/courses/{id}/outcomes", summary="COs + CO-PO matrix", response_model=Envelope[CourseOutcomes])
async def course_outcomes(
    id: uuid.UUID, request: Request, principal: Principal = Depends(OBE_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ObeService(db, principal, request).course_outcomes(id))


@obe_router.put("/courses/{id}/outcomes", summary="Replace the course's COs", response_model=Envelope[CourseOutcomes])
async def put_course_outcomes(
    id: uuid.UUID,
    body: CoReplace,
    request: Request,
    principal: Principal = Depends(CO_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ObeService(db, principal, request).replace_cos(id, body), message="COs saved")


@obe_router.put(
    "/courses/{id}/co-po-matrix",
    summary="Replace the CO-PO / PSO matrix (every CO maps to a PO)",
    response_model=Envelope[CourseOutcomes],
)
async def put_matrix(
    id: uuid.UUID,
    body: CoPoMatrixReplace,
    request: Request,
    principal: Principal = Depends(CO_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ObeService(db, principal, request).replace_matrix(id, body), message="Matrix saved")


@obe_router.get("/courses/{id}/co-po-matrix/export", summary="CO-PO matrix CSV", response_class=Response)
async def export_matrix(
    id: uuid.UUID, request: Request, principal: Principal = Depends(OBE_VIEW), db: AsyncSession = Depends(get_db)
) -> Response:
    data = await ObeService(db, principal, request).matrix_csv(id)
    return Response(
        data, media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=co-po-{id}.csv"}
    )
