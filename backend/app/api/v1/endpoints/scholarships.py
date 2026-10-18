"""Scholarships — Prompts/12 §12.8 (router included with ``feature_required("fees.scholarships")``).

Pipeline actions are separate routes (verify → recommend → sanction → disburse, reject); sanction also runs as the
``scholarship.sanction`` workflow's approval hook. Fixed paths precede parameterised ones.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required, permission_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.scholarships import (
    DisburseRequest,
    ScholarshipApplicationOut,
    ScholarshipApply,
    ScholarshipDecision,
    ScholarshipIn,
    ScholarshipOut,
)
from app.services.fees.scholarship_service import ScholarshipService
from app.utils.response import ok

router = APIRouter(tags=["scholarships"])

S = "scholarships"
READ = any_permission_required(
    (S, "view"), (S, "view_all"), (S, "create"), (S, "verify"), (S, "sanction"), (S, "disburse"), (S, "approve")
)
SCHEMES = any_permission_required((S, "manage"), (S, "disburse"), (S, "sanction"))
APPLY = any_permission_required((S, "create"), (S, "manage"))
QUEUE = any_permission_required((S, "view_all"), (S, "verify"), (S, "approve"), (S, "sanction"), (S, "disburse"))
VERIFY = permission_required(S, "verify")
RECOMMEND = any_permission_required((S, "approve"), (S, "verify"))
SANCTION = permission_required(S, "sanction")
DISBURSE = permission_required(S, "disburse")
REJECT = any_permission_required((S, "verify"), (S, "approve"), (S, "sanction"))


@router.get("/scholarships", summary="Schemes", response_model=Envelope[list[ScholarshipOut]])
async def list_schemes(
    request: Request, active: bool = False, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScholarshipService(db, principal, request).schemes(active))


@router.post("/scholarships", summary="Create a scheme", response_model=Envelope[ScholarshipOut])
async def create_scheme(
    body: ScholarshipIn, request: Request, principal: Principal = Depends(SCHEMES), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScholarshipService(db, principal, request).save(body), message="Scheme created")


@router.put("/scholarships/{id}", summary="Update a scheme", response_model=Envelope[ScholarshipOut])
async def update_scheme(
    id: uuid.UUID,
    body: ScholarshipIn,
    request: Request,
    principal: Principal = Depends(SCHEMES),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScholarshipService(db, principal, request).save(body, id), message="Scheme updated")


@router.post(
    "/scholarships/{id}/apply",
    summary="Apply (eligibility rules → 422 NOT_ELIGIBLE)",
    response_model=Envelope[ScholarshipApplicationOut],
)
async def apply(
    id: uuid.UUID,
    body: ScholarshipApply,
    request: Request,
    principal: Principal = Depends(APPLY),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScholarshipService(db, principal, request).apply(id, body), message="Application submitted")


@router.get(
    "/scholarship-applications/me",
    summary="My (or my ward's) applications",
    response_model=Envelope[list[ScholarshipApplicationOut]],
)
async def my_applications(
    request: Request, principal: Principal = Depends(READ), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await ScholarshipService(db, principal, request).mine())


@router.get(
    "/scholarship-applications",
    summary="Applications pipeline",
    response_model=Envelope[list[ScholarshipApplicationOut]],
)
async def list_applications(
    request: Request,
    status: str | None = None,
    scope: str | None = None,
    scholarship_id: uuid.UUID | None = None,
    principal: Principal = Depends(QUEUE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows, vis = await ScholarshipService(db, principal, request).list_apps(status, scope, scholarship_id)
    return ok(rows, visibility=vis)


def _action(path: str, summary: str, dep: Any, method: str, message: str) -> None:
    async def handler(
        id: uuid.UUID,
        body: ScholarshipDecision,
        request: Request,
        principal: Principal = Depends(dep),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, Any]:
        svc = ScholarshipService(db, principal, request)
        return ok(await getattr(svc, method)(id, body), message=message)

    handler.__name__ = f"scholarship_{method}"
    router.post(path, summary=summary, response_model=Envelope[ScholarshipApplicationOut])(handler)


_action("/scholarship-applications/{id}/verify", "Verify documents / income", VERIFY, "verify", "Verified")
_action(
    "/scholarship-applications/{id}/recommend",
    "HOD recommendation (starts scholarship.sanction)",
    RECOMMEND,
    "recommend",
    "Recommended",
)
_action("/scholarship-applications/{id}/sanction", "Sanction", SANCTION, "sanction", "Sanctioned")
_action("/scholarship-applications/{id}/reject", "Reject", REJECT, "reject", "Rejected")


@router.post(
    "/scholarship-applications/{id}/disburse",
    summary="Disburse (fee credit / bank transfer / external portal)",
    response_model=Envelope[ScholarshipApplicationOut],
)
async def disburse(
    id: uuid.UUID,
    body: DisburseRequest,
    request: Request,
    principal: Principal = Depends(DISBURSE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await ScholarshipService(db, principal, request).disburse(id, body), message="Disbursed")
