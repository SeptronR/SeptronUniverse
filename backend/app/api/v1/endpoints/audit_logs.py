"""Audit logs, chain integrity, exam audit, security console and retention — Prompts/37 §37.8.

* ``/audit-logs*`` {core.audit_logs}: explorer (ScopeTabs Mine | Department | College | All — ``audit_logs:view``
  self, ``view_all`` by scope), ``/me``, detail with masked diff, record timeline, who viewed, summary counts,
  export (``report.run`` of the registered ``audit.explorer`` report), ``verify-chain`` / ``chain-digests``
  (``audit_logs:verify_chain``);
* ``/exams/{session_id}/audit*`` {exams.sessions} (``exams:audit``; the decode section for COE / institution admin /
  auditor only);
* ``/security/*`` {core.audit_logs} (``audit_logs:security``) — events and anomalies; sessions and login history also
  need {security.session_management} (checked in the service so the events stay readable when it is off);
* ``/retention/*`` {core.settings} (``settings:manage``; legal holds also ``legal:manage``; restore super admin).
"""

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.audit import (
    AdminSessionOut,
    AnomalyAck,
    AnomalyAlertOut,
    ArchiveManifestOut,
    AuditDetailOut,
    AuditExportRequest,
    AuditListOut,
    AuditSummaryOut,
    ChainDigestOut,
    ChainVerifyOut,
    ChainVerifyRequest,
    ExamAuditExportRequest,
    ExamAuditOut,
    ExamAuditSummaryOut,
    JobQueuedOut,
    LegalHoldIn,
    LegalHoldOut,
    LoginHistoryAdminOut,
    RecordTimelineOut,
    RestoreRequest,
    RetentionPolicyIn,
    RetentionPolicyOut,
    RetentionPreviewOut,
    RetentionRunRequest,
    SecurityEventOut,
    SessionRevokeOut,
    SessionRevokeRequest,
    WhoViewedOut,
)
from app.schemas.common import Envelope
from app.services.audit.audit_service import AuditService
from app.services.audit.chain_service import ChainService
from app.services.audit.exam_audit_service import ExamAuditService
from app.services.audit.retention_service import RetentionService
from app.services.audit.security_service import SecurityService
from app.utils.response import VisibilityMeta, ok

router = APIRouter(tags=["audit"])

READ = any_permission_required(("audit_logs", "view"), ("audit_logs", "view_all"), ("audit_logs", "manage"))
VIEW_ALL = any_permission_required(("audit_logs", "view_all"), ("audit_logs", "manage"))
EXPORT = any_permission_required(("audit_logs", "export"), ("audit_logs", "manage"))
VERIFY = any_permission_required(("audit_logs", "verify_chain"), ("audit_logs", "manage"))
EXAM_AUDIT = any_permission_required(("exams", "audit"), ("exams", "manage"))
SECURITY = any_permission_required(("audit_logs", "security"), ("audit_logs", "manage"))
SESSIONS = any_permission_required(
    ("audit_logs", "security"), ("audit_logs", "manage"), ("users", "view_all"), ("users", "manage")
)
SETTINGS_MANAGE = any_permission_required(
    ("settings", "manage"),
)
SETTINGS_READ = any_permission_required(("settings", "manage"), ("settings", "view"))
HOLDS = any_permission_required(("settings", "manage"), ("legal", "manage"))

AUDIT = [feature_required("core.audit_logs")]
EXAMS = [feature_required("exams.sessions")]
SETTINGS = [feature_required("core.settings")]


def _queued(out: JobQueuedOut, message: str = "Queued") -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(out.model_dump(mode="json"), message=message))


def _query(**kw: Any) -> dict[str, Any]:
    return {k: v for k, v in kw.items() if v not in (None, "", False)}


# ---- explorer ------------------------------------------------------------------------------------------------------
@router.get(
    "/audit-logs",
    summary="Audit explorer (ScopeTabs Mine | Department | College | All)",
    response_model=Envelope[AuditListOut],
    dependencies=AUDIT,
)
async def list_audit(
    request: Request,
    module: str | None = Query(None, max_length=60),
    action: str | None = Query(None, max_length=40),
    user_id: uuid.UUID | None = None,
    record_type: str | None = Query(None, max_length=60),
    record_id: uuid.UUID | None = None,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    q: str | None = Query(None, max_length=100),
    impersonator_only: bool = False,
    scope: str | None = Query(None, pattern="^(mine|own|self|department|college|all)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = Query("-occurred_at", pattern="^-?occurred_at$"),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = _query(
        module=module,
        action=action,
        user_id=user_id,
        record_type=record_type,
        record_id=record_id,
        q=q,
        impersonator_only=impersonator_only,
    )
    query["from"], query["to"] = date_from, date_to
    out, vis = await AuditService(db, principal, request).explore(query, scope, page, page_size, sort)
    return ok(out, visibility=VisibilityMeta(**vis))


@router.get("/audit-logs/me", summary="My own audit rows", response_model=Envelope[AuditListOut], dependencies=AUDIT)
async def my_audit(
    request: Request,
    module: str | None = Query(None, max_length=60),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    q = _query(module=module)
    q["from"], q["to"] = date_from, date_to
    return ok(await AuditService(db, principal, request).me(q, page, page_size))


@router.get(
    "/audit-logs/timeline",
    summary="Record timeline (audit rows + domain events + workflow steps)",
    response_model=Envelope[list[RecordTimelineOut]],
    dependencies=AUDIT,
)
async def timeline(
    request: Request,
    record_type: str = Query(max_length=60),
    record_id: uuid.UUID = Query(),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).record_timeline(record_type, record_id))


@router.get(
    "/audit-logs/who-viewed",
    summary="Who viewed a confidential record",
    response_model=Envelope[list[WhoViewedOut]],
    dependencies=AUDIT,
)
async def who_viewed(
    request: Request,
    record_type: str = Query(max_length=60),
    record_id: uuid.UUID = Query(),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).who_viewed(record_type, record_id, date_from, date_to))


@router.get(
    "/audit-logs/summary",
    summary="Audit counts per module / action (aggregates)",
    response_model=Envelope[AuditSummaryOut],
    dependencies=AUDIT,
)
async def summary(
    request: Request,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).summary_counts(date_from, date_to))


@router.post(
    "/audit-logs/export",
    status_code=202,
    summary="Export audit rows (report.run job, masked unless view_pii)",
    response_model=Envelope[JobQueuedOut],
    dependencies=AUDIT,
)
async def export_audit(
    body: AuditExportRequest,
    request: Request,
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return _queued(await AuditService(db, principal, request).export(body.query, body.format), "Export queued")


@router.post(
    "/audit-logs/verify-chain",
    summary="Verify the audit hash chain for a range (+ stored digests)",
    response_model=Envelope[ChainVerifyOut],
    dependencies=AUDIT,
)
async def verify_chain(
    body: ChainVerifyRequest,
    request: Request,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await ChainService(db, principal, request).verify(body.from_, body.to, body.compare_digests)
    return ok(out, message="Chain intact" if out.ok else "Chain broken")


@router.get(
    "/audit-logs/chain-digests",
    summary="Signed daily chain digests",
    response_model=Envelope[list[ChainDigestOut]],
    dependencies=AUDIT,
)
async def chain_digests(
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ChainService(db, principal, request).digests(date_from, date_to))


@router.get(
    "/audit-logs/{id}",
    summary="Audit row with masked diff",
    response_model=Envelope[AuditDetailOut],
    dependencies=AUDIT,
)
async def audit_detail(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).detail(id))


# ---- exam audit ----------------------------------------------------------------------------------------------------
@router.get(
    "/exams/{session_id}/audit",
    summary="Exam audit section (marks | qp_print | custody | valuation | moderation | decode | runs | publication | post_result)",
    response_model=Envelope[ExamAuditOut],
    dependencies=EXAMS,
)
async def exam_audit(
    session_id: uuid.UUID,
    request: Request,
    section: str = Query("marks", max_length=20),
    paper_id: uuid.UUID | None = None,
    principal: Principal = Depends(EXAM_AUDIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamAuditService(db, principal, request).section(session_id, section, paper_id))


@router.get(
    "/exams/{session_id}/audit/summary",
    summary="Exam audit summary card (section counts, open gaps)",
    response_model=Envelope[ExamAuditSummaryOut],
    dependencies=EXAMS,
)
async def exam_audit_summary(
    session_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(EXAM_AUDIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ExamAuditService(db, principal, request).summary(session_id))


@router.post(
    "/exams/{session_id}/audit/export",
    status_code=202,
    summary="Exam audit report (report.run of exams.audit_trail)",
    response_model=Envelope[JobQueuedOut],
    dependencies=EXAMS,
)
async def exam_audit_export(
    session_id: uuid.UUID,
    body: ExamAuditExportRequest,
    request: Request,
    principal: Principal = Depends(EXAM_AUDIT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    out = await ExamAuditService(db, principal, request).export(
        session_id, list(body.sections or []) or None, body.format
    )
    return _queued(out, "Exam audit report queued")


# ---- security ------------------------------------------------------------------------------------------------------
@router.get(
    "/security/events", summary="Security events", response_model=Envelope[list[SecurityEventOut]], dependencies=AUDIT
)
async def security_events(
    request: Request,
    type: str | None = Query(None, max_length=40),
    user_id: uuid.UUID | None = None,
    ip: str | None = Query(None, max_length=60),
    severity: str | None = Query(None, pattern="^(info|low|medium|high)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(SECURITY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SecurityService(db, principal, request).events(type, user_id, ip, date_from, date_to, severity))


@router.get(
    "/security/anomalies", summary="Anomaly alerts", response_model=Envelope[list[AnomalyAlertOut]], dependencies=AUDIT
)
async def anomalies(
    request: Request,
    active: bool | None = None,
    principal: Principal = Depends(SECURITY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SecurityService(db, principal, request).anomalies(active))


@router.post(
    "/security/anomalies/{id}/acknowledge",
    summary="Acknowledge an anomaly alert",
    response_model=Envelope[AnomalyAlertOut],
    dependencies=AUDIT,
)
async def acknowledge(
    id: str,
    body: AnomalyAck,
    request: Request,
    principal: Principal = Depends(SECURITY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SecurityService(db, principal, request).acknowledge(id, body.note), message="Acknowledged")


@router.get(
    "/security/sessions",
    summary="Sessions across users",
    response_model=Envelope[list[AdminSessionOut]],
    dependencies=AUDIT,
)
async def admin_sessions(
    request: Request,
    user_id: uuid.UUID | None = None,
    include_revoked: bool = False,
    principal: Principal = Depends(SESSIONS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SecurityService(db, principal, request).sessions(user_id, include_revoked))


@router.post(
    "/security/sessions/revoke",
    summary="Revoke a session / all sessions of a user (optionally force MFA re-enrolment)",
    response_model=Envelope[SessionRevokeOut],
    dependencies=AUDIT,
)
async def admin_revoke(
    body: SessionRevokeRequest,
    request: Request,
    principal: Principal = Depends(SESSIONS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SecurityService(db, principal, request).revoke(body), message="Sessions revoked")


@router.get(
    "/security/login-history",
    summary="Login history across users",
    response_model=Envelope[list[LoginHistoryAdminOut]],
    dependencies=AUDIT,
)
async def admin_login_history(
    request: Request,
    user_id: uuid.UUID | None = None,
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    principal: Principal = Depends(SESSIONS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SecurityService(db, principal, request).login_history(user_id, date_from, date_to))


# ---- retention -----------------------------------------------------------------------------------------------------
@router.get(
    "/retention/policies",
    summary="Retention policy (+ platform maximums)",
    response_model=Envelope[RetentionPolicyOut],
    dependencies=SETTINGS,
)
async def get_policies(
    request: Request, principal: Principal = Depends(SETTINGS_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RetentionService(db, principal, request).policies())


@router.put(
    "/retention/policies",
    summary="Update the retention policy",
    response_model=Envelope[RetentionPolicyOut],
    dependencies=SETTINGS,
)
async def put_policies(
    body: RetentionPolicyIn,
    request: Request,
    principal: Principal = Depends(SETTINGS_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RetentionService(db, principal, request).put_policies(body), message="Retention policy saved")


@router.get(
    "/retention/preview",
    summary="Rows a purge / archive would touch",
    response_model=Envelope[RetentionPreviewOut],
    dependencies=SETTINGS,
)
async def preview(
    request: Request,
    data_class: str = Query(max_length=40),
    principal: Principal = Depends(SETTINGS_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RetentionService(db, principal, request).preview(data_class))


@router.post(
    "/retention/purge",
    status_code=202,
    summary="Purge a data class (retention.purge job)",
    response_model=Envelope[JobQueuedOut],
    dependencies=SETTINGS,
)
async def purge(
    body: RetentionRunRequest,
    request: Request,
    principal: Principal = Depends(SETTINGS_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return _queued(await RetentionService(db, principal, request).enqueue_run("purge", body), "Purge queued")


@router.post(
    "/retention/archive",
    status_code=202,
    summary="Archive a period (retention.archive job)",
    response_model=Envelope[JobQueuedOut],
    dependencies=SETTINGS,
)
async def archive(
    body: RetentionRunRequest,
    request: Request,
    principal: Principal = Depends(SETTINGS_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return _queued(await RetentionService(db, principal, request).enqueue_run("archive", body), "Archive queued")


@router.get(
    "/retention/manifests",
    summary="Purge / archive manifests",
    response_model=Envelope[list[ArchiveManifestOut]],
    dependencies=SETTINGS,
)
async def manifests(
    request: Request,
    data_class: str | None = Query(None, max_length=40),
    principal: Principal = Depends(SETTINGS_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RetentionService(db, principal, request).manifests(data_class))


@router.post(
    "/retention/restore",
    status_code=202,
    summary="Restore an archive (super admin, job)",
    response_model=Envelope[JobQueuedOut],
    dependencies=SETTINGS,
)
async def restore(
    body: RestoreRequest,
    request: Request,
    principal: Principal = Depends(SETTINGS_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return _queued(await RetentionService(db, principal, request).enqueue_restore(body.manifest_id), "Restore queued")


@router.get(
    "/retention/legal-holds", summary="Legal holds", response_model=Envelope[list[LegalHoldOut]], dependencies=SETTINGS
)
async def legal_holds(
    request: Request,
    active: bool = True,
    principal: Principal = Depends(HOLDS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RetentionService(db, principal, request).legal_holds(active_only=active))


@router.post(
    "/retention/legal-holds",
    status_code=201,
    summary="Set a legal hold",
    response_model=Envelope[LegalHoldOut],
    dependencies=SETTINGS,
)
async def add_hold(
    body: LegalHoldIn, request: Request, principal: Principal = Depends(HOLDS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RetentionService(db, principal, request).add_hold(body), message="Legal hold set")


@router.delete(
    "/retention/legal-holds/{id}",
    summary="Clear a legal hold",
    response_model=Envelope[LegalHoldOut],
    dependencies=SETTINGS,
)
async def clear_hold(
    id: str, request: Request, principal: Principal = Depends(HOLDS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RetentionService(db, principal, request).clear_hold(id), message="Legal hold cleared")
