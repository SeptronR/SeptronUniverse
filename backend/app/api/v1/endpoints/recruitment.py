"""Recruitment — Prompts/06 §06.8 (router included with ``feature_required("hr.recruitment")``) and the public
careers page (``PUBLIC_ROUTES``): ``GET /public/careers?institution=<slug>`` lists open postings and
``POST /public/careers/{posting_id}/apply`` files an application — the tenant is the slug's (or the posting's)
institution, pinned for RLS here, and {hr.recruitment} is checked by the tenant dependency (like the catalogue)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import is_enabled
from app.core.idempotency import idempotency_key, store
from app.db.session import bind_tenant, get_db, set_tenant
from app.enums.hr import ApplicationStatus, PostingStatus
from app.models.platform import Institution
from app.repositories.institution_repository import InstitutionRepository
from app.repositories.recruitment_repository import posting_institution
from app.schemas.common import Envelope
from app.schemas.recruitment import (
    JobApplicationIn,
    JobApplicationOut,
    JobPostingIn,
    JobPostingOut,
    JoinIn,
    OfferIn,
    PanelIn,
    PanelOut,
    PublicApplicationResult,
    PublicPostingOut,
    ScoreIn,
    ScoreOut,
    ScreenIn,
    ShortlistIn,
    StatusChangeResult,
)
from app.services.recruitment_service import RecruitmentService
from app.utils.pagination import PageParams, page_params
from app.utils.response import ok

router = APIRouter(tags=["hr"])
public_router = APIRouter(prefix="/public/careers", tags=["public"])

FEATURE = "hr.recruitment"
RECRUIT = permission_required("hr", "recruitment")
RECRUIT_READ = any_permission_required(("hr", "recruitment"), ("recruitment", "view"), ("recruitment", "view_all"))


# ---- postings -------------------------------------------------------------------------------------------------------
@router.get("/recruitment/postings", summary="Job postings", response_model=Envelope[list[JobPostingOut]])
async def list_postings(
    request: Request,
    params: PageParams = Depends(page_params),
    status: PostingStatus | None = None,
    department_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    principal: Principal = Depends(RECRUIT_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, pagination = await RecruitmentService(db, principal, request).list_postings(
        params, status.value if status else None, department_id, q
    )
    return ok(rows, pagination=pagination)


@router.post(
    "/recruitment/postings",
    status_code=201,
    summary="Create a job posting (reservation roster validated)",
    response_model=Envelope[JobPostingOut],
)
async def create_posting(
    body: JobPostingIn,
    request: Request,
    principal: Principal = Depends(RECRUIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).create_posting(body), message="Posting created")


@router.put("/recruitment/postings/{id}", summary="Update a job posting", response_model=Envelope[JobPostingOut])
async def update_posting(
    id: uuid.UUID,
    body: JobPostingIn,
    request: Request,
    principal: Principal = Depends(RECRUIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).update_posting(id, body))


def _posting_action_route(action: str) -> None:
    @router.post(
        f"/recruitment/postings/{{id}}/{action}",
        summary=f"{action.title()} a posting",
        response_model=Envelope[JobPostingOut],
    )
    async def _route(
        id: uuid.UUID,
        request: Request,
        principal: Principal = Depends(RECRUIT),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        return ok(await RecruitmentService(db, principal, request).set_posting_status(id, action))

    _route.__name__ = f"posting_{action}"


for _action in ("publish", "close", "cancel"):
    _posting_action_route(_action)


@router.get(
    "/recruitment/postings/{id}/applications",
    summary="Applications of a posting",
    response_model=Envelope[list[JobApplicationOut]],
)
async def list_applications(
    id: uuid.UUID,
    request: Request,
    status: ApplicationStatus | None = None,
    principal: Principal = Depends(RECRUIT_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).applications_for(id, status.value if status else None))


# ---- pipeline -------------------------------------------------------------------------------------------------------
@router.post(
    "/recruitment/applications/{id}/screen",
    summary="Screen (score) an application",
    response_model=Envelope[StatusChangeResult],
)
async def screen(
    id: uuid.UUID,
    body: ScreenIn,
    request: Request,
    principal: Principal = Depends(RECRUIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).screen(id, body))


@router.post(
    "/recruitment/applications/{id}/shortlist",
    summary="Shortlist (rule or manual ids) within the application's posting",
    response_model=Envelope[StatusChangeResult],
)
async def shortlist(
    id: uuid.UUID,
    request: Request,
    body: ShortlistIn | None = None,
    principal: Principal = Depends(RECRUIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).shortlist(id, body or ShortlistIn()))


@router.post(
    "/recruitment/applications/{id}/select", summary="Select a candidate", response_model=Envelope[StatusChangeResult]
)
async def select_candidate(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECRUIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).select(id))


@router.post(
    "/recruitment/applications/{id}/offer", summary="Record the offer", response_model=Envelope[StatusChangeResult]
)
async def offer(
    id: uuid.UUID,
    request: Request,
    body: OfferIn | None = None,
    principal: Principal = Depends(RECRUIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).offer(id, body or OfferIn()))


@router.post(
    "/recruitment/applications/{id}/join",
    summary="Joining — creates and links the staff record",
    response_model=Envelope[StatusChangeResult],
)
async def join(
    id: uuid.UUID,
    body: JoinIn,
    request: Request,
    principal: Principal = Depends(RECRUIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).join(id, body), message="Joined — staff record created")


@router.post(
    "/recruitment/applications/{id}/reject",
    summary="Reject an application",
    response_model=Envelope[StatusChangeResult],
)
async def reject(
    id: uuid.UUID, request: Request, principal: Principal = Depends(RECRUIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).reject(id))


# ---- panels ---------------------------------------------------------------------------------------------------------
@router.get(
    "/recruitment/postings/{id}/panels",
    summary="Interview panels of a posting",
    response_model=Envelope[list[PanelOut]],
)
async def list_panels(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required(("hr", "recruitment"), ("hr", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).list_panels(id))


@router.post(
    "/recruitment/postings/{id}/panels",
    status_code=201,
    summary="Create an interview panel",
    response_model=Envelope[PanelOut],
)
async def create_panel(
    id: uuid.UUID,
    body: PanelIn,
    request: Request,
    principal: Principal = Depends(RECRUIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).create_panel(id, body), message="Panel created")


@router.post(
    "/recruitment/panels/{id}/scores",
    summary="Record interview scores (panel members / HR)",
    response_model=Envelope[ScoreOut],
)
async def score(
    id: uuid.UUID,
    body: ScoreIn,
    request: Request,
    principal: Principal = Depends(any_permission_required(("hr", "recruitment"), ("hr", "view_all"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, principal, request).score(id, body))


# ---- public careers -------------------------------------------------------------------------------------------------
async def _pin(db: AsyncSession, inst: Institution | None) -> Institution:
    if inst is None or inst.status != "active":
        raise APIError(404, ErrorCode.NOT_FOUND, "Institution not found")
    bind_tenant(db, inst.id)
    await set_tenant(db, inst.id)
    if not await is_enabled(inst.id, FEATURE):
        raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{FEATURE}' is not enabled", {"feature": FEATURE})
    return inst


async def careers_tenant(
    request: Request,
    institution: str | None = Query(default=None, max_length=60, description="institution slug"),
    db: AsyncSession = Depends(get_db),
) -> Institution:
    repo = InstitutionRepository(db)
    slug = institution or getattr(request.state, "institution_slug", None)
    row = await repo.by_slug(slug) if slug else None
    if row is None and getattr(request.state, "institution_id", None):
        try:
            row = await repo.get(uuid.UUID(str(request.state.institution_id)))
        except ValueError:
            row = None
    return await _pin(db, row)


async def posting_tenant(posting_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Institution:
    iid = await posting_institution(posting_id)
    if iid is None:
        raise APIError(404, ErrorCode.NOT_FOUND, "Job posting not found")
    return await _pin(db, await InstitutionRepository(db).get(iid))


careers_tenant.__feature_key__ = FEATURE  # type: ignore[attr-defined]
posting_tenant.__feature_key__ = FEATURE  # type: ignore[attr-defined]


@public_router.get(
    "", summary="Open job postings (public careers page)", response_model=Envelope[list[PublicPostingOut]]
)
async def public_postings(
    inst: Institution = Depends(careers_tenant), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecruitmentService(db, None, institution_id=inst.id).public_postings())


@public_router.post(
    "/{posting_id}/apply",
    status_code=201,
    summary="Apply for a posting (public)",
    response_model=Envelope[PublicApplicationResult],
)
async def public_apply(
    posting_id: uuid.UUID,
    body: JobApplicationIn,
    request: Request,
    _idem: str | None = Depends(idempotency_key),
    inst: Institution = Depends(posting_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    response = ok(
        await RecruitmentService(db, None, request, institution_id=inst.id).public_apply(posting_id, body),
        message="Application received",
    )
    await store(request, response, db, 201)
    return response
