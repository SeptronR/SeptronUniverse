"""Placement — Prompts/28 §28.8 {placement.core}: companies (+ recruiter invitations {placement.recruiter_portal}),
policies, drives (lifecycle, eligibility preview / list, applications, shortlist, override, re-evaluation), rounds and
results, funnel, offers (create, decision, status, pending recruiter offers), profiles (+ resume render
{placement.resume_builder}, opt-out), blacklist, drive feedback, statistics, NIRF sheet and report exports. Visibility
(self / wards / department / college / all / recruiter company) is narrowed by the services.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.core.idempotency import idempotency_key, store
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.placement import (
    PlcApplicationOut,
    PlcApplyRequest,
    PlcBlacklistOut,
    PlcBlacklistRequest,
    PlcBulkReport,
    PlcCompanyBlacklist,
    PlcCompanyIn,
    PlcCompanyOut,
    PlcDriveAction,
    PlcDriveCreate,
    PlcDriveOut,
    PlcDriveUpdate,
    PlcEligibilityPreview,
    PlcFeedbackIn,
    PlcFeedbackOut,
    PlcFunnel,
    PlcJobOut,
    PlcOfferCreate,
    PlcOfferDecision,
    PlcOfferOut,
    PlcOfferStatusUpdate,
    PlcOptOut,
    PlcOverrideEligibility,
    PlcPendingOffer,
    PlcPolicyIn,
    PlcPolicyOut,
    PlcProfileIn,
    PlcProfileOut,
    PlcRecruiterInvite,
    PlcRecruiterInviteOut,
    PlcResumeRender,
    PlcRoundIn,
    PlcRoundOut,
    PlcRoundResultsBulk,
    PlcRoundUpdate,
    PlcShortlistBulk,
    PlcStats,
)
from app.services.placement.company_service import CompanyService
from app.services.placement.drive_service import DriveService
from app.services.placement.eligibility_service import PolicyService
from app.services.placement.offer_service import OfferService
from app.services.placement.profile_service import ProfileService
from app.services.placement.stats_service import StatsService
from app.utils.response import ok

router = APIRouter(tags=["placement"])

P = "placement"
MANAGE = any_permission_required((P, "manage"))
COMPANY_READ = any_permission_required((P, "manage"), (P, "view_all"), (P, "drive_manage"), (P, "recruiter"))
POLICY_READ = any_permission_required((P, "manage"), (P, "view_all"), (P, "view"), (P, "drive_manage"))
DRIVE_MANAGE = any_permission_required((P, "drive_manage"), (P, "manage"))
DRIVE_READ = any_permission_required(
    (P, "drive_manage"), (P, "manage"), (P, "view_all"), (P, "self"), (P, "wards"), (P, "recruiter")
)
STAFF_READ = any_permission_required((P, "drive_manage"), (P, "manage"), (P, "view_all"), (P, "override_eligibility"))
SELF = any_permission_required((P, "self"))
WARDS = any_permission_required((P, "wards"))
OVERRIDE = any_permission_required((P, "override_eligibility"))
OFFER_MANAGE = any_permission_required((P, "offer_manage"), (P, "manage"))
OFFER_READ = any_permission_required(
    (P, "offer_manage"), (P, "manage"), (P, "view_all"), (P, "self"), (P, "wards"), (P, "recruiter")
)
PROFILE_READ = any_permission_required((P, "view_all"), (P, "manage"))
FEEDBACK = any_permission_required((P, "recruiter"), (P, "manage"), (P, "drive_manage"))
STATS = any_permission_required((P, "view_all"), (P, "manage"), ("reports", "export"))

CORE = [feature_required("placement.core")]
PORTAL = [feature_required("placement.core"), feature_required("placement.recruiter_portal")]
RESUME = [feature_required("placement.core"), feature_required("placement.resume_builder")]


def _vis(data: Any, svc: Any) -> dict[str, Any]:
    res = ok(data)
    res["meta"]["visibility"] = svc.visibility(self_tab=False, own_tab=False)
    return res


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(status_code=202, content=ok(PlcJobOut(job_id=j.id).model_dump(mode="json"), message="Queued"))


# ---- companies ----------------------------------------------------------------------------------------------------------
@router.get(
    "/placement/companies", summary="Companies", response_model=Envelope[list[PlcCompanyOut]], dependencies=CORE
)
async def companies(
    request: Request,
    q: str | None = None,
    tier: str | None = None,
    blacklisted: bool | None = None,
    principal: Principal = Depends(COMPANY_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CompanyService(db, principal, request).list_companies(q, tier, blacklisted))


@router.post(
    "/placement/companies",
    status_code=201,
    summary="Create company",
    response_model=Envelope[PlcCompanyOut],
    dependencies=CORE,
)
async def create_company(
    body: PlcCompanyIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CompanyService(db, principal, request).create(body), message="Created")


@router.get(
    "/placement/companies/{id}",
    summary="Company page (history)",
    response_model=Envelope[PlcCompanyOut],
    dependencies=CORE,
)
async def company(
    id: uuid.UUID, request: Request, principal: Principal = Depends(COMPANY_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CompanyService(db, principal, request).get(id))


@router.put(
    "/placement/companies/{id}", summary="Update company", response_model=Envelope[PlcCompanyOut], dependencies=CORE
)
async def update_company(
    id: uuid.UUID,
    body: PlcCompanyIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CompanyService(db, principal, request).update(id, body))


@router.post(
    "/placement/companies/{id}/blacklist",
    summary="Blacklist / restore a company",
    response_model=Envelope[PlcCompanyOut],
    dependencies=CORE,
)
async def blacklist_company(
    id: uuid.UUID,
    body: PlcCompanyBlacklist,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CompanyService(db, principal, request).blacklist(id, body))


@router.post(
    "/placement/companies/{id}/recruiters/invite",
    status_code=201,
    summary="Invite a recruiter user",
    response_model=Envelope[PlcRecruiterInviteOut],
    dependencies=PORTAL,
)
async def invite_recruiter(
    id: uuid.UUID,
    body: PlcRecruiterInvite,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CompanyService(db, principal, request).invite(id, body), message="Invited")


@router.get(
    "/placement/companies/{id}/feedback",
    summary="Company feedback",
    response_model=Envelope[list[PlcFeedbackOut]],
    dependencies=CORE,
)
async def company_feedback(
    id: uuid.UUID, request: Request, principal: Principal = Depends(FEEDBACK), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CompanyService(db, principal, request).feedback(id))


# ---- policies -----------------------------------------------------------------------------------------------------------
@router.get(
    "/placement/policies", summary="Placement policies", response_model=Envelope[list[PlcPolicyOut]], dependencies=CORE
)
async def policies(
    request: Request, principal: Principal = Depends(POLICY_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).list_policies())


@router.post(
    "/placement/policies",
    status_code=201,
    summary="Create policy",
    response_model=Envelope[PlcPolicyOut],
    dependencies=CORE,
)
async def create_policy(
    body: PlcPolicyIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).create(body), message="Created")


@router.get(
    "/placement/policies/effective",
    summary="Effective policy for a batch / programme",
    response_model=Envelope[PlcPolicyOut],
    dependencies=CORE,
)
async def effective_policy(
    request: Request,
    batch_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    principal: Principal = Depends(POLICY_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).effective(batch_id, program_id))


@router.put(
    "/placement/policies/{id}", summary="Update policy", response_model=Envelope[PlcPolicyOut], dependencies=CORE
)
async def update_policy(
    id: uuid.UUID,
    body: PlcPolicyIn,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PolicyService(db, principal, request).update(id, body))


# ---- drives -------------------------------------------------------------------------------------------------------------
@router.get("/placement/drives", summary="Drives", response_model=Envelope[list[PlcDriveOut]], dependencies=CORE)
async def drives(
    request: Request,
    status: str | None = None,
    company_id: uuid.UUID | None = None,
    principal: Principal = Depends(DRIVE_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).list_drives(status, company_id))


@router.post(
    "/placement/drives",
    status_code=201,
    summary="Create drive (draft)",
    response_model=Envelope[PlcDriveOut],
    dependencies=CORE,
)
async def create_drive(
    body: PlcDriveCreate,
    request: Request,
    principal: Principal = Depends(DRIVE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).create(body), message="Created")


@router.get(
    "/placement/drives/open",
    summary="Open drives with my eligibility and reasons",
    response_model=Envelope[list[PlcDriveOut]],
    dependencies=CORE,
)
async def open_drives(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).open_drives())


@router.get("/placement/drives/{id}", summary="Drive", response_model=Envelope[PlcDriveOut], dependencies=CORE)
async def drive(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DRIVE_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).get(id))


@router.put("/placement/drives/{id}", summary="Update drive", response_model=Envelope[PlcDriveOut], dependencies=CORE)
async def update_drive(
    id: uuid.UUID,
    body: PlcDriveUpdate,
    request: Request,
    principal: Principal = Depends(DRIVE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).update(id, body))


@router.post(
    "/placement/drives/{id}/action",
    summary="Publish / close / start / complete / cancel",
    response_model=Envelope[PlcDriveOut],
    dependencies=CORE,
)
async def drive_action(
    id: uuid.UUID,
    body: PlcDriveAction,
    request: Request,
    principal: Principal = Depends(DRIVE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).action(id, body))


@router.get(
    "/placement/drives/{id}/eligibility-preview",
    summary="Eligibility preview (counts, reasons)",
    response_model=Envelope[PlcEligibilityPreview],
    dependencies=CORE,
)
async def eligibility_preview(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STAFF_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).eligibility_preview(id))


@router.get(
    "/placement/drives/{id}/eligible-list",
    summary="Eligible list (export)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=CORE,
)
async def eligible_list(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STAFF_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).eligible_list(id))


@router.post(
    "/placement/drives/{id}/apply",
    status_code=201,
    summary="Apply (Idempotency-Key)",
    response_model=Envelope[PlcApplicationOut],
    dependencies=CORE,
)
async def apply(
    id: uuid.UUID,
    body: PlcApplyRequest,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(await DriveService(db, principal, request).apply(id, body), message="Applied")
    await store(request, response, db, 201)
    return response


@router.get(
    "/placement/drives/{id}/applications",
    summary="Drive applications (ScopeTabs)",
    response_model=Envelope[list[PlcApplicationOut]],
    dependencies=CORE,
)
async def drive_applications(
    id: uuid.UUID,
    request: Request,
    status: str | None = None,
    round: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(STAFF_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = DriveService(db, principal, request)
    return _vis(await svc.drive_applications(id, status, round, department_id, scope), svc)


@router.post(
    "/placement/drives/{id}/shortlist",
    summary="Shortlist (bulk, partial report)",
    response_model=Envelope[PlcBulkReport],
    dependencies=CORE,
)
async def shortlist(
    id: uuid.UUID,
    body: PlcShortlistBulk,
    request: Request,
    principal: Principal = Depends(DRIVE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).shortlist(id, body))


@router.post(
    "/placement/drives/{id}/re-evaluate",
    summary="Re-evaluate eligibility (results republished)",
    response_model=Envelope[PlcBulkReport],
    dependencies=CORE,
)
async def re_evaluate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DRIVE_MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).re_evaluate(id))


@router.get(
    "/placement/drives/{id}/rounds", summary="Rounds", response_model=Envelope[list[PlcRoundOut]], dependencies=CORE
)
async def rounds(
    id: uuid.UUID, request: Request, principal: Principal = Depends(DRIVE_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).rounds(id))


@router.post(
    "/placement/drives/{id}/rounds",
    status_code=201,
    summary="Add round",
    response_model=Envelope[PlcRoundOut],
    dependencies=CORE,
)
async def add_round(
    id: uuid.UUID,
    body: PlcRoundIn,
    request: Request,
    principal: Principal = Depends(DRIVE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).add_round(id, body), message="Created")


@router.get(
    "/placement/drives/{id}/funnel", summary="Funnel by round", response_model=Envelope[PlcFunnel], dependencies=CORE
)
async def funnel(
    id: uuid.UUID, request: Request, principal: Principal = Depends(STAFF_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).funnel_for(id))


@router.post(
    "/placement/drives/{id}/feedback",
    status_code=201,
    summary="Company feedback on a drive",
    response_model=Envelope[PlcFeedbackOut],
    dependencies=CORE,
)
async def drive_feedback(
    id: uuid.UUID,
    body: PlcFeedbackIn,
    request: Request,
    principal: Principal = Depends(FEEDBACK),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).feedback(id, body), message="Saved")


@router.put("/placement/rounds/{id}", summary="Update round", response_model=Envelope[PlcRoundOut], dependencies=CORE)
async def update_round(
    id: uuid.UUID,
    body: PlcRoundUpdate,
    request: Request,
    principal: Principal = Depends(DRIVE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).update_round(id, body))


@router.post(
    "/placement/rounds/{id}/results",
    summary="Round results (bulk)",
    response_model=Envelope[PlcBulkReport],
    dependencies=CORE,
)
async def round_results(
    id: uuid.UUID,
    body: PlcRoundResultsBulk,
    request: Request,
    principal: Principal = Depends(DRIVE_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).round_results(id, body))


# ---- applications -------------------------------------------------------------------------------------------------------
@router.get(
    "/placement/applications/me",
    summary="My applications",
    response_model=Envelope[list[PlcApplicationOut]],
    dependencies=CORE,
)
async def my_applications(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).my_applications())


@router.get(
    "/placement/applications/wards",
    summary="Ward applications",
    response_model=Envelope[list[PlcApplicationOut]],
    dependencies=CORE,
)
async def ward_applications(
    request: Request, principal: Principal = Depends(WARDS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).ward_applications())


@router.post(
    "/placement/applications/override-eligibility",
    summary="Override eligibility (reason, audited)",
    response_model=Envelope[PlcApplicationOut],
    dependencies=CORE,
)
async def override(
    body: PlcOverrideEligibility,
    request: Request,
    principal: Principal = Depends(OVERRIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).override(body))


@router.post(
    "/placement/applications/{id}/withdraw",
    summary="Withdraw (before shortlist)",
    response_model=Envelope[PlcApplicationOut],
    dependencies=CORE,
)
async def withdraw(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DriveService(db, principal, request).withdraw(id))


# ---- offers -------------------------------------------------------------------------------------------------------------
@router.get(
    "/placement/offers", summary="Offers (ScopeTabs)", response_model=Envelope[list[PlcOfferOut]], dependencies=CORE
)
async def offers(
    request: Request,
    status: str | None = None,
    drive_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(OFFER_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = OfferService(db, principal, request)
    return _vis(await svc.list_offers(status, drive_id, scope), svc)


@router.post(
    "/placement/offers",
    status_code=201,
    summary="Create offer",
    response_model=Envelope[PlcOfferOut],
    dependencies=CORE,
)
async def create_offer(
    body: PlcOfferCreate,
    request: Request,
    principal: Principal = Depends(OFFER_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).create(body), message="Offered")


@router.get("/placement/offers/me", summary="My offers", response_model=Envelope[list[PlcOfferOut]], dependencies=CORE)
async def my_offers(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).mine())


@router.get(
    "/placement/offers/wards", summary="Ward offers", response_model=Envelope[list[PlcOfferOut]], dependencies=CORE
)
async def ward_offers(
    request: Request, principal: Principal = Depends(WARDS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).wards())


@router.get(
    "/placement/offers/pending",
    summary="Recruiter-submitted offers awaiting confirmation",
    response_model=Envelope[list[PlcPendingOffer]],
    dependencies=CORE,
)
async def pending_offers(
    request: Request, principal: Principal = Depends(OFFER_MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).pending())


@router.post(
    "/placement/offers/pending/{application_id}/confirm",
    status_code=201,
    summary="Confirm a recruiter-submitted offer",
    response_model=Envelope[PlcOfferOut],
    dependencies=CORE,
)
async def confirm_pending(
    application_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(OFFER_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).confirm_pending(application_id), message="Offered")


@router.get("/placement/offers/{id}", summary="Offer", response_model=Envelope[PlcOfferOut], dependencies=CORE)
async def offer(
    id: uuid.UUID, request: Request, principal: Principal = Depends(OFFER_READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).get(id))


@router.post(
    "/placement/offers/{id}/decision",
    summary="Accept / decline (policy enforced)",
    response_model=Envelope[PlcOfferOut],
    dependencies=CORE,
)
async def offer_decision(
    id: uuid.UUID,
    body: PlcOfferDecision,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).decide(id, body))


@router.post(
    "/placement/offers/{id}/status",
    summary="Joined / not joined / revoked",
    response_model=Envelope[PlcOfferOut],
    dependencies=CORE,
)
async def offer_status(
    id: uuid.UUID,
    body: PlcOfferStatusUpdate,
    request: Request,
    principal: Principal = Depends(OFFER_MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).set_status(id, body))


# ---- profiles -----------------------------------------------------------------------------------------------------------
@router.get(
    "/placement/profile/me", summary="My placement profile", response_model=Envelope[PlcProfileOut], dependencies=CORE
)
async def my_profile(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).me())


@router.put(
    "/placement/profile/me",
    summary="Update my profile (academics read-only)",
    response_model=Envelope[PlcProfileOut],
    dependencies=CORE,
)
async def update_my_profile(
    body: PlcProfileIn, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).update_me(body))


@router.post(
    "/placement/profile/me/resume/render",
    summary="Render my resume (PDF via documents)",
    response_model=Envelope[dict[str, Any]],
    dependencies=RESUME,
)
async def render_resume(
    body: PlcResumeRender, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).render_resume(body), message="Rendered")


@router.post(
    "/placement/profile/me/opt-out",
    summary="Opt out / back in",
    response_model=Envelope[PlcProfileOut],
    dependencies=CORE,
)
async def opt_out(
    body: PlcOptOut, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).opt_out(body))


@router.get(
    "/placement/profiles",
    summary="Profiles (ScopeTabs)",
    response_model=Envelope[list[PlcProfileOut]],
    dependencies=CORE,
)
async def profiles(
    request: Request,
    batch_id: uuid.UUID | None = None,
    status: str | None = None,
    department_id: uuid.UUID | None = None,
    scope: str | None = None,
    q: str | None = None,
    principal: Principal = Depends(PROFILE_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ProfileService(db, principal, request)
    return _vis(await svc.list_profiles(batch_id, status, department_id, scope, q), svc)


@router.get(
    "/placement/profiles/{enrollment_id}", summary="Profile", response_model=Envelope[PlcProfileOut], dependencies=CORE
)
async def profile(
    enrollment_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(PROFILE_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).get(enrollment_id))


# ---- blacklist ----------------------------------------------------------------------------------------------------------
@router.get(
    "/placement/blacklist", summary="Blacklist", response_model=Envelope[list[PlcBlacklistOut]], dependencies=CORE
)
async def blacklist(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).list_blacklist())


@router.post(
    "/placement/blacklist",
    status_code=201,
    summary="Blacklist a student",
    response_model=Envelope[PlcBlacklistOut],
    dependencies=CORE,
)
async def add_blacklist(
    body: PlcBlacklistRequest,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).blacklist(body), message="Blacklisted")


@router.delete(
    "/placement/blacklist/{enrollment_id}",
    summary="Lift a blacklist (audited)",
    response_model=Envelope[PlcBlacklistOut],
    dependencies=CORE,
)
async def remove_blacklist(
    enrollment_id: uuid.UUID,
    request: Request,
    reason: str | None = None,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await OfferService(db, principal, request).unblacklist(enrollment_id, reason))


# ---- stats & reports ----------------------------------------------------------------------------------------------------
@router.get(
    "/placement/stats",
    summary="Placement statistics (NAAC / NIRF)",
    response_model=Envelope[PlcStats],
    dependencies=CORE,
)
async def stats(
    request: Request,
    batch_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await StatsService(db, principal, request).stats(batch_id, program_id, college_id))


@router.get(
    "/placement/stats/nirf-sheet",
    status_code=202,
    summary="NIRF placement sheet (job)",
    response_model=Envelope[PlcJobOut],
    dependencies=CORE,
)
async def nirf_sheet(
    request: Request,
    year: int | None = None,
    batch_id: uuid.UUID | None = None,
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> Any:
    StatsService(db, principal, request)._require()
    return await _job(
        db, principal, "placement.nirf_sheet", {"year": year, "batch_id": str(batch_id) if batch_id else None}
    )


@router.get(
    "/placement/reports/{kind}",
    status_code=202,
    summary="Drives / offers / internships / training report (?format=xlsx — job)",
    response_model=Envelope[PlcJobOut],
    dependencies=CORE,
)
async def report(
    kind: str,
    request: Request,
    format: str = "xlsx",
    inline: bool = False,
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> Any:
    from app.core.errors import APIError, ErrorCode

    if kind not in ("drives", "offers", "internships", "training"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
    svc = StatsService(db, principal, request)
    svc._require()
    if inline:
        content = await svc.report(kind)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="placement-{kind}.xlsx"'},
        )
    return await _job(db, principal, "placement.stats_export", {"kind": kind, "format": format})
