"""Attendance & eligibility — Prompts/11 §11.8 (router included with ``feature_required("attendance.core")``;
sub-features per route: {attendance.qr}, {attendance.geo_app}, {attendance.offline_mobile}, {attendance.on_duty},
{attendance.condonation}, {attendance.eligibility_detention}, {attendance.guardian_alerts}).

Eligibility computation, term-wide recomputation and the register / detention exports answer ``202`` + ``job_id``;
``dry_run`` previews answer inline. ``public_router`` holds the device-token punch ingest (``PUBLIC_ROUTES``; checks
{attendance.biometric} / {attendance.rfid} itself). Fixed paths (``/attendance/summary/me`` …) precede parameterised
ones.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.attendance import (
    AlertConfig,
    BulkMarkRequest,
    CheckinResult,
    CondonationCreate,
    CondonationDecision,
    CondonationResponse,
    DecideRequest,
    DetentionListRow,
    EditFinalizedRequest,
    EligibilityComputeRequest,
    EligibilityRow,
    EligibilityRunSummary,
    FinalizeRequest,
    GeoCheckinRequest,
    MarkResult,
    MissingSessionRow,
    MySummaryResponse,
    OdCreate,
    OdDecision,
    OdResponse,
    OfflineBatch,
    OfflineBatchResult,
    QrCheckinRequest,
    QrIssueResponse,
    RegisterGrid,
    SessionForAttendance,
    StudentAttendanceSummary,
    StudentHistoryRow,
    StudentPunchIngest,
    StudentPunchResult,
    SummaryResponse,
    UnmatchedPunch,
)
from app.schemas.common import Envelope
from app.services.attendance.condonation_service import CondonationService
from app.services.attendance.eligibility_service import EligibilityService
from app.services.attendance.marking_service import MarkingService
from app.services.attendance.od_service import OdService
from app.services.attendance.summary_service import SummaryService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["attendance"])
public_router = APIRouter(tags=["public"])

A = "attendance"
MARK = permission_required(A, "mark")
MARK_VIEW = any_permission_required((A, "mark"), (A, "view"), (A, "view_all"))
EDIT_FIN = permission_required(A, "edit_finalized")
SELF = permission_required(A, "self")
VIEW_ANY = any_permission_required((A, "view"), (A, "view_all"), (A, "self"), (A, "mark"))
STAFF_VIEW = any_permission_required((A, "view"), (A, "view_all"), (A, "mark"))
VIEW_ALL = any_permission_required((A, "view_all"), (A, "edit_finalized"))
DEVICE = any_permission_required((A, "device_manage"), (A, "view_all"))
OD_VIEW = any_permission_required((A, "self"), (A, "mark"), (A, "view"), (A, "view_all"), (A, "condone"))
OD_CREATE = any_permission_required((A, "self"), (A, "mark"))
OD_RECOMMEND = any_permission_required((A, "mark"), (A, "condone"), (A, "view_all"))
OD_APPROVE = any_permission_required((A, "condone"), (A, "edit_finalized"))
COND_VIEW = any_permission_required((A, "condone"), (A, "self"), (A, "view"), (A, "view_all"), (A, "mark"))
COND_CREATE = any_permission_required((A, "self"), (A, "mark"), (A, "condone"))
CONDONE = permission_required(A, "condone")
ELIG = permission_required("exams", "eligibility")
ELIG_READ = any_permission_required(("exams", "eligibility"), (A, "view_all"), ("fees", "view_all"))
DETENTION = any_permission_required(("exams", "eligibility"), (A, "view_all"))
SETTINGS = permission_required("settings", "manage")
QR = [feature_required("attendance.qr")]
GEO = [feature_required("attendance.geo_app")]
OFFLINE = [feature_required("attendance.offline_mobile")]
OD = [feature_required("attendance.on_duty")]
COND = [feature_required("attendance.condonation")]
ELIGF = [feature_required("attendance.eligibility_detention")]
ALERTS = [feature_required("attendance.guardian_alerts")]


def _queued(data: Any, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(data, message=message))


# ---- marking ------------------------------------------------------------------------------------------------------------
@router.get(
    "/class-sessions/{id}/attendance",
    summary="Roster with current marks (own sessions; HOD / registrar their units)",
    response_model=Envelope[SessionForAttendance],
)
async def get_session_attendance(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MARK_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MarkingService(db, principal, request).session_for_marking(id))


@router.post(
    "/class-sessions/{id}/attendance",
    summary="Bulk mark (Idempotency-Key)",
    response_model=Envelope[MarkResult],
)
async def bulk_mark(
    id: uuid.UUID,
    body: BulkMarkRequest,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(MARK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await MarkingService(db, principal, request).bulk_mark(id, body)
    response = ok(out.model_dump(mode="json"), message="Attendance saved")
    await store(request, response, db)
    return response


@router.post(
    "/class-sessions/{id}/finalize",
    summary="Finalize (lock) a session's attendance",
    response_model=Envelope[SessionForAttendance],
)
async def finalize(
    id: uuid.UUID,
    request: Request,
    body: FinalizeRequest | None = None,
    principal: Principal = Depends(MARK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MarkingService(db, principal, request).finalize(id, body), message="Finalized")


@router.post(
    "/class-sessions/{id}/attendance/edit-finalized",
    summary="Edit finalized attendance with a reason (audited per row)",
    response_model=Envelope[MarkResult],
)
async def edit_finalized(
    id: uuid.UUID,
    body: EditFinalizedRequest,
    request: Request,
    principal: Principal = Depends(EDIT_FIN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MarkingService(db, principal, request).edit_finalized(id, body), message="Attendance corrected")


@router.post(
    "/class-sessions/{id}/qr",
    summary="Issue a rotating session QR",
    dependencies=QR,
    response_model=Envelope[QrIssueResponse],
)
async def issue_qr(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MARK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MarkingService(db, principal, request).issue_qr(id))


@router.post(
    "/attendance/qr-checkin", summary="Student QR check-in", dependencies=QR, response_model=Envelope[CheckinResult]
)
async def qr_checkin(
    body: QrCheckinRequest, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MarkingService(db, principal, request).qr_checkin(body), message="Checked in")


@router.post(
    "/attendance/geo-checkin",
    summary="Geo-fenced app check-in",
    dependencies=GEO,
    response_model=Envelope[CheckinResult],
)
async def geo_checkin(
    body: GeoCheckinRequest, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MarkingService(db, principal, request).geo_checkin(body), message="Checked in — pending review")


@router.post(
    "/attendance/offline-batch",
    summary="Offline marking batch (per-item results; batch key replay)",
    dependencies=OFFLINE,
    response_model=Envelope[OfflineBatchResult],
)
async def offline_batch(
    body: OfflineBatch, request: Request, principal: Principal = Depends(MARK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MarkingService(db, principal, request).offline_batch(body))


@router.get(
    "/attendance/punches/unmatched",
    summary="Unmatched student device punches (30 days)",
    response_model=Envelope[list[UnmatchedPunch]],
)
async def unmatched_punches(
    request: Request,
    days: int = Query(30, ge=1, le=90),
    principal: Principal = Depends(DEVICE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MarkingService(db, principal, request).unmatched_punches(days))


@public_router.post(
    "/attendance/devices/{id}/punches",
    summary="Student device punch ingest (device token)",
    response_model=Envelope[StudentPunchResult],
)
async def ingest_student_punches(
    id: uuid.UUID, body: StudentPunchIngest, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.db.session import bind_tenant, set_tenant
    from app.repositories.staff_attendance_repository import device_institution

    institution_id = await device_institution(id)
    if institution_id is None:
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid device token")
    bind_tenant(db, institution_id)
    await set_tenant(db, institution_id)
    if not (
        await is_enabled(institution_id, "attendance.biometric") or await is_enabled(institution_id, "attendance.rfid")
    ):
        raise APIError(
            403,
            ErrorCode.FEATURE_DISABLED,
            "Feature 'attendance.biometric' is not enabled",
            {"feature": "attendance.biometric"},
        )
    return ok(await MarkingService(db, None, institution_id=institution_id).ingest_punches(id, body))


@router.get(
    "/attendance/missing-sessions",
    summary="Past sessions without attendance (follow-up)",
    response_model=Envelope[list[MissingSessionRow]],
)
async def missing_sessions(
    request: Request,
    scope: str | None = None,
    days: int = Query(14, ge=1, le=120),
    principal: Principal = Depends(STAFF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = MarkingService(db, principal, request)
    rows = await svc.missing_sessions(scope, days)
    outs = await svc.session_outs(rows)
    return ok(
        [
            MissingSessionRow(
                session_id=o.id,
                session_date=o.session_date,
                start_time=o.start_time,
                course_code=o.course_code,
                staff_name=o.staff_name,
            )
            for o in outs
        ]
    )


# ---- summaries ------------------------------------------------------------------------------------------------------------
@router.get(
    "/attendance/summary/me",
    summary="My (ward's) attendance — overall + per course",
    response_model=Envelope[MySummaryResponse],
)
async def my_summary(
    request: Request,
    term_id: uuid.UUID | None = None,
    ward_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW_ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SummaryService(db, principal, request).my_summary(term_id, ward_id))


@router.get(
    "/attendance/history/me",
    summary="My (ward's) session-wise attendance",
    response_model=Envelope[list[StudentHistoryRow]],
)
async def my_history(
    request: Request,
    offering_id: uuid.UUID | None = None,
    ward_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW_ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SummaryService(db, principal, request).history(ward_id, offering_id))


@router.get(
    "/attendance/summary/student/{id}",
    summary="A student's attendance (staff)",
    response_model=Envelope[MySummaryResponse],
)
async def student_summary(
    id: uuid.UUID,
    request: Request,
    term_id: uuid.UUID | None = None,
    principal: Principal = Depends(STAFF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SummaryService(db, principal, request).for_student(id, term_id))


@router.get(
    "/attendance/summary/offerings",
    summary="Per-offering attendance overview",
    response_model=Envelope[list[SummaryResponse]],
)
async def offerings_overview(
    request: Request,
    term_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(STAFF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = SummaryService(db, principal, request)
    from app.repositories.timetable_scope import session_visibility

    return ok(await svc.offerings_overview(term_id, scope), visibility=session_visibility(principal))


@router.get(
    "/attendance/summary",
    summary="Per-student summaries (scope own | department | all)",
    response_model=Envelope[list[StudentAttendanceSummary]],
)
async def list_summaries(
    request: Request,
    offering_id: uuid.UUID | None = None,
    scope: str | None = None,
    eligibility: str | None = None,
    below: float | None = Query(None, ge=0, le=100),
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(VIEW_ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await SummaryService(db, principal, request).list_page(
        params, scope, offering_id, eligibility, below
    )
    return ok(rows, pagination=page, visibility=vis)


@router.post(
    "/attendance/recompute",
    status_code=202,
    summary="Recompute a term's summaries (job)",
    response_model=Envelope[dict[str, Any]],
)
async def recompute(
    request: Request, term_id: uuid.UUID, principal: Principal = Depends(VIEW_ALL), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    job = await enqueue(db, principal, "attendance.recompute_summaries", {"term_id": str(term_id)})
    return _queued({"job_id": str(job.id)}, "Recompute queued")


@router.get(
    "/attendance/register",
    summary="Session × student register (export=true → job)",
    response_model=Envelope[RegisterGrid],
)
async def register(
    request: Request,
    offering_id: uuid.UUID,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    export: bool = False,
    principal: Principal = Depends(STAFF_VIEW),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = SummaryService(db, principal, request)
    grid = await svc.register(offering_id, date_from, date_to)
    if export:
        from app.core.jobs import enqueue

        job = await enqueue(
            db,
            principal,
            "attendance.export",
            {
                "offering_id": str(offering_id),
                "from": date_from.isoformat() if date_from else None,
                "to": date_to.isoformat() if date_to else None,
            },
        )
        return _queued({"job_id": str(job.id)}, "Register export queued")
    return ok(grid)


# ---- alert config ---------------------------------------------------------------------------------------------------------
_ALERT_KEYS = {
    "consecutive_absences": "absent_alert_consecutive",
    "checkpoints": "checkpoints",
    "notify_guardians": "notify_guardians",
    "notify_mentor": "notify_mentor",
}


@router.get(
    "/attendance/alert-config",
    summary="Guardian alert configuration",
    dependencies=ALERTS,
    response_model=Envelope[AlertConfig],
)
async def get_alert_config(
    request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = SummaryService(db, principal, request)
    values = {k: await svc.att_setting(v) for k, v in _ALERT_KEYS.items()}
    return ok(AlertConfig.model_validate({k: v for k, v in values.items() if v is not None}))


@router.put(
    "/attendance/alert-config",
    summary="Save guardian alert configuration",
    dependencies=ALERTS,
    response_model=Envelope[AlertConfig],
)
async def put_alert_config(
    body: AlertConfig, request: Request, principal: Principal = Depends(SETTINGS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.schemas.settings import SettingItem
    from app.services.settings_service import SettingsService

    data = body.model_dump()
    await SettingsService(db, principal).bulk_update(
        [SettingItem(category=A, key=v, value=data[k]) for k, v in _ALERT_KEYS.items()], request
    )
    return ok(body, message="Alert settings saved")


# ---- on duty ----------------------------------------------------------------------------------------------------------------
@router.get("/on-duty", summary="On-duty requests (scope)", dependencies=OD, response_model=Envelope[list[OdResponse]])
async def list_od(
    request: Request,
    scope: str | None = None,
    status: str | None = None,
    student_program_enrollment_id: uuid.UUID | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(OD_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await OdService(db, principal, request).list_page(
        params, scope, status, student_program_enrollment_id
    )
    return ok(rows, pagination=page, visibility=vis)


@router.post(
    "/on-duty", status_code=201, summary="Apply for on duty", dependencies=OD, response_model=Envelope[OdResponse]
)
async def create_od(
    body: OdCreate, request: Request, principal: Principal = Depends(OD_CREATE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OdService(db, principal, request).create(body), message="On-duty request submitted")


@router.get("/on-duty/{id}", summary="On-duty request", dependencies=OD, response_model=Envelope[OdResponse])
async def get_od(
    id: uuid.UUID, request: Request, principal: Principal = Depends(OD_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OdService(db, principal, request).get(id))


@router.post(
    "/on-duty/{id}/documents", summary="Attach a document", dependencies=OD, response_model=Envelope[OdResponse]
)
async def od_document(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(OD_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OdService(db, principal, request).add_document(id, file), message="Document attached")


@router.post("/on-duty/{id}/recommend", summary="Recommend", dependencies=OD, response_model=Envelope[OdResponse])
async def od_recommend(
    id: uuid.UUID,
    request: Request,
    body: OdDecision | None = None,
    principal: Principal = Depends(OD_RECOMMEND),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OdService(db, principal, request).recommend(id, body or OdDecision()), message="Recommended")


@router.post(
    "/on-duty/{id}/approve",
    summary="Approve (marks sessions on duty)",
    dependencies=OD,
    response_model=Envelope[OdResponse],
)
async def od_approve(
    id: uuid.UUID,
    request: Request,
    body: OdDecision | None = None,
    principal: Principal = Depends(OD_APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OdService(db, principal, request).approve(id, body or OdDecision()), message="Approved")


@router.post("/on-duty/{id}/reject", summary="Reject", dependencies=OD, response_model=Envelope[OdResponse])
async def od_reject(
    id: uuid.UUID,
    request: Request,
    body: OdDecision | None = None,
    principal: Principal = Depends(OD_APPROVE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OdService(db, principal, request).reject(id, body or OdDecision()), message="Rejected")


@router.post(
    "/on-duty/{id}/withdraw", summary="Withdraw (student)", dependencies=OD, response_model=Envelope[OdResponse]
)
async def od_withdraw(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OdService(db, principal, request).withdraw(id), message="Withdrawn")


# ---- condonation ------------------------------------------------------------------------------------------------------------
@router.get(
    "/condonations/me",
    summary="My condonation requests",
    dependencies=COND,
    response_model=Envelope[list[CondonationResponse]],
)
async def my_condonations(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CondonationService(db, principal, request).mine())


@router.get(
    "/condonations",
    summary="Condonation queue (scope)",
    dependencies=COND,
    response_model=Envelope[list[CondonationResponse]],
)
async def list_condonations(
    request: Request,
    scope: str | None = None,
    status: str | None = None,
    term_id: uuid.UUID | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(COND_VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await CondonationService(db, principal, request).list_page(params, scope, status, term_id)
    return ok(rows, pagination=page, visibility=vis)


@router.post(
    "/condonations",
    status_code=201,
    summary="Request condonation",
    dependencies=COND,
    response_model=Envelope[CondonationResponse],
)
async def create_condonation(
    body: CondonationCreate,
    request: Request,
    principal: Principal = Depends(COND_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CondonationService(db, principal, request).create(body), message="Condonation requested")


@router.get(
    "/condonations/{id}", summary="Condonation request", dependencies=COND, response_model=Envelope[CondonationResponse]
)
async def get_condonation(
    id: uuid.UUID, request: Request, principal: Principal = Depends(COND_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CondonationService(db, principal, request).get(id))


@router.post(
    "/condonations/{id}/documents",
    summary="Attach a document",
    dependencies=COND,
    response_model=Envelope[CondonationResponse],
)
async def condonation_document(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(COND_CREATE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CondonationService(db, principal, request).add_document(id, file), message="Document attached")


@router.post(
    "/condonations/{id}/recommend",
    summary="HOD recommendation",
    dependencies=COND,
    response_model=Envelope[CondonationResponse],
)
async def condonation_recommend(
    id: uuid.UUID,
    request: Request,
    body: CondonationDecision | None = None,
    principal: Principal = Depends(CONDONE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await CondonationService(db, principal, request).recommend(id, body or CondonationDecision()),
        message="Recommended",
    )


@router.post(
    "/condonations/{id}/approve",
    summary="Approve (registrar / principal)",
    dependencies=COND,
    response_model=Envelope[CondonationResponse],
)
async def condonation_approve(
    id: uuid.UUID,
    request: Request,
    body: CondonationDecision | None = None,
    principal: Principal = Depends(CONDONE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await CondonationService(db, principal, request).approve(id, body or CondonationDecision()), message="Approved"
    )


@router.post(
    "/condonations/{id}/reject", summary="Reject", dependencies=COND, response_model=Envelope[CondonationResponse]
)
async def condonation_reject(
    id: uuid.UUID,
    request: Request,
    body: CondonationDecision | None = None,
    principal: Principal = Depends(CONDONE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await CondonationService(db, principal, request).reject(id, body or CondonationDecision()), message="Rejected"
    )


# ---- eligibility ------------------------------------------------------------------------------------------------------------
@router.post(
    "/terms/{id}/eligibility/compute",
    status_code=202,
    summary="Compute eligibility (job; dry_run inline)",
    dependencies=ELIGF,
    response_model=Envelope[EligibilityRunSummary],
)
async def compute_eligibility(
    id: uuid.UUID,
    request: Request,
    body: EligibilityComputeRequest | None = None,
    principal: Principal = Depends(ELIG),
    db: AsyncSession = Depends(get_db),
) -> Any:
    out = await EligibilityService(db, principal, request).compute(id, body or EligibilityComputeRequest())
    if out.dry_run:
        return JSONResponse(status_code=200, content=ok(out.model_dump(mode="json"), message="Dry run"))
    return _queued(out.model_dump(mode="json"), "Eligibility computation queued")


@router.get(
    "/terms/{id}/eligibility/versions",
    summary="Computed versions of a term",
    dependencies=ELIGF,
    response_model=Envelope[list[int]],
)
async def eligibility_versions(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ELIG_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EligibilityService(db, principal, request).versions(id))


@router.get(
    "/terms/{id}/eligibility",
    summary="Eligibility rows (latest or a version)",
    dependencies=ELIGF,
    response_model=Envelope[list[EligibilityRow]],
)
async def list_eligibility(
    id: uuid.UUID,
    request: Request,
    offering_id: uuid.UUID | None = None,
    decision: str | None = None,
    version: int | None = Query(None, ge=1),
    scope: str | None = None,
    params: PageParams = Depends(page_params),
    principal: Principal = Depends(ELIG_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, page, vis = await EligibilityService(db, principal, request).list_page(
        id, params, scope, offering_id, decision, version
    )
    return ok(rows, pagination=page, visibility=vis)


@router.post(
    "/eligibility/{id}/decide",
    summary="Manual decision with reason (audited)",
    dependencies=ELIGF,
    response_model=Envelope[EligibilityRow],
)
async def decide(
    id: uuid.UUID,
    body: DecideRequest,
    request: Request,
    principal: Principal = Depends(ELIG),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EligibilityService(db, principal, request).decide(id, body), message="Decision recorded")


@router.get(
    "/terms/{id}/detention-list",
    summary="Detention list (export=true → XLSX job)",
    dependencies=ELIGF,
    response_model=Envelope[list[DetentionListRow]],
)
async def detention_list(
    id: uuid.UUID,
    request: Request,
    college_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    export: bool = False,
    principal: Principal = Depends(DETENTION),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if export:
        from app.core.jobs import enqueue

        job = await enqueue(
            db,
            principal,
            "attendance.detention_export",
            {
                "term_id": str(id),
                "college_id": str(college_id) if college_id else None,
                "program_id": str(program_id) if program_id else None,
            },
        )
        return _queued({"job_id": str(job.id)}, "Detention list export queued")
    return ok(await EligibilityService(db, principal, request).detention_list(id, college_id, program_id))


@router.post(
    "/terms/{id}/detention-list/notify",
    summary="Notify detained students (once per version)",
    dependencies=ELIGF,
    response_model=Envelope[dict[str, int]],
)
async def notify_detained(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ELIG), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    n = await EligibilityService(db, principal, request).notify_detained(id)
    return ok({"notified": n}, message=f"{n} student(s) notified" if n else "Already notified for this version")


@router.get(
    "/eligibility/me",
    summary="My (ward's) eligibility",
    dependencies=ELIGF,
    response_model=Envelope[list[EligibilityRow]],
)
async def my_eligibility(
    request: Request,
    term_id: uuid.UUID | None = None,
    ward_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW_ANY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EligibilityService(db, principal, request).my_rows(term_id, ward_id))
