"""Aggregates module routers — Prompts/00_PREREQUISITE_Project_Setup.md §2.

Every module router is included with ``dependencies=[feature_required("<module>.core")]`` (coding standard 2);
core-key routers (``core.*``) pass through ``feature_required`` unchanged because core keys are never gated.
Phases append ``api_router.include_router(<module>.router, dependencies=[feature_required("<key>")])``.

Phase 01: ``platform`` (public config / read-only / mobile config — public routes, the write carries its own feature
dependency), ``jobs`` {core.background_jobs}, ``search`` {search.global}, ``help`` {platform.help_center},
``feedback`` {platform.in_app_feedback}; ``dev`` only when ``APP_ENV=development``.
"""

from fastapi import APIRouter

import app.features  # noqa: F401  (registers every feature key before routers cite them)
from app.api.v1.endpoints import auth, feedback, help, jobs, platform, search
from app.core.config import settings
from app.core.features import feature_required

api_router = APIRouter()

api_router.include_router(auth.router, dependencies=[feature_required("core.auth")])
api_router.include_router(platform.router)
api_router.include_router(jobs.router, dependencies=[feature_required("core.background_jobs")])
api_router.include_router(search.router, dependencies=[feature_required("search.global")])
api_router.include_router(help.router, dependencies=[feature_required("platform.help_center")])
api_router.include_router(feedback.router, dependencies=[feature_required("platform.in_app_feedback")])

if settings.APP_ENV == "development":
    from app.api.v1.endpoints import dev

    api_router.include_router(dev.router, dependencies=[feature_required("core.background_jobs")])
