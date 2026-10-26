"""Accreditation & compliance (IQAC) — Prompts/32 §32.8: frameworks / criteria trees {accreditation.aishe base; NAAC /
NBA / NIRF / AICTE-UGC checked per framework}, metric registry / compute / values (ScopeTabs Department | College |
All) / trend / drill-down / overrides / manual inputs, evidence repository {accreditation.evidence_repo}, cycles and
criterion responses {accreditation.iqac_cycles | accreditation.nba}, exports, compliance submissions (feature per
type), audit registers {accreditation.audit_registers}, consistency checks, disclosures (authenticated feed + public
website feed by institution slug) and the IQAC dashboard. Fixed-path routes are declared before ``/{key}`` routes.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import effective_features, feature_required, is_enabled
from app.db.session import get_db
from app.schemas.accreditation import (
    AccreditationJobQueued,
    AuditDashboardOut,
    AuditRegisterIn,
    AuditRegisterOut,
    AuditRegisterUpdate,
    BestPracticeIn,
    ComputeSummary,
    ConsistencyCheckOut,
    CriterionResponseIn,
    CriterionResponseOut,
    CycleExportRequest,
    CycleIn,
    CycleOut,
    CycleStatusChange,
    CycleUpdate,
    DisclosureFeedOut,
    DistinctivenessIn,
    DrilldownRows,
    EvidenceIn,
    EvidenceOut,
    EvidenceSuggestion,
    EvidenceUpdate,
    EvidenceVerify,
    ExportOut,
    FindingUpdate,
    FrameworkOut,
    IqacDashboardOut,
    ManualMetricInput,
    MetricComputeRequest,
    MetricDefinitionOut,
    MetricOverride,
    MetricTrend,
    MetricValueOut,
    OverrideVerify,
    ResponseAssign,
    ResponseReview,
    ResponseVersion,
    SubmissionDiff,
    SubmissionIn,
    SubmissionMarkSubmitted,
    SubmissionOut,
)
from app.schemas.common import Envelope
from app.services.accreditation.audit_service import AuditService
from app.services.accreditation.common import AccreditationBase
from app.services.accreditation.consistency_service import ConsistencyService
from app.services.accreditation.cycle_service import CycleService
from app.services.accreditation.dashboard_service import DashboardService
from app.services.accreditation.disclosure_service import DisclosureService
from app.services.accreditation.evidence_service import EvidenceService
from app.services.accreditation.export_service import ExportService
from app.services.accreditation.framework_service import FrameworkService
from app.services.accreditation.metric_service import MetricService
from app.services.accreditation.submission_service import SubmissionService
from app.utils.response import PaginationMeta, VisibilityMeta, ok

router = APIRouter(tags=["accreditation"])
public_router = APIRouter(tags=["accreditation"])

P = "accreditation"
VIEW = any_permission_required((P, "view"), (P, "view_all"), (P, "manage"))
VIEW_ALL = any_permission_required((P, "view_all"), (P, "manage"))
COMPUTE = any_permission_required((P, "compute"), (P, "manage"))
OVERRIDE = any_permission_required((P, "override"), (P, "approve"), (P, "manage"))
EVIDENCE = any_permission_required((P, "evidence"), (P, "view"), (P, "view_all"), (P, "manage"))
EVIDENCE_W = any_permission_required((P, "evidence"), (P, "manage"))
SUBMIT = any_permission_required((P, "submit"), (P, "manage"))
REVIEW = any_permission_required((P, "view"), (P, "approve"), (P, "manage"))
MANAGE = any_permission_required((P, "manage"))

BASE = [feature_required("accreditation.aishe")]
EVID = [feature_required("accreditation.evidence_repo")]
AUDIT = [feature_required("accreditation.audit_registers")]


def _any_feature(*keys: str) -> Any:
    """Route dependency: 403 unless one of ``keys`` is on (the first key is what the guards read)."""

    async def _dep(request: Request) -> None:
        inst = getattr(request.state, "institution_id", None)
        if not inst:
            return
        on = await effective_features(inst)
        if not any(k in on for k in keys):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{keys[0]}' is not enabled", {"feature": keys[0]})

    _dep.__feature_key__ = keys[0]  # type: ignore[attr-defined]  # read by scripts/check_authz_coverage.py
    return Depends(_dep)


CYCLES = [_any_feature("accreditation.iqac_cycles", "accreditation.nba")]
SUBS = [_any_feature("accreditation.aishe", "accreditation.nirf", "accreditation.aicte_ugc", "accreditation.naac")]

SCOPE = Query(None, pattern="^(own|department|college|all)$")


async def _job(db: AsyncSession, principal: Principal, job_type: str, params: dict[str, Any]) -> JSONResponse:
    from app.core.jobs import enqueue

    j = await enqueue(db, principal, job_type, params)
    return JSONResponse(
        status_code=202, content=ok(AccreditationJobQueued(job_id=j.id).model_dump(mode="json"), message="Queued")
    )


def _vis(svc: AccreditationBase) -> VisibilityMeta:
    v = svc.visibility()
    return VisibilityMeta(self=v["self"], scopes=v["scopes"], default=v["default"])


def _page(page: int, per_page: int, total: int) -> PaginationMeta:
    return PaginationMeta(page=page, page_size=per_page, total=total, total_pages=max(1, -(-total // per_page)))


# ---- frameworks ---------------------------------------------------------------------------------------------------------
@router.get(
    "/accreditation/frameworks",
    summary="Frameworks with active flags",
    response_model=Envelope[list[FrameworkOut]],
    dependencies=BASE,
)
async def frameworks(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FrameworkService(db, principal, request).frameworks())


@router.get(
    "/accreditation/frameworks/{code}",
    summary="Criteria tree with metric links",
    response_model=Envelope[FrameworkOut],
    dependencies=BASE,
)
async def framework(
    code: str, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FrameworkService(db, principal, request).tree(code))


@router.get(
    "/accreditation/frameworks/{code}/metrics",
    summary="Metric definitions used by a framework",
    response_model=Envelope[list[MetricDefinitionOut]],
    dependencies=BASE,
)
async def framework_metrics(
    code: str, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await FrameworkService(db, principal, request).framework_metrics(code))


# ---- metrics ---------------------------------------------------------------------------------------------------------------
@router.get(
    "/accreditation/metrics/definitions",
    summary="Metric registry (source module, depends_on, registered)",
    response_model=Envelope[list[MetricDefinitionOut]],
    dependencies=BASE,
)
async def definitions(
    request: Request,
    framework: str | None = Query(None, max_length=30),
    module: str | None = Query(None, max_length=40),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MetricService(db, principal, request).definitions(framework, module))


@router.post(
    "/accreditation/metrics/compute",
    summary="Compute metrics (job; ?inline=true computes at once)",
    response_model=Envelope[ComputeSummary],
    dependencies=BASE,
)
async def compute(
    body: MetricComputeRequest,
    request: Request,
    inline: bool = False,
    principal: Principal = Depends(COMPUTE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = MetricService(db, principal, request)
    svc.require_iqac("compute")
    if not inline:
        return await _job(db, principal, "accreditation.compute", body.model_dump(mode="json"))
    out = await svc.compute(body)
    await DisclosureService(db, principal, request).refresh()
    return ok(out)


@router.get(
    "/accreditation/metrics/overrides",
    summary="Override proposals awaiting verification",
    response_model=Envelope[list[MetricValueOut]],
    dependencies=BASE,
)
async def overrides(
    request: Request, pending: bool = True, principal: Principal = Depends(OVERRIDE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await MetricService(db, principal, request).pending_overrides())


@router.get(
    "/accreditation/metrics",
    summary="Metric values (ScopeTabs Department | College | All)",
    response_model=Envelope[list[MetricValueOut]],
    dependencies=BASE,
)
async def metric_values(
    request: Request,
    period: str | None = Query(None, max_length=20),
    framework: str | None = Query(None, max_length=30),
    college_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    source: str | None = Query(None, pattern="^(auto|manual|override)$"),
    verified: bool | None = None,
    scope: str | None = SCOPE,
    page: int = Query(1, ge=1),
    per_page: int = Query(200, ge=1, le=1000),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = MetricService(db, principal, request)
    items, total = await svc.values(
        period=period,
        framework=framework,
        college_id=college_id,
        program_id=program_id,
        source=source,
        verified=verified,
        scope=scope,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return ok(items, pagination=_page(page, per_page, total), visibility=_vis(svc))


@router.get(
    "/accreditation/metrics/{key}",
    summary="One metric value",
    response_model=Envelope[MetricValueOut],
    dependencies=BASE,
)
async def metric_value(
    key: str,
    request: Request,
    period: str = Query(max_length=20),
    college_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MetricService(db, principal, request).get(key, period, college_id, program_id))


@router.get(
    "/accreditation/metrics/{key}/trend",
    summary="Period-over-period trend",
    response_model=Envelope[MetricTrend],
    dependencies=BASE,
)
async def metric_trend(
    key: str,
    request: Request,
    periods: list[str] | None = Query(None),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MetricService(db, principal, request).trend(key, periods))


@router.get(
    "/accreditation/metrics/{key}/drilldown",
    summary="Source rows under the caller's visibility (PII masked)",
    response_model=Envelope[DrilldownRows],
    dependencies=BASE,
)
async def drilldown(
    key: str,
    request: Request,
    period: str = Query(max_length=20),
    college_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=1000),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = MetricService(db, principal, request)
    out = await svc.drilldown(key, period, college_id, program_id, page, per_page)
    return ok(out, visibility=_vis(svc))


@router.get(
    "/accreditation/metrics/{key}/drilldown/export",
    summary="Drill-down as an xlsx evidence table (job)",
    response_model=Envelope[AccreditationJobQueued],
    dependencies=BASE,
)
async def drilldown_export(
    key: str,
    request: Request,
    period: str = Query(max_length=20),
    college_id: uuid.UUID | None = None,
    program_id: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await MetricService(db, principal, request).definition(key)
    return await _job(
        db,
        principal,
        "accreditation.drilldown_export",
        {
            "key": key,
            "period": period,
            "college_id": str(college_id) if college_id else None,
            "program_id": str(program_id) if program_id else None,
        },
    )


@router.put(
    "/accreditation/metrics/{key}/override",
    summary="Override a value (reason mandatory; pending until verified)",
    response_model=Envelope[MetricValueOut],
    dependencies=BASE,
)
async def override(
    key: str,
    body: MetricOverride,
    request: Request,
    principal: Principal = Depends(OVERRIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MetricService(db, principal, request).override(key, body))


@router.post(
    "/accreditation/metrics/{key}/verify",
    summary="Verify (locks) / reject a pending override / unverify (principal)",
    response_model=Envelope[MetricValueOut],
    dependencies=BASE,
)
async def verify(
    key: str,
    body: OverrideVerify,
    request: Request,
    principal: Principal = Depends(OVERRIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MetricService(db, principal, request).verify(key, body))


@router.put(
    "/accreditation/metrics/{key}/manual",
    summary="Manual input for a non-computable metric",
    response_model=Envelope[MetricValueOut],
    dependencies=BASE,
)
async def manual(
    key: str,
    body: ManualMetricInput,
    request: Request,
    principal: Principal = Depends(OVERRIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await MetricService(db, principal, request).manual(key, body))


# ---- evidence ------------------------------------------------------------------------------------------------------------
@router.get(
    "/accreditation/evidence",
    summary="Evidence repository",
    response_model=Envelope[list[EvidenceOut]],
    dependencies=EVID,
)
async def evidence_list(
    request: Request,
    criterion: str | None = Query(None, max_length=20),
    framework: str | None = Query(None, max_length=30),
    period: str | None = Query(None, max_length=20),
    metric_key: str | None = Query(None, max_length=80),
    doc_type: str | None = Query(None, max_length=40),
    verified: bool | None = None,
    q: str | None = Query(None, max_length=100),
    scope: str | None = SCOPE,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=500),
    principal: Principal = Depends(EVIDENCE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = EvidenceService(db, principal, request)
    items, total = await svc.query(
        criterion=criterion,
        framework=framework,
        period=period,
        metric_key=metric_key,
        doc_type=doc_type,
        verified=verified,
        q=q,
        scope=scope,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return ok(items, pagination=_page(page, per_page, total), visibility=_vis(svc))


@router.post(
    "/accreditation/evidence",
    status_code=201,
    summary="Upload / tag evidence (size cap → 413)",
    response_model=Envelope[EvidenceOut],
    dependencies=EVID,
)
async def evidence_create(
    body: EvidenceIn, request: Request, principal: Principal = Depends(EVIDENCE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EvidenceService(db, principal, request).create(body), message="Created")


@router.get(
    "/accreditation/evidence/suggestions",
    summary="Auto-suggested evidence inbox",
    response_model=Envelope[list[EvidenceSuggestion]],
    dependencies=EVID,
)
async def suggestions(
    request: Request,
    status: str = Query("pending", pattern="^(pending|accepted|dismissed)$"),
    principal: Principal = Depends(EVIDENCE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EvidenceService(db, principal, request).suggestions(status))


@router.post(
    "/accreditation/evidence/suggestions/{sid}/accept",
    summary="Accept a suggestion (creates the evidence row)",
    response_model=Envelope[EvidenceSuggestion],
    dependencies=EVID,
)
async def suggestion_accept(
    sid: str, request: Request, principal: Principal = Depends(EVIDENCE_W), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EvidenceService(db, principal, request).decide_suggestion(sid, True))


@router.post(
    "/accreditation/evidence/suggestions/{sid}/dismiss",
    summary="Dismiss a suggestion",
    response_model=Envelope[EvidenceSuggestion],
    dependencies=EVID,
)
async def suggestion_dismiss(
    sid: str, request: Request, principal: Principal = Depends(EVIDENCE_W), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EvidenceService(db, principal, request).decide_suggestion(sid, False))


@router.post(
    "/accreditation/evidence/pack",
    summary="Evidence pack per criterion (zip with index; job)",
    response_model=Envelope[AccreditationJobQueued],
    dependencies=EVID,
)
async def evidence_pack(
    request: Request,
    criterion: str = Query(max_length=20),
    period: str | None = Query(None, max_length=20),
    framework: str = Query("NAAC_2024", max_length=30),
    principal: Principal = Depends(EVIDENCE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return await _job(
        db, principal, "accreditation.evidence_pack", {"criterion": criterion, "period": period, "framework": framework}
    )


@router.get(
    "/accreditation/evidence/{eid}",
    summary="Evidence document",
    response_model=Envelope[EvidenceOut],
    dependencies=EVID,
)
async def evidence_get(
    eid: uuid.UUID, request: Request, principal: Principal = Depends(EVIDENCE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await EvidenceService(db, principal, request).get(eid))


@router.put(
    "/accreditation/evidence/{eid}",
    summary="Update / re-version evidence",
    response_model=Envelope[EvidenceOut],
    dependencies=EVID,
)
async def evidence_update(
    eid: uuid.UUID,
    body: EvidenceUpdate,
    request: Request,
    principal: Principal = Depends(EVIDENCE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EvidenceService(db, principal, request).update(eid, body))


@router.delete(
    "/accreditation/evidence/{eid}", summary="Delete evidence", response_model=Envelope[None], dependencies=EVID
)
async def evidence_delete(
    eid: uuid.UUID, request: Request, principal: Principal = Depends(EVIDENCE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await EvidenceService(db, principal, request).delete(eid)
    return ok(None, message="Deleted")


@router.post(
    "/accreditation/evidence/{eid}/verify",
    summary="Verify evidence",
    response_model=Envelope[EvidenceOut],
    dependencies=EVID,
)
async def evidence_verify(
    eid: uuid.UUID,
    body: EvidenceVerify,
    request: Request,
    principal: Principal = Depends(EVIDENCE_W),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await EvidenceService(db, principal, request).verify(eid, body))


# ---- cycles -----------------------------------------------------------------------------------------------------------------
@router.get(
    "/accreditation/cycles",
    summary="Accreditation cycles",
    response_model=Envelope[list[CycleOut]],
    dependencies=CYCLES,
)
async def cycles(
    request: Request,
    framework: str | None = Query(None, max_length=30),
    status: str | None = Query(None, max_length=20),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).query(framework, status))


@router.post(
    "/accreditation/cycles",
    status_code=201,
    summary="Create a cycle (NBA per programme)",
    response_model=Envelope[CycleOut],
    dependencies=CYCLES,
)
async def cycle_create(
    body: CycleIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).create(body), message="Created")


@router.get("/accreditation/cycles/{cid}", summary="Cycle", response_model=Envelope[CycleOut], dependencies=CYCLES)
async def cycle_get(
    cid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).get(cid))


@router.put(
    "/accreditation/cycles/{cid}", summary="Update a cycle", response_model=Envelope[CycleOut], dependencies=CYCLES
)
async def cycle_update(
    cid: uuid.UUID,
    body: CycleUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).update(cid, body))


@router.post(
    "/accreditation/cycles/{cid}/status",
    summary="Advance the cycle status",
    response_model=Envelope[CycleOut],
    dependencies=CYCLES,
)
async def cycle_status(
    cid: uuid.UUID,
    body: CycleStatusChange,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).change_status(cid, body))


@router.get(
    "/accreditation/cycles/{cid}/progress",
    summary="Completion % and criteria progress",
    response_model=Envelope[dict[str, Any]],
    dependencies=CYCLES,
)
async def cycle_progress(
    cid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).progress(cid))


@router.get(
    "/accreditation/cycles/{cid}/criteria",
    summary="Criterion responses (owner / department / all)",
    response_model=Envelope[list[CriterionResponseOut]],
    dependencies=CYCLES,
)
async def criteria(
    cid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).responses(cid))


@router.post(
    "/accreditation/cycles/{cid}/criteria/assign",
    summary="Assign criteria to an owner with a due date",
    response_model=Envelope[list[CriterionResponseOut]],
    dependencies=CYCLES,
)
async def criteria_assign(
    cid: uuid.UUID,
    body: ResponseAssign,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).assign(cid, body))


@router.post(
    "/accreditation/cycles/{cid}/best-practices",
    summary="Best practice narrative (criterion 7.2.1)",
    response_model=Envelope[CriterionResponseOut],
    dependencies=CYCLES,
)
async def best_practice(
    cid: uuid.UUID,
    body: BestPracticeIn,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).best_practice(cid, body))


@router.post(
    "/accreditation/cycles/{cid}/distinctiveness",
    summary="Institutional distinctiveness (criterion 7.3.1)",
    response_model=Envelope[CriterionResponseOut],
    dependencies=CYCLES,
)
async def distinctiveness(
    cid: uuid.UUID,
    body: DistinctivenessIn,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).distinctiveness(cid, body))


@router.get(
    "/accreditation/cycles/{cid}/criteria/{code}",
    summary="Criterion response (narrative, linked metrics, evidence)",
    response_model=Envelope[CriterionResponseOut],
    dependencies=CYCLES,
)
async def criterion_get(
    cid: uuid.UUID,
    code: str,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).response(cid, code))


@router.put(
    "/accreditation/cycles/{cid}/criteria/{code}",
    summary="Save a criterion response (word limit; locked once approved)",
    response_model=Envelope[CriterionResponseOut],
    dependencies=CYCLES,
)
async def criterion_save(
    cid: uuid.UUID,
    code: str,
    body: CriterionResponseIn,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).save(cid, code, body))


@router.post(
    "/accreditation/cycles/{cid}/criteria/{code}/submit",
    summary="Submit for review (workflow accreditation.response_review)",
    response_model=Envelope[CriterionResponseOut],
    dependencies=CYCLES,
)
async def criterion_submit(
    cid: uuid.UUID,
    code: str,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).submit(cid, code))


@router.post(
    "/accreditation/cycles/{cid}/criteria/{code}/review",
    summary="Review step (HOD → IQAC → principal)",
    response_model=Envelope[CriterionResponseOut],
    dependencies=CYCLES,
)
async def criterion_review(
    cid: uuid.UUID,
    code: str,
    body: ResponseReview,
    request: Request,
    principal: Principal = Depends(REVIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).review(cid, code, body))


@router.get(
    "/accreditation/cycles/{cid}/criteria/{code}/versions",
    summary="Response versions",
    response_model=Envelope[list[ResponseVersion]],
    dependencies=CYCLES,
)
async def criterion_versions(
    cid: uuid.UUID,
    code: str,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CycleService(db, principal, request).versions(cid, code))


@router.post(
    "/accreditation/cycles/{cid}/export",
    summary="Export SSR / AQAR / SAR / NIRF / AISHE / AICTE / UGC (job)",
    response_model=Envelope[AccreditationJobQueued],
    dependencies=CYCLES,
)
async def cycle_export(
    cid: uuid.UUID,
    body: CycleExportRequest,
    request: Request,
    principal: Principal = Depends(SUBMIT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = ExportService(db, principal, request)
    svc.require_exporter()
    await CycleService(db, principal, request).cycle(cid)
    return await _job(
        db,
        principal,
        "accreditation.cycle_export",
        {"cycle_id": str(cid), "format": body.format.value, "period_label": body.period_label},
    )


@router.get(
    "/accreditation/cycles/{cid}/exports",
    summary="Generated exports",
    response_model=Envelope[list[ExportOut]],
    dependencies=CYCLES,
)
async def cycle_exports(
    cid: uuid.UUID, request: Request, principal: Principal = Depends(SUBMIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ExportService(db, principal, request).exports(cid))


# ---- submissions ------------------------------------------------------------------------------------------------------------
@router.get(
    "/accreditation/submissions",
    summary="Compliance submissions",
    response_model=Envelope[list[SubmissionOut]],
    dependencies=SUBS,
)
async def submissions(
    request: Request,
    submission_type: str | None = Query(None, max_length=20),
    period: str | None = Query(None, max_length=20),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).query(submission_type, period))


@router.post(
    "/accreditation/submissions",
    status_code=201,
    summary="Create a submission (a correction after submit is a new row)",
    response_model=Envelope[SubmissionOut],
    dependencies=SUBS,
)
async def submission_create(
    body: SubmissionIn, request: Request, principal: Principal = Depends(SUBMIT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).create(body), message="Created")


@router.get(
    "/accreditation/submissions/{sid}",
    summary="Submission (payload preview)",
    response_model=Envelope[SubmissionOut],
    dependencies=SUBS,
)
async def submission_get(
    sid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).get(sid))


@router.post(
    "/accreditation/submissions/{sid}/generate",
    summary="Generate the payload from metrics (job; ?inline=true generates at once)",
    response_model=Envelope[SubmissionOut],
    dependencies=SUBS,
)
async def submission_generate(
    sid: uuid.UUID,
    request: Request,
    inline: bool = False,
    principal: Principal = Depends(SUBMIT),
    db: AsyncSession = Depends(get_db),
) -> Any:
    svc = SubmissionService(db, principal, request)
    svc.require_iqac("submit")
    if not inline:
        await svc.row(sid)
        return await _job(db, principal, "accreditation.submission_generate", {"submission_id": str(sid)})
    return ok(await svc.generate(sid))


@router.get(
    "/accreditation/submissions/{sid}/diff",
    summary="Diff vs the previous period",
    response_model=Envelope[SubmissionDiff],
    dependencies=SUBS,
)
async def submission_diff(
    sid: uuid.UUID,
    request: Request,
    vs: uuid.UUID | None = None,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).diff(sid, vs))


@router.post(
    "/accreditation/submissions/{sid}/submitted",
    summary="Mark submitted / acknowledged (payload immutable afterwards)",
    response_model=Envelope[SubmissionOut],
    dependencies=SUBS,
)
async def submission_submitted(
    sid: uuid.UUID,
    body: SubmissionMarkSubmitted,
    request: Request,
    principal: Principal = Depends(SUBMIT),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await SubmissionService(db, principal, request).mark_submitted(sid, body))


# ---- audits -------------------------------------------------------------------------------------------------------------------
@router.get(
    "/accreditation/audits/dashboard",
    summary="Audit compliance dashboard",
    response_model=Envelope[AuditDashboardOut],
    dependencies=AUDIT,
)
async def audits_dashboard(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).dashboard())


@router.get(
    "/accreditation/audits",
    summary="Audit registers (finding owners see theirs)",
    response_model=Envelope[list[AuditRegisterOut]],
    dependencies=AUDIT,
)
async def audits(
    request: Request,
    audit_type: str | None = Query(None, max_length=30),
    period: str | None = Query(None, max_length=20),
    status: str | None = Query(None, max_length=20),
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).query(audit_type, period, status))


@router.post(
    "/accreditation/audits",
    status_code=201,
    summary="Create an audit register",
    response_model=Envelope[AuditRegisterOut],
    dependencies=AUDIT,
)
async def audit_create(
    body: AuditRegisterIn, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).create(body), message="Created")


@router.get(
    "/accreditation/audits/{aid}",
    summary="Audit register",
    response_model=Envelope[AuditRegisterOut],
    dependencies=AUDIT,
)
async def audit_get(
    aid: uuid.UUID, request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).get(aid))


@router.put(
    "/accreditation/audits/{aid}",
    summary="Update an audit register / add findings",
    response_model=Envelope[AuditRegisterOut],
    dependencies=AUDIT,
)
async def audit_update(
    aid: uuid.UUID,
    body: AuditRegisterUpdate,
    request: Request,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).update(aid, body))


@router.put(
    "/accreditation/audits/{aid}/findings/{no}",
    summary="Update a finding (owner / IQAC)",
    response_model=Envelope[AuditRegisterOut],
    dependencies=AUDIT,
)
async def finding_update(
    aid: uuid.UUID,
    no: int,
    body: FindingUpdate,
    request: Request,
    principal: Principal = Depends(VIEW),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AuditService(db, principal, request).update_finding(aid, no, body))


# ---- consistency / disclosures / dashboard -------------------------------------------------------------------------------------
@router.post(
    "/accreditation/consistency/check",
    summary="Run consistency checks (job; ?inline=true runs at once)",
    response_model=Envelope[ConsistencyCheckOut],
    dependencies=BASE,
)
async def consistency_check(
    request: Request,
    period: str = Query(max_length=20),
    inline: bool = False,
    principal: Principal = Depends(MANAGE),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not inline:
        return await _job(db, principal, "accreditation.consistency_check", {"period": period})
    return ok(await ConsistencyService(db, principal, request).run(period, notify=True))


@router.get(
    "/accreditation/consistency",
    summary="Latest consistency results",
    response_model=Envelope[ConsistencyCheckOut],
    dependencies=BASE,
)
async def consistency(
    request: Request,
    period: str = Query(max_length=20),
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ConsistencyService(db, principal, request).latest(period))


@router.get(
    "/accreditation/disclosures",
    summary="Mandatory disclosures feed",
    response_model=Envelope[DisclosureFeedOut],
    dependencies=BASE,
)
async def disclosures(
    request: Request, principal: Principal = Depends(VIEW), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DisclosureService(db, principal, request).feed())


@router.post(
    "/accreditation/disclosures/refresh",
    summary="Refresh the disclosures feed",
    response_model=Envelope[DisclosureFeedOut],
    dependencies=BASE,
)
async def disclosures_refresh(
    request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DisclosureService(db, principal, request).refresh())


@router.get(
    "/accreditation/dashboard",
    summary="IQAC dashboard with score simulation",
    response_model=Envelope[IqacDashboardOut],
    dependencies=BASE,
)
async def dashboard(
    request: Request,
    period: str | None = Query(None, max_length=20),
    principal: Principal = Depends(VIEW_ALL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DashboardService(db, principal, request).dashboard(period))


# ---- public website feed ----------------------------------------------------------------------------------------------------------
@public_router.get(
    "/accreditation/disclosures/public",
    summary="Public mandatory disclosures (website; aggregates only, no PII)",
    response_model=Envelope[DisclosureFeedOut],
)
async def disclosures_public(
    request: Request, institution: str = Query(min_length=2, max_length=60), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    if not await is_enabled(iid, "accreditation.aishe"):
        raise APIError(
            403,
            ErrorCode.FEATURE_DISABLED,
            "Feature 'accreditation.aishe' is not enabled",
            {"feature": "accreditation.aishe"},
        )
    return ok(await DisclosureService(db, None, request, iid).feed())
