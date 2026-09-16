"""Aggregates module routers — Prompts/00_PREREQUISITE_Project_Setup.md §2.

Every module router is included with ``dependencies=[feature_required("<module>.core")]`` (coding standard 2);
core-key routers (``core.*``) pass through ``feature_required`` unchanged because core keys are never gated.
Phases append ``api_router.include_router(<module>.router, dependencies=[feature_required("<key>")])``.
"""

from fastapi import APIRouter

import app.features  # noqa: F401  (registers every feature key before routers cite them)
from app.api.v1.endpoints import auth
from app.core.features import feature_required

api_router = APIRouter()

api_router.include_router(auth.router, dependencies=[feature_required("core.auth")])
