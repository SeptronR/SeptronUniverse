"""OBE attainment, CQI and NBA export — Prompts/17 §17.8.

Every route carries its feature (``obe.attainment`` / ``obe.indirect_surveys`` / ``obe.cqi`` / ``obe.nba_export``).
Compute routes answer ``202`` with the queued run + ``job_id``. Visibility narrows in the services (own offerings for
faculty, units for HOD / dean, institution for the OBE office / IQAC / auditor; 404 otherwise). Fixed paths precede
parameterised ones.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.obe_attainment import (
    AttainmentConfigIn,
    AttainmentConfigOut,
    CoAttainmentResponse,
    CoPoHeatmap,
    CoRunRequest,
    CqiActionIn,
    CqiActionOut,
    CqiActionUpdate,
    CqiStatusChange,
    CqiVerify,
    DashboardResponse,
    ExportJob,
    GapListRow,
    IndirectSurveySummary,
    NbaExportRequest,
    PoAttainmentResponse,
    PoRunRequest,
    ProgramAttainmentTrend,
    RunResponse,
    RunSummary,
    StudentCoAchievement,
)
from app.services.obe.co_service import CoAttainmentService
from app.services.obe.config_service import AttainmentConfigService
from app.services.obe.cqi_service import CqiService
from app.services.obe.nba_service import NbaExportService
from app.services.obe.po_service import PoAttainmentService
from app.utils.response import ok

router = APIRouter(tags=["obe-attainment"])

OBE = "obe"
READ = any_permission_required((OBE, "view"), (OBE, "view_all"), (OBE, "manage"), (OBE, "compute"), (OBE, "configure"))
CONFIG_READ = any_permission_required((OBE, "configure"), (OBE, "view"), (OBE, "view_all"), (OBE, "manage"))
CONFIGURE = permission_required(OBE, "configure")
COMPUTE = any_permission_required((OBE, "compute"), (OBE, "manage"))
SELF = permission_required(OBE, "view")
CQI = any_permission_required((OBE, "manage"), (OBE, "view"), (OBE, "view_all"))
EXPORT = permission_required(OBE, "export")

ATT = [feature_required("obe.attainment")]
IND = [feature_required("obe.indirect_surveys")]
CQIF = [feature_required("obe.cqi")]
NBA = [feature_required("obe.nba_export")]


def _accepted(out: RunResponse, message: str) -> JSONResponse:
    return JSONResponse(status_code=202, content=ok(out.model_dump(mode="json"), message=message))


# ---- configs -------------------------------------------------------------------------------------------------------------
@router.get(
    "/attainment-configs/effective",
    summary="Effective config of a programme (programme → regulation → platform)",
    response_model=Envelope[AttainmentConfigOut],
    dependencies=ATT,
)
async def config_effective(
    program_id: uuid.UUID,
    request: Request,
    batch_id: uuid.UUID | None = None,
    principal: Principal = Depends(CONFIG_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AttainmentConfigService(db, principal, request).get_effective(program_id, batch_id))


@router.get(
    "/attainment-configs",
    summary="Configs (optionally of one scope)",
    response_model=Envelope[list[AttainmentConfigOut]],
    dependencies=ATT,
)
async def config_list(
    request: Request,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    principal: Principal = Depends(CONFIG_READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AttainmentConfigService(db, principal, request).list_configs(scope_type, scope_id))


@router.put(
    "/attainment-configs",
    summary="Create / update the config of a regulation or programme",
    response_model=Envelope[AttainmentConfigOut],
    dependencies=ATT,
)
async def config_put(
    body: AttainmentConfigIn,
    request: Request,
    principal: Principal = Depends(CONFIGURE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await AttainmentConfigService(db, principal, request).put(body), message="Config saved")


# ---- CO attainment -------------------------------------------------------------------------------------------------------
@router.get(
    "/attainment/me",
    summary="My CO achievement in an offering (setting obe.show_students)",
    response_model=Envelope[StudentCoAchievement],
    dependencies=ATT,
)
async def attainment_me(
    offering_id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CoAttainmentService(db, principal, request).me(offering_id))


@router.post(
    "/course-offerings/{id}/attainment/compute",
    status_code=202,
    summary="Compute CO attainment (job)",
    response_model=Envelope[RunResponse],
    dependencies=ATT,
)
async def co_compute(
    id: uuid.UUID,
    request: Request,
    body: CoRunRequest | None = None,
    principal: Principal = Depends(COMPUTE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await CoAttainmentService(db, principal, request).request_run(id, body or CoRunRequest())
    return _accepted(out, "CO attainment queued")


@router.get(
    "/course-offerings/{id}/attainment",
    summary="CO attainment (latest computed run, or ?run_id=)",
    response_model=Envelope[CoAttainmentResponse],
    dependencies=ATT,
)
async def co_get(
    id: uuid.UUID,
    request: Request,
    run_id: uuid.UUID | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CoAttainmentService(db, principal, request).get(id, run_id))


@router.get(
    "/course-offerings/{id}/attainment/heatmap",
    summary="CO × assessment level heatmap",
    response_model=Envelope[CoPoHeatmap],
    dependencies=ATT,
)
async def co_heatmap(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CoAttainmentService(db, principal, request).heatmap(id))


@router.get(
    "/course-offerings/{id}/attainment/runs",
    summary="Run history",
    response_model=Envelope[list[RunSummary]],
    dependencies=ATT,
)
async def co_runs(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CoAttainmentService(db, principal, request).runs(id))


@router.get(
    "/course-offerings/{id}/attainment/students",
    summary="Per-student CO achievement",
    response_model=Envelope[list[StudentCoAchievement]],
    dependencies=ATT,
)
async def co_students(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CoAttainmentService(db, principal, request).student_achievement(id))


# ---- PO attainment -------------------------------------------------------------------------------------------------------
@router.post(
    "/programs/{id}/batches/{bid}/attainment/compute",
    status_code=202,
    summary="Compute PO / PSO attainment for a batch (job)",
    response_model=Envelope[RunResponse],
    dependencies=ATT,
)
async def po_compute(
    id: uuid.UUID,
    bid: uuid.UUID,
    request: Request,
    body: PoRunRequest | None = None,
    principal: Principal = Depends(COMPUTE),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    out = await PoAttainmentService(db, principal, request).request_run(id, bid, body or PoRunRequest())
    return _accepted(out, "PO attainment queued")


@router.get(
    "/programs/{id}/attainment/trend",
    summary="PO / PSO final levels across batches",
    response_model=Envelope[ProgramAttainmentTrend],
    dependencies=ATT,
)
async def po_trend(
    id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await PoAttainmentService(db, principal, request).trend(id))


@router.get(
    "/programs/{id}/attainment/heatmap",
    summary="Course × PO contribution heatmap",
    response_model=Envelope[CoPoHeatmap],
    dependencies=ATT,
)
async def po_heatmap(
    id: uuid.UUID,
    batch_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PoAttainmentService(db, principal, request).heatmap(id, batch_id))


@router.get(
    "/programs/{id}/attainment",
    summary="PO / PSO attainment of a batch (+ derived PEO)",
    response_model=Envelope[PoAttainmentResponse],
    dependencies=ATT,
)
async def po_get(
    id: uuid.UUID,
    batch_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PoAttainmentService(db, principal, request).get(id, batch_id))


# ---- term recompute, dashboard, gaps, indirect ---------------------------------------------------------------------------
@router.post(
    "/obe/recompute-term",
    status_code=202,
    summary="Recompute every offering of a term, then the batches' PO runs (job)",
    response_model=Envelope[ExportJob],
    dependencies=ATT,
)
async def recompute_term(
    term_id: uuid.UUID, request: Request, principal: Principal = Depends(COMPUTE), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    from app.core.jobs import enqueue

    if not (principal.has(OBE, "manage") or principal.has(OBE, "configure") or principal.is_super_admin):
        raise APIError(403, ErrorCode.PERMISSION_DENIED, "Term-wide recompute is an OBE office action")
    job = await enqueue(db, principal, "obe.batch_recompute", {"term_id": str(term_id)})
    out = ExportJob(job_id=job.id, status=job.status, progress=0)
    return JSONResponse(status_code=202, content=ok(out.model_dump(mode="json"), message="Recompute queued"))


@router.get(
    "/obe/dashboard",
    summary="Radar, heatmap, gaps, coverage (HOD / IQAC)",
    response_model=Envelope[DashboardResponse],
    dependencies=ATT,
)
async def dashboard(
    program_id: uuid.UUID,
    batch_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PoAttainmentService(db, principal, request).dashboard(program_id, batch_id))


@router.get(
    "/obe/gaps",
    summary="CO / PO gaps above a threshold with suggested actions",
    response_model=Envelope[list[GapListRow]],
    dependencies=ATT,
)
async def gaps(
    program_id: uuid.UUID,
    request: Request,
    batch_id: uuid.UUID | None = None,
    threshold: float = 0.0,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await PoAttainmentService(db, principal, request).gaps(program_id, batch_id, threshold))


@router.get(
    "/obe/indirect/summary",
    summary="Survey means by CO / outcome",
    response_model=Envelope[IndirectSurveySummary],
    dependencies=IND,
)
async def indirect_summary(
    survey_id: uuid.UUID, request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CoAttainmentService(db, principal, request).indirect_summary(survey_id))


# ---- CQI -----------------------------------------------------------------------------------------------------------------
@router.get("/cqi-actions", summary="CQI actions", response_model=Envelope[list[CqiActionOut]], dependencies=CQIF)
async def cqi_list(
    request: Request,
    status: str | None = None,
    owner_staff_id: uuid.UUID | None = None,
    scope_type: str | None = None,
    scope_id: uuid.UUID | None = None,
    mine: bool = False,
    principal: Principal = Depends(CQI),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CqiService(db, principal, request).list(status, owner_staff_id, scope_type, scope_id, mine))


@router.post("/cqi-actions", summary="Create a CQI action", response_model=Envelope[CqiActionOut], dependencies=CQIF)
async def cqi_create(
    body: CqiActionIn, request: Request, principal: Principal = Depends(CQI), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CqiService(db, principal, request).create(body), message="Action created")


@router.get("/cqi-actions/{id}", summary="CQI action", response_model=Envelope[CqiActionOut], dependencies=CQIF)
async def cqi_get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(CQI), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await CqiService(db, principal, request).get(id))


@router.put("/cqi-actions/{id}", summary="Edit a CQI action", response_model=Envelope[CqiActionOut], dependencies=CQIF)
async def cqi_update(
    id: uuid.UUID,
    body: CqiActionUpdate,
    request: Request,
    principal: Principal = Depends(CQI),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CqiService(db, principal, request).update(id, body))


@router.post(
    "/cqi-actions/{id}/status", summary="Move a CQI action", response_model=Envelope[CqiActionOut], dependencies=CQIF
)
async def cqi_status(
    id: uuid.UUID,
    body: CqiStatusChange,
    request: Request,
    principal: Principal = Depends(CQI),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CqiService(db, principal, request).change_status(id, body))


@router.post(
    "/cqi-actions/{id}/evidence",
    summary="Upload evidence (photo / PDF, ≤ 10 MB)",
    response_model=Envelope[CqiActionOut],
    dependencies=CQIF,
)
async def cqi_evidence(
    id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    principal: Principal = Depends(CQI),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await file.read()
    out = await CqiService(db, principal, request).upload_evidence(
        id, file.filename or "evidence", data, file.content_type
    )
    return ok(out, message="Evidence uploaded")


@router.post(
    "/cqi-actions/{id}/verify", summary="Verify a done action", response_model=Envelope[CqiActionOut], dependencies=CQIF
)
async def cqi_verify(
    id: uuid.UUID,
    body: CqiVerify,
    request: Request,
    principal: Principal = Depends(CQI),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await CqiService(db, principal, request).verify(id, body))


# ---- NBA export ----------------------------------------------------------------------------------------------------------
@router.post(
    "/obe/export/nba-sar",
    status_code=202,
    summary="Generate the NBA SAR Criterion 3 export (job)",
    response_model=Envelope[ExportJob],
    dependencies=NBA,
)
async def nba_export(
    body: NbaExportRequest, request: Request, principal: Principal = Depends(EXPORT), db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    out = await NbaExportService(db, principal, request).submit(body)
    return JSONResponse(status_code=202, content=ok(out.model_dump(mode="json"), message="Export queued"))


@router.get(
    "/obe/exports/{job_id}", summary="Export status / download", response_model=Envelope[ExportJob], dependencies=NBA
)
async def nba_export_get(
    job_id: uuid.UUID, request: Request, principal: Principal = Depends(EXPORT), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await NbaExportService(db, principal, request).job(job_id))
