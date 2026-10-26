"""Alumni — Prompts/29 §29.8: self-service profile / employment / engagement / membership card {alumni.portal},
claim & OTP verification (``public_router``, ``PUBLIC_ROUTES``; tenant by institution slug, rate-limited + captcha),
coordinator profiles (ScopeTabs Department | College | All, import job, verify, merge, audited export job)
{alumni.core}, the consent-projected directory with contact relay {alumni.portal}, alumni events on the Phase 25 engine
{alumni.core}, the moderated jobs board {alumni.jobs_board} and stats. ``/alumni/me``, ``/alumni/events/me`` and
``/alumni/jobs/me`` are declared before the ``/{id}`` routes of the same prefix.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.rate_limit import rate_limited, verify_captcha
from app.db.session import get_db
from app.schemas.alumni import (
    AlmEmploymentIn,
    AlmEmploymentOut,
    AlmEngagementOut,
    AlmEventIn,
    AlmEventInvite,
    AlmEventOut,
    AlmImportReport,
    AlmInviteReport,
    AlmJobClick,
    AlmJobIn,
    AlmJobOut,
    AlmJobQueued,
    AlmProfileListItem,
    AlumniImport,
    AlumniProfileOut,
    AlumniProfileUpdate,
    AlumniStats,
    ClaimRequest,
    ClaimResponse,
    ClaimVerify,
    ClaimVerifyResponse,
    ContactRequest,
    ContactRequestOut,
    DirectoryPage,
    JobModeration,
    MergeReport,
    MergeRequest,
    VerifyDecision,
)
from app.schemas.common import Envelope
from app.services.alumni.common import AlumniBase, scope_ids
from app.services.alumni.directory_service import DirectoryService
from app.services.alumni.event_service import AlumniEventService
from app.services.alumni.jobs_service import JobsService
from app.services.alumni.profile_service import ProfileService
from app.services.alumni.stats_service import AlumniStatsService
from app.utils.response import PaginationMeta, VisibilityMeta, ok

router = APIRouter(tags=["alumni"])
public_router = APIRouter(tags=["alumni"])

A = "alumni"
SELF = any_permission_required((A, "self"))
READ = any_permission_required((A, "manage"), (A, "verify"), (A, "view_all"))
VERIFY = any_permission_required((A, "verify"), (A, "manage"))
MANAGE = any_permission_required((A, "manage"))
EXPORT = any_permission_required((A, "export"), (A, "manage"))
DIRECTORY = any_permission_required((A, "self"), (A, "view"), (A, "view_all"), ("placement", "manage"))
EVENTS = any_permission_required((A, "manage"), (A, "self"), (A, "view_all"), (A, "view"))
JOBS = any_permission_required((A, "self"), (A, "manage"), (A, "view"), (A, "view_all"), ("placement", "manage"))
LEAD = any_permission_required(("placement", "manage"))
STATS = any_permission_required((A, "view_all"), (A, "manage"))

CORE = [feature_required("alumni.core")]
PORTAL = [feature_required("alumni.core"), feature_required("alumni.portal")]
JOBS_FEAT = [feature_required("alumni.portal"), feature_required("alumni.jobs_board")]


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(AlmJobQueued(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


# ---- self ------------------------------------------------------------------------------------------------------------------
@router.get("/alumni/me", summary="My alumni profile", response_model=Envelope[AlumniProfileOut], dependencies=PORTAL)
async def me(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).me())


@router.put(
    "/alumni/me", summary="Update profile & consents", response_model=Envelope[AlumniProfileOut], dependencies=PORTAL
)
async def update_me(
    body: AlumniProfileUpdate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).update_me(body), message="Saved")


@router.get(
    "/alumni/me/employment",
    summary="My employment",
    response_model=Envelope[list[AlmEmploymentOut]],
    dependencies=PORTAL,
)
async def my_employment(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).my_employment())


@router.post(
    "/alumni/me/employment",
    status_code=201,
    summary="Add employment (a current job closes the previous one)",
    response_model=Envelope[AlmEmploymentOut],
    dependencies=PORTAL,
)
async def add_employment(
    body: AlmEmploymentIn, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).add_employment(body), message="Added")


@router.put(
    "/alumni/me/employment/{id}",
    summary="Update employment",
    response_model=Envelope[AlmEmploymentOut],
    dependencies=PORTAL,
)
async def update_employment(
    id: uuid.UUID,
    body: AlmEmploymentIn,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).update_employment(id, body))


@router.delete(
    "/alumni/me/employment/{id}", summary="Delete employment", response_model=Envelope[None], dependencies=PORTAL
)
async def delete_employment(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await ProfileService(db, principal, request).delete_employment(id)
    return ok(None, message="Deleted")


@router.get(
    "/alumni/me/engagement",
    summary="My engagement score",
    response_model=Envelope[AlmEngagementOut],
    dependencies=PORTAL,
)
async def my_engagement(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).my_engagement())


@router.get("/alumni/me/card.pdf", summary="Membership card (PDF)", dependencies=PORTAL)
async def my_card(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> Response:
    pdf, name = await ProfileService(db, principal, request).card()
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


# ---- claim (public) -----------------------------------------------------------------------------------------------------------
async def _tenant(db: AsyncSession, institution: str) -> uuid.UUID:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    for key in ("alumni.core", "alumni.portal"):
        if not await is_enabled(iid, key):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{key}' is not enabled", {"feature": key})
    return iid


@public_router.post(
    "/alumni/claim",
    summary="Claim a legacy alumni profile (registration number + year + contact on record → OTP)",
    response_model=Envelope[ClaimResponse],
    dependencies=[rate_limited("alumni_claim", limit=10, window=600)],
)
async def claim(
    body: ClaimRequest,
    request: Request,
    institution: str = Query(min_length=2, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await verify_captcha(body.captcha_token, request.client.host if request.client else None)
    iid = await _tenant(db, institution)
    return ok(await ProfileService(db, None, request, iid).claim(body), message="Code sent")


@public_router.post(
    "/alumni/claim/verify",
    summary="Verify the claim OTP",
    response_model=Envelope[ClaimVerifyResponse],
    dependencies=[rate_limited("alumni_claim_verify", limit=20, window=600)],
)
async def claim_verify(
    body: ClaimVerify,
    request: Request,
    institution: str = Query(min_length=2, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    iid = await _tenant(db, institution)
    return ok(await ProfileService(db, None, request, iid).claim_verify(body), message="Claimed")


# ---- coordinator profiles -------------------------------------------------------------------------------------------------------
@router.get(
    "/alumni/profiles",
    summary="Alumni profiles (ScopeTabs Department | College | All)",
    response_model=Envelope[list[AlmProfileListItem]],
    dependencies=CORE,
)
async def profiles(
    request: Request,
    batch: int | None = None,
    program_id: uuid.UUID | None = None,
    status: str | None = Query(None, pattern="^(verified|unverified|unclaimed|claimed|rejected)$"),
    department_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    scope: str | None = Query(None, pattern="^(self|department|college|all)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ProfileService(db, principal, request)
    items, total = await svc.list_profiles(
        batch=batch,
        program_id=program_id,
        status=status,
        department_id=department_id,
        q=q,
        scope=scope,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    tabs = ["self"]
    if scope_ids(principal, "department") or scope_ids(principal, "faculty"):
        tabs.append("department")
    if scope_ids(principal, "college"):
        tabs.append("college")
    if AlumniBase(db, principal, request).all_access():
        tabs.append("all")
    return ok(
        items,
        pagination=PaginationMeta(
            page=page, page_size=per_page, total=total, total_pages=max(1, -(-total // per_page))
        ),
        visibility=VisibilityMeta(self=True, scopes=tabs, default=tabs[-1]),
    )


@router.post(
    "/alumni/import",
    status_code=202,
    summary="Legacy alumni import (job; CSV file or rows)",
    response_model=Envelope[AlmJobQueued],
    dependencies=CORE,
)
async def import_alumni(
    body: AlumniImport, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _job(db, principal, "alumni.import", body.model_dump(mode="json"))


@router.post(
    "/alumni/import/inline",
    summary="Legacy alumni import (inline, ≤ 5,000 rows)",
    response_model=Envelope[AlmImportReport],
    dependencies=CORE,
)
async def import_inline(
    body: AlumniImport, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).import_rows(body))


@router.get(
    "/alumni/profiles/export",
    status_code=202,
    summary="Export profiles (job, audited; contacts only when consented)",
    response_model=Envelope[AlmJobQueued],
    dependencies=CORE,
)
async def export_profiles(
    scope: str | None = Query(None, pattern="^(department|college|all)$"),
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.services.alumni.common import is_auditor

    if is_auditor(principal):
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "The auditor does not export alumni contacts")
    return await _job(db, principal, "alumni.directory_export", {"scope": scope})


@router.post(
    "/alumni/profiles/merge",
    summary="Merge duplicate profiles",
    response_model=Envelope[MergeReport],
    dependencies=CORE,
)
async def merge(
    body: MergeRequest, request: Request, principal: Principal = Depends(VERIFY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).merge(body), message="Merged")


@router.post(
    "/alumni/profiles/claim-links",
    status_code=202,
    summary="Send claim links to unclaimed profiles (job)",
    response_model=Envelope[AlmJobQueued],
    dependencies=CORE,
)
async def claim_links(principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)) -> JSONResponse:
    return await _job(db, principal, "alumni.claim_links_batch", {})


@router.get(
    "/alumni/profiles/{id}", summary="Alumni profile", response_model=Envelope[AlumniProfileOut], dependencies=CORE
)
async def profile(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).get_profile(id))


@router.post(
    "/alumni/profiles/{id}/verify",
    summary="Verify / reject a claimed profile",
    response_model=Envelope[AlumniProfileOut],
    dependencies=CORE,
)
async def verify(
    id: uuid.UUID,
    body: VerifyDecision,
    request: Request,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProfileService(db, principal, request).verify(id, body))


# ---- directory -------------------------------------------------------------------------------------------------------------------
@router.get(
    "/alumni/directory",
    summary="Alumni directory (consented fields; mentor / recruiter finder)",
    response_model=Envelope[DirectoryPage],
    dependencies=[*PORTAL, rate_limited("alumni_directory", limit=60, window=60)],
)
async def directory(
    request: Request,
    q: str | None = Query(None, max_length=100),
    batch: int | None = None,
    program_id: uuid.UUID | None = None,
    city: str | None = Query(None, max_length=80),
    company: str | None = Query(None, max_length=200),
    willing_to_mentor: bool | None = None,
    willing_to_recruit: bool | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(DIRECTORY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(
        await DirectoryService(db, principal, request).search(
            q=q,
            batch=batch,
            program_id=program_id,
            city=city,
            company=company,
            willing_to_mentor=willing_to_mentor,
            willing_to_recruit=willing_to_recruit,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
    )


@router.post(
    "/alumni/directory/{id}/contact-request",
    status_code=201,
    summary="Contact request (relayed; contacts never exposed)",
    response_model=Envelope[ContactRequestOut],
    dependencies=[*PORTAL, rate_limited("alumni_contact", limit=10, window=3600)],
)
async def contact(
    id: uuid.UUID,
    body: ContactRequest,
    request: Request,
    principal: Principal = Depends(DIRECTORY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DirectoryService(db, principal, request).contact(id, body), message="Sent")


# ---- events -------------------------------------------------------------------------------------------------------------------------
@router.get("/alumni/events", summary="Alumni events", response_model=Envelope[list[AlmEventOut]], dependencies=CORE)
async def events(
    request: Request,
    upcoming: bool | None = None,
    principal: Principal = Depends(EVENTS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AlumniEventService(db, principal, request).list_events(upcoming))


@router.post(
    "/alumni/events",
    status_code=201,
    summary="Create an alumni event (on the Events engine)",
    response_model=Envelope[AlmEventOut],
    dependencies=CORE,
)
async def create_event(
    body: AlmEventIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AlumniEventService(db, principal, request).create(body), message="Created")


@router.get(
    "/alumni/events/me", summary="My alumni events", response_model=Envelope[list[AlmEventOut]], dependencies=CORE
)
async def my_events(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AlumniEventService(db, principal, request).mine())


@router.get("/alumni/events/{id}", summary="Alumni event", response_model=Envelope[AlmEventOut], dependencies=CORE)
async def event(
    id: uuid.UUID, request: Request, principal: Principal = Depends(EVENTS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AlumniEventService(db, principal, request).get(id))


@router.post(
    "/alumni/events/{id}/invite",
    summary="Invite a segment (batches / programmes / chapter / city)",
    response_model=Envelope[AlmInviteReport],
    dependencies=CORE,
)
async def invite(
    id: uuid.UUID,
    body: AlmEventInvite,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AlumniEventService(db, principal, request).invite(id, body), message="Invited")


# ---- jobs ---------------------------------------------------------------------------------------------------------------------------
@router.get(
    "/alumni/jobs", summary="Alumni jobs board", response_model=Envelope[list[AlmJobOut]], dependencies=JOBS_FEAT
)
async def jobs(
    request: Request,
    status: str | None = Query(None, pattern="^(pending|approved|rejected|expired)$"),
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(JOBS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await JobsService(db, principal, request).list_jobs(status, q))


@router.post(
    "/alumni/jobs",
    status_code=201,
    summary="Post a job (verified alumni; moderated)",
    response_model=Envelope[AlmJobOut],
    dependencies=JOBS_FEAT,
)
async def post_job(
    body: AlmJobIn,
    request: Request,
    principal: Principal = Depends(any_permission_required((A, "self"), (A, "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await JobsService(db, principal, request).create(body), message="Posted")


@router.get("/alumni/jobs/me", summary="My job posts", response_model=Envelope[list[AlmJobOut]], dependencies=JOBS_FEAT)
async def my_jobs(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await JobsService(db, principal, request).mine())


@router.get("/alumni/jobs/{id}", summary="Job post", response_model=Envelope[AlmJobOut], dependencies=JOBS_FEAT)
async def job(
    id: uuid.UUID, request: Request, principal: Principal = Depends(JOBS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await JobsService(db, principal, request).get(id))


@router.post(
    "/alumni/jobs/{id}/moderate", summary="Approve / reject", response_model=Envelope[AlmJobOut], dependencies=JOBS_FEAT
)
async def moderate(
    id: uuid.UUID,
    body: JobModeration,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await JobsService(db, principal, request).moderate(id, body))


@router.post(
    "/alumni/jobs/{id}/click",
    summary="Track an apply click",
    response_model=Envelope[AlmJobClick],
    dependencies=JOBS_FEAT,
)
async def click(
    id: uuid.UUID, request: Request, principal: Principal = Depends(JOBS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await JobsService(db, principal, request).click(id))


@router.post(
    "/alumni/jobs/{id}/lead",
    summary="Convert to a placement company lead",
    response_model=Envelope[AlmJobOut],
    dependencies=JOBS_FEAT,
)
async def lead(
    id: uuid.UUID, request: Request, principal: Principal = Depends(LEAD), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await JobsService(db, principal, request).to_lead(id), message="Lead created")


# ---- stats ------------------------------------------------------------------------------------------------------------------------------
@router.get("/alumni/stats", summary="Alumni stats (NAAC 5.4)", response_model=Envelope[AlumniStats], dependencies=CORE)
async def stats(
    request: Request,
    batch: int | None = None,
    program_id: uuid.UUID | None = None,
    college_id: uuid.UUID | None = None,
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AlumniStatsService(db, principal, request).stats(batch, program_id, college_id))
