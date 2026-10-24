"""Degrees, convocation & digital credentials — Prompts/18 §18.8.

Each route carries its feature (``degrees.eligibility`` / ``convocation`` / ``certificates`` / ``provisional`` /
``digilocker_nad`` / ``abc_push``). Runs and batch operations answer ``202`` with a ``job_id``; ``award-batch``
with ``dry_run=true`` answers the preview inline. Visibility narrows in the services (own / wards / units /
institution; 404 otherwise). Public verification stays on ``GET /verify/{token}`` (``verify.py``). Fixed paths precede
parameterised ones.
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
from app.schemas.degrees import (
    AbcLedgerRow,
    AbcPushRequest,
    AbcPushSummary,
    ApproveRequest,
    AttendanceMark,
    AwardBatchPreview,
    AwardBatchRequest,
    ConvocationIn,
    ConvocationOut,
    ConvocationRegister,
    ConvocationRegistrationResponse,
    ConvocationStatusChange,
    ConvocationUpdate,
    CredentialPushRequest,
    CredentialStatusResponse,
    DegreeAwardedResponse,
    DegreeEligibilityRunSummary,
    EligibilityCheckResponse,
    EligibilityOverride,
    EligibilityRunRequest,
    GraduationStatsResponse,
    IssueBatchRequest,
    IssueRequest,
    ProvisionalRequest,
    ProvisionalResponse,
    PushSummary,
    ReissueRequest,
    RevokeRequest,
)
from app.services.degrees.award_service import AwardService
from app.services.degrees.convocation_service import ConvocationService
from app.services.degrees.credential_service import CredentialService
from app.services.degrees.eligibility_service import EligibilityService
from app.services.degrees.verification_service import GraduationStatsService
from app.utils.response import ok

router = APIRouter(tags=["degrees"])

D = "degrees"
READ = any_permission_required((D, "view_all"), (D, "manage"), (D, "award"), (D, "issue"), (D, "convocation_manage"))
SELF = any_permission_required((D, "view"), (D, "view_all"))
MANAGE = any_permission_required((D, "manage"), (D, "award"))
CONV = permission_required(D, "convocation_manage")
CONV_READ = any_permission_required((D, "convocation_manage"), (D, "view_all"), (D, "manage"), (D, "view"))
AWARD = any_permission_required((D, "award"), (D, "create"))
APPROVE = permission_required(D, "award")
ISSUE = permission_required(D, "issue")
ISSUE_OR_MANAGE = any_permission_required((D, "issue"), (D, "manage"))
STATS = permission_required(D, "view_all")

ELIG = [feature_required("degrees.eligibility")]
CONVF = [feature_required("degrees.convocation")]
CERT = [feature_required("degrees.certificates")]
PROV = [feature_required("degrees.provisional")]
CRED = [feature_required("degrees.digilocker_nad")]
ABC = [feature_required("degrees.abc_push")]


def _accepted(content: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(content, message=message))


# ---- eligibility -------------------------------------------------------------------------------------------------------------
@router.post(
    "/degree-eligibility/run",
    status_code=202,
    summary="Run the eligibility engine (job)",
    response_model=Envelope[DegreeEligibilityRunSummary],
    dependencies=ELIG,
)
async def eligibility_run(
    body: EligibilityRunRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await EligibilityService(db, principal, request).submit_run(body)
    return _accepted(out.model_dump(mode="json"), "Eligibility run queued")


@router.get(
    "/degree-eligibility/me",
    summary="My latest eligibility check(s)",
    response_model=Envelope[list[EligibilityCheckResponse]],
    dependencies=ELIG,
)
async def eligibility_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EligibilityService(db, principal, request).me())


@router.get(
    "/degree-eligibility",
    summary="Latest checks (or one run's) by batch / programme",
    response_model=Envelope[list[EligibilityCheckResponse]],
    dependencies=ELIG,
)
async def eligibility_list(
    request: Request,
    batch_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    eligible: bool | None = None,
    run_id: uuid.UUID | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EligibilityService(db, principal, request).list_checks(batch_id, program_id, eligible, run_id))


@router.get(
    "/degree-eligibility/{id}",
    summary="One check",
    response_model=Envelope[EligibilityCheckResponse],
    dependencies=ELIG,
)
async def eligibility_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EligibilityService(db, principal, request).get(id))


@router.post(
    "/degree-eligibility/{id}/override",
    summary="Override with a reason (registrar)",
    response_model=Envelope[EligibilityCheckResponse],
    dependencies=ELIG,
)
async def eligibility_override(
    id: uuid.UUID,
    body: EligibilityOverride,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EligibilityService(db, principal, request).override(id, body), message="Eligibility overridden")


# ---- convocations --------------------------------------------------------------------------------------------------------------
@router.get(
    "/convocations/me",
    summary="My convocation registrations",
    response_model=Envelope[list[ConvocationRegistrationResponse]],
    dependencies=CONVF,
)
async def convocations_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).mine_registrations())


@router.get("/convocations", summary="Convocations", response_model=Envelope[list[ConvocationOut]], dependencies=CONVF)
async def convocations_list(
    request: Request, principal: Principal = Depends(CONV_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).list_convocations())


@router.post(
    "/convocations", summary="Create a convocation", response_model=Envelope[ConvocationOut], dependencies=CONVF
)
async def convocation_create(
    body: ConvocationIn, request: Request, principal: Principal = Depends(CONV), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).create(body), message="Convocation created")


@router.get("/convocations/{id}", summary="Convocation", response_model=Envelope[ConvocationOut], dependencies=CONVF)
async def convocation_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CONV_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).get(id))


@router.put(
    "/convocations/{id}", summary="Edit a convocation", response_model=Envelope[ConvocationOut], dependencies=CONVF
)
async def convocation_update(
    id: uuid.UUID,
    body: ConvocationUpdate,
    request: Request,
    principal: Principal = Depends(CONV),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).update(id, body))


@router.post(
    "/convocations/{id}/status",
    summary="Move a convocation",
    response_model=Envelope[ConvocationOut],
    dependencies=CONVF,
)
async def convocation_status(
    id: uuid.UUID,
    body: ConvocationStatusChange,
    request: Request,
    principal: Principal = Depends(CONV),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).change_status(id, body))


@router.get(
    "/convocations/{id}/registrations",
    summary="Registrations",
    response_model=Envelope[list[ConvocationRegistrationResponse]],
    dependencies=CONVF,
)
async def convocation_registrations(
    id: uuid.UUID,
    request: Request,
    status: str | None = None,
    principal: Principal = Depends(CONV_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).registrations(id, status))


@router.get(
    "/convocations/{id}/reports/{kind}",
    summary="Gowns / seating / attendance report",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=CONVF,
)
async def convocation_report(
    id: uuid.UUID,
    kind: str,
    request: Request,
    principal: Principal = Depends(CONV_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).report(id, kind))


@router.post(
    "/convocations/{id}/register",
    summary="Register (Idempotency-Key)",
    response_model=Envelope[ConvocationRegistrationResponse],
    dependencies=CONVF,
)
async def convocation_register(
    id: uuid.UUID,
    body: ConvocationRegister,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await ConvocationService(db, principal, request).register(id, body)
    response = ok(out.model_dump(mode="json"), message="Registered")
    await store(request, response, db)
    return response


@router.post(
    "/convocations/{id}/attendance",
    summary="Mark attendance (QR scan)",
    response_model=Envelope[ConvocationRegistrationResponse],
    dependencies=CONVF,
)
async def convocation_attendance(
    id: uuid.UUID,
    body: AttendanceMark,
    request: Request,
    principal: Principal = Depends(CONV),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConvocationService(db, principal, request).mark_attendance(id, body))


# ---- awards ----------------------------------------------------------------------------------------------------------------------
@router.post(
    "/degrees/award-batch",
    status_code=202,
    summary="Recommend awards for eligible enrolments (dry_run previews)",
    response_model=Envelope[AwardBatchPreview],
    dependencies=CERT,
)
async def award_batch(
    body: AwardBatchRequest,
    request: Request,
    dry_run: bool = False,
    principal: Principal = Depends(AWARD),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await AwardService(db, principal, request).award_batch(body, dry_run=dry_run)
    return _accepted(out.model_dump(mode="json"), "Preview" if dry_run else f"{out.created} award(s) recommended")


@router.post(
    "/degrees/issue-batch",
    status_code=202,
    summary="Issue approved awards (job)",
    response_model=Envelope[dict[str, Any]],
    dependencies=CERT,
)
async def issue_batch(
    body: IssueBatchRequest, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    AwardService(db, principal, request).require_issue_rights()
    job = await enqueue(db, principal, "degrees.issue_batch", body.model_dump(mode="json"), queue="documents")
    return _accepted({"job_id": str(job.id)}, "Issue batch queued")


@router.post(
    "/degrees/print-batch",
    status_code=202,
    summary="Print file in serial order (job)",
    response_model=Envelope[dict[str, Any]],
    dependencies=CERT,
)
async def print_batch(
    body: IssueBatchRequest, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    job = await enqueue(db, principal, "degrees.print_batch", body.model_dump(mode="json"), queue="documents")
    return _accepted({"job_id": str(job.id)}, "Print batch queued")


@router.get("/degrees/register/export", summary="Statutory degree register (CSV)", dependencies=CERT)
async def register_export(
    request: Request,
    batch_id: uuid.UUID | None = None,
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> Response:
    data = await AwardService(db, principal, request).register_csv(batch_id)
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="degree-register.csv"'},
    )


@router.get("/degrees/me", summary="My awards", response_model=Envelope[list[DegreeAwardedResponse]], dependencies=CERT)
async def degrees_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).me())


@router.get(
    "/degrees/stats",
    summary="GPH / GPHD / median CGPA",
    response_model=Envelope[GraduationStatsResponse],
    dependencies=CERT,
)
async def degree_stats(
    request: Request,
    program_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GraduationStatsService(db, principal, request).stats(program_id, batch_id))


@router.post(
    "/degrees/provisional",
    summary="Issue a provisional certificate",
    response_model=Envelope[ProvisionalResponse],
    dependencies=PROV,
)
async def provisional(
    body: ProvisionalRequest,
    request: Request,
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await AwardService(db, principal, request).provisional(body.enrollment_id),
        message="Provisional certificate issued",
    )


@router.get(
    "/degrees/provisional/me",
    summary="My provisional certificates",
    response_model=Envelope[list[ProvisionalResponse]],
    dependencies=PROV,
)
async def provisional_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).provisional_me())


@router.get("/degrees", summary="Awards", response_model=Envelope[list[DegreeAwardedResponse]], dependencies=CERT)
async def degrees_list(
    request: Request,
    batch_id: uuid.UUID | None = None,
    status: str | None = None,
    program_id: uuid.UUID | None = None,
    convocation_id: uuid.UUID | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).list_awards(batch_id, status, program_id, convocation_id))


@router.get("/degrees/{id}", summary="Award", response_model=Envelope[DegreeAwardedResponse], dependencies=CERT)
async def degree_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).get(id))


@router.get("/degrees/{id}/certificate.pdf", summary="Certificate PDF", dependencies=CERT)
async def degree_pdf(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> Response:
    data = await AwardService(db, principal, request).certificate(id)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="degree-{id.hex[:8]}.pdf"'},
    )


@router.post(
    "/degrees/{id}/approve",
    summary="Council approval",
    response_model=Envelope[DegreeAwardedResponse],
    dependencies=CERT,
)
async def degree_approve(
    id: uuid.UUID,
    body: ApproveRequest,
    request: Request,
    principal: Principal = Depends(APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).approve(id, body))


@router.post(
    "/degrees/{id}/issue",
    summary="Issue (serial, PDF, QR, eSign)",
    response_model=Envelope[DegreeAwardedResponse],
    dependencies=CERT,
)
async def degree_issue(
    id: uuid.UUID,
    body: IssueRequest,
    request: Request,
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).issue(id, body), message="Issued")


@router.post(
    "/degrees/{id}/revoke",
    summary="Revoke with a reason",
    response_model=Envelope[DegreeAwardedResponse],
    dependencies=CERT,
)
async def degree_revoke(
    id: uuid.UUID,
    body: RevokeRequest,
    request: Request,
    principal: Principal = Depends(ISSUE_OR_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).revoke(id, body), message="Revoked")


@router.post(
    "/degrees/{id}/reissue",
    summary="Reissue with corrections",
    response_model=Envelope[DegreeAwardedResponse],
    dependencies=CERT,
)
async def degree_reissue(
    id: uuid.UUID,
    body: ReissueRequest,
    request: Request,
    principal: Principal = Depends(ISSUE_OR_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AwardService(db, principal, request).reissue(id, body), message="Reissued")


# ---- digital credentials / ABC ---------------------------------------------------------------------------------------------------
@router.post(
    "/credentials/push",
    status_code=202,
    summary="Push credentials to DigiLocker / NAD (job)",
    response_model=Envelope[PushSummary],
    dependencies=CRED,
)
async def credentials_push(
    body: CredentialPushRequest,
    request: Request,
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.core.jobs import enqueue

    job = await enqueue(db, principal, "credentials.push", body.model_dump(mode="json"))
    return _accepted(PushSummary(job_id=job.id).model_dump(mode="json"), "Push queued")


@router.get(
    "/credentials/me",
    summary="My credential push status",
    response_model=Envelope[list[CredentialStatusResponse]],
    dependencies=CRED,
)
async def credentials_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CredentialService(db, principal, request).me())


@router.get(
    "/credentials", summary="Credentials", response_model=Envelope[list[CredentialStatusResponse]], dependencies=CRED
)
async def credentials_list(
    request: Request,
    entity_type: str | None = None,
    status: str | None = None,
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CredentialService(db, principal, request).list_credentials(entity_type, status))


@router.get(
    "/credentials/{id}", summary="Credential", response_model=Envelope[CredentialStatusResponse], dependencies=CRED
)
async def credential_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CredentialService(db, principal, request).get(id))


@router.post(
    "/credentials/{id}/retry",
    summary="Retry a push",
    response_model=Envelope[CredentialStatusResponse],
    dependencies=CRED,
)
async def credential_retry(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CredentialService(db, principal, request).retry(id))


@router.post(
    "/credentials/{id}/revoke",
    summary="Revoke a credential",
    response_model=Envelope[CredentialStatusResponse],
    dependencies=CRED,
)
async def credential_revoke(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CredentialService(db, principal, request).revoke(id))


@router.post(
    "/abc/push",
    status_code=202,
    summary="Push pending ABC ledger rows (job)",
    response_model=Envelope[AbcPushSummary],
    dependencies=ABC,
)
async def abc_push(
    body: AbcPushRequest, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    job = await enqueue(db, principal, "abc.push", body.model_dump(mode="json"))
    return _accepted(AbcPushSummary(job_id=job.id).model_dump(mode="json"), "ABC push queued")


@router.get(
    "/abc/ledger/me", summary="My ABC ledger rows", response_model=Envelope[list[AbcLedgerRow]], dependencies=ABC
)
async def abc_me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CredentialService(db, principal, request).ledger(None, None, mine=True))


@router.get("/abc/ledger", summary="ABC ledger", response_model=Envelope[list[AbcLedgerRow]], dependencies=ABC)
async def abc_ledger(
    request: Request,
    student_id: uuid.UUID | None = None,
    status: str | None = None,
    principal: Principal = Depends(ISSUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CredentialService(db, principal, request).ledger(student_id, status))


@router.post(
    "/abc/ledger/{id}/retry", summary="Retry one ledger row", response_model=Envelope[AbcPushSummary], dependencies=ABC
)
async def abc_retry(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ISSUE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CredentialService(db, principal, request).ledger_retry(id))
