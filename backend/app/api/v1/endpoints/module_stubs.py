"""Development-only module stubs — Prompts/02 §02.11 steps 9 and 14.

The Phase 02 verification has to prove two cross-cutting rules before any business module exists:

* ``GET /hostels`` {hostel.core} — a feature-gated route answers ``403 FEATURE_DISABLED`` once the super admin turns
  the key off for the tenant (step 9);
* ``POST /students`` {students.core} — a create path that calls ``EntitlementService.enforce_seat_limit`` answers
  ``403 RULE_VIOLATION`` with ``code: SEAT_LIMIT`` when the plan's ``student_limit`` is reached (step 14).

Both are registered only while ``APP_ENV=development`` and both are **replaced** by the real modules: Phase 07
(students) and Phase 20 (hostel) delete this file together with ``app/features/dev_stubs.py``.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz.dependencies import Principal, permission_required
from app.core.features import feature_required
from app.db.session import get_db
from app.schemas.common import Envelope
from app.services.entitlement_service import EntitlementService
from app.utils.response import ok

router = APIRouter(tags=["stubs"])


class StudentStubCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


@router.get(
    "/hostels",
    summary="Hostels (stub until Phase 20 — proves the feature gate)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=[feature_required("hostel.core")],
)
async def list_hostels(principal: Principal = Depends(permission_required("hostel", "view"))) -> dict[str, Any]:
    return ok([], message="Hostel management arrives in Phase 20")


@router.post(
    "/students",
    status_code=201,
    summary="Create a student (stub until Phase 07 — proves the seat limit)",
    response_model=Envelope[dict[str, Any]],
    dependencies=[feature_required("students.core")],
)
async def create_student(
    body: StudentStubCreate,
    request: Request,
    principal: Principal = Depends(permission_required("students", "create")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await EntitlementService(db, principal).enforce_seat_limit("student")
    return ok(
        {"first_name": body.first_name, "last_name": body.last_name}, message="Student records arrive in Phase 07"
    )
