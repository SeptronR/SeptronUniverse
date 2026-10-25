"""Discipline — Prompts/27 §27.8 {discipline.core}: cases (report / inquiry / notice / hearing / decide / close),
the subject's view (my cases, statement, appeal), appeal decisions and the statutory register. Visibility (subject
self, committee, department, college, all) is narrowed by the service.
"""

import csv
import io
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, any_permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.schemas.discipline import (
    DiscAppealCreate,
    DiscAppealDecision,
    DiscCaseCreate,
    DiscCaseOut,
    DiscDecision,
    DiscHearing,
    DiscInquiry,
    DiscNotice,
    DiscRegisterRow,
    DiscStatement,
)
from app.services.student_support.discipline_service import DisciplineService
from app.utils.response import ok

router = APIRouter(tags=["discipline"])

D = "discipline"
READ = any_permission_required((D, "manage"), (D, "decide"), (D, "view_all"), (D, "view"), (D, "appeal"))
MANAGE = any_permission_required((D, "manage"), (D, "create"))
DECIDE = any_permission_required((D, "decide"), (D, "manage"))
APPEAL = any_permission_required((D, "appeal"))
REGISTER = any_permission_required((D, "view_all"), (D, "manage"))
# students / staff reach their own cases through the portal grants they already hold
SELF = any_permission_required(
    (D, "view"), (D, "manage"), ("students", "self"), ("students", "view"), ("leaves", "self"), ("mentoring", "self")
)

CORE = [feature_required("discipline.core")]


def _vis(data: Any, svc: DisciplineService) -> dict[str, Any]:
    res = ok(data)
    res["meta"]["visibility"] = svc.visibility(self_tab=True, own_tab=True)
    return res


@router.get(
    "/discipline/cases",
    summary="Disciplinary cases (ScopeTabs)",
    response_model=Envelope[list[DiscCaseOut]],
    dependencies=CORE,
)
async def cases(
    request: Request,
    status: str | None = None,
    subject_type: str | None = None,
    scope: str | None = None,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    svc = DisciplineService(db, principal, request)
    return _vis(await svc.list_cases(status, subject_type, scope), svc)


@router.post(
    "/discipline/cases",
    status_code=201,
    summary="Report a case",
    response_model=Envelope[DiscCaseOut],
    dependencies=CORE,
)
async def report(
    body: DiscCaseCreate, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).create(body), message="Reported")


@router.get(
    "/discipline/cases/me",
    summary="My cases (subject / ward)",
    response_model=Envelope[list[DiscCaseOut]],
    dependencies=CORE,
)
async def my_cases(
    request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).mine())


@router.get(
    "/discipline/register",
    summary="Discipline register (?format=csv)",
    response_model=Envelope[list[DiscRegisterRow]],
    dependencies=CORE,
)
async def register(
    request: Request,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    subject_type: str | None = None,
    format: str | None = None,
    principal: Principal = Depends(REGISTER),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await DisciplineService(db, principal, request).register(date_from, date_to, subject_type)
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(DiscRegisterRow.model_fields.keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r.model_dump(mode="json"))
        return Response(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="discipline-register.csv"'},
        )
    return ok(rows)


@router.get("/discipline/cases/{id}", summary="Case file", response_model=Envelope[DiscCaseOut], dependencies=CORE)
async def get(
    id: uuid.UUID, request: Request, principal: Principal = Depends(SELF), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).get(id))


@router.post(
    "/discipline/cases/{id}/inquiry",
    summary="Start inquiry (committee, notice)",
    response_model=Envelope[DiscCaseOut],
    dependencies=CORE,
)
async def inquiry(
    id: uuid.UUID,
    body: DiscInquiry,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).inquiry(id, body))


@router.post(
    "/discipline/cases/{id}/notice",
    summary="Send a notice (subject + guardians)",
    response_model=Envelope[DiscCaseOut],
    dependencies=CORE,
)
async def notice(
    id: uuid.UUID,
    body: DiscNotice,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).notice(id, body))


@router.post(
    "/discipline/cases/{id}/hearing",
    summary="Schedule / record a hearing",
    response_model=Envelope[DiscCaseOut],
    dependencies=CORE,
)
async def hearing(
    id: uuid.UUID,
    body: DiscHearing,
    request: Request,
    principal: Principal = Depends(READ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).hearing(id, body))


@router.post(
    "/discipline/cases/{id}/decide",
    summary="Decide with sanctions (suspension / expulsion → principal via discipline.case)",
    response_model=Envelope[DiscCaseOut],
    dependencies=CORE,
)
async def decide(
    id: uuid.UUID,
    body: DiscDecision,
    request: Request,
    principal: Principal = Depends(DECIDE),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).decide(id, body))


@router.post(
    "/discipline/cases/{id}/close", summary="Close the case", response_model=Envelope[DiscCaseOut], dependencies=CORE
)
async def close(
    id: uuid.UUID, request: Request, principal: Principal = Depends(MANAGE), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).close(id), message="Closed")


@router.post(
    "/discipline/cases/{id}/statement",
    summary="Submit my statement",
    response_model=Envelope[DiscCaseOut],
    dependencies=CORE,
)
async def statement(
    id: uuid.UUID,
    body: DiscStatement,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).statement(id, body), message="Submitted")


@router.post(
    "/discipline/cases/{id}/appeal",
    summary="Appeal within the window",
    response_model=Envelope[DiscCaseOut],
    dependencies=CORE,
)
async def appeal(
    id: uuid.UUID,
    body: DiscAppealCreate,
    request: Request,
    principal: Principal = Depends(SELF),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).appeal(id, body), message="Appeal filed")


@router.post(
    "/discipline/cases/{id}/appeal/decide",
    summary="Decide the appeal (uphold / modify / revoke with reversals)",
    response_model=Envelope[DiscCaseOut],
    dependencies=CORE,
)
async def appeal_decide(
    id: uuid.UUID,
    body: DiscAppealDecision,
    request: Request,
    principal: Principal = Depends(APPEAL),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return ok(await DisciplineService(db, principal, request).decide_appeal(id, body))
