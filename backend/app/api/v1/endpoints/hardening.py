"""Phase 43 — privacy office, security posture, QA suites (Prompts/43 §43.8).

Routers: ``router`` (``/privacy/*``, ``/consents/bulk|wards|{purpose}/withdraw``, ``/data-subject-requests/{id}…``,
``/security/*``, ``/qa/*``), ``public_router`` (``/public/privacy/notices/{key}``, ``POST /security/csp-report``),
``well_known_router`` (``/.well-known/jwks.json`` at the site root) and ``dev_router`` (``/_dev/compute/{kind}``,
registered only outside production). ``qa`` routes answer 404 in production.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import log_audit
from app.core.authz.dependencies import Principal, any_permission_required, authenticated, platform_permission
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.core.rate_limit import rate_limited
from app.core.security import jwks
from app.db.session import get_db, get_platform_db, redis_client
from app.schemas.common import Envelope
from app.schemas.privacy import (
    ConsentBannerOut,
    ConsentBulkIn,
    ConsentPurposeOut,
    ConsentReportOut,
    DsrAction,
    DsrIdentityVerify,
    DsrOut,
    NoticeIn,
    NoticeOut,
)
from app.services.hardening.posture import PostureService, iso_readiness, vapt_status
from app.services.hardening.privacy_office import PrivacyOfficeService
from app.services.hardening.qa import QaService
from app.utils.response import ok

router = APIRouter()
public_router = APIRouter(tags=["public"])
well_known_router = APIRouter(tags=["public"])
dev_router = APIRouter(tags=["dev"])

CONSENT = [feature_required("privacy.dpdp_consent")]
DSR = [feature_required("privacy.data_subject_requests")]
OFFICER = any_permission_required(("privacy", "manage"), ("privacy", "view_all"))
PII_READ = any_permission_required(
    ("privacy", "manage"), ("privacy", "view_all"), ("security", "manage"), ("security", "view_all")
)
SEC_READ = any_permission_required(
    ("security", "view"), ("security", "view_all"), ("security", "manage"), ("privacy", "manage")
)
SEC_MANAGE = any_permission_required(
    ("security", "manage"),
)
# not ``qa:view`` — every role holding ``ALL("view")`` would reach the reports; auditors read via security:view_all
QA_VIEW = any_permission_required(("qa", "run"), ("security", "manage"), ("security", "view_all"))
QA_RUN = any_permission_required(("qa", "run"), ("security", "manage"))


# ---- consents -------------------------------------------------------------------------------------------------------
@router.get(
    "/privacy/purposes",
    tags=["privacy"],
    summary="Consent purposes (registry)",
    dependencies=CONSENT,
    response_model=Envelope[list[ConsentPurposeOut]],
)
async def purposes(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).purposes())


@router.get(
    "/privacy/consent-banner",
    tags=["privacy"],
    summary="Consent banner state for me",
    dependencies=CONSENT,
    response_model=Envelope[ConsentBannerOut],
)
async def consent_banner(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).banner())


@router.post(
    "/consents/bulk",
    tags=["privacy"],
    summary="Record several consent decisions (self or a minor ward)",
    dependencies=CONSENT,
    response_model=Envelope[dict[str, Any]],
)
async def consents_bulk(
    body: ConsentBulkIn,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal, request).bulk(body), message="Preferences saved")


@router.post(
    "/consents/{purpose}/withdraw",
    tags=["privacy"],
    summary="Withdraw a consent",
    dependencies=CONSENT,
    response_model=Envelope[dict[str, Any]],
)
async def consent_withdraw(
    purpose: str, request: Request, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal, request).withdraw(purpose), message="Consent withdrawn")


@router.get(
    "/consents/wards",
    tags=["privacy"],
    summary="My wards' consents (guardian)",
    dependencies=CONSENT,
    response_model=Envelope[list[dict[str, Any]]],
)
async def consent_wards(
    principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).wards())


@router.get(
    "/privacy/consents/report",
    tags=["privacy"],
    summary="Consent report (masked rows)",
    dependencies=CONSENT,
    response_model=Envelope[ConsentReportOut],
)
async def consent_report(
    purpose: str | None = Query(default=None, max_length=40),
    granted: bool | None = None,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(OFFICER),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).report(purpose, granted, college_id))


# ---- notices --------------------------------------------------------------------------------------------------------
@router.get(
    "/privacy/notices",
    tags=["privacy"],
    summary="Privacy notices with drafts",
    dependencies=CONSENT,
    response_model=Envelope[list[NoticeOut]],
)
async def notices(principal: Principal = Depends(OFFICER), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).notices())


@router.post(
    "/privacy/notices",
    tags=["privacy"],
    summary="Save a notice draft",
    dependencies=CONSENT,
    response_model=Envelope[NoticeOut],
)
async def notice_save(
    body: NoticeIn, request: Request, principal: Principal = Depends(OFFICER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    out = await PrivacyOfficeService(db, principal, request).save_notice(body)
    await log_audit(
        db,
        principal=principal,
        module="privacy",
        action="notice_draft",
        record_type="notice",
        record_id=None,
        new={"key": body.key},
        request=request,
    )
    return ok(out, message="Draft saved")


@router.post(
    "/privacy/notices/{key}/publish",
    tags=["privacy"],
    summary="Publish a notice (new version, re-consent)",
    dependencies=CONSENT,
    response_model=Envelope[NoticeOut],
)
async def notice_publish(
    key: str, request: Request, principal: Principal = Depends(OFFICER), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal, request).publish_notice(key), message="Notice published")


@public_router.get(
    "/public/privacy/notices/{key}",
    summary="Published notice text (website / app)",
    response_model=Envelope[dict[str, Any]],
)
async def public_notice(
    key: str, institution: str | None = Query(default=None, max_length=60), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    iid = None
    if institution:
        iid = (
            await db.execute(
                text("SELECT id FROM institutions WHERE slug = :s AND deleted_at IS NULL"), {"s": institution}
            )
        ).scalar_one_or_none()
    return ok(await PrivacyOfficeService(db, None).public_notice(iid, key))


# ---- DSRs -----------------------------------------------------------------------------------------------------------
@router.get(
    "/data-subject-requests/{id}",
    tags=["privacy"],
    summary="A data-subject request (requester / officer / owner)",
    dependencies=DSR,
    response_model=Envelope[DsrOut],
)
async def dsr_get(
    id: uuid.UUID, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).get(id))


@router.post(
    "/data-subject-requests/{id}/identity",
    tags=["privacy"],
    summary="Verify identity (OTP or document)",
    dependencies=[*DSR, rate_limited("dsr_identity", limit=10, window=600)],
    response_model=Envelope[DsrOut],
)
async def dsr_identity(
    id: uuid.UUID,
    body: DsrIdentityVerify,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    out = await PrivacyOfficeService(db, principal, request).identity(id, body)
    await log_audit(
        db,
        principal=principal,
        module="privacy",
        action="dsr_identity",
        record_type="data_subject_request",
        record_id=id,
        new={"method": body.method},
        request=request,
    )
    return ok(out)


@router.post(
    "/data-subject-requests/{id}/action",
    tags=["privacy"],
    summary="Officer action (start / extend / complete / reject)",
    dependencies=DSR,
    response_model=Envelope[DsrOut],
)
async def dsr_action(
    id: uuid.UUID,
    body: DsrAction,
    request: Request,
    principal: Principal = Depends(
        any_permission_required(
            ("privacy", "manage"),
        )
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal, request).act(id, body))


@router.get(
    "/data-subject-requests/{id}/work-items",
    tags=["privacy"],
    summary="Correction work items",
    dependencies=DSR,
    response_model=Envelope[list[dict[str, Any]]],
)
async def dsr_work_items(
    id: uuid.UUID, principal: Principal = Depends(authenticated()), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).work_items(id))


@router.post(
    "/data-subject-requests/{id}/work-items/{n}/done",
    tags=["privacy"],
    summary="Close a work item (record owner)",
    dependencies=DSR,
    response_model=Envelope[DsrOut],
)
async def dsr_work_item_done(
    id: uuid.UUID,
    n: int,
    request: Request,
    principal: Principal = Depends(authenticated()),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal, request).work_item_done(id, n))


@router.get(
    "/privacy/dsr/dashboard",
    tags=["privacy"],
    summary="DSR board counts / SLA",
    dependencies=DSR,
    response_model=Envelope[dict[str, Any]],
)
async def dsr_dashboard(principal: Principal = Depends(OFFICER), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).dashboard())


@router.get(
    "/privacy/dsr/register",
    tags=["privacy"],
    summary="DSR register rows (export)",
    dependencies=DSR,
    response_model=Envelope[list[dict[str, Any]]],
)
async def dsr_register(principal: Principal = Depends(OFFICER), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).register())


# ---- PII inventory / masking audit ------------------------------------------------------------------------------------
@router.get(
    "/privacy/pii-inventory",
    tags=["privacy"],
    summary="PII field inventory",
    response_model=Envelope[list[dict[str, Any]]],
)
async def pii_inventory(principal: Principal = Depends(PII_READ), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).pii_inventory())


@router.post(
    "/privacy/masking-audit", tags=["privacy"], summary="Run the masking audit", response_model=Envelope[dict[str, Any]]
)
async def masking_audit(
    request: Request,
    principal: Principal = Depends(any_permission_required(("privacy", "manage"), ("security", "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal, request).masking_audit())


@router.get(
    "/privacy/masking-audit/latest",
    tags=["privacy"],
    summary="Latest masking audit",
    response_model=Envelope[dict[str, Any]],
)
async def masking_audit_latest(
    principal: Principal = Depends(PII_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PrivacyOfficeService(db, principal).masking_audit_latest())


# ---- security posture -----------------------------------------------------------------------------------------------
@router.get(
    "/security/posture", tags=["security"], summary="Latest posture result", response_model=Envelope[dict[str, Any]]
)
async def posture(principal: Principal = Depends(SEC_READ), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PostureService(db, principal).latest())


@router.post(
    "/security/posture/check",
    tags=["security"],
    summary="Re-check the posture controls",
    response_model=Envelope[dict[str, Any]],
)
async def posture_check(
    request: Request, principal: Principal = Depends(SEC_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    out = await PostureService(db, principal, request).check()
    await log_audit(
        db,
        principal=principal,
        module="security",
        action="posture_check",
        record_type="institution",
        record_id=principal.institution_id,
        new={"score": out["score"]},
        request=request,
    )
    return ok(out)


@router.get(
    "/security/mfa-enforcement",
    tags=["security"],
    summary="Users missing MFA in required roles",
    response_model=Envelope[dict[str, Any]],
)
async def mfa_enforcement(
    principal: Principal = Depends(SEC_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PostureService(db, principal).mfa_enforcement())


@router.post(
    "/security/mfa-enforcement/enforce",
    tags=["security"],
    summary="Enforce MFA after a grace period",
    response_model=Envelope[dict[str, Any]],
)
async def mfa_enforce(
    request: Request,
    grace_days: int = Query(default=3, ge=0, le=60),
    principal: Principal = Depends(SEC_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PostureService(db, principal, request).enforce_mfa(grace_days), message="MFA enforcement scheduled")


@router.get(
    "/security/scans", tags=["security"], summary="CI scan summary", response_model=Envelope[list[dict[str, Any]]]
)
async def scans(principal: Principal = Depends(SEC_READ), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await PostureService(db, principal).scans())


@router.get(
    "/security/vapt",
    tags=["security"],
    summary="VAPT findings and release gate",
    response_model=Envelope[dict[str, Any]],
)
async def vapt(principal: Principal = Depends(SEC_READ)) -> dict[str, Any]:
    return ok(vapt_status())


@router.get(
    "/security/iso-readiness",
    tags=["security"],
    summary="ISO 27001 readiness summary",
    response_model=Envelope[dict[str, Any]],
)
async def iso(principal: Principal = Depends(SEC_READ)) -> dict[str, Any]:
    return ok(iso_readiness())


@router.get("/security/jwt", tags=["security"], summary="Signing keys status", response_model=Envelope[dict[str, Any]])
async def jwt_status(
    principal: Principal = Depends(platform_permission("platform", "view")), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await PostureService(db, principal).jwt_status())


@router.post(
    "/security/jwt/rotate",
    tags=["security"],
    summary="JWT key rotation (runbook — keys are deployment secrets)",
    response_model=Envelope[dict[str, Any]],
)
async def jwt_rotate(
    request: Request,
    principal: Principal = Depends(platform_permission("platform", "manage", support=False)),
    db: AsyncSession = Depends(get_platform_db),
) -> dict[str, Any]:
    await log_audit(
        db,
        principal=principal,
        module="security",
        action="jwt_rotate_requested",
        record_type="platform",
        record_id=None,
        new={},
        request=request,
    )
    status = await PostureService(db, principal).jwt_status()
    return ok(
        {
            **status,
            "steps": [
                "Generate a new RSA-2048 key pair offline (openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048).",
                "Move the current public key into JWT_RSA_PREVIOUS_PUBLIC_KEYS under the current JWT_KID.",
                "Deploy the new private key as JWT_RSA_PRIVATE_KEY with a new JWT_KID (rolling restart).",
                "After ACCESS_TOKEN_EXPIRE_MINUTES + REFRESH_TOKEN_EXPIRE_DAYS remove the previous key.",
            ],
        },
        message="Rotation is a deployment change — follow the steps",
    )


@router.get(
    "/security/platform-posture",
    tags=["security"],
    summary="Platform posture across tenants (super admin)",
    response_model=Envelope[dict[str, Any]],
)
async def platform_posture(
    principal: Principal = Depends(platform_permission("platform", "view")), db: AsyncSession = Depends(get_platform_db)
) -> dict[str, Any]:
    return ok(await PostureService(db, principal).platform_posture())


@public_router.post(
    "/security/csp-report",
    summary="CSP violation report (sampled)",
    status_code=204,
    dependencies=[rate_limited("csp_report", limit=60, window=60)],
)
async def csp_report(request: Request) -> None:
    body = (await request.body())[:4000]
    try:
        import random

        if random.random() < 0.2:  # noqa: S311 - sampling, not security
            await redis_client.lpush("csp:reports", body)  # type: ignore[misc]
            await redis_client.ltrim("csp:reports", 0, 999)  # type: ignore[misc]
    except Exception:  # noqa: BLE001, S110 - reports are best effort
        pass


@public_router.post("/internal/security/scans", summary="CI scan summary push (X-Ops-Token)", status_code=204)
async def internal_scans(request: Request, db: AsyncSession = Depends(get_platform_db)) -> None:
    import hmac
    import json

    from app.core.config import settings

    token = request.headers.get("x-ops-token", "")
    if not settings.INTERNAL_OPS_TOKEN or not hmac.compare_digest(token, settings.INTERNAL_OPS_TOKEN):
        raise APIError(401, ErrorCode.UNAUTHENTICATED, "Invalid ops token")
    body = await request.json()
    if not isinstance(body, dict):
        raise APIError(422, ErrorCode.VALIDATION, "Expected {tool: {high, medium, low, run_at, report_url}}")
    await db.execute(
        text(
            "INSERT INTO platform_settings (key, value) VALUES ('security.scans', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
        ),
        {"v": json.dumps(body)},
    )
    await db.commit()


@well_known_router.get("/.well-known/jwks.json", summary="JWK set of the token signing keys")
async def well_known_jwks() -> dict[str, Any]:
    return jwks()


# ---- QA (non-production) --------------------------------------------------------------------------------------------
@router.post(
    "/qa/suites/run", tags=["qa"], summary="Run a verification suite (job)", response_model=Envelope[dict[str, Any]]
)
async def qa_run(
    request: Request,
    suite: str = Query(max_length=40),
    env: str = Query(default="dev", pattern="^(dev|demo|staging)$"),
    principal: Principal = Depends(QA_RUN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await QaService(db, principal, request).run_suite(suite, env), message="Suite queued")


@router.get("/qa/suites/runs", tags=["qa"], summary="Suite runs", response_model=Envelope[list[dict[str, Any]]])
async def qa_runs(principal: Principal = Depends(QA_VIEW), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await QaService(db, principal).runs())


@router.get("/qa/suites/runs/{id}/report", tags=["qa"], summary="Suite report", response_model=Envelope[dict[str, Any]])
async def qa_report(
    id: uuid.UUID, principal: Principal = Depends(QA_VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await QaService(db, principal).report(str(id)))


@router.post("/qa/golden/run", tags=["qa"], summary="Run the golden datasets", response_model=Envelope[dict[str, Any]])
async def qa_golden(
    request: Request, principal: Principal = Depends(QA_RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await QaService(db, principal, request).golden())


@router.get(
    "/qa/access-matrix",
    tags=["qa"],
    summary="Access matrix summary + unexpected grants",
    response_model=Envelope[dict[str, Any]],
)
async def qa_matrix(principal: Principal = Depends(QA_VIEW), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await QaService(db, principal).access_matrix())


@router.post(
    "/qa/access-matrix/regenerate",
    tags=["qa"],
    summary="Regenerate the access matrix (job)",
    response_model=Envelope[dict[str, Any]],
)
async def qa_matrix_regen(
    request: Request, principal: Principal = Depends(QA_RUN), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    out = await QaService(db, principal, request).regenerate_access_matrix()
    await log_audit(
        db,
        principal=principal,
        module="qa",
        action="access_matrix_regenerate",
        record_type="qa",
        record_id=None,
        new=out,
        request=request,
    )
    return ok(out)


@router.get(
    "/qa/load-results", tags=["qa"], summary="Load-test results vs thresholds", response_model=Envelope[dict[str, Any]]
)
async def qa_load(principal: Principal = Depends(QA_VIEW), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return ok(await QaService(db, principal).load_results())


# ---- golden compute (dev / staging) ---------------------------------------------------------------------------------
@dev_router.post(
    "/_dev/compute/{kind}",
    summary="Run a production calculator on golden input",
    response_model=Envelope[dict[str, Any]],
)
async def dev_compute(kind: str, body: dict[str, Any], principal: Principal = Depends(QA_RUN)) -> dict[str, Any]:
    from app.services.hardening.golden import COMPUTE, _norm

    fn = COMPUTE.get(kind)
    if fn is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown calculator", {"allowed": sorted(COMPUTE)})
    return ok(_norm(fn(body)))
