"""Research & faculty development — Prompts/30 §30.8: publications (ScopeTabs Mine | Department | All, imports,
two-level verification, claim co-authorship) {research.publications}, patents {research.patents}, funded projects
(sanction workflow → Phase 23 grant ledger, expense requests, reports, staff) {research.projects_grants}, consultancy
{research.consultancy}, ethics committees {research.ethics_committee}, incentives {research.seed_grants_incentives},
FDP / awards {research.fdp}, MoUs / collaborations {research.mous_collaborations}, start-ups {research.incubation},
API score {research.api_score}, research profiles and stats / reports / NAAC evidence packs. ``/me`` routes are
declared before the ``/{id}`` routes of the same prefix.
"""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.research import (
    ApiRankingRow,
    ApiScoreOut,
    ApiScoreRequest,
    AwardIn,
    AwardOut,
    ClaimCoauthor,
    CollaborationIn,
    CollaborationOut,
    ConsultancyIn,
    ConsultancyOut,
    ConsultancyReceipt,
    ConsultancyShares,
    ConsultancyUpdate,
    EthicsAmend,
    EthicsApplication,
    EthicsApplicationOut,
    EthicsCommitteeIn,
    EthicsCommitteeOut,
    EthicsReview,
    FdpComplianceRow,
    FdpIn,
    FdpOut,
    FdpUpdate,
    ImportApply,
    ImportPreview,
    ImportResult,
    IncentiveDecision,
    IncentiveDisburse,
    IncentiveOut,
    IncentiveRequest,
    IncentiveSlabs,
    MouActivityRow,
    MouIn,
    MouOut,
    MouSign,
    MouUpdate,
    PatentIn,
    PatentOut,
    PatentUpdate,
    ProjectAction,
    ProjectExpenseRequest,
    ProjectLedgerOut,
    ProjectReport,
    ProjectStaffIn,
    PublicationImport,
    PublicationIn,
    PublicationOut,
    PublicationUpdate,
    ResearchProfileOut,
    ResearchStats,
    RschJobQueued,
    RschProjectIn,
    RschProjectOut,
    RschProjectUpdate,
    RschVerifyRequest,
    RschVerifyResult,
    StartupIn,
    StartupOut,
    StartupStageIn,
    StartupUpdate,
)
from app.services.research.common import ResearchBase
from app.services.research.consultancy_service import ConsultancyService
from app.services.research.ethics_service import EthicsService
from app.services.research.incentive_service import IncentiveService
from app.services.research.mou_service import MouService
from app.services.research.project_service import ProjectService
from app.services.research.publication_service import PublicationService
from app.services.research.record_service import RecordService
from app.services.research.score_service import ScoreService
from app.utils.response import PaginationMeta, VisibilityMeta, ok

router = APIRouter(tags=["research"])

R = "research"
VIEW = any_permission_required((R, "view"), (R, "view_all"), (R, "manage"), (R, "verify"))
WRITE = any_permission_required((R, "manage"))
VERIFY = any_permission_required((R, "verify"), (R, "manage"))
MONEY = any_permission_required(
    (R, "view"), (R, "view_all"), (R, "manage"), ("accounting", "view_all"), ("accounting", "manage")
)
MONEY_WRITE = any_permission_required((R, "manage"), ("accounting", "manage"), ("accounting", "post"))
ETHICS = any_permission_required((R, "ethics"), (R, "view"), (R, "view_all"), (R, "manage"))
INCENTIVES = any_permission_required(
    (R, "incentives"), (R, "view"), (R, "view_all"), (R, "manage"), ("accounting", "manage")
)
MOUS = any_permission_required((R, "mous"), (R, "view"), (R, "view_all"), (R, "manage"))
INCUBATION = any_permission_required((R, "incubation"), (R, "view"), (R, "view_all"), (R, "manage"))
API_READ = any_permission_required((R, "view"), (R, "view_all"), (R, "manage"), ("hr", "view_all"))
STATS = any_permission_required((R, "view_all"), ("reports", "export"))
EXPORT = any_permission_required((R, "export"), (R, "view_all"), ("reports", "export"))

PUBS = [feature_required("research.publications")]
PATENTS = [feature_required("research.patents")]
PROJECTS = [feature_required("research.projects_grants")]
CONSULT = [feature_required("research.consultancy")]
ETHICS_F = [feature_required("research.ethics_committee")]
INCENT_F = [feature_required("research.seed_grants_incentives")]
FDP = [feature_required("research.fdp")]
MOU_F = [feature_required("research.mous_collaborations")]
INCUB_F = [feature_required("research.incubation")]
API_F = [feature_required("research.api_score")]

SCOPE = Query(None, pattern="^(self|mine|own|department|college|all)$")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(RschJobQueued(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


def _vis(svc: ResearchBase, own: bool = False) -> VisibilityMeta:
    v = svc.visibility(own_tab=own)
    return VisibilityMeta(self=v["self"], scopes=v["scopes"], default=v["default"])


def _page(page: int, per_page: int, total: int) -> PaginationMeta:
    return PaginationMeta(page=page, page_size=per_page, total=total, total_pages=max(1, -(-total // per_page)))


# ---- publications -----------------------------------------------------------------------------------------------------
@router.get(
    "/research/publications",
    summary="Publications (ScopeTabs Mine | Department | All)",
    response_model=Envelope[list[PublicationOut]],
    dependencies=PUBS,
)
async def publications(
    request: Request,
    staff_id: str | None = None,
    department_id: uuid.UUID | None = None,
    indexing: str | None = Query(None, pattern="^(sci|scie|scopus|wos|ugc_care|other|none)$"),
    year: int | None = None,
    verified: bool | None = None,
    q: str | None = Query(None, max_length=100),
    scope: str | None = SCOPE,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = PublicationService(db, principal, request)
    items, total = await svc.query(
        staff_id=await svc.resolve_staff_param(staff_id),
        department_id=department_id,
        indexing=indexing,
        year=year,
        verified=verified,
        q=q,
        scope=scope,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return ok(items, pagination=_page(page, per_page, total), visibility=_vis(svc))


@router.post(
    "/research/publications",
    status_code=201,
    summary="Add a publication (409 DUPLICATE_DOI with a claim-coauthor hint)",
    response_model=Envelope[PublicationOut],
    dependencies=PUBS,
)
async def create_publication(
    body: PublicationIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PublicationService(db, principal, request).create(body), message="Added")


@router.post(
    "/research/publications/import/preview",
    summary="Import preview (Crossref / Scopus / ORCID / BibTeX / CSV → matches, duplicates, new)",
    response_model=Envelope[ImportPreview],
    dependencies=PUBS,
)
async def import_preview(
    body: PublicationImport,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PublicationService(db, principal, request).preview(body))


@router.post(
    "/research/publications/import/apply",
    status_code=202,
    summary="Apply an import preview (job; ?inline=true applies at once)",
    response_model=Envelope[ImportResult],
    dependencies=PUBS,
)
async def import_apply(
    body: ImportApply,
    request: Request,
    inline: bool = False,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if inline:
        return ok(await PublicationService(db, principal, request).apply(body), message="Imported")
    return await _job(db, principal, "research.import_publications", body.model_dump(mode="json"))


@router.post(
    "/research/publications/verify",
    summary="Bulk verify (HOD first level → research cell final) / reject with remarks",
    response_model=Envelope[RschVerifyResult],
    dependencies=PUBS,
)
async def verify_publications(
    body: RschVerifyRequest,
    request: Request,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PublicationService(db, principal, request).verify(body))


@router.post(
    "/research/publications/sync-citations",
    status_code=202,
    summary="Citations refresh (job)",
    response_model=Envelope[RschJobQueued],
    dependencies=PUBS,
)
async def sync_citations(
    staff_id: uuid.UUID | None = None, principal: Principal = Depends(VERIFY), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    return await _job(db, principal, "research.sync_citations", {"staff_id": str(staff_id) if staff_id else None})


@router.get(
    "/research/publications/{id}",
    summary="Publication",
    response_model=Envelope[PublicationOut],
    dependencies=PUBS,
)
async def publication(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PublicationService(db, principal, request).get(id))


@router.put(
    "/research/publications/{id}",
    summary="Edit (authors until verified — 403 LOCKED after; research cell any time)",
    response_model=Envelope[PublicationOut],
    dependencies=PUBS,
)
async def update_publication(
    id: uuid.UUID,
    body: PublicationUpdate,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PublicationService(db, principal, request).update(id, body), message="Saved")


@router.delete("/research/publications/{id}", summary="Delete", response_model=Envelope[None], dependencies=PUBS)
async def delete_publication(
    id: uuid.UUID, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await PublicationService(db, principal, request).delete(id)
    return ok(None, message="Deleted")


@router.post(
    "/research/publications/{id}/claim-coauthor",
    summary="Claim co-authorship of an existing record",
    response_model=Envelope[PublicationOut],
    dependencies=PUBS,
)
async def claim_coauthor(
    id: uuid.UUID,
    request: Request,
    body: ClaimCoauthor | None = None,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PublicationService(db, principal, request).claim(id, body or ClaimCoauthor()), message="Claimed")


# ---- patents ------------------------------------------------------------------------------------------------------------
@router.get("/research/patents", summary="Patents", response_model=Envelope[list[PatentOut]], dependencies=PATENTS)
async def patents(
    request: Request,
    status: str | None = Query(None, pattern="^(filed|published|granted|commercialised)$"),
    staff_id: str | None = None,
    scope: str | None = SCOPE,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RecordService(db, principal, request)
    rows = await svc.patents(status=status, staff_id=await svc.resolve_staff_param(staff_id), scope=scope)
    return ok(rows, visibility=_vis(svc))


@router.post(
    "/research/patents",
    status_code=201,
    summary="Record a patent",
    response_model=Envelope[PatentOut],
    dependencies=PATENTS,
)
async def create_patent(
    body: PatentIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecordService(db, principal, request).create_patent(body), message="Recorded")


@router.get("/research/patents/{id}", summary="Patent", response_model=Envelope[PatentOut], dependencies=PATENTS)
async def patent(
    id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = RecordService(db, principal, request)
    return ok((await svc.patent_outs([await svc.patent_row(id)]))[0])


@router.put(
    "/research/patents/{id}",
    summary="Update / advance (filed → published → granted → commercialised; backwards → 409)",
    response_model=Envelope[PatentOut],
    dependencies=PATENTS,
)
async def update_patent(
    id: uuid.UUID,
    body: PatentUpdate,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordService(db, principal, request).update_patent(id, body), message="Saved")


# ---- projects -----------------------------------------------------------------------------------------------------------
@router.get(
    "/research/projects/me",
    summary="My projects (PI / co-PI)",
    response_model=Envelope[list[RschProjectOut]],
    dependencies=PROJECTS,
)
async def my_projects(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).mine())


@router.get(
    "/research/projects",
    summary="Funded projects (Own | Department | All)",
    response_model=Envelope[list[RschProjectOut]],
    dependencies=PROJECTS,
)
async def projects(
    request: Request,
    status: str | None = Query(None, pattern="^(applied|sanctioned|ongoing|completed|closed)$"),
    agency: str | None = Query(None, max_length=100),
    department_id: uuid.UUID | None = None,
    scope: str | None = SCOPE,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(MONEY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ProjectService(db, principal, request)
    items, total = await svc.query(
        status=status,
        agency=agency,
        department_id=department_id,
        scope=scope,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return ok(items, pagination=_page(page, per_page, total), visibility=_vis(svc, own=True))


@router.post(
    "/research/projects",
    status_code=201,
    summary="Apply (proposal record → applied)",
    response_model=Envelope[RschProjectOut],
    dependencies=PROJECTS,
)
async def create_project(
    body: RschProjectIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).create(body), message="Applied")


@router.get(
    "/research/projects/{id}", summary="Project", response_model=Envelope[RschProjectOut], dependencies=PROJECTS
)
async def project(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MONEY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).get(id))


@router.put(
    "/research/projects/{id}", summary="Edit project", response_model=Envelope[RschProjectOut], dependencies=PROJECTS
)
async def update_project(
    id: uuid.UUID,
    body: RschProjectUpdate,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).update(id, body), message="Saved")


@router.post(
    "/research/projects/{id}/action",
    summary="submit | sanction (research cell → principal workflow) | start | complete | close",
    response_model=Envelope[RschProjectOut],
    dependencies=PROJECTS,
)
async def project_action(
    id: uuid.UUID,
    body: ProjectAction,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).action(id, body))


@router.get(
    "/research/projects/{id}/ledger",
    summary="Grant ledger summary (Phase 23)",
    response_model=Envelope[ProjectLedgerOut],
    dependencies=PROJECTS,
)
async def project_ledger(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MONEY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).ledger(id))


@router.post(
    "/research/projects/{id}/expense-requests",
    status_code=201,
    summary="Expense request (via=indent → Phase 22 indent; via=direct → Phase 23 grant expense)",
    response_model=Envelope[RschProjectOut],
    dependencies=PROJECTS,
)
async def project_expense(
    id: uuid.UUID,
    body: ProjectExpenseRequest,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).expense(id, body), message="Requested")


@router.get(
    "/research/projects/{id}/reports",
    summary="Progress reports",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=PROJECTS,
)
async def project_reports(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MONEY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).reports(id))


@router.post(
    "/research/projects/{id}/reports",
    status_code=201,
    summary="Upload a progress report",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=PROJECTS,
)
async def add_project_report(
    id: uuid.UUID,
    body: ProjectReport,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).add_report(id, body), message="Uploaded")


@router.post(
    "/research/projects/{id}/staff",
    status_code=201,
    summary="Add project staff (JRF / SRF / RA)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=PROJECTS,
)
async def add_project_staff(
    id: uuid.UUID,
    body: ProjectStaffIn,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ProjectService(db, principal, request).add_staff(id, body), message="Added")


# ---- consultancy --------------------------------------------------------------------------------------------------------
@router.get(
    "/research/consultancies",
    summary="Consultancy agreements",
    response_model=Envelope[list[ConsultancyOut]],
    dependencies=CONSULT,
)
async def consultancies(
    request: Request,
    staff_id: str | None = None,
    status: str | None = Query(None, pattern="^(ongoing|completed|cancelled)$"),
    scope: str | None = SCOPE,
    principal: Principal = Depends(MONEY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ConsultancyService(db, principal, request)
    rows = await svc.query(staff_id=await svc.resolve_staff_param(staff_id), status=status, scope=scope)
    return ok(rows, visibility=_vis(svc))


@router.post(
    "/research/consultancies",
    status_code=201,
    summary="Record a consultancy (institution share auto from the setting)",
    response_model=Envelope[ConsultancyOut],
    dependencies=CONSULT,
)
async def create_consultancy(
    body: ConsultancyIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConsultancyService(db, principal, request).create(body), message="Recorded")


@router.put(
    "/research/consultancies/{id}",
    summary="Edit (share override needs the research cell)",
    response_model=Envelope[ConsultancyOut],
    dependencies=CONSULT,
)
async def update_consultancy(
    id: uuid.UUID,
    body: ConsultancyUpdate,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConsultancyService(db, principal, request).update(id, body), message="Saved")


@router.post(
    "/research/consultancies/{id}/receipts",
    status_code=201,
    summary="Receipt through a Phase 12 invoice (payer company, source consultancy)",
    response_model=Envelope[ConsultancyOut],
    dependencies=CONSULT,
)
async def consultancy_receipt(
    id: uuid.UUID,
    body: ConsultancyReceipt,
    request: Request,
    principal: Principal = Depends(MONEY_WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConsultancyService(db, principal, request).receipt(id, body), message="Invoiced")


@router.get(
    "/research/consultancies/{id}/shares",
    summary="Institution / faculty share split",
    response_model=Envelope[ConsultancyShares],
    dependencies=CONSULT,
)
async def consultancy_shares(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MONEY), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ConsultancyService(db, principal, request).shares(id))


# ---- ethics -------------------------------------------------------------------------------------------------------------
@router.get(
    "/research/ethics/committees",
    summary="Ethics committees (IEC / IAEC / IBSC)",
    response_model=Envelope[list[EthicsCommitteeOut]],
    dependencies=ETHICS_F,
)
async def ethics_committees(
    request: Request, principal: Principal = Depends(ETHICS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EthicsService(db, principal, request).committees())


@router.post(
    "/research/ethics/committees",
    status_code=201,
    summary="Constitute an ethics committee (bound to a Phase 33 committee)",
    response_model=Envelope[EthicsCommitteeOut],
    dependencies=ETHICS_F,
)
async def create_ethics_committee(
    body: EthicsCommitteeIn,
    request: Request,
    principal: Principal = Depends(any_permission_required((R, "ethics"), (R, "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EthicsService(db, principal, request).create_committee(body), message="Created")


@router.get(
    "/research/ethics/applications",
    summary="Ethics applications (own / committee / secretariat)",
    response_model=Envelope[list[EthicsApplicationOut]],
    dependencies=ETHICS_F,
)
async def ethics_applications(
    request: Request,
    committee_id: uuid.UUID | None = None,
    status: str | None = Query(None, pattern="^(pending|approved|revise|rejected)$"),
    principal: Principal = Depends(ETHICS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EthicsService(db, principal, request).applications(committee_id=committee_id, status=status))


@router.post(
    "/research/ethics/applications",
    status_code=201,
    summary="Submit a protocol (→ research.ethics_review)",
    response_model=Envelope[EthicsApplicationOut],
    dependencies=ETHICS_F,
)
async def apply_ethics(
    body: EthicsApplication,
    request: Request,
    principal: Principal = Depends(ETHICS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EthicsService(db, principal, request).apply(body), message="Submitted")


@router.get(
    "/research/ethics/applications/{id}",
    summary="Ethics application",
    response_model=Envelope[EthicsApplicationOut],
    dependencies=ETHICS_F,
)
async def ethics_application(
    id: uuid.UUID, request: Request, principal: Principal = Depends(ETHICS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EthicsService(db, principal, request).get(id))


@router.post(
    "/research/ethics/applications/{id}/review",
    summary="Member review",
    response_model=Envelope[EthicsApplicationOut],
    dependencies=ETHICS_F,
)
async def review_ethics(
    id: uuid.UUID,
    body: EthicsReview,
    request: Request,
    principal: Principal = Depends(ETHICS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EthicsService(db, principal, request).review(id, body), message="Reviewed")


@router.post(
    "/research/ethics/applications/{id}/decide",
    summary="Chair decision (approved with approval_no / validity, revise, rejected)",
    response_model=Envelope[EthicsApplicationOut],
    dependencies=ETHICS_F,
)
async def decide_ethics(
    id: uuid.UUID,
    body: EthicsReview,
    request: Request,
    principal: Principal = Depends(ETHICS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EthicsService(db, principal, request).decide(id, body), message="Decided")


@router.post(
    "/research/ethics/approvals/{id}/{kind}",
    summary="Amendment / renewal / adverse event",
    response_model=Envelope[EthicsApplicationOut],
    dependencies=ETHICS_F,
)
async def amend_ethics(
    id: uuid.UUID,
    kind: str,
    body: EthicsAmend,
    request: Request,
    principal: Principal = Depends(ETHICS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if kind not in ("amend", "renew", "adverse-event") or kind != body.kind:
        raise APIError(422, ErrorCode.VALIDATION, "kind must match the path (amend | renew | adverse-event)")
    return ok(await EthicsService(db, principal, request).amend(id, body), message="Recorded")


# ---- incentives ---------------------------------------------------------------------------------------------------------
@router.get(
    "/research/incentives/slabs",
    summary="Incentive slabs and caps",
    response_model=Envelope[IncentiveSlabs],
    dependencies=INCENT_F,
)
async def incentive_slabs(
    request: Request, principal: Principal = Depends(INCENTIVES), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IncentiveService(db, principal, request).slabs())


@router.get(
    "/research/incentives/me",
    summary="My incentive requests",
    response_model=Envelope[list[IncentiveOut]],
    dependencies=INCENT_F,
)
async def my_incentives(
    request: Request, principal: Principal = Depends(INCENTIVES), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IncentiveService(db, principal, request).mine())


@router.get(
    "/research/incentives",
    summary="Incentive requests (Mine | Department | All)",
    response_model=Envelope[list[IncentiveOut]],
    dependencies=INCENT_F,
)
async def incentives(
    request: Request,
    status: str | None = Query(None, pattern="^(requested|approved|disbursed|rejected)$"),
    incentive_type: str | None = Query(
        None, pattern="^(seed_grant|publication_incentive|travel_grant|patent_filing_support)$"
    ),
    scope: str | None = SCOPE,
    principal: Principal = Depends(INCENTIVES),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = IncentiveService(db, principal, request)
    return ok(await svc.query(status=status, incentive_type=incentive_type, scope=scope), visibility=_vis(svc))


@router.post(
    "/research/incentives",
    status_code=201,
    summary="Request an incentive (→ research.incentive)",
    response_model=Envelope[IncentiveOut],
    dependencies=INCENT_F,
)
async def request_incentive(
    body: IncentiveRequest, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IncentiveService(db, principal, request).submit(body), message="Requested")


@router.get(
    "/research/incentives/{id}",
    summary="Incentive request",
    response_model=Envelope[IncentiveOut],
    dependencies=INCENT_F,
)
async def incentive(
    id: uuid.UUID, request: Request, principal: Principal = Depends(INCENTIVES), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await IncentiveService(db, principal, request).get(id))


@router.post(
    "/research/incentives/{id}/decide",
    summary="Recommend / approve / reject the caller's open step",
    response_model=Envelope[IncentiveOut],
    dependencies=INCENT_F,
)
async def decide_incentive(
    id: uuid.UUID,
    body: IncentiveDecision,
    request: Request,
    principal: Principal = Depends(INCENTIVES),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await IncentiveService(db, principal, request).decide(id, body))


@router.post(
    "/research/incentives/{id}/disburse",
    summary="Disburse (payroll earning line or Phase 23 expense)",
    response_model=Envelope[IncentiveOut],
    dependencies=INCENT_F,
)
async def disburse_incentive(
    id: uuid.UUID,
    body: IncentiveDisburse,
    request: Request,
    principal: Principal = Depends(any_permission_required((R, "incentives"), ("accounting", "post"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await IncentiveService(db, principal, request).disburse(id, body), message="Disbursed")


# ---- FDP / awards -------------------------------------------------------------------------------------------------------
@router.get("/research/fdp", summary="FDP records", response_model=Envelope[list[FdpOut]], dependencies=FDP)
async def fdps(
    request: Request,
    staff_id: str | None = None,
    year: int | None = None,
    role: str | None = Query(None, pattern="^(attended|organised|resource_person)$"),
    scope: str | None = SCOPE,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RecordService(db, principal, request)
    rows = await svc.fdps(staff_id=await svc.resolve_staff_param(staff_id), year=year, role=role, scope=scope)
    return ok(rows, visibility=_vis(svc))


@router.post(
    "/research/fdp", status_code=201, summary="Add an FDP record", response_model=Envelope[FdpOut], dependencies=FDP
)
async def create_fdp(
    body: FdpIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecordService(db, principal, request).create_fdp(body), message="Recorded")


@router.get(
    "/research/fdp/compliance",
    summary="Annual FDP hours vs target",
    response_model=Envelope[list[FdpComplianceRow]],
    dependencies=FDP,
)
async def fdp_compliance(
    request: Request,
    year: int = Query(..., ge=2000, le=2100),
    department_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordService(db, principal, request).compliance(year, department_id))


@router.put("/research/fdp/{id}", summary="Edit an FDP record", response_model=Envelope[FdpOut], dependencies=FDP)
async def update_fdp(
    id: uuid.UUID,
    body: FdpUpdate,
    request: Request,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordService(db, principal, request).update_fdp(id, body), message="Saved")


@router.get("/research/awards", summary="Awards", response_model=Envelope[list[AwardOut]], dependencies=FDP)
async def awards(
    request: Request,
    year: int | None = None,
    scope: str | None = SCOPE,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = RecordService(db, principal, request)
    return ok(await svc.awards(year=year, scope=scope), visibility=_vis(svc))


@router.post(
    "/research/awards", status_code=201, summary="Record an award", response_model=Envelope[AwardOut], dependencies=FDP
)
async def create_award(
    body: AwardIn, request: Request, principal: Principal = Depends(WRITE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await RecordService(db, principal, request).create_award(body), message="Recorded")


@router.post(
    "/research/awards/{id}/verify", summary="Verify an award", response_model=Envelope[AwardOut], dependencies=FDP
)
async def verify_award(
    id: uuid.UUID,
    request: Request,
    approve: bool = True,
    principal: Principal = Depends(VERIFY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await RecordService(db, principal, request).verify_award(id, approve))


# ---- MoUs / collaborations ----------------------------------------------------------------------------------------------
@router.get(
    "/research/mous/activity-report",
    summary="Collaborations per MoU for a year (functional MoUs)",
    response_model=Envelope[list[MouActivityRow]],
    dependencies=MOU_F,
)
async def mou_activity_report(
    request: Request,
    year: int = Query(..., ge=2000, le=2100),
    principal: Principal = Depends(MOUS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).activity_report(year))


@router.get("/research/mous", summary="MoU register", response_model=Envelope[list[MouOut]], dependencies=MOU_F)
async def mous(
    request: Request,
    status: str | None = Query(None, pattern="^(draft|submitted|approved|active|expired|renewed|rejected)$"),
    mou_type: str | None = Query(None, pattern="^(academic|research|placement|exchange)$"),
    expiring: bool = False,
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(MOUS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).query(status=status, mou_type=mou_type, expiring=expiring, q=q))


@router.post(
    "/research/mous", status_code=201, summary="Draft an MoU", response_model=Envelope[MouOut], dependencies=MOU_F
)
async def create_mou(
    body: MouIn,
    request: Request,
    principal: Principal = Depends(any_permission_required((R, "mous"), (R, "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).create(body), message="Drafted")


@router.get("/research/mous/{id}", summary="MoU", response_model=Envelope[MouOut], dependencies=MOU_F)
async def mou(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MOUS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).get(id))


@router.put(
    "/research/mous/{id}", summary="Edit (coordinator: activities)", response_model=Envelope[MouOut], dependencies=MOU_F
)
async def update_mou(
    id: uuid.UUID,
    body: MouUpdate,
    request: Request,
    principal: Principal = Depends(MOUS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).update(id, body), message="Saved")


@router.post(
    "/research/mous/{id}/submit",
    summary="Submit (→ research.mou: research cell → legal → principal)",
    response_model=Envelope[MouOut],
    dependencies=MOU_F,
)
async def submit_mou(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MOUS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).submit(id), message="Submitted")


@router.post(
    "/research/mous/{id}/sign", summary="Record signing (→ active)", response_model=Envelope[MouOut], dependencies=MOU_F
)
async def sign_mou(
    id: uuid.UUID,
    body: MouSign,
    request: Request,
    principal: Principal = Depends(any_permission_required((R, "mous"), (R, "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).sign(id, body), message="Signed")


@router.post(
    "/research/mous/{id}/renew", summary="Renew (new version)", response_model=Envelope[MouOut], dependencies=MOU_F
)
async def renew_mou(
    id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(any_permission_required((R, "mous"), (R, "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).renew(id), message="Renewal drafted")


@router.get(
    "/research/mous/{id}/collaborations",
    summary="Collaborations under an MoU",
    response_model=Envelope[list[CollaborationOut]],
    dependencies=MOU_F,
)
async def mou_collaborations(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MOUS), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).collaborations(mou_id=id))


@router.post(
    "/research/mous/{id}/collaborations",
    status_code=201,
    summary="Record a collaboration (internships link the Phase 28 company)",
    response_model=Envelope[CollaborationOut],
    dependencies=MOU_F,
)
async def add_collaboration(
    id: uuid.UUID,
    body: CollaborationIn,
    request: Request,
    principal: Principal = Depends(MOUS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).add_collaboration(id, body), message="Recorded")


@router.get(
    "/research/collaborations",
    summary="Collaborations",
    response_model=Envelope[list[CollaborationOut]],
    dependencies=MOU_F,
)
async def collaborations(
    request: Request,
    type: str | None = Query(None, pattern="^(joint_research|exchange|joint_degree|internship)$"),
    year: int | None = None,
    principal: Principal = Depends(MOUS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).collaborations(ctype=type, year=year))


# ---- start-ups ----------------------------------------------------------------------------------------------------------
@router.get(
    "/research/startups", summary="Start-ups register", response_model=Envelope[list[StartupOut]], dependencies=INCUB_F
)
async def startups(
    request: Request,
    stage: str | None = Query(None, pattern="^(idea|prototype|incubated|funded|graduated)$"),
    q: str | None = Query(None, max_length=100),
    principal: Principal = Depends(INCUBATION),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).startups(stage=stage, q=q))


@router.post(
    "/research/startups",
    status_code=201,
    summary="Register a start-up",
    response_model=Envelope[StartupOut],
    dependencies=INCUB_F,
)
async def create_startup(
    body: StartupIn,
    request: Request,
    principal: Principal = Depends(any_permission_required((R, "incubation"), (R, "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).create_startup(body), message="Registered")


@router.put(
    "/research/startups/{id}", summary="Edit a start-up", response_model=Envelope[StartupOut], dependencies=INCUB_F
)
async def update_startup(
    id: uuid.UUID,
    body: StartupUpdate,
    request: Request,
    principal: Principal = Depends(any_permission_required((R, "incubation"), (R, "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).update_startup(id, body), message="Saved")


@router.post(
    "/research/startups/{id}/stage",
    summary="Advance the stage",
    response_model=Envelope[StartupOut],
    dependencies=INCUB_F,
)
async def startup_stage(
    id: uuid.UUID,
    body: StartupStageIn,
    request: Request,
    principal: Principal = Depends(any_permission_required((R, "incubation"), (R, "manage"))),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MouService(db, principal, request).stage(id, body))


# ---- API score ----------------------------------------------------------------------------------------------------------
@router.post(
    "/research/api-score/compute",
    status_code=202,
    summary="Compute API scores (job; ?inline=true computes at once)",
    response_model=Envelope[list[ApiScoreOut]],
    dependencies=API_F,
)
async def compute_api(
    body: ApiScoreRequest,
    request: Request,
    inline: bool = False,
    principal: Principal = Depends(WRITE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if inline or body.staff_id:
        return ok(
            await ScoreService(db, principal, request).compute(
                body.staff_id, body.department_id, body.period_from, body.period_to
            ),
            message="Computed",
        )
    return await _job(db, principal, "research.api_compute", body.model_dump(mode="json"))


@router.get(
    "/research/api-score/rankings",
    summary="Department ranking",
    response_model=Envelope[list[ApiRankingRow]],
    dependencies=API_F,
)
async def api_rankings(
    request: Request,
    department_id: uuid.UUID | None = None,
    principal: Principal = Depends(API_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScoreService(db, principal, request).rankings(department_id))


@router.get(
    "/research/api-score", summary="API score breakdown", response_model=Envelope[ApiScoreOut], dependencies=API_F
)
async def api_score(
    request: Request,
    staff_id: str = "self",
    period: str | None = Query(None, max_length=40),
    principal: Principal = Depends(API_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ScoreService(db, principal, request)
    sid = await svc.resolve_staff_param(staff_id)
    assert sid is not None
    return ok(await svc.get_score(sid, period))


# ---- profile / stats / reports ------------------------------------------------------------------------------------------
@router.get(
    "/research/profile/me",
    summary="My research profile",
    response_model=Envelope[ResearchProfileOut],
    dependencies=PUBS,
)
async def my_profile(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    svc = ScoreService(db, principal, request)
    return ok(await svc.profile((await svc.require_my_staff()).id))


@router.get(
    "/research/profile/{staff_id}",
    summary="Research profile",
    response_model=Envelope[ResearchProfileOut],
    dependencies=PUBS,
)
async def profile(
    staff_id: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScoreService(db, principal, request).profile(staff_id))


@router.get(
    "/research/stats",
    summary="Research stats (NAAC 3.x / NIRF RP)",
    response_model=Envelope[ResearchStats],
    dependencies=PUBS,
)
async def stats(
    request: Request,
    department_id: uuid.UUID | None = None,
    year: int | None = None,
    college_id: uuid.UUID | None = None,
    publish: bool = False,
    principal: Principal = Depends(STATS),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = ScoreService(db, principal, request)
    if publish and year:
        return ok(await svc.publish(year), message="Published")
    return ok(await svc.stats(year=year, department_id=department_id, college_id=college_id))


@router.get(
    "/research/reports/{kind}",
    status_code=202,
    summary="Reports (?format=xlsx — job; ?inline=true downloads)",
    response_model=Envelope[RschJobQueued],
    dependencies=PUBS,
)
async def report(
    kind: str,
    request: Request,
    format: str = Query("xlsx", pattern="^(xlsx)$"),
    year: int | None = None,
    inline: bool = False,
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if kind not in ("publications", "projects", "consultancy", "patents", "fdp", "mous", "nirf_rp"):
        raise APIError(404, ErrorCode.NOT_FOUND, "Unknown report")
    if inline:
        from app.tasks.research import xlsx_bytes

        rows = await ScoreService(db, principal, request).report_rows(kind, year)
        return Response(
            content=xlsx_bytes(kind, rows),
            media_type=XLSX,
            headers={"Content-Disposition": f'attachment; filename="research-{kind}.xlsx"'},
        )
    return await _job(db, principal, "research.reports_export", {"kind": kind, "year": year, "format": format})


@router.post(
    "/research/evidence-pack",
    status_code=202,
    summary="NAAC 3.x evidence pack (zip job)",
    response_model=Envelope[RschJobQueued],
    dependencies=PUBS,
)
async def evidence_pack(
    criterion: str = Query("3.3", max_length=10),
    period: int | None = Query(None, ge=2000, le=2100),
    principal: Principal = Depends(EXPORT),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    return await _job(db, principal, "research.evidence_pack", {"criterion": criterion, "year": period})


@router.get(
    "/research/mous-activity/{year}",
    summary="MoU activity report export (job)",
    status_code=202,
    response_model=Envelope[RschJobQueued],
    dependencies=MOU_F,
)
async def mou_activity_export(
    year: int, principal: Principal = Depends(EXPORT), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    if not 2000 <= year <= 2100:
        raise APIError(422, ErrorCode.VALIDATION, "year out of range")
    return await _job(db, principal, "research.mou_activity_report", {"year": year, "today": date.today().isoformat()})
