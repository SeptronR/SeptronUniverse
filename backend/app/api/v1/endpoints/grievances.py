"""Grievances — Prompts/27 §27.8 {grievances.core} / {grievances.anonymous}: raise (Idempotency-Key), mine / wards,
complainant updates / reopen / rate, the officer & committee kanban (triage / internal notes / resolve / close /
escalate) and the statutory registers. ``public_router`` takes anonymous grievances (captcha, rate-limited) and
anonymous tracking (ticket + secret) with the tenant from the institution slug (``PUBLIC_ROUTES``).
"""

import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.errors import APIError, ErrorCode
from app.core.features import feature_required, is_enabled
from app.core.idempotency import idempotency_key, store
from app.core.rate_limit import rate_limited, verify_captcha
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.grievances import (
    GrvAnonymousCreate,
    GrvCreate,
    GrvCreated,
    GrvEscalate,
    GrvOut,
    GrvRate,
    GrvRegister,
    GrvReopen,
    GrvResolve,
    GrvTrack,
    GrvTriage,
    GrvUpdateIn,
)
from app.services.student_support.grievance_service import GrievanceService
from app.utils.response import ok

router = APIRouter(tags=["grievances"])
public_router = APIRouter(tags=["grievances"])

G = "grievances"
SELF = any_permission_required((G, "create"), (G, "view"), (G, "view_all"), (G, "triage"), (G, "manage"))
HANDLE = any_permission_required(
    (G, "triage"), (G, "resolve"), (G, "escalate"), (G, "committee"), (G, "view_all"), (G, "manage"), (G, "view")
)
REGISTERS = any_permission_required((G, "view_all"), (G, "manage"), ("reports", "statutory"))

CORE = [feature_required("grievances.core")]


def _vis(data: Any, svc: GrievanceService) -> dict[str, Any]:
    res = ok(data)
    tabs = svc.visibility(self_tab=True, own_tab=True)
    res["meta"]["visibility"] = tabs
    return res


@router.post(
    "/grievances",
    status_code=201,
    summary="Raise a grievance (Idempotency-Key; anonymous toggle needs grievances.anonymous)",
    response_model=Envelope[GrvCreated],
    dependencies=CORE,
)
async def create(
    body: GrvCreate,
    request: Request,
    key: str | None = Depends(idempotency_key),
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    res = ok(await GrievanceService(db, principal, request).create(body), message="Submitted")
    await store(request, res, db, 201)
    return res


@router.get("/grievances/me", summary="My grievances", response_model=Envelope[list[GrvOut]], dependencies=CORE)
async def mine(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).mine())


@router.get(
    "/grievances/wards", summary="My wards' grievances", response_model=Envelope[list[GrvOut]], dependencies=CORE
)
async def wards(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).wards())


@router.get(
    "/grievances/registers/{register}",
    summary="Statutory register (ugc | icc | anti_ragging; anonymised; ?format=csv)",
    response_model=Envelope[GrvRegister],
    dependencies=CORE,
)
async def register(
    register: str,
    request: Request,
    period: str | None = None,
    format: str | None = None,
    principal: Principal = Depends(REGISTERS),
    db: AsyncSession = Depends(get_db),
) -> Any:
    reg = await GrievanceService(db, principal, request).register(register, period)
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(reg.rows[0].model_dump().keys()) if reg.rows else ["ticket_number"])
        w.writeheader()
        for r in reg.rows:
            w.writerow(r.model_dump(mode="json"))
        return Response(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="grievance-register-{register}.csv"'},
        )
    return ok(reg)


@router.get(
    "/grievances",
    summary="Grievances (ScopeTabs; confidential categories only for the routed committee / officers)",
    response_model=Envelope[list[GrvOut]],
    dependencies=CORE,
)
async def list_all(
    request: Request,
    status: str | None = None,
    category: str | None = None,
    committee: str | None = None,
    department_id: uuid.UUID | None = None,
    scope: str | None = None,
    principal: Principal = Depends(HANDLE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = GrievanceService(db, principal, request)
    return _vis(await svc.list_all(status, category, committee, department_id, scope), svc)


@router.get("/grievances/{id}", summary="Grievance ticket", response_model=Envelope[GrvOut], dependencies=CORE)
async def get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).get(id))


@router.post(
    "/grievances/{id}/updates",
    summary="Post an update (complainant: public; handler: may be internal)",
    response_model=Envelope[GrvOut],
    dependencies=CORE,
)
async def add_update(
    id: uuid.UUID,
    body: GrvUpdateIn,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).add_update(id, body))


@router.post(
    "/grievances/{id}/reopen", summary="Reopen once (complainant)", response_model=Envelope[GrvOut], dependencies=CORE
)
async def reopen(
    id: uuid.UUID,
    body: GrvReopen,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).reopen(id, body), message="Reopened")


@router.post(
    "/grievances/{id}/rate", summary="Rate the resolution (closes)", response_model=Envelope[GrvOut], dependencies=CORE
)
async def rate(
    id: uuid.UUID,
    body: GrvRate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).rate(id, body), message="Thank you")


@router.post(
    "/grievances/{id}/triage",
    summary="Triage (assign / priority / committee)",
    response_model=Envelope[GrvOut],
    dependencies=CORE,
)
async def triage(
    id: uuid.UUID,
    body: GrvTriage,
    request: Request,
    principal: Principal = Depends(HANDLE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).triage(id, body))


@router.post("/grievances/{id}/resolve", summary="Resolve", response_model=Envelope[GrvOut], dependencies=CORE)
async def resolve(
    id: uuid.UUID,
    body: GrvResolve,
    request: Request,
    principal: Principal = Depends(HANDLE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).resolve(id, body), message="Resolved")


@router.post("/grievances/{id}/close", summary="Close", response_model=Envelope[GrvOut], dependencies=CORE)
async def close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).close(id), message="Closed")


@router.post(
    "/grievances/{id}/escalate",
    summary="Escalate (workflow grievance.escalation)",
    response_model=Envelope[GrvOut],
    dependencies=CORE,
)
async def escalate(
    id: uuid.UUID,
    body: GrvEscalate,
    request: Request,
    principal: Principal = Depends(HANDLE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await GrievanceService(db, principal, request).escalate(id, body), message="Escalated")


# ---- public ---------------------------------------------------------------------------------------------------------------
async def _tenant(db: AsyncSession, institution: str, *, anonymous: bool) -> uuid.UUID:
    from app.db.session import bind_tenant, set_tenant
    from app.services.inventory.vendor_service import tenant_by_slug

    iid = await tenant_by_slug(institution)
    bind_tenant(db, iid)
    await set_tenant(db, iid)
    for key in ("grievances.core",) + (("grievances.anonymous",) if anonymous else ()):
        if not await is_enabled(iid, key):
            raise APIError(403, ErrorCode.FEATURE_DISABLED, f"Feature '{key}' is not enabled", {"feature": key})
    return iid


@public_router.post(
    "/grievances/anonymous",
    status_code=201,
    summary="Anonymous grievance (public form, captcha; tracking secret shown once)",
    response_model=Envelope[GrvCreated],
    dependencies=[rate_limited("grievance_anonymous", limit=5, window=600)],
)
async def anonymous(
    body: GrvAnonymousCreate,
    request: Request,
    institution: str = Query(min_length=2, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await verify_captcha(body.captcha_token, request.client.host if request.client else None)
    iid = await _tenant(db, institution, anonymous=True)
    return ok(await GrievanceService(db, None, request, iid).create_anonymous(body), message="Submitted")


@public_router.get(
    "/grievances/track",
    summary="Track an anonymous grievance (ticket + secret; wrong secret → 404)",
    response_model=Envelope[GrvTrack],
    dependencies=[rate_limited("grievance_track", limit=20, window=600)],
)
async def track(
    request: Request,
    ticket_number: str = Query(min_length=3, max_length=30),
    secret: str = Query(min_length=8, max_length=80),
    institution: str = Query(min_length=2, max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    iid = await _tenant(db, institution, anonymous=False)
    return ok(await GrievanceService(db, None, request, iid).track(ticket_number, secret))
