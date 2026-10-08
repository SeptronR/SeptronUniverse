"""Development-only module stub — Prompts/02 §02.11 step 9.

The Phase 02 verification has to prove that a feature-gated route answers ``403 FEATURE_DISABLED`` once the super admin
turns the key off for the tenant before the hostel module exists: ``GET /hostels`` {hostel.core}. Registered only
while ``APP_ENV=development``; **Phase 20 (hostel) deletes this file** together with ``app/features/dev_stubs.py``.

Phase 07 removed the ``POST /students`` stub ({students.core}, the seat-limit proof of step 14): the real
``POST /students`` (``app/api/v1/endpoints/students.py``) enforces the plan's student limit before creating anything.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.core.authz.dependencies import Principal, permission_required
from app.core.features import feature_required
from app.schemas.common import Envelope
from app.utils.response import ok

router = APIRouter(tags=["stubs"])


@router.get(
    "/hostels",
    summary="Hostels (stub until Phase 20 — proves the feature gate)",
    response_model=Envelope[list[dict[str, Any]]],
    dependencies=[feature_required("hostel.core")],
)
async def list_hostels(principal: Principal = Depends(permission_required("hostel", "view"))) -> dict[str, Any]:
    return ok([], message="Hostel management arrives in Phase 20")
